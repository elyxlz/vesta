---
migration_phase: before_sync
---

This is the final one-time repair of your workspace before the new upstream-sync flow runs.
Do not start upstream sync yourself during this migration. The next boot owns that, after this
repair has proved that your workspace is a plain full checkout, recovered any skill activation
evidence left by the v0.1.180 conversion, and made the read-only `agent/core` mount invisible to
Git. Every step is safe to repeat.

### 1. Stop on an unfinished Git operation

Run `git -C ~ status`. If it reports a merge or rebase in progress, finish or abort that
operation first. If you cannot do so safely, STOP HERE, leave this migration unmarked, and tell
the user. Never checkpoint an unfinished operation.

### 2. Recover the active-skill set from every trustworthy source

The v0.1.180 conversion could under-read a legacy non-cone sparse list. Preserve the current
`active_skills`, add valid skill names from every retained legacy sparse-checkout file and from
the pre-conversion `~/agent-backup.tar.gz`, and add local-only skill directories that do not exist
in the newest stock tag already merged into this workspace. If the current workspace is still
sparse, every skill directory actually present is also active. Do not activate every stock
directory in an already-flat checkout: flat workspaces deliberately keep inactive stock skills
on disk.

```bash
cd ~
python3 - <<'PY'
import json
import pathlib
import re
import subprocess
import tarfile

home = pathlib.Path.home()
config_path = home / "agent/data/config.json"
skill_name = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

try:
    data = json.loads(config_path.read_text()) if config_path.is_file() else {}
except (json.JSONDecodeError, OSError) as error:
    raise SystemExit(f"STOP: cannot safely read {config_path}: {error}") from error
if not isinstance(data, dict):
    raise SystemExit(f"STOP: {config_path} is not a JSON object")
existing = data.get("active_skills")
recovered = {name.strip() for name in existing if isinstance(name, str) and skill_name.fullmatch(name.strip())} if isinstance(existing, list) else set()

current_sparse_file = home / ".git/info/sparse-checkout"
current_sparse = current_sparse_file.is_file()
configured_sparse = subprocess.run(
    ["git", "-C", str(home), "config", "--bool", "--get", "core.sparseCheckout"],
    capture_output=True,
    text=True,
    check=False,
).stdout.strip() == "true"

sparse_files = [current_sparse_file, *sorted(home.glob(".git-legacy*/info/sparse-checkout"))]
for path in sparse_files:
    if not path.is_file():
        continue
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        line = line.lstrip("/")
        prefix = "agent/skills/"
        if not line.startswith(prefix):
            continue
        candidate = line.removeprefix(prefix).rstrip("/")
        if skill_name.fullmatch(candidate):
            recovered.add(candidate)

# The original flat-checkout migration made this archive before retiring the sparse repo. Unlike
# today's full checkout, it contains only the skill directories that were physically present then.
legacy_archive = home / "agent-backup.tar.gz"
if legacy_archive.is_file():
    try:
        with tarfile.open(legacy_archive) as archive:
            for member in archive.getmembers():
                parts = pathlib.PurePosixPath(member.name).parts
                if len(parts) >= 3 and parts[:2] == ("agent", "skills") and skill_name.fullmatch(parts[2]):
                    recovered.add(parts[2])
    except (OSError, tarfile.TarError) as error:
        print(f"warning: could not read legacy skill backup: {error}")

skills_dir = home / "agent/skills"
on_disk = {path.name for path in skills_dir.iterdir() if path.is_dir() and skill_name.fullmatch(path.name)} if skills_dir.is_dir() else set()
if current_sparse or configured_sparse:
    recovered.update(on_disk)
else:
    tags = subprocess.run(
        ["git", "-C", str(home), "tag", "--merged", "HEAD", "--list", "agent-v*", "--sort=-version:refname"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    if tags:
        stock = set(
            subprocess.run(
                ["git", "-C", str(home), "ls-tree", "-d", "--name-only", f"{tags[0]}:agent/skills"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.splitlines()
        )
        recovered.update(on_disk - stock)

data["active_skills"] = sorted(recovered)
config_path.parent.mkdir(parents=True, exist_ok=True)
tmp = config_path.with_name(f"{config_path.name}.tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
tmp.replace(config_path)
print("active skills recovered:", ", ".join(data["active_skills"]) or "(defaults only)")
PY
```

If the script exits with `STOP`, leave this migration unmarked and tell the user rather than
overwriting an unreadable config. A backup warning is non-fatal because the retained sparse
patterns and local-only directories remain independent recovery sources.

### 3. Repair a remaining sparse workspace without discarding it

Check both sparse markers:

```bash
cd ~
if [ -f .git/info/sparse-checkout ] || [ "$(git config --bool --get core.sparseCheckout || true)" = "true" ]; then
  echo sparse
else
  echo flat
fi
```

If it prints `flat`, continue to step 4.

If it prints `sparse`, preserve the entire agent tree and old repository, then attach a fresh
flat repository. The backup names are new, so the evidence retained by earlier conversions is
never overwritten:

```bash
cd ~
STAMP="$(date +%Y%m%d%H%M%S)"
BACKUP="$HOME/agent-workspace-repair-$STAMP.tar.gz"
OLD_GIT="$HOME/.git-legacy-repair-$STAMP"
if ! tar czf "$BACKUP" agent; then
  echo "workspace repair stopped: backup failed"
elif ! mv .git "$OLD_GIT"; then
  echo "workspace repair stopped: could not preserve the old repository"
elif ! bash agent/core/skills/upstream-sync/scripts/attach.sh; then
  [ ! -d .git ] || mv .git "$HOME/.git-failed-repair-$STAMP"
  mv "$OLD_GIT" .git
  echo "workspace repair deferred: fresh flat attach failed"
fi
```

If the block printed any `stopped` or `deferred` message, STOP HERE, leave this migration
unmarked, and tell the user. An attach failure restores the old repository, and the next boot
will retry this repair before sync.

After a successful attach, inspect `git status`. Keep personal files and edits, adopt stock's
current structure, and never blanket-select one side. The attach deliberately exposes
personalizations as working-tree changes; upstream sync will checkpoint them on the next boot.

### 4. Restore the load-bearing root ignore

The root `.gitignore` is workspace infrastructure, not personal content. Put it in its canonical
form so Git tracks only the workspace and never sees the read-only engine mount:

```bash
cd ~
python3 - <<'PY'
import pathlib

pathlib.Path(".gitignore").write_text("/*\n!/.gitignore\n!/agent/\n/agent/core/\n")
PY
```

Verify the final invariants:

```bash
set -e
cd ~
test ! -f .git/info/sparse-checkout
test "$(git config --bool --get core.sparseCheckout || true)" != "true"
git check-ignore -q agent/core/pyproject.toml
test -z "$(git status --porcelain -- agent/core)"
git rev-parse -q --verify HEAD
```

If any check fails, STOP HERE, leave this migration unmarked, and tell the user exactly which
invariant failed.

After the generated final step below marks this migration applied, follow the before-sync batch
instructions. The migration runner owns the boot barrier and restart into upstream sync.
