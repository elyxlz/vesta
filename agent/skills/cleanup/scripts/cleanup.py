#!/usr/bin/env python3
"""
cleanup.py — Disk cleanup utility for vesta agent containers.

Scans for cleanable items (caches, build artifacts, temp files, etc.) and
reports their sizes. By default runs in dry-run mode — nothing is deleted
until you pass --clean.

Two-tier system:
  Tier 1 — Auto-clean  : safe items that regenerate automatically (pyc, logs,
                          tmp, build-artifacts). Cleaned by --clean.
  Tier 2 — Report-only : caches that re-download on next use (pip, uv, go,
                          npm, huggingface, playwright). Require --clean-all.

Usage:
    python3 ~/vesta/skills/cleanup/scripts/cleanup.py               # dry-run report
    python3 ~/vesta/skills/cleanup/scripts/cleanup.py --clean       # clean tier-1 only
    python3 ~/vesta/skills/cleanup/scripts/cleanup.py --clean-all   # clean everything
    python3 ~/vesta/skills/cleanup/scripts/cleanup.py --clean --target pyc logs
    python3 ~/vesta/skills/cleanup/scripts/cleanup.py --list-targets
"""

import argparse
import shutil
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fmt_size(n_bytes: int) -> str:
    """Format a byte count as a human-readable string (e.g. 1.23 GB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n_bytes) < 1024.0:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024.0
    return f"{n_bytes:.1f} PB"


def fmt_atime(path: Path) -> str:
    """Return a human-readable 'last accessed' string for a path, or '' if unavailable."""
    try:
        atime = path.stat().st_atime
    except OSError:
        return ""
    age_secs = time.time() - atime
    if age_secs < 3600:
        return f"last accessed {int(age_secs // 60)}m ago"
    if age_secs < 86400:
        return f"last accessed {int(age_secs // 3600)}h ago"
    days = int(age_secs // 86400)
    return f"last accessed {days}d ago"


def dir_size(path: Path) -> int:
    """Return total size in bytes of all files under *path* (non-recursive symlinks ignored)."""
    total = 0
    if not path.exists():
        return 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file(follow_symlinks=False):
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except PermissionError:
        pass
    return total


def file_size(path: Path) -> int:
    """Return file size, or 0 if it doesn't exist / not accessible."""
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def remove_path(path: Path) -> None:
    """Delete a file or directory tree, ignoring errors."""
    try:
        if path.is_dir(follow_symlinks=False):
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Target definitions
# ---------------------------------------------------------------------------

# Each target is a dict with:
#   key         : str        — CLI name
#   label       : str        — display label
#   description : str        — one-line description
#   tier        : str        — "auto" (cleaned by --clean) or "report" (--clean-all only)
#   warning     : str | None — shown in yellow if set
#   scan        : callable() -> list[Path]  — returns paths to delete

HOME = Path.home()
VESTA_ROOT = HOME / "vesta"


# ---------------------------------------------------------------------------
# Scan functions — each returns a list of Path objects to be deleted
# ---------------------------------------------------------------------------


def _scan_single_dir(path: Path) -> list[Path]:
    """Return [path] if it exists, else []."""
    return [path] if path.exists() else []


def _scan_pyc() -> list[Path]:
    """Find all .pyc files and __pycache__ dirs under VESTA_ROOT."""
    if not VESTA_ROOT.exists():
        return []
    found: list[Path] = []
    try:
        # __pycache__ dirs (we'll delete the dir, which includes all .pyc inside)
        pycache_dirs = set()
        for p in VESTA_ROOT.rglob("__pycache__"):
            if p.is_dir(follow_symlinks=False):
                pycache_dirs.add(p)
        found.extend(sorted(pycache_dirs))

        # Loose .pyc files that live outside __pycache__ (rare but possible)
        for p in VESTA_ROOT.rglob("*.pyc"):
            if p.is_file() and p.parent not in pycache_dirs:
                found.append(p)
    except PermissionError:
        pass
    return found


