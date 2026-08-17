use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::device_registry::{DeviceContext, DeviceInfo};
use crate::docker::{AgentOperation, AgentStatus, BuildPhase};
use crate::types::ClientKind;

/// The gateway (host) branch of the state tree. camelCase on the wire to match
/// `apps/core/src/protocol/tree.ts` `GatewayInfo`.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct GatewayInfo {
    pub version: String,
    pub channel: String,
    pub auto_update: bool,
    pub port: u16,
    pub lan: GatewayLan,
    pub tunnel_url: Option<String>,
    pub update_available: bool,
    pub latest_version: Option<String>,
    pub managed: bool,
    /// The gateway-wide operation in flight, or None when the gateway is idle. Mirrors the agent
    /// nodes' `operation`: work that outlives the request that started it, so every client sees it
    /// rather than only the one that asked. Defaulted so a tree written by an older gateway (before
    /// the field existed) still parses.
    #[serde(default)]
    pub operation: Option<GatewayOperation>,
}

/// The kinds of gateway operation there are. An enum rather than a bare string so a third kind
/// cannot be added without every reader being told about it.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum GatewayOperationKind {
    Update,
    Restart,
}

/// The wire face of an operation's phase. Terminal success is deliberately absent: a finished
/// operation clears the slot, and the client reads the new version off the gateway node itself.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum GatewayOperationPhase {
    Snapshotting,
    Applying,
    Restarting,
    Failed,
}

/// One in-flight gateway operation, flattened for the wire: the progress fields carry values only
/// while snapshotting, `error` only on a failure, and `targetVersion` only for an update, a restart
/// having no release to name.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct GatewayOperation {
    pub kind: GatewayOperationKind,
    pub phase: GatewayOperationPhase,
    pub agent: Option<String>,
    pub done: Option<u32>,
    pub total: Option<u32>,
    pub target_version: Option<String>,
    pub warnings: Vec<String>,
    pub error: Option<String>,
}

impl From<crate::operation::ActiveOperation> for GatewayOperation {
    fn from(active: crate::operation::ActiveOperation) -> Self {
        use crate::operation::{ActiveOperation, UpdatePhase};
        // A restart is one phase with nothing to report, and it is deliberately the phase an update
        // ends on, so every client renders it on the screen it already has.
        let update = match active {
            ActiveOperation::Restart => {
                return Self {
                    kind: GatewayOperationKind::Restart,
                    phase: GatewayOperationPhase::Restarting,
                    agent: None,
                    done: None,
                    total: None,
                    target_version: None,
                    warnings: Vec::new(),
                    error: None,
                }
            }
            ActiveOperation::Update(update) => update,
        };
        let (phase, agent, done, total, error) = match update.phase {
            UpdatePhase::Snapshotting { agent, done, total } => (
                GatewayOperationPhase::Snapshotting,
                agent,
                Some(done),
                Some(total),
                None,
            ),
            UpdatePhase::Applying => (GatewayOperationPhase::Applying, None, None, None, None),
            UpdatePhase::Restarting => (GatewayOperationPhase::Restarting, None, None, None, None),
            UpdatePhase::Failed { during, error } => (
                GatewayOperationPhase::Failed,
                None,
                None,
                None,
                Some(format!("while {during}: {error}")),
            ),
        };
        Self {
            kind: GatewayOperationKind::Update,
            phase,
            agent,
            done,
            total,
            target_version: Some(update.target_version),
            warnings: update.warnings,
            error,
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub(crate) struct GatewayLan {
    pub exposed: bool,
    pub url: Option<String>,
}

/// One registered agent-hosted service (dashboard, voice, ...). Mirrors `ServiceInfo`.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub(crate) struct ServiceInfo {
    pub port: u16,
    pub rev: u64,
}

/// The per-agent `info` branch. camelCase to match `AgentInfo`. `activity_state` is a plain string
/// ("idle"/"thinking") sourced from the activity cache; the TS union narrows it.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AgentInfo {
    pub status: AgentStatus,
    pub activity_state: String,
    pub build_phase: Option<BuildPhase>,
    pub operation: Option<AgentOperation>,
    /// An `Alive` agent still working through its boot turns; clients label it as waking up.
    #[serde(default)]
    pub booting: bool,
    pub started_at: Option<String>,
    pub services: BTreeMap<String, ServiceInfo>,
}

/// The per-agent node: info + the always-on pending-notifications branch. `pending` events are
/// relayed verbatim from the agent's Python (opaque JSON), so they carry whatever fields the agent
/// emitted plus their id.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub(crate) struct AgentNode {
    pub info: AgentInfo,
    pub notifications: NotificationsBranch,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Default)]
