//! Host filesystem grants: user-authored bind mounts that give an agent access to
//! specific host paths. The single owner of the mount format, validation, and the
//! protected-prefix rule. A grant is a decision only the user makes (see serve.rs auth).

use serde::{Deserialize, Serialize};
use std::fmt;

/// Container-path roots a grant may never mount onto. `/root` covers the agent's entire
/// world (home, `/root/agent/data` = events.db + state.json, `/root/.claude` = auth,
/// `/root/agent/core` = code); the rest are OS dirs whose replacement would break the
/// container. Everything outside these — `/mnt`, `/media`, `/data`, `/srv`, … — is allowed.
pub const PROTECTED_PREFIXES: &[&str] = &[
    "/root", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/run", "/proc", "/sys", "/dev", "/boot",
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HostMount {
    pub host_path: String,
    pub container_path: String,
    #[serde(default)]
    pub writable: bool,
}

#[derive(Debug)]
pub enum MountError {
    NotAbsolute,
    HostPathMissing,
    ContainerPathProtected(String),
    DuplicateContainerPath(String),
}

impl fmt::Display for MountError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MountError::NotAbsolute => write!(f, "path must be absolute"),
            MountError::HostPathMissing => write!(f, "host path does not exist"),
            MountError::ContainerPathProtected(path) => {
                write!(f, "container path '{path}' is protected; choose a path outside /root and system dirs, e.g. under /mnt")
            }
            MountError::DuplicateContainerPath(path) => write!(f, "duplicate container path '{path}'"),
        }
    }
}

impl std::error::Error for MountError {}

/// Normalize by stripping a single trailing slash (but keep root "/").
fn normalize(path: &str) -> &str {
    if path.len() > 1 {
        path.strip_suffix('/').unwrap_or(path)
    } else {
        path
    }
}

/// True if `container_path` is at or under any protected root, or is `/` itself.
pub fn is_protected(container_path: &str) -> bool {
    let path = normalize(container_path);
    if path == "/" {
        return true;
    }
    PROTECTED_PREFIXES.iter().any(|root| path == *root || path.starts_with(&format!("{root}/")))
}

/// Validate one grant. `host_path` must be absolute and exist (canonicalized). The container
/// path defaults to the (canonicalized) host path and must not be protected.
pub fn validate_mount(host_path: &str, container_path: Option<&str>, writable: bool) -> Result<HostMount, MountError> {
    if !host_path.starts_with('/') {
        return Err(MountError::NotAbsolute);
    }
    let canonical = std::fs::canonicalize(host_path).map_err(|_| MountError::HostPathMissing)?;
    let canonical = canonical.to_string_lossy().to_string();

    let container = match container_path {
        Some(cp) => {
            if !cp.starts_with('/') {
                return Err(MountError::NotAbsolute);
            }
            normalize(cp).to_string()
        }
        None => canonical.clone(),
    };
    if is_protected(&container) {
        return Err(MountError::ContainerPathProtected(container));
    }
    if std::path::Path::new(&container).components().any(|c| matches!(c, std::path::Component::ParentDir)) {
        return Err(MountError::ContainerPathProtected(container));
    }
    Ok(HostMount { host_path: canonical, container_path: container, writable })
}

/// Validate a full list and reject duplicate container paths (two grants can't target one dest).
pub fn validate_mounts(inputs: &[(String, Option<String>, bool)]) -> Result<Vec<HostMount>, MountError> {
    let mut out: Vec<HostMount> = Vec::with_capacity(inputs.len());
    for (host, container, writable) in inputs {
        let mount = validate_mount(host, container.as_deref(), *writable)?;
        if out.iter().any(|m| m.container_path == mount.container_path) {
            return Err(MountError::DuplicateContainerPath(mount.container_path));
        }
        out.push(mount);
    }
    Ok(out)
}

/// The Docker `-v` bind spec: `host:container:{ro|rw},z`.
pub fn bind_string(m: &HostMount) -> String {
    let mode = if m.writable { "rw" } else { "ro" };
    format!("{}:{}:{mode},z", m.host_path, m.container_path)
}

/// Host roots whose immediate subdirectories are common places to share (media libraries,
/// downloads, data disks). Their children — e.g. `/mnt/media` — are the suggestions.
pub const SUGGESTION_ROOTS: &[&str] = &["/mnt", "/media", "/srv", "/data", "/pool", "/tank"];

/// Well-known folders inside the host user's home worth suggesting when they exist.
pub const HOME_SUGGESTIONS: &[&str] =
    &["Downloads", "Movies", "Videos", "Music", "Pictures", "Documents"];

/// Existing host folders to suggest as shares, so the user doesn't hand-type a path. Scans the
/// immediate children of the common mount roots plus a few well-known home folders. Only
/// directories that actually exist are returned.
pub fn suggest_host_folders() -> Vec<String> {
    scan_candidate_folders(
        SUGGESTION_ROOTS,
        std::env::var("HOME").ok().as_deref(),
        HOME_SUGGESTIONS,
    )
}

