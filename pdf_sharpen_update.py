# PDF SHARPEN
"""PDF page SHARPENING pre-processing for ai_parse_document.

Poor page-image quality (soft / low-contrast scans) makes ai_parse_document
misread text (e.g. 'SSE' -> 'S&C') and can distort table-structure detection.
Applying an image SHARPNESS enhancement to each page BEFORE ai_parse reads it
fixes these at the SOURCE — deterministically — which is far better than any
downstream compensation.

This module is PDF-ONLY (PPTX stays on the normal native path). It works in two
steps so the brightening is separate from, and does not disturb, the existing
extraction:

  1. sharpen_pdf_to_folder(pdf_path, out_root)
        Renders each PDF page, applies SHARPNESS, and writes
        <out_root>/<document_name>/page_<NNN>.png  (page_001 = first page).
        The folder is the EXACT document name (only '/' -> '_', the one
        filesystem-forbidden char) for full traceability.

  2. run_ai_parse_on_image(spark, image_path, image_output_path)
        Runs ai_parse_document on ONE sharpened page image and returns the same
        VARIANT the normal pipeline consumes — so the existing
        parse_ai_parse_response / hybrid_extract_document path is unchanged.

  iter_sharpened_pages(out_root)
        Yields (source_document, page, image_path) for every sharpened page, so
        a batch loop can parse each image and tag claims with the document + page
        (document from the folder, page from the file name).

Tunables: SHARPNESS (the enhancement factor) and RENDER_DPI (page render
resolution). SHARPNESS is set to the value found to fix the misreads.
"""
from __future__ import annotations

import io
import os
import re
import uuid
import json
from typing import Iterator, Tuple, List


# --- tunables -------------------------------------------------------------
SHARPNESS = 35.0        # PIL Sharpness factor found to fix the misreads
RENDER_DPI = 200        # page render resolution before sharpening


def _local(path: str) -> str:
    """Map a Volume / dbfs path to a local filesystem path for PIL / PyMuPDF."""
    if path.startswith("/Volumes"):
        return path.replace("/Volumes", "/dbfs/Volumes")
    if path.startswith("dbfs:"):
        return path.replace("dbfs:", "/dbfs")
    return path


def _vol(path: str) -> str:
    """Map a local /dbfs path back to a Volume path (for Spark READ_FILES)."""
    if path.startswith("/dbfs/Volumes"):
        return path.replace("/dbfs/Volumes", "/Volumes")
    return path


def _safe_folder(document_name: str) -> str:
    """Keep the document name EXACTLY; only replace '/' (the single filesystem-
    forbidden char in a path segment) with '_'. Nothing else is altered."""
    return document_name.replace("/", "_")


def _page_no_from_name(filename: str):
    m = re.search(r"page_(\d+)\.png$", filename)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# STEP 1 — sharpen a PDF's pages into a per-document folder
# ---------------------------------------------------------------------------
def sharpen_pdf_to_folder(pdf_path: str, out_root: str,
                          sharpness: float = SHARPNESS,
                          dpi: int = RENDER_DPI) -> str:
    """Render each page of the PDF, apply SHARPNESS, and save to
    <out_root>/<document_name>/page_<NNN>.png (1-based). Returns the folder path.
    Requires PyMuPDF (fitz) and Pillow."""
    import fitz                                   # PyMuPDF
    from PIL import Image, ImageEnhance

    document_name = os.path.basename(pdf_path)    # EXACT name, with extension
    folder = os.path.join(out_root, _safe_folder(document_name))
    os.makedirs(_local(folder), exist_ok=True)

    doc = fitz.open(_local(pdf_path))
    try:
        for i in range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img = ImageEnhance.Sharpness(img).enhance(sharpness)   # ONLY sharpness
            fname = f"page_{i + 1:03d}.png"                        # page_001...
            img.save(_local(os.path.join(folder, fname)), format="PNG")
        n = doc.page_count
    finally:
        doc.close()
    return folder


def sharpen_pdfs(pdf_paths: List[str], out_root: str,
                 sharpness: float = SHARPNESS, dpi: int = RENDER_DPI) -> List[str]:
    """Sharpen a list of PDFs. Returns the list of folders written."""
    return [sharpen_pdf_to_folder(p, out_root, sharpness, dpi) for p in pdf_paths]


