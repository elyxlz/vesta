//! Canonical copy for every vestad-driven agent lifecycle transition.
//!
//! `log_reason` is terse, categorized operational copy used in shutdown/startup logs.
//! `agent_message` is a complete sentence delivered only to an authenticated agent.

use std::borrow::Cow;

use serde::Serialize;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct LifecycleReason {
    pub log_reason: Cow<'static, str>,
    pub agent_message: Cow<'static, str>,
}

impl LifecycleReason {
    pub const fn borrowed(log_reason: &'static str, agent_message: &'static str) -> Self {
        Self {
            log_reason: Cow::Borrowed(log_reason),
            agent_message: Cow::Borrowed(agent_message),
        }
    }

    /// A transition the agent never reads: it is handed over just before SIGTERM, where only the
    /// operational copy is written, so there is no agent copy to author.
    pub const fn shutdown_only(log_reason: &'static str) -> Self {
        Self::borrowed(log_reason, "")
    }

    pub fn owned(log_reason: impl Into<String>, agent_message: impl Into<String>) -> Self {
        Self {
            log_reason: Cow::Owned(log_reason.into()),
            agent_message: Cow::Owned(agent_message.into()),
        }
    }

    /// Build the reason a client asked for. A client older than the release that ships agent copy
    /// sends only `reason`; an absent agent message stays absent, because the agent derives its own
    /// copy from a bare log reason and is the single owner of that derivation.
    pub fn from_request(log_reason: String, agent_message: Option<String>) -> Self {
        Self::owned(
            log_reason,
            agent_message.filter(|message| !message.trim().is_empty()).unwrap_or_default(),
        )
    }
}

pub static DEFAULT_RESTART: LifecycleReason =
    LifecycleReason::borrowed("manual: restart requested", "You were restarted manually.");
pub static MANUAL_START: LifecycleReason =
    LifecycleReason::borrowed("manual: start requested", "You were started manually.");
pub static MANUAL_STOP: LifecycleReason = LifecycleReason::shutdown_only("manual: stop requested");
pub static START_ALL: LifecycleReason =
    LifecycleReason::borrowed("manual: start-all requested", "You were started manually.");
pub static DESTROY: LifecycleReason = LifecycleReason::shutdown_only("manual: delete requested");

pub static SCHEDULED_BACKUP: LifecycleReason = LifecycleReason::borrowed(
    "backup: scheduled",
    "The system briefly paused you while it created a scheduled backup. No action is required.",
);
pub static MANUAL_BACKUP: LifecycleReason = LifecycleReason::borrowed(
    "backup: manual",
    "The system briefly paused you while it created a manual backup. No action is required.",
);
pub static PRE_RESTORE_BACKUP: LifecycleReason = LifecycleReason::borrowed(
    "backup: pre-restore safety backup",
    "The system briefly paused you while it created a safety backup before a restore. No action is required.",
);
pub static BACKUP_EXPORT: LifecycleReason = LifecycleReason::borrowed(
    "backup: export",
    "The system briefly paused you while it exported a backup. No action is required.",
);
pub static BACKUP_IMPORT: LifecycleReason = LifecycleReason::borrowed(
    "backup: import",
    "You were restored from an exported backup.",
);

pub static RESTORE_SHUTDOWN: LifecycleReason = LifecycleReason::shutdown_only("restore: preparing");
pub static RESTORE_BOOT: LifecycleReason =
    LifecycleReason::borrowed("restore: completed", "You were restored from a backup.");
pub static RESTORE_ABORTED: LifecycleReason = LifecycleReason::borrowed(
    "restore: aborted",
    "The restore did not complete, so you resumed unchanged.",
);

pub static VESTAD_SHUTDOWN: LifecycleReason = LifecycleReason::shutdown_only("system: vestad shutdown");
pub static VESTAD_RESUME: LifecycleReason = LifecycleReason::borrowed(
    "system: vestad restarted",
    "You resumed after the system service restarted.",
);
pub static CONFIG_WRITE_START: LifecycleReason = LifecycleReason::borrowed(
    "system: configuration write",
    "You were started so the system could apply a configuration change.",
);
pub static CODE_UPDATE: LifecycleReason = LifecycleReason::borrowed(
    "update: agent code changed",
    "Your runtime restarted to load updated agent code.",
);
pub static CONTAINER_UPDATE: LifecycleReason = LifecycleReason::borrowed(
    "update: container configuration changed",
    "Your runtime restarted to apply updated container configuration.",
);
pub static DESIRED_STOP: LifecycleReason = LifecycleReason::shutdown_only("system: desired state is stopped");

