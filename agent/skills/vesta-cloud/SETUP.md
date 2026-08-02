# vesta-cloud setup

Install the CLI once (editable, so it tracks live source under `~/agent`):

```bash
uv tool install --editable ~/agent/skills/vesta-cloud/cli
```

That puts the `vesta-cloud` command on `PATH`. If it is ever missing or stale, re-run
with `--force --reinstall`. There is no key to configure: for every call the CLI asks
this box's vestad to mint a short-lived server-identity token. A managed VM has its
account from provisioning; a self-hosted box links one with `vesta-cloud login` (see
SKILL.md).
