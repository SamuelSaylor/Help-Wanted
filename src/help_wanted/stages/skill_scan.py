from help_wanted.contracts import SkillAssessment


async def run(context, *, profile):
    return SkillAssessment(
        username=context.username,
        experience_level="not assessed",
        summary="Skill Assessment placeholder: no GitHub history has been analysed.",
    )
