//! Host filesystem grants: user-authored bind mounts that give an agent access to
//! specific host paths. The single owner of the mount format, validation, and the
//! protected-prefix rule. A grant is a decision only the user makes (see serve.rs auth).

use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fmt;

/// Container-path roots a grant may never mount onto at all (prefix match). `/root` covers the
/// agent's entire world (home, `/root/agent/data` = events.db + state.json, `/root/.claude` = auth,
/// `/root/agent/core` = code); the rest are OS dirs whose replacement would break the container.
pub const PROTECTED_PREFIXES: &[&str] = &[
    "/root", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/run", "/proc", "/sys", "/dev",
    "/boot",
];

/// Writable container runtime roots that must not be *shadowed at their top level* (mounting onto
/// `/tmp`/`/var`/`/opt` breaks the agent's temp files, logs, etc.), but whose subpaths ARE fine —
/// a grant onto e.g. `/var/lib/plexmediaserver` is legitimate. Exact match only, unlike the prefixes.
pub const PROTECTED_EXACT: &[&str] = &["/tmp", "/var", "/opt"];

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
    HostPathMissing(String),
    ContainerPathProtected(String),
    DuplicateContainerPath(String),
}

impl fmt::Display for MountError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MountError::NotAbsolute => write!(f, "path must be absolute"),
            MountError::HostPathMissing(path) => write!(f, "host path '{path}' does not exist"),
            MountError::ContainerPathProtected(path) => {
                write!(f, "container path '{path}' is protected; choose a path outside /root and system dirs, e.g. under /mnt")
            }
            MountError::DuplicateContainerPath(path) => {
                write!(f, "duplicate container path '{path}'")
            }
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

/// True if `container_path` is `/`, exactly a protected runtime root (`/tmp`, `/var`, `/opt`), or at
/// or under any protected prefix (`/root` and the OS dirs).
pub fn is_protected(container_path: &str) -> bool {
    let path = normalize(container_path);
    if path == "/" || PROTECTED_EXACT.contains(&path) {
        return true;
    }
    PROTECTED_PREFIXES
        .iter()
        .any(|root| path == *root || path.starts_with(&format!("{root}/")))
}

/// Validate one grant. `host_path` must be absolute and (normally) exist — it is canonicalized so the
/// stored form resolves symlinks. The container path defaults to the (canonicalized) host path and
/// must not be protected. `known_host_paths` are the host paths of grants already accepted for this
/// agent: a path in that set that is *temporarily* missing (unplugged drive, unmounted NFS) is kept
/// as-is instead of rejected, so one offline grant can't block edits to unrelated grants. A brand-new
/// missing path is still rejected.
pub fn validate_mount(
    host_path: &str,
    container_path: Option<&str>,
    writable: bool,
    known_host_paths: &HashSet<String>,
) -> Result<HostMount, MountError> {
    if !host_path.starts_with('/') {
        return Err(MountError::NotAbsolute);
    }
    let canonical = match std::fs::canonicalize(host_path) {
        Ok(p) => p.to_string_lossy().to_string(),
        // A grant that was accepted before is already canonical; if it's merely offline now, keep it.
        Err(_) if known_host_paths.contains(host_path) => host_path.to_string(),
        Err(_) => return Err(MountError::HostPathMissing(host_path.to_string())),
    };

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
    if std::path::Path::new(&container)
        .components()
        .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err(MountError::ContainerPathProtected(container));
    }
    Ok(HostMount {
        host_path: canonical,
        container_path: container,
        writable,
    })
}

/// Validate a full list and reject duplicate container paths (two grants can't target one dest).
/// `known_host_paths` (the agent's already-accepted grant paths) grandfathers temporarily-offline
/// existing grants so a single missing path can't reject the whole edit — see `validate_mount`.
pub fn validate_mounts(
    inputs: &[(String, Option<String>, bool)],
    known_host_paths: &HashSet<String>,
) -> Result<Vec<HostMount>, MountError> {
    let mut out: Vec<HostMount> = Vec::with_capacity(inputs.len());
    for (host, container, writable) in inputs {
        let mount = validate_mount(host, container.as_deref(), *writable, known_host_paths)?;
        if out.iter().any(|m| m.container_path == mount.container_path) {
            return Err(MountError::DuplicateContainerPath(mount.container_path));
        }
        out.push(mount);
    }
    Ok(out)
}

