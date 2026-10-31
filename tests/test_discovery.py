import asyncio
import base64
import json
from datetime import date

import pytest

from help_wanted.contracts import ContributorProfile, SkillAssessment
from help_wanted.pipeline import run_pipeline


class Model:
    def __init__(self, ranking, queries=None):
        self.ranking = ranking
        self.queries = queries or ["music language:Python", "audio CLI"]
        self.inputs = []

    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"
        model = self

        class Reply:
            async def ainvoke(self, messages):
                model.inputs.append(messages)
                if len(model.inputs) == 1:
                    return {"queries": model.queries}
                if isinstance(model.ranking, Exception):
                    raise model.ranking
                return {"projects": model.ranking}

        return Reply()


class Tool:
    def __init__(self, name, response):
        self.name = name
        self.response = response
        self.calls = []

    async def ainvoke(self, arguments):
        self.calls.append(arguments)
        return self.response(arguments) if callable(self.response) else self.response


def discover(tmp_path, model, tools, profile=None, skills=None):
    folder = tmp_path / "octocat"
    folder.mkdir(exist_ok=True)
    profile = profile or ContributorProfile()
    skills = skills or SkillAssessment(
        username="octocat", experience_level="beginner", summary="new to GitHub",
        new_to_github=True,
    )
    for name, value in [("profile", profile), ("skills", skills)]:
        (folder / f"{name}.json").write_text(value.model_dump_json())
    (folder / "issues.json").write_text('{"issues": []}')
    (folder / "recommendations.md").write_text("Cached Recommendations")
    asyncio.run(run_pipeline(model, tools, username="octocat", output_root=tmp_path))
    return json.loads((folder / "projects.json").read_text())


def repository(number, **metadata):
    return {
        "full_name": f"music/project-{number}",
        "html_url": f"https://github.com/music/project-{number}",
        "description": "Audio CLI", "language": "Python", "stargazers_count": 50,
        **metadata,
    }


def ranked(*numbers):
    return [{"full_name": f"music/project-{n}", "reason": f"Fit {n}: audio practice"}
            for n in numbers]


def test_discovery_persists_ranked_projects_and_two_spares(tmp_path):
    model = Model(ranked(7, 3, 5, 1, 0, 2, 6, 4))
    search = Tool("search_repositories", {"items": [repository(n) for n in range(8)]})
    readme = Tool("get_file_contents", {"content": "Audio CLI README", "encoding": "utf-8"})
    output = discover(tmp_path, model, [search, readme])
    assert [p["full_name"] for p in output["projects"]] == [
        "music/project-7", "music/project-3", "music/project-5", "music/project-1",
        "music/project-0", "music/project-2",
    ]
    assert [p["full_name"] for p in output["spares"]] == ["music/project-6", "music/project-4"]
    assert output["projects"][0]["reason"] == "Fit 7: audio practice"
    assert len(readme.calls) == 8


@pytest.mark.parametrize("popularity,activity,stars,pushed", [
    ("small", "1 month", "stars:<100", "pushed:>=2026-02-28"),
    ("medium", "6 months", "stars:100..999", "pushed:>=2025-09-30"),
    ("large", "any", "stars:>=1000", None),
])
def test_searches_apply_code_owned_filters(tmp_path, monkeypatch, popularity, activity, stars, pushed):
    from help_wanted.stages import discovery

    class Clock(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 31)

    monkeypatch.setattr(discovery, "date", Clock, raising=False)
    model = Model([], queries=[
        "music language:Python stars:0 pushed:<2000-01-01 contributors:>5 OR is:private",
        "audio CLI",
    ])
    search = Tool("search_repositories", {"items": []})
    output = discover(tmp_path, model, [search], ContributorProfile(
        project_popularity=popularity, recent_activity=activity, contributor_count="<10",
    ))
    assert len(search.calls) >= 2
    for call in search.calls:
        query = call["query"]
        assert stars in query
        assert "archived:false" in query and "is:public" in query
        assert "stars:0" not in query and "contributors:" not in query
        assert "pushed:<" not in query and "is:private" not in query and " OR " not in query
        assert "good-first-issues:>0" in query or "help-wanted-issues:>0" in query
        if pushed:
            assert pushed in query
        else:
            assert "pushed:" not in query
    assert "contributor count" in output["reason"].lower()
    assert "not filtered" in output["reason"].lower()


