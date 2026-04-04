# ChatGPT Skill

This skill should be used when the user asks to "ask chatgpt", "ask openai", "ask gpt", "what does chatgpt think", "compare with chatgpt", or wants to query OpenAI's models for a second opinion, comparison, or any task.

## Usage

```bash
chatgpt ask "your question here"
chatgpt ask --model gpt-4o "your question here"
chatgpt ask --system "you are a poet" "write a haiku about sardinia"
```

## How it works

- Calls the OpenAI Chat Completions API
- Default model: `gpt-5.4` (standard)
- Supports custom system prompts via `--system`
- API key stored in environment as `OPENAI_API_KEY`
- No external dependencies — uses stdlib `urllib` only

## When to use

- User explicitly asks to query ChatGPT/OpenAI
- User wants a second opinion or comparison between Claude and GPT
- User asks to delegate a specific task to OpenAI

## Setup

Set the `OPENAI_API_KEY` environment variable:

```bash
echo 'OPENAI_API_KEY=sk-...' >> /etc/environment
source /etc/environment
```

## Notes

- Always show the response to the user — don't summarize unless asked
- If the query is conversational, keep the system prompt minimal
- For code or technical questions, let GPT use its defaults
- Supports both legacy models (gpt-4o, gpt-4-turbo) and newer models (gpt-5.x, o-series) with appropriate parameter handling
