from help_wanted.contracts import SetupResult


async def run(context):
    return SetupResult(username=context.username)
