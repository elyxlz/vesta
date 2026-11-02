from reminders_cli.commands import cron_dom_step_warning


def test_dom_step_warns():
    assert cron_dom_step_warning("30 10 */2 * *") is not None
    assert cron_dom_step_warning("0 9 1-31/3 * *") is not None


def test_plain_and_step_one_do_not_warn():
    assert cron_dom_step_warning("0 9 * * 1-5") is None
    assert cron_dom_step_warning("0 9 1,15 * *") is None
    assert cron_dom_step_warning("0 9 */1 * *") is None
    assert cron_dom_step_warning("*/15 * * * *") is None  # minute step, not day-of-month
    assert cron_dom_step_warning("bad") is None
