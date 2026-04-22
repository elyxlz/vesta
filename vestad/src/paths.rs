use std::path::PathBuf;

/// Resolves the vestad config directory (`~/.config/vesta/vestad`). Returns
/// `None` if `HOME` is unset — callers decide whether that is fatal.
pub fn config_dir() -> Option<PathBuf> {
    std::env::var("HOME")
        .ok()
        .map(|h| PathBuf::from(h).join(".config/vesta/vestad"))
}

/// Same as `config_dir` but falls back to a relative path when `HOME` is unset.
/// Use in non-critical contexts where we want a best-effort path.
pub fn config_dir_or_relative() -> PathBuf {
    config_dir().unwrap_or_else(|| PathBuf::from(".config/vesta/vestad"))
}
