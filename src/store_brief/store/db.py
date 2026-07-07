"""SQLite event store.

Data volume is tiny (tens of events/week, 4-week window), so the query strategy is simply
'load the recent window into memory and filter with temporal/ + relevance/'. The store's
real jobs are persistence across daily runs and the bookkeeping that makes diffs possible:
  - first_seen: set once, on first insert  -> powers 'new this week'
  - last_updated: bumped on every upsert    -> powers 'updated this week'
  - 4-week prune                            -> bounded growth

Events are stored as a JSON blob plus the scalar columns we filter/prune on.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

_DDL = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT,
    valid_to TEXT,
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    version_of TEXT,
    blob TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_first_seen ON events(first_seen);
CREATE INDEX IF NOT EXISTS idx_events_valid_to ON events(valid_to);
"""


class EventStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_DDL)

    def upsert(self, event, as_of: date) -> None:
        """Insert new (first_seen=as_of) or update existing (bump last_updated, keep first_seen)."""
        row = self.conn.execute("SELECT first_seen FROM events WHERE id=?", (event.id,)).fetchone()
        first_seen = row[0] if row else as_of.isoformat()
        event.first_seen = date.fromisoformat(first_seen)
        event.last_updated = as_of
        self.conn.execute(
            "REPLACE INTO events (id, type, valid_to, first_seen, last_updated, version_of, blob)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                event.id, _enum(event.type),
                event.valid_to.isoformat() if event.valid_to else None,
                first_seen, as_of.isoformat(), event.version_of,
                event.model_dump_json(),
            ),
        )
        self.conn.commit()

    def load_recent(self, as_of: date, weeks: int = 4) -> list:
        """Return Events whose first_seen is within the trailing window (as model objects)."""
        from store_brief.extract.schema import Event  # local import: keeps store import light

        since = (as_of - timedelta(weeks=weeks)).isoformat()
        rows = self.conn.execute(
            "SELECT blob FROM events WHERE first_seen >= ?", (since,)
        ).fetchall()
        return [Event.model_validate_json(r[0]) for r in rows]

    def delete(self, event_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def delete_many(self, event_ids: list[str]) -> int:
        if not event_ids:
            return 0
        cur = self.conn.executemany("DELETE FROM events WHERE id=?", [(i,) for i in event_ids])
        self.conn.commit()
        return cur.rowcount
        cutoff = (as_of - timedelta(weeks=weeks)).isoformat()
        cur = self.conn.execute("DELETE FROM events WHERE first_seen < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount


def _enum(v):
    return getattr(v, "value", v)
