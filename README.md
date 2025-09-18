# CAMA Class Implementation

## Requirements
- Python 3.10+
- (GUI) `pip install streamlit pandas`

## Run CLI demo
```bash
python main.py
```

## Run tests
```bash
python -m unittest discover -s tests -p "test*.py" -v
```

## Run GUI
```bash
pip install streamlit pandas
python -m streamlit run app.py
```

## Class reference (what each class does)

### `cama/models.py` — Domain models & DTOs

**Enums**
- `PassageType` — `CANYON | TUBE | KEYHOLE | PIT | CRAWL | ROOM`
- `QueueItemType` — `CHECKPOINT_CREATE | CHECKPOINT_UPDATE | CHECKPOINT_DELETE | SESSION_UPLOAD`

**`SurveyStation`**
- Survey point with `station_id`, `name`, and coordinates `x / y / z`.
- `to_dto()` returns a typed `StationDTO`.

**`Checkpoint`**
- User-defined point to capture readings.
- **Fields:** `id (UUID)`, `name`, `passage_type`, `survey_station_id`, `depth_from_entrance`, `distance_from_station`, `created_at`, `updated_at`.
- `is_valid()` for basic checks.
- `to_dto()` rounds numeric fields and uses ISO timestamps for clean payloads.

**`GasReading`**
- One meter sample: `o2_pct`, `co_ppm`, `h2s_ppm`, `lel_pct`, `captured_at`, optional `checkpoint_id`.
- `to_dto()` → JSON-ready reading (rounded values, ISO timestamp).

**`SamplingSession`**
- A run of readings anchored to a station.
- Methods: `add_reading()`, `end()`.
- `to_dto()` → versioned payload (`schema_version`), `reading_count`, full `readings[]`.

**`QueuedItem`**
- Outbound event placed in the offline queue with `kind` and `payload` (usually a DTO).

---

### `cama/services.py` — Persistence, queue, sync, helpers

**`LocalStorageService`**
- Wraps SQLite with `check_same_thread=False` (Streamlit-friendly).
- **Tables:** `stations`, `checkpoints`, `sessions`, `readings`, `offline_queue`.
- **CRUD:** `save_checkpoint()`, `delete_checkpoint()`, `list_checkpoints()`, `save_session()`, `upsert_station()`, etc.
- **Queue ops:** `enqueue()`, `take_batch()`, `purge()`.

**`OfflineQueue`**
- Composition over `QueuedItem`s; thin façade over storage queue methods.

**`SyncService`**
- `flush(n=50)` moves a batch of queued items into `outbox.json` (simulated server), then purges them from the queue.

**`SurveyDataRepository`**
- Read-only helpers over stations (e.g., `nearest_station(x, y, z)`); **aggregation** (does not own station lifecycle).

**`InteractiveMapController`**
- Given a click/point, returns nearest station via the repository.

**`MeterConnectionManager`**
- Generates realistic mock meter readings (swap in BLE/USB later).

**`CrashRecoveryService`**
- Placeholder for integrity checks (count pending items, etc.).

---

### `cama/managers.py` — Use-case orchestration

**`CheckpointManager`** — Implements UC-F1:
- `add_checkpoint()` → **validate** → **persist** → **enqueue** `CHECKPOINT_CREATE` (`checkpoint.to_dto()`).
- `edit_metadata()` → **update** → **revalidate** → **persist** → **enqueue** `CHECKPOINT_UPDATE`.
- `delete_checkpoint()` → **delete** → **enqueue** `CHECKPOINT_DELETE`.
- `list_checkpoints()` passthrough.