/// The Docker `-v` bind spec: `host:container:{ro|rw}`. Deliberately no SELinux `z`/`Z` relabel: a
/// grant shares an *existing* host directory that host services (Plex, Samba, the user) may also use,
/// and `z` would recursively `chcon` the whole tree to a container-shared label — slow on large trees
/// and a host-wide change that can break those services. On an SELinux-enforcing host the user relabels
/// intentionally if needed; we never mutate host labels behind their back.
pub fn bind_string(m: &HostMount) -> String {
    let mode = if m.writable { "rw" } else { "ro" };
    format!("{}:{}:{mode}", m.host_path, m.container_path)
}

/// Join items as "a", "a and b", or "a, b and c" for human-readable reason copy.
fn join_and(items: &[String]) -> String {
    match items {
        [] => String::new(),
        [one] => one.clone(),
        [head @ .., last] => format!("{} and {}", head.join(", "), last),
    }
}

/// A `mounts:` restart reason describing a grant change, or None if nothing changed.
/// `actual` is the container's current user binds as (host, container, writable) tuples
/// (`docker::actual_user_mounts`); `desired` is the new grant list. Classified per
/// container_path: new path = granted, dropped path = removed, same path with a different
/// mode = changed — a downgrade must read as a revocation of write access, never a gain.
pub fn mount_change_reason(
    actual: &[(String, String, bool)],
    desired: &[HostMount],
) -> Option<String> {
    let actual_modes: std::collections::HashMap<&str, bool> = actual
        .iter()
        .map(|(_, container, writable)| (container.as_str(), *writable))
        .collect();
    let desired_paths: std::collections::HashSet<&str> = desired
        .iter()
        .map(|mount| mount.container_path.as_str())
        .collect();

    let mode = |writable: bool| if writable { "read-write" } else { "read-only" };

    let mut granted: Vec<String> = Vec::new();
    let mut changed: Vec<String> = Vec::new();
    for mount in desired {
        match actual_modes.get(mount.container_path.as_str()) {
            None => granted.push(format!(
                "{} ({})",
                mount.container_path,
                mode(mount.writable)
            )),
            Some(current) if *current != mount.writable => {
                changed.push(format!(
                    "{} (now {})",
                    mount.container_path,
                    mode(mount.writable)
                ));
            }
            Some(_) => {}
        }
    }
    let removed: Vec<String> = actual
        .iter()
        .filter(|(_, container, _)| !desired_paths.contains(container.as_str()))
        .map(|(_, container, _)| container.clone())
        .collect();

    match (granted.is_empty(), removed.is_empty(), changed.is_empty()) {
        (true, true, true) => None,
        (false, true, true) => Some(format!(
            "mounts: you now have access to {}",
            join_and(&granted)
        )),
        (true, false, true) => Some(format!(
            "mounts: your access to {} was removed",
            join_and(&removed)
        )),
        (true, true, false) => Some(format!(
            "mounts: your access changed: {}",
            join_and(&changed)
        )),
        _ => {
            let mut segments: Vec<String> = Vec::new();
            if !granted.is_empty() {
                segments.push(format!("granted: {}", granted.join(", ")));
            }
            if !removed.is_empty() {
                segments.push(format!("removed: {}", removed.join(", ")));
            }
            if !changed.is_empty() {
                segments.push(format!("changed: {}", changed.join(", ")));
            }
            Some(format!(
                "mounts: filesystem access changed. {}",
                segments.join("; ")
            ))
        }
    }
}

