Your workspace (`~`) is a git repo in the old sparse-checkout (cone) shape. Convert it once
to the flat shape: a plain full checkout of your skills + `MEMORY.md`, with which skills are
active recorded in `~/agent/data/config.json` instead of the cone. The engine
(`agent/core`) is a read-only mount and no longer lives in the checkout. Run step 1; its exit
code tells you what to do next. Re-running is safe: a converted workspace no longer matches
the old shape, so attach just no-ops.

If you were created with the removed `--no-manage-core-code` option, `agent/core` used to be
tracked, writable content in your checkout. Vestad now mounts core read-only for every agent
(it remounts on this boot), so the conversion below drops that tracked copy: the flat snapshot
gitignores `agent/core`, leaving the read-only mount as the only source of the engine. Any core
edits you had made stop taking effect; that is intended, core is now always vestad-managed.

### 1. Probe
```bash
cd ~ && bash agent/core/skills/upstream-sync/scripts/attach.sh; echo "exit: $?"
```
- Exit 4: old sparse workspace (attach refused to touch it). Convert it in step 2.
- Exit 0: already flat (converted, or a repo that just attached cleanly). You're done.
- Exit 3, or a failed fetch: this version's snapshot isn't available from Vesta's daemon yet. Not yours to fix; you're done, and the next boot converts once it is.

### 2. Convert
Record which skills the cone had active, then retire the old repo and attach the new flat
one, putting the old one back if the attach fails so you are never left without a working repo:
```bash
cd ~
mkdir -p agent/data
python3 - <<'PY'
import json
import pathlib
import re
import subprocess

config_path = pathlib.Path("agent/data/config.json")
skill_name_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
try:
    loaded = json.loads(config_path.read_text()) if config_path.is_file() else {}
except json.JSONDecodeError:
    loaded = {}
data = loaded if isinstance(loaded, dict) else {}
cone = subprocess.run(["git", "sparse-checkout", "list"], capture_output=True, text=True, check=False)
captured = [line.removeprefix("agent/skills/") for line in cone.stdout.splitlines() if line.startswith("agent/skills/")]
existing = data["active_skills"] if isinstance(data.get("active_skills"), list) else []
data["active_skills"] = sorted({name.strip() for name in [*existing, *captured] if isinstance(name, str) and skill_name_re.fullmatch(name.strip())})
tmp = config_path.with_name(f"{config_path.name}.tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
tmp.replace(config_path)
PY
tar czf ~/agent-backup.tar.gz agent        # safety net, keep until verified
mv ~/.git ~/.git-legacy                     # retire the old repo (delete on a later dream)
if ! bash agent/core/skills/upstream-sync/scripts/attach.sh; then
  rm -rf ~/.git                             # drop the half-made repo the failed attach left
  mv ~/.git-legacy ~/.git                   # restore the working repo, untouched
  echo "conversion deferred: this version's snapshot isn't available from Vesta's daemon"
fi
```
If you saw `conversion deferred`, stop: your old workspace is back exactly as it was and still
works. Tell the user. Otherwise continue to step 3.

### 3. Reconcile your changes
`git status` now shows every file where your content differs from stock (your personalized
skills, `MEMORY.md`). Judge each: keep yours, take stock (`git checkout -- <file>`), or
integrate both. A file whose only diff is stock that moved or got deleted is not yours, take
stock. For `agent/MEMORY.md`, keep your accumulated knowledge and adopt the stock structure.
Then commit. Your recorded skills are linked by the boot entrypoint on the next restart:
```bash
git add -A && git commit -m "my customizations"
```
Your active skill set (`active_skills` plus the shipped defaults) takes effect on your next
restart.
