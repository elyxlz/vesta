---
name: walking-guide
description: Use this skill when the user asks for a "walking guide", "tour guide", "historical tour", "what's nearby", "points of interest", or wants location-based historical information while walking. Tracks GPS via Home Assistant and sends WhatsApp messages about nearby historical sites when the user moves. Requires a background daemon.
---

# Walking Guide

A location-aware walking tour guide. Polls the user's GPS position via Home Assistant, detects movement, researches nearby historical points of interest, and sends casual WhatsApp messages about them.

## Prerequisites

- **Home Assistant** with a device tracker entity for the user's smartphone (e.g. via the HA Companion App)
- **WhatsApp skill** configured and running
- The HA Companion App must have location permissions enabled and be actively reporting to your HA instance
- `HASS_TOKEN` and `HASS_URL` must be set in `/etc/environment` or the shell environment

> **Important**: This skill depends on receiving constant location updates from the user's smartphone via Home Assistant. If the HA Companion App is not installed, lacks location permissions, or the phone has poor connectivity to the HA instance, location updates will be delayed or unavailable. The skill works best when the user is on the same network as HA, or when the HA instance is publicly accessible.

## How it works

1. A background daemon polls the HA device tracker at a configurable interval (default: every 2 minutes)
2. When the user moves more than a configurable distance from the last-notified position (default: 50 meters), it drops a notification
3. The agent picks up the notification, researches nearby historical sites via web search, and sends a WhatsApp message
4. Already-mentioned places are tracked in `/tmp/walking-guide-sent.txt` to avoid repetition

## Starting the guide

```bash
walking-guide start --phone <number> --entity <ha_entity> [--interval <seconds>] [--threshold <meters>]
```

Options:
- `--phone` (required in generic mode): WhatsApp number to send messages to
- `--entity` (required in generic mode): HA device tracker entity ID (e.g. `device_tracker.my_phone`)
- `--interval`: Polling interval in seconds (default: 120)
- `--threshold`: Movement threshold in meters (default: 50)

## Stopping the guide

```bash
walking-guide stop
```

## Running as a daemon

```bash
screen -dmS walking-guide walking-guide start --phone +1234567890 --entity device_tracker.my_phone
```

## Style guidelines for agent messages

When processing walking-guide notifications, the agent should:
- Be a knowledgeable friend walking alongside — casual, interesting, maybe a fun fact
- Keep messages concise — 2-4 sentences max
- Focus on things within ~200 meters: historical buildings, monuments, plaques, churches, notable sites, blue plaques, archaeological finds
- Don't repeat places already mentioned (check the sent file)
- Skip silently if nothing notable is nearby
