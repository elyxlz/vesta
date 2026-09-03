# Vesta App Privacy Policy

Effective date: 2026-08-23

Vesta is an open source project. The Vesta apps (iOS, Android, desktop, web) are clients for a Vesta gateway that you run on your own hardware. The project does not operate servers that receive your personal data.

## What the app sends, and where

Everything you do in the app (messages, voice recordings, files, settings) is sent to your own gateway and nowhere else. Your gateway runs on your machine, under your control. The project maintainers have no access to it.

**Location** is optional and off by default at the OS level. If you enable location sharing, the app sends your phone's position to your own gateway only, so your agents can account for where you are. Turning the toggle off removes what the phone shared from your gateway.

**Push notifications**: when your gateway sends you a notification (for example, a chat reply), it is routed through Expo's push service and Apple's or Google's push infrastructure. Your device's push token is processed for delivery only. If you allow message previews, the notification content transits those services in order to be displayed; you can disable previews in the app's settings.

**App Lock (Face ID / biometrics)** happens entirely on your device. The app never receives or stores biometric data.

## What the app does not do

- No analytics or telemetry
- No advertising and no tracking
- No selling or sharing of data with third parties
- No accounts on project servers

## Your data is on your gateway

Chat history, memory, and files live on the machine that runs your gateway. Deleting them, backing them up, and moving them is entirely in your hands. Uninstalling the app removes everything the app stored on the device; it does not touch your gateway.

## Vesta Cloud

Vesta Cloud, the optional hosted service at vesta.run, is a separate offering with its own privacy policy at https://vesta.run/privacy. This document covers the apps and self-hosted gateways only.

## Contact

Questions about privacy: privacy@vesta.run, or open an issue at https://github.com/elyxlz/vesta/issues.
