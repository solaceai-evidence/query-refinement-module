import sys
from pathlib import Path
import yaml

from query_refinement_module.schema.model import RefinementAspect
from query_refinement_module.schema.synthesis import SynthesisPromptBuilder


def load_framework(yaml_path: Path, framework_name: str) -> list[RefinementAspect]:
    document = yaml.safe_load(yaml_path.read_text())
    framework_def = document.get(framework_name)
    if not framework_def:
        raise ValueError(f"Framework '{framework_name}' not found in {yaml_path}")
    return [RefinementAspect(**aspect) for aspect in framework_def]


def print_full_unified_prompt(aspect: RefinementAspect, query: str, show_followup: bool = False):
    """Print the complete unified prompt as it would appear in production."""
    print(f"\n{'=' * 80}")
    print(f"ASPECT: {aspect.aspect_name} (ID: {aspect.id})")
    print('=' * 80)
    
    print("\n[SYSTEM PROMPT]\n")
    print(aspect.get_system_role())
    
    print("\n[USER PROMPT - INITIAL]\n")
    initial_prompt = aspect.build_unified_prompt(
        original_input=query,
        follow_up_history=[],
        dependency_context={},
        mode='initial'
    )
    print(initial_prompt)
    
    if show_followup:
        print("\n[USER PROMPT - FOLLOWUP]\n")
        followup_prompt = aspect.build_unified_prompt(
            original_input=query,
            follow_up_history=[
                {'question': 'What age range?', 'response': 'Adults 18-65'},
                {'question': 'Any specific gender?', 'response': 'All genders'}
            ],
            dependency_context={
                'population': {
                    'name': 'Population',
                    'description': 'Target population',
                    'value': 'Adults aged 18-65, all genders'
                }
            },
            mode='followup'
        )
        print(followup_prompt)


def print_summary(aspect: RefinementAspect):
    """Print a compact summary of the aspect configuration."""
    print(f"• {aspect.aspect_name} ({aspect.id})")
    print(f"  Description: {aspect.aspect_description}")
    print(f"  Follow-ups: {'Enabled' if aspect.allow_follow_up else 'Disabled'} (max: {aspect.max_follow_ups})")
    if aspect.depends_on:
        print(f"  Dependencies: {', '.join(aspect.depends_on)}")
    if aspect.examples:
        example_counts = {k: len(v) for k, v in aspect.examples.items()}
        print(f"  Examples: {example_counts}")
    print()


def print_synthesis_prompt(aspects: list[RefinementAspect], query: str):
    """Print the synthesis prompt with mock completed refinements."""
    print(f"\n{'=' * 80}")
    print("SYNTHESIS STEP")
    print('=' * 80)
    
    refinement_aspect_values = {}
    for i, aspect in enumerate(aspects):
        if i % 3 == 0:
            refinement_aspect_values[aspect.id] = "[SKIPPED]"
        elif i % 3 == 1:
            refinement_aspect_values[aspect.id] = "[CLEAR_IN_ORIGINAL]"
        else:
            if "population" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "adults aged 18-65 with Type 2 diabetes"
            elif "intervention" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "metformin therapy, 500-1000mg daily"
            elif "outcome" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "glycemic control (HbA1c reduction)"
            elif "temporal" in aspect.id.lower() or "time" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "studies from 2018-2023"
            else:
                refinement_aspect_values[aspect.id] = f"refined value for {aspect.aspect_name}"
    
    builder = SynthesisPromptBuilder()
    
    print("\n[SYSTEM PROMPT]\n")
    print(builder.get_system_prompt())
    
    print("\n[USER PROMPT]\n")
    synthesis_prompt = builder.get_synthesis_prompt(
        original_input=query,
        aspectID_value_mapping=refinement_aspect_values,
        aspect_list=aspects
    )
    print(synthesis_prompt)
    
    print("\n[MOCK REFINEMENT VALUES]\n")
    for aspect in aspects:
        value = refinement_aspect_values.get(aspect.id, "[NOT SET]")
        print(f"{aspect.id}: {value}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python print_framework_prompts.py <framework_yaml> <framework_name> [options]")
        print("\nOptions:")
        print("  --query <text>       Custom query (default: 'sample research query')")
        print("  --aspect <id>        Show only specific aspect by ID")
        print("  --summary            Show compact summary instead of full prompts")
        print("  --followup           Also show follow-up mode example")
        print("  --synthesis          Show synthesis (final) prompt with mock refinements")
        print("\nExamples:")
        print("  python scripts/print_framework_prompts.py examples/pico_advanced_complete.yaml pico_advanced")
        print("  python scripts/print_framework_prompts.py examples/mph_dissertation.yaml mph_dissertation --aspect population")
        print("  python scripts/print_framework_prompts.py examples/pico_advanced_complete.yaml pico_advanced --query 'diabetes treatment' --followup")
        print("  python scripts/print_framework_prompts.py examples/pico_advanced_complete.yaml pico_advanced --synthesis")
        raise SystemExit(1)

    yaml_path = Path(sys.argv[1])
    framework_name = sys.argv[2]
    
    # Parse options
    args = sys.argv[3:]
    query = "sample research query"
    aspect_filter = None
    show_summary = False
    show_followup = False
    show_synthesis = False
    
    i = 0
    while i < len(args):
        if args[i] == '--query' and i + 1 < len(args):
            query = args[i + 1]
            i += 2
        elif args[i] == '--aspect' and i + 1 < len(args):
            aspect_filter = args[i + 1]
            i += 2
        elif args[i] == '--summary':
            show_summary = True
            i += 1
        elif args[i] == '--followup':
            show_followup = True
            i += 1
        elif args[i] == '--synthesis':
            show_synthesis = True
            i += 1
        else:
            print(f"Unknown option: {args[i]}")
            raise SystemExit(1)

    aspects = load_framework(yaml_path, framework_name)
    
    # Filter by aspect ID if specified
    if aspect_filter:
        aspects = [a for a in aspects if a.id == aspect_filter]
        if not aspects:
            print(f"❌ Aspect '{aspect_filter}' not found in framework '{framework_name}'")
            raise SystemExit(1)

    print(f"\n{'=' * 80}")
    print(f"Framework: {framework_name}")
    print(f"Source: {yaml_path}")
    print(f"Query: {query}")
    print(f"Total Aspects: {len(aspects)}")
    if aspect_filter:
        aspects = [a for a in aspects if a.id == aspect_filter]
        if not aspects:
            print(f"Error: Aspect '{aspect_filter}' not found in framework '{framework_name}'")
            raise SystemExit(1)

    print(f"{'=' * 80}")
    print(f"FRAMEWORK: {framework_name}")
    print(f"SOURCE: {yaml_path}")
    print(f"QUERY: {query}")
    print(f"ASPECTS: {len(aspects)}")
    print('=' * 80)

    if show_synthesis:
        print_synthesis_prompt(aspects, query)
    elif show_summary:
        for aspect in aspects:
            print_summary(aspect)
    else:
        for aspect in aspects:
            print_full_unified_prompt(aspect, query, show_followup=show_followup)


if __name__ == "__main__":
    main()