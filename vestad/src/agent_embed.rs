use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "../agent"]
// The complete publishable agent home: what build-upstream.sh snapshots and what
// boxes sync from. ruff.toml ships because the box formats its own code before an
// upstream PR and must match CI's config. hooks/ ships because ~/.claude/settings.json
// invokes those paths directly, and the Dockerfile copies all of agent/ anyway, so a
// directory left out here is on the box but untracked in the snapshot (dirty tree on
// attach). pytest.ini / ty.toml / tests/ are dev-only
// (the box never runs pytest or ty) and are kept out of both the image and the snapshot.
#[include = "core/**/*"]
#[include = "skills/**/*"]
#[include = "hooks/**/*"]
#[include = "MEMORY.md"]
#[include = ".gitignore"]
#[include = "ruff.toml"]
#[exclude = "**/__pycache__/*"]
#[exclude = "**/*.pyc"]
#[exclude = "**/.venv/**"]
#[exclude = "**/node_modules/**"]
pub(crate) struct AgentSource;
