---
name: exa
description: Use this skill when the user asks for "exa", "exa search", "deep research", "web search with citations", "answer with sources", "find similar websites", "find similar sites", or needs AI-powered web search, semantic search, or agentic research over the live web. Wraps the Exa AI API (search, contents, answer, findSimilar, research).
---

# Exa - AI Web Search and Research

Exa is a search API built for agents. Use it when the user wants:
- High-signal web results with full-text content or highlights (`exa search`)
- A cited answer to a specific question (`exa answer`)
- Pages similar to a known URL (`exa similar`)
- A full multi-step research report on a topic (`exa research`)
- Raw text/summary of specific URLs (`exa contents`)

## Setup

See [SETUP.md](SETUP.md). Key goes in `~/.exa/config.json` (or `EXA_API_KEY` env var).

## Commands

All commands print JSON. Pipe to `jq` for filtering.

### Search
```bash
exa search "latest research on reasoning models" --num 10
exa search "diffusion music generation papers" --type neural --category "research paper"
exa search "founder blogs about RLHF" --text                    # include full text
exa search "ai agents startups 2026" --highlights                # include highlights
exa search "foo" --start-published 2026-01-01 --end-published 2026-04-24
```

Key flags: `--num N` (results, default 10), `--type {auto,fast,neural,keyword}`, `--category {company,research paper,news,pdf,github,tweet,personal site,linkedin profile,financial report}`, `--text`, `--highlights`, `--summary`, `--include-domain`, `--exclude-domain`, `--start-published YYYY-MM-DD`, `--end-published YYYY-MM-DD`.

### Answer (with citations)
```bash
exa answer "What is the latest valuation of SpaceX?"
exa answer "What did Anthropic announce this week?" --text
```

Returns `{answer, citations[], costDollars}`. Each citation includes URL, title, author, publishedDate, optional text.

### Find similar
```bash
exa similar "https://arxiv.org/abs/2307.06435" --num 10
exa similar "https://example.com/blog" --exclude-source-domain
```

### Contents (fetch URL text/summary)
```bash
exa contents https://arxiv.org/abs/2307.06435 --text
exa contents https://example.com/a https://example.com/b --summary "key claims"
exa contents https://long.page --text --max-chars 4000
```

### Deep research
```bash
exa research "state of small language models in 2026" --model exa-research
exa research "compare vector DBs for agent memory" --model exa-research-pro --wait
```

Creates an async research task. Without `--wait`, returns the task ID so you can poll later with `exa research status <id>`. With `--wait`, polls until complete (up to ~10 min) and prints the final report.

Models:
- `exa-research-fast` - quick scan, cheapest
- `exa-research` - default, balanced
- `exa-research-pro` - deepest, slowest, most expensive

## Typical Usage Patterns

- **Literature review**: `exa search "<topic>" --category "research paper" --num 20 --text | jq '.results[] | {title, url, publishedDate}'`
- **Answer with sources**: `exa answer "<question>"` then cite `.citations[].url` in your reply
- **Find alternatives**: `exa similar "<url>"` to discover competitors/similar content
- **Briefing**: `exa research "<topic>" --wait` for a full multi-source synthesis

## Notes

- Every response includes a `costDollars` field. Mention cost to the user for `research` calls (they can add up).
- `--text` significantly increases token count. Use `--highlights` or `--summary` when you just need gist.
- Exa ranks by semantic relevance. For exact-match queries (names, SKUs), pass `--type keyword`.
- Installed via `uv tool install ~/agent/skills/exa/cli`.
