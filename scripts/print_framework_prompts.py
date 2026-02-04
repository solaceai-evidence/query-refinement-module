"""
Print framework prompts for review and auditing.

This script loads a YAML framework definition and prints the prompts that would be
generated, allowing you to audit each component separately. It uses the production
code paths (build_refinement_messages, SynthesisPromptBuilder) to ensure you see
exactly what the LLM receives.

Updated: Uses RefinementDimension (the Pydantic model) consistently throughout.
RefinementAspect is maintained in the codebase as a backward-compatibility alias.

Usage:
    poetry run python scripts/print_framework_prompts.py <framework_yaml> <framework_name> [options]

Audit Options (show specific components):
    --global-system      Show only the global system directive prompt
    --user-context-only  Show only the user context adaptation prompt
    --dimension <id>     Show only specific dimension prompt (full: system + user)
    --all-dimensions     Show all dimension prompts together with user context
    --synthesis          Show synthesis prompt with mock refinements
    --summary            Show compact summary of framework structure

Other Options:
    --query <text>       Custom query (default: realistic sample based on framework)
    --clean              No headers/decorations, just raw prompt output
"""
import sys
from pathlib import Path
import yaml

# RefinementDimension is the new name; RefinementAspect is an alias for backward compatibility
from query_refinement_module.schema import RefinementDimension
from query_refinement_module.schema.synthesis import SynthesisPromptBuilder
from query_refinement_module.schema.prompt_builder import PromptBuilder
from query_refinement_module.schema.templates.global_system import GLOBAL_SYSTEM_PROMPT


# Sample queries for different framework types
SAMPLE_QUERIES = {
    "pico_advanced": "What is the effectiveness of cognitive behavioral therapy compared to pharmacotherapy for treating anxiety disorders in adults?",
    "mph_dissertation": "I want to examine factors associated with childhood obesity in urban school districts",
    "default": "What interventions are effective for improving health outcomes in the target population?"
}


def load_framework(yaml_path: Path, framework_name: str) -> tuple[list[RefinementDimension], dict | None]:
    """
    Load a framework from YAML, handling the user_context pattern.
    
    Returns:
        tuple: (list of RefinementDimension, user_context dict or None)
    """
    document = yaml.safe_load(yaml_path.read_text())
    framework_def = document.get(framework_name)
    if not framework_def:
        available = list(document.keys())
        raise ValueError(f"Framework '{framework_name}' not found in {yaml_path}. Available: {available}")
    
    # Handle user_context as first item (matches registry.py logic)
    user_context = None
    aspect_items = framework_def
    
    if framework_def and isinstance(framework_def[0], dict) and "user_context" in framework_def[0]:
        # Extract user_context dict from first item
        first_item = framework_def[0]
        user_context = first_item["user_context"]
        aspect_items = framework_def[1:]  # Remaining items are aspects
    
    # Attach user_context to each aspect if present
    aspects = []
    for item in aspect_items:
        if user_context:
            item = {**item, 'user_context': user_context}
        aspects.append(RefinementDimension(**item))
    
    return aspects, user_context


def print_global_system_prompt(clean: bool = False):
    """Print the global system directive."""
    if not clean:
        print("=" * 80)
        print("GLOBAL SYSTEM DIRECTIVE")
        print("=" * 80)
        print()
    print(GLOBAL_SYSTEM_PROMPT)


def print_user_context_prompt(aspects: list[RefinementDimension], clean: bool = False):
    """Print the user context adaptation prompt."""
    if not aspects or not aspects[0].user_context:
        if not clean:
            print("No user context defined for this framework")
        return
    
    builder = PromptBuilder()
    user_context_prompt = builder.render_user_context(aspects[0].user_context)
    
    if not clean:
        print("=" * 80)
        print("USER CONTEXT ADAPTATION PROMPT")
        print("=" * 80)
        print()
    print(user_context_prompt)


