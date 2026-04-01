#!/usr/bin/env python3
# UPS monitor skill — watches EcoFlow via NUT, alerts via WhatsApp on power events
# While on battery: sends full status every minute

import socket
import time
import subprocess
import sys

NUT_HOST = "localhost"
NUT_PORT = 3493
UPS_NAME = "ecoflow"
WA_NUMBER = "+393483826189"
CHECK_INTERVAL = 30  # seconds (normal, on mains)
BATTERY_REPORT_INTERVAL = 60  # seconds between status messages while on battery
BATTERY_LOW_THRESHOLD = 20

last_status = None
alerted_low = False
last_battery_report = 0


def query_nut(cmd):
    try:
        s = socket.socket()
        s.settimeout(5)
        s.connect((NUT_HOST, NUT_PORT))
        s.send((cmd + "\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            data += chunk
            if b"END" in data or b"ERR" in data or not chunk:
                break
        s.close()
        return data.decode()
    except Exception as e:
        return f"ERR {e}"


def get_var(var):
    result = query_nut(f"GET VAR {UPS_NAME} {var}")
    try:
        return result.split('"')[1]
    except (IndexError, ValueError):
        return None


def get_all_vars():
    result = query_nut(f"LIST VAR {UPS_NAME}")
    vars = {}
    for line in result.splitlines():
        if line.startswith("VAR"):
            parts = line.split('"')
            if len(parts) >= 2:
                key = line.split()[2]
                val = parts[1]
                vars[key] = val
    return vars


def send_whatsapp(msg):
    subprocess.run(["whatsapp", "send", "--to", WA_NUMBER, "--message", msg], capture_output=True)


def battery_report(vars):
    charge = vars.get("battery.charge", "?")
    runtime_s = vars.get("battery.runtime", None)
    voltage = vars.get("battery.voltage", "?")
    status = vars.get("ups.status", "?")
    power = vars.get("ups.power.nominal", "?")

    runtime_str = ""
    if runtime_s and runtime_s.isdigit():
        mins = int(runtime_s) // 60
        runtime_str = f" | ~{mins} min left"

    return f"🔋 UPS status: {charge}% | {voltage}V | {status}{runtime_str} | {power}W nominal"


def main():
    global last_status, alerted_low, last_battery_report

    # Handle serve subcommand
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        pass  # fall through to monitoring loop

    print("[UPS monitor] starting")
    send_whatsapp("🔌 UPS monitor started — watching EcoFlow River 3 Plus")

    while True:
        vars = get_all_vars()
        status = vars.get("ups.status", "")

        if not status:
            time.sleep(CHECK_INTERVAL)
            continue

        on_battery = "OB" in status
        now = time.time()

        # Power loss event
        if last_status == "OL" and on_battery:
            charge = vars.get("battery.charge", "?")
            runtime_s = vars.get("battery.runtime", None)
            runtime_str = f" (~{int(runtime_s) // 60} min)" if runtime_s and runtime_s.isdigit() else ""
            msg = f"⚡ POWER CUT — switched to battery. {charge}%{runtime_str}"
            print(f"[UPS] ALERT: {msg}")
            send_whatsapp(msg)
            alerted_low = False
            last_battery_report = now

        # Power restored
        elif last_status and "OB" in last_status and not on_battery:
            charge = vars.get("battery.charge", "?")
            msg = f"✅ Power restored — back on mains. Battery at {charge}%"
            print(f"[UPS] INFO: {msg}")
            send_whatsapp(msg)
            alerted_low = False

        # While on battery: send status every minute
        if on_battery:
            if now - last_battery_report >= BATTERY_REPORT_INTERVAL:
                msg = battery_report(vars)
                print(f"[UPS] {msg}")
                send_whatsapp(msg)
                last_battery_report = now

            # Low battery alert
            charge = vars.get("battery.charge", "100")
            if charge.isdigit() and int(charge) <= BATTERY_LOW_THRESHOLD and not alerted_low:
                runtime_s = vars.get("battery.runtime", None)
                runtime_str = f" ~{int(runtime_s) // 60} min left" if runtime_s and runtime_s.isdigit() else ""
                msg = f"🔋 Battery LOW: {charge}%{runtime_str} — shutting down soon"
                print(f"[UPS] ALERT: {msg}")
                send_whatsapp(msg)
                alerted_low = True

        last_status = status
        time.sleep(CHECK_INTERVAL if not on_battery else 30)


if __name__ == "__main__":
    main()
