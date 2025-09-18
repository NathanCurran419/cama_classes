from cama.models import PassageType, SamplingSession, QueuedItem, QueueItemType
from cama.services import LocalStorageService, OfflineQueue, SyncService, SurveyDataRepository, InteractiveMapController, MeterConnectionManager, ValidationService
from cama.managers import CheckpointManager
from uuid import uuid4
import os

DB = os.path.join(os.path.dirname(__file__), "cama.db")
OUTBOX = os.path.join(os.path.dirname(__file__), "outbox.json")

def seed_stations(storage):
    from cama.models import SurveyStation
    for name, x, y, z in [("A1",0.0,0.0,0.0), ("B5",10.0,2.0,0.0), ("C12",25.0,-3.0,-1.0), ("Z78",100.0,0.0,-5.0)]:
        storage.upsert_station(SurveyStation(station_id=name, name=name, x=x, y=y, z=z))

def demo():
    storage = LocalStorageService(DB)
    seed_stations(storage)
    repo = SurveyDataRepository(storage)
    mapc = InteractiveMapController(repo)
    queue = OfflineQueue(storage)
    sync = SyncService(storage, queue, OUTBOX)
    validator = ValidationService()
    mgr = CheckpointManager(mapc, storage, validator, queue)

    print("== Demo: Add/Edit/Delete Checkpoint ==")
    cp_id = mgr.add_checkpoint("Lower crawl at A1", PassageType.CRAWL, "A1", depth_from_entrance=5.0, distance_from_station=2.0)
    print("Created:", cp_id)
    mgr.edit_metadata(cp_id, name="Lower crawl near A1")
    print("Edited name; pending sync items flushed:", sync.flush())
    mgr.delete_checkpoint(cp_id)
    print("Deleted; pending sync items flushed:", sync.flush())

    print("\n== Demo: Start Sampling Session ==")
    meter = MeterConnectionManager()
    sess = SamplingSession(anchor_station_id="A1")
    for _ in range(3):
        sess.add_reading(meter.produce_reading())
    sess.end()
    storage.save_session(sess)
    queue.add(QueuedItem(id=uuid4(), kind=QueueItemType.SESSION_UPLOAD, payload=sess.to_dto()))
    print("Session saved; flushed:", sync.flush())

if __name__ == "__main__":
    demo()