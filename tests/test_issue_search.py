"""Issue rules exercised through the pipeline with cached adjacent stages."""

import asyncio
from datetime import datetime, timezone
import json

import pytest

from help_wanted.contracts import CandidateProject, CandidateProjects, ContributorProfile, SkillAssessment
from help_wanted.pipeline import run_pipeline


class Model:
    def __init__(self, indices=None, query="small documentation improvements"):
        self.seen = []
        self.indices = indices
        self.query = query

    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"
        model = self

        class Reply:
            async def ainvoke(self, messages):
                data = json.loads(messages[-1]["content"])
                if "issues" not in data:
                    return {"query": model.query}
                model.seen.extend(data["issues"])
                return {"indices": model.indices if model.indices is not None else list(range(len(data["issues"])))}

        return Reply()


class Search:
    name = "search_issues"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def ainvoke(self, arguments):
        self.calls.append(arguments)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def issue(number, **changes):
    return {
        "number": number, "title": f"Issue {number}", "body": "Fix a typo",
        "html_url": f"https://github.com/example/project/issues/{number}",
        "state": "open", "assignees": [], "assignee": None,
        "labels": [{"name": "good first issue"}],
        "updated_at": datetime.now(timezone.utc).isoformat(), **changes,
    }


def payload(*items):
    return {"total_count": len(items), "incomplete_results": False, "items": list(items)}


def project(name="example/project"):
    return CandidateProject(full_name=name, url=f"https://github.com/{name}")


def run_search(tmp_path, model, tool, *, profile=None, projects=None):
    folder = tmp_path / "octocat"
    folder.mkdir(exist_ok=True)
    cached = {
        "profile.json": profile or ContributorProfile(),
        "skills.json": SkillAssessment(username="octocat", experience_level="beginner", summary="New"),
        "projects.json": projects or CandidateProjects(projects=[project()]),
    }
    for filename, value in cached.items():
        (folder / filename).write_text(value.model_dump_json())
    (folder / "recommendations.md").write_text("Cached Recommendations")
    asyncio.run(run_pipeline(model, [tool], username="octocat", output_root=tmp_path))
    return json.loads((folder / "issues.json").read_text())


def test_unsafe_issues_never_reach_model_or_saved_output(tmp_path):
    model = Model()
    tool = Search([payload(
        issue(1), issue(2, assignees=[{"login": "taken"}]),
        issue(3, linked_pull_requests=[{"number": 22}]),
        issue(4, updated_at="2020-01-01T00:00:00Z"), issue(5, state="closed"),
        issue(6, pull_request={}), issue(7, updated_at=None),
        issue(8, html_url="https://github.com/other/repo/issues/8"),
    )])
    result = run_search(tmp_path, model, tool)
    assert [i["number"] for i in result["issues"]] == [1]
    assert [i["number"] for i in model.seen] == [1]
    assert "-linked:pr" in tool.calls[0]["query"]
    assert "no:assignee" in tool.calls[0]["query"]
    assert "search_type" not in tool.calls[0]


@pytest.mark.parametrize("beginner_only, expected", [(True, [3, 1]), (False, [3, 1, 4])])
def test_beginner_labels_are_required_or_ranked_first_and_selection_is_bounded(tmp_path, beginner_only, expected):
    model = Model(indices=[3, 2, 1, 0, 999, -1, 2])
    tool = Search([payload(issue(1), issue(2, labels=[]), issue(3, labels=["help wanted"]), issue(4, labels=[]))])
    result = run_search(tmp_path, model, tool, profile=ContributorProfile(beginner_friendly_only=beginner_only))
    assert [i["number"] for i in result["issues"]] == expected
    if beginner_only:
        assert [i["number"] for i in model.seen] == [1, 3]


@pytest.mark.parametrize("response", [
    {"isError": True, "structuredContent": payload(issue(1)), "content": [{"type": "text", "text": "permission denied"}]},
    {"items": [issue(1)]},
    {"total_count": 1, "incomplete_results": False, "items": "bad"},
    RuntimeError("GitHub unavailable"),
])
def test_tool_errors_and_unknown_envelopes_fail_closed(tmp_path, response):
    model = Model()
    result = run_search(tmp_path, model, Search([response]))
    assert result["issues"] == []
    assert model.seen == []
    assert "GitHub" in result["reason"]


@pytest.mark.parametrize("wrap", [
    lambda data: {"isError": False, "structuredContent": data},
    lambda data: [{"type": "text", "text": json.dumps(data)}],
    lambda data: {"content": [{"type": "text", "text": json.dumps(data)}]},
])
def test_mcp_result_envelopes_are_normalized_before_filtering(tmp_path, wrap):
    result = run_search(tmp_path, Model(), Search([wrap(payload(issue(1), issue(2, assignees=["taken"])))]))
    assert [i["number"] for i in result["issues"]] == [1]


