# Pipeline integration

Run `uv run help-wanted` for the walking skeleton and `uv run pytest` for tests.
The command uses a sample Contributor Profile, writes to
`.help-wanted/sample-contributor/`, and explicitly reports placeholder results.
It performs no sign-in, model download, or GitHub search. `--fresh` reruns every
stage. Real setup and stage implementations are separate tickets.

## Entry point and dependencies

```python
from help_wanted.clients import build_model, load_github_tools
from help_wanted.pipeline import run_pipeline

model = build_model()
tools = await load_github_tools(token)
result = await run_pipeline(
    model, tools, profile=profile, username=github_login,
    output_root=output_root, fresh=False,
)
```

Obtain `github_login` from the authenticated `get_me` result, not a questionnaire
answer. The setup integration owns token acquisition and selecting the login
before choosing the output folder. The skeleton's setup node is a placeholder.
The pipeline never constructs either outside dependency. `result` is a
`PipelineResult`, containing output location, completed/skipped stages and Markdown.

`build_model()` returns `ChatOllama` with `HELP_WANTED_MODEL` (default
`gemma4:e4b`) and explicit `num_ctx` (`HELP_WANTED_NUM_CTX`, default 8192).
`OLLAMA_HOST` selects the Ollama server. `load_github_tools(token)` uses hosted
MCP, falling back to `github-mcp-server stdio` when loading hosted tools fails.
Pass `transport="hosted"` or `transport="stdio"` to select explicitly.
The adapter does not acquire or save credentials.

## Independent stage modules

Each `help_wanted.stages.<name>` module exports `async run(context, **inputs)`.
Replace only the relevant module's implementation. Output models are in
`help_wanted.contracts`; the questionnaire's `ContributorProfile` matches spec #1.

| Module | Keyword inputs | Return contract | Saved output |
| --- | --- | --- | --- |
| `setup` | none | `SetupResult` | none; checked each run |
| `questionnaire` | `setup` | `ContributorProfile` | `profile.json` |
| `skill_scan` | `profile` | `SkillAssessment` | `skills.json` |
| `discovery` | `profile`, `skills` | `CandidateProjects` | `projects.json` |
| `issue_search` | `profile`, `skills`, `projects` | `IssueSelection` | `issues.json` |
| `recommendations` | `profile`, `skills`, `projects`, `issues` | `Recommendations` | `recommendations.md` |

`StageContext` exposes:

- `model`: the injected chat model. Use `model.bind_tools(context.tools)` only
  when a stage needs model tool calling; never force `tool_choice` with Ollama.
- `await context.structured(Schema, messages)`: calls
  `model.with_structured_output(Schema, method="json_schema").ainvoke(messages)`
  and validates its result. Each call receives only the supplied messages;
  the pipeline retains no conversation history.
- `await context.call_tool(name, arguments)`: calls the allowed tool's async
  `ainvoke`. Missing/disallowed tools raise `ValueError`.
- `tools`: only the stage's allowed GitHub tools (see `pipeline.STAGE_TOOLS`).
- `username`, `output_directory`, and `profile` (the initial sample/seed Profile;
  later stages must use their `profile` keyword input, which can come from cache).

Stages return data, not files. The graph validates return values, atomically
writes each output, and validates cached JSON before reuse. Invalid caches stop
the run; `--fresh` replaces them. A missing later output is recomputed from
validated earlier outputs. With cached Recommendations, Markdown is reused as-is.
Markdown is the human-readable final output; all earlier stage data uses JSON.

The stage modules contain honest empty placeholders. They make no claims about
Contributor experience, project suitability, issue eligibility, or actual Gemma
decisions. Issue filtering, ranking, recovery, and native-language writing belong
to their respective stage implementations.
