import asyncio
import json

import pytest

from help_wanted.contracts import CandidateProjects, ContributorProfile, IssueSelection
from help_wanted.pipeline import run_pipeline


class GithubTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, arguments):
        self.calls.append(arguments)
        return self.result


class NoModel:
    def with_structured_output(self, schema, *, method):
        raise AssertionError("An empty public history needs no model guess")


def seed_other_stages(tmp_path, profile=None):
    folder = tmp_path / "octocat"
    folder.mkdir()
    (folder / "profile.json").write_text((profile or ContributorProfile()).model_dump_json())
    (folder / "projects.json").write_text(CandidateProjects().model_dump_json())
    (folder / "issues.json").write_text(IssueSelection().model_dump_json())
    (folder / "recommendations.md").write_text("# Recommendations\nStart with a beginner-friendly issue.\n")
    return folder


def test_contributor_without_public_history_gets_skill_assessment_and_continues(tmp_path):
    folder = seed_other_stages(tmp_path, ContributorProfile(
        coding_languages=["Python"], years_programming="3+", git_experience="comfortable",
        past_contributions="I contributed at work, outside GitHub.",
    ))
    tools = [
        GithubTool("get_me", [{"type": "text", "text": '{"login":"octocat"}'}]),
        GithubTool("search_repositories", {"total_count": 0, "items": []}),
        GithubTool("search_pull_requests", [{"type": "text", "text": '{"total_count":0,"items":[]}'}]),
    ]

    result = asyncio.run(run_pipeline(NoModel(), tools, username="octocat", output_root=tmp_path))

    skills = json.loads((folder / "skills.json").read_text())
    assert skills["username"] == "octocat"
    assert skills["new_to_github"] is True
    assert skills["experience_level"] == "new to GitHub"
    assert skills["coding_languages"] == ["Python"]
    assert "3+" in skills["summary"]
    assert "comfortable" in skills["summary"]
    assert "outside GitHub" in skills["summary"]
    assert skills["evidence"] == []
    assert "skill_scan" in result.completed_stages
    assert result.recommendations.startswith("# Recommendations")
    assert tools[1].calls[0]["query"] == "user:octocat is:public"
    assert tools[2].calls[0]["query"] == "author:octocat is:merged is:public"


class AssessmentModel:
    def __init__(self):
        self.messages = []

    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"
        model = self

        class Reply:
            async def ainvoke(self, messages):
                model.messages.extend(messages)
                return {
                    "username": "hallucinated-login", "experience_level": "intermediate",
                    "summary": "Your Python repository and merged fix build on your reported 1-3 years programming.",
                    "coding_languages": ["Python"], "new_to_github": True,
                    "evidence": ["Invented repository"],
                }

        return Reply()


@pytest.mark.parametrize("envelope", [
    lambda value: value,
    lambda value: [{"type": "text", "text": json.dumps(value)}],
    lambda value: {"content": [{"type": "text", "text": json.dumps(value)}]},
    lambda value: {"structuredContent": value},
])
def test_public_history_and_self_reports_produce_grounded_skill_assessment(tmp_path, envelope):
    folder = seed_other_stages(tmp_path, ContributorProfile(
        coding_languages=["JavaScript"], years_programming="1-3", git_experience="some",
        past_contributions="Helped with classroom documentation.",
    ))
    model = AssessmentModel()
    tools = [
        GithubTool("get_me", envelope({"login": "octocat", "email": "omit@example.com"})),
        GithubTool("search_repositories", envelope({"items": [{
            "full_name": "octocat/music", "language": "Python", "description": "A music CLI",
            "html_url": "https://github.com/octocat/music", "private": False,
            "owner": {"login": "octocat"}, "body": "DO NOT SEND RAW REPOSITORY BODY",
        }]})),
        GithubTool("search_pull_requests", envelope({"items": [{
            "title": "Fix audio parsing", "number": 42,
            "html_url": "https://github.com/community/audio/pull/42",
            "body": "DO NOT SEND RAW PULL REQUEST BODY",
        }]})),
    ]

    asyncio.run(run_pipeline(model, tools, username="octocat", output_root=tmp_path))

    skills = json.loads((folder / "skills.json").read_text())
    assert skills["username"] == "octocat"
    assert skills["experience_level"] == "intermediate"
    assert "reported 1-3 years" in skills["summary"]
    assert skills["new_to_github"] is False
    assert set(skills["coding_languages"]) == {"Python", "JavaScript"}
    assert any("https://github.com/octocat/music" in item for item in skills["evidence"])
    assert any("https://github.com/community/audio/pull/42" in item for item in skills["evidence"])
    assert "Invented repository" not in skills["evidence"]
    model_input = json.dumps(model.messages)
    for expected in ["1-3", "some", "classroom documentation", "octocat/music", "Fix audio parsing"]:
        assert expected in model_input
    assert "DO NOT SEND RAW" not in model_input
    assert "omit@example.com" not in model_input


def test_different_signed_in_contributor_cannot_write_this_results_folder(tmp_path):
    folder = seed_other_stages(tmp_path)
    tools = [GithubTool("get_me", {"login": "someone-else"})]

    with pytest.raises(ValueError, match="sign-in.*results folder"):
        asyncio.run(run_pipeline(NoModel(), tools, username="octocat", output_root=tmp_path))

    assert not (folder / "skills.json").exists()


@pytest.mark.parametrize("response", [
    [{"type": "text", "text": "GitHub search failed"}],
    {"isError": True, "content": [{"type": "text", "text": "Access denied"}]},
    {"message": "API rate limit exceeded"},
])
def test_unreadable_history_is_not_saved_as_new_to_github(tmp_path, response):
    folder = seed_other_stages(tmp_path)
    tools = [
        GithubTool("get_me", {"login": "octocat"}),
        GithubTool("search_repositories", response),
    ]

    with pytest.raises(ValueError, match="GitHub.*public history"):
        asyncio.run(run_pipeline(NoModel(), tools, username="octocat", output_root=tmp_path))

    assert not (folder / "skills.json").exists()
