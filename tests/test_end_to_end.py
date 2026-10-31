"""Run every matching stage together through the agreed pipeline seam."""

import asyncio
from datetime import datetime, timezone
import json

from help_wanted.contracts import ContributorProfile
from help_wanted.pipeline import run_pipeline


class ScriptedGemma:
    def __init__(self):
        self.inputs = []

    def with_structured_output(self, schema, *, method):
        model = self

        class Reply:
            async def ainvoke(self, messages):
                model.inputs.append(json.dumps(messages, ensure_ascii=False))
                return {
                    "SearchPlan": {"queries": ["music language:Python"]},
                    "ProjectRanking": {"projects": [{
                        "full_name": "music/player", "reason": "Python music project with a Spanish README.",
                    }]},
                    "SearchText": {"query": "small playlist bug"},
                    "IssueRanking": {"indices": [0]},
                    "RecommendationWriting": {
                        "heading": "Tus recomendaciones", "why_heading": "Por qué encaja",
                        "learn_heading": "Qué aprenderás", "steps_heading": "Primeros pasos",
                        "notice": "", "narratives": [{
                            "why_it_fits": "Combina tu interés por la música con Python.",
                            "what_you_will_learn": "Aprenderás a corregir una lista.",
                            "first_steps": ["Lee la incidencia y la guía para contribuir."],
                        }],
                    },
                }[schema.__name__]

        return Reply()


class GitHubTool:
    def __init__(self, name):
        self.name = name

    async def ainvoke(self, arguments):
        if self.name == "get_me":
            return {"login": "octocat"}
        if self.name == "search_pull_requests" or "user:octocat" in arguments.get("query", ""):
            return {"items": [], "total_count": 0, "incomplete_results": False}
        if self.name == "search_repositories":
            return {"items": [{
                "full_name": "music/player", "stargazers_count": 42,
                "description": "A Python music player", "language": "Python", "private": False,
            }], "total_count": 1, "incomplete_results": False}
        if self.name == "get_file_contents":
            return {"content": "Un reproductor de música. Lee la guía para contribuir.", "encoding": "utf-8"}
        assert self.name == "search_issues"
        assert "-linked:pr" in arguments["query"]
        safe = {
            "number": 1, "title": "Fix playlist ordering", "body": "The playlist sorts backwards.",
            "html_url": "https://github.com/music/player/issues/1",
            "repository_url": "https://api.github.com/repos/music/player",
            "state": "open", "assignees": [], "labels": [{"name": "good first issue"}],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        unsafe = []
        for number, title, overrides in [
            (2, "UNSAFE_ASSIGNED", {"assignees": [{"login": "someone"}]}),
            (3, "UNSAFE_PR_LINK", {"linked_pull_requests": [{"number": 99}]}),
            (4, "UNSAFE_STALE", {"updated_at": "2000-01-01T00:00:00Z"}),
        ]:
            unsafe.append({**safe, "number": number, "title": title,
                           "html_url": f"https://github.com/music/player/issues/{number}", **overrides})
        return {"items": [*unsafe, safe], "total_count": 4, "incomplete_results": False}


def test_new_contributor_gets_safe_native_language_recommendation(tmp_path):
    model = ScriptedGemma()
    tools = [GitHubTool(name) for name in (
        "get_me", "search_repositories", "search_pull_requests", "get_file_contents", "search_issues",
    )]
    result = asyncio.run(run_pipeline(
        model, tools, username="octocat", output_root=tmp_path,
        profile=ContributorProfile(
            interests=["music"], coding_languages=["Python"], spoken_languages=["Spanish"],
            recommendation_count=1,
        ),
    ))
    folder = tmp_path / "octocat"
    assert json.loads((folder / "skills.json").read_text())["new_to_github"] is True
    selected = json.loads((folder / "issues.json").read_text())["issues"]
    assert [issue["number"] for issue in selected] == [1]
    assert "Tus recomendaciones" in result.recommendations
    assert "Combina tu interés por la música" in result.recommendations
    assert "[Fix playlist ordering](https://github.com/music/player/issues/1)" in result.recommendations
    assert "UNSAFE_" not in "".join(model.inputs)
    assert "UNSAFE_" not in result.recommendations
    assert (folder / "recommendations.md").read_text() == result.recommendations
