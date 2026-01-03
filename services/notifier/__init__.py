"""
Notifier module - Multi-channel notifications
"""

from .discord import send_discord_notification

__all__ = ["send_discord_notification"]
