from __future__ import annotations
from typing import Dict, Optional, List
from uuid import uuid4, UUID
from datetime import datetime

from .models import Checkpoint, PassageType, QueuedItem, QueueItemType
from .services import LocalStorageService, ValidationService, OfflineQueue, InteractiveMapController


class CheckpointManager:
    def __init__(self, map_controller: InteractiveMapController, storage: LocalStorageService, validator: ValidationService, queue: OfflineQueue) -> None:
        self.map_controller = map_controller
        self.storage = storage
        self.validator = validator
        self.queue = queue
        self.cache: Dict[UUID, Checkpoint] = {}

    def add_checkpoint(self, name: str, passage_type: PassageType, survey_station_id: str, depth_from_entrance: float = 0.0, distance_from_station: float = 0.0) -> UUID:
        cp = Checkpoint(
            id=uuid4(),
            name=name,
            passage_type=passage_type,
            survey_station_id=survey_station_id,
            depth_from_entrance=depth_from_entrance,
            distance_from_station=distance_from_station,
        )
        errors = self.validator.validate_checkpoint(cp)
        if errors:
            raise ValueError("; ".join(errors))
        self.storage.save_checkpoint(cp)
        self.cache[cp.id] = cp
        self.queue.add(QueuedItem(id=uuid4(), kind=QueueItemType.CHECKPOINT_CREATE, payload=cp.to_dto()))
        return cp.id

    def edit_metadata(self, cp_id: UUID, **updates) -> None:
        cp = self.cache.get(cp_id)
        if not cp:
            # load from storage
            for c in self.storage.list_checkpoints():
                if c.id == cp_id:
                    cp = c
                    break
        if not cp:
            raise KeyError("Checkpoint not found")
        for k, v in updates.items():
            if hasattr(cp, k):
                setattr(cp, k, v)
        cp.updated_at = datetime.utcnow()
        errors = self.validator.validate_checkpoint(cp)
        if errors:
            raise ValueError("; ".join(errors))
        self.storage.save_checkpoint(cp)
        self.cache[cp.id] = cp
        self.queue.add(QueuedItem(id=uuid4(), kind=QueueItemType.CHECKPOINT_UPDATE, payload=cp.to_dto()))

    def delete_checkpoint(self, cp_id: UUID) -> None:
        self.storage.delete_checkpoint(str(cp_id))
        self.cache.pop(cp_id, None)
        self.queue.add(QueuedItem(id=uuid4(), kind=QueueItemType.CHECKPOINT_DELETE, payload={"id": str(cp_id)}))

    def list_checkpoints(self):
        return self.storage.list_checkpoints()