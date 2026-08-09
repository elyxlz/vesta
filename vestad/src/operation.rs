//! The gateway's one operation slot: the phase vocabulary every client renders, and the in-memory
//! slot that holds the operation running right now. Holding the slot IS the lock, so a second update
//! and a gateway restart are refused from one place. Sits below `state`, which carries the slot, and
//! below `update`, which drives it.

use std::fmt;

use serde::{Deserialize, Serialize};

/// The release the periodic check last saw, and whether it is ahead of the running gateway.
#[derive(Clone, Debug)]
pub struct UpdateInfo {
    pub latest: String,
    pub update_available: bool,
}

/// The step an update was on. Named separately from `UpdatePhase` so a failure can say what it was
/// doing without carrying that step's payload.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum UpdateStage {
    Resolving,
    Snapshotting,
    Applying,
    Restarting,
}

impl fmt::Display for UpdateStage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let word = match self {
            Self::Resolving => "resolving the release",
            Self::Snapshotting => "backing up",
            Self::Applying => "installing",
            Self::Restarting => "restarting",
        };
        f.write_str(word)
    }
}

/// Where one update is right now. `Snapshotting` carries its own progress so every client can render
/// "backing up axel 2/4"; `agent` is None only for the moment before the first agent is picked.
/// `Failed` is terminal and stays on the operation until the user retries or dismisses it.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum UpdatePhase {
    Snapshotting {
        agent: Option<String>,
        done: u32,
        total: u32,
    },
    Applying,
    Restarting,
    Failed {
        during: UpdateStage,
        error: String,
    },
}

impl UpdatePhase {
    /// The stage this phase is on, for a failure's `during` and for boot recovery.
    pub fn stage(&self) -> UpdateStage {
        match self {
            Self::Snapshotting { .. } => UpdateStage::Snapshotting,
            Self::Applying => UpdateStage::Applying,
            Self::Restarting => UpdateStage::Restarting,
            Self::Failed { during, .. } => *during,
        }
    }
}

/// One update as clients see it. Held in memory only: the ledger is what survives a restart.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActiveUpdate {
    pub target_version: String,
    pub phase: UpdatePhase,
    pub warnings: Vec<String>,
}

/// What the gateway is doing to itself right now. An update walks its own phases; a restart has the
/// one, and the process coming back up is what empties the slot, so a restart records nothing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActiveOperation {
    Update(ActiveUpdate),
    Restart,
}

impl ActiveOperation {
    /// The phase this operation is on: an update's own, and `Restarting` for a restart, which is
    /// what lets every client render a restart on the update screen it already has.
    pub fn phase(&self) -> UpdatePhase {
        match self {
            Self::Update(update) => update.phase.clone(),
            Self::Restart => UpdatePhase::Restarting,
        }
    }
}

/// The single gateway operation slot. Holding it IS the lock: a second update, and a gateway
/// restart, are refused while a live operation sits here, and the claim is what takes it, so there
/// is no window between deciding and acting. A terminal (failed) operation keeps projecting so the
/// user sees the failure, but yields the slot to a retry.
pub struct OperationSlot {
    active: std::sync::Mutex<Option<ActiveOperation>>,
    changes: tokio::sync::watch::Sender<u64>,
}

impl Default for OperationSlot {
    fn default() -> Self {
        Self::new()
    }
}

impl OperationSlot {
    pub fn new() -> Self {
        let (changes, _keep_open) = tokio::sync::watch::channel(0);
        Self {
            active: std::sync::Mutex::new(None),
            changes,
        }
    }

    /// What every `/sync` session projects.
    pub fn snapshot(&self) -> Option<ActiveOperation> {
        self.lock().clone()
    }

    /// The phase of a live operation, or None when the gateway is idle or the operation is
    /// terminal. What the dismiss handler consults: a failure keeps projecting but never blocks.
    pub fn running_phase(&self) -> Option<UpdatePhase> {
        match self.lock().as_ref() {
            Some(running) if !matches!(running.phase(), UpdatePhase::Failed { .. }) => {
                Some(running.phase())
            }
            _ => None,
        }
    }

    /// Wake on every phase transition, so a client sees "backing up axel 2/4" as it happens.
    pub fn subscribe(&self) -> tokio::sync::watch::Receiver<u64> {
        self.changes.subscribe()
    }

    /// Take the slot, or hand back the live phase already holding it. Every operation starts here,
    /// so an update and a restart asked for at the same moment cannot both proceed.
    pub(crate) fn claim(&self, operation: ActiveOperation) -> Result<(), UpdatePhase> {
        let mut active = self.lock();
        if let Some(running) = active.as_ref() {
            let phase = running.phase();
            if !matches!(phase, UpdatePhase::Failed { .. }) {
                return Err(phase);
            }
        }
        *active = Some(operation);
        drop(active);
        self.bump();
        Ok(())
    }

    /// Move the update holding the slot to `phase` and report the warnings collected so far, which
    /// the caller writes into the ledger alongside it.
    pub(crate) fn set_phase(&self, phase: UpdatePhase) -> Vec<String> {
        let mut active = self.lock();
        let warnings = match active.as_mut() {
            Some(ActiveOperation::Update(update)) => {
                update.phase = phase;
                update.warnings.clone()
            }
            _ => Vec::new(),
        };
        drop(active);
        self.bump();
        warnings
    }

