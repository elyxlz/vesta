The account skill's identity and command are now `vesta-cloud` (its directory, the
`name:` in its `SKILL.md`, and its CLI: `vesta-cloud whoami`, `vesta-cloud plan`, ...).
The referral code it stores (`~/.config/vesta/referral_code`, shared with `onboard`) is
untouched, so nothing you set up needs redoing.

`vesta-cloud` is a default skill, so if it is missing your box installs it automatically
on boot (the default-skill sync turn). This migration only clears the old
`vesta-cloud-account` entry from your installed set so its stale `vesta-cloud-account`
launcher does not linger on `PATH`. Safe to run more than once: it no-ops if you never
had `vesta-cloud-account` installed.

### Drop the old `vesta-cloud-account` skill

```bash
~/agent/skills/skills-registry/scripts/skills-remove vesta-cloud-account
```

If it prints that `vesta-cloud-account` is not installed, you never had it and there is
nothing to do. If it errors because the old directory holds uncommitted local changes,
commit them (`git -C ~ add agent/skills && git -C ~ commit -m "checkpoint skill edits"`)
and run it again.
