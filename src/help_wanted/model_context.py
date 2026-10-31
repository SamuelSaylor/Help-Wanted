"""Conservative aggregate context guard for fresh structured model calls.

No tokenizer download is needed: UTF-8 bytes bound byte-fallback tokens, even
for multilingual text. Count the complete serialized messages and JSON schema,
plus template overhead and a finite output allowance. This intentionally uses
less space than an optimistic characters-per-token estimate.
"""

import json


OUTPUT_TOKENS = 1024
TEMPLATE_TOKENS = 512
DESCRIPTIVE = frozenset({
    "past_contributions", "interests", "industries", "search_keywords", "project_types",
    "contribution_goal", "summary", "evidence", "description", "readme", "body", "reason",
    "shortfall_reason",
})


class ModelContextError(ValueError):
    """The non-descriptive inputs cannot safely fit the configured window."""


def _project(value, limit, descriptive=False):
    if isinstance(value, dict):
        return {key: _project(item, limit, key in DESCRIPTIVE) for key, item in value.items()}
    if isinstance(value, list):
        items = value[:min(20, limit)] if descriptive else value
        return [_project(item, limit, descriptive) for item in items]
    if isinstance(value, str) and descriptive:
        return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
    return value


def budget_messages(model, schema, messages):
    """Return bounded copies; never change saved data or safety/issue identities.

    Instructions, titles, labels, URLs, names, numbers and policy fields cannot
    be shortened. If those alone cannot fit, stop before invoking the model.
    """
    context = getattr(model, "num_ctx", None) or 8192
    output = getattr(model, "num_predict", None)
    output = output if isinstance(output, int) and output > 0 else OUTPUT_TOKENS
    schema_size = len(json.dumps(schema.model_json_schema(), ensure_ascii=False).encode("utf-8"))

    def fits(candidate):
        size = len(json.dumps(candidate, ensure_ascii=False).encode("utf-8"))
        return size + schema_size + TEMPLATE_TOKENS + output <= context

    if fits(messages):
        return messages
    parsed = []
    for message in messages:
        data = None
        if message.get("role") == "user":
            try:
                data = json.loads(message["content"])
            except (ValueError, TypeError):
                pass
        parsed.append(data)
    for limit in (4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 0):
        candidate = [
            {**message, "content": json.dumps(_project(data, limit), ensure_ascii=False)}
            if data is not None else dict(message)
            for message, data in zip(messages, parsed, strict=True)
        ]
        if candidate and candidate[0].get("role") == "system":
            candidate[0]["content"] += (
                " Descriptive text may be shortened or omitted to fit the context window; "
                "missing detail is unknown, not evidence of absence."
            )
        if fits(candidate):
            return candidate
    raise ModelContextError(
        "There is too much information for this model's context window. "
        "Shorten your answers or increase HELP_WANTED_NUM_CTX on a machine with enough memory, then retry."
    )
