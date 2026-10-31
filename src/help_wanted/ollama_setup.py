"""Ollama setup for the Contributor's machine."""

import asyncio
import json
import os
import platform
import shutil
import subprocess
import time
from typing import Never
from urllib.parse import urlsplit

import httpx
from rich.console import Console
from rich.prompt import Confirm
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn


class SetupError(RuntimeError):
    """Setup could not finish; the message gives plain-words next steps."""


async def prepare_ollama(*, console: Console | None = None) -> str:
    """Return the chosen model, or raise SetupError with actionable next steps.

    Await this from the setup stage. Blocking prompts, HTTP and downloads run
    in a worker thread so the pipeline's event loop remains available.
    The caller must pass the returned model to its model adapter; this function
    does not change environment variables.
    """
    return await asyncio.to_thread(_prepare_ollama, console)


def _prepare_ollama(console: Console | None) -> str:
    console = console or Console()
    binary = shutil.which("ollama")
    if not binary:
        message = "Please install Ollama from https://ollama.com/download, then run Help Wanted again."
        console.print(message)
        raise SetupError(message)
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    try:
        parsed = urlsplit(host)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid Ollama address")
        httpx.URL(host)
    except (ValueError, httpx.InvalidURL):
        _stop(console, "Set OLLAMA_HOST to an Ollama address such as http://localhost:11434, then try again.")
    with httpx.Client(base_url=host, timeout=5, trust_env=False) as client:
        try:
            downloaded = _ready_models(client, binary, host, console)
        except (httpx.HTTPError, ValueError):
            _stop(console, "Ollama could not list its models. Open or update Ollama, check OLLAMA_HOST, then try again.")
        model = os.getenv("HELP_WANTED_MODEL", "").strip()
        if not model:
            console.print(
                "You can run Gemma locally on this machine or use Ollama cloud. "
                "Cloud sends model inputs to Ollama's service and requires "
                "internet access and an Ollama account."
            )
            model = (
                "gemma4:cloud"
                if Confirm.ask("Would you like to use Ollama cloud?", default=False, console=console)
                else _local_model(console)
            )
        if "cloud" in model:
            console.print(
                "The cloud model sends model inputs to Ollama's service and requires "
                "internet access and an Ollama account."
            )
            _ensure_cloud_signin(client, binary, console)
        names = {item.get("name") for item in downloaded.get("models", [])}
        if model not in names and f"{model}:latest" not in names:
            try:
                _pull(client, model, console)
            except (httpx.HTTPError, ValueError, TypeError):
                _stop(
                    console,
                    "Ollama could not finish the download. Check your internet connection and free disk space, "
                    f"then run `ollama pull {model}` and try again. "
                    "For cloud models, run `ollama signin` first.",
                )
    return model


def _stop(console: Console, message: str) -> Never:
    console.print(message, markup=False)
    raise SetupError(message) from None


def _cloud_signed_in(client: httpx.Client, console: Console, *, timeout: float = 5) -> bool:
    try:
        response = client.post("/api/me", timeout=timeout)
        if response.status_code == 401:
            return False
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("Invalid Ollama account")
    except (httpx.HTTPError, ValueError):
        _stop(console, "Ollama could not check your sign-in. Check your internet connection and update Ollama, then try again.")
    return True


def _ensure_cloud_signin(client: httpx.Client, binary: str, console: Console) -> None:
    if _cloud_signed_in(client, console):
        console.print("Signed in to Ollama.")
        return
    console.print(
        "Opening Ollama sign-in in your browser. Finish signing in there; "
        "if the browser does not open, use the link printed by Ollama. "
        "Help Wanted will wait up to 3 minutes."
    )
    try:
        # Ollama opens its account-linking URL and prints it as a browser fallback.
        # A zero exit status only means it opened sign-in, not that it finished.
        subprocess.run([binary, "signin"], check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        _stop(console, "Ollama could not open sign-in. Run `ollama signin`, finish in your browser, then try Help Wanted again.")
    deadline = time.monotonic() + 180
    for _ in range(180):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if _cloud_signed_in(client, console, timeout=min(5, remaining)):
            console.print("Signed in to Ollama.")
            return
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    _stop(console, "Ollama sign-in did not finish within 3 minutes. Finish signing in in your browser, then run Help Wanted again.")


def _tags(client: httpx.Client, *, timeout: float = 5) -> dict:
    response = client.get("/api/tags", timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("Invalid model list")
    if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in data["models"]):
        raise ValueError("Invalid model entry")
    return data


def _ready_models(client: httpx.Client, binary: str, host: str, console: Console) -> dict:
    try:
        return _tags(client)
    except httpx.TransportError:
        pass
    manual_fix = "Open Ollama or run `ollama serve` in another terminal, then try again."
    console.print("Ollama is not running or cannot be reached.")
    if urlsplit(host).hostname not in {"localhost", "127.0.0.1", "::1"}:
        _stop(console, "Check OLLAMA_HOST and start Ollama on that machine, then try again.")
    if not Confirm.ask("May I start Ollama on this machine?", default=False, console=console):
        _stop(console, manual_fix)
    try:
        subprocess.Popen(
            [binary, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        _stop(console, manual_fix)
    deadline = time.monotonic() + 15
    for _ in range(30):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            return _tags(client, timeout=min(1, remaining))
        except httpx.TransportError:
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    _stop(console, "Ollama did not become ready within 15 seconds. " + manual_fix)


def _pull(client: httpx.Client, model: str, console: Console) -> None:
    console.print(f"Downloading {model}. This can take a while on the first run.", markup=False)
    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), DownloadColumn(),
        console=console,
    ) as progress:
        tasks = {}
        success = False
        with client.stream(
            "POST", "/api/pull", json={"model": model, "stream": True},
            timeout=httpx.Timeout(300, connect=5),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict) or event.get("error"):
                    raise ValueError("Ollama reported a download error")
                if event.get("status") == "success":
                    success = True
                if event.get("total"):
                    digest = event.get("digest", "model")
                    if digest not in tasks:
                        tasks[digest] = progress.add_task("Download", total=event["total"])
                    progress.update(tasks[digest], completed=event.get("completed", 0))
        if not success:
            raise ValueError("Download ended before success")
    console.print("Download complete.")


def _local_model(console: Console) -> str:
    memory = _memory_gb()
    if memory is None:
        return "gemma4:e4b"
    if memory >= 32:
        return "gemma4:26b"
    if memory >= 16:
        return "gemma4:12b"
    if memory >= 12:
        return "gemma4:e4b"
    if memory >= 8:
        return "gemma4:e2b"
    console.print(
        "Local models need at least 8 GB of memory. Ollama cloud can run the model "
        "elsewhere; it needs internet access and an Ollama account."
    )
    if Confirm.ask("Use gemma4:cloud instead?", default=False, console=console):
        return "gemma4:cloud"
    _stop(console, "Use a machine with at least 8 GB of memory, or try again and choose Ollama cloud.")


def _memory_gb() -> float | None:
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True,
                text=True, check=True, timeout=5,
            )
            return int(result.stdout.strip()) / 1024**3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None
