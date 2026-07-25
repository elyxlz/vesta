from agentmail_bridge.setup import _print_summary


def test_setup_summary_claims_a_bindable_public_port(capsys) -> None:
    _print_summary(
        {"email_address": "ada@example.com", "inbox_id": "inbox_1"},
        "https://example.test/webhook",
    )

    output = capsys.readouterr().out
    assert "register-service agentmail --public --claim" in output
    assert "curl -sk -X POST" not in output