def test_search_waits_for_local_and_github_rate_limits_without_changing_query(tmp_path, monkeypatch):
    from help_wanted.stages import issue_search

    clock = [0.0]
    waits = []

    async def sleep(seconds):
        assert seconds > 0
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(issue_search, "monotonic", lambda: clock[0], raising=False)
    monkeypatch.setattr(issue_search, "sleep", sleep, raising=False)
    responses = [payload()] * 9 + [
        {"isError": True, "content": [{"type": "text", "text": "429 rate limit exceeded"}]},
        RuntimeError("secondary rate limit exceeded"),
        [{"type": "text", "text": "API rate limit exceeded. Retry-After: 120"}], payload(issue(1)),
    ]
    tool = Search(responses)
    # Failed requests count against the same rolling window as successful ones.
    candidates = CandidateProjects(projects=[project(f"example/project{i}") for i in range(10)])
    result = run_search(tmp_path, Model(), tool, projects=candidates)
    assert len(tool.calls) == 13
    assert clock[0] >= 240
    assert len(waits) >= 3
    assert tool.calls[-1] == tool.calls[-2] == tool.calls[-3] == tool.calls[-4]
    assert result["issues"] == []  # Wrong-repository response is still rejected on retry.


def test_unknown_safety_metadata_is_not_assumed_safe(tmp_path):
    missing_assignees = issue(2)
    del missing_assignees["assignees"]
    model = Model()
    result = run_search(tmp_path, model, Search([payload(
        issue(1), missing_assignees, issue(3, assignee="taken"),
        issue(4, closed_by_pull_requests={"total_count": 1}),
        issue(5, has_linked_pull_request=True), issue(6, labels=None),
        issue(7, updated_at="2026-10-01"),
    )]))
    assert [i["number"] for i in result["issues"]] == [1]
    assert [i["number"] for i in model.seen] == [1]


def test_bad_model_selection_fails_closed_with_plain_reason(tmp_path):
    result = run_search(tmp_path, Model(indices=[True, "0"]), Search([payload(issue(1))]))
    assert result["issues"] == []
    assert "Gemma" in result["reason"]


@pytest.mark.parametrize("structured", [True, False])
def test_known_mcp_omission_of_empty_assignees_uses_constrained_query_evidence(tmp_path, structured):
    available = issue(1, labels=["good first issue"] if structured else [{"name": "good first issue"}])
    del available["assignee"]
    del available["assignees"]
    if structured:
        response = {"structuredContent": payload(available, issue(2, assignees=["taken"]))}
    else:
        available["repository_url"] = "https://api.github.com/repos/example/project"
        response = [{"type": "text", "text": json.dumps(payload(available))}]
    tool = Search([response])
    result = run_search(tmp_path, Model(), tool)
    assert [i["number"] for i in result["issues"]] == [1]
    assert "no:assignee" in tool.calls[0]["query"]


def test_model_cannot_override_query_and_only_gets_compact_safe_issue_fields(tmp_path):
    model = Model(query='repo:other/repo OR is:closed -no:assignee "unsafe"')
    tool = Search([payload(*(issue(n, body="x" * 10000, private_metadata="secret") for n in range(1, 101)))])
    result = run_search(tmp_path, model, tool)
    query = tool.calls[0]["query"]
    assert query.count("repo:") == 1
    assert "is:closed" not in query and " OR " not in query
    assert "is:open" in query and "-linked:pr" in query
    assert "private_metadata" not in json.dumps(model.seen)
    assert len(json.dumps(model.seen)) < 30000
    assert [i["number"] for i in result["issues"]] == [1, 2, 3]


def test_six_calendar_month_cutoff_is_inclusive_and_clamps_month_end(tmp_path, monkeypatch):
    from help_wanted.stages import issue_search

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 31, 12, tzinfo=timezone.utc)

    monkeypatch.setattr(issue_search, "datetime", Clock)
    tool = Search([payload(
        issue(1, updated_at="2026-04-30T00:00:00Z"),
        issue(2, updated_at="2026-04-29T23:59:59Z"),
        issue(3, updated_at="2026-04-29T23:00:00-02:00"),
    )])
    result = run_search(tmp_path, Model(), tool)
    assert [i["number"] for i in result["issues"]] == [1, 3]
    assert "updated:>=2026-04-30" in tool.calls[0]["query"]


@pytest.mark.parametrize("beginner_only, expected", [(True, []), (False, [1])])
def test_typed_output_omits_empty_labels_without_relaxing_beginner_requirement(tmp_path, beginner_only, expected):
    unlabelled = issue(1)
    for key in ("labels", "assignees", "assignee"):
        del unlabelled[key]
    tool = Search([{"structuredContent": payload(unlabelled)}])
    result = run_search(tmp_path, Model(), tool, profile=ContributorProfile(beginner_friendly_only=beginner_only))
    assert [i["number"] for i in result["issues"]] == expected


def test_local_search_limit_waits_and_progress_names_each_candidate_project(tmp_path, monkeypatch, capsys):
    from help_wanted.stages import issue_search

    clock = [0.0]

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(issue_search, "monotonic", lambda: clock[0])
    monkeypatch.setattr(issue_search, "sleep", sleep)
    tool = Search([payload()] * 11)
    candidates = CandidateProjects(projects=[project(f"example/project{i}") for i in range(11)])
    run_search(tmp_path, Model(), tool, projects=candidates)
    assert len(tool.calls) == 11
    assert clock[0] >= 60
    progress = capsys.readouterr().out
    assert all(f"example/project{i}" in progress for i in range(11))
    assert "Waiting" in progress


def test_incomplete_search_is_not_presented_as_exhaustive(tmp_path):
    response = payload()
    response["incomplete_results"] = True
    result = run_search(tmp_path, Model(), Search([response]))
    assert "more" in result["reason"].lower()
