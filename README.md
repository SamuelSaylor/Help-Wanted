<p align="center">
  <img src="https://raw.githubusercontent.com/SamuelSaylor/Help-Wanted/main/logo.png" width="160" alt="Help Wanted logo">
</p>

<p align="center">Nathan Davies · Samuel Saylor · Simon Teague · Fredy Mata</p>

# Help Wanted

Help Wanted finds a first open-source issue that fits what you know, what you care about, and how much time you have. You run one command, answer a few optional questions, and get a short list of real GitHub issues with a plain explanation of how to start each one, written in your own language.

Gemma 4 runs locally through Ollama and makes the decisions at every stage: it turns your answers into searches, judges your experience, ranks projects and issues, and writes the guides. Built for Hacktoberfest Hack Day San Antonio 2026, for the MLH Best Open-Source AI Project (Gemma 4) and OSPO Open Source Education tracks.

## Why it exists

Most people who have never contributed to open source can't tell which projects are friendly, which issues are still free, or which ones match their skills. A "good first issue" search gives them links but no reason to pick one and no idea what to do next. This is aimed at beginners: high schoolers, non-CS majors, first-generation students, and people whose first language isn't English.

The project is MIT licensed, and issues and pull requests are welcome. [GLOSSARY.md](https://github.com/SamuelSaylor/Help-Wanted/blob/main/GLOSSARY.md) and [AGENTS.md](https://github.com/SamuelSaylor/Help-Wanted/blob/main/AGENTS.md) explain the terms and design decisions before you read the code.

## How it works

A fixed [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) pipeline runs six stages in order:

1. **Setup:** checks Ollama, pulls the model, and signs you in to GitHub.
2. **Questionnaire:** asks about your interests, languages, experience, goals and time. Every question is optional. Gemma pulls search keywords out of your free-text answers.
3. **Skill scan:** combines your answers with your public repositories and merged pull requests. If you have no public history, you are treated as new to GitHub.
4. **Discovery:** Gemma writes repository searches and ranks the results by reading their READMEs. It picks twice as many projects as the recommendations you asked for, up to six.
5. **Issue search:** code filters issues first, then Gemma picks the best one to three per project. An issue must be open, unassigned, updated in the last six months, and have no linked pull request. Beginner labels rank higher, and are required if you chose beginner-friendly only. These rules are never relaxed. If too few issues pass, you get fewer recommendations and a reason.
6. **Recommendations:** Gemma explains why each issue fits you, what you will learn, and the first steps, in your native language. Issue titles stay exactly as they appear on GitHub.

Results are saved to `.help-wanted/<github-username>/` as validated JSON (`profile.json`, `skills.json`, `projects.json`, `issues.json`) plus a readable `recommendations.md`.

## Run it

You need Python 3.13 or newer, [Ollama](https://ollama.com/download) (installed and running), and a GitHub account. Install with [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/getting-started/installation/), then run it:

```bash
pipx install help-wanted
help-wanted
```

With uv, use `uv tool install help-wanted` instead. To run from source, clone the repo and use `uv run help-wanted` inside it.

There are no subcommands. The setup guide downloads the model with a progress bar and walks you through GitHub sign-in. It does not install Ollama for you, but it tells you where to get it.

To change your answers, or to rerun every stage:

```bash
help-wanted --fresh
```

A rerun otherwise reuses saved stages, so a failure late in the pipeline doesn't cost you the questionnaire.

### Which Gemma 4 model

The default is `gemma4:e4b`. Setup asks whether you want Ollama cloud (`gemma4:cloud`, which sends model inputs to Ollama's service and needs an Ollama account). If you decline, it picks a local size from your memory:

| Memory | Model |
| --- | --- |
| 8 GB | `gemma4:e2b` |
| 12 GB | `gemma4:e4b` |
| 16 GB | `gemma4:12b` |
| 32 GB or more | `gemma4:26b` |

Below 8 GB, setup offers the cloud model again. These sizes are starting points, not guarantees. To skip the prompts, set the model yourself:

```bash
export HELP_WANTED_MODEL=gemma4:e2b
export HELP_WANTED_NUM_CTX=8192
uv run help-wanted
```

`HELP_WANTED_NUM_CTX` sets the context window and defaults to 8192 for local models and 131072 for cloud. Ollama's own default is much smaller and truncates silently, so the app always sets it explicitly. `OLLAMA_HOST` changes the Ollama address from `http://localhost:11434`.

### GitHub sign-in

Setup tries these in order: the `GITHUB_TOKEN` environment variable, your GitHub CLI login, a token Help Wanted saved earlier, then browser sign-in where you type a short code into a GitHub page. If that fails, it links to a pre-filled fine-grained token page. No client secret is needed.

Help Wanted requests no OAuth scopes and only reads public data. It never changes repositories or opens pull requests. Tokens you type in are saved to `~/.config/help-wanted/token` with owner-only permissions. Keep that file private.

GitHub access goes through the [hosted GitHub MCP server](https://github.com/github/github-mcp-server). If it refuses the connection, the app falls back to a local `github-mcp-server stdio` binary (`brew install github-mcp-server` on macOS).

## Tests

```bash
uv run pytest
```

**Built on October 31, 2026:** the `help_wanted` package and CLI, including the Ollama setup guide, GitHub sign-in, questionnaire, skill scan, discovery, issue search, recommendation writing, and the offline tests.

**Reused:**

- [Gemma 4](https://ai.google.dev/gemma) is the pretrained model. We did no training or fine-tuning.
- [Ollama](https://ollama.com/) serves it locally, with optional cloud inference.
- GitHub's public repository, README and issue data, through the GitHub MCP server. No dataset is bundled.
- LangGraph, the LangChain Ollama and MCP adapters, Pydantic, Typer, Rich, questionary, HTTPX, uv and pytest.
