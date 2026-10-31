"""Exercise the setup guide without starting processes or downloading models."""

import asyncio
from io import StringIO
import json
from unittest.mock import Mock

import httpx
import pytest
from rich.console import Console

from help_wanted.ollama_setup import SetupError, prepare_ollama as _prepare_ollama


def prepare_ollama(console):
    """Drive the public async seam from ordinary pytest tests."""
    return asyncio.run(_prepare_ollama(console=console))


@pytest.fixture(autouse=True)
def isolated_machine(monkeypatch):
    monkeypatch.delenv("HELP_WANTED_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: "/mock/ollama")
    monkeypatch.setattr("subprocess.Popen", Mock(side_effect=AssertionError("unexpected process")))
    monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(stdout=str(8 * 1024**3))))
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("rich.prompt.Confirm.ask", Mock(side_effect=AssertionError("unexpected prompt")))
    client_type = httpx.Client
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [
            {"name": f"gemma4:{tag}"} for tag in ("e2b", "e4b", "12b", "26b", "cloud")
        ]})

    handler = Mock(side_effect=respond)
    monkeypatch.setattr("httpx.Client", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(handler),
    ))
    return handler, requests


def test_missing_ollama_explains_how_to_install(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    output = StringIO()
    with pytest.raises(SetupError, match="https://ollama.com/download"):
        prepare_ollama(Console(file=output))
    assert "install" in output.getvalue().lower()


@pytest.mark.parametrize(("ram_gb", "expected"), [
    (8, "gemma4:e2b"), (12, "gemma4:e4b"),
    (16, "gemma4:12b"), (32, "gemma4:26b"), (64, "gemma4:26b"),
])
def test_chooses_a_downloaded_model_that_fits_ram(monkeypatch, ram_gb, expected):
    monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(stdout=str(ram_gb * 1024**3))))
    assert prepare_ollama(Console(file=StringIO())) == expected


def test_respects_model_and_host_overrides(monkeypatch, isolated_machine):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:12b")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:22434")
    assert prepare_ollama(Console(file=StringIO())) == "gemma4:12b"
    assert str(isolated_machine[1][0].url) == "http://127.0.0.1:22434/api/tags"


def test_starts_a_stopped_local_server_only_after_permission(monkeypatch, isolated_machine):
    handler, _ = isolated_machine
    handler.side_effect = [httpx.ConnectError("offline"), httpx.Response(200, json={
        "models": [{"name": "gemma4:e2b"}],
    })]
    prompt = Mock(return_value=True)
    start = Mock(return_value=Mock())
    monkeypatch.setattr("rich.prompt.Confirm.ask", prompt)
    monkeypatch.setattr("subprocess.Popen", start)
    assert prepare_ollama(Console(file=StringIO())) == "gemma4:e2b"
    prompt.assert_called_once()
    assert start.call_args.args[0] == ["/mock/ollama", "serve"]


@pytest.mark.parametrize("remote", [False, True])
def test_unavailable_server_explains_manual_fix_without_unapproved_start(monkeypatch, isolated_machine, remote):
    isolated_machine[0].side_effect = httpx.ConnectError("offline")
    prompt = Mock(return_value=False)
    monkeypatch.setattr("rich.prompt.Confirm.ask", prompt)
    if remote:
        monkeypatch.setenv("OLLAMA_HOST", "https://ollama.example.test")
    with pytest.raises(SetupError, match="ollama serve|OLLAMA_HOST"):
        prepare_ollama(Console(file=StringIO()))
    assert prompt.call_count == (0 if remote else 1)


def test_server_start_has_a_bounded_wait(monkeypatch, isolated_machine):
    isolated_machine[0].side_effect = httpx.ConnectError("offline")
    monkeypatch.setattr("rich.prompt.Confirm.ask", Mock(return_value=True))
    monkeypatch.setattr("subprocess.Popen", Mock(return_value=Mock()))
    monkeypatch.setattr("time.sleep", Mock())
    with pytest.raises(SetupError, match="ollama serve"):
        prepare_ollama(Console(file=StringIO()))
    assert isolated_machine[0].call_count <= 31


@pytest.mark.parametrize("accept", [False, True])
def test_low_memory_offers_cloud_and_explains_sign_in(monkeypatch, accept):
    monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(stdout=str(4 * 1024**3))))
    monkeypatch.setattr("rich.prompt.Confirm.ask", Mock(return_value=accept))
    output = StringIO()
    if accept:
        assert prepare_ollama(Console(file=output)) == "gemma4:cloud"
    else:
        with pytest.raises(SetupError, match="8 GB"):
            prepare_ollama(Console(file=output))
    assert "ollama signin" in output.getvalue()


def test_explicit_cloud_override_explains_sign_in(monkeypatch):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:cloud")
    output = StringIO()
    assert prepare_ollama(Console(file=output)) == "gemma4:cloud"
    assert "ollama signin" in output.getvalue()


def test_missing_model_downloads_with_streamed_progress(isolated_machine):
    handler, _ = isolated_machine
    handler.side_effect = [
        httpx.Response(200, json={"models": []}),
        httpx.Response(200, text='\n'.join([
            '{"status":"pulling manifest"}',
            '{"status":"pulling layer","digest":"sha256:a","total":100,"completed":25}',
            '{"status":"pulling layer","digest":"sha256:a","total":100,"completed":100}',
            '{"status":"success"}',
        ])),
    ]
    output = StringIO()
    assert prepare_ollama(Console(file=output)) == "gemma4:e2b"
    pull = handler.call_args.args[0]
    assert pull.method == "POST"
    assert pull.url.path == "/api/pull"
    assert json.loads(pull.content) == {"model": "gemma4:e2b", "stream": True}
    assert "Download" in output.getvalue()


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="private server details"),
    httpx.Response(200, text='{"error":"private server details"}'),
    httpx.Response(200, text='{"status":"pulling manifest"}'),
    httpx.Response(200, text='not json'),
    httpx.Response(200, text='[]'),
    httpx.ReadTimeout("private server details"),
])
def test_download_failures_give_plain_retry_instructions(isolated_machine, response):
    isolated_machine[0].side_effect = [httpx.Response(200, json={"models": []}), response]
    output = StringIO()
    with pytest.raises(SetupError, match="ollama pull") as error:
        prepare_ollama(Console(file=output))
    assert "private server details" not in str(error.value)
    assert "Download complete" not in output.getvalue()


def test_cloud_authorization_failure_explains_sign_in(monkeypatch, isolated_machine):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:cloud")
    isolated_machine[0].side_effect = [
        httpx.Response(200, json={"models": []}), httpx.Response(401),
    ]
    with pytest.raises(SetupError, match="ollama signin"):
        prepare_ollama(Console(file=StringIO()))


@pytest.mark.parametrize("response", [
    httpx.Response(503), httpx.Response(200, text="invalid"),
    httpx.Response(200, json=[]), httpx.Response(200, json={"models": [None]}),
])
def test_unexpected_server_responses_give_plain_next_steps(isolated_machine, response):
    isolated_machine[0].side_effect = [response]
    with pytest.raises(SetupError, match="Ollama"):
        prepare_ollama(Console(file=StringIO()))


@pytest.mark.parametrize("host", ["http://localhost:bad", "http://[broken", "ftp://localhost"])
def test_invalid_host_gives_plain_configuration_instructions(monkeypatch, host):
    monkeypatch.setenv("OLLAMA_HOST", host)
    with pytest.raises(SetupError, match="OLLAMA_HOST"):
        prepare_ollama(Console(file=StringIO()))
