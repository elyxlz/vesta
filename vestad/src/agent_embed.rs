use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "../agent"]
#[include = "core/**/*.py"]
#[include = "pyproject.toml"]
#[include = "uv.lock"]
#[exclude = "**/__pycache__/*"]
#[exclude = "**/*.pyc"]
pub(crate) struct AgentSource;
