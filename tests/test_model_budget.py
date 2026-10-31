"""Observe real stage calls through the pipeline, not per-field cap helpers."""

import asyncio
from datetime import datetime, timezone
import json

import pytest

from help_wanted.contracts import ContributorProfile, SkillAssessment
from help_wanted.pipeline import StageContext, run_pipeline


class BudgetModel:
    def __init__(self, num_ctx=8192):
        if num_ctx is not None:
            self.num_ctx = num_ctx
        self.calls = []

    def with_structured_output(self, schema, *, method):
        model = self

        class Reply:
            async def ainvoke(self, messages):
                # A conservative byte-token ceiling, independently checked at
                # the actual invocation, including schema and output allowance.
                wire = json.dumps(messages, ensure_ascii=False).encode("utf-8")
                schema_wire = json.dumps(schema.model_json_schema(), ensure_ascii=False).encode("utf-8")
                assert len(wire) + len(schema_wire) + 512 + 1024 <= getattr(model, "num_ctx", 8192)
                model.calls.append((schema.__name__, messages))
                if schema.__name__ == "SkillAssessment":
                    return {"username": "octocat", "experience_level": "beginner", "summary": "学び" * 10000}
                if schema.__name__ == "SearchPlan":
                    return {"queries": ["Python"]}
                if schema.__name__ == "ProjectRanking":
                    return {"projects": [{"full_name": "example/project-0", "reason": "学び" * 10000}]}
                if schema.__name__ == "SearchText":
                    return {"query": "documentation"}
                if schema.__name__ == "IssueRanking":
                    return {"indices": [0]}
                if schema.__name__ == "RecommendationWriting":
                    return {"heading": "Recommendations", "why_heading": "Why", "learn_heading": "Learn",
                            "steps_heading": "Steps", "notice": "", "narratives": [{
                                "why_it_fits": "Matches", "what_you_will_learn": "Git", "first_steps": ["Read the guide"],
                            }]}
                raise AssertionError(schema.__name__)

        return Reply()


class Tool:
    def __init__(self, name):
        self.name = name

    async def ainvoke(self, arguments):
        if self.name == "get_me":
            return {"login": "octocat"}
        if self.name == "search_repositories":
            return {"items": [{"full_name": f"example/project-{n}", "description": "学び" * 10000,
                               "html_url": f"https://github.com/example/project-{n}", "language": "Python"}
                              for n in range(10)]}
        if self.name == "search_pull_requests":
            return {"items": []}
        if self.name == "get_file_contents":
            return {"content": "مرحبا世界" * 10000, "encoding": "utf-8"}
        return {"total_count": 20, "incomplete_results": False, "items": [{
            "number": n, "title": f"Issue {n}", "body": "مرحبا世界" * 10000, "state": "open",
            "assignees": [], "labels": ["good first issue"],
            "html_url": f"https://github.com/example/project-0/issues/{n}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        } for n in range(1, 21)]}


@pytest.mark.parametrize("num_ctx", [None, 8192, 16384])
def test_full_pipeline_bounds_multilingual_inputs_and_keeps_saved_json(tmp_path, num_ctx):
    model = BudgetModel(num_ctx)
    profile = ContributorProfile(
        interests=["音楽" * 3000] * 20, past_contributions="مرحبا世界" * 10000,
        coding_languages=["Python"], spoken_languages=["Japanese"], recommendation_count=1,
    )
    asyncio.run(run_pipeline(model, [Tool(name) for name in (
        "get_me", "search_repositories", "search_pull_requests", "get_file_contents", "search_issues",
    )], profile=profile, username="octocat", output_root=tmp_path))
    assert [name for name, _ in model.calls] == [
        "SkillAssessment", "SearchPlan", "ProjectRanking", "SearchText", "IssueRanking", "RecommendationWriting",
    ]
    folder = tmp_path / "octocat"
    assert ContributorProfile.model_validate_json((folder / "profile.json").read_text()) == profile
    assert json.loads((folder / "skills.json").read_text())["summary"] == "学び" * 10000
    assert json.loads((folder / "projects.json").read_text())["projects"][0]["reason"] == "学び" * 10000
    assert json.loads((folder / "issues.json").read_text())["issues"][0]["body"] == ("مرحبا世界" * 10000)[:3000]
    inputs = {name: json.loads(messages[-1]["content"]) for name, messages in model.calls}
    assert [item["full_name"] for item in inputs["ProjectRanking"]["candidates"]] == [
        f"example/project-{n}" for n in range(10)
    ]
    assert [item["number"] for item in inputs["IssueRanking"]["issues"]] == list(range(1, 21))
    assert all(item["labels"] == ["good first issue"] for item in inputs["IssueRanking"]["issues"])
    assert inputs["RecommendationWriting"]["issues"][0]["url"] == "https://github.com/example/project-0/issues/1"
    assert inputs["RecommendationWriting"]["native_language"] == "Japanese"


def test_irreducible_input_is_rejected_before_model_call(tmp_path):
    model = BudgetModel()
    context = StageContext(model, (), "octocat", ContributorProfile(), tmp_path)
    with pytest.raises(ValueError, match="too much.*model|too large.*model"):
        asyncio.run(context.structured(SkillAssessment, [{"role": "user", "content": json.dumps({
            "url": "https://github.com/" + "a" * 20000,
        })}]))
    assert model.calls == []


def test_budget_includes_instructions_schema_and_output_not_only_data(tmp_path):
    model = BudgetModel()
    context = StageContext(model, (), "octocat", ContributorProfile(), tmp_path)
    messages = [{"role": "system", "content": "x" * 6500},
                {"role": "user", "content": '{"past_contributions": "short"}'}]
    assert len(json.dumps(messages)) < 8192
    with pytest.raises(ValueError, match="too much information"):
        asyncio.run(context.structured(SkillAssessment, messages))
    assert model.calls == []


def test_configured_output_allowance_is_included_in_context_budget(tmp_path):
    model = BudgetModel()
    model.num_predict = 4096
    context = StageContext(model, (), "octocat", ContributorProfile(), tmp_path)
    with pytest.raises(ValueError, match="too much information"):
        asyncio.run(context.structured(SkillAssessment, [{"role": "system", "content": "x" * 4000}]))
    assert model.calls == []


def test_ollama_invocation_has_the_same_context_and_output_limits_as_guard(tmp_path, monkeypatch):
    from langchain_ollama import ChatOllama

    calls = []

    def structured(model, schema, *, method):
        calls.append((model.num_ctx, model.num_predict))

        class Reply:
            async def ainvoke(self, messages):
                return {"username": "octocat", "experience_level": "beginner", "summary": "New"}

        return Reply()

    monkeypatch.setattr(ChatOllama, "with_structured_output", structured)
    model = ChatOllama(model="gemma4:e4b")
    context = StageContext(model, (), "octocat", ContributorProfile(), tmp_path)
    asyncio.run(context.structured(SkillAssessment, [{"role": "user", "content": "Assess octocat"}]))
    assert calls == [(8192, 1024)]
