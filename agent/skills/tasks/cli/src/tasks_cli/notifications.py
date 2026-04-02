"""Notification writing for the unified tasks+reminders system.

All notification helpers live in scheduler.py (write_reminder_notification,
write_task_due_notification). This module re-exports them for backward
compatibility and provides the legacy write_notification alias.
"""

from .scheduler import write_reminder_notification, write_task_due_notification

# Legacy alias used by old code paths
write_notification = write_task_due_notification

__all__ = [
    "write_notification",
    "write_reminder_notification",
    "write_task_due_notification",
]
