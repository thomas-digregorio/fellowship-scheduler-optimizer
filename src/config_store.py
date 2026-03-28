"""Supabase-backed shared config persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from supabase import Client, create_client

CONFIG_ID = "default"
DEFAULT_SAVED_BY = "public_user"


class ConfigStoreError(RuntimeError):
    """Raised when the shared config store cannot complete an operation."""


class ConfigStoreUnavailableError(ConfigStoreError):
    """Raised when Supabase secrets are not configured."""


@dataclass(frozen=True)
class PublishedConfigRecord:
    """The current published configuration row."""

    config_json: dict[str, Any]
    updated_at: str | None
    updated_by: str | None


@dataclass(frozen=True)
class ConfigHistoryEntry:
    """A single config history row."""

    version_id: int | None
    config_id: str
    config_json: dict[str, Any]
    saved_at: str | None
    saved_by: str | None


def _require_supabase_settings() -> tuple[str, str]:
    """Read required Supabase settings from Streamlit secrets."""

    try:
        url = str(st.secrets["SUPABASE_URL"])
        key = str(st.secrets["SUPABASE_KEY"])
    except Exception as exc:  # pragma: no cover - exact exception varies by runtime
        raise ConfigStoreUnavailableError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY in Streamlit secrets."
        ) from exc

    if not url or not key:
        raise ConfigStoreUnavailableError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY in Streamlit secrets."
        )
    return url, key


@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client:
    """Return a cached Supabase client."""

    url, key = _require_supabase_settings()
    return create_client(url, key)


def _row_to_published_record(row: dict[str, Any] | None) -> PublishedConfigRecord | None:
    if row is None:
        return None
    return PublishedConfigRecord(
        config_json=dict(row.get("config_json") or {}),
        updated_at=row.get("updated_at"),
        updated_by=row.get("updated_by"),
    )


def _row_to_history_entry(row: dict[str, Any]) -> ConfigHistoryEntry:
    return ConfigHistoryEntry(
        version_id=row.get("version_id"),
        config_id=row.get("config_id") or CONFIG_ID,
        config_json=dict(row.get("config_json") or {}),
        saved_at=row.get("saved_at"),
        saved_by=row.get("saved_by"),
    )


def load_published_config() -> PublishedConfigRecord | None:
    """Load the currently published config row from Supabase."""

    try:
        response = (
            get_supabase_client()
            .table("app_config")
            .select("config_json, updated_at, updated_by")
            .eq("id", CONFIG_ID)
            .limit(1)
            .execute()
        )
    except ConfigStoreUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        raise ConfigStoreError(f"Failed to load the published config from Supabase: {exc}") from exc

    rows = response.data or []
    return _row_to_published_record(rows[0] if rows else None)


def bootstrap_published_config_if_missing(seed_config: dict[str, Any]) -> PublishedConfigRecord:
    """Create the published config row if it does not yet exist."""

    existing = load_published_config()
    if existing is not None:
        return existing

    saved_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": CONFIG_ID,
        "config_json": seed_config,
        "updated_at": saved_at,
        "updated_by": "bootstrap",
    }
    history_payload = {
        "config_id": CONFIG_ID,
        "config_json": seed_config,
        "saved_at": saved_at,
        "saved_by": "bootstrap",
    }
    try:
        client = get_supabase_client()
        client.table("app_config").insert(payload).execute()
        client.table("config_history").insert(history_payload).execute()
    except ConfigStoreUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        raise ConfigStoreError(f"Failed to bootstrap the published config in Supabase: {exc}") from exc

    return PublishedConfigRecord(
        config_json=seed_config,
        updated_at=saved_at,
        updated_by="bootstrap",
    )


def save_published_config(
    config: dict[str, Any],
    saved_by: str = DEFAULT_SAVED_BY,
) -> PublishedConfigRecord:
    """Write the published config row and append a history entry."""

    saved_at = datetime.now(timezone.utc).isoformat()
    published_payload = {
        "id": CONFIG_ID,
        "config_json": config,
        "updated_at": saved_at,
        "updated_by": saved_by,
    }
    history_payload = {
        "config_id": CONFIG_ID,
        "config_json": config,
        "saved_at": saved_at,
        "saved_by": saved_by,
    }

    try:
        client = get_supabase_client()
        client.table("app_config").upsert(published_payload, on_conflict="id").execute()
        client.table("config_history").insert(history_payload).execute()
    except ConfigStoreUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        raise ConfigStoreError(f"Failed to save the published config to Supabase: {exc}") from exc

    return PublishedConfigRecord(
        config_json=config,
        updated_at=saved_at,
        updated_by=saved_by,
    )


def load_recent_config_history(limit: int = 10) -> list[ConfigHistoryEntry]:
    """Return the most recent published-config history entries."""

    try:
        response = (
            get_supabase_client()
            .table("config_history")
            .select("version_id, config_id, config_json, saved_at, saved_by")
            .eq("config_id", CONFIG_ID)
            .order("saved_at", desc=True)
            .limit(limit)
            .execute()
        )
    except ConfigStoreUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - network/runtime dependent
        raise ConfigStoreError(f"Failed to load config history from Supabase: {exc}") from exc

    return [_row_to_history_entry(row) for row in (response.data or [])]
