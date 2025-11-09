"""Centralized constants for Vesta."""

# Color codes for terminal output (dict for backward compatibility)
Colors = {
    "dim": "\033[2m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "yellow": "\033[93m",
    "green": "\033[92m",
    "red": "\033[91m",
    "reset": "\033[0m",
}


class Emoji:
    TOOL = "🔧"
    ROBOT = "🤖"
    MEMO = "📝"
    WARNING = "⚠️"
    SUCCESS = "✅"
    FIRE = "🔥"
    SLEEP = "💤"
    LIGHTNING = "⚡"
    CLOCK = "⏰"
    CHART = "📊"
    MOON = "🌙"
    EXPLOSION = "💥"
    WEB = "🌐"
    PHONE = "📱"
    EMAIL = "📧"
    CALENDAR = "📅"
    BELL = "🔔"
    CHECKBOX = "☑️"


class Senders:
    USER = "You"
    ASSISTANT = "Vesta"
    SYSTEM = "System"


class Messages:
    SHUTDOWN_INITIATED = f"{Emoji.SLEEP} vesta is tired and taking a nap to help remember stuff..."
    SHUTDOWN_COMPLETE = "sweet dreams!"
    FORCE_SHUTDOWN = f"{Emoji.LIGHTNING} Force shutdown!"
    INTERRUPTING_TASK = f"{Emoji.WARNING} Interrupting current task..."
    PROACTIVE_CHECK = f"{Emoji.CHART} Running 60-minute check..."
    NIGHTLY_MEMORY = f"{Emoji.MOON} Running nightly memory consolidation..."
    MEMORY_UPDATED = f"{Emoji.MEMO} Memory updated:"


class Formats:
    TIMESTAMP = "%I:%M %p"
    BOX_TOP = "╔" + "═" * 58 + "╗"
    BOX_MIDDLE_LEFT = "║"
    BOX_MIDDLE_RIGHT = "║"
    BOX_BOTTOM = "╚" + "═" * 58 + "╝"
