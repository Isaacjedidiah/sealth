# Evaluation Notebook

# Databricks notebook source
# MAGIC %md
# MAGIC # Extraction Evaluation — Accuracy · Coverage · Robustness
# MAGIC **This notebook does NOT run extraction.** It READS already-stored results
# MAGIC and compares them to a human-labelled ground-truth CSV. No LLM calls.
# MAGIC
# MAGIC You run the extraction yourself beforehand:
# MAGIC - **once** for accuracy + coverage (writes to a table prefix, e.g. `runA_`)
# MAGIC - **a second time** into a DIFFERENT prefix (e.g. `runB_`) if you want robustness
# MAGIC
# MAGIC Then this notebook reads those stored tables and reports:
# MAGIC - **Accuracy** — confusion matrix (TP/FP/FN/TN) + precision/recall/accuracy/F1, per type
# MAGIC - **Coverage** — pages processed (chunks) vs total pages (auto-counted from raw files)
# MAGIC - **Robustness** — run A vs run B (two stored results compared)

# COMMAND ----------
# MAGIC %md ## 0 · Config — point at the ALREADY-STORED runs + the ground truth

# COMMAND ----------
from preprocessing_etl.custom.evaluation_suite import (
    evaluate_accuracy, evaluate_coverage, evaluate_robustness, full_report,
    total_pages_for)

# the table-set prefixes you already extracted into (run the pipeline first!)
PREFIX_A = "runA_"          # the run used for accuracy + coverage
PREFIX_B = "runB_"          # the SECOND run of the SAME docs, for robustness (optional)
DB = "docextract.reporting" # catalog.schema where the tables live

GROUND_TRUTH_CSV = "/Volumes/<catalog>/<schema>/<volume>/eval/ground_truth.csv"
CHART_TOL = 0.03            # charts are estimates: +-3%

# the eval documents (paths) — used ONLY to auto-count total pages (no extraction)
EVAL_SUBMISSIONS = [
    {"path": "/Volumes/<catalog>/<schema>/<volume>/docs/LCR_BankA.pptx", "entity_ref": "BankA"},
    # ... the other 4 ...
]
EVAL_ENTITY_REFS = [s.get("entity_ref") for s in EVAL_SUBMISSIONS if s.get("entity_ref")]

# COMMAND ----------
# MAGIC %md ## 1 · Load the ground-truth CSV

# COMMAND ----------
import csv
def load_ground_truth(path):
    local = (path.replace("/Volumes", "/dbfs/Volumes") if path.startswith("/Volumes")
             else path.replace("dbfs:", "/dbfs") if path.startswith("dbfs:") else path)
    rows = []
    with open(local, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({k.strip().lower(): (v.strip() if isinstance(v, str) else v)
                         for k, v in r.items()})
    for r in rows:
        try: r["page"] = int(float(r.get("page")))
        except (TypeError, ValueError): r["page"] = None
    return rows

truth_rows = load_ground_truth(GROUND_TRUTH_CSV)
print(f"loaded {len(truth_rows)} ground-truth rows")

# COMMAND ----------
# MAGIC %md ## 2 · Read the STORED claims + chunks (no extraction, just SQL)

# COMMAND ----------
class _C: pass

def read_claims(prefix):
    """Read the already-stored claims from the silver table (all extracted values)."""
    rows = spark.sql(f"""
        SELECT source_document, page, element_type, canonical_metric, value
        FROM {DB}.{prefix}silver
    """).collect()
    out = []
    for r in rows:
        c = _C()
        c.source_document=r["source_document"]; c.page=r["page"]
        c.element_type=r["element_type"]; c.canonical_metric=r["canonical_metric"]
        c.value=r["value"]
        out.append(c)
    return out

def read_chunks(prefix, entity_refs):
    where = ""
    if entity_refs:
        refs = ",".join(f"'{r}'" for r in entity_refs)
        where = f"WHERE entity_ref IN ({refs})"
    rows = spark.sql(f"""
        SELECT source_document_id AS source_document, page
        FROM {DB}.{prefix}search_chunks
        {where}
    """).collect()
    return [{"source_document": r["source_document"], "page": r["page"]} for r in rows]

claims_a = read_claims(PREFIX_A)
chunks_a = read_chunks(PREFIX_A, EVAL_ENTITY_REFS)
print(f"run A: {len(claims_a)} claims, {len(chunks_a)} chunks")

# COMMAND ----------
# MAGIC %md ## 3 · ACCURACY — confusion matrix vs ground truth (stored run A)

# COMMAND ----------
accuracy = evaluate_accuracy(claims_a, truth_rows, chart_tol=CHART_TOL)

# COMMAND ----------
# MAGIC %md ## 4 · COVERAGE — pages processed (chunks) vs total pages (auto from raw files)

# COMMAND ----------
TOTAL_PAGES = total_pages_for(EVAL_SUBMISSIONS)   # auto page count from raw files
print("total pages (auto):", TOTAL_PAGES)
coverage = evaluate_coverage(chunks_a, total_pages_by_doc=TOTAL_PAGES)

# COMMAND ----------
# MAGIC %md ## 5 · ROBUSTNESS — compare the TWO stored runs (A vs B)
# MAGIC Only if you extracted the same documents into PREFIX_B as well.

# COMMAND ----------
robustness = None
try:
    claims_b = read_claims(PREFIX_B)
    print(f"run B: {len(claims_b)} claims")
    robustness = evaluate_robustness(claims_a, claims_b, chart_tol=CHART_TOL)
except Exception as e:
    print(f"(skipping robustness — PREFIX_B not available: {e})")

# COMMAND ----------
# MAGIC %md ## 6 · FULL REPORT

# COMMAND ----------
print(full_report(accuracy=accuracy, coverage=coverage, robustness=robustness))