@pytest.mark.parametrize("transport", ["direct", "structured", "text", "adapter"])
def test_readmes_are_decoded_truncated_and_search_results_compacted(tmp_path, transport):
    def wrap(payload):
        if transport == "structured":
            return {"structuredContent": payload}
        blocks = [{"type": "text", "text": json.dumps(payload)}]
        if transport == "text":
            return {"content": blocks, "isError": False}
        return blocks if transport == "adapter" else payload

    model = Model(ranked(1, 2))
    search = Tool("search_repositories", wrap({"items": [
        repository(1, unrelated_large_field="NOT FOR GEMMA"), repository(2),
    ]}))
    readme = Tool("get_file_contents", wrap({
        "content": base64.b64encode(("Música en español. " + "x" * 5000 + "HIDDEN TAIL").encode()).decode(),
        "encoding": "base64",
    }))
    output = discover(tmp_path, model, [search, readme], ContributorProfile(
        spoken_languages=["Spanish"], recommendation_count=1,
    ))
    assert len(output["projects"]) == 2
    model_input = json.loads(model.inputs[1][-1]["content"])
    assert len(model_input["candidates"]) == 2
    for candidate in model_input["candidates"]:
        assert candidate["readme"].startswith("Música en español.")
        assert 1000 <= len(candidate["readme"]) <= 3000
    assert "HIDDEN TAIL" not in json.dumps(model.inputs)
    assert "NOT FOR GEMMA" not in json.dumps(model.inputs)
    assert model_input["profile"]["spoken_languages"] == ["Spanish"]


def test_ranking_cannot_invent_duplicate_or_rewrite_projects(tmp_path):
    model = Model([
        {"full_name": "invented/repository", "reason": "Made up"},
        *ranked(2, 2, 1),
    ])
    search = Tool("search_repositories", {"items": [repository(1), repository(2)]})
    readme = Tool("get_file_contents", {"content": "Real project", "encoding": "utf-8"})
    output = discover(tmp_path, model, [search, readme])
    assert [p["full_name"] for p in output["projects"]] == ["music/project-2", "music/project-1"]
    assert output["projects"][0]["url"] == "https://github.com/music/project-2"
    assert output["spares"] == []
    assert "fewer" in output["reason"].lower()


def test_repository_metadata_filters_before_ranking_but_contributor_counts_do_not(tmp_path):
    model = Model(ranked(0, 1, 2, 3, 4, 5, 6))
    search = Tool("search_repositories", {"items": [
        repository(0, contributor_count=4, contributor_count_verified=True),
        repository(1, contributor_count=20, contributor_count_verified=True),
        repository(2, contributor_count=2),
        repository(3, stargazers_count=9999),
        repository(4, archived=True),
        repository(5, private=True),
        repository(6, pushed_at="2000-01-01T00:00:00Z"),
    ]})
    readme = Tool("get_file_contents", {"content": "README", "encoding": "utf-8"})
    output = discover(tmp_path, model, [search, readme], ContributorProfile(
        project_popularity="small", contributor_count="<10", recent_activity="1 month",
    ))
    assert [p["full_name"] for p in output["projects"]] == [
        "music/project-0", "music/project-1", "music/project-2",
    ]
    assert "contributor count is not filtered" in output["reason"].lower()
    offered = json.loads(model.inputs[1][-1]["content"])["candidates"]
    assert [p["full_name"] for p in offered] == [
        "music/project-0", "music/project-1", "music/project-2",
    ]


