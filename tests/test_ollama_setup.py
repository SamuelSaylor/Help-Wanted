"""Exercise the setup guide without starting processes or downloading models."""

import asyncio
from io import StringIO
import json
import subprocess
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
    monkeypatch.setattr("rich.prompt.Confirm.ask", Mock(return_value=False))
    client_type = httpx.Client
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/api/me":
            assert request.method == "POST"
            return httpx.Response(200, json={"name": "contributor"})
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


def test_contributor_can_choose_cloud_on_a_capable_machine(monkeypatch):
    memory = Mock(return_value=Mock(stdout=str(32 * 1024**3)))
    monkeypatch.setattr("subprocess.run", memory)
    prompt = Mock(return_value=True)
    monkeypatch.setattr("rich.prompt.Confirm.ask", prompt)
    output = StringIO()

    assert prepare_ollama(Console(file=output, width=120)) == "gemma4:cloud"
    prompt.assert_called_once()
    assert "cloud" in prompt.call_args.args[0].lower()
    assert prompt.call_args.kwargs["default"] is False
    memory.assert_not_called()
    text = output.getvalue()
    assert "sends model inputs to Ollama's service" in text
    assert "internet access and an Ollama account" in text
    assert "Signed in to Ollama" in text
    assert "ollama signin" not in text


@pytest.mark.parametrize(("ram_gb", "expected"), [
    (8, "gemma4:e2b"), (12, "gemma4:e4b"),
    (16, "gemma4:12b"), (32, "gemma4:26b"), (64, "gemma4:26b"),
])
def test_chooses_a_downloaded_model_that_fits_ram(monkeypatch, isolated_machine, ram_gb, expected):
    monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(stdout=str(ram_gb * 1024**3))))
    prompt = Mock(return_value=False)
    monkeypatch.setattr("rich.prompt.Confirm.ask", prompt)
    output = StringIO()
    assert prepare_ollama(Console(file=output)) == expected
    prompt.assert_called_once()
    assert "cloud" in prompt.call_args.args[0].lower()
    assert [request.url.path for request in isolated_machine[1]] == ["/api/tags"]
    assert "Signed in" not in output.getvalue()
    assert "ollama signin" not in output.getvalue()


def test_respects_model_and_host_overrides(monkeypatch, isolated_machine):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:12b")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:22434")
    assert prepare_ollama(Console(file=StringIO())) == "gemma4:12b"
    assert str(isolated_machine[1][0].url) == "http://127.0.0.1:22434/api/tags"


@pytest.mark.parametrize("model", ["gemma4:e2b", "gemma4:12b", "gemma4:cloud"])
def test_explicit_model_bypasses_choice_and_memory_detection(monkeypatch, model):
    monkeypatch.setenv("HELP_WANTED_MODEL", model)
    monkeypatch.setattr("rich.prompt.Confirm.ask", Mock(side_effect=AssertionError("unexpected prompt")))
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("unexpected memory check")))
    assert prepare_ollama(Console(file=StringIO())) == model


def test_starts_a_stopped_local_server_only_after_permission(monkeypatch, isolated_machine):
    handler, _ = isolated_machine
    handler.side_effect = [httpx.ConnectError("offline"), httpx.Response(200, json={
        "models": [{"name": "gemma4:e2b"}],
    })]
    prompt = Mock(side_effect=[True, False])
    start = Mock(return_value=Mock())
    monkeypatch.setattr("rich.prompt.Confirm.ask", prompt)
    monkeypatch.setattr("subprocess.Popen", start)
    assert prepare_ollama(Console(file=StringIO())) == "gemma4:e2b"
    assert prompt.call_count == 2
    assert "start Ollama" in prompt.call_args_list[0].args[0]
    assert "cloud" in prompt.call_args_list[1].args[0].lower()
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
def test_low_memory_checks_sign_in_only_after_cloud_is_accepted(monkeypatch, isolated_machine, accept):
    monkeypatch.setattr("subprocess.run", Mock(return_value=Mock(stdout=str(4 * 1024**3))))
    prompt = Mock(side_effect=[False, accept])
    monkeypatch.setattr("rich.prompt.Confirm.ask", prompt)
    output = StringIO()
    if accept:
        assert prepare_ollama(Console(file=output)) == "gemma4:cloud"
    else:
        with pytest.raises(SetupError, match="8 GB"):
            prepare_ollama(Console(file=output))
    assert ("Signed in to Ollama" in output.getvalue()) is accept
    assert "ollama signin" not in output.getvalue()
    assert [request.url.path for request in isolated_machine[1]] == (
        ["/api/tags", "/api/me"] if accept else ["/api/tags"]
    )
    assert prompt.call_count == 2
    assert "instead" in prompt.call_args.args[0]


