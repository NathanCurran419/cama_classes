from __future__ import annotations
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple, Iterable
from uuid import uuid4, UUID
from datetime import datetime
import sqlite3, json, os

from .models import Checkpoint, PassageType, QueuedItem, QueueItemType, SamplingSession, GasReading, SurveyStation


class ValidationService:
    def validate_checkpoint(self, cp: Checkpoint) -> List[str]:
        errors = []
        if not cp.name:
            errors.append("name is required")
        if not cp.survey_station_id:
            errors.append("survey_station_id is required")
        if cp.depth_from_entrance < 0:
            errors.append("depth_from_entrance must be >= 0")
        return errors


class LocalStorageService:
    def __init__(self, db_path: str = ":memory:") -> None:
        # Alow cross-thread use for Streamlit reruns
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS checkpoints(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                passage_type TEXT NOT NULL,
                survey_station_id TEXT NOT NULL,
                depth REAL NOT NULL,
                distance REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS offline_queue(
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY,
                anchor_id TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT
            );
            CREATE TABLE IF NOT EXISTS readings(
                session_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                o2 REAL NOT NULL,
                co REAL NOT NULL,
                h2s REAL NOT NULL,
                lel REAL NOT NULL,
                checkpoint_id TEXT
            );
            CREATE TABLE IF NOT EXISTS stations(
                station_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                z REAL NOT NULL
            );
            """
        )
        self.conn.commit()

    # Checkpoints
    def save_checkpoint(self, cp: Checkpoint) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO checkpoints(id,name,passage_type,survey_station_id,depth,distance,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
            (
                str(cp.id), cp.name, cp.passage_type.value, cp.survey_station_id,
                cp.depth_from_entrance, cp.distance_from_station,
                cp.created_at.isoformat(), cp.updated_at.isoformat()
            ),
        )
        self.conn.commit()

    def delete_checkpoint(self, cp_id: str) -> None:
        self.conn.execute("DELETE FROM checkpoints WHERE id=?", (cp_id,))
        self.conn.commit()

    def list_checkpoints(self) -> List[Checkpoint]:
        rows = self.conn.execute("SELECT * FROM checkpoints").fetchall()
        out: List[Checkpoint] = []
        for r in rows:
            out.append(Checkpoint(
                id=UUID(r["id"]),
                name=r["name"],
                passage_type=PassageType(r["passage_type"]),
                survey_station_id=r["survey_station_id"],
                depth_from_entrance=r["depth"],
                distance_from_station=r["distance"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            ))
        return out

    #queue
    def enqueue(self, item: QueuedItem) -> None:
        self.conn.execute(
            "INSERT INTO offline_queue(id,kind,payload,created_at) VALUES(?,?,?,?)",
            (str(item.id), item.kind.value, json.dumps(item.payload), item.created_at.isoformat())
        )
        self.conn.commit()

    def take_batch(self, n: int) -> List[QueuedItem]:
        rows = self.conn.execute("SELECT * FROM offline_queue ORDER BY created_at LIMIT ?", (n,)).fetchall()
        items: List[QueuedItem] = []
        for r in rows:
            items.append(QueuedItem(
                id=UUID(r["id"]),
                kind=QueueItemType(r["kind"]),
                payload=json.loads(r["payload"]),
            ))
        return items

    def purge(self, ids: Iterable[str]) -> None:
        self.conn.executemany("DELETE FROM offline_queue WHERE id=?", [(i,) for i in ids])
        self.conn.commit()

    # Sessions & Readings
    def save_session(self, sess: SamplingSession) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO sessions(id,anchor_id,started_at,ended_at) VALUES(?,?,?,?)",
            (str(sess.id), sess.anchor_station_id, sess.started_at.isoformat(), sess.ended_at.isoformat() if sess.ended_at else None)
        )
        if sess.readings:
            self.conn.executemany(
                "INSERT INTO readings(session_id,captured_at,o2,co,h2s,lel,checkpoint_id) VALUES(?,?,?,?,?,?,?)",
                [
                    (str(sess.id), r.captured_at.isoformat(), r.o2_pct, r.co_ppm, r.h2s_ppm, r.lel_pct, r.checkpoint_id)
                    for r in sess.readings
                ]
            )
        self.conn.commit()

    # Stations
    def upsert_station(self, st: SurveyStation) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO stations(station_id,name,x,y,z) VALUES(?,?,?,?,?)",
            (st.station_id, st.name, st.x, st.y, st.z)
        )
        self.conn.commit()

    def get_station(self, station_id: str) -> Optional[SurveyStation]:
        r = self.conn.execute("SELECT * FROM stations WHERE station_id=?", (station_id,)).fetchone()
        if not r: return None
        return SurveyStation(r["station_id"], r["name"], r["x"], r["y"], r["z"])

    def list_stations(self) -> List[SurveyStation]:
        rows = self.conn.execute("SELECT * FROM stations").fetchall()
        return [SurveyStation(r["station_id"], r["name"], r["x"], r["y"], r["z"]) for r in rows]


class OfflineQueue:
    """Composition in diagram: queue owns items."""
    def __init__(self, storage: LocalStorageService) -> None:
        self.storage = storage

    def add(self, item: QueuedItem) -> None:
        self.storage.enqueue(item)

    def take_batch(self, n: int) -> List[QueuedItem]:
        return self.storage.take_batch(n)

    def purge(self, items: List[QueuedItem]) -> None:
        self.storage.purge([str(i.id) for i in items])


class SyncService:
    def __init__(self, storage: LocalStorageService, queue: OfflineQueue, outbox_path: str) -> None:
        self.storage = storage
        self.queue = queue
        self.outbox_path = outbox_path

    def flush(self, n: int = 50) -> int:
        batch = self.queue.take_batch(n)
        if not batch: return 0
        existing = []
        if os.path.exists(self.outbox_path):
            with open(self.outbox_path, "r", encoding="utf-8") as f:
                data = f.read().strip()
                existing = json.loads(data) if data else []
        existing += [{"id": str(i.id), "kind": i.kind.value, "payload": i.payload} for i in batch]
        with open(self.outbox_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        self.queue.purge(batch)
        return len(batch)


class SurveyDataRepository:
    """Aggregation in diagram: does not own station lifecycle."""
    def __init__(self, storage: LocalStorageService) -> None:
        self.storage = storage

    def nearest_station(self, x: float, y: float, z: float) -> Optional[SurveyStation]:
        stations = self.storage.list_stations()
        if not stations: return None
        def d(st): return (st.x-x)**2 + (st.y-y)**2 + (st.z-z)**2
        return min(stations, key=d)


class InteractiveMapController:
    def __init__(self, repo: SurveyDataRepository) -> None:
        self.repo = repo

    def handle_tap(self, x: float, y: float, z: float = 0.0) -> Dict:
        st = self.repo.nearest_station(x, y, z)
        return {"x": x, "y": y, "z": z, "station_id": st.station_id if st else None}


class MeterConnectionManager:
    def produce_reading(self) -> GasReading:
        import random
        # Create a simulated but plausible reading (O2 ~ 20.9% normal)
        return GasReading(
            o2_pct=round(random.uniform(18.0, 21.0), 2),
            co_ppm=round(random.uniform(0, 15), 1),
            h2s_ppm=round(random.uniform(0, 5), 1),
            lel_pct=round(random.uniform(0, 5), 1),
        )


class CrashRecoveryService:
    def __init__(self, storage: LocalStorageService, queue: OfflineQueue) -> None:
        self.storage = storage
        self.queue = queue

    def verify_integrity(self) -> int:
        batch = self.queue.take_batch(1000)
        return len(batch)