def _scan_logs() -> list[Path]:
    """
    Find rotated/old log files in ~/vesta/logs/.

    Strategy: for each unique filename prefix (everything before the first dot
    or numeric suffix), keep the most recently modified file and mark the rest
    as deletable.  Also marks any .gz / .1 / .2 / .old / .bak suffixed files.
    """
    logs_dir = VESTA_ROOT / "logs"
    if not logs_dir.exists():
        return []

    deletable: list[Path] = []
    try:
        all_files = [f for f in logs_dir.iterdir() if f.is_file(follow_symlinks=False)]
    except PermissionError:
        return []

    # Group by stem (e.g. "agent.log.1" → stem "agent.log")
    from collections import defaultdict

    groups: dict[str, list[Path]] = defaultdict(list)

    for f in all_files:
        name = f.name
        # Rotated indicators: ends with .gz, .1-.9, .old, .bak, or has numeric suffix
        if name.endswith(".gz") or name.endswith(".bak") or name.endswith(".old") or (name.split(".")[-1].isdigit()):
            deletable.append(f)
        else:
            # Current log — group by base name so we can keep the newest per prefix
            stem = name.split(".")[0]
            groups[stem].append(f)

    # Within each group keep only the most recently modified file; delete the rest
    for stem, files in groups.items():
        if len(files) > 1:
            files_sorted = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
            deletable.extend(files_sorted[1:])  # keep index 0, delete the rest

    return deletable


def _scan_tmp() -> list[Path]:
    """Find files and dirs in /tmp/ not accessed or modified in the last 24h."""
    tmp = Path("/tmp")
    if not tmp.exists():
        return []
    cutoff = time.time() - 86400  # 24 hours ago
    deletable: list[Path] = []
    try:
        for entry in tmp.iterdir():
            try:
                mtime = entry.stat(follow_symlinks=False).st_mtime
                if mtime < cutoff:
                    deletable.append(entry)
            except OSError:
                pass
    except PermissionError:
        pass
    return deletable


def _scan_build_artifacts() -> list[Path]:
    """Find build/, dist/, and *.egg-info/ directories under ~/vesta/skills/."""
    skills_dir = VESTA_ROOT / "skills"
    if not skills_dir.exists():
        return []
    found: list[Path] = []
    patterns = ("build", "dist")
    try:
        for pattern in patterns:
            for p in skills_dir.rglob(pattern):
                if p.is_dir(follow_symlinks=False):
                    found.append(p)
        for p in skills_dir.rglob("*.egg-info"):
            if p.is_dir(follow_symlinks=False):
                found.append(p)
    except PermissionError:
        pass
    return found


# ---------------------------------------------------------------------------
# Target definitions
# ---------------------------------------------------------------------------
# Defined after the scan functions so lambdas/references resolve correctly.

TARGETS: list[dict] = [
    # ---- Tier 1: Auto-clean (safe, items regenerate without network) -------
    {
        "key": "pyc",
        "label": "Python bytecode",
        "description": "Compiled .pyc files and __pycache__ dirs under ~/vesta/",
        "tier": "auto",
        "warning": None,
        "scan": _scan_pyc,
    },
    {
        "key": "logs",
        "label": "Old log files",
        "description": "Rotated/old log files in ~/vesta/logs/ (current logs kept)",
        "tier": "auto",
        "warning": None,
        "scan": _scan_logs,
    },
    {
        "key": "tmp",
        "label": "Stale /tmp files",
        "description": "Files in /tmp/ not modified in the last 24 hours",
        "tier": "auto",
        "warning": None,
        "scan": _scan_tmp,
    },
    {
        "key": "build-artifacts",
        "label": "Build artifacts",
        "description": "build/, dist/, *.egg-info/ under ~/vesta/skills/",
        "tier": "auto",
        "warning": None,
        "scan": _scan_build_artifacts,
    },
    # ---- Tier 2: Report-only (caches that re-download on next use) ---------
    {
        "key": "pip-cache",
        "label": "pip cache",
        "description": "pip wheel and HTTP cache (~/.cache/pip/)",
        "tier": "report",
        "warning": None,
        "scan": lambda: _scan_single_dir(HOME / ".cache" / "pip"),
    },
    {
        "key": "uv-cache",
        "label": "uv cache",
        "description": "uv package cache (~/.cache/uv/)",
        "tier": "report",
        "warning": None,
        "scan": lambda: _scan_single_dir(HOME / ".cache" / "uv"),
    },
    {
        "key": "go-build",
        "label": "Go build cache",
        "description": "Go compiler build cache (~/.cache/go-build/)",
        "tier": "report",
        "warning": None,
        "scan": lambda: _scan_single_dir(HOME / ".cache" / "go-build"),
    },
    {
        "key": "npm-cache",
        "label": "npm cache",
        "description": "npm package cache (~/.npm/)",
        "tier": "report",
        "warning": None,
        "scan": lambda: _scan_single_dir(HOME / ".npm"),
    },
    {
        "key": "huggingface",
        "label": "HuggingFace cache",
        "description": "HuggingFace model/dataset cache (~/.cache/huggingface/)",
        "tier": "report",
        "warning": "Models must be re-downloaded from HuggingFace Hub after cleaning.",
        "scan": lambda: _scan_single_dir(HOME / ".cache" / "huggingface"),
    },
    {
        "key": "playwright",
        "label": "Playwright browsers",
        "description": "Playwright browser binaries (~/.cache/ms-playwright/)",
        "tier": "report",
        "warning": "Browser automation will break until 'playwright install' is re-run.",
        "scan": lambda: _scan_single_dir(HOME / ".cache" / "ms-playwright"),
    },
]

