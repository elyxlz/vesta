# vesta-cloud setup

Install the CLI once (editable, so it tracks live source under `~/agent`):

```bash
uv tool install --editable ~/agent/skills/vesta-cloud/cli
```

That puts the `vesta-cloud` command on `PATH`. If it is ever missing or stale, re-run
with `--force --reinstall`. There is nothing else to configure: no key and no account to
link, the CLI authenticates to the control plane on its own.
