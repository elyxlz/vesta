use crate::agent_embed::AgentSource;
use std::collections::hash_map::DefaultHasher;
use std::hash::Hasher;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::{fmt, fs};

const FINGERPRINT_MARKER: &str = ".vestad-fingerprint";
const MAIN_PY: &str = "core/main.py";

#[derive(Debug)]
pub enum AgentCodeError {
    Io(String),
}

impl fmt::Display for AgentCodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(msg) => write!(f, "io error: {msg}"),
        }
    }
}

pub fn agent_code_dir(config: &Path) -> PathBuf {
    config.join("agent-code")
}

fn embed_fingerprint() -> &'static str {
    static FINGERPRINT: OnceLock<String> = OnceLock::new();
    FINGERPRINT.get_or_init(|| {
        let mut hasher = DefaultHasher::new();
        hasher.write(env!("CARGO_PKG_VERSION").as_bytes());
        // build.rs emits VESTAD_EMBED_HASH from the embedded inputs' content; reading it here
        // via env!() makes this crate depend on it, so a change to agent/core forces a vestad
        // RECOMPILE (and a fresh rust-embed snapshot), not just a build-script rerun.
        hasher.write(env!("VESTAD_EMBED_HASH").as_bytes());
        for name in AgentSource::iter() {
            hasher.write(name.as_bytes());
            if let Some(file) = AgentSource::get(&name) {
                hasher.write(&file.data);
            }
        }
        format!("{:016x}", hasher.finish())
    })
}

/// Re-extracts embedded agent code into `agent-code/` whenever the on-disk
/// fingerprint marker doesn't match the binary's (i.e. after a rebuild).
/// Whether the next `ensure_agent_code` call would re-extract (the on-disk fingerprint is missing
/// or differs from this binary's embedded code). Callers check this BEFORE extracting to learn the
/// boot is delivering new agent code, so reconcile can restart running agents to pick it up — a
/// re-extract `remove_dir_all`s the code dir, detaching the inode running agents' core mounts hold.
pub fn agent_code_is_stale(config: &Path) -> bool {
    let dir = agent_code_dir(config);
    let marker = dir.join(FINGERPRINT_MARKER);
    let main_py = dir.join(MAIN_PY);
    !(main_py.exists() && fs::read_to_string(&marker).ok().as_deref() == Some(embed_fingerprint()))
}

pub fn ensure_agent_code(config: &Path) -> Result<PathBuf, AgentCodeError> {
    let dir = agent_code_dir(config);
    let fingerprint = embed_fingerprint();

    let marker = dir.join(FINGERPRINT_MARKER);
    let main_py = dir.join(MAIN_PY);
    if main_py.exists() && fs::read_to_string(&marker).ok().as_deref() == Some(fingerprint) {
        return Ok(dir);
    }

    tracing::info!(version = env!("CARGO_PKG_VERSION"), dir = %dir.display(), "writing embedded agent code");

    if dir.exists() {
        fs::remove_dir_all(&dir).map_err(|e| AgentCodeError::Io(format!("clean {}: {e}", dir.display())))?;
    }
    fs::create_dir_all(&dir).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    for name in AgentSource::iter() {
        let file = AgentSource::get(&name)
            .ok_or_else(|| AgentCodeError::Io(format!("embedded file {name} missing at extraction time")))?;
        let dest = dir.join(name.as_ref());
        if let Some(parent) = dest.parent() {
            fs::create_dir_all(parent).map_err(|e| AgentCodeError::Io(e.to_string()))?;
        }
        fs::write(&dest, file.data.as_ref())
            .map_err(|e| AgentCodeError::Io(format!("write {}: {e}", dest.display())))?;
    }

    // Guards against a broken include filter in agent_embed.rs silently producing
    // an empty extraction — not a TOCTOU concern, the file was just written.
    if !main_py.exists() {
        return Err(AgentCodeError::Io(format!(
            "extraction completed but {MAIN_PY} is missing — check agent_embed.rs include rules"
        )));
    }

    fs::write(&marker, fingerprint).map_err(|e| AgentCodeError::Io(e.to_string()))?;

    tracing::info!(dir = %dir.display(), "agent code ready");
    Ok(dir)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ensure_extracts_expected_files_and_is_idempotent() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let config = tmp.path();

        let dir = ensure_agent_code(config).expect("first call");
        assert_eq!(dir, agent_code_dir(config));
        assert!(dir.join(MAIN_PY).is_file());
        assert!(dir.join("core/pyproject.toml").is_file());
        assert!(dir.join("core/uv.lock").is_file());
        // Non-.py files under core/ (prompts, skill manifests) must also be embedded
        // — the agent's prompt loader depends on them at runtime.
        assert!(dir.join("core/prompts/nightly_dream.md").is_file());
        assert!(dir.join("core/prompts/notification_suffix.md").is_file());
        assert_eq!(
            fs::read_to_string(dir.join(FINGERPRINT_MARKER)).expect("marker"),
            embed_fingerprint(),
        );

        // Matching-fingerprint second call must not rewrite files.
        let sentinel = dir.join("core/pyproject.toml");
        fs::write(&sentinel, b"SENTINEL").expect("write sentinel");
        let _ = ensure_agent_code(config).expect("second call");
        assert_eq!(fs::read(&sentinel).expect("read sentinel"), b"SENTINEL");

        // Tampered marker triggers re-extraction.
        fs::write(dir.join(FINGERPRINT_MARKER), "stale").expect("write stale marker");
        let _ = ensure_agent_code(config).expect("third call");
        assert_ne!(fs::read(&sentinel).expect("read sentinel"), b"SENTINEL");
    }

    #[test]
    fn is_stale_tracks_whether_ensure_would_reextract() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let config = tmp.path();

        // Nothing extracted yet -> stale (the next ensure would extract).
        assert!(agent_code_is_stale(config), "missing code must read as stale");

        ensure_agent_code(config).expect("extract");
        assert!(!agent_code_is_stale(config), "freshly extracted code is not stale");

        // A fingerprint mismatch (what a new vestad version produces) reads as stale -> reconcile
        // restarts running agents to pick up the re-extracted core.
        fs::write(agent_code_dir(config).join(FINGERPRINT_MARKER), "different-version").expect("write marker");
        assert!(agent_code_is_stale(config), "a fingerprint mismatch must read as stale");
    }
}
