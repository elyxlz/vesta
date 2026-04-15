# Legacy layout migration (`~/vesta` → canonical `$HOME`)

**One sentence:** If the workspace still lives under **`$HOME/vesta`** or runtime dirs sit under **`agent/`** instead of beside it, restructure once so **`VestaConfig`** paths match reality, then use **[SKILL.md](SKILL.md)** for upstream sync.

## When to run

| Situation | Action |
|-----------|--------|
| **`test -d "$HOME/vesta"`** | Run the steps below |
| **`$HOME/agent/data`**, **`.../logs`**, or **`.../notifications`** exists as dirs | Run — lift them to **`$HOME`** (step 3) |
| No **`vesta`**, **`agent/`** exists, **`data` / `logs` / `notifications`** at **`$HOME`** (or empty dirs OK) | **Stop** — nothing to migrate |

If a previous run stopped mid-way, resume from the first step whose condition is still true; repeat **`mv`** only when source still exists.

## Rules

1. **No** **`rm -rf "$HOME/vesta"`** or **`rm -rf "$HOME/agent"`** from this document without explicit user approval after showing what is left.
2. **Do not** move unrelated **`$HOME`** trees (**`go/`**, tool caches, etc.) into **`agent/`**. Only **`vesta/`** leftovers and **`data` / `logs` / `notifications`** belong here.
3. If **`$HOME/agent`** already is the real workspace, **never** **`mv vesta agent`** on top of it — merge and lift only.
4. Prefer **`mv`** (same filesystem). **`mkdir -p`** parents before **`mv`** when needed.

## Target layout

| Path | Purpose |
|------|---------|
| **`$HOME/agent/`** | Git workspace: **`skills/`**, **`prompts/`**, **`dreamer/`**, **`MEMORY.md`**, **`src/`**, … |
| **`$HOME/data/`**, **`logs/`**, **`notifications/`** | Siblings of **`agent/`** — local state, not committed |
| **`$HOME/.git`** | Repo root when deploy uses **`git -C ~`** |
| **`$HOME/.claude/`** | Local; **`ln -sf ../agent/skills .claude/skills`** when **`agent/skills`** exists |

Reference: **`agent/src/vesta/config.py`** (`source_dir`, `data_dir`, `logs_dir`, `notifications_dir`).

### Before → after

```text
# Monolithic legacy
~/vesta/MEMORY.md          →  ~/agent/MEMORY.md
~/vesta/data/session_id   →  ~/data/session_id
~/vesta/logs/vesta.log    →  ~/logs/vesta.log

# Nested legacy
~/vesta/agent/…  →  ~/agent/…
~/vesta/data/…   →  ~/data/…   (after lift)
```

**`vesta`** should become empty enough to remove with **`rmdir`**, not **`rm -rf`**.

---

## Steps (in order)

Skip any step whose **if** is false.

### 1 — Nested: promote `vesta/agent` to `~/agent`

If **`[ -d "$HOME/vesta/agent" ] && [ ! -e "$HOME/agent" ]`:**

```bash
mv "$HOME/vesta/agent" "$HOME/agent"
```

If **`[ -d "$HOME/vesta/agent" ] && [ -d "$HOME/agent" ]`** (both exist):

```bash
find "$HOME/vesta/agent" -mindepth 1 -maxdepth 1 2>/dev/null | while IFS= read -r x; do
  bn=$(basename "$x")
  [ ! -e "$HOME/agent/$bn" ] && mv "$x" "$HOME/agent/"
done
rmdir "$HOME/vesta/agent" 2>/dev/null || true
```

### 2 — Monolithic: rename `vesta` → `agent`

If **`[ -d "$HOME/vesta" ] && [ ! -e "$HOME/agent" ]`:**

```bash
mv "$HOME/vesta" "$HOME/agent"
```

### 3 — Lift `data`, `logs`, `notifications`

For each **`x`** in **`data`**, **`logs`**, **`notifications`**:

- If **`[ -d "$HOME/agent/$x" ] && [ ! -e "$HOME/$x" ]`:** `mv "$HOME/agent/$x" "$HOME/$x"`
- Else if **`[ -d "$HOME/vesta/$x" ] && [ ! -e "$HOME/$x" ]`:** `mv "$HOME/vesta/$x" "$HOME/$x"`

Then **`rmdir`** empty **`$HOME/agent/$x`** if safe.

### 4 — Leftover `vesta` next to `agent`

If **`[ -d "$HOME/vesta" ] && [ -d "$HOME/agent" ]`:**

```bash
mkdir -p "$HOME/agent"
find "$HOME/vesta" -maxdepth 1 -mindepth 1 ! -name .git 2>/dev/null | while IFS= read -r vp; do
  vb=$(basename "$vp")
  [ "$vb" = "agent" ] && continue
  [ ! -e "$HOME/agent/$vb" ] && mv "$vp" "$HOME/agent/"
done
```

Git / metadata (only if target missing at **`$HOME`**):

```bash
[ -d "$HOME/vesta/.git" ] && [ ! -d "$HOME/.git" ] && mv "$HOME/vesta/.git" "$HOME/.git"
[ -f "$HOME/vesta/.gitignore" ] && [ ! -f "$HOME/.gitignore" ] && mv "$HOME/vesta/.gitignore" "$HOME/.gitignore"
[ -d "$HOME/vesta/.claude" ] && [ ! -d "$HOME/.claude" ] && mv "$HOME/vesta/.claude" "$HOME/.claude"
```

If **`[ -d "$HOME/agent/.git" ] && [ ! -d "$HOME/.git" ]`:**

```bash
mv "$HOME/agent/.git" "$HOME/.git"
```

Try **`rmdir "$HOME/vesta" 2>/dev/null`**. If it fails, **`ls -la "$HOME/vesta"`**, resolve conflicts, ask the user before any recursive delete.

### 5 — `.claude` and skills symlink

```bash
mkdir -p "$HOME/agent" "$HOME/.claude"
[ -d "$HOME/agent/skills" ] && ln -sf ../agent/skills "$HOME/.claude/skills"
```

### 6 — Git only with real deploy facts

If **`git -C ~ rev-parse --is-inside-work-tree`** fails or sparse-checkout does not match what the image expects: do **not** guess **`origin`**. Use **`$VESTA_UPSTREAM_REF`**, image documentation, or vestad behavior.

---

## Verify

```bash
test -d "$HOME/agent" || { echo "FAIL: missing $HOME/agent"; exit 1; }
mkdir -p "$HOME/data" "$HOME/logs" "$HOME/notifications"
if test -d "$HOME/vesta"; then
  echo "WARN: $HOME/vesta still exists"
  ls -la "$HOME/vesta"
fi
if git -C ~ rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "OK: git repository at ~"
else
  echo "WARN: fix git (step 6) if deploy requires it"
fi
```

Ensure the process supervisor still runs **`python -m vesta.main`** (or equivalent) with **`$HOME`** as layout root unless **`VESTA_ROOT`** overrides **`root`** in **`config.py`**.

## Next

**[SKILL.md](SKILL.md)** — commit under **`agent/`**, **`git fetch`**, merge **`$VESTA_UPSTREAM_REF`**.
