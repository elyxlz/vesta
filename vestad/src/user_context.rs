//! Which agents to tell about the user's device context, and once. A device reporting a timezone
//! that differs from an agent's own zone earns that agent one `user-timezone` notification per
//! zone, reset when the agent's own zone changes (it acted, or moved on its own). A position whose
//! macro place differs from the last place an agent was told, or that moved far enough with no
//! place to compare, earns one `user-location` notification. The registry stores the facts; this
//! module only decides who hears about a change. Pure decisions over an in-memory told-state, so
//! a vestad restart re-tells at most once.

use std::collections::{HashMap, HashSet};
use std::sync::Mutex;

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::Json;

use crate::device_registry::{DeviceContext, DevicePlace, DevicePosition};
use crate::state::{err_response, ok_json, SharedState};

/// With no macro place to compare, a position must move at least this far from the last told
/// point before an agent hears about it again.
pub(crate) const LOCATION_NOTIFY_MIN_KM: f64 = 25.0;

const EARTH_RADIUS_KM: f64 = 6371.0;

#[derive(Debug, Default)]
struct Told {
    /// The agent's own zone the `zones` set was accumulated under; a different current zone resets it.
    agent_zone: Option<String>,
    zones: HashSet<String>,
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

impl UserContext {
    pub(crate) fn new() -> Self {
        Self::default()
    }

    /// The agents to tell that a device reports `device_zone`, out of `agent_zones` (agent name ->
    /// its own zone, serving agents only). An agent already on that zone, or already told it since
    /// its own zone last changed, is skipped; the ones returned are marked told.
    pub(crate) fn timezone_changes(&self, device_zone: &str, agent_zones: &HashMap<String, String>) -> Vec<TimezoneChange> {
        let mut told = self.told.lock().expect("user context mutex");
        let mut changes: Vec<TimezoneChange> = agent_zones
            .iter()
            .filter_map(|(agent, agent_zone)| {
                let entry = told.entry(agent.clone()).or_default();
                if entry.agent_zone.as_deref() != Some(agent_zone.as_str()) {
                    entry.agent_zone = Some(agent_zone.clone());
                    entry.zones.clear();
                }
                if agent_zone == device_zone || !entry.zones.insert(device_zone.to_string()) {
                    return None;
                }
                Some(TimezoneChange { agent: agent.clone(), agent_zone: agent_zone.clone() })
            })
            .collect();
        changes.sort_by(|a, b| a.agent.cmp(&b.agent));
        changes
    }

