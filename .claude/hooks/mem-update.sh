#!/bin/bash

# PreCompact hook that reminds to update memory before compacting

cat << 'EOF'
Before compacting, please review the conversation and update CLAUDE.md with any important information:

1. New facts about Elio (personal details, preferences, relationships)
2. Tasks completed or new tasks added
3. Important decisions or events from today
4. Technical learnings or workarounds discovered
5. Behavioral corrections or communication preferences

Use the /mem command after this to trigger a full memory update if needed.
EOF

# Exit successfully
exit 0