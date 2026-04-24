# Setup Local State for Upstream Sync

Use this when your filesystem or git state is not in the expected shape yet. The goal is not just to move files around. The goal is to end on branch `$AGENT_NAME`, with your current code under `~/agent`, large local-only files ignored via `~/agent/.gitignore`, your current state captured in a clean checkpoint commit, and `$VESTA_UPSTREAM_REF` merged afterward.

## Success condition

At the end, all of this should be true:

- `~/.git` exists and `origin` points at the upstream repo
- `git -C ~ rev-parse --show-toplevel` prints `~`
- `git -C ~ branch --show-current` prints `$AGENT_NAME`
- your real local code and customizations live under `~/agent`
- repo-root `~` keeps `.git`, `.gitignore`, and `.claude`; agent-owned content lives under `~/agent`
- `~/agent/.gitignore` excludes large or local-only artifacts that should not be committed
- `git -C ~ status` is commit-ready
- your local state has been committed
- you have merged `origin/$VESTA_UPSTREAM_REF`, resolving conflicts by preserving both functionalities
- the history is easy to reason about: local checkpoint commit first, then upstream merge

## 1. Read the environment

Start by reading the env file:

```bash
cat /run/vestad-env
```

You need these values:

- `AGENT_NAME`
- `VESTA_UPSTREAM_REF`

## 1a. Initialize the git repo if missing

Fresh containers do not ship with a git repo at `~`. If `~/.git` is missing, create it from scratch before continuing:

```bash
if [ ! -d ~/.git ]; then
  cd ~
  git init
  git remote add origin https://github.com/elyxlz/vesta.git
  git sparse-checkout init --no-cone
  printf '/agent/\n!/agent/core/\n!/agent/pyproject.toml\n!/agent/uv.lock\n/.gitignore\n' > .git/info/sparse-checkout
  printf '/*\n!.gitignore\n!/agent/\n' > .gitignore
fi
```

Ensure the commit identity matches your name (safe to re-run):

```bash
git -C ~ config user.name "$AGENT_NAME"
git -C ~ config user.email "$AGENT_NAME@vesta"
```

The sparse-checkout pattern keeps bind-mounted paths (`agent/core/`, `agent/pyproject.toml`, `agent/uv.lock`) out of the worktree so vestad's read-only mounts do not look like local modifications. The skills-registry skill appends to this set when you install non-default skills; do not overwrite the pattern once it exists.

## 2. Inspect filesystem and git state

Check the current layout:

```bash
cd ~
pwd
ls -la
find ~/agent -maxdepth 1 -mindepth 1 2>/dev/null | sort
git -C ~ rev-parse --show-toplevel
git -C ~ branch --show-current
git -C ~ status
git -C ~ sparse-checkout list
```

If `~/vesta` exists, inspect it too:

```bash
find ~/vesta -maxdepth 2 -mindepth 1 2>/dev/null | sort
```

## 3. Normalize the layout

Target layout:

- `~/.git` is the repo metadata
- `~/.claude` stays local
- `~/agent` contains the agent workspace and local state
- `~/agent/data`, `~/agent/logs`, and `~/agent/notifications` live under `agent`
- any other agent-related/owned files or directories also move under `~/agent`

Keep at repo root:

- `.git`
- `.gitignore`
- `.claude`
- `agent`

Everything else that belongs to the agent should end up under `~/agent`.

### If `~/vesta/agent` exists

If `~/agent` does not exist yet:

```bash
mv ~/vesta/agent ~/agent
```

If both exist, merge entries from `~/vesta/agent` into `~/agent`. For each item: if the target doesn't exist, move it directly. If both are directories, recurse into them. If the target file already exists, keep the existing one (it's newer).

```bash
merge_dirs() {
  local src="$1" dst="$2"
  find "$src" -mindepth 1 -maxdepth 1 2>/dev/null | while IFS= read -r item; do
    local name
    name=$(basename "$item")
    if [ ! -e "$dst/$name" ]; then
      mv "$item" "$dst/"
    elif [ -d "$item" ] && [ -d "$dst/$name" ]; then
      merge_dirs "$item" "$dst/$name"
    fi
  done
}
merge_dirs ~/vesta/agent ~/agent
```

### If agent-owned paths exist at repo root

Examples:

- `~/agent/data`
- `~/agent/logs`
- `~/agent/notifications`
- leftover runtime dirs
- exports or caches created by earlier layouts
- files that clearly belong to the agent rather than repo root

Move them under `~/agent`:

```bash
mkdir -p ~/agent
```

For each root-level path that belongs under `agent`:

- if `~/agent/<name>` does not exist, move it directly
- if both source and target exist, merge carefully so functionality and data are preserved

Do not move:

- `.git`
- `.gitignore`
- `.claude`
- `agent`

### Fix the skills symlink

```bash
mkdir -p ~/.claude
ln -sf ../agent/skills ~/.claude/skills
```

## 4. Fix ignore rules

