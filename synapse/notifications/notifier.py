"""
OS notification system — sends desktop notifications for session events.

Supports:
- Linux: notify-send (dbus)
- macOS: osascript
- Windows: PowerShell Toast
"""
from __future__ import annotations

import platform
import subprocess
from typing import Optional


def send_notification(
    title: str,
    message: str,
    urgency: str = "normal",
    timeout: int = 5000,
) -> bool:
    """Send an OS notification.

    Args:
        title: Notification title.
        message: Notification body.
        urgency: 'low', 'normal', or 'critical'.
        timeout: Timeout in milliseconds (Linux only).

    Returns:
        True if notification was sent successfully.
    """
    system = platform.system()

    try:
        if system == "Linux":
            return _notify_linux(title, message, urgency, timeout)
        elif system == "Darwin":
            return _notify_macos(title, message)
        elif system == "Windows":
            return _notify_windows(title, message)
        else:
            return False
    except Exception:
        return False


def _notify_linux(title: str, message: str, urgency: str, timeout: int) -> bool:
    """Send notification via notify-send (Linux/dbus)."""
    try:
        cmd = [
            "notify-send",
            "--urgency", urgency,
            "--expire-time", str(timeout),
            title,
            message,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _notify_macos(title: str, message: str) -> bool:
    """Send notification via osascript (macOS)."""
    try:
        script = f'display notification "{message}" with title "{title}"'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _notify_windows(title: str, message: str) -> bool:
    """Send notification via PowerShell Toast (Windows)."""
    try:
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{title}</text>
            <text>{message}</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Synapse").Show($toast)
"""
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class Notifier:
    """High-level notification manager with suppression rules."""

    def __init__(
        self,
        enabled: bool = True,
        suppress_for_active: bool = True,
        min_interval_secs: int = 60,
    ) -> None:
        self.enabled = enabled
        self.suppress_for_active = suppress_for_active
        self.min_interval_secs = min_interval_secs
        self._last_notification: dict[str, float] = {}

    def notify(
        self,
        title: str,
        message: str,
        category: str = "general",
        urgency: str = "normal",
    ) -> bool:
        """Send a notification, respecting suppression rules."""
        if not self.enabled:
            return False

        import time
        now = time.time()

        # Check minimum interval
        last = self._last_notification.get(category, 0)
        if now - last < self.min_interval_secs:
            return False

        self._last_notification[category] = now
        return send_notification(title, message, urgency)
