import asyncio
import getpass
import subprocess
import warnings
from io import StringIO
from unittest.mock import Mock

import httpx
import pytest
from rich.console import Console

from help_wanted.auth import AuthError, get_github_token as async_get_github_token


def get_github_token(console):
    return asyncio.run(async_get_github_token(console=console))

HTTPClient = httpx.Client

@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("subprocess.run", Mock(side_effect=FileNotFoundError))
    monkeypatch.setattr("webbrowser.open", Mock(return_value=True))
    monkeypatch.setattr("httpx.Client", Mock(side_effect=AssertionError("Unexpected network")))
    monkeypatch.setattr("getpass.getpass", Mock(side_effect=AssertionError("Unexpected prompt")))
    return tmp_path, Console(file=StringIO(), markup=False)


def test_environment_token_has_priority_without_prompting(isolated, monkeypatch):
    home, console = isolated
    monkeypatch.setenv("GITHUB_TOKEN", " env-token ")
    monkeypatch.setattr("subprocess.run", Mock(side_effect=AssertionError("Must not run gh")))
    assert get_github_token(console) == "env-token"
    assert "env-token" not in console.file.getvalue()


def test_gh_token_is_used_before_saved_token(isolated, monkeypatch):
    home, console = isolated
    saved = home / ".config/help-wanted/token"
    saved.parent.mkdir(parents=True)
    saved.write_text("old-token")
    saved.chmod(0o600)
    command = Mock(return_value=subprocess.CompletedProcess([], 0, "gh-token\n", ""))
    monkeypatch.setattr("subprocess.run", command)
    assert get_github_token(console) == "gh-token"
    assert command.call_args.args[0] == ["gh", "auth", "token"]
    assert command.call_args.kwargs["timeout"] <= 10


@pytest.mark.parametrize("gh_failure", [FileNotFoundError(), subprocess.TimeoutExpired("gh", 10)])
def test_owner_only_saved_token_is_reused(isolated, monkeypatch, gh_failure):
    home, console = isolated
    monkeypatch.setattr("subprocess.run", Mock(side_effect=gh_failure))
    saved = home / ".config/help-wanted/token"
    saved.parent.mkdir(parents=True)
    saved.write_text("saved-token\n")
    saved.chmod(0o600)
    assert get_github_token(console) == "saved-token"
    assert "saved-token" not in console.file.getvalue()


def github(monkeypatch, responses):
    requests = []
    responses = iter(responses)

    def respond(request):
        requests.append(request)
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(200, json=result)

    client = HTTPClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("httpx.Client", Mock(return_value=client))
    return requests


def test_device_sign_in_saves_private_token_and_shows_only_user_code(isolated, monkeypatch):
    home, console = isolated
    requests = github(monkeypatch, [
        {"device_code": "private-device-code", "user_code": "WXYZ-1234",
         "verification_uri": "https://github.com/login/device", "expires_in": 900, "interval": 5},
        {"access_token": "device-token"},
    ])
    monkeypatch.setattr("time.sleep", Mock())
    assert get_github_token(console) == "device-token"
    assert requests[0].url == "https://github.com/login/device/code"
    assert requests[0].content == b"client_id=Ov23limUFG1pepZFGN7q"
    assert b"client_secret" not in requests[1].content
    assert b"scope" not in requests[1].content
    assert "WXYZ-1234" in console.file.getvalue()
    assert "github.com/login/device" in console.file.getvalue()
    assert "private-device-code" not in console.file.getvalue()
    assert "device-token" not in console.file.getvalue()
    saved = home / ".config/help-wanted/token"
    assert saved.read_text().strip() == "device-token"
    assert saved.stat().st_mode & 0o777 == 0o600
    assert saved.parent.stat().st_mode & 0o777 == 0o700
    assert [p.name for p in saved.parent.iterdir()] == ["token"]


def test_pending_and_slow_down_poll_at_github_intervals(isolated, monkeypatch):
    _, console = isolated
    requests = github(monkeypatch, [
        {"device_code": "device", "user_code": "WXYZ-1234", "expires_in": 900, "interval": 5},
        {"error": "authorization_pending"},
        {"error": "slow_down"},
        {"error": "authorization_pending"},
        {"access_token": "signed-in-token"},
    ])
    sleep = Mock()
    monkeypatch.setattr("time.sleep", sleep)
    assert get_github_token(console) == "signed-in-token"
    assert [call.args[0] for call in sleep.call_args_list] == [5, 5, 10, 10]
    assert len(requests) == 5