Your goal is a commit-ready `git status`, not a dump of every bulky local file. The point is to create one clean local checkpoint commit before upstream sync.

Create or update `~/agent/.gitignore` and add local-only or bulky artifacts such as:

- model files: `*.bin`, `*.onnx`, `*.pt`
- local databases: `*.db`, `*.sqlite`
- media: `*.mp3`, `*.mp4`, `*.wav`
- archives: `*.zip`, `*.tar.gz`
- dependency/build outputs: `node_modules/`, `dist/`, `.venv/`, `__pycache__/`
- any other large or machine-specific files you discover during setup

Use `~/agent/.gitignore` for these rules.

## 5. Ensure the branch exists

You should be on `$AGENT_NAME`.

Check:

```bash
git -C ~ branch --show-current
git -C ~ rev-parse --verify "$AGENT_NAME"
```

If the branch is missing, create it:

```bash
git -C ~ checkout -b "$AGENT_NAME"
```

If it exists but is not checked out:

```bash
git -C ~ checkout "$AGENT_NAME"
```

## 6. Populate index with full upstream tree

Before staging local changes, populate the index with the full upstream tree. This ensures the first commit contains the complete upstream file set, so subsequent `git diff` against upstream only shows real differences in `agent/`.

```bash
# Fetch upstream ref
git -C ~ fetch origin "$VESTA_UPSTREAM_REF"

# Populate index with the full upstream tree (does NOT write to disk)
git -C ~ read-tree FETCH_HEAD

# Reapply sparse checkout to set skip-worktree on non-agent files
git -C ~ sparse-checkout reapply

# If vestad bind-mounts core/pyproject/uv.lock from the host, mark them skip-worktree
# so the mounted content does not show as local modifications.
if mount | grep -q '/root/agent/core '; then
  git -C ~ update-index --skip-worktree agent/core agent/pyproject.toml agent/uv.lock 2>/dev/null || true
fi
```

Non-agent files stay in the index (and therefore in the commit tree) but are not checked out to disk. Sparse checkout manages that transparently.

## 7. Stage only meaningful local state

```bash
git -C ~ add agent/ --ignore-errors
git -C ~ reset HEAD -- '*.bin' '*.onnx' '*.pt' '*.db' '*.sqlite' '*.mp3' '*.mp4' '*.wav' '*.zip' '*.tar.gz' '**/node_modules' '**/dist' '**/.venv' '**/__pycache__'
git -C ~ status
```

If more bulky or local-only files still appear, add them to `~/agent/.gitignore`, then re-run:

```bash
git -C ~ add agent/ --ignore-errors
git -C ~ status
```

Do not continue until `git status` shows only meaningful code, prompt, skill, config, or local-state changes you actually want represented on your branch.

After staging, run the safety step to ensure no non-agent files are accidentally staged for deletion:

```bash
# Safety: ensure no non-agent files are accidentally staged for deletion
git -C ~ diff --cached --name-only --diff-filter=D | grep -v '^agent/' | grep -v '^\.gitignore$' | xargs -r git -C ~ reset HEAD -- 2>/dev/null || true
```

## 8. Commit your current state

If there are staged changes, commit them:

```bash
git -C ~ commit -m "chore: checkpoint local state before $VESTA_UPSTREAM_REF upstream sync"
```

Use that exact message format for the local checkpoint commit. This commit is your clean local checkpoint before upstream sync. If there is nothing to commit, continue.

## 9. Merge upstream

Fetch upstream (already fetched in step 6, but re-fetch if time has passed):

```bash
git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
```

Merge it:

```bash
git -C ~ merge FETCH_HEAD --no-edit
```

If you populated the index with `read-tree` in step 6, the merge should cleanly skip all non-agent files since they already match upstream. Only actual `agent/` changes will appear as conflicts.

If there are conflicts, resolve them with this rule:

- preserve both functionalities
- preserve both intent sets
- if needed, decouple the implementations so both behaviors survive

Do not default to `git checkout --ours` or `git checkout --theirs` for meaningful logic.

Good resolutions:

- combine both logic branches into one coherent function
- extract separate helpers and call both where appropriate
- split responsibilities so upstream behavior and local behavior both remain
- rename or reorganize code to avoid collisions

Only take one side wholesale if the other side is clearly obsolete, redundant, generated, or a strict subset.

After resolving conflicts:

```bash
git -C ~ add <resolved-files>
git -C ~ commit --no-edit
```

## 10. Verify the result

Run:

```bash
git -C ~ rev-parse --show-toplevel
git -C ~ branch --show-current
git -C ~ status
git -C ~ diff FETCH_HEAD..$AGENT_NAME -- agent/
```

You are done only if:

- top-level repo is still `~`
- current branch is `$AGENT_NAME`
- your current code is under `~/agent`
- bulky local-only files are ignored by `~/agent/.gitignore`
- local state is committed
- upstream merge is complete
- the merged result still preserves both local and upstream functionality
- the history is clean and easy to follow: checkpoint commit before merge
