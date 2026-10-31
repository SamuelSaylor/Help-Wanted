import asyncio
import json

import pytest
from pydantic import ValidationError

from help_wanted.contracts import ContributorProfile
from help_wanted.pipeline import run_pipeline


class ScriptedModel:
    def with_structured_output(self, schema, *, method):
        class Reply:
            async def ainvoke(self, messages):
                if schema.__name__ == "SearchPlan":
                    return {"queries": ["Python"]}
                if schema.__name__ == "RecommendationWriting":
                    return {
                        "heading": "Recommendations", "why_heading": "Why it fits",
                        "learn_heading": "What you will learn", "steps_heading": "First steps",
                        "notice": "Found 0 of 3: no issues met the rules. Try again later.",
                        "narratives": [],
                    }
                raise AssertionError(f"Unexpected structured output: {schema.__name__}")
        return Reply()


class GitHubTool:
    def __init__(self, name, username="octocat"):
        self.name = name
        self.username = username

    async def ainvoke(self, arguments):
        if self.name == "get_me":
            return {"login": self.username}
        return {"items": [], "total_count": 0}


def github_tools(username="octocat"):
    return [GitHubTool(name, username) for name in (
        "get_me", "search_repositories", "search_pull_requests", "get_file_contents", "search_issues",
    )]


def test_pipeline_writes_validated_stage_outputs(tmp_path):
    result = asyncio.run(run_pipeline(
        ScriptedModel(), github_tools(), profile=ContributorProfile(),
        username="octocat", output_root=tmp_path,
    ))
    folder = tmp_path / "octocat"
    assert json.loads((folder / "profile.json").read_text())["spoken_languages"] == ["English"]
    assert json.loads((folder / "skills.json").read_text())["experience_level"] == "new to GitHub"
    assert json.loads((folder / "projects.json").read_text())["projects"] == []
    assert json.loads((folder / "issues.json").read_text())["issues"] == []
    assert "Found 0 of 3" in (folder / "recommendations.md").read_text()
    assert result.completed_stages == [
        "setup", "questionnaire", "skill_scan", "discovery", "issue_search", "recommendations",
    ]


def test_pipeline_reuses_saved_profile_and_fresh_replaces_it(tmp_path):
    async def run():
        await run_pipeline(ScriptedModel(), github_tools(), username="octocat", output_root=tmp_path)
        changed = ContributorProfile(spoken_languages=["Spanish"])
        cached = await run_pipeline(
            ScriptedModel(), github_tools(), profile=changed, username="octocat", output_root=tmp_path,
        )
        assert cached.skipped_stages == [
            "questionnaire", "skill_scan", "discovery", "issue_search", "recommendations",
        ]
        assert cached.completed_stages == ["setup"]
        assert json.loads((tmp_path / "octocat/profile.json").read_text())["spoken_languages"] == ["English"]
        fresh = await run_pipeline(
            ScriptedModel(), github_tools(), profile=changed, username="octocat", output_root=tmp_path, fresh=True,
        )
        assert fresh.skipped_stages == []
        assert json.loads((tmp_path / "octocat/profile.json").read_text())["spoken_languages"] == ["Spanish"]

    asyncio.run(run())


def test_invalid_cached_output_is_not_silently_used(tmp_path):
    folder = tmp_path / "octocat"
    folder.mkdir()
    (folder / "profile.json").write_text('{"years_programming": "expert"}')
    with pytest.raises(ValidationError):
        asyncio.run(run_pipeline(ScriptedModel(), [], username="octocat", output_root=tmp_path))
    assert not (folder / "skills.json").exists()


def test_contributors_have_separate_output_folders(tmp_path):
    for username, language in [("octocat", "Spanish"), ("another-contributor", "French")]:
        asyncio.run(run_pipeline(
            ScriptedModel(), github_tools(username), username=username, output_root=tmp_path,
            profile=ContributorProfile(spoken_languages=[language]),
        ))
    assert json.loads((tmp_path / "octocat/profile.json").read_text())["spoken_languages"] == ["Spanish"]
    assert json.loads((tmp_path / "another-contributor/profile.json").read_text())["spoken_languages"] == ["French"]


def test_stage_plugins_use_structured_model_and_only_allowed_async_tools(tmp_path, monkeypatch):
    """Exercise the public stage plug-in boundary through the pipeline."""
    from help_wanted.contracts import CandidateProjects, IssueSelection, SkillAssessment
    from help_wanted.stages import discovery, issue_search, skill_scan

    class Tool:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, arguments):
            return {"login": "octocat"}

    class Model:
        def with_structured_output(self, schema, *, method):
            assert method == "json_schema"

            class Reply:
                async def ainvoke(self, messages):
                    if schema.__name__ == "RecommendationWriting":
                        return {
                            "heading": "Recommendations", "why_heading": "Why",
                            "learn_heading": "Learn", "steps_heading": "Steps",
                            "notice": "Found 0 of 3 eligible issues. Try again later.", "narratives": [],
                        }
                    assert messages == [{"role": "user", "content": "Assess octocat"}]
                    return {"username": "octocat", "experience_level": "beginner", "summary": "New Contributor"}

            return Reply()

    async def assess(context, *, profile):
        assert {t.name for t in context.tools} == {"get_me", "search_repositories", "search_pull_requests"}
        identity = await context.call_tool("get_me", {})
        with pytest.raises(ValueError):
            await context.call_tool("search_issues", {})
        return await context.structured(SkillAssessment, [
            {"role": "user", "content": f"Assess {identity['login']}"},
        ])

    async def discover(context, *, profile, skills):
        return CandidateProjects(reason=",".join(sorted(t.name for t in context.tools)))

    async def search(context, *, profile, skills, projects):
        return IssueSelection(reason=",".join(t.name for t in context.tools))

    monkeypatch.setattr(skill_scan, "run", assess)
    monkeypatch.setattr(discovery, "run", discover)
    monkeypatch.setattr(issue_search, "run", search)
    tools = [Tool(name) for name in [
        "get_me", "search_repositories", "search_pull_requests", "get_file_contents",
        "search_issues", "create_issue",
    ]]
    asyncio.run(run_pipeline(Model(), tools, username="octocat", output_root=tmp_path))
    folder = tmp_path / "octocat"
    assert json.loads((folder / "skills.json").read_text())["experience_level"] == "beginner"
    assert json.loads((folder / "projects.json").read_text())["reason"] == "get_file_contents,search_repositories"
    assert json.loads((folder / "issues.json").read_text())["reason"] == "search_issues"
