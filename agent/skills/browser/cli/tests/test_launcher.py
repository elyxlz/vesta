from vesta_browser import launcher


def test_stealth_args_count():
    # If this drops, Scrapling's defense posture probably weakened — investigate.
    assert len(launcher.STEALTH_ARGS) >= 50


def test_harmful_args_removed_in_stealth_mode_concept():
    # The stealth-mode arg filter drops args that leak automation signals.
    assert "--enable-automation" in launcher.HARMFUL_ARGS
    assert "--disable-popup-blocking" in launcher.HARMFUL_ARGS


def test_find_free_port_returns_int_in_range():
    port = launcher.find_free_port(start=38000, end=38050)
    assert 38000 <= port < 38050


def test_port_free_false_for_bound_port():
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        assert launcher._port_free(port) is False
    finally:
        s.close()


def test_is_cdp_reachable_false_when_nothing_listens():
    assert launcher.is_cdp_reachable(1, timeout_s=0.1) is False
