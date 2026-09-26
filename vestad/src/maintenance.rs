//! The maintenance cycle: when the pass fires, which agents it snapshots, the snapshot itself
//! applied to one agent, and the compaction a routine snapshot can call for. The routine pass and
//! the update's pre-update pass both drive `snapshot_agent` from here, so neither owns the other's
//! module.

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
/// The freshness window is this much shorter than the cadence. The pass lands at about the
/// same clock time every night, so an exact `every_n_days * 86_400` window would read the
/// previous pass's own snapshot as fresh by seconds and capture every other night. A
/// snapshot counts as fresh only if it is meaningfully younger than the cadence.
const SNAPSHOT_FRESHNESS_SLACK_SECS: u64 = 2 * 3600;
/// Dead bytes (image files the agent has since deleted or rewritten) an agent must carry before a
/// routine pass compacts it. Both floors must hold, so a small agent never pays the restart.
const COMPACT_MIN_DEAD_BYTES: u64 = 5_000_000_000;
const COMPACT_MIN_DEAD_PERCENT_OF_LIVE: u64 = 25;

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
            let stale_before = now_epoch
                .saturating_sub(u64::from(every_n_days) * 86_400)
                .saturating_add(SNAPSHOT_FRESHNESS_SLACK_SECS);
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

/// The bytes a compaction would reclaim, when that is worth a restart. `root_fs_bytes` counts every
/// layer the container holds; `live_bytes` is what its export streamed, only the visible files. A
/// zero live size is an unmeasured snapshot, never an empty agent.
pub fn compaction_worth(root_fs_bytes: u64, live_bytes: u64) -> Option<u64> {
    let dead = root_fs_bytes.saturating_sub(live_bytes);
    let worth = live_bytes > 0
        && dead > COMPACT_MIN_DEAD_BYTES
        && dead.saturating_mul(100) > live_bytes.saturating_mul(COMPACT_MIN_DEAD_PERCENT_OF_LIVE);
    worth.then_some(dead)
}

/// Compact one agent after its routine snapshot when its image carries enough dead weight. The
/// snapshot is the live-size measure and the rollback point should the recreate go wrong.
pub(crate) async fn compact_if_bloated(state: &AppState, name: &str, snapshot: &BackupInfo) {
    let cname = crate::docker::container_name(name);
    let Some(root_fs_bytes) = crate::docker::container_size_root_fs(&state.docker, &cname).await
    else {
        return;
    };
    let Some(dead_bytes) = compaction_worth(root_fs_bytes, snapshot.size) else {
        return;
    };
    let _guard = agent_write_guard(state, name).await;
    // The stop/start cycle is planned work, kept out of the lifecycle push.
    let _operation = crate::agent_status::PublishedOperation::new(
        state.agent_status_cache.clone(),
        name,
        crate::docker::AgentOperation::Restarting,
    );
    tracing::info!(agent = %name, dead_bytes, live_bytes = snapshot.size, "maintenance: compacting");
    let user_mounts = state.settings.read().await.agent_mounts(name);
    match crate::docker::compact_agent(
        &state.docker,
        name,
        &state.env_config,
        &user_mounts,
        snapshot.size,
        &state.rebuilding,
    )
    .await
    {
        Ok(()) => tracing::info!(agent = %name, dead_bytes, "maintenance: compacted"),
        Err(e) => tracing::error!(agent = %name, error = %e, "maintenance: compaction failed"),
    }
    // A recreated container can come up on a new address.
    state.agent_status_cache.clear_bridge_ip(name);
}

/// Snapshot one agent if the pass selects it, then apply retention, returning the snapshot taken. The
/// error is reported as well as logged, because the pre-update pass turns it into the warning the user
/// sees on the update screen; an agent the pass skips (backups off, too young, snapshot still fresh) is
/// a plain `Ok(None)`.
pub(crate) async fn snapshot_agent(
    state: &AppState,
    name: &str,
    kind: &PassKind,
    backup_settings: &BackupGlobalSettings,
    now_epoch: u64,
) -> Result<Option<BackupInfo>, crate::docker::DockerError> {
    let (agent_enabled, retention) = backup_settings.effective_for(name);
    if !agent_enabled {
        tracing::debug!(agent = %name, "maintenance: backups disabled for agent, skipping");
        return Ok(None);
    }
    if let Some(age) = crate::backup::container_age_secs(&state.docker, name).await {
        if age < crate::backup::MIN_AGE_FOR_BACKUP_SECS {
            tracing::debug!(agent = %name, age_hours = age / 3600, "maintenance: skipping young agent");
            return Ok(None);
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
    let mut taken = None;
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
                taken = Some(info.clone());
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
    Ok(taken)
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
            vestad_version: None,
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
    fn nightly_pass_survives_last_nights_snapshot_at_the_same_clock_time() {
        // The pass lands at about the same clock time each night, so an exact one-day
        // freshness window would read last night's own snapshot as fresh and capture
        // every other night instead of nightly.
        let kind = PassKind::Routine;
        assert!(
            agent_needs_snapshot(&kind, &[periodic_at(NOW - DAY + 30)], NOW, 1),
            "last night's snapshot must not suppress tonight's pass"
        );
        assert!(
            !agent_needs_snapshot(&kind, &[periodic_at(NOW - 3 * 3600)], NOW, 1),
            "a snapshot from a few hours ago still suppresses the pass"
        );
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

    const GB: u64 = 1_000_000_000;

    #[test]
    fn compaction_reclaims_a_heavily_bloated_agent() {
        // okami: 202 GB on disk, 54 GB live.
        assert_eq!(compaction_worth(202 * GB, 54 * GB), Some(148 * GB));
    }

    #[test]
    fn compaction_skips_an_agent_with_little_dead_weight() {
        // aria: 9.7 GB on disk, 9.43 GB live.
        assert_eq!(compaction_worth(9_700_000_000, 9_430_000_000), None);
    }

    #[test]
    fn compaction_needs_both_the_absolute_and_the_relative_floor() {
        assert_eq!(
            compaction_worth(10 * GB, 5 * GB),
            None,
            "5 GB dead is not above the floor"
        );
        assert_eq!(
            compaction_worth(106 * GB, 100 * GB),
            None,
            "6 GB dead is only 6% of live"
        );
        assert_eq!(
            compaction_worth(26 * GB, 20 * GB),
            Some(6 * GB),
            "6 GB dead is 30% of live"
        );
    }

    #[test]
    fn compaction_never_trusts_an_unmeasured_snapshot() {
        assert_eq!(compaction_worth(200 * GB, 0), None);
    }

    #[test]
    fn compaction_reads_live_above_root_fs_as_nothing_dead() {
        assert_eq!(compaction_worth(10 * GB, 11 * GB), None);
    }
}