TARGET_MAP = {t["key"]: t for t in TARGETS}


# ---------------------------------------------------------------------------
# Size calculation
# ---------------------------------------------------------------------------


def compute_size(paths: list[Path]) -> int:
    """Sum the size of a list of paths (files or directory trees)."""
    total = 0
    for p in paths:
        if p.is_dir(follow_symlinks=False):
            total += dir_size(p)
        else:
            total += file_size(p)
    return total


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"


def color(text: str, code: str) -> str:
    """Wrap text in ANSI color if stdout is a TTY."""
    if sys.stdout.isatty():
        return f"{code}{text}{RESET}"
    return text


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def _print_section(
    section_label: str,
    targets: list[dict],
    col_label: int,
    col_size: int,
    show_atime: bool,
) -> tuple[list[tuple], int]:
    """
    Print one section of the dry-run table.

    Returns (results, section_total) where results is a list of
    (label, size, paths, warning, key) tuples.
    """
    print(color(f"  {section_label}", BOLD))
    print(color("  " + "-" * (col_label + col_size + 44), DIM))

    results: list[tuple] = []
    section_total = 0

    for target in targets:
        paths = target["scan"]()
        size = compute_size(paths)
        section_total += size
        results.append((target["label"], size, paths, target.get("warning"), target["key"]))

        size_str = fmt_size(size) if size > 0 else color("—", DIM)
        warn_icon = color(" !", YELLOW) if target.get("warning") else "  "

        extra = ""
        if show_atime and paths:
            extra = color(f"  [{fmt_atime(paths[0])}]", DIM)

        print(f"  {target['label']:<{col_label}}  {size_str:>{col_size}}{warn_icon}  {target['description']}{extra}")

    print(color("  " + "-" * (col_label + col_size + 44), DIM))
    total_str = color(fmt_size(section_total), GREEN if section_total > 0 else DIM)
    print(f"  {'Subtotal':<{col_label}}  {total_str:>{col_size}}\n")

    return results, section_total


