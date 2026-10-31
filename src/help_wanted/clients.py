"""Production adapters. Construction is outside the pipeline test seam."""

import os
import shutil
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama


def build_model(*, num_ctx: int | None = None) -> ChatOllama:
    context = num_ctx if num_ctx is not None else int(os.getenv("HELP_WANTED_NUM_CTX", "8192"))
    if context < 1:
        raise ValueError("The model context window must be a positive number.")
    return ChatOllama(
        model=os.getenv("HELP_WANTED_MODEL", "gemma4:e4b"), num_ctx=context,
        base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        temperature=0,
    )


async def load_github_tools(token: str, *, transport: str = "auto") -> list[Any]:
    """Load hosted MCP tools; auto retries through the local stdio binary.

    Token acquisition belongs to the setup guide, not this adapter. Never log
    the underlying exception: HTTP errors may contain authentication headers.
    """
    if not token:
        raise ValueError("Sign in to GitHub before loading its tools.")
    if transport not in {"auto", "hosted", "stdio"}:
        raise ValueError("GitHub transport must be auto, hosted, or stdio.")
    if transport != "stdio":
        client = MultiServerMCPClient({"github": {
            "transport": "streamable_http", "url": "https://api.githubcopilot.com/mcp/",
            "headers": {"Authorization": f"Bearer {token}"},
        }}, handle_tool_errors=False)
        try:
            return await client.get_tools()
        except Exception:
            if transport == "hosted":
                raise RuntimeError("GitHub's hosted tools are unavailable. Try the local GitHub MCP server.") from None
    binary = shutil.which("github-mcp-server")
    if not binary:
        raise RuntimeError(
            "GitHub's tools are unavailable. Install the fallback with "
            "`brew install github-mcp-server`, then try again."
        ) from None
    client = MultiServerMCPClient({"github": {
        "transport": "stdio", "command": binary, "args": ["stdio"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token},
    }}, handle_tool_errors=False)
    try:
        return await client.get_tools()
    except Exception:
        raise RuntimeError("The local GitHub tools could not start. Check your sign-in and try again.") from None