@pytest.mark.parametrize("failure,message", [
    ({"error": "access_denied"}, "declined"),
    ({"error": "expired_token"}, "expired"),
    ({"error": "incorrect_client_credentials", "error_description": "secret-detail"}, "could not"),
    (httpx.ConnectError("secret-detail"), "reach GitHub"),
])
def test_failed_device_sign_in_offers_hidden_public_token_fallback(isolated, monkeypatch, failure, message):
    home, console = isolated
    github(monkeypatch, [
        {"device_code": "device", "user_code": "WXYZ-1234", "expires_in": 900}, failure,
    ])
    monkeypatch.setattr("time.sleep", Mock())
    prompt = Mock(return_value=" pasted-token ")
    monkeypatch.setattr("getpass.getpass", prompt)
    assert get_github_token(console) == "pasted-token"
    output = console.file.getvalue()
    assert message in output
    assert "github.com/settings/personal-access-tokens/new?" in output
    assert "public" in output
    assert "secret-detail" not in output
    assert "pasted-token" not in output
    prompt.assert_called_once()
    assert (home / ".config/help-wanted/token").read_text().strip() == "pasted-token"


@pytest.mark.parametrize("reply", [{"access_token": 123}, {"access_token": "bad\ntoken"}])
def test_invalid_token_reply_does_not_get_saved(isolated, monkeypatch, reply):
    home, console = isolated
    github(monkeypatch, [
        {"device_code": "device", "user_code": "CODE", "expires_in": 60}, reply,
    ])
    monkeypatch.setattr("time.sleep", Mock())
    monkeypatch.setattr("getpass.getpass", Mock(return_value=""))
    with pytest.raises(AuthError, match="No GitHub token"):
        get_github_token(console)
    assert not (home / ".config/help-wanted/token").exists()


def test_browser_failure_still_allows_sign_in_at_printed_url(isolated, monkeypatch):
    _, console = isolated
    github(monkeypatch, [
        {"device_code": "device", "user_code": "CODE", "expires_in": 60},
        {"access_token": "device-token"},
    ])
    monkeypatch.setattr("time.sleep", Mock())
    monkeypatch.setattr("webbrowser.open", Mock(side_effect=OSError("secret-detail")))
    assert get_github_token(console) == "device-token"
    assert "Open the link" in console.file.getvalue()
    assert "secret-detail" not in console.file.getvalue()


def test_polling_does_not_send_a_request_after_code_expires(isolated, monkeypatch):
    _, console = isolated
    requests = github(monkeypatch, [
        {"device_code": "device", "user_code": "CODE", "expires_in": 10, "interval": 5},
    ])
    now = [0]
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    monkeypatch.setattr("time.sleep", lambda _: now.__setitem__(0, 11))
    monkeypatch.setattr("getpass.getpass", Mock(return_value="manual-token"))
    assert get_github_token(console) == "manual-token"
    assert len(requests) == 1
    assert "expired" in console.file.getvalue()


def test_pending_polling_is_bounded_even_without_clock_progress(isolated, monkeypatch):
    _, console = isolated
    requests = github(monkeypatch, [
        {"device_code": "device", "user_code": "CODE", "expires_in": 11, "interval": 5},
        {"error": "authorization_pending"}, {"error": "authorization_pending"},
    ])
    monkeypatch.setattr("time.monotonic", lambda: 0)
    monkeypatch.setattr("time.sleep", Mock())
    monkeypatch.setattr("getpass.getpass", Mock(return_value="manual-token"))
    assert get_github_token(console) == "manual-token"
    assert len(requests) == 3
    assert "expired" in console.file.getvalue()


