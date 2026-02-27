from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    lectio_html_path: Path
    output_ics_path: Path
    timezone: str
    sync_days_past: int
    sync_days_future: int
    delete_missing: bool
    emit_cancelled_events: bool


def load_config_from_env() -> Config:
    """Load configuration from environment variables with default values."""
    return load_config_from_env_with_overrides()


def load_config_from_env_with_overrides(
    *,
    lectio_html_path: Path | None = None,
    output_ics_path: Path | None = None,
    timezone: str | None = None,
    sync_days_past: int | None = None,
    sync_days_future: int | None = None,
    delete_missing: bool | None = None,
    emit_cancelled_events: bool | None = None,
) -> Config:
    """Load configuration from environment, allowing CLI overrides.

    This exists so CLI flags can be used without requiring env vars.
    """

    import os

    def _env_path(name: str, default: str = "") -> Path:
        return Path(os.environ.get(name, default))

    resolved_html = lectio_html_path or _env_path("LECTIO_HTML_PATH")
    if not str(resolved_html):
        raise ValueError("LECTIO_HTML_PATH is required (or pass --html)")

    resolved_out = output_ics_path or _env_path("OUTPUT_ICS_PATH", "docs/calendar.ics")
    resolved_tz = timezone or os.environ.get("LECTIO_TIMEZONE", "Europe/Copenhagen")

    def _int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return default
        return int(raw)

    def _bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return default
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        raise ValueError(f"Invalid boolean for {name}: {raw!r}")

    resolved_sync_days_past = sync_days_past if sync_days_past is not None else _int("SYNC_DAYS_PAST", 7)
    resolved_sync_days_future = sync_days_future if sync_days_future is not None else _int("SYNC_DAYS_FUTURE", 90)
    resolved_delete_missing = delete_missing if delete_missing is not None else _bool("DELETE_MISSING", True)
    resolved_emit_cancelled_events = (
        emit_cancelled_events
        if emit_cancelled_events is not None
        else _bool("EMIT_CANCELLED_EVENTS", False)
    )

    return Config(
        lectio_html_path=resolved_html,
        output_ics_path=resolved_out,
        timezone=resolved_tz,
        sync_days_past=resolved_sync_days_past,
        sync_days_future=resolved_sync_days_future,
        delete_missing=resolved_delete_missing,
        emit_cancelled_events=resolved_emit_cancelled_events,
    )
