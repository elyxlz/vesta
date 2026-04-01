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
    entries = []
    for entry in history[0]:
        entries.append(
            {
                "state": entry.get("state", ""),
                "last_changed": entry.get("last_changed", ""),
            }
        )
    return entries


def check_api(config: Config) -> dict:
    client = HAClient(config)
    return client.check_api()
