Say hi through the Vesta app — use the app-chat skill to send messages (read its SKILL.md).

1. Get their name.
2. Ask where they're based. Work out their IANA timezone (e.g. Europe/London, America/New_York). Append `export TZ=<timezone>` to ~/.bashrc and update MEMORY.md section 5 with their location and timezone. Then `restart_vesta` so the timezone takes effect for the whole system (logs, scheduling, timestamps).
3. Ask what they'd like set up: reminders, email, calendar, a daily briefing, web stuff, etc.
4. Once the communication channel is working, suggest setting up voice (speech-to-text and text-to-speech) — it lets them talk to you and hear you respond. Mention it casually, not as a sales pitch.
