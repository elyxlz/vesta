//! Which agents to tell about the user's device context, and once per change. An agent hears about
//! a device zone that is neither its own zone nor the last zone it was told, and about a device
//! position whose macro place differs from the last place it was told (or that moved far enough
//! with no place to compare). One memory per agent, nothing per device: two devices arriving in the
//! same zone are one fact, and the agent's own zone is read live on every report, so it decides
//! what to do and is nudged again only when something changes. The registry stores the facts; this
//! module only decides who hears about a change, over in-memory state, so a vestad restart re-tells
//! at most once.

use std::collections::{BTreeMap, HashMap};
use std::sync::Mutex;

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::Json;

use crate::device_registry::{DeviceContext, DevicePlace, DevicePosition, PositionReport};
use crate::state::{err_response, ok_json, SharedState};

/// With no macro place to compare, a position must move at least this far from the last told
/// point before an agent hears about it again.
const LOCATION_NOTIFY_MIN_KM: f64 = 25.0;

const EARTH_RADIUS_KM: f64 = 6371.0;

/// What one agent was last told: the device zone, and the place (or point) of the last position.
#[derive(Debug, Default)]
struct Told {
    zone: Option<String>,
    place: Option<String>,
    point: Option<(f64, f64)>,
}

/// One agent to notify that a device is in `device_zone` while the agent runs on `agent_zone`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TimezoneChange {
    pub agent: String,
    pub agent_zone: String,
}

#[derive(Debug, Default)]
pub(crate) struct UserContext {
    told: Mutex<HashMap<String, Told>>,
}

/// The serving agents, each with its own IANA zone, in name order.
pub(crate) type AgentZones = BTreeMap<String, String>;

impl UserContext {
    /// The agents to tell that a device reports `device_zone`: those whose own zone is not it and who
    /// were not last told it. The ones returned are marked told.
    pub(crate) fn timezone_changes(&self, device_zone: &str, agent_zones: &AgentZones) -> Vec<TimezoneChange> {
        let mut told = self.told.lock().expect("user context mutex");
        agent_zones
            .iter()
            .filter_map(|(agent, agent_zone)| {
                let entry = told.entry(agent.clone()).or_default();
                if agent_zone == device_zone || entry.zone.as_deref() == Some(device_zone) {
                    return None;
                }
                entry.zone = Some(device_zone.to_string());
                Some(TimezoneChange { agent: agent.clone(), agent_zone: agent_zone.clone() })
            })
            .collect()
    }

    /// The agents to tell that a device is at `position`: the macro place differs from the last one
    /// told, or, when either side has no place, the point moved at least `LOCATION_NOTIFY_MIN_KM`
    /// from the last told point. The ones returned are marked told.
    pub(crate) fn location_changes(&self, position: &DevicePosition, agent_zones: &AgentZones) -> Vec<String> {
        let mut told = self.told.lock().expect("user context mutex");
        let place = position.place.as_ref().and_then(DevicePlace::macro_label);
        let point = (position.latitude, position.longitude);
        agent_zones
            .keys()
            .filter(|agent| {
                let entry = told.entry((*agent).clone()).or_default();
                let moved = match (&place, &entry.place, entry.point) {
                    (Some(now), Some(before), _) => now != before,
                    (_, _, Some(before)) => distance_km(point, before) >= LOCATION_NOTIFY_MIN_KM,
                    (_, _, None) => true,
                };
                if moved {
                    entry.place.clone_from(&place);
                    entry.point = Some(point);
                }
                moved
            })
            .cloned()
            .collect()
    }
}

/// Whether a report places the user at the reporting device. A focused, fresh socket frame or a
/// background poll from a phone does; an unfocused frame or a resync replay stores its zone but
/// tells no one.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum UserPresence {
    AtDevice,
    StoreOnly,
}

/// A device report arriving on either carrier: store it, then tell the agents it is news to.
/// `None` when the device is unknown to the registry: a device that has never connected has no
/// identity to report against. Best-effort past the store: a stopped agent or a write failure
/// logs itself.
pub(crate) async fn report_device_context(state: &SharedState, device_id: &str, context: DeviceContext, presence: UserPresence) -> Option<()> {
    let now = crate::time_utils::now_epoch_secs();
    let device = state.device_registry.report_context(device_id, context.clone(), now)?;
    let timestamp = match crate::time_utils::epoch_to_rfc3339(now) {
        Ok(timestamp) => timestamp,
        Err(error) => {
            tracing::warn!(%error, "could not stamp user context notification");
            return Some(());
        }
    };
    // Serving agents with a reported zone: the ones vestad holds a current picture of.
    let agent_zones = state.agent_status_cache.serving_timezones();
    if let Some(zone) = context.timezone.filter(|_| presence == UserPresence::AtDevice) {
        for change in state.user_context.timezone_changes(&zone, &agent_zones) {
            let payload = timezone_notification_payload(&timestamp, &device, &zone, &change.agent_zone);
            deliver(state, &change.agent, "user-timezone", &payload).await;
        }
    }
    if let Some(PositionReport::At(position)) = context.position {
        let payload = location_notification_payload(&timestamp, &device, &position);
        for agent in state.user_context.location_changes(&position, &agent_zones) {
            deliver(state, &agent, "user-location", &payload).await;
        }
    }
    Some(())
}

