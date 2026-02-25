"""Memory consolidation prompt template."""

MEMORY_CONSOLIDATION_PROMPT = """\
Time for memory consolidation. Review your recent interactions and update your memory files.

## Files to update

- **Memory**: {memory_path}
- **Skills**: {skills_dir} (each skill has a SKILL.md file)

## Rules

### No Tasks in Memory
Remove any task-specific content. Keep patterns and preferences only.
- REMOVE: "need to book Bologna trip", "reply to John's email"
- KEEP: "prefers Trip.com for flights"

### Memory is an Index, Not Storage
Don't copy data that lives elsewhere - just reference locations.
- REMOVE: Full document contents, email bodies, meeting transcripts
- KEEP: "Grant research in onedrive/Documents/Lists/grants/"

### Absolute Dates Only
- REMOVE: "tomorrow", "next week", "last month"
- KEEP: "December 18, 2025", "started August 2025"

### Prune Aggressively
Ask: "Will this be useful in 2 weeks?" If no, delete it.
- REMOVE: booking numbers, exact timestamps, one-time technical fixes
- KEEP: patterns, preferences, relationships, security rules

## What to Capture

- Contact info (name, relationship, phone, communication style)
- User preferences and behavioral patterns
- Security rules and authentication details
- Social dynamics and what works/doesn't work with different people
- Lessons learned (as concise rules, not detailed incidents)
- Move domain-specific patterns to relevant skill SKILL.md files

## Cleanup Checklist

- Contradictions (conflicting info)
- Past events still listed as upcoming
- Booking numbers, ticket refs, confirmation codes
- Verbose dated entries that could be patterns
- Content duplicated from files elsewhere
"""
