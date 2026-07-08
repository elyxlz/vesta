"""Config knobs for the pooled-notification idle pass."""

from core.config import VestaConfig


def test_notif_pool_triage_config_defaults():
    config = VestaConfig()
    assert config.notif_pool_idle_grace_seconds == 30.0
