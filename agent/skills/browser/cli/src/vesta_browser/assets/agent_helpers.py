"""Loaded by Browser Harness into every program's globals from the session's agent workspace.

The browser runs headed on its own display, and Chromium drops input aimed at a tab that is not
the visible one, so a tab this program opens is brought to the front as part of opening it.
"""

import browser_harness.helpers as _helpers

_open_in_background = _helpers.new_tab


def new_tab(url="about:blank"):
    target_id = _open_in_background(url)
    _helpers.activate_tab(target_id)
    return target_id
