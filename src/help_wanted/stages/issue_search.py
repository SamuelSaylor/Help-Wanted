from help_wanted.contracts import IssueSelection


async def run(context, *, profile, skills, projects):
    return IssueSelection(reason="Issue search placeholder: no issues searched or selected.")
