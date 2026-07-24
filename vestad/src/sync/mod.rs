//! The client protocol's server side: the aggregator's shared fan-out state (`SyncHub`) and the
//! `/sync` WebSocket handler. This module owns vestad's Rust side of the wire protocol, mirroring
//! `apps/core/src/protocol` and contract-tested at the fixture seam. It is additive beside the
//! legacy control WS in this stage; the old surface is retired later in the epic.

pub(crate) mod events;
mod handler;
pub(crate) mod hub;
pub(crate) mod protocol;

/// The oldest client release this gateway still accepts, serialized into the `/sync` hello as
/// `min_supported` (the window's low end; the high end is the gateway's own `CARGO_PKG_VERSION`).
/// A client older than this hits the terminal `app_behind` screen in `@vesta/core`. "0.0.0" accepts
/// every client ever built; the first wire break bumps it (see release.sh's guard and the Client
/// compatibility contract in CLAUDE.md). Additive changes never move it, thanks to the
/// ignore-unknown-frames rule.
pub(crate) const MIN_SUPPORTED_CLIENT_VERSION: &str = "0.0.0";

pub(crate) use events::{activity_state, notification_change};
pub(crate) use protocol::ModelAccess;
pub(crate) use handler::sync_ws_handler;
pub(crate) use hub::SyncHub;
