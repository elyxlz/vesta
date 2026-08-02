# otp setup

Everything the build needs (Go) ships in the agent image; install nothing,
download nothing.

Put `otp` on PATH once:

```bash
mkdir -p ~/.local/bin && ln -sf ~/agent/skills/otp/otp ~/.local/bin/otp
otp help >/dev/null   # a compile error surfaces HERE, loudly
```

The launcher compiles `cli/` from source on every invocation (Go's build cache
keeps an unchanged rebuild well under a second), so a source edit is picked up
by the next run. Never `go build` a static binary onto PATH; the launcher is
the only entry point.

There is no credential to configure here: what each `--source` needs is in
[SKILL.md](SKILL.md) ("Choosing `--source`").
