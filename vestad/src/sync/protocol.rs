use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::docker::{AgentStatus, BuildPhase};

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
}

/// The `state` delta's scope; always `gateway` in protocol 1 (a whole-branch replace).
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
    Hello { version: String, protocol: u32, floor: u32 },
    Snapshot { tree: Tree },
    State { scope: GatewayScope, value: GatewayInfo },
    Agent { name: String, info: AgentInfo },
    AgentRemoved { name: String },
    Notifications { agent: String, pending: Vec<serde_json::Value> },
    UserNotification { agent: String, kind: String, title: String, body: String },
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
    };
    let mut services = BTreeMap::new();
    services.insert("dashboard".to_string(), ServiceInfo { port: 8080, rev: 3 });
    let info = AgentInfo {
        status: AgentStatus::Alive,
        activity_state: "thinking".into(),
        build_phase: None,
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
    let tree = Tree { gateway: gateway.clone(), agents };

    serde_json::json!({
        "hello": to_value(Frame::Hello {
            version: "0.1.0".into(),
            protocol: super::PROTOCOL_VERSION,
            floor: super::PROTOCOL_FLOOR,
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
    fn agent_info_serializes_camelcase() {
        let info = AgentInfo {
            status: crate::docker::AgentStatus::Alive,
            activity_state: "idle".into(),
            build_phase: None,
            started_at: Some("2026-07-18T00:00:00Z".into()),
            services: std::collections::BTreeMap::new(),
        };
        let value = serde_json::to_value(info).expect("serialize");
        assert_eq!(value["status"], serde_json::json!("alive"));
        assert!(value.get("activityState").is_some());
        assert!(value.get("buildPhase").is_some());
        assert!(value.get("startedAt").is_some());
    }

    fn sample_agent_info() -> AgentInfo {
        AgentInfo {
            status: crate::docker::AgentStatus::Alive,
            activity_state: "idle".into(),
            build_phase: None,
            started_at: None,
            services: BTreeMap::new(),
        }
    }

    #[test]
    fn every_frame_variant_uses_its_wire_tag() {
        let cases = [
            (Frame::Hello { version: "0.1.0".into(), protocol: 1, floor: 1 }, "hello"),
            (Frame::Snapshot { tree: Tree { gateway: sample_gateway(), agents: Default::default() } }, "snapshot"),
            (Frame::State { scope: GatewayScope::Gateway, value: sample_gateway() }, "state"),
            (Frame::Agent { name: "scout".into(), info: sample_agent_info() }, "agent"),
            (Frame::AgentRemoved { name: "scout".into() }, "agent_removed"),
            (Frame::Notifications { agent: "scout".into(), pending: vec![] }, "notifications"),
            (Frame::UserNotification { agent: "scout".into(), kind: "message".into(), title: "scout".into(), body: "hi".into() }, "user_notification"),
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
}