    /// The agents to tell that a device is at `position`, out of `agents` (serving agents only): the
    /// macro place differs from the last one told, or, when either side has no place, the point
    /// moved at least `LOCATION_NOTIFY_MIN_KM` from the last told point. The ones returned are
    /// marked told.
    pub(crate) fn location_changes(&self, position: &DevicePosition, agents: &[String]) -> Vec<String> {
        let mut told = self.told.lock().expect("user context mutex");
        let place = position.place.as_ref().and_then(DevicePlace::macro_label);
        let point = (position.latitude, position.longitude);
        let mut changes: Vec<String> = agents
            .iter()
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
            .collect();
        changes.sort();
        changes
    }
}

/// A device report arriving on either carrier: store it, then tell the agents it is news to.
/// `counts_for_timezone` is whether this report places the user at that device (a focused socket
/// frame, or a background poll from a phone); an unfocused frame stores its zone but tells no one.
/// Best-effort past the store: a stopped agent or a write failure logs itself.
pub(crate) async fn report_device_context(state: &SharedState, device_id: &str, context: DeviceContext, counts_for_timezone: bool) {
    let now = crate::time_utils::now_epoch_secs();
    let identity = state.device_registry.report_context(device_id, context.clone(), now);
    let device = identity.label();
    // Serving agents with a reported zone: the ones vestad holds a current picture of.
    let agent_zones = state.agent_status_cache.serving_timezones();
    if let Some(zone) = context.timezone.filter(|_| counts_for_timezone) {
        for change in state.user_context.timezone_changes(&zone, &agent_zones) {
            let payload = timezone_notification_payload(now, &device, &zone, &change.agent_zone);
            deliver(state, &change.agent, &format!("user-timezone-{now}.json"), payload).await;
        }
    }
    if let Some(position) = context.position {
        let agents: Vec<String> = agent_zones.into_keys().collect();
        for agent in state.user_context.location_changes(&position, &agents) {
            let payload = location_notification_payload(now, &device, &position);
            deliver(state, &agent, &format!("user-location-{now}.json"), payload).await;
        }
    }
}

async fn deliver(state: &SharedState, agent: &str, file_name: &str, payload: Result<serde_json::Value, String>) {
    let written = match payload {
        Ok(payload) => crate::serve::drop_notification(&state.docker, agent, file_name, &payload).await,
        Err(error) => Err(error),
    };
    if let Err(error) = written {
        tracing::warn!(%agent, %error, "could not drop user context notification");
    }
}

/// `PUT /devices/{device_id}/context`: a device reporting its context outside the `/sync` socket
/// (the mobile background poll). Client-authed. The report is taken as the user being at that
/// device, so a differing zone is news to the agents.
pub(crate) async fn report_context_handler(
    State(state): State<SharedState>,
    Path(device_id): Path<String>,
    Json(context): Json<DeviceContext>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if device_id.trim().is_empty() {
        return Err(err_response(StatusCode::BAD_REQUEST, "device id is required"));
    }
    if context.is_empty() {
        return Err(err_response(StatusCode::BAD_REQUEST, "a report carries a timezone or a position"));
    }
    report_device_context(&state, &device_id, context, true).await;
    Ok(ok_json())
}

/// `GET /agents/{name}/devices`: every device the user has, with its reported context, for the
/// agent's `user_devices` tool. Agent-token authed and self-scoped by the middleware.
pub(crate) async fn agent_devices_handler(State(state): State<SharedState>) -> Json<serde_json::Value> {
    Json(serde_json::json!({ "devices": state.device_registry.snapshot() }))
}

/// The `user-timezone` notification. Pure so its shape is asserted without a container. Snoozed
/// (`interrupt: false`): a zone change is worked through at the next idle point.
pub(crate) fn timezone_notification_payload(
    epoch_secs: u64,
    device: &str,
    device_zone: &str,
    agent_zone: &str,
) -> Result<serde_json::Value, String> {
    let timestamp = crate::time_utils::epoch_to_rfc3339(epoch_secs)?;
    Ok(serde_json::json!({
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
    }))
}

/// The `user-location` notification: the macro place first, the coordinates after it.
pub(crate) fn location_notification_payload(
    epoch_secs: u64,
    device: &str,
    position: &DevicePosition,
) -> Result<serde_json::Value, String> {
    let timestamp = crate::time_utils::epoch_to_rfc3339(epoch_secs)?;
    let place = position.place.as_ref().and_then(DevicePlace::macro_label);
    let coordinates = match position.accuracy_m {
        Some(accuracy) => format!("{:.4}, {:.4}, ±{accuracy:.0} m", position.latitude, position.longitude),
        None => format!("{:.4}, {:.4}", position.latitude, position.longitude),
    };
    let message = match &place {
        Some(place) => format!("the user's device ({device}) is now in {place} ({coordinates})."),
        None => format!("the user's device ({device}) is now at {coordinates}, no place name known."),
    };
    Ok(serde_json::json!({
        "timestamp": timestamp,
        "source": "vestad",
        "type": "user-location",
        "interrupt": false,
        "device": device,
        "place": place,
        "position": position,
        "message": message,
    }))
}

/// Great-circle distance between two (latitude, longitude) points in degrees.
fn distance_km(a: (f64, f64), b: (f64, f64)) -> f64 {
    let (lat_a, lon_a) = (a.0.to_radians(), a.1.to_radians());
    let (lat_b, lon_b) = (b.0.to_radians(), b.1.to_radians());
    let half_lat = ((lat_b - lat_a) / 2.0).sin();
    let half_lon = ((lon_b - lon_a) / 2.0).sin();
    let chord = half_lat * half_lat + lat_a.cos() * lat_b.cos() * half_lon * half_lon;
    2.0 * EARTH_RADIUS_KM * chord.sqrt().asin()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn zones(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs.iter().map(|(agent, zone)| ((*agent).to_string(), (*zone).to_string())).collect()
    }

    fn agents(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| (*name).to_string()).collect()
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
    fn a_differing_zone_is_told_once_per_agent() {
        let context = UserContext::new();
        let fleet = zones(&[("scout", "Europe/London"), ("quiet", "Asia/Tokyo")]);
        let first = context.timezone_changes("Asia/Tokyo", &fleet);
        assert_eq!(first, vec![TimezoneChange { agent: "scout".into(), agent_zone: "Europe/London".into() }]);
        assert!(context.timezone_changes("Asia/Tokyo", &fleet).is_empty(), "already told");
    }

    #[test]
    fn a_second_zone_is_told_and_the_first_stays_told() {
        let context = UserContext::new();
        let fleet = zones(&[("scout", "Europe/London")]);
        assert_eq!(context.timezone_changes("Asia/Tokyo", &fleet).len(), 1);
        assert_eq!(context.timezone_changes("America/New_York", &fleet).len(), 1);
        assert!(context.timezone_changes("Asia/Tokyo", &fleet).is_empty());
    }

    #[test]
    fn the_agent_changing_its_own_zone_resets_what_it_was_told() {
        let context = UserContext::new();
        assert_eq!(context.timezone_changes("Asia/Tokyo", &zones(&[("scout", "Europe/London")])).len(), 1);
        // The agent moved to Tokyo: a device back in London is news again.
        assert_eq!(context.timezone_changes("Europe/London", &zones(&[("scout", "Asia/Tokyo")])).len(), 1);
        // And a device in Tokyo is where the agent already is.
        assert!(context.timezone_changes("Asia/Tokyo", &zones(&[("scout", "Asia/Tokyo")])).is_empty());
    }

    #[test]
    fn a_first_position_is_told_then_only_a_new_place() {
        let context = UserContext::new();
        let fleet = agents(&["scout"]);
        assert_eq!(context.location_changes(&at(51.5, -0.12, Some("London")), &fleet), fleet);
        assert!(context.location_changes(&at(51.51, -0.13, Some("London")), &fleet).is_empty(), "same city");
        assert_eq!(context.location_changes(&at(35.68, 139.65, Some("Tokyo")), &fleet), fleet);
    }

    #[test]
    fn without_a_place_distance_decides() {
        let context = UserContext::new();
        let fleet = agents(&["scout"]);
        assert_eq!(context.location_changes(&at(51.5, -0.12, None), &fleet), fleet);
        assert!(context.location_changes(&at(51.6, -0.12, None), &fleet).is_empty(), "11 km is a walk");
        assert_eq!(context.location_changes(&at(52.0, -0.12, None), &fleet), fleet, "56 km is a trip");
    }

    #[test]
    fn timezone_payload_names_device_and_both_zones() {
        let payload = timezone_notification_payload(1_780_000_000, "Chrome on macOS", "Asia/Tokyo", "Europe/London").expect("payload");
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
        let payload = location_notification_payload(1_780_000_000, "Vesta Mobile on iOS", &position).expect("payload");
        assert_eq!(payload["type"], "user-location");
        assert_eq!(payload["place"], "Tokyo, X");
        assert_eq!(payload["position"]["latitude"], 35.6762);
        assert_eq!(payload["position"]["place"]["city"], "Tokyo");
        assert_eq!(payload["message"], "the user's device (Vesta Mobile on iOS) is now in Tokyo, X (35.6762, 139.6503, ±50 m).");
        let bare = location_notification_payload(1_780_000_000, "phone", &at(1.0, 2.0, None)).expect("payload");
        assert_eq!(bare["place"], serde_json::Value::Null);
        assert_eq!(bare["message"], "the user's device (phone) is now at 1.0000, 2.0000, no place name known.");
    }

    #[test]
    fn distance_is_the_great_circle() {
        let london_to_paris = distance_km((51.5074, -0.1278), (48.8566, 2.3522));
        assert!((london_to_paris - 343.5).abs() < 2.0, "got {london_to_paris}");
    }
}
