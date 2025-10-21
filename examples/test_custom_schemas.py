"""
Test script to demonstrate custom schema loading.

This script shows how to:
1. Load custom schemas from CUSTOM_SCHEMAS_PATH
2. List available schemas
3. Use custom schemas for query refinement

Before running, set the CUSTOM_SCHEMAS_PATH environment variable:
    export CUSTOM_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml
"""

import sys
import os
from pathlib import Path

# Add src to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from schemas import list_schemas, get_schema, describe_schema


def main():
    print("=" * 60)
    print("Query Refinement - Custom Schema Demo")
    print("=" * 60)
    print()

    # Check if CUSTOM_SCHEMAS_PATH is set
    print("1. Environment Configuration:")
    print("-" * 40)
    env_path = os.getenv("CUSTOM_SCHEMAS_PATH")
    if env_path:
        print(f"  ✓ CUSTOM_SCHEMAS_PATH: {env_path}")
        if Path(env_path).exists():
            print(f"  ✓ File exists: Yes")
        else:
            print(f"  ✗ File exists: No")
    else:
        print("  ✗ CUSTOM_SCHEMAS_PATH not set")
        print()
        print("  Please set the environment variable:")
        print("    export CUSTOM_SCHEMAS_PATH=/path/to/custom_schemas.yaml")
    print()

    # List all available schemas
    print("2. Available Schemas:")
    print("-" * 40)
    schemas = list_schemas()
    if schemas:
        for schema_name in schemas:
            print(f"  ✓ {schema_name}")
    else:
        print("  No schemas loaded.")
        print("  Make sure CUSTOM_SCHEMAS_PATH points to a valid YAML file.")
    print()

    
    # 3. If we have schemas, show details
    if schemas:
        print("3. Schema Details:")
        print("-" * 40)
        for schema_name in schemas[:2]:  # Show first 2 schemas
            try:
                schema = get_schema(schema_name)
                info = describe_schema(schema_name)
                
                print(f"\n  Schema: {schema_name}")
                print(f"  Framework: {info.get('framework', 'N/A')}")
                print(f"  Domain: {info.get('domain', 'N/A')}")
                print(f"  Dimensions: {info['num_dimensions']}")
                
                for dim in schema[:2]:  # Show first 2 dimensions
                    print(f"\n    - {dim.name} ({dim.id})")
                    print(f"      Description: {dim.description}")
                    print(f"      Follow-ups: {dim.allow_follow_up} (max: {dim.max_follow_ups if dim.allow_follow_up else 'N/A'})")
                
                if len(schema) > 2:
                    print(f"\n    ... and {len(schema) - 2} more dimensions")
                
            except Exception as e:
                print(f"  Error loading schema '{schema_name}': {e}")
        
        if len(schemas) > 2:
            print(f"\n  ... and {len(schemas) - 2} more schemas")
    
    print()
    print("=" * 60)
    print("Setup Instructions:")
    print("1. Create your custom_schemas.yaml file")
    print("2. Set CUSTOM_SCHEMAS_PATH environment variable:")
    print("   export CUSTOM_SCHEMAS_PATH=/path/to/custom_schemas.yaml")
    print("3. Install PyYAML: pip install pyyaml")
    print()
    print("Example file: examples/custom_schemas.yaml")
    print("=" * 60)
if __name__ == "__main__":
    main()
