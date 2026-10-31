# Pipeline integration

Run `uv run help-wanted` for the single-command pipeline and `uv run pytest` for
tests, using Python 3.13. The CLI prepares Ollama (including offering a model
download or cloud model), signs the Contributor in to GitHub, loads GitHub MCP
tools, and calls authenticated `get_me`. It validates that login before creating
`.help-wanted/<login>/`. No questionnaire answer selects an identity or folder.

**The questionnaire is not integrated yet.** The CLI visibly warns that a new run
uses a default Contributor Profile, not collected answers. An existing validated
`profile.json` is reused on resume. `--fresh` reruns every stage, currently using
the default Profile. Questionnaire implementation belongs to its teammate.

## Entry point and dependencies

```python
from help_wanted.clients import build_model, load_github_tools
from help_wanted.clients import get_github_username
from help_wanted.auth import get_github_token
from help_wanted.ollama_setup import prepare_ollama
from help_wanted.pipeline import run_pipeline

model_name = await prepare_ollama(console=console)
token = await get_github_token(console=console)
tools = await load_github_tools(token)
github_login = await get_github_username(tools)
model = build_model(model_name)
result = await run_pipeline(
    model, tools, username=github_login, fresh=False,
)
```

The CLI owns setup and sign-in. `get_github_username` accepts MCP JSON dictionaries,
JSON text, text blocks and content wrappers, and rejects missing/unsafe logins.
The graph's setup node reports readiness from the supplied identity, model and
tools; it performs no network calls or independent authentication. Tests can
still inject just the model and GitHub tools into `run_pipeline`. `result` is a
`PipelineResult`, containing output location, completed/skipped stages and Markdown.

`build_model(model_name=None)` returns `ChatOllama` with the setup-selected model,
or `HELP_WANTED_MODEL` (default `gemma4:e4b`) when no name is supplied, and explicit
`num_ctx` (`HELP_WANTED_NUM_CTX`, default 8192).
Generation has a finite 1024-token allowance by default.
`OLLAMA_HOST` selects the Ollama server. `load_github_tools(token)` uses hosted
MCP, falling back to `github-mcp-server stdio` when loading hosted tools fails.
Pass `transport="hosted"` or `transport="stdio"` to select explicitly.
The adapter does not acquire or save credentials.

Expected setup/sign-in failures show safe, plain-word guidance. Unexpected
network, model and tool failures show a retry message without raw exceptions,
HTTP headers or tokens. Keyboard cancellation remains cancellation. Completed
stage files remain available for a later run.

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
  the pipeline retains no conversation history. Before invocation, an aggregate
  guard counts UTF-8 bytes of the complete messages and schema, reserves 512
  tokens for the chat template and the configured output allowance, and checks
  against `num_ctx` (8192 for test models without it). This conservative
  byte-token ceiling handles multilingual input without a tokenizer download.
  If needed, only descriptive text/evidence/README excerpts are shortened in
  copies; saved JSON and issue identities, URLs, labels and safety fields remain
  intact. Irreducibly large inputs stop with guidance to shorten answers or
  increase `HELP_WANTED_NUM_CTX`, rather than relying on silent truncation.
- `await context.call_tool(name, arguments)`: calls the allowed tool's async
  `ainvoke`. Missing/disallowed tools raise `ValueError`.
- `tools`: only the stage's allowed GitHub tools (see `pipeline.STAGE_TOOLS`).
- `username`, `output_directory`, and `profile` (the initial default/seed Profile;
  later stages must use their `profile` keyword input, which can come from cache).

Stages return data, not files. The graph validates return values, atomically
writes each output, and validates cached JSON before reuse. Invalid caches stop
the run. Before running stages, `--fresh` invalidates exactly `profile.json`,
`skills.json`, `projects.json`, `issues.json` and `recommendations.md`, removing
descendants first and keeping unrelated files. An interrupted fresh run can
resume its completed stages without reusing descendants from an earlier run.
A missing later output is recomputed from
validated earlier outputs. With cached Recommendations, Markdown is reused as-is.
Markdown is the human-readable final output; all earlier stage data uses JSON.

## Search rules and remaining verification

Discovery uses `stars:` and `pushed:>` for popularity and recent activity.
`contributor_count` remains a Contributor Profile compatibility field, not a
search filter. Issue search must keep issues open, unassigned, updated within
six months and without a closing-reference pull request (`-linked:pr`). Arbitrary
PR mentions are outside that guarantee. Beginner labels rank higher and are
required with `beginner_friendly_only`; shortfalls never relax eligibility.
All repository, pull-request and issue searches share up to four identical-query
attempts on GitHub search-limit errors, waiting at least 60 seconds (or a larger
Retry-After). Issue searches also observe the local ten-requests/minute window.
Identity and stages share MCP envelope decoding; issue eligibility still checks
the result shape and retains typed-result provenance for omitted empty fields.

Skill Assessment and Recommendation writing use structured Gemma calls; discovery
and issue-search implementations are integrated independently. Their individual
tests and the CLI's scripted external boundaries do not establish live model
quality or hosted MCP availability. A live Gemma 4 / GitHub end-to-end run remains
a manual verification blocker, alongside questionnaire integration. CLI tests
perform no downloads, sign-in interactions or live network calls.