def test_new_to_github_searches_favour_many_beginner_issues(tmp_path):
    def search(arguments):
        assert arguments["sort"] == "help-wanted-issues"
        assert arguments["order"] == "desc"
        assert ("good-first-issues:>0" in arguments["query"]
                or "help-wanted-issues:>0" in arguments["query"])
        return {"items": [repository(1)]}

    output = discover(tmp_path, Model(ranked(1)), [
        Tool("search_repositories", search),
        Tool("get_file_contents", {"content": "Beginner guide"}),
    ])
    assert output["projects"][0]["full_name"] == "music/project-1"


@pytest.mark.parametrize("requested,expected", [(1, 2), (2, 4), (3, 6), (99, 6)])
def test_requested_project_count_is_capped_and_spares_stay_separate(tmp_path, requested, expected):
    output = discover(tmp_path, Model(ranked(*range(8))), [
        Tool("search_repositories", {"items": [repository(n) for n in range(8)]}),
        Tool("get_file_contents", {"content": "README"}),
    ], ContributorProfile(recommendation_count=requested))
    assert len(output["projects"]) == expected
    assert len(output["spares"]) == 2


def test_unavailable_readme_is_not_mistaken_for_language_evidence(tmp_path):
    model = Model(ranked(1))
    output = discover(tmp_path, model, [
        Tool("search_repositories", {"items": [repository(1)]}),
        Tool("get_file_contents", {"isError": True, "content": [{"type": "text", "text": "not found"}]}),
    ])
    assert output["projects"][0]["readme_status"] == "unavailable"
    offered = json.loads(model.inputs[1][-1]["content"])["candidates"][0]
    assert offered["readme"] == ""
    assert offered["readme_status"] == "unavailable"
    assert "readme" in output["reason"].lower()


def test_embedded_mcp_readme_resource_is_read_and_truncated(tmp_path):
    model = Model(ranked(1))
    output = discover(tmp_path, model, [
        Tool("search_repositories", {"items": [repository(1)]}),
        Tool("get_file_contents", {"structuredContent": {"content": [
            {"type": "text", "text": "successfully downloaded text file (SHA: abc)"},
            {"type": "resource", "resource": {"text": "Bonjour " + "x" * 4000}},
        ]}}),
    ])
    assert output["projects"][0]["readme_status"] == "excerpt"
    offered = json.loads(model.inputs[1][-1]["content"])["candidates"][0]
    assert offered["readme"].startswith("Bonjour ")
    assert len(offered["readme"]) == 2000


@pytest.mark.parametrize("response", [
    {"isError": True, "structuredContent": {"items": [repository(1)]}},
    {"message": "API rate limit exceeded"},
    {"items": "malformed"},
])
def test_search_error_does_not_persist_made_up_projects(tmp_path, response):
    with pytest.raises(ValueError, match="GitHub"):
        discover(tmp_path, Model(ranked(1)), [
            Tool("search_repositories", response),
        ])
    assert not (tmp_path / "octocat/projects.json").exists()


def test_empty_searches_report_shortfall_without_asking_gemma_to_rank_nothing(tmp_path):
    output = discover(tmp_path, Model(RuntimeError("There is nothing to rank")), [
        Tool("search_repositories", {"items": [], "incomplete_results": True}),
    ])
    assert output["projects"] == [] and output["spares"] == []
    assert "fewer" in output["reason"].lower()
    assert "incomplete" in output["reason"].lower()


def test_distinct_searches_share_the_bounded_model_context(tmp_path):
    model = Model(ranked(99, 0, 1, 2, 3, 4, 5, 6))

    def search(arguments):
        return {"items": ([repository(n) for n in range(20)]
                          if "music" in arguments["query"] else [repository(99)])}

    readme = Tool("get_file_contents", {"content": "README"})
    output = discover(tmp_path, model, [Tool("search_repositories", search), readme])
    assert output["projects"][0]["full_name"] == "music/project-99"
    assert len(readme.calls) <= 10
    offered = json.loads(model.inputs[1][-1]["content"])["candidates"]
    assert len(offered) <= 10
    assert any(p["full_name"] == "music/project-99" for p in offered)
