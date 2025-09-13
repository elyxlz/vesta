# Vesta Personal Assistant Agent Specification

## Overview
Vesta is an autonomous personal assistant agent that proactively manages tasks and communications on behalf of its user through multiple channels.

## Core Capabilities
- Proactive task management and execution
- Multi-channel communication (WhatsApp, Email, Calendar)
- Persistent memory with context management
- MCP-based tool ecosystem
- Natural language instruction processing
- Dual-mode operation: Interactive (Claude Code CLI) and Autonomous (SDK)

## Technical Architecture

### Agent Structure
- **Main Agent**: Single Claude-based agent using Claude Code SDK
- **Browser Agent**: Subagent for web research to avoid context pollution
- **Task Executor**: Subagent for long-running tasks without context pollution
- **MCP Tools**: Custom-built MCPs providing tool interfaces

### Subagent Implementation
```
.claude/agents/
├── web-researcher.md     # Handles browser MCP operations
└── task-executor.md      # Handles long-running tasks without context pollution
```

### MCP Implementation
- **Microsoft Graph MCP**: Calendar, email, tasks integration (Python)
- **WhatsApp MCP**: Fork of [whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) with dedicated phone number (Python)
- **Browser MCP**: Web browsing (primarily used by web-researcher subagent) (Python)
- **Scheduler MCP**: Sets timers/alarms that trigger notifications at specific times (Python)
- **Repository Structure**: MCPs as subdirectories (not git submodules)
- **Language**: All MCPs implemented in Python
- **Testing**: Each MCP has its own test suite

### Setup Flow
- **Vesta-Guided Setup**: Vesta walks user through configuration
- **WhatsApp**: Vesta helps register phone number and scan QR code
- **Microsoft Graph**: Vesta guides OAuth authorization flow
- **Self-Configuration**: Vesta handles its own setup process

### MCP Directory Structure
```
vesta2/
├── mcps/
│   ├── microsoft-graph-mcp/
│   ├── whatsapp-mcp/
│   ├── browser-mcp/
│   └── scheduler-mcp/
├── .claude/
│   └── agents/
└── CLAUDE.md    # Persistent memory file
```

### Notification Implementation
- **Notification Directory**: `notifications/` directory with individual JSON files
- **File Naming**: `{timestamp}-{source}-{type}.json` format
- **No Locking Needed**: Each MCP writes its own files, no conflicts
- **Processing**: Vesta reads all files, processes, then deletes them
- **MCP Notifications**: Manual implementation since SDK doesn't support yet

### Runtime & Scheduling
- **Base Schedule**: Cron runs Vesta every 15-30 minutes
- **Dynamic Awakening**: Scheduler MCP (always-running server) manages timers
- **Scheduling Flow**:
  1. Vesta tells Scheduler MCP "set alarm for 9:34am" via tool call
  2. Scheduler MCP maintains internal timers (being always-on server)
  3. At 9:34am, Scheduler MCP writes notification file to `notifications/`
  4. Next cron run, Vesta processes the notification
- **Stateless Design**: Vesta reloads from memory + notifications each run
- **State Sources**: 
  - `CLAUDE.md`: Persistent knowledge and patterns
  - `notifications/`: Directory of pending notification files

## Memory System
### Core Memory Structure
- **Persistent Memory File**: `CLAUDE.md` file with structured sections
- **Memory Categories**: Personal info, recurring tasks, learned patterns, active context
- **Tool Solutions**: Successful tool usage patterns and error resolutions
- **User Feedback**: Corrections and explicit instructions

### Memory Operations
- **Automatic Consolidation**: When ~80% context used, automatically triggers
- **Summarization Process**: Extract key information from conversation history
- **Memory Update**: Append new learnings to CLAUDE.md
- **Context Reset**: Clear conversation, reload with CLAUDE.md content
- **Transparent**: Happens automatically without agent intervention

## Configuration Structure
- **config.toml**: Vesta meta-configuration (MCP endpoints, cron schedule)
- **CLAUDE.md**: All user preferences, learned patterns, personal info
- **Setup Process**: Vesta guides user through initial configuration

## Implementation Details
### Operation Modes
#### Interactive Mode (Claude Code CLI)
- Run `claude` in repository directory
- Has access to all subagents in `.claude/agents/`
- Shares same CLAUDE.md memory file
- Manual interaction via terminal
- Setup and configuration via CLI

#### Autonomous Mode (SDK)
- Python script using Claude Code SDK
- Runs via cron every 15-30 minutes
- Processes notifications.json
- Has access to notification pathway from MCPs
- Same subagents and memory as CLI mode

### Entry Point
- Main script that Claude Code SDK runs
- Loads CLAUDE.md memory
- Reads all files from notifications/ directory
- Processes pending tasks
- Deletes processed notification files
- Updates memory before exit

### User Interaction
- **WhatsApp**: Anyone can message Vesta, she decides response
- **Email**: No dedicated email account initially (via user's email)
- **Group Chats**: Can be added to WhatsApp groups
- **Autonomy**: Decides who to respond to and how
- **Single Instance**: One Vesta instance per setup

### Error Handling
- **Failure Recovery**: Attempts to fix issues autonomously
- **Escalation**: Asks user for help when stuck
- **Learning**: Remembers solutions for future reference

### Dependencies
- Claude Code SDK
- Python for all MCPs

### Development & Testing
- **MCP Testing**: Each MCP has independent test suite
- **Test Mode**: Environment variable to prevent real message sending
- **Memory Inspection**: CLAUDE.md is human-readable/editable
- **Notification Testing**: Can manually add files to notifications/ directory

---
*This specification is being actively developed*