@pytest.mark.parametrize("unsafe", ["permissions", "file_symlink", "directory_symlink", "config_symlink"])
def test_unsafe_saved_token_is_not_read_and_symlink_targets_are_untouched(isolated, monkeypatch, unsafe):
    home, console = isolated
    outside = home / "outside"
    outside.mkdir()
    target = outside / "token"
    target.write_text("do-not-use")
    target.chmod(0o600)
    config = home / ".config"
    directory = config / "help-wanted"
    if unsafe == "config_symlink":
        config.symlink_to(outside, target_is_directory=True)
        (outside / "help-wanted").mkdir()
        (outside / "help-wanted/token").write_text("do-not-use")
        (outside / "help-wanted/token").chmod(0o600)
    elif unsafe == "directory_symlink":
        config.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
    else:
        directory.mkdir(parents=True)
        if unsafe == "file_symlink":
            (directory / "token").symlink_to(target)
        else:
            (directory / "token").write_text("do-not-use")
            (directory / "token").chmod(0o644)
    github(monkeypatch, [{"error": "device_flow_disabled"}])
    monkeypatch.setattr("getpass.getpass", Mock(return_value="new-token"))
    assert get_github_token(console) == "new-token"
    assert target.read_text() == "do-not-use"
    if unsafe in {"directory_symlink", "config_symlink"}:
        assert "could not save" in console.file.getvalue()
    else:
        assert not (directory / "token").is_symlink()
        assert (directory / "token").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("cancel", [EOFError(), KeyboardInterrupt(), ""])
def test_cancelled_manual_sign_in_raises_plain_error_without_writing(isolated, monkeypatch, cancel):
    home, console = isolated
    github(monkeypatch, [httpx.ConnectError("private-detail")])
    prompt = Mock(side_effect=cancel) if isinstance(cancel, BaseException) else Mock(return_value=cancel)
    monkeypatch.setattr("getpass.getpass", prompt)
    with pytest.raises(AuthError) as caught:
        get_github_token(console)
    assert "private-detail" not in str(caught.value)
    assert "Run Help Wanted again" in str(caught.value)
    assert not (home / ".config/help-wanted/token").exists()


def test_failed_atomic_save_keeps_existing_token_and_cleans_temporary_file(isolated, monkeypatch):
    home, console = isolated
    directory = home / ".config/help-wanted"
    directory.mkdir(parents=True)
    saved = directory / "token"
    saved.write_text("old-token")
    saved.chmod(0o644)  # An unsafe file must not be reused.
    github(monkeypatch, [{"error": "device_flow_disabled"}])
    monkeypatch.setattr("getpass.getpass", Mock(return_value="new-token"))
    monkeypatch.setattr("os.replace", Mock(side_effect=OSError("private-detail")))
    assert get_github_token(console) == "new-token"
    assert saved.read_text() == "old-token"
    assert [p.name for p in directory.iterdir()] == ["token"]
    assert "could not save" in console.file.getvalue()
    assert "private-detail" not in console.file.getvalue()


def test_cancelling_device_wait_stops_with_plain_error(isolated, monkeypatch):
    home, console = isolated
    github(monkeypatch, [{"device_code": "device", "user_code": "CODE", "expires_in": 60}])
    monkeypatch.setattr("time.sleep", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(AuthError, match="Sign-in stopped"):
        get_github_token(console)
    assert not (home / ".config/help-wanted/token").exists()


def test_manual_entry_refuses_a_terminal_that_cannot_hide_input(isolated, monkeypatch):
    home, console = isolated
    github(monkeypatch, [{"error": "device_flow_disabled"}])

    def unsafe_prompt(_):
        warnings.warn("Cannot hide input", getpass.GetPassWarning)
        pytest.fail("Must stop before falling back to echoed input")

    monkeypatch.setattr("getpass.getpass", unsafe_prompt)
    with pytest.raises(AuthError, match="Sign-in stopped"):
        get_github_token(console)
    assert not (home / ".config/help-wanted/token").exists()


@pytest.mark.parametrize("response", [[], {"device_code": "device"}, {"expires_in": "not-a-number"}])
def test_malformed_device_reply_offers_manual_sign_in(isolated, monkeypatch, response):
    _, console = isolated
    github(monkeypatch, [response])
    monkeypatch.setattr("getpass.getpass", Mock(return_value="manual-token"))
    assert get_github_token(console) == "manual-token"
    assert "could not read" in console.file.getvalue()


def test_environment_token_is_not_copied_to_config(isolated, monkeypatch):
    home, console = isolated
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    assert get_github_token(console) == "env-token"
    assert not (home / ".config").exists()