# ---------------------------------------------------------------------------
# iterate the sharpened pages (document from folder, page from file name)
# ---------------------------------------------------------------------------
def iter_sharpened_pages(out_root: str) -> Iterator[Tuple[str, int, str]]:
    """Yield (source_document, page, image_volume_path) for every sharpened page.
    source_document = the folder name (the exact document name); page is 1-based
    from the file name. image path is returned as a Volume path for Spark."""
    root_local = _local(out_root)
    if not os.path.isdir(root_local):
        return
    for document_name in sorted(os.listdir(root_local)):
        folder_local = os.path.join(root_local, document_name)
        if not os.path.isdir(folder_local):
            continue
        for fname in sorted(f for f in os.listdir(folder_local) if f.endswith(".png")):
            page = _page_no_from_name(fname)
            if page is None:
                continue
            yield document_name, page, _vol(os.path.join(folder_local, fname))


# ---------------------------------------------------------------------------
# STEP 2 — ai_parse ONE sharpened image (returns the same VARIANT as normal)
# ---------------------------------------------------------------------------
def run_ai_parse_on_image(spark, image_path: str, image_output_path: str = None):
    """Run ai_parse_document on a single (sharpened) page image. Returns the
    same VARIANT value the normal pipeline consumes, so downstream parsing is
    unchanged. A unique temp view avoids Spark plan caching (same precaution as
    the main _run_ai_parse)."""
    view = f"_aip_sharp_{uuid.uuid4().hex}"
    df = spark.read.format("binaryFile").load(image_path)
    df.createOrReplaceTempView(view)
    if image_output_path:
        return spark.sql(
            f"SELECT ai_parse_document(content, "
            f"map('version','2.0','imageOutputPath','{image_output_path}')) AS p "
            f"FROM {view}"
        ).collect()[0]["p"]
    return spark.sql(
        f"SELECT ai_parse_document(content, map('version','2.0')) AS p FROM {view}"
    ).collect()[0]["p"]


# ---------------------------------------------------------------------------
# SHARPEN-ONLY batch (Design B): sharpen the PDFs in a submission list into a
# per-run folder of page images. NO extraction here -- ai_parse_pipeline then
# consumes these images. Keeping sharpening separate from extraction means a
# sharpen issue never touches the proven extraction/storage path.
# ---------------------------------------------------------------------------
def sharpen_submissions(submissions, sharpen_root, *, run_id=None,
                        sharpness=SHARPNESS, dpi=RENDER_DPI, dbutils=None):
    """Sharpen the PDF submissions into <sharpen_root>/<run_id>/<document>/page_<NNN>.png.
    Returns {run_id, root, documents: [{source_document, folder, pages}]}.
    Non-PDF submissions are ignored (they go through ai_parse_pipeline normally).
    The caller passes the SAME run_id to ai_parse_pipeline so it finds these images."""
    import os as _os
    rid = run_id or uuid.uuid4().hex
    run_root = f"{sharpen_root.rstrip('/')}/{rid}"
    out = {"run_id": rid, "root": run_root, "documents": []}
    for sub in submissions:
        path = sub["path"] if isinstance(sub, dict) else sub
        if not str(path).lower().endswith(".pdf"):
            continue                                  # PDFs only
        folder = sharpen_pdf_to_folder(path, run_root, sharpness, dpi)
        pages = sorted(f for f in _os.listdir(_local(folder)) if f.endswith(".png"))
        out["documents"].append({
            "source_document": _os.path.basename(path),
            "folder": _vol(folder) if folder.startswith("/dbfs") else folder,
            "pages": len(pages),
        })
    return out

# sharpen notebook
# Databricks notebook source
# MAGIC %md
# MAGIC # Extraction with PDF sharpening (integrated, one run)
# MAGIC Set sharpen_pdfs=True. PDFs are SHARPENED into THIS run's fresh folder
# MAGIC (same per-run pattern as figure images) and ai_parsed from there; non-PDFs
# MAGIC use the normal raw path. run_id is internal — no hand-off. Extraction +
# MAGIC storage unchanged.
# COMMAND ----------
# MAGIC %pip install PyMuPDF
# COMMAND ----------
dbutils.library.restartPython()
# COMMAND ----------
import dataclasses
from preprocessing_etl.custom.ai_parse_pipeline import run_ai_parse_batch
from preprocessing_etl.custom.storage import DeltaLakeStorage
from preprocessing_etl.shared.config import CONFIG
from preprocessing_etl.shared.llm_client import LLMClient