def test_signed_in_cloud_contributor_continues_without_sign_in(monkeypatch, isolated_machine):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:cloud")
    signin = Mock(side_effect=AssertionError("unexpected sign-in"))
    monkeypatch.setattr("subprocess.run", signin)
    output = StringIO()
    assert prepare_ollama(Console(file=output)) == "gemma4:cloud"
    assert "Signed in to Ollama" in output.getvalue()
    assert "ollama signin" not in output.getvalue()
    signin.assert_not_called()
    assert [request.url.path for request in isolated_machine[1]] == ["/api/tags", "/api/me"]


def test_signed_out_cloud_contributor_is_signed_in_before_continuing(monkeypatch, isolated_machine):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:cloud")
    handler, _ = isolated_machine
    handler.side_effect = [
        httpx.Response(200, json={"models": []}),
        httpx.Response(401, json={"error": "unauthorized"}),
        httpx.Response(401, json={"error": "unauthorized"}),
        httpx.Response(200, json={"name": "contributor"}),
        httpx.Response(200, text='{"status":"success"}'),
    ]
    signin = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr("subprocess.run", signin)
    monkeypatch.setattr("time.sleep", Mock())
    output = StringIO()

    assert prepare_ollama(Console(file=output, width=120)) == "gemma4:cloud"
    signin.assert_called_once_with(["/mock/ollama", "signin"], check=True, timeout=30)
    assert "browser" in output.getvalue()
    assert "Signed in to Ollama" in output.getvalue()
    assert [call.args[0].url.path for call in handler.call_args_list] == [
        "/api/tags", "/api/me", "/api/me", "/api/me", "/api/pull",
    ]
    for call in handler.call_args_list[1:4]:
        assert call.args[0].method == "POST"


@pytest.mark.parametrize("failure", [
    OSError("private process details"),
    subprocess.CalledProcessError(1, "ollama", output="private process details"),
    subprocess.TimeoutExpired("ollama", 30, output="private process details"),
])
def test_sign_in_command_failure_stops_setup_with_safe_instructions(monkeypatch, isolated_machine, failure):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:cloud")
    handler, _ = isolated_machine
    handler.side_effect = [
        httpx.Response(200, json={"models": []}), httpx.Response(401),
    ]
    monkeypatch.setattr("subprocess.run", Mock(side_effect=failure))
    output = StringIO()

    with pytest.raises(SetupError, match="ollama signin") as error:
        prepare_ollama(Console(file=output))
    assert "private process details" not in str(error.value)
    assert "Signed in to Ollama" not in output.getvalue()
    assert handler.call_count == 2


def test_unfinished_browser_sign_in_has_a_bounded_wait(monkeypatch, isolated_machine):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:cloud")
    handler, _ = isolated_machine
    handler.side_effect = lambda request: (
        httpx.Response(200, json={"models": []})
        if request.url.path == "/api/tags" else httpx.Response(401)
    )
    signin = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr("subprocess.run", signin)
    monkeypatch.setattr("time.sleep", Mock())
    output = StringIO()

    with pytest.raises(SetupError, match="within 3 minutes"):
        prepare_ollama(Console(file=output))
    signin.assert_called_once()
    assert handler.call_count <= 182
    assert "Signed in to Ollama" not in output.getvalue()
    assert all(call.args[0].url.path != "/api/pull" for call in handler.call_args_list)


@pytest.mark.parametrize("response", [
    httpx.Response(503, text="private account details"),
    httpx.Response(404), httpx.Response(200, text="invalid"),
    httpx.Response(200, json={}), httpx.Response(200, json={"name": " "}),
    httpx.Response(200, json={"name": None}), httpx.Response(200, json=[]),
    httpx.ReadTimeout("private account details"),
])
def test_unavailable_authentication_does_not_launch_sign_in(monkeypatch, isolated_machine, response):
    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:cloud")
    handler, _ = isolated_machine
    handler.side_effect = [httpx.Response(200, json={"models": []}), response]
    signin = Mock(side_effect=AssertionError("unexpected sign-in"))
    monkeypatch.setattr("subprocess.run", signin)
    output = StringIO()

    with pytest.raises(SetupError, match="check your sign-in") as error:
        prepare_ollama(Console(file=output))
    signin.assert_not_called()
    assert "private account details" not in str(error.value)
    assert "Signed in to Ollama" not in output.getvalue()
    assert handler.call_count == 2


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
        httpx.Response(200, json={"models": []}),
        httpx.Response(200, json={"name": "contributor"}), httpx.Response(401),
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