fn scan_candidate_folders(roots: &[&str], home: Option<&str>, home_dirs: &[&str]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for root in roots {
        let Ok(entries) = std::fs::read_dir(root) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                out.push(path.to_string_lossy().into_owned());
            }
        }
    }
    if let Some(home) = home {
        for name in home_dirs {
            let path = std::path::Path::new(home).join(name);
            if path.is_dir() {
                out.push(path.to_string_lossy().into_owned());
            }
        }
    }
    out.sort();
    out.dedup();
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mirror_uses_canonical_host_path_as_container_path() {
        let dir = std::env::temp_dir();
        let sub = dir.join("vesta-mount-test");
        std::fs::create_dir_all(&sub).unwrap();
        let m = validate_mount(sub.to_str().unwrap(), None, false).unwrap();
        assert_eq!(m.container_path, m.host_path);
        assert!(!m.writable);
    }

    #[test]
    fn rejects_relative_host_path() {
        assert!(matches!(validate_mount("relative/path", None, false), Err(MountError::NotAbsolute)));
    }

    #[test]
    fn scan_lists_existing_subdirs_and_home_media_only() {
        let tmp = std::env::temp_dir().join(format!("vesta-suggest-{}", std::process::id()));
        let root = tmp.join("mnt");
        std::fs::create_dir_all(root.join("media")).unwrap();
        std::fs::create_dir_all(root.join("downloads")).unwrap();
        std::fs::write(root.join("a-file"), b"x").unwrap(); // a file, not a dir — excluded
        let home = tmp.join("home");
        std::fs::create_dir_all(home.join("Downloads")).unwrap(); // exists
        // "Movies" intentionally not created — must be excluded.

        let got = scan_candidate_folders(&[root.to_str().unwrap()], home.to_str(), &["Downloads", "Movies"]);

        assert!(got.iter().any(|p| p.ends_with("/media")), "should list /mnt/media child: {got:?}");
        assert!(got.iter().any(|p| p.ends_with("/downloads")));
        assert!(got.iter().any(|p| p.ends_with("/Downloads")), "should include existing home folder");
        assert!(!got.iter().any(|p| p.ends_with("/a-file")), "files must be excluded");
        assert!(!got.iter().any(|p| p.ends_with("/Movies")), "nonexistent home folder must be excluded");
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn rejects_missing_host_path() {
        assert!(matches!(validate_mount("/definitely/does/not/exist/xyzzy", None, false), Err(MountError::HostPathMissing)));
    }

    #[test]
    fn rejects_dotdot_in_container_path() {
        let dir = std::env::temp_dir();
        let sub = dir.join("vesta-mount-test-dotdot");
        std::fs::create_dir_all(&sub).unwrap();
        assert!(matches!(
            validate_mount(sub.to_str().unwrap(), Some("/mnt/../root/.claude"), false),
            Err(MountError::ContainerPathProtected(_))
        ));
    }

    #[test]
    fn rejects_protected_container_paths() {
        assert!(is_protected("/root"));
        assert!(is_protected("/root/agent/data"));
        assert!(is_protected("/root/.claude"));
        assert!(is_protected("/etc/passwd"));
        assert!(is_protected("/"));
        assert!(is_protected("/usr/bin"));
    }

    #[test]
    fn allows_neutral_roots() {
        assert!(!is_protected("/mnt/media"));
        assert!(!is_protected("/data/movies"));
        assert!(!is_protected("/srv/plex"));
        assert!(!is_protected("/media"));
        // A prefix that merely starts with "/roo" but is not "/root" must be allowed.
        assert!(!is_protected("/rootfs/data"));
    }

    #[test]
    fn bind_string_ro_and_rw() {
        let ro = HostMount { host_path: "/mnt/media".into(), container_path: "/mnt/media".into(), writable: false };
        assert_eq!(bind_string(&ro), "/mnt/media:/mnt/media:ro,z");
        let rw = HostMount { host_path: "/mnt/dl".into(), container_path: "/mnt/dl".into(), writable: true };
        assert_eq!(bind_string(&rw), "/mnt/dl:/mnt/dl:rw,z");
    }

    #[test]
    fn validate_mounts_rejects_duplicate_container_path() {
        // Host paths must exist (validate_mount canonicalizes them), so use real tmpdirs
        // rather than the brief's illustrative "/mnt/a"/"/mnt/b" which don't exist on
        // arbitrary hosts.
        let dir = std::env::temp_dir();
        let sub_a = dir.join("vesta-mount-test-dup-a");
        let sub_b = dir.join("vesta-mount-test-dup-b");
        std::fs::create_dir_all(&sub_a).unwrap();
        std::fs::create_dir_all(&sub_b).unwrap();
        let inputs = vec![
            (sub_a.to_str().unwrap().to_string(), Some("/mnt/x".to_string()), false),
            (sub_b.to_str().unwrap().to_string(), Some("/mnt/x".to_string()), false),
        ];
        assert!(matches!(validate_mounts(&inputs), Err(MountError::DuplicateContainerPath(_))));
    }
}
