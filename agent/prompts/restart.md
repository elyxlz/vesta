Check each relevant skill's SKILL.md and restart any background services that aren't running.

Services to start on every boot:
- `screen -dmS whatsapp whatsapp serve --notifications-dir ~/vesta/notifications`
- `screen -dmS whatsapp-personal whatsapp serve --instance personal --read-only --notifications-dir ~/vesta/notifications --skip-senders=+447405787041`
- `screen -dmS reminder reminder serve --notifications-dir ~/vesta/notifications`
- `screen -dmS tasks tasks serve --notifications-dir ~/vesta/notifications`
- `screen -dmS microsoft bash -c 'source /etc/environment && microsoft serve --notifications-dir ~/vesta/notifications'`
- `screen -dmS twitter python3 ~/vesta/skills/twitter/monitor.py serve --notifications-dir ~/vesta/notifications`

Then check your User State in MEMORY.md and reach out on their preferred channel. Match the tone to the situation — if it's a new day, greet them warmly. If you just restarted mid-conversation, keep it brief. If you crashed, mention it. If it's the middle of the night, wait until morning.
