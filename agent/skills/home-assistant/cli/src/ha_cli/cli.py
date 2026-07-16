import argparse
import json
import sys

from . import commands
from .config import Config


def main():
    parser = argparse.ArgumentParser(prog="ha", description="Home Assistant CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # state
    p_state = sub.add_parser("state", help="Get state of an entity")
    p_state.add_argument("entity_id", help="Entity ID (e.g. sensor.temperature)")
    p_state.add_argument("--full", action="store_true", help="Include all attributes")

    # states (list)
    p_states = sub.add_parser("states", help="List entity states")
    p_states.add_argument("--domain", default=None, help="Filter by domain (e.g. sensor, switch, camera)")
    p_states.add_argument("--search", default=None, help="Search entity IDs and names")

    # weather
    sub.add_parser("weather", help="Weather and sun info")

    # service
    p_service = sub.add_parser("service", help="Call a Home Assistant service")
    p_service.add_argument("domain", help="Service domain (e.g. switch, light)")
    p_service.add_argument("service_name", help="Service name (e.g. turn_on, turn_off)")
    p_service.add_argument("--entity-id", default=None, help="Target entity ID")
    p_service.add_argument("--data", default=None, help="JSON data payload")

    # history
    p_history = sub.add_parser("history", help="Get state history for an entity")
    p_history.add_argument("entity_id", help="Entity ID")
    p_history.add_argument("--hours", type=int, default=24, help="Hours of history (default: 24)")

    # ping
    sub.add_parser("ping", help="Check API connectivity")

    args = parser.parse_args()
    config = Config()

    try:
        result = _dispatch(args, config)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


def _dispatch(args, config: Config):
    if args.command == "state":
        return commands.get_state(config, args.entity_id, full=args.full)
    if args.command == "states":
        return commands.list_states(config, domain=args.domain, search=args.search)
    if args.command == "weather":
        return commands.weather(config)
    if args.command == "service":
        data = json.loads(args.data) if args.data else None
        return commands.call_service(config, args.domain, args.service_name, entity_id=args.entity_id, data=data)
    if args.command == "history":
        return commands.get_history(config, args.entity_id, hours=args.hours)
    if args.command == "ping":
        return commands.check_api(config)
    return None


if __name__ == "__main__":
    main()
