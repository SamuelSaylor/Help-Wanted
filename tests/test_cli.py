import json

import pytest
from typer.testing import CliRunner

from help_wanted import cli


@pytest.mark.parametrize("is_terminal", [True, False])
def test_startup_clears_only_interactive_terminals(external_services, monkeypatch, is_terminal):
    console = cli.themed_console()
    monkeypatch.setattr(type(console), "is_terminal", property(lambda self: is_terminal))
    monkeypatch.setattr(cli, "themed_console", lambda: console)
    cleared = []
    monkeypatch.setattr(console, "clear", lambda: cleared.append(list(external_services)))

    result = CliRunner().invoke(cli.app, [])

    assert result.exit_code == 0
    assert cleared == ([[]] if is_terminal else [])


class Model:
    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"

        class Reply:
            async def ainvoke(self, messages):
                if schema.__name__ == "Keywords":
                    return schema.model_validate({"search_keywords": ["audio"]})
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
    assert "not integrated" not in result.output
    assert (tmp_path / ".help-wanted/octocat/recommendations.md").exists()
    assert not (tmp_path / ".help-wanted/sample-contributor").exists()
    assert "secret-token" not in result.output


@pytest.mark.parametrize("model_name", ["gemma4:cloud", "gemma4:e4b"])
def test_cli_explains_irreducible_context_budget(external_services, monkeypatch, model_name):
    async def prepare(*, console):
        external_services.append("ollama")
        return model_name

    def small_model(selected_model):
        assert selected_model == model_name
        model = Model()
        model.model = model_name
        model.num_ctx = 64
        return model

    monkeypatch.setattr(cli, "prepare_ollama", prepare)
    monkeypatch.setattr(cli, "build_model", small_model)
    result = CliRunner().invoke(cli.app, [])
    output = " ".join(result.output.split())
    assert result.exit_code == 1
    assert "too much information" in output
    assert "HELP_WANTED_NUM_CTX" in output
    if model_name == "gemma4:cloud":
        assert "cloud" in output.lower()
        assert "not a local memory error" in output
        assert "machine with enough memory" not in output
    else:
        assert "machine with enough memory" in output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("payload", [
    {"login": "octocat"},
    '{"login":"octocat"}',
    {"content": [{"type": "text", "text": '{"login":"octocat"}'}]},
    {"structuredContent": {"login": "octocat"}},
    {"structured_content": {"login": "octocat"}},
    {"content": '{"login":"octocat"}'},
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
    {"is_error": True, "structured_content": {"login": "octocat"}},
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


def test_cli_resumes_saved_contributor_profile_and_fresh_replaces_it(external_services, tmp_path):
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
    assert "Reusing your saved Contributor Profile" not in fresh.output
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


def test_cli_does_not_claim_merged_questionnaire_is_missing(external_services):
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert "not integrated" not in result.output
    assert "interests and experience have not been collected" not in result.output


def test_cloud_skill_scan_fits_normal_public_history(external_services, monkeypatch, tmp_path):
    from langchain_ollama import ChatOllama
    from help_wanted import clients
    from help_wanted.contracts import ContributorProfile, SkillAssessment

    monkeypatch.delenv("HELP_WANTED_NUM_CTX", raising=False)
    folder = tmp_path / ".help-wanted/octocat"
    folder.mkdir(parents=True)
    (folder / "profile.json").write_text(ContributorProfile().model_dump_json())
    (folder / "projects.json").write_text('{"projects": []}')
    (folder / "issues.json").write_text('{"issues": []}')
    (folder / "recommendations.md").write_text("# Saved Recommendations")

    class History:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, arguments):
            if self.name == "get_me":
                return {"login": "octocat"}
            if self.name == "search_repositories":
                return {"items": [{
                    "full_name": f"octocat/community-project-{n}", "language": "Python",
                    "description": "An educational community project.",
                    "html_url": f"https://github.com/octocat/community-project-{n}",
                } for n in range(20)]}
            return {"items": [{
                "number": n, "title": f"Improve getting-started documentation for contributors {n}",
                "html_url": f"https://github.com/community/educational-project/pull/{n}",
            } for n in range(20)]}

    async def tools(token):
        return [History(name) for name in ("get_me", "search_repositories", "search_pull_requests")]

    calls = []

    def structured(model, schema, *, method):
        assert model.model == "gemma4:cloud"
        assert model.num_ctx == 131072
        assert schema is SkillAssessment

        class Reply:
            async def ainvoke(self, messages):
                calls.append(messages)
                return {"username": "octocat", "experience_level": "intermediate", "summary": "Public contributions"}

        return Reply()

    monkeypatch.setattr(cli, "load_github_tools", tools)
    monkeypatch.setattr(cli, "build_model", clients.build_model)
    monkeypatch.setattr(ChatOllama, "with_structured_output", structured)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert (folder / "skills.json").exists()


@pytest.mark.parametrize("interest", ["music", "music " * 2000])
def test_cli_asks_questionnaire_resumes_answers_and_fresh_asks_again(external_services, monkeypatch, tmp_path, interest):
    from types import SimpleNamespace
    from help_wanted.stages import questionnaire

    prompts = []

    class Prompter:
        async def select(self, message, choices):
            prompts.append(message)
            return "Spanish" if message.startswith("What is your native language?") else None

        async def checkbox(self, message, choices):
            prompts.append(message)
            return []

        async def text(self, message):
            prompts.append(message)
            return interest if message.startswith("What topics or hobbies") else ""

    monkeypatch.setattr(questionnaire, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: True)))
    monkeypatch.setattr(questionnaire, "QuestionaryPrompter", Prompter)
    first = CliRunner().invoke(cli.app, [])
    assert first.exit_code == 0, first.output
    assert "Every question is optional" in first.output
    assert "not integrated" not in first.output
    profile_path = tmp_path / ".help-wanted/octocat/profile.json"
    profile = json.loads(profile_path.read_text())
    assert profile["spoken_languages"] == ["Spanish"]
    assert profile["search_keywords"] == ["audio"]
    assert profile["interests"] == [interest.strip()]
    prompt_count = len(prompts)
    assert prompt_count > 0

    resumed = CliRunner().invoke(cli.app, [])
    assert resumed.exit_code == 0, resumed.output
    assert len(prompts) == prompt_count
    assert "Reusing your saved Contributor Profile" in resumed.output
    assert "--fresh" in resumed.output
    assert json.loads(profile_path.read_text()) == profile

    fresh = CliRunner().invoke(cli.app, ["--fresh"])
    assert fresh.exit_code == 0, fresh.output
    assert len(prompts) == 2 * prompt_count
    assert "Reusing your saved Contributor Profile" not in fresh.output