def run(targets: list[dict], dry_run: bool, clean_all: bool) -> None:
    if dry_run:
        mode_label = color("DRY RUN", YELLOW)
    elif clean_all:
        mode_label = color("CLEAN ALL", RED + BOLD)
    else:
        mode_label = color("CLEAN", RED + BOLD)

    print(f"\n{color('Vesta Disk Cleanup', BOLD)}  [{mode_label}]\n")

    col_label = 22
    col_size = 12

    # Split selected targets by tier
    auto_targets = [t for t in targets if t.get("tier") == "auto"]
    report_targets = [t for t in targets if t.get("tier") == "report"]

    all_results: list[tuple] = []
    grand_total = 0

    if dry_run:
        # Show both sections clearly labelled
        if auto_targets:
            results, subtotal = _print_section(
                "Auto-clean  (safe — items regenerate automatically)",
                auto_targets,
                col_label,
                col_size,
                show_atime=False,
            )
            all_results.extend(results)
            grand_total += subtotal

        if report_targets:
            results, subtotal = _print_section(
                "Report only (caches — will re-download on next use)",
                report_targets,
                col_label,
                col_size,
                show_atime=True,
            )
            all_results.extend(results)
            grand_total += subtotal

        total_str = color(fmt_size(grand_total), GREEN if grand_total > 0 else DIM)
        print(f"  {'GRAND TOTAL':<{col_label}}  {total_str:>{col_size}}\n")

        # Print warnings
        warned = [(lbl, warn) for (lbl, _, paths, warn, _) in all_results if warn and compute_size(paths) > 0]
        if warned:
            print(color("  Warnings:", YELLOW + BOLD))
            for lbl, warn in warned:
                print(f"  {color('!', YELLOW)} {color(lbl, BOLD)}: {warn}")
            print()

        print(color("  Run with --clean to delete auto-clean items.", DIM))
        print(color("  Run with --clean-all to also delete report-only caches.", DIM))
        print()
        return

    # --- Actual deletion ---
    # Determine which targets to actually clean
    if clean_all:
        clean_targets = targets
    else:
        clean_targets = [t for t in targets if t.get("tier") == "auto"]

    # Collect results for clean_targets only
    results_to_clean: list[tuple] = []
    total_to_clean = 0
    for target in clean_targets:
        paths = target["scan"]()
        size = compute_size(paths)
        total_to_clean += size
        results_to_clean.append((target["label"], size, paths, target.get("warning"), target["key"]))

    # In clean (non-dry-run) mode, still print a summary table first
    header = f"  {'Target':<{col_label}}  {'Size':>{col_size}}  Description"
    print(color(header, DIM))
    print(color("  " + "-" * (col_label + col_size + 40), DIM))
    for lbl, size, paths, warning, key in results_to_clean:
        size_str = fmt_size(size) if size > 0 else color("—", DIM)
        warn_icon = color(" !", YELLOW) if warning else "  "
        tgt = TARGET_MAP[key]
        print(f"  {lbl:<{col_label}}  {size_str:>{col_size}}{warn_icon}  {tgt['description']}")
    print(color("  " + "-" * (col_label + col_size + 40), DIM))
    total_str = color(fmt_size(total_to_clean), GREEN if total_to_clean > 0 else DIM)
    print(f"  {'TOTAL':<{col_label}}  {total_str:>{col_size}}\n")

    if total_to_clean == 0:
        print(color("  Nothing to clean.", DIM))
        print()
        return

    # Warnings
    warned = [(lbl, warn) for (lbl, _, paths, warn, _) in results_to_clean if warn and compute_size(paths) > 0]
    if warned:
        print(color("  Warnings:", YELLOW + BOLD))
        for lbl, warn in warned:
            print(f"  {color('!', YELLOW)} {color(lbl, BOLD)}: {warn}")
        print()

    cleaned = 0
    errors = 0
    for lbl, size, paths, warning, key in results_to_clean:
        if not paths or size == 0:
            continue
        print(f"  Cleaning {color(lbl, BOLD)} ...", end=" ", flush=True)
        for p in paths:
            try:
                remove_path(p)
                cleaned += size
            except Exception as e:
                errors += 1
                print(color(f"\n    Error removing {p}: {e}", RED))
        print(color("done", GREEN))

    print()
    print(f"  {color('Freed:', BOLD)} {color(fmt_size(cleaned), GREEN)}", end="")
    if errors:
        print(f"  {color(f'({errors} errors)', RED)}", end="")
    print("\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Disk cleanup utility for vesta agent containers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report cleanable items without deleting (default)",
    )
    mode_group.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Delete tier-1 (auto-clean) items only",
    )
    mode_group.add_argument(
        "--clean-all",
        action="store_true",
        default=False,
        help="Delete everything including tier-2 caches (pip, uv, npm, etc.)",
    )
    parser.add_argument(
        "--target",
        nargs="+",
        metavar="TARGET",
        help="Limit cleanup to specific targets (see --list-targets)",
    )
    parser.add_argument(
        "--list-targets",
        action="store_true",
        help="Print available target names and exit",
    )

    args = parser.parse_args()

    if args.list_targets:
        print("\nAvailable targets:\n")
        auto = [t for t in TARGETS if t.get("tier") == "auto"]
        report = [t for t in TARGETS if t.get("tier") == "report"]
        print(color("  Tier 1 — Auto-clean:", BOLD))
        for t in auto:
            warn = f"  {color('!', YELLOW)} {t['warning']}" if t.get("warning") else ""
            print(f"    {color(t['key'], BOLD):<30} {t['description']}{warn}")
        print()
        print(color("  Tier 2 — Report-only (caches):", BOLD))
        for t in report:
            warn = f"  {color('!', YELLOW)} {t['warning']}" if t.get("warning") else ""
            print(f"    {color(t['key'], BOLD):<30} {t['description']}{warn}")
        print()
        return

    # Resolve targets
    if args.target:
        unknown = [k for k in args.target if k not in TARGET_MAP]
        if unknown:
            print(color(f"Unknown target(s): {', '.join(unknown)}", RED), file=sys.stderr)
            print("Run with --list-targets to see available options.", file=sys.stderr)
            sys.exit(1)
        selected = [TARGET_MAP[k] for k in args.target]
    else:
        selected = TARGETS

    dry_run = not (args.clean or args.clean_all)
    run(selected, dry_run=dry_run, clean_all=args.clean_all)


if __name__ == "__main__":
    main()