/// Write one notification into an agent's intake. The file name carries the millisecond, so two
/// devices reporting inside one second (every client replaying after a gateway restart) do not
/// overwrite each other in the intake.
async fn deliver(state: &SharedState, agent: &str, kind: &str, payload: &serde_json::Value) {
    let file_name = format!("{kind}-{}.json", crate::time_utils::now_epoch_millis());
    if let Err(error) = crate::serve::drop_notification(&state.docker, agent, &file_name, payload).await {
        tracing::warn!(%agent, %error, "could not drop user context notification");
    }
}

/// `PUT /devices/{device_id}/context`: a device reporting its context outside the `/sync` socket
/// (the mobile background poll). Client-authed. The report is taken as the user being at that
/// device, so a differing zone is news to the agents. A device the registry has never seen is
/// refused: identity is minted by the `/sync` attach alone.
pub(crate) async fn report_context_handler(
    State(state): State<SharedState>,
    Path(device_id): Path<String>,
    Json(context): Json<DeviceContext>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if context.is_empty() {
        return Err(err_response(StatusCode::BAD_REQUEST, "a report carries a timezone or a position"));
    }
    match report_device_context(&state, &device_id, context, UserPresence::AtDevice).await {
        Some(()) => Ok(ok_json()),
        None => Err(err_response(StatusCode::NOT_FOUND, "unknown device")),
    }
}

/// `GET /agents/{name}/devices`: every device the user has, with its reported context, for the
/// agent's `user_devices` tool. Agent-token authed and self-scoped by the middleware.
pub(crate) async fn agent_devices_handler(State(state): State<SharedState>) -> Json<serde_json::Value> {
    Json(serde_json::json!({ "devices": state.device_registry.snapshot() }))
}

/// The `user-timezone` notification. Pure so its shape is asserted without a container. Snoozed
/// (`interrupt: false`): a zone change is worked through at the next idle point.
pub(crate) fn timezone_notification_payload(timestamp: &str, device: &str, device_zone: &str, agent_zone: &str) -> serde_json::Value {
    serde_json::json!({
        "timestamp": timestamp,
        "source": "vestad",
        "type": "user-timezone",
        "interrupt": false,
        "device": device,
        "device_timezone": device_zone,
        "agent_timezone": agent_zone,
        "message": format!(
            "the user's device ({device}) reports timezone {device_zone}; your timezone is {agent_zone}. \
             If the user has moved, update your timezone with the timezone skill."
        ),
    })
}

/// The `user-location` notification: the macro place first, the coordinates after it. Every field
/// is a scalar, since the agent renders notification fields as attribute text.
pub(crate) fn location_notification_payload(timestamp: &str, device: &str, position: &DevicePosition) -> serde_json::Value {
    let place = position.place.as_ref().and_then(DevicePlace::macro_label);
    let coordinates = match position.accuracy_m {
        Some(accuracy) => format!("{:.4}, {:.4}, ±{accuracy:.0} m", position.latitude, position.longitude),
        None => format!("{:.4}, {:.4}", position.latitude, position.longitude),
    };
    let message = match &place {
        Some(place) => format!("the user's device ({device}) is now in {place} ({coordinates})."),
        None => format!("the user's device ({device}) is now at {coordinates}, no place name known."),
    };
    serde_json::json!({
        "timestamp": timestamp,
        "source": "vestad",
        "type": "user-location",
        "interrupt": false,
        "device": device,
        "place": place,
        "latitude": position.latitude,
        "longitude": position.longitude,
        "accuracy_m": position.accuracy_m,
        "message": message,
    })
}

