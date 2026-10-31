"""Single-command walking skeleton; real setup and stages plug in separately."""

import asyncio

from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown
import typer

from help_wanted.clients import build_model
from help_wanted.pipeline import run_pipeline


app = typer.Typer(add_completion=False)


@app.command()
def main(fresh: bool = typer.Option(False, "--fresh", help="Run every stage again.")) -> None:
    console = Console()
    console.print("Help Wanted walking skeleton — sample Contributor Profile and placeholder stages.")
    try:
        # No network calls or sign-in until the setup guide stage is implemented.
        result = asyncio.run(run_pipeline(build_model(), [], fresh=fresh))
    except ValidationError:
        console.print("Saved answers could not be read. Run `help-wanted --fresh` to start over.")
        raise typer.Exit(1) from None
    except (OSError, ValueError, RuntimeError):
        console.print("Help Wanted could not finish. Check your settings and output folder, then try again.")
        raise typer.Exit(1) from None
    console.print(Markdown(result.recommendations))
    console.print(f"Saved to {result.output_directory}")
    if result.skipped_stages:
        console.print("Reused saved stages. Use --fresh to start over.")
