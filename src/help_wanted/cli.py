"""Set up external services, then run the single Contributor pipeline."""

import asyncio
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown
import typer

from help_wanted.auth import AuthError, get_github_token
from help_wanted.clients import GitHubClientError, build_model, get_github_username, load_github_tools
from help_wanted.ollama_setup import SetupError, prepare_ollama
from help_wanted.pipeline import run_pipeline
from help_wanted.model_context import ModelContextError


app = typer.Typer(add_completion=False)


async def _run(console: Console, *, fresh: bool):
    model_name = await prepare_ollama(console=console)
    token = await get_github_token(console=console)
    tools = await load_github_tools(token)
    username = await get_github_username(tools)
    console.print(f"Signed in to GitHub as {username}.")
    if fresh or not (Path(".help-wanted") / username / "profile.json").exists():
        console.print(
            "The questionnaire is not integrated yet. Using a default Contributor Profile; "
            "your interests and experience have not been collected."
        )
    else:
        console.print("Reusing your saved Contributor Profile. The questionnaire is not integrated yet.")
    return await run_pipeline(build_model(model_name), tools, username=username, fresh=fresh)


@app.command()
def main(fresh: bool = typer.Option(False, "--fresh", help="Run every stage again.")) -> None:
    console = Console()
    console.print("Help Wanted — find an open-source contribution.")
    try:
        result = asyncio.run(_run(console, fresh=fresh))
    except (SetupError, AuthError, GitHubClientError, ModelContextError) as error:
        console.print(str(error), markup=False)
        raise typer.Exit(1) from None
    except ValidationError:
        console.print(
            "Saved answers or Gemma's reply could not be read. Try again; "
            "if saved answers are invalid, run `help-wanted --fresh` to start over."
        )
        raise typer.Exit(1) from None
    except Exception:
        console.print(
            "Help Wanted could not finish. Check that Ollama and your chosen Gemma model "
            "are running, your GitHub sign-in and connection work, and your output folder "
            "can be written. Then try again; saved stages will be reused."
        )
        raise typer.Exit(1) from None
    console.print(Markdown(result.recommendations))
    console.print(f"Saved to {result.output_directory}")
    if result.skipped_stages:
        console.print("Reused saved stages. Use --fresh to start over.")
