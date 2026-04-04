---
name: app-chat
description: Use this skill when the user sends a message through the Vesta app or CLI. This is the primary channel for direct conversation with the user.
---

# AppChat — Tool: app_chat_reply

The Vesta app (desktop/mobile/browser) and CLI connect via AppChat. User messages arrive as the normal user prompt. **You must reply using `app_chat_reply`** — your direct assistant text is not shown in the chat.

## Sending Messages

```
app_chat_reply({ "message": "hey, what's up" })
```

- Call `app_chat_reply` once per message
- Send multiple short messages instead of one long one (like texting)
- Follow the communication style in MEMORY.md (lowercase, no bullet points, no newlines within a message)

## When to Use

- Every time you want to say something to the user in the app
- For follow-up questions, confirmations, status updates
- When delivering results from tasks or research

## When NOT to Use

- When sending messages through other channels (WhatsApp, Telegram) — use those skills instead
- For internal processing — just think and use tools normally, the user sees a "thinking" indicator
