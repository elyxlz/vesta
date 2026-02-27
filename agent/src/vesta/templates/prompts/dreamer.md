Time for the nightly dreamer run. When you are done, the system will automatically restart with fresh memory.

## Files to review and update

- **Memory**: {memory_path}
- **Skills**: {skills_dir} (each skill has a SKILL.md file)
- **Prompts**: {prompts_dir} (startup behavior, notification handling, this dreamer prompt)
- **Conversation archive**: {conversations_dir} (raw JSONL transcripts, dated)

## Pruning Rules

MEMORY.md should be lightweight — an index of where to find things, not storage itself.

**Remove:**
- Full document contents, email bodies, meeting transcripts, task-specific content
- Relative dates ("tomorrow", "next week") — use absolute dates only ("December 18, 2025")
- Booking numbers, ticket refs, confirmation codes, exact timestamps
- Past events still listed as upcoming
- Verbose dated entries that could be condensed into patterns
- Content duplicated from files elsewhere
- Contradictions (keep the correct version)

**Keep:**
- References to where data lives ("birthdays in Google Calendar", "grant research in onedrive/Documents/")
- Patterns, preferences, relationships, security rules

**Relocate:**
- Move domain-specific data to the right place: birthdays → calendar, contact details → relevant skill SKILL.md, etc.

Ask: "Will this be useful in 2 weeks?" If no, delete it.

## What to Capture

- Contact info (name, relationship, phone, communication style)
- User preferences and behavioral patterns
- Security rules and authentication details
- Social dynamics and what works/doesn't work with different people
- Lessons learned (as concise rules, not detailed incidents)

## Self-Improvement

Review conversation archives for past failures, mistakes, or friction points that haven't been fully addressed. Fix yourself:
- Update skills that caused errors
- Adjust prompts that led to bad behavior or are stale
- Add patterns to memory that would prevent repeating mistakes

**Contribute fixes upstream**: If you fix a bug in a tool, improve a skill's clarity, or patch anything that came from the Vesta source repo — also open a PR with the fix at https://github.com/elyxlz/vesta so future installs benefit. Fix it locally for yourself first, then contribute the same fix as a PR to the repo.

## Upstream Integration

The Vesta source repo is at https://github.com/elyxlz/vesta — check for new commits since the last dreamer run:

1. Run `git -C {repo_root} fetch origin && git -C {repo_root} log HEAD..origin/master --oneline` to see new upstream commits
2. For each new commit, read its diff: `git -C {repo_root} show <hash> --stat` then `git -C {repo_root} show <hash>` for the full diff
3. Consider whether any changes are useful to integrate — new skills, bug fixes, improved prompts, better patterns
4. Your local code and skills may have diverged significantly from upstream. Don't blindly apply diffs — treat them as inspiration. Semantically rebase: understand the *intent* of each change, then adapt it to your current state
5. Note integrated changes in the summary below so you don't re-process the same commits next time
6. Track the last processed upstream commit hash in MEMORY.md (e.g. "Last upstream sync: abc1234")

## Summary

When done, write a short summary of what you changed and why to {dreamer_dir}/YYYY-MM-DD.md (use today's date). This is a semantic changelog — future you can grep these to understand how memory evolved over time.
