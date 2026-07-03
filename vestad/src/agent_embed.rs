use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "../agent"]
#[include = "core/**/*"]
// the personality preset frontmatter is the catalog vestad merges into GET /manifest
#[include = "skills/personality/presets/*.md"]
#[exclude = "**/__pycache__/*"]
#[exclude = "**/*.pyc"]
pub(crate) struct AgentSource;
