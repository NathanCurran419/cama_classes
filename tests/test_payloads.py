import os, json, shutil, tempfile, unittest
from uuid import uuid4
from cama.models import PassageType, SamplingSession, GasReading, QueuedItem, QueueItemType, SurveyStation
from cama.services import LocalStorageService, OfflineQueue, SyncService, SurveyDataRepository, InteractiveMapController, ValidationService
from cama.managers import CheckpointManager

class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="cama_tests_")
        self.db = os.path.join(self.tmpdir, "test.db")
        self.out = os.path.join(self.tmpdir, "out.json")
        self.storage = LocalStorageService(self.db)
        self.repo = SurveyDataRepository(self.storage)
        self.mapc = InteractiveMapController(self.repo)
        self.queue = OfflineQueue(self.storage)
        self.sync = SyncService(self.storage, self.queue, self.out)
        self.storage.upsert_station(SurveyStation("A1", "A1", 0, 0, 0))

    def tearDown(self):
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_session_payload_contains_readings(self):
        sess = SamplingSession(anchor_station_id="A1")
        sess.add_reading(GasReading(20.5, 0.5, 0.0, 0.1))
        sess.add_reading(GasReading(20.1, 1.0, 0.1, 0.0))
        sess.end()
        self.storage.save_session(sess)
        self.queue.add(QueuedItem(id=uuid4(), kind=QueueItemType.SESSION_UPLOAD, payload=sess.to_dto()))
        flushed = self.sync.flush()
        self.assertGreaterEqual(flushed, 1)
        with open(self.out, "r", encoding="utf-8") as f:
            data = json.load(f)
        last = data[-1]
        self.assertEqual(last["kind"], "SESSION_UPLOAD")
        readings = last["payload"]["readings"]
        self.assertIsInstance(readings, list)
        self.assertEqual(len(readings), 2)
        self.assertIn("o2_pct", readings[0])
        self.assertIn("co_ppm", readings[0])
        self.assertIn("captured_at", readings[0])

    def test_checkpoint_payload_roundtrip(self):
        mgr = CheckpointManager(self.mapc, self.storage, ValidationService(), self.queue)
        cp_id = mgr.add_checkpoint("CP", PassageType.CRAWL, "A1", 1.23456, 0.98765)
        flushed = self.sync.flush()
        self.assertGreaterEqual(flushed, 1)
        with open(self.out, "r", encoding="utf-8") as f:
            data = json.load(f)
        payload = data[-1]["payload"]
        self.assertEqual(payload["name"], "CP")
        self.assertAlmostEqual(payload["depth_from_entrance"], 1.235, places=3)

if __name__ == "__main__":
    unittest.main(verbosity=2)
