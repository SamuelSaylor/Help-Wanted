"""The single async test seam; dependencies are supplied by the caller."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from help_wanted.contracts import (
    CandidateProjects, ContributorProfile, IssueSelection, PipelineResult,
    Recommendations, SetupResult, SkillAssessment,
)
from help_wanted.stages import (
    discovery, issue_search, questionnaire, recommendations, setup, skill_scan,
)
from help_wanted.model_context import budget_messages, default_context_window, OUTPUT_TOKENS


STAGE_TOOLS = {
    "setup": (), "questionnaire": (),
    "skill_scan": ("get_me", "search_repositories", "search_pull_requests"),
    "discovery": ("search_repositories", "get_file_contents"),
    "issue_search": ("search_issues",), "recommendations": (),
}


@dataclass(frozen=True)
class StageContext:
    model: Any
    tools: tuple[Any, ...]
    username: str
    profile: ContributorProfile
    output_directory: Path

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Invoke only a tool allowed for this stage, using the async MCP API."""
        for tool in self.tools:
            if tool.name == name:
                return await tool.ainvoke(arguments)
        raise ValueError(f"GitHub tool {name!r} is not available in this stage")

    async def structured(self, schema: type[BaseModel], messages: list) -> BaseModel:
        """No stored conversation: pass only this stage's compact inputs."""
        messages = budget_messages(self.model, schema, messages)
        model = self.model
        # Explicit finite generation headroom also applies to externally supplied
        # ChatOllama models. Lightweight test models retain the existing API.
        from langchain_ollama import ChatOllama
        if isinstance(model, ChatOllama):
            model = model.model_copy(update={
                "num_ctx": model.num_ctx or default_context_window(model.model),
                "num_predict": model.num_predict if model.num_predict and model.num_predict > 0 else OUTPUT_TOKENS,
            })
        runnable = model.with_structured_output(schema, method="json_schema")
        value = await runnable.ainvoke(messages)
        return schema.model_validate(value)


class _State(TypedDict):
    outputs: dict[str, Any]
    completed: list[str]
    skipped: list[str]


async def run_pipeline(
    model, github_tools, *, profile: ContributorProfile | None = None,
    username: str = "sample-contributor", output_root: Path = Path(".help-wanted"),
    fresh: bool = False,
) -> PipelineResult:
    """Run fixed ordered stages. Existing outputs are validated before reuse.

    The skeleton's default username is explicitly a sample, not an authenticated
    identity. The setup integration must supply the login returned by get_me.
    """
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", username):
        raise ValueError("Use a GitHub username, not a folder path.")
    profile = profile or ContributorProfile()
    folder = Path(output_root) / username
    folder.mkdir(parents=True, exist_ok=True)
    stages = [
        ("setup", setup, SetupResult, None, ()),
        ("questionnaire", questionnaire, ContributorProfile, "profile.json", ("setup",)),
        ("skill_scan", skill_scan, SkillAssessment, "skills.json", ("profile",)),
        ("discovery", discovery, CandidateProjects, "projects.json", ("profile", "skills")),
        ("issue_search", issue_search, IssueSelection, "issues.json", ("profile", "skills", "projects")),
        ("recommendations", recommendations, Recommendations, "recommendations.md", ("profile", "skills", "projects", "issues")),
    ]
    if fresh:
        # Remove descendants first, before any new answers can be persisted.
        # Only these exact generated outputs belong to --fresh; keep other files.
        for _, _, _, filename, _ in reversed(stages):
            if filename:
                (folder / filename).unlink(missing_ok=True)
    output_keys = dict(zip(STAGE_TOOLS, ("setup", "profile", "skills", "projects", "issues", "recommendations")))
    graph = StateGraph(_State)

    def make_node(name, module, schema, filename, inputs):
        async def node(state):
            path = folder / filename if filename else None
            skipped = path is not None and path.exists() and not fresh
            if skipped:
                text = path.read_text(encoding="utf-8")
                value = Recommendations(markdown=text) if schema is Recommendations else schema.model_validate_json(text)
            else:
                context = StageContext(
                    model=model,
                    tools=tuple(t for t in github_tools if t.name in STAGE_TOOLS[name]),
                    username=username, profile=profile, output_directory=folder,
                )
                value = schema.model_validate(await module.run(
                    context, **{key: state["outputs"][key] for key in inputs},
                ))
                if path:
                    text = value.markdown if schema is Recommendations else value.model_dump_json(indent=2)
                    temporary = path.with_suffix(path.suffix + ".tmp")
                    temporary.write_text(text, encoding="utf-8")
                    temporary.replace(path)
            return {
                "outputs": {**state["outputs"], output_keys[name]: value},
                "completed": state["completed"] + ([] if skipped else [name]),
                "skipped": state["skipped"] + ([name] if skipped else []),
            }
        return node

    previous = START
    for name, module, schema, filename, inputs in stages:
        graph.add_node(name, make_node(name, module, schema, filename, inputs))
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    state = await graph.compile().ainvoke({"outputs": {}, "completed": [], "skipped": []})
    return PipelineResult(
        username=username, output_directory=str(folder),
        completed_stages=state["completed"], skipped_stages=state["skipped"],
        recommendations=state["outputs"]["recommendations"].markdown,
    )
