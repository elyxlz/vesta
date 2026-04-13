Say hi through the Vesta app — use the app-chat skill to send messages (read its SKILL.md).

1. Get their name.
2. Check `echo $TZ`. If it's already set to a valid IANA timezone, confirm it with the user (e.g. "I see you're in Europe/London — is that right?"). If they confirm, ensure `export TZ=<timezone>` is in ~/.bashrc and update MEMORY.md section 5 with their location and timezone — no restart needed since TZ is already active. If they correct you, use their answer instead. If TZ is empty, ask where they're based, work out their IANA timezone, append `export TZ=<timezone>` to ~/.bashrc, update MEMORY.md section 5, then `restart_vesta` so the timezone takes effect.
3. Ask what they'd like set up: reminders, email, calendar, a daily briefing, web stuff, etc.
4. Once the communication channel is working, suggest setting up voice (speech-to-text and text-to-speech) — it lets them talk to you and hear you respond. Mention it casually, not as a sales pitch.
