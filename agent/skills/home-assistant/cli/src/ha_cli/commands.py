from .api import HAClient
from .config import Config


def _slim_state(s: dict) -> dict:
    """Compact state representation."""
    out = {
        "entity_id": s["entity_id"],
        "state": s["state"],
        "friendly_name": s["attributes"].get("friendly_name", ""),
    }
    # include unit if present
    unit = s["attributes"].get("unit_of_measurement")
    if unit:
        out["unit"] = unit
    # include device class if present
    dc = s["attributes"].get("device_class")
    if dc:
        out["device_class"] = dc
    out["last_changed"] = s.get("last_changed", "")
    return out


def _full_state(s: dict) -> dict:
    """Full state with all attributes."""
    return {
        "entity_id": s["entity_id"],
        "state": s["state"],
        "attributes": s["attributes"],
        "last_changed": s.get("last_changed", ""),
        "last_updated": s.get("last_updated", ""),
    }


def get_state(config: Config, entity_id: str, full: bool = False) -> dict:
    client = HAClient(config)
    s = client.get_state(entity_id)
    return _full_state(s) if full else _slim_state(s)


def list_states(config: Config, domain: str | None = None, search: str | None = None) -> list[dict]:
    client = HAClient(config)
    states = client.get_all_states()
    if domain:
        states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]
    if search:
        q = search.lower()
        states = [s for s in states if q in s["entity_id"].lower() or q in s["attributes"].get("friendly_name", "").lower()]
    return [_slim_state(s) for s in sorted(states, key=lambda x: x["entity_id"])]


def energy_summary(config: Config) -> dict:
    client = HAClient(config)
    daily = client.get_state("sensor.daily_energy_so_ai")
    total = client.get_state("sensor.energy_total_so_ai")
    power = client.get_state("sensor.generale_power")
    return {
        "daily_kwh": float(daily["state"]) if daily["state"] not in ("unavailable", "unknown") else None,
        "total_kwh": float(total["state"]) if total["state"] not in ("unavailable", "unknown") else None,
        "current_watts": float(power["state"]) if power["state"] not in ("unavailable", "unknown") else None,
        "last_reset": daily["attributes"].get("last_reset", ""),
    }


def location(config: Config) -> dict:
    client = HAClient(config)
    person = client.get_state("person.lucio_pascarelli")
    attrs = person["attributes"]
    phone = client.get_state("sensor.lps_brick_s25_ultra_battery_level")
    phone_state = client.get_state("sensor.lps_brick_s25_ultra_battery_state")
    phone_charger = client.get_state("sensor.lps_brick_s25_ultra_charger_type")
    return {
        "state": person["state"],
        "latitude": attrs.get("latitude"),
        "longitude": attrs.get("longitude"),
        "gps_accuracy": attrs.get("gps_accuracy"),
        "maps_url": f"https://www.google.com/maps?q={attrs.get('latitude')},{attrs.get('longitude')}" if attrs.get("latitude") else None,
        "last_updated": person.get("last_updated", ""),
        "phone_battery": f"{phone['state']}%",
        "phone_battery_state": phone_state["state"],
        "phone_charger": phone_charger["state"],
    }


def climate_summary(config: Config) -> dict:
    client = HAClient(config)

    def _safe_float(entity_id):
        try:
            s = client.get_state(entity_id)
            v = s["state"]
            return float(v) if v not in ("unavailable", "unknown") else None
        except Exception:
            return None

    return {
        "outdoor": {
            "temperature_c": _safe_float("sensor.bedroom_unknown_02_00_00_af_77_10_temperature"),
            "humidity": _safe_float("sensor.bedroom_unknown_02_00_00_af_77_10_humidity"),
        },
        "bedroom": {
            "temperature_c": _safe_float("sensor.bedroom_temperature"),
            "humidity": _safe_float("sensor.bedroom_humidity"),
            "co2": _safe_float("sensor.bedroom_carbon_dioxide"),
            "noise_db": _safe_float("sensor.bedroom_noise"),
            "pressure_hpa": _safe_float("sensor.bedroom_atmospheric_pressure"),
        },
        "living_room": {
            "temperature_c": _safe_float("sensor.bedroom_living_room_sensor_temperature"),
            "humidity": _safe_float("sensor.bedroom_living_room_sensor_humidity"),
            "co2": _safe_float("sensor.bedroom_living_room_sensor_carbon_dioxide"),
        },
        "studio": {
            "temperature_c": _safe_float("sensor.bedroom_studio_temperature"),
            "humidity": _safe_float("sensor.bedroom_studio_humidity"),
            "co2": _safe_float("sensor.bedroom_studio_carbon_dioxide"),
        },
    }


def weather(config: Config) -> dict:
    client = HAClient(config)
    w = client.get_state("weather.forecast_home")
    sun = client.get_state("sun.sun")
    sunrise = client.get_state("sensor.sun_next_rising")
    sunset = client.get_state("sensor.sun_next_setting")
    return {
        "condition": w["state"],
        "temperature_c": w["attributes"].get("temperature"),
        "humidity": w["attributes"].get("humidity"),
        "wind_speed_kmh": w["attributes"].get("wind_speed"),
        "wind_bearing": w["attributes"].get("wind_bearing"),
        "sun": sun["state"],
        "sunrise": sunrise["state"],
        "sunset": sunset["state"],
    }


def security_summary(config: Config) -> dict:
    client = HAClient(config)

    def _alarm(entity_id):
        try:
            s = client.get_state(entity_id)
            return {"state": s["state"], "friendly_name": s["attributes"].get("friendly_name", "")}
        except Exception:
            return {"state": "error"}

    # count cameras with motion detected
    states = client.get_all_states()
    motion_sensors = [s for s in states if s["entity_id"].startswith("binary_sensor.") and s["entity_id"].endswith("_motion")]
    active_motion = [s["attributes"].get("friendly_name", s["entity_id"]) for s in motion_sensors if s["state"] == "on"]

    return {
        "alarms": {
            "cantinetta": _alarm("alarm_control_panel.blink_nuraghecantinetta"),
            "sopra": _alarm("alarm_control_panel.blink_nuraghesopra"),
            "sotto": _alarm("alarm_control_panel.blink_nuraghesotto"),
        },
        "active_motion": active_motion if active_motion else "none",
    }


def home_overview(config: Config) -> dict:
    """Combined overview for morning briefings etc."""
    return {
        "energy": energy_summary(config),
        "climate": climate_summary(config),
        "weather": weather(config),
        "security": security_summary(config),
        "location": location(config),
    }


def call_service(config: Config, domain: str, service: str, entity_id: str | None = None, data: dict | None = None) -> dict:
    client = HAClient(config)
    payload = data or {}
    if entity_id:
        payload["entity_id"] = entity_id
    result = client.call_service(domain, service, payload)
    return {"status": "ok", "changed_states": len(result)}


def get_history(config: Config, entity_id: str, hours: int = 24) -> list[dict]:
    client = HAClient(config)
    history = client.get_history(entity_id, hours)
    if not history or not history[0]:
        return []
    # return compact history
    entries = []
    for entry in history[0]:
        entries.append({
            "state": entry.get("state", ""),
            "last_changed": entry.get("last_changed", ""),
        })
    return entries


def check_api(config: Config) -> dict:
    client = HAClient(config)
    return client.check_api()
