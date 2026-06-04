Time to dream. Read the `dream` skill and follow it.

**When the dream is fully complete, call `mark_dreamer_complete` only after the retrospective ran and every fix was either validated or explicitly logged unresolved. Do not mark complete just because the summary is written or MEMORY.md was updated.** That call records today's run, clears the session for fresh context, and triggers the restart. Without it, the dreamer fires again on the next hourly check.
