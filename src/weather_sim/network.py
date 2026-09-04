"""Shared HTTPS handling with a portable trusted CA bundle."""

from __future__ import annotations

import ssl
import urllib.request
from typing import Any

import certifi

_TRUSTED_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def open_trusted_url(request: urllib.request.Request, *, timeout: float) -> Any:
    """Open an HTTPS request using certifi instead of Python's host CA path."""
    return urllib.request.urlopen(
        request,
        timeout=timeout,
        context=_TRUSTED_SSL_CONTEXT,
    )
