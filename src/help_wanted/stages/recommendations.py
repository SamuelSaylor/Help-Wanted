from help_wanted.contracts import Recommendations


async def run(context, *, profile, skills, projects, issues):
    return Recommendations(markdown=(
        "# Help Wanted\n\n"
        "Pipeline placeholder: no real Recommendations have been generated.\n\n"
        "The questionnaire, Skill Assessment, discovery and issue search stages "
        "are not implemented in this walking skeleton.\n"
    ))
