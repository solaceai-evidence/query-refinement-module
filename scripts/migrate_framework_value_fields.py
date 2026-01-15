#!/usr/bin/env python3
"""
Migrate framework YAML files to include value_field_type and value_field_description.

This script:
1. Scans all YAML files in examples/
2. Adds default value_field_type: string to aspects missing it
3. Suggests better types based on aspect content
4. Creates backup files before modification
"""

import yaml
import re
from pathlib import Path
from typing import Dict, Any, List
import shutil
from datetime import datetime


def suggest_value_type(aspect: Dict[str, Any]) -> str:
    """Suggest appropriate value_field_type based on aspect content."""
    aspect_id = aspect.get('id', '').lower()
    aspect_name = aspect.get('aspect_name', '').lower()
    description = aspect.get('aspect_description', '').lower()
    
    # Check for indicators of complex types
    all_text = f"{aspect_id} {aspect_name} {description}"
    
    # Array indicators
    array_keywords = ['outcomes', 'factors', 'criteria', 'components', 'list', 'multiple']
    if any(keyword in all_text for keyword in array_keywords):
        return 'array'
    
    # Object indicators (multi-part structures)
    object_keywords = [
        'population and setting', 'design and timeframe', 
        'intervention or exposure', 'study design',
        'characteristics', 'specification'
    ]
    if any(keyword in all_text for keyword in object_keywords):
        return 'object'
    
    # Boolean indicators
    boolean_keywords = ['yes/no', 'presence', 'whether', 'flag']
    if any(keyword in all_text for keyword in boolean_keywords):
        return 'boolean'
    
    # Number indicators
    number_keywords = ['age', 'count', 'duration', 'number', 'quantity', 'size']
    if any(keyword in all_text for keyword in number_keywords):
        # But some of these should be strings for ranges
        if 'range' in all_text or 'group' in all_text:
            return 'string'
        return 'number'
    
    # Default to string
    return 'string'


def generate_value_description(aspect: Dict[str, Any], value_type: str) -> str:
    """Generate a helpful value_field_description based on aspect details."""
    aspect_name = aspect.get('aspect_name', 'value')
    aspect_desc = aspect.get('aspect_description', '')
    
    # Get examples if available
    examples = aspect.get('examples', {})
    clear_examples = examples.get('clear', [])
    
    description_parts = []
    
    # Base description
    if aspect_desc:
        description_parts.append(f"The {aspect_desc}")
    
    # Type-specific guidance
    if value_type == 'object':
        description_parts.append("Expected format: object with relevant fields")
    elif value_type == 'array':
        description_parts.append("Expected format: array of related items")
    elif value_type == 'boolean':
        description_parts.append("Expected format: true or false")
    elif value_type == 'number':
        description_parts.append("Expected format: numeric value")
    
    # Add examples if available
    if clear_examples:
        example_statements = []
        for ex in clear_examples[:3]:  # Max 3 examples
            if isinstance(ex, dict):
                if 'statement' in ex:
                    example_statements.append(f'"{ex["statement"]}"')
                elif 'value' in ex:
                    example_statements.append(f'"{ex["value"]}"')
        
        if example_statements:
            description_parts.append(f"Examples: {', '.join(example_statements)}")
    
    return '. '.join(description_parts) + '.' if description_parts else f"The {aspect_name} value"


def migrate_aspect(aspect: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """Add value_field_type and value_field_description to an aspect if missing."""
    migrated = aspect.copy()
    changes = []
    
    # Check if fields already exist
    has_type = 'value_field_type' in aspect
    has_description = 'value_field_description' in aspect
    
    if not has_type:
        suggested_type = suggest_value_type(aspect)
        migrated['value_field_type'] = suggested_type
        changes.append(f"Added value_field_type: {suggested_type}")
    
    if not has_description:
        value_type = migrated.get('value_field_type', 'string')
        description = generate_value_description(aspect, value_type)
        migrated['value_field_description'] = description
        changes.append(f"Added value_field_description")
    
    if changes and not dry_run:
        aspect_name = aspect.get('aspect_name', aspect.get('id', 'unknown'))
        print(f"  - {aspect_name}: {', '.join(changes)}")
    
    return migrated, changes


def migrate_yaml_file(file_path: Path, dry_run: bool = False, backup: bool = True) -> bool:
    """Migrate a single YAML file."""
    print(f"\nProcessing: {file_path.name}")
    
    try:
        # Load YAML
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        
        if not data:
            print(f"  ⚠️  Empty or invalid YAML")
            return False
        
        # Track changes
        total_changes = 0
        
        # Process each framework in the file
        for framework_name, aspects in data.items():
            if not isinstance(aspects, list):
                continue
            
            print(f"\n  Framework: {framework_name}")
            
            migrated_aspects = []
            for aspect in aspects:
                if not isinstance(aspect, dict):
                    migrated_aspects.append(aspect)
                    continue
                
                migrated_aspect, changes = migrate_aspect(aspect, dry_run)
                migrated_aspects.append(migrated_aspect)
                
                if changes:
                    total_changes += len(changes)
            
            data[framework_name] = migrated_aspects
        
        if total_changes == 0:
            print(f"  ✓ No changes needed")
            return False
        
        if dry_run:
            print(f"\n  [DRY RUN] Would make {total_changes} changes")
            return False
        
        # Create backup
        if backup:
            backup_path = file_path.with_suffix(f'.yaml.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
            shutil.copy2(file_path, backup_path)
            print(f"\n  💾 Backup created: {backup_path.name}")
        
        # Write updated YAML
        with open(file_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
        
        print(f"  ✅ Migrated successfully ({total_changes} changes)")
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run migration on all framework YAML files."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate framework YAML files with value field metadata')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying files')
    parser.add_argument('--no-backup', action='store_true', help='Skip creating backup files')
    parser.add_argument('--files', nargs='+', help='Specific files to migrate (default: all in examples/)')
    
    args = parser.parse_args()
    
    # Determine files to process
    if args.files:
        file_paths = [Path(f) for f in args.files]
    else:
        examples_dir = Path(__file__).parent.parent / 'examples'
        file_paths = list(examples_dir.glob('*.yaml'))
    
    print("=" * 60)
    print("Framework Value Fields Migration")
    print("=" * 60)
    
    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No files will be modified\n")
    
    # Process each file
    migrated_count = 0
    for file_path in sorted(file_paths):
        if file_path.suffix in ['.yaml', '.yml']:
            if migrate_yaml_file(file_path, dry_run=args.dry_run, backup=not args.no_backup):
                migrated_count += 1
    
    print("\n" + "=" * 60)
    print(f"Migration complete: {migrated_count}/{len(file_paths)} files modified")
    print("=" * 60)
    
    if args.dry_run:
        print("\n💡 Run without --dry-run to apply changes")


if __name__ == '__main__':
    main()