// Transitions only a client can name: the restart is a separate request from the provider write
// that preceded it, so vestad cannot infer which one happened. The client names it with a token
// and vestad supplies the copy, keeping every word the agent reads authored in this file.
pub static PROVIDER_CONFIGURED: LifecycleReason = LifecycleReason::borrowed(
    "provider: configuration changed",
    "Your provider configuration changed.",
);
pub static PROVIDER_SIGNED_OUT: LifecycleReason =
    LifecycleReason::borrowed("provider: signed out", "Your provider was signed out.");
pub static PROVIDER_MODEL: LifecycleReason = LifecycleReason::borrowed(
    "provider: model changed",
    "Your configured model changed.",
);
pub static PROVIDER_CONTEXT: LifecycleReason = LifecycleReason::borrowed(
    "provider: context window changed",
    "Your configured context window changed.",
);

/// Every token a client may send, with the reason it resolves to. Emitted into
/// `apps/core/fixtures/restart-reason-tokens.json` by the API contract test, so a client cannot
/// drift onto a token this table does not carry.
pub static CLIENT_TOKENS: [(&str, &LifecycleReason); 4] = [
    ("provider.configured", &PROVIDER_CONFIGURED),
    ("provider.signed-out", &PROVIDER_SIGNED_OUT),
    ("provider.model", &PROVIDER_MODEL),
    ("provider.context", &PROVIDER_CONTEXT),
];

/// Resolve a client token. An unknown one yields None rather than invented copy, so a client newer
/// than this vestad degrades to the generic manual reason instead of saying something wrong.
pub fn from_token(token: &str) -> Option<LifecycleReason> {
    CLIENT_TOKENS
        .iter()
        .find(|(name, _)| *name == token)
        .map(|(_, reason)| (*reason).clone())
}

pub fn rename(old_name: &str, new_name: &str) -> LifecycleReason {
    LifecycleReason::owned(
        format!("rename: {old_name} -> {new_name}"),
        format!("Your name changed from {old_name} to {new_name}."),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every reason vestad can hand over. Shutdown-only ones carry no agent copy: the shutdown
    /// inbox writes the log reason alone, so a sentence there would reach nobody.
    const BOOT_FACING: [&LifecycleReason; 18] = [
        &DEFAULT_RESTART,
        &PROVIDER_CONFIGURED,
        &PROVIDER_SIGNED_OUT,
        &PROVIDER_MODEL,
        &PROVIDER_CONTEXT,
        &MANUAL_START,
        &START_ALL,
        &SCHEDULED_BACKUP,
        &MANUAL_BACKUP,
        &PRE_RESTORE_BACKUP,
        &BACKUP_EXPORT,
        &BACKUP_IMPORT,
        &RESTORE_BOOT,
        &RESTORE_ABORTED,
        &VESTAD_RESUME,
        &CONFIG_WRITE_START,
        &CODE_UPDATE,
        &CONTAINER_UPDATE,
    ];
    const SHUTDOWN_ONLY: [&LifecycleReason; 5] = [
        &MANUAL_STOP,
        &DESTROY,
        &RESTORE_SHUTDOWN,
        &VESTAD_SHUTDOWN,
        &DESIRED_STOP,
    ];

    #[test]
    fn every_static_reason_uses_the_category_detail_log_shape() {
        for reason in BOOT_FACING.iter().chain(SHUTDOWN_ONLY.iter()) {
            let (category, detail) = reason
                .log_reason
                .split_once(": ")
                .expect("lifecycle reasons use 'category: detail'");
            assert!(!category.is_empty());
            assert!(!detail.is_empty());
        }
    }

    #[test]
    fn boot_facing_reasons_carry_a_full_sentence_for_the_agent() {
        for reason in BOOT_FACING {
            assert!(reason.agent_message.ends_with('.'), "{}", reason.log_reason);
            assert_ne!(reason.log_reason, reason.agent_message);
        }
    }

    #[test]
    fn shutdown_only_reasons_carry_no_agent_copy() {
        for reason in SHUTDOWN_ONLY {
            assert!(reason.agent_message.is_empty(), "{}", reason.log_reason);
        }
    }

    #[test]
    fn every_client_token_resolves_and_unknown_ones_do_not() {
        for (token, reason) in CLIENT_TOKENS {
            assert_eq!(from_token(token).as_ref(), Some(reason));
        }
        assert!(from_token("provider.nonexistent").is_none());
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
    fn a_request_without_agent_copy_leaves_the_derivation_to_the_agent() {
        let reason = LifecycleReason::from_request("provider: model changed".to_string(), None);
        assert_eq!(reason.log_reason, "provider: model changed");
        assert!(reason.agent_message.is_empty());

        let blank =
            LifecycleReason::from_request("provider: model changed".to_string(), Some("  ".into()));
        assert!(blank.agent_message.is_empty());
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
