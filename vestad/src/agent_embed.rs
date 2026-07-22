use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "../agent"]
// The complete publishable agent home: what build-upstream.sh snapshots and what
// boxes sync from. ruff.toml ships because the box formats its own code before an
// upstream PR and must match CI's config. pytest.ini / ty.toml / tests/ are dev-only
// (the box never runs pytest or ty) and are kept out of both the image and the snapshot.
#[include = "core/**/*"]
#[include = "skills/**/*"]
#[include = "MEMORY.md"]
#[include = ".gitignore"]
#[include = "ruff.toml"]
#[exclude = "**/__pycache__/*"]
#[exclude = "**/*.pyc"]
#[exclude = "**/.venv/**"]
#[exclude = "**/node_modules/**"]
pub(crate) struct AgentSource;
