"""Tests for Supabase-backed config persistence helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.config_store as config_store


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTableQuery:
    def __init__(self, client, table_name: str):
        self.client = client
        self.table_name = table_name
        self._filters: dict[str, object] = {}
        self._limit: int | None = None
        self._order_desc = False
        self._payload = None
        self._mode = "select"

    def select(self, _columns: str):
        self._mode = "select"
        return self

    def eq(self, field: str, value):
        self._filters[field] = value
        return self

    def limit(self, limit: int):
        self._limit = limit
        return self

    def order(self, _field: str, desc: bool = False):
        self._order_desc = desc
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict: str | None = None):
        self._mode = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def execute(self):
        if self._mode == "select":
            rows = list(self.client.tables[self.table_name])
            for field, value in self._filters.items():
                rows = [row for row in rows if row.get(field) == value]
            if self.table_name == "config_history" and self._order_desc:
                rows.sort(key=lambda row: row.get("saved_at") or "", reverse=True)
            if self._limit is not None:
                rows = rows[: self._limit]
            return _FakeResponse(rows)

        if self._mode == "insert":
            payload = dict(self._payload)
            if self.table_name == "config_history" and "version_id" not in payload:
                payload["version_id"] = self.client.next_version_id
                self.client.next_version_id += 1
            self.client.tables[self.table_name].append(payload)
            return _FakeResponse([payload])

        if self._mode == "upsert":
            payload = dict(self._payload)
            rows = self.client.tables[self.table_name]
            for index, row in enumerate(rows):
                if row.get("id") == payload.get("id"):
                    rows[index] = payload
                    return _FakeResponse([payload])
            rows.append(payload)
            return _FakeResponse([payload])

        raise AssertionError(f"Unsupported mode {self._mode}")


class _FakeClient:
    def __init__(self):
        self.tables = {
            "app_config": [],
            "config_history": [],
        }
        self.next_version_id = 1

    def table(self, table_name: str):
        return _FakeTableQuery(self, table_name)


def test_bootstrap_published_config_if_missing(monkeypatch) -> None:
    """Bootstrapping should insert a published row plus a history row."""

    client = _FakeClient()
    monkeypatch.setattr(config_store, "get_supabase_client", lambda: client)

    seed = {"hello": "world"}
    record = config_store.bootstrap_published_config_if_missing(seed)

    assert record.config_json == seed
    assert record.updated_by == "bootstrap"
    assert client.tables["app_config"][0]["id"] == "default"
    assert client.tables["config_history"][0]["saved_by"] == "bootstrap"


def test_save_published_config_appends_history(monkeypatch) -> None:
    """Saving should upsert the published row and append a history row."""

    client = _FakeClient()
    client.tables["app_config"].append(
        {
            "id": "default",
            "config_json": {"old": True},
            "updated_at": "2026-01-01T00:00:00+00:00",
            "updated_by": "bootstrap",
        }
    )
    monkeypatch.setattr(config_store, "get_supabase_client", lambda: client)

    saved = config_store.save_published_config({"new": True}, saved_by="public_user")
    history = config_store.load_recent_config_history(limit=10)
    published = config_store.load_published_config()

    assert saved.updated_by == "public_user"
    assert published is not None
    assert published.config_json == {"new": True}
    assert len(history) == 1
    assert history[0].saved_by == "public_user"
    assert history[0].config_json == {"new": True}
