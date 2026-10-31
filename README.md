<img src="logo.png" width="160" alt="Help Wanted logo">

# Help Wanted

Find a first open-source issue that fits what you know, what you care about, and the time you have. Help Wanted is a Python command-line tool that uses **Gemma 4 through Ollama** to assess experience, find Candidate Projects, and explain how to get started in your native language.

Built for Hacktoberfest Hack Day San Antonio, October 31, 2026: MLH Best Open-Source AI Project (Gemma 4) and OSPO Open Source Education.

> [!WARNING]
> **Work in progress, not a verified end-to-end demo.** The questionnaire is teammate-owned work in [#6](https://github.com/SamuelSaylor/Hack-Day-2026/issues/6); its current placeholder supplies a default Contributor Profile rather than asking questions. Issue search is also being integrated. The full live Gemma run has **not been verified because Ollama is absent from the preparation environment**. [#9](https://github.com/SamuelSaylor/Hack-Day-2026/issues/9) remains blocked; this guide does not establish fresh-clone, demo, or production readiness.

## Get ready

You need a terminal, an internet connection, a GitHub account, and:

- [Git](https://git-scm.com/downloads), to copy this repository.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), to manage Python and install the project's dependencies.
- **Python 3.13**, installed with uv below. Use it rather than a newer system Python, which may lack compatible dependency builds.
- [Ollama](https://ollama.com/download), installed and available as the `ollama` command. Open the Ollama app, or run `ollama serve` in another terminal and leave it running.
- Enough memory and disk space for a local model, or an Ollama account for cloud inference. The first model download can be large and slow.

## Clone and run

These steps start the CLI, including Ollama setup and GitHub sign-in. Until the work listed above is merged, a run uses default answers and incomplete stages; it should not be treated as a completed Recommendation demo.

```bash
git clone https://github.com/SamuelSaylor/Hack-Day-2026.git
cd Hack-Day-2026
uv python install 3.13
uv run --python 3.13 help-wanted
```

Later, from the same folder:

```bash
uv run help-wanted
```

uv creates the Python environment and installs dependencies for you. There are **no subcommands** to learn. The setup guide checks Ollama, asks before starting a stopped local server, downloads the selected model with progress, and walks you through GitHub sign-in. It explains how to install Ollama if it is missing; it does not install Ollama itself.

### Choose a Gemma model

The model adapter defaults to **`gemma4:e4b`**. The setup helper chooses a size from detected memory when you have not set `HELP_WANTED_MODEL`:

| Computer memory | Setup selection |
| --- | --- |
| 8 GB | `gemma4:e2b` |
| 12 GB | `gemma4:e4b` |
| 16 GB | `gemma4:12b` |
| 32 GB or more | `gemma4:26b` |
| Below 8 GB | Offers `gemma4:cloud` |

These are starting points, not performance guarantees; other apps and context size also use memory. If memory cannot be detected, setup falls back to `gemma4:e4b`. You can choose explicitly (bash/zsh):

```bash
export HELP_WANTED_MODEL=gemma4:e2b
export HELP_WANTED_NUM_CTX=8192
uv run help-wanted
```

`HELP_WANTED_NUM_CTX` controls how much text the model can consider at once. The adapter explicitly sets it to **8192** by default because Ollama's default can silently truncate inputs. Start around 8192 on an 8 GB machine; 16384–32768 may suit larger machines, with additional memory use. Stages use fresh conversations and short GitHub/README excerpts to keep inputs bounded.

For cloud inference, keep local Ollama installed and running, then:

```bash
ollama signin
export HELP_WANTED_MODEL=gemma4:cloud
uv run help-wanted
```

Cloud inference requires internet access and sends model inputs to Ollama's service. Local inference runs on your machine, but GitHub searches still require internet access. `OLLAMA_HOST` optionally changes the Ollama address; it defaults to `http://localhost:11434`.

### GitHub sign-in

The sign-in helper tries `GITHUB_TOKEN`, an existing GitHub CLI sign-in (`gh auth token`), a safely saved Help Wanted token, then browser device sign-in. For device sign-in, open GitHub's displayed page and enter the short code. The public OAuth client ID is in the source; **no client secret or API key is needed**.

If device sign-in fails, the helper offers a pre-filled fine-grained token page and a hidden token prompt. Keep public repositories read-only and add no permissions. Help Wanted requests **no OAuth scopes** and only reads public data; it does not modify repositories or open pull requests. Existing tokens may have broader permissions, but those are not required by the application.

Newly entered tokens are saved to `~/.config/help-wanted/token` with owner-only permissions (`600`). Tokens from the environment or GitHub CLI are not copied there. Never share that file or paste a token into an issue.

GitHub tools normally use the [hosted GitHub MCP server](https://github.com/github/github-mcp-server). If it rejects the connection, the adapter can use the local `github-mcp-server stdio` binary. On macOS with Homebrew, install that optional fallback with `brew install github-mcp-server`. Hosted access and no-scope semantic issue search still need live verification on the demo account.

## What the pipeline does

The target flow is a fixed LangGraph sequence, not a chatbot deciding which stage to run:

1. **Setup:** prepare Ollama and sign in to GitHub.
2. **Questionnaire:** create a Contributor Profile from optional answers about interests, coding and spoken languages, experience, goals, and time. Gemma extracts search keywords from free text. **This stage currently returns defaults; #6 owns the interactive questionnaire.**
3. **Skill scan:** combine experience answers with public repositories and merged pull requests for a Gemma-written Skill Assessment. No public history means “new to GitHub,” not “cannot program.”
4. **Discovery:** Gemma writes repository searches and ranks Candidate Projects using their metadata and README excerpts. Code applies popularity and recent-push filters. Discovery selects twice the requested Recommendation count, at most six, with up to two spare projects. **Contributor-count filtering is out of scope:** `contributor_count` is retained only for Contributor Profile compatibility, not filtering or ranking.
5. **Issue search:** the intended stage searches projects sequentially, filters issues before Gemma sees them, and lets Gemma choose the best one to three per project, considering available time. This stage is being integrated.
6. **Recommendations:** Gemma writes why each selected issue fits, what you will learn, and concrete first steps in the first language in `spoken_languages`. Code preserves GitHub's original issue titles and links.

The issue-search contract requires open issues, no assignee, an update within six months, and no closing-reference pull request link (`-linked:pr`). Arbitrary PR mentions are **not** covered by that linked-PR definition. `good first issue` and `help wanted` labels rank higher and are required when `beginner_friendly_only` is set. If too few issues pass, search up to two spare Candidate Projects, then explain the shortfall rather than relax the rules. These are the intended guarantees, not evidence of a completed live run.

Gemma makes the matching decisions: search planning, evidence-based assessment, project/issue ranking, and personalized explanations. Python owns validation, issue eligibility, bounded GitHub calls, and output formatting. The questionnaire's keyword extraction and issue selection await their stage integration; the implemented assessment, discovery, and Recommendation-writing stages already call the model adapter.

## Saved work and starting over

The pipeline saves work in `.help-wanted/<github-username>/` inside the folder where you run it:

| File | Contents |
| --- | --- |
| `profile.json` | Contributor Profile: answers and preferences |
| `skills.json` | Skill Assessment and public-history evidence |
| `projects.json` | Ranked Candidate Projects and spares |
| `issues.json` | Selected issues and any shortfall reason |
| `recommendations.md` | Readable Recommendations, also shown in the terminal |

The JSON files are Pydantic-validated and are the source of truth. A rerun reuses existing stage outputs, including saved Markdown, so completed work survives a later failure. Setup and the GitHub identity check still run, so Ollama and GitHub access are needed even when outputs are cached. The CLI uses the signed-in GitHub username for the output folder.

To replace saved outputs and run every stage again:

```bash
uv run help-wanted --fresh
```

Use `--fresh` after changing model settings if you want newly generated results. A damaged saved JSON file produces a message asking you to start over. Keep your results private if your answers contain personal information; separate username folders are not an access-control boundary on a shared machine.

## Team and credits

Repository history credits **Simon ([@simonteague6](https://github.com/simonteague6))** and **Samuel ([@SamuelSaylor](https://github.com/SamuelSaylor))**. Samuel supplied the hand-drawn logo. The project is shared under the [MIT license](LICENSE).

**Built on October 31, 2026:** the Help Wanted Python package and CLI with Ollama/GitHub setup wiring, validated stage contracts and saved-output pipeline, GitHub sign-in helper, Ollama setup helper, public-history Skill Assessment, Gemma-driven discovery, Recommendation writing, and offline tests. The questionnaire and issue search are integration work in progress; this README is documentation preparation, not a claim that those blockers or the live demo are complete.

**Reused, not trained or built by this team:**

- [Google Gemma 4](https://ai.google.dev/gemma), the pretrained model family making the matching decisions. No model training or fine-tuning is claimed.
- [Ollama](https://ollama.com/), for local model serving and optional cloud inference.
- [GitHub](https://github.com/) public repository, README, issue, and contribution data, accessed through the [GitHub MCP server](https://github.com/github/github-mcp-server). No separate project dataset is bundled; repository content remains its authors' work.
- [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview), LangChain's Ollama and MCP adapters, Pydantic, Typer, Rich, HTTPX, uv, and pytest for orchestration, adapters, validation, terminal output, packaging, and offline checks.

See [AGENTS.md](AGENTS.md) for the implementation contract and [GLOSSARY.md](GLOSSARY.md) for shared project terms. A real-model demo's chosen model and results still need to be recorded on [#9](https://github.com/SamuelSaylor/Hack-Day-2026/issues/9).
