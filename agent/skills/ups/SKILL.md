---
name: ups
description: "This skill should be used when the user asks about \"UPS\", \"battery\", \"power outage\", \"mains power\", or needs to check UPS status or battery level. Monitors UPS via NUT and alerts on power events. Requires a background daemon."
---

# UPS Skill

Monitors the UPS via NUT (Network UPS Tools) over local network.

## What it does
- Monitors UPS status continuously (every 30s on mains, every 30s on battery)
- Alerts via WhatsApp when power cuts or is restored
- Sends full battery status every minute while on battery power
- Alerts when battery drops below 20%

## Requirements
- NUT (`nut`) must be installed and running on the Ubuntu host
- UPS configured in `/etc/nut/ups.conf` as `ecoflow` (vendorid=3746, productid=ffff)
- NUT daemon listening on `localhost:3493`

## Daemon
```
screen -dmS ups-monitor python3 ~/vesta/skills/ups/monitor.py
```

## Status query (manual)
Ask okami "ups status" or "how's the UPS?" — will query NUT and report.

## Setup (host-side, one-time)
1. `sudo apt install nut`
2. Configure `/etc/nut/ups.conf`, `nut.conf`, `upsd.conf`, `upsd.users` (see notes)
3. `sudo systemctl enable nut-server nut-driver && sudo systemctl start nut-driver nut-server`
