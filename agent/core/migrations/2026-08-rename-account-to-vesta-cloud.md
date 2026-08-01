The account skill's identity and command are now `vesta-cloud` (its directory, the
`name:` in its `SKILL.md`, and its CLI: `vesta-cloud whoami`, `vesta-cloud plan`, ...).
The referral code it stores (`~/.config/vesta/referral_code`, shared with `onboard`) is
untouched, so nothing you set up needs redoing.

### 1. Put the `vesta-cloud` command on PATH, drop the old one

```bash
uv tool install --editable ~/agent/skills/vesta-cloud/cli
uv tool uninstall vesta-cloud-account 2>/dev/null || true
```

The install is transactional and editable (the command runs from live source under
`~/agent`); the uninstall clears the old `vesta-cloud-account` launcher if you had it and
no-ops otherwise.

### 2. Drop the old `vesta-cloud-account` skill entry

```bash
~/agent/skills/skills-registry/scripts/skills-remove vesta-cloud-account
```

If it prints that `vesta-cloud-account` is not installed, you never had it and there is
nothing more to do here. If it errors because the old directory holds uncommitted local
changes, commit them (`git -C ~ add agent/skills && git -C ~ commit -m "checkpoint skill
edits"`) and run it again.
