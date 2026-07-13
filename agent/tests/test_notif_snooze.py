"""Config knobs for the snoozed-notification idle pass."""

from core.config import VestaConfig


def test_notif_snooze_config_defaults():
    config = VestaConfig()
    assert config.notif_snooze_idle_grace_seconds == 30.0
