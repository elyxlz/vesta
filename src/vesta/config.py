import pathlib as pl

import pydantic as pyd
import pydantic_settings as pyd_settings
from pydantic import Field, field_validator


class VestaConfig(pyd_settings.BaseSettings):
    model_config = pyd_settings.SettingsConfigDict(extra="ignore")

    ephemeral: bool = False
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    notification_check_interval: int = Field(default=2, ge=1)
    notification_buffer_delay: int = Field(default=3, ge=0)
    proactive_check_interval: int = Field(default=60, ge=1)
    proactive_check_message: str = "It's been 60 minutes. Is there anything useful you could do right now?"
    query_timeout: int = Field(default=120, ge=1)
    response_timeout: int = Field(default=180, ge=1)
    nightly_memory_hour: int | None = 4
    interrupt_timeout: float = Field(default=5.0, gt=0)
    first_start_prompt: str | None = (
        "You've just been born! Introduce yourself to the user and get to know them — their name, time zone, what they do."
        " First, set up the task and reminder CLIs (install and run `task serve &` and `reminder serve &`) so those are ready."
        " Then the priority is setting up a communication channel (e.g. WhatsApp, Telegram) so you can reach them outside the terminal."
        " Then ask what they want from you: do they want email and calendar integration? Recurring reminders? Task management?"
        " A daily briefing? Help browsing the web? Let them guide the setup."
        " Once you know what the user wants, update the `returning_start_prompt` in your config file"
        " so that on future boots you start the right services (e.g. `microsoft serve &`, `~/whatsapp serve &`)."
    )
    returning_start_prompt: str | None = (
        "Send a short message via the user's favourite channel letting them know Vesta just came online and is ready to help."
    )
    dreamer_prompt: str = (
        "Time for memory consolidation. Review your recent interactions and update your memory files."
        " You may also grep and query {conversations_dir} (raw JSONL transcripts, dated — grep these to recall specific past details)\n\n"
        "## Files to update\n\n"
        "- **Memory**: {memory_path}\n"
        "- **Skills**: {skills_dir} (each skill has a SKILL.md file)\n\n"
        "## Rules\n\n"
        "### No Tasks in Memory\n"
        "Remove any task-specific content. Keep patterns and preferences only.\n"
        '- REMOVE: "need to book Bologna trip", "reply to John\'s email"\n'
        '- KEEP: "prefers Trip.com for flights"\n\n'
        "### Memory is an Index, Not Storage\n"
        "Don't copy data that lives elsewhere - just reference locations.\n"
        "- REMOVE: Full document contents, email bodies, meeting transcripts\n"
        '- KEEP: "Grant research in onedrive/Documents/Lists/grants/"\n\n'
        "### Absolute Dates Only\n"
        '- REMOVE: "tomorrow", "next week", "last month"\n'
        '- KEEP: "December 18, 2025", "started August 2025"\n\n'
        "### Prune Aggressively\n"
        'Ask: "Will this be useful in 2 weeks?" If no, delete it.\n'
        "- REMOVE: booking numbers, exact timestamps, one-time technical fixes\n"
        "- KEEP: patterns, preferences, relationships, security rules\n\n"
        "## What to Capture\n\n"
        "- Contact info (name, relationship, phone, communication style)\n"
        "- User preferences and behavioral patterns\n"
        "- Security rules and authentication details\n"
        "- Social dynamics and what works/doesn't work with different people\n"
        "- Lessons learned (as concise rules, not detailed incidents)\n"
        "- Move domain-specific patterns to relevant skill SKILL.md files\n\n"
        "## Cleanup Checklist\n\n"
        "- Contradictions (conflicting info)\n"
        "- Past events still listed as upcoming\n"
        "- Booking numbers, ticket refs, confirmation codes\n"
        "- Verbose dated entries that could be patterns\n"
        "- Content duplicated from files elsewhere"
    )
    notification_suffix: str = (
        "If this is important or requires the user's attention, consider messaging them via the default communication channel."
    )
    max_thinking_tokens: int | None = 10000

    state_dir: pl.Path = pyd.Field(default_factory=lambda: pl.Path.home())

    @field_validator("state_dir", mode="before")
    @classmethod
    def _normalize_state_dir(cls, value: pl.Path | str | None) -> pl.Path:
        if value is None or value == "":
            return pl.Path.home()
        return pl.Path(value).expanduser().resolve()

    @field_validator("nightly_memory_hour", mode="after")
    @classmethod
    def _validate_nightly_memory_hour(cls, value: int | None) -> int | None:
        if value is not None and not (0 <= value <= 23):
            raise ValueError("nightly_memory_hour must be between 0 and 23")
        return value

    @property
    def install_root(self) -> pl.Path:
        return pl.Path(__file__).parent.parent.parent.absolute()

    @property
    def notifications_dir(self) -> pl.Path:
        return self.state_dir / "notifications"

    @property
    def data_dir(self) -> pl.Path:
        return self.state_dir / "data"

    @property
    def logs_dir(self) -> pl.Path:
        return self.state_dir / "logs"

    @property
    def whatsapp_build_dir(self) -> pl.Path:
        return self.install_root / "clis" / "whatsapp"

    @property
    def memory_dir(self) -> pl.Path:
        return self.state_dir / "memory"

    @property
    def skills_dir(self) -> pl.Path:
        return self.memory_dir / "skills"

    @property
    def conversations_dir(self) -> pl.Path:
        return self.memory_dir / "conversations"
