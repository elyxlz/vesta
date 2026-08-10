//! The maintenance cycle: when the pass fires, which agents it snapshots, and the snapshot itself
//! applied to one agent. The routine pass and the update's pre-update pass both drive
//! `snapshot_agent` from here, so neither owns the other's module.

use crate::settings::BackupGlobalSettings;
use crate::state::{agent_write_guard, AppState};
use crate::types::{BackupInfo, BackupType};

/// Concurrent snapshots per pass. Repos are per-agent so restic never contends;
/// disk IO is the resource this bounds.
pub const SNAPSHOT_CONCURRENCY: usize = 2;
/// A pre-update snapshot this fresh for the same from-version is reused instead of
/// re-taken, so a retried apply within the window doesn't stack snapshots.
pub const PRE_UPDATE_REUSE_SECS: u64 = 24 * 3600;
/// Minimum gap between passes: one per day, tolerant of the window drifting across
/// DST or a fleet timezone change.
pub const PASS_DEDUP_SECS: u64 = 20 * 3600;

#[derive(Debug, Clone, PartialEq)]
pub enum PassKind {
    Routine,
    PreUpdate { from_version: String },
}

impl PassKind {
    /// The pre-update pass for the vestad version currently running: the version its
    /// snapshots roll back to, stamped as their `from-version` tag.
    pub fn pre_update_from_current() -> Self {
        Self::PreUpdate { from_version: format!("v{}", env!("CARGO_PKG_VERSION")) }
    }

    /// The snapshot type this pass produces.
    pub fn backup_type(&self) -> BackupType {
        match self {
            Self::Routine => BackupType::Periodic,
            Self::PreUpdate { .. } => BackupType::PreUpdate,
        }
    }

    /// The `from-version` tag this pass stamps on its snapshots.
    pub fn version_tag(&self) -> Option<&str> {
        match self {
            Self::Routine => None,
            Self::PreUpdate { from_version } => Some(from_version),
        }
    }
}

/// The one firing rule: only inside the window, at a poll where every agent is idle
/// or at the window's last poll (so maintenance always lands within its window).
pub fn should_fire(in_window: bool, window_closing: bool, all_idle: bool) -> bool {
    in_window && (all_idle || window_closing)
}

/// Whether this agent needs a snapshot in a pass of `kind`. Routine passes snapshot
/// only agents with no fresh auto snapshot (periodic or pre-update, within
/// `every_n_days`); pre-update passes snapshot every agent, reusing only a fresh
/// same-version set. Manual and pre-restore snapshots never satisfy either.
pub fn agent_needs_snapshot(
    kind: &PassKind,
    backups: &[BackupInfo],
    now_epoch: u64,
    every_n_days: u8,
) -> bool {
    match kind {
        PassKind::Routine => {
            let stale_before = now_epoch.saturating_sub(u64::from(every_n_days) * 86_400);
            !backups.iter().any(|b| {
                matches!(b.backup_type, BackupType::Periodic | BackupType::PreUpdate)
                    && crate::time_utils::parse_compact_utc_epoch(&b.created_at)
                        .is_some_and(|epoch| epoch >= stale_before)
            })
        }
        PassKind::PreUpdate { from_version } => {
            let reuse_after = now_epoch.saturating_sub(PRE_UPDATE_REUSE_SECS);
            !backups.iter().any(|b| {
                b.backup_type == BackupType::PreUpdate
                    && b.from_version.as_deref() == Some(from_version)
                    && crate::time_utils::parse_compact_utc_epoch(&b.created_at)
                        .is_some_and(|epoch| epoch >= reuse_after)
            })
        }
    }
}

