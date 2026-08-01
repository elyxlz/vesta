# notifications setup

Install the CLI once (editable, so it tracks live source under `~/agent`):

```bash
uv tool install --editable ~/agent/skills/notifications/cli
```

That puts the `notifications` command on `PATH`. If it is ever missing or stale, re-run
with `--force --reinstall`.
