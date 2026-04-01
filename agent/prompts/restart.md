Check each relevant skill's SKILL.md and restart any background services that aren't running.

Services to start on every boot:
- `screen -dmS whatsapp whatsapp serve --notifications-dir ~/vesta/notifications`
- `screen -dmS whatsapp-personal whatsapp serve --instance personal --read-only --notifications-dir ~/vesta/notifications --skip-senders=+447405787041`
- `screen -dmS reminder reminder serve --notifications-dir ~/vesta/notifications`
- `screen -dmS tasks tasks serve --notifications-dir ~/vesta/notifications`
- `screen -dmS microsoft bash -c 'source /etc/environment && microsoft serve --notifications-dir ~/vesta/notifications'`
- `screen -dmS twitter python3 ~/vesta/skills/twitter/monitor.py serve --notifications-dir ~/vesta/notifications`
- `screen -dmS backup bash /root/vesta/scripts/backup-daemon.sh`
- `screen -dmS ups-monitor python3 ~/vesta/skills/ups/monitor.py`
- `screen -dmS tts-server bash -c 'PIP_BREAK_SYSTEM_PACKAGES=1 /usr/bin/python3 /usr/local/bin/tts-server'`
- `screen -dmS webapp python3 /root/vesta/webapp/serve.py`

Then check your User State in MEMORY.md and reach out on their preferred channel. Match the tone to the situation — if it's a new day, greet them warmly. If you just restarted mid-conversation, keep it brief. If you crashed, mention it. If it's the middle of the night, wait until morning.
