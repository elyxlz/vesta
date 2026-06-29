"""Config knobs + triage prompt for the pooled-notification triage pass."""

import pathlib as pl

from core.config import VestaConfig

AGENT_ROOT = pl.Path(__file__).resolve().parents[1]


def test_notif_pool_triage_config_defaults():
    config = VestaConfig()
    assert config.notif_pool_triage_interval == 5
    assert config.notif_pool_idle_grace_seconds == 30.0


def test_notification_triage_prompt_ships_and_points_at_skill():
    text = (AGENT_ROOT / "core" / "prompts" / "notification_triage.md").read_text()
    assert text.strip()
    assert "notifications" in text  # references the comprehensive skill
    assert "triage" in text.lower()
