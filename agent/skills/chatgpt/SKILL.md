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
- Default model: `gpt-4o` (latest auto)
- Supports custom system prompts via `--system`
- API key stored in `/etc/environment` as `OPENAI_API_KEY`

## When to use

- User explicitly asks to query ChatGPT/OpenAI
- User wants a second opinion or comparison between Claude and GPT
- User asks okami to delegate a specific task to OpenAI

## Notes

- Always show the response to the user — don't summarize unless asked
- If the query is conversational, keep the system prompt minimal
- For code or technical questions, let GPT use its defaults
