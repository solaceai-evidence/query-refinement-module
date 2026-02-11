#!/usr/bin/env python3
"""
Script to migrate API endpoints from unversioned to versioned (v1).

Replaces /api/{endpoint} with /api/v1/{endpoint} in all test files.
"""
import os
import re
from pathlib import Path

# Patterns to replace
REPLACEMENTS = [
    (r'"/api/(auth|refinement|queries|webhooks|feedback|audit|admin|logs)/', r'"/api/v1/\1/'),
    (r"'/api/(auth|refinement|queries|webhooks|feedback|audit|admin|logs)/", r"'/api/v1/\1/"),
    (r'f"/api/(auth|refinement|queries|webhooks|feedback|audit|admin|logs)/', r'f"/api/v1/\1/'),
    (r"f'/api/(auth|refinement|queries|webhooks|feedback|audit|admin|logs)/", r"f'/api/v1/\1/"),
]

# Preserve these (they should not be versioned)
PRESERVE_PATTERNS = [
    '/health',
    '/ready',
    '/docs',
    '/api/version',  # Version info endpoint itself
]

def should_preserve(line):
    """Check if line contains patterns that should not be versioned."""
    return any(pattern in line for pattern in PRESERVE_PATTERNS)

def migrate_file(filepath):
    """Migrate a single file to versioned API endpoints."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        lines = content.split('\n')
        modified_lines = []
        changes_made = 0
        
        for line in lines:
            modified_line = line
            
            # Skip lines that should be preserved
            if not should_preserve(line):
                # Apply all replacement patterns
                for pattern, replacement in REPLACEMENTS:
                    new_line = re.sub(pattern, replacement, modified_line)
                    if new_line != modified_line:
                        changes_made += 1
                        modified_line = new_line
            
            modified_lines.append(modified_line)
        
        # Write back if changes were made
        if changes_made > 0:
            new_content = '\n'.join(modified_lines)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"✅ {filepath.name}: {changes_made} changes")
            return changes_made
        
        return 0
        
    except Exception as e:
        print(f"❌ Error processing {filepath}: {e}")
        return 0

def main():
    """Main migration function."""
    print("🔄 Migrating API endpoints to versioned (v1)...")
    print()
    
    # Find all test files
    test_dir = Path(__file__).parent.parent / 'tests'
    test_files = list(test_dir.rglob('test_*.py'))
    
    if not test_files:
        print("⚠️  No test files found")
        return
    
    total_changes = 0
    files_modified = 0
    
    for test_file in sorted(test_files):
        changes = migrate_file(test_file)
        if changes > 0:
            files_modified += 1
            total_changes += changes
    
    print()
    print("="* 60)
    print(f"✅ Migration complete!")
    print(f"   Files modified: {files_modified}/{len(test_files)}")
    print(f"   Total changes: {total_changes}")
    print("="* 60)
    print()
    print("Next steps:")
    print("1. Review the changes: git diff")
    print("2. Run tests: poetry run pytest tests/api/")
    print("3. Start API: poetry run uvicorn query_refinement_module.api.main:app --reload")

if __name__ == '__main__':
    main()
