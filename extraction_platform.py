"""
Content Extraction — Self-Service App (IDEATION PROTOTYPE)
=========================================================
A Streamlit UI that lets any user run the content-extraction pipeline on their
own: point at a volume, choose where output tables go, name (or reuse) a table
set, and trigger a run — without needing the pipeline's author.

This is an IDEATION prototype: the UI + flow are real; the Databricks calls are
stubbed behind a thin `backend` layer so the shape is clear and you can wire the
real Jobs API / Databricks SDK in one place later.

Run:  streamlit run extraction_app.py
"""
import streamlit as st
import time
from datetime import datetime

# =============================================================================
# BACKEND (stubbed) — swap these for real Databricks SDK / Jobs API calls later.
# Keeping all Databricks interaction in ONE place makes the prototype honest
# about where the real integration goes.
# =============================================================================
class Backend:
    """Thin seam over Databricks. Replace the bodies with real SDK calls:
      * list_volumes / list_table_sets  -> Unity Catalog queries
      * trigger_run                     -> Jobs API run-now with parameters
      * get_run_status                  -> Jobs API get-run
    """
    def list_catalogs(self):
        return ["docextract", "reporting_prod", "sandbox"]

    def list_schemas(self, catalog):
        return {"docextract": ["reporting", "staging"],
                "reporting_prod": ["gold", "silver"],
                "sandbox": ["user_tests"]}.get(catalog, ["default"])

    def list_existing_table_sets(self, catalog, schema):
        # a "table set" = a prefix (e.g. v5_) that already has gold/silver/etc.
        demo = {("docextract", "reporting"): ["v5_", "v6_", "bankA_2024_"]}
        return demo.get((catalog, schema), [])

    def volume_exists(self, path):
        return path.startswith("/Volumes/") and len(path.split("/")) >= 5

    def count_documents(self, volume_path):
        return 128 if self.volume_exists(volume_path) else 0  # stub

    def trigger_run(self, params):
        # REAL: databricks Jobs API run-now with `params` as notebook/job params.
        run_id = f"run_{int(time.time())}"
        st.session_state.setdefault("_runs", {})[run_id] = {
            "params": params, "status": "RUNNING", "started": datetime.now(),
            "stages": ["ai_parse", "extract", "gate", "store", "index"], "stage_i": 0}
        return run_id

    def get_run_status(self, run_id):
        r = st.session_state.get("_runs", {}).get(run_id)
        if not r:
            return None
        # stub: advance one stage each poll
        if r["status"] == "RUNNING":
            r["stage_i"] += 1
            if r["stage_i"] >= len(r["stages"]):
                r["status"] = "SUCCESS"
        return r


backend = Backend()

# =============================================================================
# UI
# =============================================================================
st.set_page_config(page_title="Content Extraction", page_icon="📊", layout="centered")
st.title("📊 Content Extraction — Self-Service Run")
st.caption("Point at your documents, choose where results go, and run — no code required.")

# ---- Step 1: source volume ----
st.header("1 · Source documents")
volume_path = st.text_input(
    "Unity Catalog volume path (where your documents are)",
    placeholder="/Volumes/<catalog>/<schema>/<volume>/<folder>")
if volume_path:
    if backend.volume_exists(volume_path):
        n = backend.count_documents(volume_path)
        st.success(f"Found the volume. ~{n} document(s) detected.")
    else:
        st.error("That doesn't look like a valid /Volumes/... path.")

# ---- Step 2: output location ----
st.header("2 · Output location")
col1, col2 = st.columns(2)
with col1:
    catalog = st.selectbox("Catalog (where tables are written)", backend.list_catalogs())
with col2:
    schema = st.selectbox("Schema", backend.list_schemas(catalog))

# ---- Step 3: table set (reuse or create) ----
st.header("3 · Table set")
existing = backend.list_existing_table_sets(catalog, schema)
mode = st.radio("Use an existing table set, or create a new one?",
                ["Create new", "Reuse existing"], horizontal=True)
if mode == "Reuse existing":
    if existing:
        prefix = st.selectbox("Existing table sets", existing)
        st.info(f"Results will be ADDED to the **{prefix}** tables in "
                f"`{catalog}.{schema}`.")
    else:
        st.warning("No existing table sets here yet — switch to 'Create new'.")
        prefix = None
else:
    raw = st.text_input("New table-set name (a short prefix)", placeholder="bankA_2024")
    prefix = (raw.strip().rstrip("_") + "_") if raw.strip() else None
    if prefix:
        if prefix.rstrip("_") in [e.rstrip("_") for e in existing]:
            st.error(f"'{prefix}' already exists — pick another name or reuse it.")
            prefix = None
        else:
            st.info(f"Will CREATE new tables: `{catalog}.{schema}.{prefix}gold`, "
                    f"`{prefix}silver`, `{prefix}review`, …")

# ---- Step 4: options ----
st.header("4 · Options")
use_sonnet = st.toggle("Read charts with the vision model (slower, richer)", value=True)
limit = st.number_input("Limit (0 = all documents)", min_value=0, value=0, step=1)

# ---- Step 5: run ----
st.header("5 · Run")
ready = bool(volume_path and backend.volume_exists(volume_path) and prefix and catalog and schema)
if not ready:
    st.caption("Fill in a valid volume, output location, and table set to enable Run.")

if st.button("▶ Run extraction", type="primary", disabled=not ready):
    params = {
        "volume_path": volume_path,
        "catalog": catalog, "schema": schema, "table_prefix": prefix,
        "use_sonnet": use_sonnet, "limit": int(limit),
    }
    run_id = backend.trigger_run(params)
    st.session_state["active_run"] = run_id
    st.success(f"Started run **{run_id}**.")

# ---- live status ----
active = st.session_state.get("active_run")
if active:
    st.header("Run status")
    r = backend.get_run_status(active)
    if r:
        stages = r["stages"]; done = r["stage_i"]
        st.progress(min(done / len(stages), 1.0))
        for i, stg in enumerate(stages):
            icon = "✅" if i < done else ("⏳" if i == done and r["status"]=="RUNNING" else "⬜")
            st.write(f"{icon} {stg}")
        if r["status"] == "SUCCESS":
            st.success("Run complete. Tables written to "
                       f"`{r['params']['catalog']}.{r['params']['schema']}."
                       f"{r['params']['table_prefix']}…`")
            st.balloons()
        else:
            st.info("Running… (this view polls for progress)")
            time.sleep(1)
            st.rerun()
