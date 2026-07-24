//! Canonical reasons for every vestad-driven agent lifecycle transition.
//!
//! Reasons use `category: human detail`: the category keeps operational logs greppable, while
//! the agent's restart message strips non-crash categories and shows only the human detail.

pub const DEFAULT_RESTART: &str = "manual: restart requested";
pub const MANUAL_START: &str = "manual: you were started";
pub const MANUAL_STOP: &str = "manual: you were stopped";
pub const START_ALL: &str = "manual: all agents were started";
pub const DESTROY: &str = "manual: you were deleted";

pub const SCHEDULED_BACKUP: &str = "backup: you were paused for a scheduled backup";
pub const MANUAL_BACKUP: &str = "backup: you were paused for a manual backup";
pub const PRE_RESTORE_BACKUP: &str = "backup: you were paused for a safety backup before a restore";
pub const BACKUP_EXPORT: &str = "backup: you were paused for a backup export";
pub const BACKUP_IMPORT: &str = "backup: you were imported from a backup export";

pub const RESTORE_SHUTDOWN: &str = "restore: you were stopped to restore a backup";
pub const RESTORE_BOOT: &str = "restore: you were restored from a backup";
pub const RESTORE_ABORTED: &str = "restore: the restore did not complete; you resumed unchanged";

pub const VESTAD_SHUTDOWN: &str = "system: vestad is shutting down";
pub const VESTAD_RESUME: &str = "system: you resumed after vestad restarted";
pub const CONFIG_WRITE_START: &str =
    "system: you were started so a configuration change could be applied";
pub const CODE_UPDATE: &str = "update: restarting to load updated agent code";
pub const CONTAINER_UPDATE: &str = "update: restarting to apply updated container configuration";
pub const DESIRED_STOP: &str = "system: stopping to match the requested state";

pub fn rename_shutdown(new_name: &str) -> String {
    format!("rename: you are being renamed to {new_name}")
}

pub fn rename_boot(old_name: &str, new_name: &str) -> String {
    format!("rename: you were renamed from {old_name} to {new_name}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_static_reason_has_a_category_and_human_detail() {
        for reason in [
            DEFAULT_RESTART,
            MANUAL_START,
            MANUAL_STOP,
            START_ALL,
            DESTROY,
            SCHEDULED_BACKUP,
            MANUAL_BACKUP,
            PRE_RESTORE_BACKUP,
            BACKUP_EXPORT,
            BACKUP_IMPORT,
            RESTORE_SHUTDOWN,
            RESTORE_BOOT,
            RESTORE_ABORTED,
            VESTAD_SHUTDOWN,
            VESTAD_RESUME,
            CONFIG_WRITE_START,
            CODE_UPDATE,
            CONTAINER_UPDATE,
            DESIRED_STOP,
        ] {
            let (category, detail) = reason
                .split_once(": ")
                .expect("lifecycle reasons use 'category: detail'");
            assert!(!category.is_empty());
            assert!(!detail.is_empty());
        }
    }

    #[test]
    fn rename_reasons_name_both_sides_of_the_transition() {
        assert_eq!(
            rename_shutdown("luna"),
            "rename: you are being renamed to luna"
        );
        assert_eq!(
            rename_boot("selene", "luna"),
            "rename: you were renamed from selene to luna"
        );
    }
}