SUBMISSIONS = [
    {"path": "/Volumes/<cat>/<sch>/<vol>/submissions/LCR_BankA.pdf",
     "team": "lcr", "report_type": "lcr", "entity_ref": "BankA"},
    {"path": "/Volumes/<cat>/<sch>/<vol>/submissions/deck.pptx",
     "team": "lcr", "report_type": "lcr", "entity_ref": "BankA"},
]
IMG_OUT = "/Volumes/<cat>/<sch>/<vol>/figures"   # figure renders + sharpened pages go under here per run
TABLE_PREFIX = "v6_"
HOST = "<host>"; TOKEN = "<token>"

CONFIG.storage = dataclasses.replace(CONFIG.storage, table_prefix=TABLE_PREFIX)
storage = DeltaLakeStorage(spark=spark)
client  = LLMClient(base_url=f"{HOST}/serving-endpoints", api_key=TOKEN)
dbutils.fs.mkdirs(IMG_OUT)

def run_async(coro):
    import asyncio
    try:
        import nest_asyncio; nest_asyncio.apply()
    except Exception: pass
    try: loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
# COMMAND ----------
result = run_ai_parse_batch(
    spark, SUBMISSIONS, storage,
    use_sonnet=True, llm_client=client, run_async_fn=run_async,
    image_output_path=IMG_OUT, dbutils=dbutils,
    sharpen_pdfs=True)                 # <-- PDFs sharpened in-run; non-PDFs raw
print("documents:", result.documents, "claims:", result.claims_total,
      "gold:", result.gold_total, "failures:", result.failures)

# ai parse pipeline updates

# CHANGE 1 — add the two parameters to the run_ai_parse_batch signature. Find:
                       folder_map=None) -> BatchResult:

# Replace with:
                       folder_map=None, sharpen_pdfs=False,
                       sharpen_root=None) -> BatchResult:

# CHANGE 2 — add the sharpen flag + the sharpening branch in the parse block.

# 2a — after subs = submissions[:limit] if limit else submissions, add the sharpen flag. Find:
    subs = submissions[:limit] if limit else submissions

    for sub in subs:
        path = sub["path"]
        fname = os.path.basename(path)
        try:

# Replace with:
    subs = submissions[:limit] if limit else submissions

    # SHARPENED-PDF support: when sharpen_pdfs is on, a PDF's pages are SHARPENED
    # (fixes OCR misreads from soft scans) into THIS run's own fresh folder --
    # the SAME per-run/per-document pattern as the figure images, so the run_id
    # is internal (no hand-off) and folders are fresh (reproducible).
    _sharpen_on = bool(sharpen_pdfs)
    _sharpen_base = (sharpen_root or image_output_path)

    for sub in subs:
        path = sub["path"]
        fname = os.path.basename(path)
        try:

# 2b — replace your parse block (the if option_a: ... parsed = _run_ai_parse(...) section). Find YOUR current version — it looks like this (the per-run folder version you pasted):
            crop_fn = None
            _file_img_dir = None
            _file_crop_dir = None
            if option_a:
                # PRODUCTION reproducibility: give THIS file, THIS run its own
                # fresh image AND crop folders ...
                import re as _re
                _safe_doc = _re.sub(r"[^A-Za-z0-9_.-]", "_", fname)[:80]
                _base = f"{image_output_path.rstrip('/')}/{result.run_id}/{_safe_doc}"
                _file_img_dir = f"{_base}/images"
                _file_crop_dir = f"{_base}/crops"
                try:
                    dbutils.fs.mkdirs(_file_img_dir)
                    dbutils.fs.mkdirs(_file_crop_dir)
                except Exception:
                    pass
                parsed = _run_ai_parse(spark, path, _file_img_dir)
            else:
                parsed = _run_ai_parse(spark, path)