    pub(crate) fn warn(&self, warning: String) {
        tracing::warn!(%warning, "gateway update warning");
        let mut active = self.lock();
        if let Some(ActiveOperation::Update(update)) = active.as_mut() {
            update.warnings.push(warning);
        }
        drop(active);
        self.bump();
    }

    pub fn clear(&self) {
        *self.lock() = None;
        self.bump();
    }

    /// Project the failure a previous vestad never got to report (see `recover_at_boot`), so the
    /// user meets an explicit "update failed" with a retry instead of silence.
    pub fn set_interrupted(&self, target_version: String, during: UpdateStage) {
        *self.lock() = Some(ActiveOperation::Update(ActiveUpdate {
            target_version,
            phase: UpdatePhase::Failed {
                during,
                error: "the update stopped before it finished".into(),
            },
            warnings: Vec::new(),
        }));
        self.bump();
    }

    /// Drop a failure the user has acknowledged. False when there is nothing terminal to dismiss;
    /// a running operation is untouched.
    pub fn dismiss(&self) -> bool {
        let mut active = self.lock();
        if !matches!(
            active.as_ref().map(ActiveOperation::phase),
            Some(UpdatePhase::Failed { .. })
        ) {
            return false;
        }
        *active = None;
        drop(active);
        self.bump();
        true
    }

    /// Resolve once the operation is over: cleared (the process is about to be replaced, or there
    /// was nothing to do) or terminal. The auto-update path awaits this so one maintenance cycle
    /// never overlaps the next.
    pub async fn wait_until_settled(&self) {
        let mut changes = self.subscribe();
        loop {
            match self.snapshot() {
                None => return,
                Some(running) if matches!(running.phase(), UpdatePhase::Failed { .. }) => return,
                Some(_) => {}
            }
            if changes.changed().await.is_err() {
                return;
            }
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Option<ActiveOperation>> {
        self.active
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn bump(&self) {
        self.changes.send_modify(|version| *version = version.wrapping_add(1));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn claiming_update(target_version: &str) -> ActiveOperation {
        ActiveOperation::Update(ActiveUpdate {
            target_version: target_version.to_string(),
            phase: UpdatePhase::Snapshotting { agent: None, done: 0, total: 0 },
            warnings: Vec::new(),
        })
    }

    #[test]
    fn a_live_operation_holds_the_slot_and_a_failed_one_yields_it() {
        let slot = OperationSlot::new();
        assert_eq!(slot.snapshot(), None);

        slot.claim(claiming_update("0.1.190")).expect("the first claim takes the free slot");
        let live = UpdatePhase::Snapshotting { agent: None, done: 0, total: 0 };
        assert_eq!(slot.claim(claiming_update("0.1.190")), Err(live.clone()));
        assert_eq!(slot.running_phase(), Some(live));

        // A failure the user has not dismissed still projects, but a retry replaces it and the
        // restart/update guards read it as no longer running.
        slot.set_phase(UpdatePhase::Failed {
            during: UpdateStage::Applying,
            error: "curl failed".into(),
        });
        assert_eq!(slot.running_phase(), None);
        assert!(slot.claim(claiming_update("0.1.191")).is_ok());
        assert_eq!(
            slot.snapshot(),
            Some(claiming_update("0.1.191")),
        );

        slot.clear();
        assert_eq!(slot.snapshot(), None);
    }

    #[test]
    fn an_update_and_a_restart_compete_for_the_one_slot() {
        let slot = OperationSlot::new();
        slot.claim(ActiveOperation::Restart).expect("a free slot takes the restart");
        // A restart reports the phase every client already renders, so the update it refuses says
        // exactly what is running.
        assert_eq!(slot.running_phase(), Some(UpdatePhase::Restarting));
        assert_eq!(
            slot.claim(claiming_update("0.1.190")),
            Err(UpdatePhase::Restarting),
            "an update never starts while a restart holds the slot"
        );

        slot.clear();
        slot.claim(claiming_update("0.1.190")).expect("claim");
        assert_eq!(
            slot.claim(ActiveOperation::Restart),
            Err(UpdatePhase::Snapshotting { agent: None, done: 0, total: 0 }),
            "the restart that once killed a backup mid-export is refused instead"
        );
        // A restart carries no phases and no warnings of its own to move.
        assert!(slot.set_phase(UpdatePhase::Applying).is_empty());
    }

    #[test]
    fn dismiss_clears_only_a_terminal_operation() {
        let slot = OperationSlot::new();
        assert!(!slot.dismiss(), "nothing to dismiss when idle");

        slot.claim(claiming_update("0.1.190")).expect("claim");
        assert!(!slot.dismiss(), "a running update is not dismissable");
        assert!(slot.snapshot().is_some());

        slot.set_phase(UpdatePhase::Failed {
            during: UpdateStage::Snapshotting,
            error: "boom".into(),
        });
        assert!(slot.dismiss());
        assert_eq!(slot.snapshot(), None);
    }

    #[test]
    fn a_recovered_interruption_projects_as_a_failure() {
        let slot = OperationSlot::new();
        slot.set_interrupted("0.1.190".into(), UpdateStage::Snapshotting);
        let ActiveOperation::Update(active) = slot.snapshot().expect("the interruption projects")
        else {
            panic!("a recovered interruption is an update");
        };
        assert_eq!(active.target_version, "0.1.190");
        assert!(matches!(
            active.phase,
            UpdatePhase::Failed { during: UpdateStage::Snapshotting, .. }
        ));
        assert!(slot.dismiss(), "the user can dismiss a recovered failure");
    }
}