/// Great-circle distance between two (latitude, longitude) points in degrees.
fn distance_km(from: (f64, f64), to: (f64, f64)) -> f64 {
    let (lat_from, lon_from) = (from.0.to_radians(), from.1.to_radians());
    let (lat_to, lon_to) = (to.0.to_radians(), to.1.to_radians());
    let half_lat = ((lat_to - lat_from) / 2.0).sin();
    let half_lon = ((lon_to - lon_from) / 2.0).sin();
    let chord = half_lat * half_lat + lat_from.cos() * lat_to.cos() * half_lon * half_lon;
    2.0 * EARTH_RADIUS_KM * chord.sqrt().asin()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn zones(pairs: &[(&str, &str)]) -> AgentZones {
        pairs.iter().map(|(agent, zone)| ((*agent).to_string(), (*zone).to_string())).collect()
    }

    fn at(latitude: f64, longitude: f64, city: Option<&str>) -> DevicePosition {
        DevicePosition {
            latitude,
            longitude,
            accuracy_m: None,
            place: city.map(|city| DevicePlace { city: Some(city.into()), region: None, country: Some("X".into()) }),
        }
    }

    #[test]
    fn a_differing_zone_is_told_once_whichever_device_reports_it() {
        let context = UserContext::default();
        let fleet = zones(&[("scout", "Europe/London"), ("quiet", "Asia/Tokyo")]);
        let first = context.timezone_changes("Asia/Tokyo", &fleet);
        assert_eq!(first, vec![TimezoneChange { agent: "scout".into(), agent_zone: "Europe/London".into() }]);
        // A second device landing in the same zone is the same fact.
        assert!(context.timezone_changes("Asia/Tokyo", &fleet).is_empty(), "already told");
    }

    #[test]
    fn each_move_is_told_once_and_home_is_silent_while_the_agent_stays() {
        let context = UserContext::default();
        let fleet = zones(&[("scout", "Europe/London")]);
        assert_eq!(context.timezone_changes("Asia/Tokyo", &fleet).len(), 1);
        assert_eq!(context.timezone_changes("America/New_York", &fleet).len(), 1, "a real move");
        assert_eq!(context.timezone_changes("Asia/Tokyo", &fleet).len(), 1, "and back is a real move too");
        assert!(context.timezone_changes("Europe/London", &fleet).is_empty(), "home equals the agent's zone");
    }

    #[test]
    fn the_agents_own_zone_is_read_live_so_no_reset_is_needed() {
        let context = UserContext::default();
        assert_eq!(context.timezone_changes("Asia/Tokyo", &zones(&[("scout", "Europe/London")])).len(), 1);
        // The agent moved to Tokyo: a device in Tokyo is where it already is.
        assert!(context.timezone_changes("Asia/Tokyo", &zones(&[("scout", "Asia/Tokyo")])).is_empty());
        // And a device back in London is news.
        assert_eq!(context.timezone_changes("Europe/London", &zones(&[("scout", "Asia/Tokyo")])).len(), 1);
    }

    #[test]
    fn a_first_position_is_told_then_only_a_new_place() {
        let context = UserContext::default();
        let fleet = zones(&[("scout", "Europe/London")]);
        assert_eq!(context.location_changes(&at(51.5, -0.12, Some("London")), &fleet), ["scout"]);
        assert!(context.location_changes(&at(51.51, -0.13, Some("London")), &fleet).is_empty(), "same city");
        assert_eq!(context.location_changes(&at(35.68, 139.65, Some("Tokyo")), &fleet), ["scout"]);
    }

    #[test]
    fn without_a_place_distance_decides() {
        let context = UserContext::default();
        let fleet = zones(&[("scout", "Europe/London")]);
        assert_eq!(context.location_changes(&at(51.5, -0.12, None), &fleet), ["scout"]);
        assert!(context.location_changes(&at(51.6, -0.12, None), &fleet).is_empty(), "11 km is a walk");
        assert_eq!(context.location_changes(&at(52.0, -0.12, None), &fleet), ["scout"], "56 km is a trip");
    }

    #[test]
    fn timezone_payload_names_device_and_both_zones() {
        let payload = timezone_notification_payload("2026-05-28T20:26:40Z", "Chrome on macOS", "Asia/Tokyo", "Europe/London");
        assert_eq!(payload["source"], "vestad");
        assert_eq!(payload["type"], "user-timezone");
        assert_eq!(payload["interrupt"], false);
        assert_eq!(payload["device_timezone"], "Asia/Tokyo");
        assert_eq!(payload["agent_timezone"], "Europe/London");
        let message = payload["message"].as_str().expect("message");
        assert!(message.contains("Chrome on macOS") && message.contains("Asia/Tokyo") && message.contains("Europe/London"));
    }

    #[test]
    fn location_payload_leads_with_the_place_then_the_coordinates() {
        let mut position = at(35.6762, 139.6503, Some("Tokyo"));
        position.accuracy_m = Some(50.0);
        let payload = location_notification_payload("2026-05-28T20:26:40Z", "Vesta Mobile on iOS", &position);
        assert_eq!(payload["type"], "user-location");
        assert_eq!(payload["place"], "Tokyo, X");
        assert_eq!(payload["latitude"], 35.6762);
        assert_eq!(payload["accuracy_m"], 50.0);
        assert!(payload["position"].is_null(), "no nested objects: the agent renders fields as text");
        assert_eq!(payload["message"], "the user's device (Vesta Mobile on iOS) is now in Tokyo, X (35.6762, 139.6503, ±50 m).");
        let bare = location_notification_payload("2026-05-28T20:26:40Z", "phone", &at(1.0, 2.0, None));
        assert_eq!(bare["place"], serde_json::Value::Null);
        assert_eq!(bare["message"], "the user's device (phone) is now at 1.0000, 2.0000, no place name known.");
    }

    #[test]
    fn distance_is_the_great_circle() {
        let london_to_paris = distance_km((51.5074, -0.1278), (48.8566, 2.3522));
        assert!((london_to_paris - 343.5).abs() < 2.0, "got {london_to_paris}");
    }
}
