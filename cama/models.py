from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Tuple
from uuid import uuid4, UUID
from datetime import datetime


class PassageType(str, Enum):
    CANYON = "CANYON"
    TUBE = "TUBE"
    KEYHOLE = "KEYHOLE"
    PIT = "PIT"
    CRAWL = "CRAWL"
    ROOM = "ROOM"


@dataclass(frozen=True)
class StationDTO:
    station_id: str
    name: str
    x: float
    y: float
    z: float


@dataclass
class SurveyStation:
    station_id: str
    name: str
    x: float
    y: float
    z: float

    def to_dto(self) -> StationDTO:
        return StationDTO(self.station_id, self.name, self.x, self.y, self.z)


@dataclass
class Checkpoint:
    id: UUID
    name: str
    passage_type: PassageType
    survey_station_id: str
    depth_from_entrance: float = 0.0
    distance_from_station: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_valid(self) -> bool:
        return bool(self.name) and bool(self.survey_station_id) and self.depth_from_entrance >= 0

    def to_dto(self) -> Dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "passage_type": self.passage_type.value,
            "survey_station_id": self.survey_station_id,
            "depth_from_entrance": round(self.depth_from_entrance, 3),
            "distance_from_station": round(self.distance_from_station, 3),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class GasReading:
    o2_pct: float
    co_ppm: float
    h2s_ppm: float
    lel_pct: float
    captured_at: datetime = field(default_factory=datetime.utcnow)
    checkpoint_id: Optional[str] = None  # stringified UUID

    def to_dto(self) -> dict:
        return {
            "captured_at": self.captured_at.isoformat(),
            "o2_pct": round(self.o2_pct, 3),
            "co_ppm": round(self.co_ppm, 3),
            "h2s_ppm": round(self.h2s_ppm, 3),
            "lel_pct": round(self.lel_pct, 3),
            "checkpoint_id": self.checkpoint_id,
        }


@dataclass
class SamplingSession:
    id: UUID = field(default_factory=uuid4)
    anchor_station_id: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    readings: List[GasReading] = field(default_factory=list)

    def add_reading(self, r: GasReading) -> None:
        self.readings.append(r)

    def end(self) -> None:
        self.ended_at = datetime.utcnow()

    def to_dto(self) -> dict:
        return {
            "schema_version": 1,
            "id": str(self.id),
            "anchor_station_id": self.anchor_station_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "readings": [r.to_dto() for r in self.readings],
            "reading_count": len(self.readings),
        }


class QueueItemType(str, Enum):
    CHECKPOINT_CREATE = "CHECKPOINT_CREATE"
    CHECKPOINT_UPDATE = "CHECKPOINT_UPDATE"
    CHECKPOINT_DELETE = "CHECKPOINT_DELETE"
    SESSION_UPLOAD = "SESSION_UPLOAD"


@dataclass
class QueuedItem:
    id: UUID
    kind: QueueItemType
    payload: dict
    created_at: datetime = field(default_factory=datetime.utcnow)