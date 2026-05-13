"""SSRF protection tests for _validate_webhook_url.

All tests mock socket.gethostbyname to avoid real DNS lookups.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.notifications.notifier import _validate_webhook_url


def _mock_resolve(ip: str):
    """Return a mock for socket.gethostbyname that always resolves to ip."""
    return lambda hostname: ip


def test_public_https_url_is_accepted():
    """https URL resolving to a public IP must NOT raise."""
    with patch("src.notifications.notifier.socket.gethostbyname", _mock_resolve("54.80.1.1")):
        _validate_webhook_url("https://hooks.slack.com/services/xyz")  # must not raise


def test_http_url_raises_value_error():
    """http (non-https) URL must raise ValueError regardless of IP."""
    with patch("src.notifications.notifier.socket.gethostbyname", _mock_resolve("54.80.1.1")):
        with pytest.raises(ValueError, match="must use https"):
            _validate_webhook_url("http://hooks.slack.com/services/xyz")


def test_private_192_168_raises_value_error():
    """URL resolving to 192.168.x.x (RFC-1918 private) must raise ValueError."""
    with patch("src.notifications.notifier.socket.gethostbyname", _mock_resolve("192.168.1.1")):
        with pytest.raises(ValueError, match="non-public IP"):
            _validate_webhook_url("https://192.168.1.1/webhook")


def test_private_10_0_0_raises_value_error():
    """URL resolving to 10.x.x.x (RFC-1918 private) must raise ValueError."""
    with patch("src.notifications.notifier.socket.gethostbyname", _mock_resolve("10.0.0.1")):
        with pytest.raises(ValueError, match="non-public IP"):
            _validate_webhook_url("https://10.0.0.1/webhook")


def test_link_local_169_254_raises_value_error():
    """URL resolving to 169.254.x.x (link-local, AWS metadata) must raise ValueError."""
    with patch("src.notifications.notifier.socket.gethostbyname", _mock_resolve("169.254.169.254")):
        with pytest.raises(ValueError, match="non-public IP"):
            _validate_webhook_url("https://169.254.169.254/latest/meta-data")


def test_loopback_127_0_0_1_raises_value_error():
    """URL resolving to 127.0.0.1 (loopback) must raise ValueError."""
    with patch("src.notifications.notifier.socket.gethostbyname", _mock_resolve("127.0.0.1")):
        with pytest.raises(ValueError, match="non-public IP"):
            _validate_webhook_url("https://127.0.0.1/webhook")