/// The reason a restart should hand the agent: an explicit caller reason wins; otherwise the
/// mount delta the restart applies speaks for itself; no delta, no reason. Factored pure so the
/// precedence is pinned by a fast test (`restart_agent` itself needs Docker).
pub fn effective_restart_reason(
    caller: Option<String>,
    actual: &[(String, String, bool)],
    desired: &[HostMount],
) -> Option<String> {
    caller.or_else(|| mount_change_reason(actual, desired))
}

/// Host roots whose immediate subdirectories are common places to share (media libraries,
/// downloads, data disks). Their children — e.g. `/mnt/media` — are the suggestions.
pub const SUGGESTION_ROOTS: &[&str] = &["/mnt", "/media", "/srv", "/data", "/pool", "/tank"];

/// Well-known folders inside the host user's home worth suggesting when they exist.
pub const HOME_SUGGESTIONS: &[&str] = &[
    "Downloads",
    "Movies",
    "Videos",
    "Music",
    "Pictures",
    "Documents",
];

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

    fn no_known() -> HashSet<String> {
        HashSet::new()
    }

    fn m(container: &str, writable: bool) -> HostMount {
        HostMount {
            host_path: container.into(),
            container_path: container.into(),
            writable,
        }
    }

    #[test]
    fn mount_change_reason_grants_removals_and_mixed() {
        // single grant
        assert_eq!(
            mount_change_reason(&[], &[m("/media/Plex", false)]).as_deref(),
            Some("mounts: you now have access to /media/Plex (read-only)")
        );
        // multiple grants
        assert_eq!(
            mount_change_reason(&[], &[m("/media/Plex", false), m("/downloads", true)]).as_deref(),
            Some("mounts: you now have access to /media/Plex (read-only) and /downloads (read-write)")
        );
        // removal only
        assert_eq!(
            mount_change_reason(&[("/media/Plex".into(), "/media/Plex".into(), false)], &[])
                .as_deref(),
            Some("mounts: your access to /media/Plex was removed")
        );
        // mixed
        assert_eq!(
            mount_change_reason(&[("/old".into(), "/old".into(), false)], &[m("/media/Plex", false)]).as_deref(),
            Some("mounts: filesystem access changed. granted: /media/Plex (read-only); removed: /old")
        );
        // writable flips are mode changes, not fresh grants: a downgrade must not read as a gain
        assert_eq!(
            mount_change_reason(&[("/x".into(), "/x".into(), true)], &[m("/x", false)]).as_deref(),
            Some("mounts: your access changed: /x (now read-only)")
        );
        assert_eq!(
            mount_change_reason(&[("/x".into(), "/x".into(), false)], &[m("/x", true)]).as_deref(),
            Some("mounts: your access changed: /x (now read-write)")
        );
        // grant + mode change fold into the general branch
        assert_eq!(
            mount_change_reason(&[("/x".into(), "/x".into(), false)], &[m("/x", true), m("/new", false)]).as_deref(),
            Some("mounts: filesystem access changed. granted: /new (read-only); changed: /x (now read-write)")
        );
        // no change
        assert_eq!(
            mount_change_reason(&[("/x".into(), "/x".into(), true)], &[m("/x", true)]),
            None
        );
    }

    #[test]
    fn effective_restart_reason_prefers_the_caller_reason() {
        // Caller intent wins over the synthesized delta...
        assert_eq!(
            effective_restart_reason(
                Some("manual: switching model".into()),
                &[],
                &[m("/new", false)]
            )
            .as_deref(),
            Some("manual: switching model")
        );
        // ...else the delta speaks, and no delta means no reason.
        assert_eq!(
            effective_restart_reason(None, &[], &[m("/new", false)]).as_deref(),
            Some("mounts: you now have access to /new (read-only)")
        );
        assert_eq!(effective_restart_reason(None, &[], &[]), None);
    }

    #[test]
    fn mirror_uses_canonical_host_path_as_container_path() {
        let dir = std::env::temp_dir();
        let sub = dir.join("vesta-mount-test");
        std::fs::create_dir_all(&sub).unwrap();
        let m = validate_mount(sub.to_str().unwrap(), None, false, &no_known()).unwrap();
        assert_eq!(m.container_path, m.host_path);
        assert!(!m.writable);
    }

    #[test]
    fn rejects_relative_host_path() {
        assert!(matches!(
            validate_mount("relative/path", None, false, &no_known()),
            Err(MountError::NotAbsolute)
        ));
    }

    #[test]
    fn known_but_offline_host_path_is_kept_not_rejected() {
        // A grant that was accepted before but whose host path is now missing (unplugged drive)
        // must validate so edits to OTHER grants aren't blocked. It's already canonical, so it's
        // kept as-is; a NEW missing path is still rejected.
        let missing = "/definitely/does/not/exist/offline-drive";
        let known: HashSet<String> = [missing.to_string()].into_iter().collect();
        let m = validate_mount(missing, Some("/mnt/offline"), false, &known).unwrap();
        assert_eq!(m.host_path, missing);
        assert!(matches!(
            validate_mount(missing, Some("/mnt/offline"), false, &no_known()),
            Err(MountError::HostPathMissing(_))
        ));
    }

    #[test]
    fn known_offline_path_still_enforces_container_protection() {
        // Grandfathering an offline host path must not bypass the protected-container-path rule.
        let missing = "/definitely/does/not/exist/offline-drive";
        let known: HashSet<String> = [missing.to_string()].into_iter().collect();
        assert!(matches!(
            validate_mount(missing, Some("/root/.claude"), false, &known),
            Err(MountError::ContainerPathProtected(_))
        ));
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

        let got = scan_candidate_folders(
            &[root.to_str().unwrap()],
            home.to_str(),
            &["Downloads", "Movies"],
        );

        assert!(
            got.iter().any(|p| p.ends_with("/media")),
            "should list /mnt/media child: {got:?}"
        );
        assert!(got.iter().any(|p| p.ends_with("/downloads")));
        assert!(
            got.iter().any(|p| p.ends_with("/Downloads")),
            "should include existing home folder"
        );
        assert!(
            !got.iter().any(|p| p.ends_with("/a-file")),
            "files must be excluded"
        );
        assert!(
            !got.iter().any(|p| p.ends_with("/Movies")),
            "nonexistent home folder must be excluded"
        );
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn rejects_missing_host_path() {
        assert!(matches!(
            validate_mount("/definitely/does/not/exist/xyzzy", None, false, &no_known()),
            Err(MountError::HostPathMissing(_))
        ));
    }

    #[test]
    fn rejects_dotdot_in_container_path() {
        let dir = std::env::temp_dir();
        let sub = dir.join("vesta-mount-test-dotdot");
        std::fs::create_dir_all(&sub).unwrap();
        assert!(matches!(
            validate_mount(
                sub.to_str().unwrap(),
                Some("/mnt/../root/.claude"),
                false,
                &no_known()
            ),
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
        // Writable container runtime roots: shadowing the root itself is blocked...
        assert!(is_protected("/tmp"));
        assert!(is_protected("/var"));
        assert!(is_protected("/opt"));
        // ...but a subpath is fine (e.g. Plex config lives under /var/lib/plexmediaserver).
        assert!(!is_protected("/var/lib/plexmediaserver"));
        assert!(!is_protected("/tmp/shared"));
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
        let ro = HostMount {
            host_path: "/mnt/media".into(),
            container_path: "/mnt/media".into(),
            writable: false,
        };
        assert_eq!(bind_string(&ro), "/mnt/media:/mnt/media:ro");
        let rw = HostMount {
            host_path: "/mnt/dl".into(),
            container_path: "/mnt/dl".into(),
            writable: true,
        };
        assert_eq!(bind_string(&rw), "/mnt/dl:/mnt/dl:rw");
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
            (
                sub_a.to_str().unwrap().to_string(),
                Some("/mnt/x".to_string()),
                false,
            ),
            (
                sub_b.to_str().unwrap().to_string(),
                Some("/mnt/x".to_string()),
                false,
            ),
        ];
        assert!(matches!(
            validate_mounts(&inputs, &no_known()),
            Err(MountError::DuplicateContainerPath(_))
        ));
    }
}
