# Susan Calvin — Robopsychology Skill

Named after Isaac Asimov's robopsychologist from *I, Robot*. Performs comprehensive self-analysis of okami by packaging real operational data and submitting it to GPT-5.4 for independent evaluation.

## When to use

- When the user asks for self-analysis, memory review, or "robopsychology"
- Periodically (e.g., weekly) for ongoing self-improvement
- After significant failures or behavioral corrections
- When the user says "susan calvin", "analyze yourself", "self-review", "robopsych"

## What it collects (11 data sources)

1. **MEMORY.md** — full persistent memory (credentials stripped)
2. **CLAUDE.md** — system instructions that shape behavior
3. **Dreamer outputs** — last 2 nightly curation reports
4. **Conversation history** — last 50 exchanges from SQLite
5. **Failure patterns** — extracted from learned patterns section
6. **Core architecture** — source file structure and function signatures
7. **Skills inventory** — all skills with sizes and descriptions
8. **Security surface** — env var names, open ports, running daemons, file permissions
9. **Dependencies** — pyproject.toml + installed packages
10. **Error logs** — recent errors/warnings from vesta.log
11. **Resource usage** — disk, memory, GPU/VRAM, DB size, notification backlog

## Usage

```bash
susan-calvin analyze              # full analysis (all 11 sources)
susan-calvin analyze --brief      # shorter, focused analysis
susan-calvin analyze --deep       # include full source code (real code review)
```

## Dependencies

- OpenAI API key in `/etc/environment` (OPENAI_API_KEY)
- chatgpt skill (for API access)