pub(crate) struct NotificationsBranch {
    pub pending: Vec<serde_json::Value>,
}

/// The full state tree sent on the connect snapshot: roster + pending sets, no tails.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub(crate) struct Tree {
    pub gateway: GatewayInfo,
    pub agents: BTreeMap<String, AgentNode>,
    #[serde(default)]
    pub devices: Vec<DeviceInfo>,
}

/// The `state` delta's scope: the gateway branch is the only one, replaced whole.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum GatewayScope {
    Gateway,
}

/// Every server -> client frame in one tagged union, matching the flat `type` routing in
/// `apps/core/src/protocol/parse.ts`. hello/snapshot plus the delta types share one wire
/// discriminator space; on one ordered TCP socket there are no sequence numbers.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub(crate) enum Frame {
    Hello { version: String, min_supported: String },
    Snapshot { tree: Tree },
    State { scope: GatewayScope, value: GatewayInfo },
    Agent { name: String, info: AgentInfo },
    AgentRemoved { name: String },
    Notifications { agent: String, pending: Vec<serde_json::Value> },
    UserNotification { agent: String, kind: String, title: String, body: String },
    Presence { any_focused: bool },
    Devices { devices: Vec<DeviceInfo> },
}

impl Frame {
    /// Serialize to a wire string. Serialization of these owned DTOs does not fail in practice, but
    /// the fallible API is honored so no `unwrap` rides the send path: a serialize error is logged
    /// and the frame dropped by the caller.
    pub fn encode(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }
}

/// Client -> server frames. Anything that fails to parse as one of these is ignored by the handler.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub(crate) enum ClientFrame {
    Reauth { token: String },
    ClientContext(ClientContext),
}

/// A client's reported context, sent up the `/sync` socket. `focused` is global Vesta-app presence:
/// web visibility/window focus or mobile foreground state. `client` identifies the surface that
/// caused a return. `resync` is true when the socket replays its cached context on reconnect, so a
/// reconnect never looks like the user returning. `viewing` is the agent whose page is open on this
/// client, or `None` on the roster, a non-agent screen, or a blurred window: it drives the per-agent
/// presence notification, independently of `focused`.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ClientContext {
    pub focused: bool,
    #[serde(default)]
    pub client: ClientKind,
    #[serde(default)]
    pub resync: bool,
    #[serde(default)]
    pub viewing: Option<String>,
    /// The client-minted installation id identifying the device across reconnects. Absent from
    /// older clients, which are simply not tracked in the device registry.
    #[serde(default)]
    pub device_id: Option<String>,
    /// A human label the client composes for itself, e.g. "Chrome on macOS".
    #[serde(default)]
    pub descriptor: Option<String>,
    /// What the device reports about itself (`timezone`, `position`), read when the frame is built
    /// so a change after mount is reported on the next focus edge or reconnect. The same shape the
    /// registry stores and `PUT /devices/{id}/context` takes.
    #[serde(flatten)]
    pub context: DeviceContext,
}

