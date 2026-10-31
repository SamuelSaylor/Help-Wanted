import json

import pytest
from typer.testing import CliRunner

from help_wanted import cli


class Model:
    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"

        class Reply:
            async def ainvoke(self, messages):
                if schema.__name__ == "SearchPlan":
                    return schema.model_validate({"queries": ["topic:education"]})
                return schema.model_validate({
                    "heading": "Recommendations", "why_heading": "Why it fits",
                    "learn_heading": "What you will learn", "steps_heading": "First steps",
                    "notice": "No Recommendations were found: 0 of 3 issues met the rules.",
                    "narratives": [],
                })

        return Reply()


@pytest.fixture
def external_services(monkeypatch, tmp_path):
    """Replace only setup/auth/Ollama/MCP, keeping the real CLI and graph."""
    monkeypatch.chdir(tmp_path)
    events = []

    async def prepare(*, console):
        events.append("ollama")
        return "gemma4:cloud"

    async def token(*, console):
        events.append("auth")
        return "secret-token"

    class Tool:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, arguments):
            events.append(self.name)
            if self.name == "get_me":
                assert not (tmp_path / ".help-wanted").exists() or len(events) > 4
                return [{"type": "text", "text": '{"login":"octocat"}'}]
            return {"items": []}

    async def tools(token):
        assert token == "secret-token"
        events.append("tools")
        return [Tool(name) for name in [
            "get_me", "search_repositories", "search_pull_requests",
            "get_file_contents", "search_issues",
        ]]

    def model(model_name=None, **kwargs):
        assert model_name == "gemma4:cloud"
        return Model()

    monkeypatch.setattr(cli, "prepare_ollama", prepare, raising=False)
    monkeypatch.setattr(cli, "get_github_token", token, raising=False)
    monkeypatch.setattr(cli, "load_github_tools", tools, raising=False)
    monkeypatch.setattr(cli, "build_model", model)
    return events


def test_cli_authenticates_before_selecting_contributor_folder(external_services, tmp_path):
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert external_services[:4] == ["ollama", "auth", "tools", "get_me"]
    assert "default Contributor Profile" in result.output
    assert "questionnaire" in result.output.lower()
    assert (tmp_path / ".help-wanted/octocat/recommendations.md").exists()
    assert not (tmp_path / ".help-wanted/sample-contributor").exists()
    assert "secret-token" not in result.output


@pytest.mark.parametrize("payload", [
    {"login": "octocat"},
    '{"login":"octocat"}',
    {"content": [{"type": "text", "text": '{"login":"octocat"}'}]},
    {"structuredContent": {"login": "octocat"}},
])
def test_cli_accepts_mcp_identity_formats(external_services, monkeypatch, payload, tmp_path):
    class Identity:
        name = "get_me"

        async def ainvoke(self, arguments):
            return payload

    async def tools(token):
        return [Identity()]

    # Validated saved stages let this test isolate the initial identity check.
    folder = tmp_path / ".help-wanted/octocat"
    folder.mkdir(parents=True)
    from help_wanted.contracts import ContributorProfile, SkillAssessment
    (folder / "profile.json").write_text(ContributorProfile().model_dump_json())
    (folder / "skills.json").write_text(SkillAssessment(
        username="octocat", experience_level="new to GitHub", summary="No public activity",
    ).model_dump_json())
    (folder / "projects.json").write_text('{"projects": []}')
    (folder / "issues.json").write_text('{"issues": []}')
    (folder / "recommendations.md").write_text("# Saved Recommendations")
    monkeypatch.setattr(cli, "load_github_tools", tools)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert "Saved Recommendations" in result.output


@pytest.mark.parametrize("payload", [
    {"login": "../someone"}, {"login": ""}, {},
    {"isError": True, "content": "Authorization: Bearer secret-token"},
    [{"type": "text", "text": "Authorization: Bearer secret-token"}],
])
def test_cli_stops_before_writing_when_identity_is_invalid(external_services, monkeypatch, payload, tmp_path):
    class Identity:
        name = "get_me"

        async def ainvoke(self, arguments):
            return payload

    async def tools(token):
        return [Identity()]

    monkeypatch.setattr(cli, "load_github_tools", tools)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 1
    assert "GitHub could not confirm your username" in result.output
    assert "secret-token" not in result.output
    assert not (tmp_path / ".help-wanted").exists()


def test_cli_resumes_saved_contributor_profile_and_fresh_uses_defaults(external_services, tmp_path):
    first = CliRunner().invoke(cli.app, [])
    assert first.exit_code == 0, first.output
    folder = tmp_path / ".help-wanted/octocat"
    profile_path = folder / "profile.json"
    profile = json.loads(profile_path.read_text())
    profile["spoken_languages"] = ["Spanish"]
    profile_path.write_text(json.dumps(profile))
    resumed = CliRunner().invoke(cli.app, [])
    assert resumed.exit_code == 0, resumed.output
    assert "Reusing your saved Contributor Profile" in resumed.output
    assert json.loads(profile_path.read_text())["spoken_languages"] == ["Spanish"]
    fresh = CliRunner().invoke(cli.app, ["--fresh"])
    assert fresh.exit_code == 0, fresh.output
    assert "default Contributor Profile" in fresh.output
    assert json.loads(profile_path.read_text())["spoken_languages"] == ["English"]


@pytest.mark.parametrize("boundary", ["prepare_ollama", "get_github_token", "load_github_tools"])
def test_cli_hides_untrusted_external_errors(external_services, monkeypatch, boundary, tmp_path):
    async def failed(*args, **kwargs):
        raise Exception("Authorization: Bearer secret-token")

    monkeypatch.setattr(cli, boundary, failed)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 1
    assert "could not finish" in result.output
    assert "secret-token" not in result.output
    assert "Traceback" not in result.output
    assert not (tmp_path / ".help-wanted").exists()


@pytest.mark.parametrize("boundary,error", [
    ("prepare_ollama", cli.SetupError("Please start Ollama and try again.")),
    ("get_github_token", cli.AuthError("Please sign in to GitHub again.")),
])
def test_cli_shows_safe_setup_guidance(external_services, monkeypatch, boundary, error):
    async def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, boundary, failed)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 1
    assert str(error) in result.output
    assert "Traceback" not in result.output


def test_cli_preserves_keyboard_cancel(external_services, monkeypatch, tmp_path):
    async def cancel(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "prepare_ollama", cancel)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code != 0
    assert "could not finish" not in result.output
    assert not (tmp_path / ".help-wanted").exists()


def test_cli_uses_selected_model_instead_of_environment(external_services, monkeypatch):
    from help_wanted import clients

    monkeypatch.setenv("HELP_WANTED_MODEL", "gemma4:e4b")
    monkeypatch.setenv("HELP_WANTED_NUM_CTX", "16384")

    def ollama(**kwargs):
        assert kwargs["model"] == "gemma4:cloud"
        assert kwargs["num_ctx"] == 16384
        return Model()

    monkeypatch.setattr(clients, "ChatOllama", ollama)
    monkeypatch.setattr(cli, "build_model", clients.build_model)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0, result.output


def test_cli_handles_model_errors_without_headers_or_tracebacks(external_services, monkeypatch):
    def unavailable(model_name):
        class Unavailable:
            def with_structured_output(self, *args, **kwargs):
                raise ConnectionError("Authorization: Bearer secret-token")
        return Unavailable()

    monkeypatch.setattr(cli, "build_model", unavailable)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 1
    assert "Gemma" in result.output
    assert "secret-token" not in result.output
    assert "Traceback" not in result.output
