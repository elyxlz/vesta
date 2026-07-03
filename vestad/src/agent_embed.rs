use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "../agent"]
// The complete publishable agent home: what build-workspace.sh snapshots and what
// boxes sync from. Dev-tool configs (ruff.toml, pytest.ini, ty.toml) and tests/ live
// outside these globs and are never shipped.
#[include = "core/**/*"]
#[include = "skills/**/*"]
// generate-index.py is dev tooling (CI index regen): not shipped in the image, so it
// must not be in the workspace snapshot either or every fresh attach shows it deleted.
#[exclude = "skills/generate-index.py"]
#[include = "MEMORY.md"]
#[include = ".gitignore"]
#[exclude = "**/__pycache__/*"]
#[exclude = "**/*.pyc"]
#[exclude = "**/.venv/**"]
#[exclude = "**/node_modules/**"]
pub(crate) struct AgentSource;
