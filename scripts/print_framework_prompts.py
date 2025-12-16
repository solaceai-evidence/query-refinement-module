import sys
from pathlib import Path
import yaml

from query_refinement_module.schema.model import RefinementAspect


def load_framework(yaml_path: Path, framework_name: str) -> list[RefinementAspect]:
    document = yaml.safe_load(yaml_path.read_text())
    framework_def = document.get(framework_name)
    if not framework_def:
        raise ValueError(f"Framework '{framework_name}' not found in {yaml_path}")
    return [RefinementAspect(**aspect) for aspect in framework_def]


def main():
    if len(sys.argv) < 3:
        print("Usage: python print_framework_prompts.py <framework_yaml> <framework_name>")
        raise SystemExit(1)

    yaml_path = Path(sys.argv[1])
    framework_name = sys.argv[2]
    statement = "{statement}"

    aspects = load_framework(yaml_path, framework_name)

    print(f"\n=== Prompts for framework '{framework_name}' ({yaml_path}) ===\n")
    for aspect in aspects:
        system_prompt, user_prompt = aspect.get_prompts(statement)
        print(f"# Refinement Aspect(s): {aspect.aspect_name} ({aspect.id})\n")
        print("SYSTEM PROMPT:")
        print(system_prompt.strip())
        print("\nREFINEMENT INSTRUCTIONS:")
        print(user_prompt.strip())
        print("\n" + "-" * 80 + "\n")


if __name__ == "__main__":
    main()