from help_wanted.contracts import SetupResult


async def run(context):
    return SetupResult(
        username=context.username,
        message=f"Ready to continue as {context.username}, using the supplied model and GitHub tools.",
    )
