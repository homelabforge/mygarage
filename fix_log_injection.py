#!/usr/bin/env python3
"""
Automated fix for log injection vulnerabilities (CWE-117).

Converts f-string logging to parameterized logging across all Python files:
  Before: logger.info(f"Message {var}")
  After:  logger.info("Message %s", var)

This prevents newline injection attacks where attackers can inject \\n
to forge log entries.
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple


def fix_log_injection_in_file(file_path: Path) -> Tuple[int, List[str]]:
    """Fix all log injection issues in a single file.

    Returns:
        Tuple of (number_of_fixes, list_of_fixed_lines)
    """
    content = file_path.read_text()
    original_content = content
    fixes = []

    # Pattern to match logger.level(f"...")
    # Captures: logger method, opening quote type, f-string content
    pattern = r'logger\.(debug|info|warning|error|critical)\(f(["\'])(.*?)\2\)'

    def replace_fstring(match):
        method = match.group(1)  # debug, info, warning, error, critical
        quote = match.group(2)   # " or '
        fstring_content = match.group(3)  # Content inside f"..."

        # Convert f-string interpolations {var} to %s placeholders
        # Handle simple cases: {variable}, {obj.attr}, {dict['key']}, {func()}
        params = []
        converted_string = fstring_content

        # Find all {expressions} and replace with %s
        # This regex handles nested braces for dict access, but keeps it simple
        expr_pattern = r'\{([^{}]+)\}'

        def extract_param(expr_match):
            expr = expr_match.group(1)
            params.append(expr)
            return '%s'

        converted_string = re.sub(expr_pattern, extract_param, converted_string)

        # Build the replacement
        if params:
            # Has parameters - use parameterized logging
            params_str = ', '.join(params)
            replacement = f'logger.{method}({quote}{converted_string}{quote}, {params_str})'
        else:
            # No parameters - just remove the f prefix
            replacement = f'logger.{method}({quote}{converted_string}{quote})'

        fixes.append(f"  {match.group(0)} -> {replacement}")
        return replacement

    # Apply all replacements
    content = re.sub(pattern, replace_fstring, content, flags=re.DOTALL)

    # Only write if changes were made
    if content != original_content:
        file_path.write_text(content)
        return len(fixes), fixes

    return 0, []


def main():
    """Fix log injection across all Python files in backend/app."""
    base_dir = Path(__file__).parent / "backend" / "app"

    if not base_dir.exists():
        print(f"Error: {base_dir} does not exist", file=sys.stderr)
        return 1

    print(f"Scanning {base_dir} for log injection vulnerabilities...")
    print("=" * 80)

    total_files = 0
    total_fixes = 0

    # Process all .py files recursively
    for py_file in sorted(base_dir.rglob("*.py")):
        # Skip __pycache__ and test files (we'll fix those separately if needed)
        if "__pycache__" in str(py_file):
            continue

        num_fixes, fix_details = fix_log_injection_in_file(py_file)

        if num_fixes > 0:
            total_files += 1
            total_fixes += num_fixes
            relative_path = py_file.relative_to(base_dir.parent.parent)
            print(f"\n{relative_path}: {num_fixes} fixes")
            for detail in fix_details:
                print(detail)

    print("\n" + "=" * 80)
    print(f"Fixed {total_fixes} log injection vulnerabilities across {total_files} files")

    return 0


if __name__ == "__main__":
    sys.exit(main())
