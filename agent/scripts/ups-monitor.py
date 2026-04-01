#!/usr/bin/env python3
# UPS monitor — watches EcoFlow via NUT, alerts via WhatsApp on power events

import socket
import time
import subprocess
import os

NUT_HOST = "localhost"
NUT_PORT = 3493
UPS_NAME = "ecoflow"
WA_NUMBER = "+393483826189"
CHECK_INTERVAL = 30  # seconds
BATTERY_LOW_THRESHOLD = 20  # percent

last_status = None
last_battery = None
alerted_low = False


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
    # VAR ecoflow ups.status "OL"
    try:
        return result.split('"')[1]
    except:
        return None


def send_whatsapp(msg):
    subprocess.run(
        ["whatsapp", "send", "--to", WA_NUMBER, "--message", msg],
        capture_output=True
    )


def main():
    global last_status, last_battery, alerted_low
    print(f"[UPS monitor] starting — polling every {CHECK_INTERVAL}s")
    send_whatsapp("🔌 UPS monitor started — watching EcoFlow River 3 Plus")

    while True:
        status = get_var("ups.status")
        battery = get_var("battery.charge")
        runtime_s = get_var("battery.runtime")

        if status is None:
            time.sleep(CHECK_INTERVAL)
            continue

        battery_pct = int(battery) if battery else None
        runtime_min = int(runtime_s) // 60 if runtime_s else None

        # Power loss — OL → OB
        if last_status == "OL" and "OB" in status:
            msg = f"⚡ POWER CUT — on battery now. {battery_pct}% charge, ~{runtime_min} min remaining"
            print(f"[UPS monitor] ALERT: {msg}")
            send_whatsapp(msg)
            alerted_low = False

        # Power restored — OB → OL
        elif last_status and "OB" in last_status and status == "OL":
            msg = f"✅ Power restored — back on mains. Battery at {battery_pct}%"
            print(f"[UPS monitor] INFO: {msg}")
            send_whatsapp(msg)
            alerted_low = False

        # Battery low (only while on battery)
        if battery_pct and battery_pct <= BATTERY_LOW_THRESHOLD and "OB" in (status or ""):
            if not alerted_low:
                msg = f"🔋 Battery LOW: {battery_pct}% — ~{runtime_min} min left. Shutdown soon."
                print(f"[UPS monitor] ALERT: {msg}")
                send_whatsapp(msg)
                alerted_low = True

        last_status = status
        last_battery = battery_pct
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
