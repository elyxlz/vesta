//! Canonical copy for every vestad-driven agent lifecycle transition.
//!
//! `log_reason` is terse, categorized operational copy used in shutdown/startup logs.
//! `agent_message` is a complete sentence delivered only to an authenticated agent.

use std::borrow::Cow;

use serde::Serialize;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct LifecycleReason<'a> {
    pub log_reason: Cow<'a, str>,
    pub agent_message: Cow<'a, str>,
}

impl LifecycleReason<'static> {
    pub const fn borrowed(log_reason: &'static str, agent_message: &'static str) -> Self {
        Self {
            log_reason: Cow::Borrowed(log_reason),
            agent_message: Cow::Borrowed(agent_message),
        }
    }

    pub fn owned(log_reason: impl Into<String>, agent_message: impl Into<String>) -> Self {
        Self {
            log_reason: Cow::Owned(log_reason.into()),
            agent_message: Cow::Owned(agent_message.into()),
        }
    }

    pub fn from_legacy(log_reason: String, agent_message: Option<String>) -> Self {
        let fallback = || {
            let detail = log_reason.split_once(": ").map(|(_, detail)| detail);
            if log_reason.starts_with("crash:") || log_reason.starts_with("error:") {
                log_reason.clone()
            } else {
                detail.unwrap_or(&log_reason).to_string()
            }
        };
        let agent_message = agent_message
            .filter(|message| !message.trim().is_empty())
            .unwrap_or_else(fallback);
        Self::owned(log_reason, agent_message)
    }
}

pub static DEFAULT_RESTART: LifecycleReason<'static> =
    LifecycleReason::borrowed("manual: restart requested", "You were restarted manually.");
pub static MANUAL_START: LifecycleReason<'static> =
    LifecycleReason::borrowed("manual: start requested", "You were started manually.");
pub static MANUAL_STOP: LifecycleReason<'static> =
    LifecycleReason::borrowed("manual: stop requested", "You were stopped manually.");
pub static START_ALL: LifecycleReason<'static> =
    LifecycleReason::borrowed("manual: start-all requested", "You were started manually.");
pub static DESTROY: LifecycleReason<'static> =
    LifecycleReason::borrowed("manual: delete requested", "You were deleted.");

pub static SCHEDULED_BACKUP: LifecycleReason<'static> = LifecycleReason::borrowed(
    "backup: scheduled",
    "The system briefly paused you while it created a scheduled backup. No action is required.",
);
pub static MANUAL_BACKUP: LifecycleReason<'static> = LifecycleReason::borrowed(
    "backup: manual",
    "The system briefly paused you while it created a manual backup. No action is required.",
);
pub static PRE_RESTORE_BACKUP: LifecycleReason<'static> = LifecycleReason::borrowed(
    "backup: pre-restore safety backup",
    "The system briefly paused you while it created a safety backup before a restore. No action is required.",
);
pub static BACKUP_EXPORT: LifecycleReason<'static> = LifecycleReason::borrowed(
    "backup: export",
    "The system briefly paused you while it exported a backup. No action is required.",
);
pub static BACKUP_IMPORT: LifecycleReason<'static> = LifecycleReason::borrowed(
    "backup: import",
    "You were restored from an exported backup.",
);

pub static RESTORE_SHUTDOWN: LifecycleReason<'static> = LifecycleReason::borrowed(
    "restore: preparing",
    "The system stopped you to restore a backup.",
);
pub static RESTORE_BOOT: LifecycleReason<'static> =
    LifecycleReason::borrowed("restore: completed", "You were restored from a backup.");
pub static RESTORE_ABORTED: LifecycleReason<'static> = LifecycleReason::borrowed(
    "restore: aborted",
    "The restore did not complete, so you resumed unchanged.",
);

pub static VESTAD_SHUTDOWN: LifecycleReason<'static> = LifecycleReason::borrowed(
    "system: vestad shutdown",
    "The system stopped you while its service shut down.",
);
pub static VESTAD_RESUME: LifecycleReason<'static> = LifecycleReason::borrowed(
    "system: vestad restarted",
    "You resumed after the system service restarted.",
);
pub static CONFIG_WRITE_START: LifecycleReason<'static> = LifecycleReason::borrowed(
    "system: configuration write",
    "You were started so the system could apply a configuration change.",
);
pub static CODE_UPDATE: LifecycleReason<'static> = LifecycleReason::borrowed(
    "update: agent code changed",
    "Your runtime restarted to load updated agent code.",
);
pub static CONTAINER_UPDATE: LifecycleReason<'static> = LifecycleReason::borrowed(
    "update: container configuration changed",
    "Your runtime restarted to apply updated container configuration.",
);
pub static DESIRED_STOP: LifecycleReason<'static> = LifecycleReason::borrowed(
    "system: desired state is stopped",
    "The system stopped you to match the requested state.",
);

pub fn rename(old_name: &str, new_name: &str) -> LifecycleReason<'static> {
    LifecycleReason::owned(
        format!("rename: {old_name} -> {new_name}"),
        format!("Your name changed from {old_name} to {new_name}."),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_static_reason_has_distinct_operational_and_agent_copy() {
        for reason in [
            &DEFAULT_RESTART,
            &MANUAL_START,
            &MANUAL_STOP,
            &START_ALL,
            &DESTROY,
            &SCHEDULED_BACKUP,
            &MANUAL_BACKUP,
            &PRE_RESTORE_BACKUP,
            &BACKUP_EXPORT,
            &BACKUP_IMPORT,
            &RESTORE_SHUTDOWN,
            &RESTORE_BOOT,
            &RESTORE_ABORTED,
            &VESTAD_SHUTDOWN,
            &VESTAD_RESUME,
            &CONFIG_WRITE_START,
            &CODE_UPDATE,
            &CONTAINER_UPDATE,
            &DESIRED_STOP,
        ] {
            let (category, detail) = reason
                .log_reason
                .split_once(": ")
                .expect("lifecycle reasons use 'category: detail'");
            assert!(!category.is_empty());
            assert!(!detail.is_empty());
            assert!(reason.agent_message.ends_with('.'));
            assert_ne!(reason.log_reason, reason.agent_message);
        }
    }

    #[test]
    fn rename_reason_has_copy_for_both_audiences() {
        let reason = rename("selene", "luna");
        assert_eq!(reason.log_reason, "rename: selene -> luna",);
        assert_eq!(
            reason.agent_message,
            "Your name changed from selene to luna.",
        );
    }

    #[test]
    fn legacy_reason_derives_the_old_agent_copy() {
        let reason = LifecycleReason::from_legacy("provider: model changed".to_string(), None);
        assert_eq!(reason.log_reason, "provider: model changed");
        assert_eq!(reason.agent_message, "model changed");
    }

    #[test]
    fn boot_inbox_json_uses_the_agent_contract_field_names() {
        assert_eq!(
            serde_json::to_value(&SCHEDULED_BACKUP).unwrap(),
            serde_json::json!({
                "log_reason": "backup: scheduled",
                "agent_message": concat!(
                    "The system briefly paused you while it created a scheduled backup. ",
                    "No action is required."
                ),
            }),
        );
    }
}
