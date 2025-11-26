from query_refinement_module.schema import RefinementAspect

def make_aspect(
    *,
    aspect_id: str = "demo",
    name: str = "Demo Aspect",
    description: str = "Demo description",
    analysis_prompt: str = "Analyze {query}",
    system_prompt: str = None,
    response_format: dict = None,
    examples: dict = None,
    depends_on: list = None,
    allow_follow_up: bool = False,
    max_follow_ups: int = 3,
) -> RefinementAspect:
    return RefinementAspect(
        id=aspect_id,
        name=name,
        description=description,
        analysis_prompt=analysis_prompt,
        system_prompt=system_prompt,
        response_format=response_format,
        examples=examples,
        depends_on=depends_on or [],
        allow_follow_up=allow_follow_up,
        max_follow_ups=max_follow_ups,
    )