def print_dimension_prompt(aspect: RefinementDimension, query: str, clean: bool = False, 
                          all_aspects: list[RefinementDimension] = None):
    """Print a single dimension's complete message array structure."""
    from query_refinement_module.schema.prompt_builder import build_refinement_messages
    
    if not clean:
        print("=" * 80)
        print(f"DIMENSION MESSAGES: {aspect.aspect_name} (ID: {aspect.id})")
        if aspect.depends_on:
            print(f"Dependencies: {', '.join(aspect.depends_on)}")
        print("=" * 80)
        print()
    
    # Build mock dependency context if dimension has dependencies
    dependency_context = None
    if aspect.depends_on and all_aspects:
        dependency_context = {}
        aspect_map = {a.id: a for a in all_aspects}
        for dep_id in aspect.depends_on:
            dep_aspect = aspect_map.get(dep_id)
            if dep_aspect:
                # Create mock value based on dependency type
                mock_value = f"[Mock {dep_aspect.aspect_name}]"
                if "population" in dep_id.lower():
                    mock_value = "adults aged 18-65 with Type 2 diabetes"
                elif "intervention" in dep_id.lower():
                    mock_value = "metformin therapy, 500-1000mg daily"
                elif "clinical" in dep_id.lower() or "condition" in dep_id.lower():
                    mock_value = "Type 2 diabetes mellitus, newly diagnosed"
                
                dependency_context[dep_id] = {
                    "name": dep_aspect.aspect_name,
                    "description": dep_aspect.aspect_description,
                    "value": mock_value
                }
    
    # Build messages using the actual production code path
    messages = build_refinement_messages(
        dimension=aspect,
        query=query,
        conversation_history=[],
        dependency_context=dependency_context
    )
    
    # Print each message with role labels
    for i, msg in enumerate(messages, 1):
        role = msg['role']
        content = msg['content']
        cache_marker = " [CACHED]" if msg.get('_cache') else ""
        
        if not clean:
            print(f"[MESSAGE {i}: {role.upper()}{cache_marker}]")
            print()
        print(content)
        if not clean and i < len(messages):
            print()
            print("-" * 80)
            print()


def print_all_dimensions(aspects: list[RefinementDimension], query: str, clean: bool = False):
    """Print all dimension message structures."""
    from query_refinement_module.schema.prompt_builder import build_refinement_messages
    
    if not clean:
        print("=" * 80)
        print("ALL DIMENSIONS MESSAGE STRUCTURE")
        print("=" * 80)
        print()
    
    # Print each dimension's complete message array
    for i, aspect in enumerate(aspects):
        if not clean:
            print(f"--- DIMENSION {i+1}: {aspect.aspect_name} (ID: {aspect.id}) ---")
            print()
        
        messages = build_refinement_messages(
            dimension=aspect,
            query=query,
            conversation_history=[],
            dependency_context=None
        )
        
        for j, msg in enumerate(messages, 1):
            role = msg['role']
            content = msg['content']
            cache_marker = " [CACHED]" if msg.get('_cache') else ""
            
            if not clean:
                print(f"  [Message {j}: {role.upper()}{cache_marker}]")
                print()
            
            # Indent content for readability
            if not clean:
                for line in content.split('\n'):
                    print(f"    {line}")
            else:
                print(content)
            
            if not clean and j < len(messages):
                print()
        
        if not clean and i < len(aspects) - 1:
            print()
            print("=" * 80)
            print()


def print_synthesis_prompt(aspects: list[RefinementDimension], query: str, clean: bool = False):
    """Print the synthesis prompt with mock completed refinements."""
    if not clean:
        print("=" * 80)
        print("SYNTHESIS PROMPT")
        print("=" * 80)
        print()
    
    # Create mock refinement values
    refinement_aspect_values = {}
    for i, aspect in enumerate(aspects):
        if i % 3 == 0:
            refinement_aspect_values[aspect.id] = "[SKIPPED]"
        else:
            # Generate appropriate mock values for non-skipped dimensions
            if "population" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "adults aged 18-65 with Type 2 diabetes"
            elif "intervention" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "metformin therapy, 500-1000mg daily"
            elif "outcome" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "glycemic control (HbA1c reduction)"
            elif "comparator" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "placebo or standard care"
            elif "temporal" in aspect.id.lower() or "time" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "studies from 2018-2023"
            elif "study" in aspect.id.lower() and "type" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "randomized controlled trials and systematic reviews"
            elif "setting" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "primary care clinics in urban settings"
            elif "condition" in aspect.id.lower() or "clinical" in aspect.id.lower():
                refinement_aspect_values[aspect.id] = "mild to moderate severity, newly diagnosed"
            else:
                refinement_aspect_values[aspect.id] = f"refined value for {aspect.aspect_name}"
    
    builder = SynthesisPromptBuilder()
    
    if not clean:
        print("[SYSTEM PROMPT]")
        print()
    print(builder.get_system_prompt())
    
    if not clean:
        print()
        print("[USER PROMPT]")
        print()
    synthesis_prompt = builder.get_synthesis_prompt(
        original_input=query,
        aspectID_value_mapping=refinement_aspect_values,
        aspect_list=aspects
    )
    print(synthesis_prompt)


def print_summary(aspects: list[RefinementDimension], framework_name: str, yaml_path: Path, clean: bool = False):
    """Print a compact summary of the framework."""
    if not clean:
        print("=" * 80)
        print(f"FRAMEWORK SUMMARY: {framework_name}")
        print(f"SOURCE: {yaml_path}")
        print("=" * 80)
        print()
    
    for aspect in aspects:
        print(f"• {aspect.aspect_name} ({aspect.id})")
        print(f"  Description: {aspect.aspect_description}")
        print(f"  Follow-ups: {'Enabled' if aspect.allow_follow_up else 'Disabled'} (max: {aspect.max_follow_ups})")
        if aspect.depends_on:
            print(f"  Dependencies: {', '.join(aspect.depends_on)}")
        if aspect.examples:
            examples_dict = aspect.examples.model_dump(exclude_none=True)
            example_counts = {k: len(v) for k, v in examples_dict.items() if isinstance(v, list)}
            print(f"  Examples: {example_counts}")
        print()


