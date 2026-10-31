# AGENTS.md

## Project

Hack Day 2026 (Hacktoberfest Hack Day San Antonio, Oct 31, 2026) entry. A Python CLI that helps a beginner find an open-source project and issue to contribute to, matched to them by Gemma 4. Entered in: **MLH Best Open-Source AI Project (Gemma 4)** and **OSPO Open Source Education**, plus Best Overall automatically.

Name: **Help Wanted** (command `help-wanted`, package `help_wanted`).

Use the terms in `GLOSSARY.md` (Contributor, Contributor Profile, Skill Assessment, Candidate Project, Recommendation) in code, prompts and docs.

## Pipeline

One command, no subcommands: a beginner runs it once and goes through every stage. A LangGraph graph runs these nodes in a fixed order:

1. **Setup guide**: checks Ollama is installed and running, pulls the model, offers an Ollama cloud model if the machine can't run one locally, and signs the Contributor in to GitHub. Explains every fix in plain words.
2. **Questionnaire** → Contributor Profile (a teammate owns this stage). 15 questions, **every question is optional**; unanswered ones fall back to defaults. Mostly multiple choice, with a few free-text fields. Topics: optional GitHub username, years programming, Git/GitHub experience, past contributions, programming languages, spoken languages, industry/interests, contribution goal, time available, project popularity, contributor-count range, beginner-friendly only, recent-activity requirement, number of projects to recommend, whether to generate topic files. Gemma turns the free-text answers (interests) into search keywords. Gemma writes `master.md` from the answers, and if the Contributor opts in, topic profiles (e.g. `Python.md`, `Engineering.md`) into a `Questionaire/` folder (spelling is intentional).
3. **Skill scan** of the signed-in Contributor's public GitHub (username from the MCP `get_me` tool) → Skill Assessment. With no GitHub history, the Skill Assessment says "new to GitHub" and discovery favours projects with many beginner-labelled issues.
4. **Discovery**: Gemma writes GitHub repository searches from the Profile and Assessment (language, topic, stars, contributors, good-first-issue count, recent activity), then reranks the results → Candidate Projects. Candidate Projects = `recommendation_count × 2`, at most 6.
5. **Issue search**: one short run per Candidate Project, run sequentially (Ollama queues requests, and semantic issue search allows 10 requests/min). Gemma writes the query; code calls `search_issues` and filters the results before Gemma sees them: open, no assignee, no linked pull request, updated in the last 6 months. Issues labelled `good first issue` or `help wanted` rank higher but are not required. Gemma then picks the best 1–3. If too few issues pass, search up to 2 more Candidate Projects, then show fewer Recommendations and say why in plain words. Never relax the filter.
6. **Recommendations**: for each issue, Gemma writes why it fits the Contributor, what they will learn, and first steps, in the Contributor's native language (issue titles stay as on GitHub).

Each stage writes a Pydantic-validated JSON file (the source of truth) to `.help-wanted/<username>/` (`profile.json`, `skills.json`, `projects.json`, `issues.json`), plus a Markdown file for people to read (`recommendations.md`). On startup, a stage whose output file exists is skipped; `--fresh` reruns everything.

`profile.json` is the contract between the questionnaire and every later stage. **Open:** reconcile this with the questionnaire design in step 2 (its extra fields, `master.md` as the search input, the optional username):

```
interests: list[str]          # e.g. ["music", "games"]
industries: list[str]         # e.g. ["healthcare", "education"]
project_types: list[str]      # e.g. ["web app", "CLI tool", "library"]
coding_languages: list[str]   # e.g. ["Python", "JavaScript"]
spoken_languages: list[str]   # first entry = native language, used for Recommendations
experience_level: "none" | "some" | "comfortable"
recommendation_count: int     # how many Recommendations, e.g. 3
```

## Stack

- Python 3.13 via `uv` (`uv run help-wanted`). The system Python may be 3.15, which some compiled packages don't have wheels for yet.
- Typer + Rich for the CLI and output. No Textual.
- LangGraph for orchestration, with `langchain-ollama` `ChatOllama` for Gemma.
- Gemma 4 through Ollama only. The model comes from the `HELP_WANTED_MODEL` env var and defaults to `gemma4:e4b`. Pick per machine: `e2b` for 8 GB, `12b` for 16 GB, `26b` for 32 GB, or a cloud tag (`gemma4:cloud`) through a signed-in local Ollama.
- GitHub through the hosted GitHub MCP server (`https://api.githubcopilot.com/mcp/`, Bearer token) via `langchain-mcp-adapters`. The fallback is the local `github-mcp-server stdio` binary (`brew install github-mcp-server`).
- GitHub sign-in uses the OAuth device flow (no client secret). Order: `GITHUB_TOKEN`, then `gh auth token`, then device flow, then a pre-filled fine-grained token link. The token is saved to `~/.config/help-wanted/token` with mode 600. A token with no scopes is enough, since the tool only reads public data.

Gemma must be central to the work (judged on this), not a chat wrapper.

## Gotchas

- Ollama ignores `tool_choice`, so you can't force a tool call. Give each node only the tools it needs.
- The MCP adapter loads every tool on the server. Filter by name: skill scan uses `get_me`, `search_repositories` and `search_pull_requests`; discovery uses `search_repositories` and `get_file_contents`; issue search uses `search_issues`. Small models get worse when they see more tools.
- The MCP `search_issues` tool already does semantic search (`search_type=semantic`) and strips quotes from free text.
- Use `with_structured_output` (json_schema) for nodes that only need structured output, and keep tool calling for the nodes that search.
- Ollama's default context window is far smaller than Gemma 4's 128K/256K and truncates silently. Set `num_ctx` on `ChatOllama` explicitly (about 8K on 8 GB machines, 16–32K on bigger ones). Keep each stage a fresh conversation that receives only the previous stage's JSON, cut READMEs to their first few thousand characters, and strip MCP results down to the fields Gemma needs.

## Hackathon constraints

- Submissions close 4:00 PM on the day; live demo follows. Teams of up to 4.
- Public repo with an open-source license (MIT/Apache 2.0). README must state: what it does, how to run it, who built it, which Gemma 4 model is used, and credit any data/APIs.
- Work must be done on the day; say in the README what was built vs. reused.
- Judging: Gemma use, openness (clone-and-run), usefulness, execution; for Education: reach to non-contributors, beginner clarity without help, reusability.
- Target users are beginners (e.g. high schoolers, non-CS majors, first-gen students, non-English speakers), so keep setup and output simple.