# Replace with (keeps your per-run folders, adds the sharpen branch before the parse):
            crop_fn = None
            _file_img_dir = None
            _file_crop_dir = None
            if option_a:
                import re as _re
                _safe_doc = _re.sub(r"[^A-Za-z0-9_.-]", "_", fname)[:80]
                _base = f"{image_output_path.rstrip('/')}/{result.run_id}/{_safe_doc}"
                _file_img_dir = f"{_base}/images"
                _file_crop_dir = f"{_base}/crops"
                try:
                    dbutils.fs.mkdirs(_file_img_dir)
                    dbutils.fs.mkdirs(_file_crop_dir)
                except Exception:
                    pass

            # SHARPENED PDF path: sharpen each page into THIS run's fresh folder
            # (same per-run/per-document pattern), then ai_parse the SHARPENED
            # images. Non-PDFs / sharpen-off -> the normal raw path. Sharpening
            # lives in pdf_sharpen so a sharpen issue never touches extraction.
            if _sharpen_on and str(path).lower().endswith(".pdf"):
                import re as _re2, json as _json
                from .pdf_sharpen import (sharpen_pdf_to_folder,
                                          iter_sharpened_pages,
                                          run_ai_parse_on_image)
                _sd = _re2.sub(r"[^A-Za-z0-9_.-]", "_", fname)[:80]
                _sharp_dir = (f"{(_sharpen_base or image_output_path).rstrip('/')}/"
                              f"{result.run_id}/{_sd}/sharpened")
                try:
                    dbutils.fs.mkdirs(_sharp_dir)
                except Exception:
                    pass
                sharpen_pdf_to_folder(path, _sharp_dir)
                _merged = []
                for _sdoc, _page, _img in iter_sharpened_pages(_sharp_dir):
                    _pp = run_ai_parse_on_image(spark, _img, _file_img_dir)
                    _d = (_json.loads(_pp) if isinstance(_pp, str)
                          else _json.loads(_pp.toJson()) if hasattr(_pp, "toJson")
                          else _pp)
                    for _el in _d.get("document", _d).get("elements", []):
                        _el["_sharpen_page"] = _page
                        _merged.append(_el)
                parsed = {"document": {"elements": _merged}}
            elif option_a:
                parsed = _run_ai_parse(spark, path, _file_img_dir)
            else:
                parsed = _run_ai_parse(spark, path)
                
# new notebook

# Databricks notebook source
# MAGIC %md
# MAGIC # Extraction with PDF sharpening (integrated)
# MAGIC Uses the existing discover_submissions. PDFs are sharpened in-run (fresh
# MAGIC per-run folders, internal run_id); non-PDFs use the normal raw path.
# MAGIC Only addition vs the normal run: sharpen_pdfs=True.

# COMMAND ----------
# MAGIC %pip install PyMuPDF
# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
import os, dataclasses
from preprocessing_etl.custom.ai_parse_pipeline import run_ai_parse_batch, discover_submissions
from preprocessing_etl.custom.storage import DeltaLakeStorage
from preprocessing_etl.shared.config import CONFIG
from preprocessing_etl.shared.llm_client import LLMClient

TABLE_PREFIX = "v6_"
IMG_OUT = "/Volumes/<cat>/<sch>/<vol>/figures"
HOST = "<host>"; TOKEN = "<token>"

CONFIG.storage = dataclasses.replace(CONFIG.storage, table_prefix=TABLE_PREFIX)
storage = DeltaLakeStorage(spark=spark)
client  = LLMClient(base_url=f"{HOST}/serving-endpoints", api_key=TOKEN)
dbutils.fs.mkdirs(IMG_OUT)

def run_async(coro):
    import asyncio
    try:
        import nest_asyncio; nest_asyncio.apply()
    except Exception: pass
    try: loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

# COMMAND ----------
# MAGIC %md ## Discover submissions (existing)
# COMMAND ----------
submissions = discover_submissions(CONFIG.storage.volume_root)
print(f"Discovered {len(submissions)} submission(s) under {CONFIG.storage.volume_root}")
for s in submissions[:5]:
    print(" ", s["team"], "/", s["report_type"], "/",
          os.path.basename(s["path"]), "->", s.get("entity_ref"))

# COMMAND ----------
# MAGIC %md ## Run — PDFs sharpened in-run, non-PDFs raw
# COMMAND ----------
result = run_ai_parse_batch(
    spark, submissions, storage,
    use_sonnet=True, llm_client=client, run_async_fn=run_async,
    image_output_path=IMG_OUT, dbutils=dbutils,
    sharpen_pdfs=True)          # <-- the ONLY addition vs your normal run

print("documents:", result.documents, "claims:", result.claims_total,
      "gold:", result.gold_total, "failures:", result.failures)