"""Aggregate counters and short-lived hashed webhook delivery claims; no conversation storage."""

import hashlib
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


def message_key(message_id: str) -> str:
    return hashlib.sha256(message_id.encode()).hexdigest()


def summarize(rows):
    total = sum(row["count"] for row in rows)
    grounded = sum(row["grounded_count"] for row in rows)
    latency = sum(row["latency_ms"] for row in rows)
    categories, channels, daily = {}, {}, {}
    for row in rows:
        categories[row["category"]] = categories.get(row["category"], 0) + row["count"]
        channels[row["channel"]] = channels.get(row["channel"], 0) + row["count"]
        daily[row["date"]] = daily.get(row["date"], 0) + row["count"]
    return {
        "total_messages": total,
        "grounded_messages": grounded,
        "fallback_messages": total - grounded,
        "avg_latency_ms": round(latency / total, 1) if total else 0,
        "by_category": categories,
        "by_channel": channels,
        "daily": [{"date": day, "count": count} for day, count in sorted(daily.items())],
        "retention_days": 90,
        "stores_conversation_content": False,
    }


class Store(Protocol):
    def record(self, category: str, channel: str, grounded: bool, latency_ms: float): ...
    def metrics(self) -> dict: ...
    def claim(self, message_id: str) -> str: ...
    def complete(self, message_id: str, metric: dict | None = None): ...
    def release(self, message_id: str): ...


class SQLiteStore:
    def __init__(self, path: str):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metrics (
                date TEXT, category TEXT, channel TEXT, count INTEGER, grounded_count INTEGER,
                latency_ms REAL, PRIMARY KEY (date, category, channel)
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                key TEXT PRIMARY KEY, status TEXT, lease_until REAL, expires_at REAL
            );
        """)
        self.db.commit()

    def record(self, category, channel, grounded, latency_ms):
        date = datetime.now(UTC).date()
        with self.lock, self.db:
            self.db.execute("DELETE FROM metrics WHERE date < ?", (str(date - timedelta(days=90)),))
            self.db.execute(
                """INSERT INTO metrics VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(date,category,channel) DO UPDATE SET count=count+1,
                grounded_count=grounded_count+excluded.grounded_count,
                latency_ms=latency_ms+excluded.latency_ms""",
                (str(date), category, channel, int(grounded), latency_ms),
            )

    def metrics(self):
        cutoff = str(datetime.now(UTC).date() - timedelta(days=90))
        with self.lock:
            rows = [
                dict(row)
                for row in self.db.execute("SELECT * FROM metrics WHERE date >= ?", (cutoff,))
            ]
        return summarize(rows)

    def claim(self, message_id):
        now = time.time()
        key = message_key(message_id)
        with self.lock, self.db:
            self.db.execute("DELETE FROM deliveries WHERE expires_at < ?", (now,))
            row = self.db.execute("SELECT * FROM deliveries WHERE key = ?", (key,)).fetchone()
            if row and row["status"] == "sent":
                return "sent"
            if row and row["lease_until"] > now:
                return "pending"
            self.db.execute(
                "INSERT OR REPLACE INTO deliveries VALUES (?, 'pending', ?, ?)",
                (key, now + 90, now + 7 * 86400),
            )
        return "claimed"

    def complete(self, message_id, metric=None):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE deliveries SET status='sent' WHERE key=?", (message_key(message_id),)
            )
            if metric is not None:
                date = datetime.now(UTC).date()
                self.db.execute(
                    "DELETE FROM metrics WHERE date < ?", (str(date - timedelta(days=90)),)
                )
                self.db.execute(
                    """INSERT INTO metrics VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(date,category,channel) DO UPDATE SET count=count+1,
                    grounded_count=grounded_count+excluded.grounded_count,
                    latency_ms=latency_ms+excluded.latency_ms""",
                    (
                        str(date),
                        metric["category"],
                        "whatsapp",
                        int(metric["grounded"]),
                        metric["latency_ms"],
                    ),
                )

    def release(self, message_id):
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM deliveries WHERE key=? AND status='pending'",
                (message_key(message_id),),
            )


class FirestoreStore:
    def __init__(self, project: str, database: str):
        from google.cloud import firestore

        self.firestore = firestore
        self.db = firestore.Client(project=project, database=database)

    def record(self, category, channel, grounded, latency_ms):
        date = datetime.now(UTC).date()
        ref = self.db.collection("metrics").document(f"{date}_{category}_{channel}")
        self.db.collection("metrics").document(ref.id).set(
            {
                "date": str(date),
                "category": category,
                "channel": channel,
                "count": self.firestore.Increment(1),
                "grounded_count": self.firestore.Increment(int(grounded)),
                "latency_ms": self.firestore.Increment(latency_ms),
                "expires_at": datetime.now(UTC) + timedelta(days=90),
            },
            merge=True,
        )

    def metrics(self):
        from google.cloud.firestore_v1.base_query import FieldFilter

        cutoff = str(datetime.now(UTC).date() - timedelta(days=90))
        rows = [
            doc.to_dict()
            for doc in self.db.collection("metrics")
            .where(filter=FieldFilter("date", ">=", cutoff))
            .stream()
        ]
        return summarize(rows)

    def claim(self, message_id):
        ref = self.db.collection("deliveries").document(message_key(message_id))
        now = datetime.now(UTC)

        @self.firestore.transactional
        def claim_transaction(transaction):
            snapshot = ref.get(transaction=transaction)
            existing = snapshot.to_dict() if snapshot.exists else None
            if existing and existing["expires_at"] > now:
                if existing["status"] == "sent":
                    return "sent"
                if existing["lease_until"] > now:
                    return "pending"
            transaction.set(
                ref,
                {
                    "status": "pending",
                    "lease_until": now + timedelta(seconds=90),
                    "expires_at": now + timedelta(days=7),
                },
            )
            return "claimed"

        return claim_transaction(self.db.transaction())

    def complete(self, message_id, metric=None):
        batch = self.db.batch()
        batch.update(
            self.db.collection("deliveries").document(message_key(message_id)), {"status": "sent"}
        )
        if metric is not None:
            now = datetime.now(UTC)
            date = str(now.date())
            ref = self.db.collection("metrics").document(f"{date}_{metric['category']}_whatsapp")
            batch.set(
                ref,
                {
                    "date": date,
                    "category": metric["category"],
                    "channel": "whatsapp",
                    "count": self.firestore.Increment(1),
                    "grounded_count": self.firestore.Increment(int(metric["grounded"])),
                    "latency_ms": self.firestore.Increment(metric["latency_ms"]),
                    "expires_at": now + timedelta(days=90),
                },
                merge=True,
            )
        batch.commit()

    def release(self, message_id):
        ref = self.db.collection("deliveries").document(message_key(message_id))

        @self.firestore.transactional
        def release_transaction(transaction):
            snapshot = ref.get(transaction=transaction)
            if snapshot.exists and snapshot.to_dict()["status"] == "pending":
                transaction.delete(ref)

        release_transaction(self.db.transaction())


def make_store(settings) -> Store:
    if settings.storage_backend == "firestore":
        return FirestoreStore(settings.google_cloud_project, settings.firestore_database)
    return SQLiteStore(settings.sqlite_path)
