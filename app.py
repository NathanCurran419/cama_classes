import streamlit as st
from uuid import uuid4, UUID
from datetime import datetime
from typing import Optional, List
import pandas as pd

from cama.models import PassageType, SamplingSession
from cama.services import LocalStorageService, OfflineQueue, SyncService, SurveyDataRepository, InteractiveMapController, MeterConnectionManager, ValidationService
from cama.managers import CheckpointManager
from cama.models import SurveyStation, GasReading, QueuedItem, QueueItemType

DB = "cama.db"
OUTBOX = "outbox.json"

@st.cache_resource
def get_services():
    storage = LocalStorageService(DB)
    repo = SurveyDataRepository(storage)
    mapc = InteractiveMapController(repo)
    queue = OfflineQueue(storage)
    sync = SyncService(storage, queue, OUTBOX)
    validator = ValidationService()
    mgr = CheckpointManager(mapc, storage, validator, queue)
    return storage, repo, mapc, queue, sync, mgr

def seed_default_stations(storage):
    if not storage.list_stations():
        for name, x, y, z in [("A1",0,0,0), ("B5",10,2,0), ("C12",25,-3,-1), ("Z78",100,0,-5)]:
            storage.upsert_station(SurveyStation(name, name, x, y, z))

def page_manage_checkpoints():
    st.header("Manage Checkpoints")
    storage, repo, mapc, queue, sync, mgr = get_services()
    seed_default_stations(storage)

    with st.expander("Add checkpoint", expanded=True):
        with st.form("add_cp"):
            name = st.text_input("Name", "")
            station = st.selectbox("Survey station", [s.station_id for s in storage.list_stations()])
            passage = st.selectbox("Passage type", [p.value for p in PassageType])
            depth = st.number_input("Depth from entrance (m)", min_value=0.0, value=0.0, step=0.5)
            dist = st.number_input("Distance from station (m)", min_value=0.0, value=0.0, step=0.5)
            submitted = st.form_submit_button("Create")
            if submitted:
                try:
                    cp_id = mgr.add_checkpoint(name, PassageType(passage), station, depth, dist)
                    st.success(f"Created checkpoint {cp_id}")
                except Exception as e:
                    st.error(str(e))

    cps = mgr.list_checkpoints()
    if cps:
        df = pd.DataFrame([{
            "id": str(c.id), "name": c.name, "passage_type": c.passage_type.value,
            "station": c.survey_station_id, "depth": c.depth_from_entrance,
            "distance": c.distance_from_station, "updated_at": c.updated_at
        } for c in cps])
        st.dataframe(df, use_container_width=True)

        st.subheader("Edit / Delete")
        selected = st.selectbox("Select checkpoint to edit/delete", df["id"].tolist())
        if selected:
            cp = next(c for c in cps if str(c.id) == selected)
            new_name = st.text_input("New name", cp.name)
            new_depth = st.number_input("New depth", value=float(cp.depth_from_entrance), step=0.5)
            new_distance = st.number_input("New distance", value=float(cp.distance_from_station), step=0.5)
            cols = st.columns(2)
            with cols[0]:
                if st.button("Save changes"):
                    mgr.edit_metadata(UUID(selected), name=new_name, depth_from_entrance=new_depth, distance_from_station=new_distance)
                    st.success("Saved changes")
            with cols[1]:
                if st.button("Delete", type="secondary"):
                    mgr.delete_checkpoint(UUID(selected))
                    st.warning("Deleted checkpoint")
    else:
        st.info("No checkpoints yet. Add your first one above.")

    st.divider()
    if st.button("Flush offline queue → outbox.json"):
        n = get_services()[4].flush()
        st.success(f"Flushed {n} item(s) to outbox.json")

def page_start_session():
    st.header("Start Sampling Session")
    storage, repo, mapc, queue, sync, mgr = get_services()
    seed_default_stations(storage)
    meter = MeterConnectionManager()

    if "sess" not in st.session_state:
        st.session_state.sess = None

    if st.session_state.sess is None:
        station = st.selectbox("Anchor station", [s.station_id for s in storage.list_stations()])
        if st.button("Start session"):
            st.session_state.sess = SamplingSession(anchor_station_id=station)
            st.success("Session started")
    else:
        st.write(f"**Session ID:** {st.session_state.sess.id}")
        cols = st.columns(3)
        with cols[0]:
            if st.button("Add mock reading"):
                r = meter.produce_reading()
                st.session_state.sess.add_reading(r)
        with cols[1]:
            if st.button("End session"):
                st.session_state.sess.end()
        with cols[2]:
            if st.button("Save & Enqueue Upload"):
                storage.save_session(st.session_state.sess)
                queue.add(QueuedItem(id=uuid4(), kind=QueueItemType.SESSION_UPLOAD, payload=st.session_state.sess.to_dto()))
                st.success("Saved session and queued upload")
                st.session_state.sess = None

        if st.session_state.sess is not None:
            if st.session_state.sess.readings:
                import pandas as pd
                df = pd.DataFrame([{
                    "captured_at": r.captured_at, "O2 %": r.o2_pct, "CO ppm": r.co_ppm,
                    "H2S ppm": r.h2s_ppm, "LEL %": r.lel_pct
                } for r in st.session_state.sess.readings])
                st.dataframe(df, use_container_width=True)
            else:
                st.info("No readings yet. Click 'Add mock reading'.")

def page_stations():
    st.header("Survey Stations")
    storage, *_ = get_services()
    seed_default_stations(storage)

    st.subheader("Add / Update Station")
    with st.form("station_form"):
        sid = st.text_input("Station ID", "")
        name = st.text_input("Name", "")
        x = st.number_input("X", value=0.0)
        y = st.number_input("Y", value=0.0)
        z = st.number_input("Z", value=0.0)
        submitted = st.form_submit_button("Upsert station")
        if submitted:
            if sid and name:
                storage.upsert_station(SurveyStation(sid, name, x, y, z))
                st.success(f"Upserted station {sid}")
            else:
                st.error("Station ID and Name are required.")

    sts = storage.list_stations()
    import pandas as pd
    df = pd.DataFrame([{"id": s.station_id, "name": s.name, "x": s.x, "y": s.y, "z": s.z} for s in sts])
    st.dataframe(df, use_container_width=True)

def page_offline_queue():
    st.header("Offline Queue & Sync")
    storage, repo, mapc, queue, sync, mgr = get_services()
    st.write("Click 'Flush' to write pending items to `outbox.json`.")

    if st.button("Flush now"):
        n = sync.flush()
        st.success(f"Flushed {n} item(s).")
    try:
        import json, os
        if os.path.exists(OUTBOX):
            data = json.load(open(OUTBOX, "r", encoding="utf-8"))
            st.subheader("Outbox preview")
            st.json(data)
        else:
            st.info("No outbox.json yet.")
    except Exception as e:
        st.warning(f"Could not read outbox: {e}")

def main():
    st.set_page_config(page_title="CAMA Demo GUI", layout="wide")
    st.title("Cave Air Monitoring — Demo GUI")

    page = st.sidebar.radio("Navigate", ["Manage Checkpoints", "Start Session", "Stations", "Offline Queue"])
    if page == "Manage Checkpoints":
        page_manage_checkpoints()
    elif page == "Start Session":
        page_start_session()
    elif page == "Stations":
        page_stations()
    else:
        page_offline_queue()

if __name__ == "__main__":
    main()