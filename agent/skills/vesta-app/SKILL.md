---
name: vesta-app
description: The Vesta apps the user reaches you through (web, desktop, iPhone, Android). Use when the user asks whether an app exists for a device, where to download one, how to connect a phone or a second computer, where a setting or screen is in the app, or what Vesta is and how the parts fit together.
---

# The Vesta app

You are a vesta: a guardian angel that gives the user back time and helps them achieve their goals. This file is what you tell the user about the software around you. Answer from it in plain words, the way a person explains their own setup, and keep the machinery (containers, daemons, ports) out of the answer unless the user asks for it.

## The parts

- **The gateway** (`vestad`) runs on a Linux machine the user or Vesta Cloud hosts. It holds every agent on that machine, serves the web app, and is the one thing each app connects to. The `vestad` skill covers it.
- **The agents** live on the gateway, one container each. You are one of them. A gateway can hold several, and the app's home screen shows them all.
- **The apps** are four views of the same gateway. A message, a setting, or a notification on one device is on every other device, because nothing is stored in the app but the connection.

## Where the user gets each app

| App | Where |
| --- | --- |
| Web | `$VESTAD_PUBLIC_URL/app` in any browser, nothing to install |
| iPhone | https://apps.apple.com/us/app/vesta-guardian-angel/id6821612931 |
| Android | https://github.com/elyxlz/vesta/releases/latest/download/vesta-android.apk (an APK the phone installs directly, with no store listing; the browser asks once to allow the install) |
| Mac, Windows, Linux | the web app, App settings, "get the Vesta app" card, which offers the build that matches the gateway. All builds are also on https://github.com/elyxlz/vesta/releases/latest |

The Mac build needs Apple Silicon (M1 or newer). Linux ships a `.deb` (Ubuntu, Debian) and an `.rpm` (Fedora). No iPad, Apple Watch, or Intel Mac build exists.

## Connecting a device

An app connects with a **connect link**: `<gateway address>/app#k=<api key>`. The link carries the gateway's api key, the user's credential that opens every agent on it. You do not hold that key and cannot produce the link, so a new device gets it from one of these:

- **The host**: `vestad status` on the machine that runs the gateway prints the link and a QR code. Their one path when no device is connected.
- **A browser that is already connected**: the web app at `$VESTAD_PUBLIC_URL/app` works there with no link. That is enough to download the desktop app, but the link itself still comes from the host.

Then the user opens the link in a browser, pastes it on the connect screen of the desktop or mobile app, or scans the QR code with the mobile app.

The phone apps accept only a public HTTPS address. When `$VESTAD_TUNNEL` is unset the gateway has no such address, and the user runs `vestad connect` on the host first. The web and desktop apps also work on a LAN or localhost address.

Treat the link like a password: tell the user to keep it to themselves, and never ask them to paste it into a chat. Someone else who wants a vesta gets their own (the `onboard` skill), never this link.

## What each app can do

All four have chat, your dashboard, your logs, the notification feed, voice, agent settings, backups, and gateway updates. The differences:

- **Create an agent**: web and desktop only. The phone app sends the user to the web app for it.
- **Phone only**: push notifications, App Lock (biometrics), background location sharing, the QR scanner.
- **Web and desktop only**: keybinds, the list of your services, the microphone, dictation, and conversation voice cards.
- **Desktop only**: launch on startup, and its own updater (App settings, "updates"). The desktop app never updates on its own; the user starts it.

## Where things are

Two settings areas exist. **App settings** (the gear on the home screen) holds what belongs to the device and the gateway. **Agent settings** (inside an agent) holds what belongs to you.

| The user wants to | Where |
| --- | --- |
| Update the gateway, turn on automatic updates or beta releases | App settings, updates and gateway |
| Restart the gateway, read its logs, switch to another gateway, disconnect | App settings, gateway |
| See connected devices, share this device's location | App settings, devices (on the phone: Privacy) |
| Change push notification behavior | phone App settings, Notifications |
| Change your provider or model, sign in again | Agent settings, provider |
| Change voice providers and behavior | Agent settings, voice |
| Edit which notifications interrupt you | Agent settings, notifications |
| Read or edit your memory and constitution, see your skills | Agent settings, files |
| Give you a folder from the host machine | Agent settings, files, shared folders (phone: Host access) |
| Back up now, restore a backup, turn automatic backups on or off | Agent settings, backups |
| Rename, stop, start, restart, or delete you | Agent settings |

Several of these you can also do yourself when asked, and doing it beats sending the user to a screen: notification rules (`notifications` skill), voice (`voice`), your timezone (`timezone`), a gateway update (`vestad`), a restart (`restart`). Your personality has no screen after creation; the `personality` skill changes it. The constitution is the user's alone to edit.

## When this file is not enough

Screens change between releases. For a detail this file does not hold, read the app's source before you answer: `upstream gh api repos/elyxlz/vesta/contents/README.md -H "Accept: application/vnd.github.raw"` for install and setup, and `apps/web/src/components` or `apps/mobile/app` in the same repo for a screen. Say "let me check" over guessing a button name.
