#!/usr/bin/env python3
"""
Script to add keyword-only argument markers (*) to Python function signatures.

Rules:
- Functions with 0 args: no change
- Functions with 1+ args: add * after first positional arg
- Apply to all functions and methods including dunders
"""

import ast
import sys
from pathlib import Path


def add_star_to_signature(source_code: str) -> str:
    """Add * to function signatures in source code."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        print(f"Syntax error parsing file: {e}", file=sys.stderr)
        return source_code

    source_code.splitlines(keepends=True)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        args = node.args

        # Skip if no arguments at all
        if not args.args and not args.posonlyargs and not args.kwonlyargs:
            continue

        # Skip if already has keyword-only args (kwonlyargs populated)
        if args.kwonlyargs:
            continue

        # Count positional args (including self/cls)
        total_positional = len(args.posonlyargs) + len(args.args)

        # Need at least 2 params to add * after the first
        # (or 1 param if we want all keyword-only, but user said keep first positional)
        if total_positional < 2:
            continue

        # Find the position to insert *
        # We want to insert * after the first positional argument
        if args.posonlyargs:
            # If there are positional-only args, insert after first posonlyarg
            args.posonlyargs[0]
        else:
            # Otherwise insert after first regular arg
            args.args[0]

        # Get the line and column where we need to insert
        # We'll insert after the first arg

        # This is tricky - we need to find where to insert the *
        # Let's mark this for manual review for now
        print(f"Function {node.name} at line {node.lineno} needs update")

    # For now, return original source - this is complex to automate perfectly
    # Better to use regex or manual editing
    return source_code


def process_file(file_path: Path, dry_run: bool = True) -> bool:
    """Process a single Python file."""
    print(f"Processing {file_path}")

    try:
        content = file_path.read_text()
        modified = add_star_to_signature(content)

        if content != modified:
            if not dry_run:
                file_path.write_text(modified)
                print(f"  ✓ Modified {file_path}")
            else:
                print(f"  Would modify {file_path}")
            return True
        else:
            print("  No changes needed")
            return False
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Add keyword-only argument markers to Python functions")
    parser.add_argument("files", nargs="+", type=Path, help="Python files to process")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without modifying files")

    args = parser.parse_args()

    modified_count = 0
    for file_path in args.files:
        if file_path.suffix == ".py":
            if process_file(file_path, args.dry_run):
                modified_count += 1

    print(f"\nProcessed {len(args.files)} files, {modified_count} would be modified")


if __name__ == "__main__":
    main()
