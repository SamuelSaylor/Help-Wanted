"""Shared MCP decoding and bounded search-limit waiting.

Decoding never supplies safety evidence itself: callers validate the payload.
Only an actual structured-content wrapper carries typed-result provenance.
"""

import asyncio
from dataclasses import dataclass
import json
import re

from rich.console import Console
from help_wanted.theme import themed_console


@dataclass(frozen=True)
class GitHubResult:
    payload: dict | list
    structured: bool = False


def normalize(value, *, structured=False):
    for _ in range(20):
        if hasattr(value, "model_dump"):
            value = value.model_dump(by_alias=True)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError(value) from None
        elif isinstance(value, dict):
            if (value.get("isError") or value.get("is_error") or "error" in value
                    or re.search(r"rate[ -]?limit|\b429\b", str(value.get("message", "")), re.I)):
                raise ValueError(str(value))
            key = next((k for k in ("structuredContent", "structured_content")
                        if value.get(k) is not None), None)
            if key:
                value, structured = value[key], True
            elif isinstance(value.get("content"), (list, dict)):
                value = value["content"]
            elif (isinstance(value.get("content"), str)
                  and set(value) <= {"content", "isError", "is_error"}):
                # A JSON-only legacy wrapper, not a file with an encoding.
                try:
                    decoded = json.loads(value["content"])
                except json.JSONDecodeError:
                    if re.search(r"rate[ -]?limit|\b429\b", value["content"], re.I):
                        raise ValueError(value["content"]) from None
                    return GitHubResult(value, structured)
                value = decoded
            else:
                return GitHubResult(value, structured)
        elif isinstance(value, list):
            resources = [block["resource"] for block in value if isinstance(block, dict)
                         and isinstance(block.get("resource"), dict) and "text" in block["resource"]]
            if len(resources) == 1 and isinstance(resources[0]["text"], str):
                return GitHubResult({"content": resources[0]["text"], "encoding": "utf-8"}, structured)
            texts = [block["text"] for block in value if isinstance(block, dict)
                     and block.get("type") == "text" and isinstance(block.get("text"), str)]
            if len(texts) == 1:
                value = texts[0]
            elif any(isinstance(block, dict) and "type" in block for block in value):
                raise ValueError("GitHub returned ambiguous content blocks. Please try again.")
            else:
                return GitHubResult(value, structured)
        else:
            break
    raise ValueError("GitHub returned an unreadable response. Please try again.")


async def search(context, name, arguments, *, before=None, pause=None, console=None):
    """Retry the identical read-only search, at most four attempts."""
    pause = pause or asyncio.sleep
    console = console or themed_console()
    for attempt in range(4):
        if before:
            await before()
        try:
            return normalize(await context.call_tool(name, arguments))
        except Exception as error:
            text = str(error).lower()
            if attempt == 3 or not re.search(r"rate[ -]?limit|\b429\b", text):
                raise ValueError("GitHub could not complete this search. Check your connection or sign-in and try again.") from None
            delay = 60.0
            retry = re.search(r"retry[-_ ]after['\"\s:=]+(\d+)", text)
            if retry:
                delay = max(delay, float(retry[1]))
            headers = getattr(getattr(error, "response", None), "headers", {})
            try:
                delay = max(delay, float(headers.get("retry-after", 0)))
            except (ValueError, TypeError):
                pass
            console.print("GitHub needs a pause before searching again. Waiting…")
            await pause(delay)
