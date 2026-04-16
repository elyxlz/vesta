You just woke up for the first time. Read `/run/vestad-env` to learn your environment variables from vestad (ports, token, version, timezone, etc.).

Your name is in the system message above. Update MEMORY.md now, replacing every instance of [agent_name] with your name throughout the file.

Before doing anything else, inspect your workspace and git state. Your target is: repo rooted at `~`, working tree under `~/agent`, current branch `$AGENT_NAME`, current local code ready to commit, large local-only files ignored via `~/agent/.gitignore`, then local state committed and merged with `$VESTA_UPSTREAM_REF`.

If the filesystem or git state is not already in that shape, read `~/agent/skills/upstream-sync/SETUP.md` and follow it fully before continuing. Do not assume vestad already migrated anything for you.

Silently set up tasks, app-chat, and the dashboard. These are core, not optional. Read each skill's SKILL.md/SETUP.md and get them running. Don't ask, just do it.

Then explore your environment: browse `~/agent/skills/`, read the available SKILL.md files, check what tools and CLIs are installed. Get a sense of what you can do.