/// Build one representative of every `/sync` frame through the real serde path, for the contract
/// fixture the `@vesta/core` test parses. Test-only.
#[cfg(test)]
pub(crate) fn protocol_fixtures() -> serde_json::Value {
    use serde_json::to_value;

    let gateway = GatewayInfo {
        version: "0.1.0".into(),
        channel: "stable".into(),
        auto_update: true,
        port: 4111,
        lan: GatewayLan { exposed: false, url: None },
        tunnel_url: Some("https://sample.vesta.run".into()),
        update_available: true,
        latest_version: Some("0.1.1".into()),
        managed: false,
        operation: Some(GatewayOperation {
            kind: GatewayOperationKind::Update,
            phase: GatewayOperationPhase::Snapshotting,
            agent: Some("sample-agent".into()),
            done: Some(1),
            total: Some(2),
            target_version: Some("0.1.1".into()),
            warnings: vec!["other-agent: backup failed (disk full)".into()],
            error: None,
        }),
    };
    let mut services = BTreeMap::new();
    services.insert("dashboard".to_string(), ServiceInfo { port: 8080, rev: 3 });
    let info = AgentInfo {
        status: AgentStatus::Alive,
        activity_state: "thinking".into(),
        build_phase: None,
        operation: Some(AgentOperation::BackingUp),
        booting: false,
        started_at: Some("2026-01-01T00:00:00Z".into()),
        services,
    };
    let notification = serde_json::json!({
        "id": 7, "type": "notification", "source": "whatsapp", "summary": "new message",
        "notif_id": "whatsapp-123",
    });
    let mut agents = BTreeMap::new();
    agents.insert(
        "sample-agent".to_string(),
        AgentNode { info: info.clone(), notifications: NotificationsBranch { pending: vec![notification.clone()] } },
    );
    let devices = vec![DeviceInfo {
        id: "device-1".into(),
        kind: ClientKind::Desktop,
        descriptor: Some("Vesta Desktop on macOS".into()),
        present: true,
        last_seen: "2026-01-01T00:00:00Z".into(),
        push_enabled: false,
        location: Some("London, United Kingdom".into()),
        timezone: Some("Europe/London".into()),
        position: Some(crate::device_registry::DevicePosition {
            latitude: 51.5074,
            longitude: -0.1278,
            accuracy_m: Some(50.0),
            place: Some(crate::device_registry::DevicePlace {
                city: Some("London".into()),
                region: Some("England".into()),
                country: Some("United Kingdom".into()),
            }),
        }),
        position_at: Some("2026-01-01T00:00:00Z".into()),
    }];
    let tree = Tree { gateway: gateway.clone(), agents, devices: devices.clone() };

    serde_json::json!({
        "hello": to_value(Frame::Hello {
            version: "0.1.0".into(),
            min_supported: super::MIN_SUPPORTED_CLIENT_VERSION.into(),
        }).expect("serialize hello"),
        "snapshot": to_value(Frame::Snapshot { tree }).expect("serialize snapshot"),
        "deltas": {
            "state": to_value(Frame::State { scope: GatewayScope::Gateway, value: gateway }).expect("serialize state"),
            "agent": to_value(Frame::Agent { name: "sample-agent".into(), info }).expect("serialize agent"),
            "agent_removed": to_value(Frame::AgentRemoved { name: "stopped-agent".into() }).expect("serialize agent_removed"),
            "notifications": to_value(Frame::Notifications { agent: "sample-agent".into(), pending: vec![notification] }).expect("serialize notifications"),
            "user_notification": to_value(Frame::UserNotification {
                agent: "sample-agent".into(), kind: "message".into(), title: "sample-agent".into(), body: "hello".into(),
            }).expect("serialize user_notification"),
            "presence": to_value(Frame::Presence { any_focused: true }).expect("serialize presence"),
            "devices": to_value(Frame::Devices { devices }).expect("serialize devices"),
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_gateway() -> GatewayInfo {
        GatewayInfo {
            version: "0.1.0".into(),
            channel: "stable".into(),
            auto_update: true,
            port: 4111,
            lan: GatewayLan { exposed: false, url: None },
            tunnel_url: None,
            update_available: false,
            latest_version: None,
            managed: false,
            operation: None,
        }
    }

    #[test]
    fn gateway_info_serializes_camelcase_like_the_ts_tree() {
        let value = serde_json::to_value(sample_gateway()).expect("serialize");
        // camelCase field names must match apps/core/src/protocol/tree.ts GatewayInfo.
        assert!(value.get("autoUpdate").is_some());
        assert!(value.get("tunnelUrl").is_some());
        assert!(value.get("updateAvailable").is_some());
        assert!(value.get("latestVersion").is_some());
        assert!(value.get("auto_update").is_none());
    }

    #[test]
    fn a_running_update_projects_its_phase_and_progress() {
        let active = crate::operation::ActiveOperation::Update(crate::operation::ActiveUpdate {
            target_version: "0.1.190".into(),
            phase: crate::operation::UpdatePhase::Snapshotting {
                agent: Some("axel".into()),
                done: 1,
                total: 4,
            },
            warnings: vec!["mona: backup failed (disk full)".into()],
        });
        let value = serde_json::to_value(GatewayOperation::from(active)).expect("serialize");
        assert_eq!(value["kind"], serde_json::json!("update"));
        assert_eq!(value["phase"], serde_json::json!("snapshotting"));
        assert_eq!(value["agent"], serde_json::json!("axel"));
        assert_eq!(value["done"], serde_json::json!(1));
        assert_eq!(value["total"], serde_json::json!(4));
        assert_eq!(value["targetVersion"], serde_json::json!("0.1.190"));
        assert_eq!(value["warnings"][0], serde_json::json!("mona: backup failed (disk full)"));
        assert_eq!(value["error"], serde_json::Value::Null);
    }

    #[test]
    fn a_failed_update_projects_the_stage_it_died_on() {
        let active = crate::operation::ActiveOperation::Update(crate::operation::ActiveUpdate {
            target_version: "0.1.190".into(),
            phase: crate::operation::UpdatePhase::Failed {
                during: crate::operation::UpdateStage::Applying,
                error: "curl failed".into(),
            },
            warnings: Vec::new(),
        });
        let operation = GatewayOperation::from(active);
        assert_eq!(operation.phase, GatewayOperationPhase::Failed);
        assert_eq!(operation.error.as_deref(), Some("while installing: curl failed"));
        assert_eq!(operation.agent, None);
    }

    #[test]
    fn a_restart_projects_as_the_restarting_phase_with_nothing_to_report() {
        let value = serde_json::to_value(GatewayOperation::from(
            crate::operation::ActiveOperation::Restart,
        ))
        .expect("serialize");
        assert_eq!(value["kind"], serde_json::json!("restart"));
        assert_eq!(value["phase"], serde_json::json!("restarting"));
        // A restart installs nothing, so it names no release and carries no progress.
        assert_eq!(value["targetVersion"], serde_json::Value::Null);
        assert_eq!(value["agent"], serde_json::Value::Null);
        assert_eq!(value["warnings"], serde_json::json!([]));
    }

    #[test]
    fn an_idle_gateway_carries_a_null_operation() {
        let value = serde_json::to_value(sample_gateway()).expect("serialize");
        assert_eq!(value["operation"], serde_json::Value::Null);

        // A gateway node from an older vestad has no `operation` key at all; parsing must not need one.
        let mut older = value.clone();
        let object = older.as_object_mut().expect("gateway object");
        object.remove("operation");
        let parsed: GatewayInfo = serde_json::from_value(older).expect("parse a gateway without the field");
        assert_eq!(parsed.operation, None);
    }

    #[test]
    fn agent_info_serializes_camelcase() {
        let info = AgentInfo {
            status: crate::docker::AgentStatus::Alive,
            activity_state: "idle".into(),
            build_phase: None,
            operation: None,
            booting: false,
            started_at: Some("2026-07-18T00:00:00Z".into()),
            services: std::collections::BTreeMap::new(),
        };
        let value = serde_json::to_value(info).expect("serialize");
        assert_eq!(value["status"], serde_json::json!("alive"));
        assert!(value.get("activityState").is_some());
        assert!(value.get("buildPhase").is_some());
        assert!(value.get("operation").is_some());
        assert!(value.get("startedAt").is_some());
    }

    fn sample_agent_info() -> AgentInfo {
        AgentInfo {
            status: crate::docker::AgentStatus::Alive,
            activity_state: "idle".into(),
            build_phase: None,
            operation: None,
            booting: false,
            started_at: None,
            services: BTreeMap::new(),
        }
    }

    #[test]
    fn every_frame_variant_uses_its_wire_tag() {
        let cases = [
            (Frame::Hello { version: "0.1.0".into(), min_supported: "0.0.0".into() }, "hello"),
            (Frame::Snapshot { tree: Tree { gateway: sample_gateway(), agents: Default::default(), devices: Default::default() } }, "snapshot"),
            (Frame::State { scope: GatewayScope::Gateway, value: sample_gateway() }, "state"),
            (Frame::Agent { name: "scout".into(), info: sample_agent_info() }, "agent"),
            (Frame::AgentRemoved { name: "scout".into() }, "agent_removed"),
            (Frame::Notifications { agent: "scout".into(), pending: vec![] }, "notifications"),
            (Frame::UserNotification { agent: "scout".into(), kind: "message".into(), title: "scout".into(), body: "hi".into() }, "user_notification"),
            (Frame::Presence { any_focused: true }, "presence"),
        ];
        for (frame, tag) in cases {
            let value = serde_json::to_value(&frame).expect("serialize frame");
            assert_eq!(value["type"], serde_json::json!(tag));
        }
    }

    #[test]
    fn state_delta_scope_is_gateway() {
        let value = serde_json::to_value(Frame::State {
            scope: GatewayScope::Gateway,
            value: sample_gateway(),
        })
        .expect("serialize");
        assert_eq!(value["scope"], serde_json::json!("gateway"));
    }

    #[test]
    fn client_frames_round_trip() {
        let reauth: ClientFrame = serde_json::from_str(r#"{"type":"reauth","token":"tok"}"#).expect("parse reauth");
        assert_eq!(reauth, ClientFrame::Reauth { token: "tok".into() });
        // An unknown client frame is a parse error the handler treats as "ignore".
        assert!(serde_json::from_str::<ClientFrame>(r#"{"type":"future"}"#).is_err());
    }

    #[test]
    fn client_context_frame_round_trips() {
        // resync defaults to false when the field is absent (older clients, additive-safe).
        let parsed: ClientFrame = serde_json::from_str(
            r#"{"type":"client_context","focused":true,"client":"desktop"}"#,
        )
        .expect("parse client_context");
        assert_eq!(
            parsed,
            ClientFrame::ClientContext(ClientContext {
                focused: true,
                client: ClientKind::Desktop,
                resync: false,
                ..Default::default()
            })
        );
        // A shipped client still sends the retired `active_agent`; unknown fields are ignored by
        // rule, which is what keeps this removal off `MIN_SUPPORTED_CLIENT_VERSION`.
        let legacy: ClientFrame =
            serde_json::from_str(r#"{"type":"client_context","focused":true,"active_agent":"scout"}"#)
                .expect("parse legacy client_context");
        assert_eq!(
            legacy,
            ClientFrame::ClientContext(ClientContext {
                focused: true,
                client: ClientKind::Unknown,
                resync: false,
                ..Default::default()
            })
        );
        let resync: ClientFrame = serde_json::from_str(
            r#"{"type":"client_context","focused":false,"resync":true}"#,
        )
        .expect("parse client_context resync");
        assert_eq!(
            resync,
            ClientFrame::ClientContext(ClientContext {
                focused: false,
                client: ClientKind::Unknown,
                resync: true,
                ..Default::default()
            })
        );
        // `timezone` and `position` are the device's reported context, camelCase like the rest.
        let context: ClientFrame = serde_json::from_str(
            r#"{"type":"client_context","focused":true,"client":"mobile","timezone":"Asia/Tokyo",
                "position":{"latitude":35.6762,"longitude":139.6503,"accuracyM":50.0,"place":{"city":"Tokyo","country":"Japan"}}}"#,
        )
        .expect("parse client_context with context");
        assert_eq!(
            context,
            ClientFrame::ClientContext(ClientContext {
                focused: true,
                client: ClientKind::Mobile,
                context: DeviceContext {
                    timezone: Some("Asia/Tokyo".into()),
                    position: Some(crate::device_registry::PositionReport::At(crate::device_registry::DevicePosition {
                        latitude: 35.6762,
                        longitude: 139.6503,
                        accuracy_m: Some(50.0),
                        place: Some(crate::device_registry::DevicePlace {
                            city: Some("Tokyo".into()),
                            region: None,
                            country: Some("Japan".into()),
                        }),
                    })),
                },
                ..Default::default()
            })
        );
        // A `position: null` is a retraction (location sharing turned off), distinct from absent.
        let retracted: ClientFrame = serde_json::from_str(
            r#"{"type":"client_context","focused":true,"client":"mobile","timezone":"Asia/Tokyo","position":null}"#,
        )
        .expect("parse client_context retracting the position");
        let ClientFrame::ClientContext(retracted) = retracted else { panic!("client_context expected") };
        assert_eq!(retracted.context.position, Some(crate::device_registry::PositionReport::Retract));
        // `viewing` carries the open agent's name; absent it defaults to None (additive-safe).
        let viewing: ClientFrame = serde_json::from_str(
            r#"{"type":"client_context","focused":true,"client":"web","viewing":"scout"}"#,
        )
        .expect("parse client_context viewing");
        assert_eq!(
            viewing,
            ClientFrame::ClientContext(ClientContext {
                focused: true,
                client: ClientKind::Web,
                resync: false,
                viewing: Some("scout".into()),
                ..Default::default()
            })
        );
    }

    #[test]
    fn client_kinds_have_user_facing_app_names() {
        assert_eq!(ClientKind::Web.display_name(), "Vesta Web App");
        assert_eq!(ClientKind::Mobile.display_name(), "Vesta Mobile App");
        assert_eq!(ClientKind::Desktop.display_name(), "Vesta Desktop App");
        assert_eq!(ClientKind::Unknown.display_name(), "Vesta App");
    }

    #[test]
    fn presence_frame_uses_its_wire_tag() {
        let value = serde_json::to_value(Frame::Presence { any_focused: true }).expect("serialize presence");
        assert_eq!(value["type"], serde_json::json!("presence"));
        assert_eq!(value["any_focused"], serde_json::json!(true));
    }
}