/// Snapshot one agent if the pass selects it, then apply retention. The error is reported as well as
/// logged, because the pre-update pass turns it into the warning the user sees on the update screen;
/// an agent the pass skips (backups off, too young, snapshot still fresh) is a plain Ok.
pub(crate) async fn snapshot_agent(
    state: &AppState,
    name: &str,
    kind: &PassKind,
    backup_settings: &BackupGlobalSettings,
    now_epoch: u64,
) -> Result<(), crate::docker::DockerError> {
    let (agent_enabled, retention) = backup_settings.effective_for(name);
    if !agent_enabled {
        tracing::debug!(agent = %name, "maintenance: backups disabled for agent, skipping");
        return Ok(());
    }
    if let Some(age) = crate::backup::container_age_secs(&state.docker, name).await {
        if age < crate::backup::MIN_AGE_FOR_BACKUP_SECS {
            tracing::debug!(agent = %name, age_hours = age / 3600, "maintenance: skipping young agent");
            return Ok(());
        }
    }

    let _guard = agent_write_guard(state, name).await;
    let mut backups = match crate::backup::list_backups(&state.env_config.agents_dir, name).await {
        Ok(b) => b,
        Err(e) => {
            tracing::error!(agent = %name, error = %e, "maintenance: failed to list backups");
            return Err(e);
        }
    };
    if agent_needs_snapshot(kind, &backups, now_epoch, backup_settings.every_n_days) {
        let _file_lock = match crate::backup::agent_file_lock(name) {
            Ok(lock) => lock,
            Err(e) => {
                tracing::error!(agent = %name, error = %e, "maintenance: failed to acquire lock");
                return Err(e);
            }
        };
        // Scheduled snapshots carry the same roster badge a manual backup does, and mark the
        // work as planned for the lifecycle push.
        let _operation = crate::agent_status::PublishedOperation::new(
            state.agent_status_cache.clone(),
            name,
            crate::docker::AgentOperation::BackingUp,
        );
        match crate::backup::create_backup(&state.docker, name, kind.backup_type(), kind.version_tag()).await {
            Ok(info) => {
                if info.backup_type == crate::types::BackupType::PreUpdate {
                    let superseded: Vec<String> = backups
                        .iter()
                        .filter(|b| b.backup_type == crate::types::BackupType::Periodic)
                        .map(|b| b.id.clone())
                        .collect();
                    if !superseded.is_empty() {
                        tracing::info!(agent = %name, count = superseded.len(), "maintenance: clearing periodic snapshots superseded by pre-update set");
                        if let Err(e) = crate::restic::forget(name, &superseded).await {
                            tracing::warn!(agent = %name, error = %e, "maintenance: failed to clear periodic snapshots");
                        } else {
                            backups.retain(|b| b.backup_type != crate::types::BackupType::Periodic);
                        }
                    }
                }
                backups.insert(0, info);
            }
            Err(e) => {
                tracing::error!(agent = %name, error = %e, "maintenance: snapshot failed");
                // Retention still runs below for a failed snapshot, so report the failure after it.
                crate::backup::cleanup_backups(name, &backups, &retention).await;
                return Err(e);
            }
        }
    }
    // Retention runs even when no snapshot was taken, so a tightened policy prunes on the
    // next pass instead of waiting days for the next snapshot to trigger it.
    crate::backup::cleanup_backups(name, &backups, &retention).await;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const NOW: u64 = 1_780_000_000;
    const DAY: u64 = 86_400;

    fn backup_at(backup_type: BackupType, epoch: u64, from_version: Option<&str>) -> BackupInfo {
        BackupInfo {
            id: format!("{backup_type}-{epoch}"),
            agent_name: "a".to_string(),
            backup_type,
            created_at: crate::time_utils::now_timestamp_from_epoch(epoch),
            size: 1000,
            from_version: from_version.map(str::to_string),
        }
    }

    fn periodic_at(epoch: u64) -> BackupInfo {
        backup_at(BackupType::Periodic, epoch, None)
    }

    fn pre_update_at(epoch: u64, version: &str) -> BackupInfo {
        backup_at(BackupType::PreUpdate, epoch, Some(version))
    }

    #[test]
    fn routine_selects_only_stale_agents() {
        let kind = PassKind::Routine;
        assert!(agent_needs_snapshot(&kind, &[], NOW, 3), "no snapshots is stale");
        assert!(agent_needs_snapshot(&kind, &[periodic_at(NOW - 4 * DAY)], NOW, 3));
        assert!(!agent_needs_snapshot(&kind, &[periodic_at(NOW - 2 * DAY)], NOW, 3));
        // A recent pre-update snapshot also satisfies freshness.
        assert!(!agent_needs_snapshot(&kind, &[pre_update_at(NOW - DAY, "v0.1.182")], NOW, 3));
        // Manual snapshots do not count toward auto freshness.
        assert!(agent_needs_snapshot(
            &kind,
            &[backup_at(BackupType::Manual, NOW - 3600, None)],
            NOW,
            3
        ));
    }

    #[test]
    fn pre_update_selects_all_but_reuses_fresh_same_version_sets() {
        let kind = PassKind::PreUpdate { from_version: "v0.1.182".into() };
        assert!(agent_needs_snapshot(&kind, &[], NOW, 3));
        assert!(
            agent_needs_snapshot(&kind, &[periodic_at(NOW - 1)], NOW, 3),
            "periodic never substitutes a rollback point"
        );
        assert!(
            !agent_needs_snapshot(&kind, &[pre_update_at(NOW - 3600, "v0.1.182")], NOW, 3),
            "retry reuses a <24h same-version set"
        );
        assert!(agent_needs_snapshot(&kind, &[pre_update_at(NOW - 25 * 3600, "v0.1.182")], NOW, 3));
        assert!(
            agent_needs_snapshot(&kind, &[pre_update_at(NOW - 3600, "v0.1.181")], NOW, 3),
            "different from-version never reused"
        );
    }

    #[test]
    fn pass_kind_owns_its_snapshot_type_and_version_tag() {
        let routine = PassKind::Routine;
        assert_eq!(routine.backup_type(), BackupType::Periodic);
        assert_eq!(routine.version_tag(), None);

        let pre_update = PassKind::pre_update_from_current();
        assert_eq!(pre_update.backup_type(), BackupType::PreUpdate);
        let expected_tag = format!("v{}", env!("CARGO_PKG_VERSION"));
        assert_eq!(pre_update.version_tag(), Some(expected_tag.as_str()));
    }

    #[test]
    fn pass_fires_on_idle_or_at_window_close() {
        assert!(!should_fire(false, false, true), "never outside the window");
        assert!(should_fire(true, false, true), "idle poll inside the window fires");
        assert!(!should_fire(true, false, false), "busy agents defer the pass");
        assert!(should_fire(true, true, false), "the last in-window poll fires regardless");
    }
}