def main():
    if len(sys.argv) < 3:
        print("Usage: poetry run python scripts/print_framework_prompts.py <framework_yaml> <framework_name> [options]")
        print("\nAudit Options (show specific components):")
        print("  --global-system      Show only the global system directive prompt")
        print("  --user-context-only  Show only the user context adaptation prompt")
        print("  --dimension <id>     Show only specific dimension prompt (full: system + user)")
        print("  --all-dimensions     Show all dimension prompts together with user context")
        print("  --synthesis          Show synthesis prompt with mock refinements")
        print("  --summary            Show compact summary of framework structure")
        print("\nOther Options:")
        print("  --query <text>       Custom query (default: realistic sample based on framework)")
        print("  --clean              No headers/decorations, just raw prompt output")
        print("\nExamples:")
        print("  # Show global system directive")
        print("  poetry run python scripts/print_framework_prompts.py refinement_frameworks/frameworks.yaml pico_advanced --global-system")
        print("\n  # Show user context only")
        print("  poetry run python scripts/print_framework_prompts.py refinement_frameworks/frameworks.yaml pico_advanced --user-context-only")
        print("\n  # Show specific dimension")
        print("  poetry run python scripts/print_framework_prompts.py refinement_frameworks/frameworks.yaml pico_advanced --dimension population")
        print("\n  # Show all dimensions together")
        print("  poetry run python scripts/print_framework_prompts.py refinement_frameworks/frameworks.yaml pico_advanced --all-dimensions")
        print("\n  # Show synthesis prompt")
        print("  poetry run python scripts/print_framework_prompts.py refinement_frameworks/frameworks.yaml pico_advanced --synthesis")
        print("\n  # Clean output (no decorations)")
        print("  poetry run python scripts/print_framework_prompts.py refinement_frameworks/frameworks.yaml pico_advanced --dimension population --clean")
        raise SystemExit(1)

    yaml_path = Path(sys.argv[1])
    framework_name = sys.argv[2]
    
    # Parse options
    args = sys.argv[3:]
    query = None
    dimension_id = None
    show_global_system = False
    show_user_context_only = False
    show_all_dimensions = False
    show_synthesis = False
    show_summary = False
    clean = False
    
    i = 0
    while i < len(args):
        if args[i] == '--query' and i + 1 < len(args):
            query = args[i + 1]
            i += 2
        elif args[i] == '--dimension' and i + 1 < len(args):
            dimension_id = args[i + 1]
            i += 2
        elif args[i] == '--global-system':
            show_global_system = True
            i += 1
        elif args[i] == '--user-context-only':
            show_user_context_only = True
            i += 1
        elif args[i] == '--all-dimensions':
            show_all_dimensions = True
            i += 1
        elif args[i] == '--synthesis':
            show_synthesis = True
            i += 1
        elif args[i] == '--summary':
            show_summary = True
            i += 1
        elif args[i] == '--clean':
            clean = True
            i += 1
        else:
            print(f"Unknown option: {args[i]}")
            raise SystemExit(1)

    # Load framework
    aspects, user_context = load_framework(yaml_path, framework_name)
    
    # Use framework-appropriate sample query if not specified
    if query is None:
        query = SAMPLE_QUERIES.get(framework_name, SAMPLE_QUERIES["default"])
    
    # Execute requested operation
    if show_global_system:
        print_global_system_prompt(clean=clean)
    elif show_user_context_only:
        print_user_context_prompt(aspects, clean=clean)
    elif dimension_id:
        # Find specific dimension
        dimension_aspects = [a for a in aspects if a.id == dimension_id]
        if not dimension_aspects:
            print(f"Error: Dimension '{dimension_id}' not found in framework '{framework_name}'")
            print(f"Available dimensions: {', '.join([a.id for a in aspects])}")
            raise SystemExit(1)
        print_dimension_prompt(dimension_aspects[0], query, clean=clean, all_aspects=aspects)
    elif show_all_dimensions:
        print_all_dimensions(aspects, query, clean=clean)
    elif show_synthesis:
        print_synthesis_prompt(aspects, query, clean=clean)
    elif show_summary:
        print_summary(aspects, framework_name, yaml_path, clean=clean)
    else:
        # Default: show summary
        print_summary(aspects, framework_name, yaml_path, clean=clean)


if __name__ == "__main__":
    main()