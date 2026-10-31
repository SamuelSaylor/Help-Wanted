"""GitHub sign-in for public, read-only discovery."""

import asyncio
import getpass
import os
import secrets
import stat
import subprocess
import time
import webbrowser
import warnings
from pathlib import Path
from urllib.parse import urlencode

import httpx
from rich.console import Console
from help_wanted.theme import themed_console

GITHUB_CLIENT_ID = "Ov23limUFG1pepZFGN7q"
DEVICE_URL = "https://github.com/login/device"
TOKEN_URL = "https://github.com/settings/personal-access-tokens/new?" + urlencode({
    "name": "Help Wanted", "description": "Read public projects and issues for Help Wanted",
    "expires_in": "30",
})


class AuthError(RuntimeError):
    """A sign-in problem safe to show without exposing credentials."""


def _manual_token(console: Console) -> str:
    console.print("You can create a fine-grained token instead. Keep public repositories (read-only) and do not add permissions.")
    console.print(TOKEN_URL, markup=False, soft_wrap=True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            token = getpass.getpass("Paste your GitHub token (hidden): ").strip()
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        raise AuthError("Sign-in stopped. Run Help Wanted again when you are ready to sign in.") from None
    if not token:
        raise AuthError("No GitHub token was entered. Run Help Wanted again to sign in.")
    return token


def _save_token(token: str, console: Console) -> None:
    directory = Path.home() / ".config" / "help-wanted"
    temporary = f".token-{secrets.token_hex(16)}"
    directory_fd = None
    try:
        config = directory.parent
        config.mkdir(mode=0o700, exist_ok=True)
        if config.is_symlink():
            raise OSError("Unsafe configuration folder")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if os.fstat(directory_fd).st_uid != os.getuid():
            raise OSError("Configuration folder has a different owner")
        os.fchmod(directory_fd, 0o700)
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory_fd,
        )
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(token + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, "token", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    except OSError:
        console.print("You are signed in, but we could not save your sign-in safely. You may need to sign in next time.")
    finally:
        if directory_fd is not None:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)


def _device_token(console: Console) -> str:
    with httpx.Client(timeout=15, headers={"Accept": "application/json"}) as client:
        response = client.post(
            "https://github.com/login/device/code", data={"client_id": GITHUB_CLIENT_ID},
        )
        response.raise_for_status()
        device = response.json()
        console.print(f"Open {DEVICE_URL} and enter {device['user_code']}", markup=False)
        try:
            opened = webbrowser.open(DEVICE_URL)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            console.print("We could not open your browser. Open the link above in a browser to continue.")
        interval = max(1, int(device.get("interval", 5)))
        lifetime = min(900, max(0, int(device["expires_in"])))
        deadline = time.monotonic() + lifetime
        waited = 0
        while waited + interval < lifetime and time.monotonic() + interval < deadline:
            time.sleep(interval)
            waited += interval
            if time.monotonic() >= deadline:
                break
            response = client.post(
                "https://github.com/login/oauth/access_token",
                data={"client_id": GITHUB_CLIENT_ID, "device_code": device["device_code"],
                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
                timeout=min(15, deadline - time.monotonic()),
            )
            response.raise_for_status()
            result = response.json()
            if token := result.get("access_token"):
                if not isinstance(token, str) or any(char.isspace() for char in token):
                    raise AuthError("GitHub sent a sign-in reply we could not read.")
                return token
            error = result.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error == "access_denied":
                raise AuthError("GitHub sign-in was declined.")
            if error == "expired_token":
                raise AuthError("The GitHub sign-in code has expired.")
            raise AuthError("GitHub could not complete this sign-in.")
        raise AuthError("The GitHub sign-in code has expired.")


def _saved_token() -> str:
    path = Path.home() / ".config" / "help-wanted" / "token"
    try:
        if path.parent.is_symlink() or path.parent.parent.is_symlink():
            return ""
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                return ""
            return source.read(16384).strip()
    except (OSError, UnicodeError):
        return ""


def _get_github_token(console: Console | None = None) -> str:
    """Resolve sign-in in a worker so polling does not block the event loop."""
    console = console if console is not None else themed_console()
    if token := os.environ.get("GITHUB_TOKEN", "").strip():
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10,
            check=False,
        )
        if result.returncode == 0 and (token := result.stdout.strip()):
            return token
    except (OSError, subprocess.TimeoutExpired):
        pass
    if token := _saved_token():
        return token
    try:
        token = _device_token(console)
    except KeyboardInterrupt:
        raise AuthError("Sign-in stopped. Run Help Wanted again when you are ready to sign in.") from None
    except AuthError as error:
        console.print(str(error))
        token = ""
    except httpx.HTTPError:
        console.print("We could not reach GitHub to finish sign-in. Check your internet connection.")
        token = ""
    except (ValueError, KeyError, TypeError, AttributeError):
        console.print("GitHub sent a sign-in reply we could not read.")
        token = ""
    if not token:
        token = _manual_token(console)
    _save_token(token, console)
    return token


async def get_github_token(*, console: Console | None = None) -> str:
    """Return a token or raise AuthError with a message safe to show.

    Uses GITHUB_TOKEN, gh auth token, then an owner-only saved token before
    prompting for device sign-in or a hidden manual token. Newly entered tokens
    are saved atomically to ~/.config/help-wanted/token (mode 600). Tokens from
    the environment and GitHub CLI are not copied to disk. No scopes requested.
    """
    return await asyncio.to_thread(_get_github_token, console)
