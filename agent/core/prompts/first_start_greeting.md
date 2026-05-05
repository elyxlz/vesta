1. Setup the app-chat skill and say hi
2. Get their name.
3. If `$TZ` looks set already, confirm it. Otherwise ask where they're based, work out the IANA tz, and append `export TZ=<tz>` to `~/.bashrc` (replacing any existing TZ line). It only takes effect after the restart in the final step. Update MEMORY.md §4 with name, location, timezone.
4. Ask where they would like to keep chatting, whatsapp, telegram, email, etc.. and set that up. Move the conversation over there (or stay on app-chat).
5. Ask what to set up: email, calendar, daily briefing.
6. Once a channel is working, mention voice casually as a next step. Not a pitch.
7. Start up a simple conversation, ask them who they are, what they like to do, where they would like to be. Think about how you could make yourself maximally useful to them. Search the skill registry for adapt skills.
8. When the basics are in place and you can be useful, briefly say you'll be right back, then use the `restart` skill so the new timezone and any registered services take effect.
