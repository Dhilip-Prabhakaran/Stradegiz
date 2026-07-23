"""Selects the option-chain provider from configuration.

Adding a provider is a new branch here plus its adapter file — the recorder
stays provider-agnostic.
"""

from __future__ import annotations

from .. import auth
from ..config import Settings
from .base import DataSourceError


def make_source(settings: Settings):
    """Build the configured DataSource, or raise DataSourceError if it cannot."""
    which = settings.data_source

    if which == "kotak":
        from .kotak_source import KotakNeoSource

        if settings.kotak is None or not settings.kotak.is_complete():
            missing = settings.kotak.missing() if settings.kotak else ["all KOTAK_*"]
            raise DataSourceError(
                f"DATA_SOURCE=kotak but .env is missing: {', '.join(missing)}. "
                "Kotak needs the full 2FA login even for market data."
            )
        return KotakNeoSource(settings.kotak)

    if which == "upstox":
        from .upstox_source import UpstoxOptionChain

        return UpstoxOptionChain(auth.get_valid_token)

    raise DataSourceError(f"unknown DATA_SOURCE: {which!r} (expected kotak or upstox)")
