"""The behaviors: values that change how a session acts, the same for every provider.

They use the settings schema format of the providers, so the one check and the app's settings
card serve both.
"""

from voice.settings import Domain, SettingDef

BEHAVIOR_SCHEMA: list[SettingDef] = [
    {
        "key": "barge_in",
        "type": "bool",
        "label": "interrupt by voice",
        "description": "talk over a spoken reply to stop it; when off, a reply plays to its end or until you stop it on the device",
        "default": True,
    },
]


def barge_in_allowed(stored: Domain, session_can: bool | None) -> bool:
    """Barge-in has two inputs: the stored behavior is what the user wants, and `session_can` is
    what this session states it can do (None when it states nothing). Both must allow it."""
    wanted = stored["barge_in"] if "barge_in" in stored else True
    return wanted is not False and session_can is not False
