//! The client protocol's server side: the aggregator's shared fan-out state (`SyncHub`) and the
//! `/sync` WebSocket handler. This module owns vestad's Rust side of the wire protocol, mirroring
//! `apps/core/src/protocol` and contract-tested at the fixture seam. It is additive beside the
//! legacy control WS in this stage; the old surface is retired later in the epic.

pub(crate) mod events;
mod hub;
pub(crate) mod protocol;

/// The protocol version vestad speaks and the minimum it still accepts. Mirrors
/// `apps/core/src/protocol/version.ts` (PROTOCOL_VERSION / PROTOCOL_FLOOR); the contract fixture
/// pins them equal on both seams.
pub(crate) const PROTOCOL_VERSION: u32 = 1;
pub(crate) const PROTOCOL_FLOOR: u32 = 1;

pub(crate) use events::{NotificationChange, PendingNotifications, activity_state, notification_change};
pub(crate) use hub::{LiveMessage, SyncHub, TapUnavailable};
