            crop_fn = None
            _file_img_dir = None
            _file_crop_dir = None
            if option_a:
                # PRODUCTION reproducibility: give THIS file, THIS run its own
                # fresh image AND crop folders (no manual folder creation in the
                # notebook). Reusing one folder is unstable — cloud-storage
                # eventual consistency means a cleared folder can still hold the
                # previous run's images, corrupting the page->image mapping
                # ("works first run, duplicates the second"). BOTH folders are
                # made fresh (an earlier fix made only the image folder fresh, so
                # the crop folder still accumulated -> this makes both fresh).
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
                

                crop_fn = _build_figure_crop_fn(
                    spark, image_output_path, dbutils,
                    all_elements=_els, save_crops_to=_SAVE_CROPS_TO)
                
                crop_fn = _build_figure_crop_fn(
                    spark, _file_img_dir, dbutils,
                    all_elements=_els,
                    save_crops_to=(_file_crop_dir or _SAVE_CROPS_TO))


import dataclasses, asyncio
from preprocessing_etl.custom.ai_parse_pipeline import run_ai_parse_batch
from preprocessing_etl.custom.storage import DeltaLakeStorage
from preprocessing_etl.search.ai_search_store import AzureAISearchStore
from preprocessing_etl.shared.config import CONFIG
from preprocessing_etl.shared.llm_client import LLMClient

_orig = CONFIG.storage
CONFIG.storage = dataclasses.replace(CONFIG.storage, table_prefix="v5_")
storage = DeltaLakeStorage(spark=spark)
search_store = AzureAISearchStore()

HOST = "<host>"
TOKEN = "<token>"
BASE_URL = f"{HOST}/serving-endpoints"
client = LLMClient(base_url=BASE_URL, api_key=TOKEN)

def run_async(coro):
    import asyncio
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except Exception:
        pass
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

# --- base image folder (pipeline creates fresh per-file/per-run subfolders) ---
IMG_OUT = "/Volumes/<catalog>/<schema>/<volume>/ai_parse_figures"

result = run_ai_parse_batch(
    spark, submissions, storage,
    search_store=search_store,
    use_sonnet=True,
    llm_client=client,
    run_async_fn=run_async,
    image_output_path=IMG_OUT,
    dbutils=dbutils,
    limit=1)

print(f"docs={result.documents} claims={result.claims_total} "
      f"gold={result.gold_total} review={result.review_total} "
      f"quarantined={result.quarantined} indexed={result.indexed_chunks}")
if result.failures:
    for f, e in result.failures: print(f"  FAILED {f}: {e}")

CONFIG.storage = _orig
spark.sql("SHOW TABLES IN docextract.reporting LIKE 'v5_*'").show(truncate=False)

def _enhance_for_vision(region, ImageEnhance, ImageFilter, Image, target_min=1400,
                        max_scale=3):
    """Make a chart crop more legible for the vision model: upscale small crops
    with LANCZOS, then apply light sharpening and a slight contrast lift. Moderate
    on purpose -- over-sharpening introduces artifacts. Scales BOTH dimensions by
    the same factor (aspect ratio preserved -- no squeezing/distortion). Returns
    the enhanced image; on any error returns the original (never fails the crop)."""
    try:
        w, h = region.size
        if w <= 0 or h <= 0:
            return region
        # upscale so the width reaches ~target_min px (capped), keeping aspect ratio
        if w < target_min:
            scale = min(max_scale, max(1, round(target_min / w)))
            if scale > 1:
                region = region.resize((w * scale, h * scale), Image.LANCZOS)
        # light unsharp mask (better than plain Sharpness for text/edges)
        region = region.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))
        # slight contrast lift to separate text from background
        region = ImageEnhance.Contrast(region).enhance(1.08)
        return region
    except Exception:
        return region

    from PIL import Image, ImageEnhance, ImageFilter
    import base64 as _b64, io as _io, json as _json

            # ENHANCE the crop for Sonnet: chart crops are often small/blurry
            # (the source page renders at limited resolution). Upscaling with a
            # high-quality filter + light sharpening/contrast makes the text and
            # data points more legible for the vision model.
            region = _enhance_for_vision(region, ImageEnhance, ImageFilter, Image)

            buf = _io.BytesIO()
            region.save(buf, format="PNG")
            buf.seek(0)
            return _b64.b64encode(buf.read()).decode()

# FILE 1: hybrid_extraction.py

# Edit 1 — add the firm_xaxis_cfg parameter. Find:
                            vision_model_key: str = "tier2",
                            use_sonnet: bool = False) -> list:

# Edit 2 — add the position-capturing prompt. Find:
CHART_DIGITISATION_PROMPT = (

# Add this right before it:
# For the firm-specific x-axis case: the SAME single call also returns each point's
# x-position and the printed x-axis labels + positions, so the geometry can
# resolve periods IN-MEMORY without a second Sonnet call (no doubled calls).
CHART_DIGITISATION_PROMPT_WITH_POS = (
    "You are a chart digitisation engine. Read ONLY the CHARTS and GRAPHS in this "
    "image and return their data points as a JSON array \u2014 no prose:\n"
    '[{"label": "<chart title | series name from legend | category/x-axis label>", '
    '"value": <number>, "unit": "<%/\u00a3m/bps/count/etc>", '
    '"x_center": <approx horizontal PIXEL position of this bar/point centre>}]\n'
    "ALSO return the printed x-axis labels with their positions as a SECOND array "
    'under the key "xlabels": [{"text": "<label e.g. Jan 2025>", "x_center": <pixel>}].\n'
    "Return a JSON object: {\"points\": [...], \"xlabels\": [...]}. Use the number "
    "PRINTED on/beside each bar/point exactly; do not estimate from the axis scale."
)


CHART_DIGITISATION_PROMPT = (

# Edit 3 — add the single-call helper. Find:
            def sonnet_points_to_claims(points: list[dict], el: ParsedElement, filename: str,
# Add this right before it:
def _sonnet_read_image_with_pos(run_async_fn, llm_client, model_key, content, img_b64):
    """ONE Sonnet call that returns chart points (value + x_center) AND the printed
    x-axis labels (text + x_center), for the firm-specific geometry. Returns
    (points, xlabels). No second call. Sends the ai_parse `content` (description)
    like the normal read, so context is preserved."""
    import json as _json, re as _re
    try:
        from ..shared.llm_client import EXTRACTION_TOOL_SCHEMA
    except Exception:
        EXTRACTION_TOOL_SCHEMA = {"name": "extract"}
    try:
        resp = run_async_fn(llm_client.extract(
            model_key, CHART_DIGITISATION_PROMPT_WITH_POS, content or "",
            EXTRACTION_TOOL_SCHEMA, image_base64=img_b64))
    except Exception:
        return [], []
    ta = getattr(resp, "tool_arguments", None)
    data = ta if isinstance(ta, dict) else None
    if data is None:
        txt = getattr(resp, "text", "") or ""
        m = _re.search(r"\{.*\}", txt, _re.S)
        try:
            data = _json.loads(m.group(0)) if m else {}
        except Exception:
            data = {}
    points = (data.get("points") or data.get("claims") or data.get("data") or [])
    xlabels = data.get("xlabels") or data.get("labels") or []
    norm = []
    for p in points if isinstance(points, list) else []:
        if isinstance(p, dict):
            norm.append({"label": p.get("label") or p.get("field_name") or "",
                         "value": p.get("value"),
                         "x_center": p.get("x_center")})
    return norm, (xlabels if isinstance(xlabels, list) else [])

# Edit 4 — replace the figure-read block. Find:
                pts = _sonnet_read_image(
                    run_async_fn, llm_client, vision_model_key,
                    CHART_DIGITISATION_PROMPT, content, img_b64)
                if pts:
                    claims.extend(sonnet_points_to_claims(pts, el, filename, entity_ref))
                else:
                    claims.extend(desc_claims)   # vision found nothing -> keep desc
# Replace with:
                # For the FIRM-SPECIFIC x-axis case, one call returns values AND
                # positions; the geometry then resolves periods IN-MEMORY (no 2nd
                # Sonnet call -> no doubled calls / throttling). Otherwise the
                # normal single read.
                if firm_xaxis_cfg:
                    pts, xlabels = _sonnet_read_image_with_pos(
                        run_async_fn, llm_client, vision_model_key, content, img_b64)
                    if pts:
                        fig_claims = sonnet_points_to_claims(pts, el, filename, entity_ref)
                        try:
                            from .firm_xaxis import resolve_axis_labels
                            bars = [{"id": i, "series": p.get("label", ""),
                                     "value": str(p.get("value", "")),
                                     "x_center": p.get("x_center", 0)}
                                    for i, p in enumerate(pts) if p.get("x_center") is not None]
                            labs = [{"text": l.get("text", ""), "x_center": l.get("x_center", 0)}
                                    for l in (xlabels or []) if l.get("x_center") is not None]
                            if bars and labs:
                                id_to_period, status = resolve_axis_labels(
                                    bars, labs,
                                    monthly_step=firm_xaxis_cfg.get("monthly_step", 1),
                                    x_tolerance=firm_xaxis_cfg.get("x_tolerance", 8))
                                if status in ("geometry", "geometry_month"):
                                    vp = {}
                                    for i, p in enumerate(pts):
                                        per = id_to_period.get(i)
                                        if per and per != "FLAG_REVIEW":
                                            vp[(str(p.get("label", "")), str(p.get("value", "")))] = per
                                    for cl in fig_claims:
                                        per = vp.get((str(getattr(cl, "field_name", "") or ""),
                                                      str(getattr(cl, "value", "") or "")))
                                        if per:
                                            setattr(cl, "as_at_date", per)
                        except Exception:
                            pass
                        claims.extend(fig_claims)
                    else:
                        claims.extend(desc_claims)
                else:
                    pts = _sonnet_read_image(
                        run_async_fn, llm_client, vision_model_key,
                        CHART_DIGITISATION_PROMPT, content, img_b64)
                    if pts:
                        claims.extend(sonnet_points_to_claims(pts, el, filename, entity_ref))
                    else:
                        claims.extend(desc_claims)   # vision found nothing -> keep desc

# FILE 2: ai_parse_pipeline.py

# Edit — resolve the config and pass it. Find:

            claims = hybrid_extract_document(
                ai_parse_response=parsed, filename=fname,
                team=sub["team"], report_type=sub["report_type"],
                entity_ref=sub.get("entity_ref"),
                use_sonnet=option_a, llm_client=llm_client,
                run_async_fn=run_async_fn, crop_figure_image=crop_fn)
# Replace with:
            # firm-specific x-axis geometry config (None -> normal path, no-op).
            # Resolved here so the SINGLE-call position read + in-memory geometry
            # applies only to the configured firm.
            _fx_cfg = None
            try:
                from .firm_xaxis import _firm_config
                from .entity_path import parse_entity_path as _pep
                _ent = _pep(path)
                _fx_cfg = _firm_config(
                    firm_id=sub.get("entity_id") or _ent.get("entity_id"),
                    firm_name=sub.get("entity_name") or _ent.get("entity_name"))
            except Exception:
                _fx_cfg = None

            claims = hybrid_extract_document(
                ai_parse_response=parsed, filename=fname,
                team=sub["team"], report_type=sub["report_type"],
                entity_ref=sub.get("entity_ref"),
                use_sonnet=option_a, llm_client=llm_client,
                run_async_fn=run_async_fn, crop_figure_image=crop_fn,
                firm_xaxis_cfg=_fx_cfg)

# hybrid_extraction
# Find this (the start of _sonnet_read_image_with_pos):
    import json as _json, re as _re
    try:
        from ..shared.llm_client import EXTRACTION_TOOL_SCHEMA
    except Exception:
        EXTRACTION_TOOL_SCHEMA = {"name": "extract"}
    try:
        resp = run_async_fn(llm_client.extract(
            model_key, CHART_DIGITISATION_PROMPT_WITH_POS, content or "",
            EXTRACTION_TOOL_SCHEMA, image_base64=img_b64))
    except Exception:
        return [], []
# Replace with:
    import json as _json, re as _re
    # CUSTOM schema matching the WITH_POS prompt (points + xlabels) -- NOT the
    # normal claims schema, so x-axis LABELS never leak into the claims/gold.
    _POS_SCHEMA = {
        "name": "record_chart_with_positions",
        "description": "Chart data points (value + x position) and x-axis labels (text + x position).",
        "parameters": {"type": "object", "properties": {
            "points": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "value": {"type": "string"},
                "unit": {"type": "string"}, "x_center": {"type": "number"}},
                "required": ["value", "x_center"]}},
            "xlabels": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "x_center": {"type": "number"}},
                "required": ["text", "x_center"]}},
        }, "required": ["points"]},
    }
    try:
        resp = run_async_fn(llm_client.extract(
            model_key, CHART_DIGITISATION_PROMPT_WITH_POS, content or "",
            _POS_SCHEMA, image_base64=img_b64))
    except Exception:
        return [], []

# inspect

# =============================================================================
#  ONE script to check THREE things from ai_parse_document output:
#   1. CONFIDENCE  — is there a score, and is it LOW on bad tables?
#   2. FOOTNOTE/LEGEND — what text does ai_parse give for legends?
#   3. BEAUTIFULSOUP — does it parse a malformed table better than our parser?
#  Handles the VariantVal type (to_json -> json.loads).
# =============================================================================
import json
from collections import Counter

DOC = "/Volumes/<catalog>/<schema>/<volume>/docs/your_doc.pptx"   # <-- set this
IMG_OUT = "/Volumes/<catalog>/<schema>/<volume>/inspect_imgs"
dbutils.fs.mkdirs(IMG_OUT)

# ---- run ai_parse + convert VARIANT to a plain dict ----
spark.sql("CREATE OR REPLACE TEMP VIEW _insp AS "
          f"SELECT * FROM READ_FILES('{DOC}', format => 'binaryFile')")
df = spark.sql(f"""
    SELECT ai_parse_document(content,
        map('version','2.0','imageOutputPath','{IMG_OUT}')) AS parsed
    FROM _insp
""")
d = json.loads(df.selectExpr("to_json(parsed) AS js").collect()[0]["js"])
elements = d.get("document", d).get("elements", [])
print(f"Total elements: {len(elements)}")
print("Types:", dict(Counter(e.get('type') for e in elements)), "\n")


# =============================================================================
# 1. CONFIDENCE
# =============================================================================
print("=" * 60)
print("1. CONFIDENCE")
print("=" * 60)
found_conf = False
for i, e in enumerate(elements):
    # element-level
    cf = {k: v for k, v in e.items() if "conf" in k.lower() or "score" in k.lower()}
    # bbox-level
    bb = e.get("bbox")
    if bb and isinstance(bb, list) and isinstance(bb[0], dict):
        cf.update({f"bbox.{k}": v for k, v in bb[0].items()
                   if "conf" in k.lower() or "score" in k.lower()})
    if cf:
        found_conf = True
        print(f"  [{i}] type={e.get('type')}  {cf}")
if not found_conf:
    print("  No confidence/score fields found at element or bbox level.")
    print("  -> printing ALL keys of the first table so you can look manually:")
    for e in elements:
        if e.get("type") == "table":
            print("  table keys:", list(e.keys()))
            break
print(">>> KEY TEST: on a table you KNOW was misread, is confidence LOW?")
print(">>> If low on bad tables -> reliable. If high -> OCR confidently wrong -> not useful.\n")


# =============================================================================
# 2. FOOTNOTE / LEGEND text
# =============================================================================
print("=" * 60)
print("2. FOOTNOTE / LEGEND / CAPTION (legend-as-text check)")
print("=" * 60)
for i, e in enumerate(elements):
    t = e.get("type", "")
    content = e.get("content") or e.get("text") or e.get("description") or ""
    if t in ("footnote", "legend", "caption") or "legend" in str(content).lower():
        print(f"  [{i}] type={t}")
        print(f"      text: {str(content)[:250]}")
print(">>> Does the legend text have series names + colours ('Blue = Revenue')")
print(">>> or just names, or is it a source note? That decides legend-as-text.\n")


# =============================================================================
# 3. BEAUTIFULSOUP vs our parser on a table's HTML
# =============================================================================
print("=" * 60)
print("3. BEAUTIFULSOUP on a table's HTML")
print("=" * 60)
try:
    from bs4 import BeautifulSoup
except Exception:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "beautifulsoup4", "--quiet"])
    from bs4 import BeautifulSoup

tables = [e for e in elements if e.get("type") == "table"]
if tables:
    html = tables[0].get("content") or tables[0].get("html") or ""
    print(f"  (first table HTML, {len(html)} chars)\n")
    soup = BeautifulSoup(html, "html.parser")
    for ri, tr in enumerate(soup.find_all("tr")):
        cells = tr.find_all(["td", "th"])
        row = [(c.get_text(strip=True)[:15], c.get("colspan"), c.get("rowspan")) for c in cells]
        print(f"  row {ri}: {row}")
    print("\n>>> Compare this row/cell/span structure to what our parser produces.")
    print(">>> Does BeautifulSoup give a cleaner/more correct structure on malformed tables?")
else:
    print("  No tables found in this document.")

# another inspect all

# =============================================================================
#  Inspect ai_parse_document output — each check has ITS OWN page setting:
#   1. CONFIDENCE      — on CONF_PAGE
#   2. FOOTNOTE/LEGEND — on FOOT_PAGE
#   3. BEAUTIFULSOUP   — on BS_PAGE
#  Set each to a page number, or None for all pages.
#  Handles the VariantVal type (to_json -> json.loads).
# =============================================================================
import json
from collections import Counter

DOC = "/Volumes/<catalog>/<schema>/<volume>/docs/your_doc.pptx"   # <-- set this
IMG_OUT = "/Volumes/<catalog>/<schema>/<volume>/inspect_imgs"

# ---- SET THE PAGE FOR EACH CHECK (None = all pages) ----
CONF_PAGE = None    # page for the CONFIDENCE check
FOOT_PAGE = None    # page for the FOOTNOTE/LEGEND check
BS_PAGE   = None    # page for the BEAUTIFULSOUP check

dbutils.fs.mkdirs(IMG_OUT)

# ---- run ai_parse + convert VARIANT to a plain dict ----
spark.sql("CREATE OR REPLACE TEMP VIEW _insp AS "
          f"SELECT * FROM READ_FILES('{DOC}', format => 'binaryFile')")
df = spark.sql(f"""
    SELECT ai_parse_document(content,
        map('version','2.0','imageOutputPath','{IMG_OUT}')) AS parsed
    FROM _insp
""")
d = json.loads(df.selectExpr("to_json(parsed) AS js").collect()[0]["js"])
elements = d.get("document", d).get("elements", [])

try:
    from bs4 import BeautifulSoup
except Exception:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "beautifulsoup4", "--quiet"])
    from bs4 import BeautifulSoup

def _page(e):
    bb = e.get("bbox")
    if bb and isinstance(bb, list) and isinstance(bb[0], dict):
        return bb[0].get("page_id")
    return None

def _conf(e):
    for k, v in e.items():
        if ("conf" in k.lower() or "score" in k.lower()) and isinstance(v, (int, float)):
            return v, k
    bb = e.get("bbox")
    if bb and isinstance(bb, list) and isinstance(bb[0], dict):
        for k, v in bb[0].items():
            if ("conf" in k.lower() or "score" in k.lower()) and isinstance(v, (int, float)):
                return v, f"bbox.{k}"
    return None, None

def _content(e):
    return e.get("content") or e.get("html") or e.get("text") or e.get("description") or ""

def _on_page(e, pg):
    return pg is None or _page(e) == pg

pages = sorted({_page(e) for e in elements if _page(e) is not None})
print(f"Total elements: {len(elements)}  |  pages available: {pages}")
print("Types:", dict(Counter(e.get('type') for e in elements)))


# =============================================================================
# 1. CONFIDENCE  (on CONF_PAGE)
# =============================================================================
print("\n" + "=" * 60)
print(f"1. CONFIDENCE  (page = {CONF_PAGE if CONF_PAGE is not None else 'ALL'})")
print("=" * 60)
tbls = [e for e in elements if e.get("type") == "table" and _on_page(e, CONF_PAGE)]
if not tbls:
    print("  (no tables on this page)")
for j, e in enumerate(tbls):
    cv, ck = _conf(e)
    snip = " ".join(str(_content(e)).split())[:180]
    print(f"\n  table {j} (page {_page(e)}): confidence={cv} (field={ck})")
    print(f"    content: {snip}")
print("\n  >>> find the BAD table by content; is its confidence LOWER than good ones?")


# =============================================================================
# 2. FOOTNOTE / LEGEND  (on FOOT_PAGE)
# =============================================================================
print("\n" + "=" * 60)
print(f"2. FOOTNOTE / LEGEND  (page = {FOOT_PAGE if FOOT_PAGE is not None else 'ALL'})")
print("=" * 60)
found = False
for e in elements:
    if not _on_page(e, FOOT_PAGE):
        continue
    t = e.get("type", "")
    cont = _content(e)
    if t in ("footnote", "legend", "caption") or "legend" in str(cont).lower():
        found = True
        print(f"  type={t} (page {_page(e)}): {str(cont)[:250]}")
if not found:
    print("  (no footnote/legend/caption on this page)")
print("\n  >>> does the legend text have series names + colours (legend-as-text)?")


# =============================================================================
# 3. BEAUTIFULSOUP  (on BS_PAGE)
# =============================================================================
print("\n" + "=" * 60)
print(f"3. BEAUTIFULSOUP  (page = {BS_PAGE if BS_PAGE is not None else 'ALL'})")
print("=" * 60)
bs_tbls = [e for e in elements if e.get("type") == "table" and _on_page(e, BS_PAGE)]
if not bs_tbls:
    print("  (no table on this page)")
for j, e in enumerate(bs_tbls):
    html = _content(e)
    soup = BeautifulSoup(str(html), "html.parser")
    rows = soup.find_all("tr")
    print(f"\n  table {j} (page {_page(e)}, {len(rows)} rows):")
    for ri, tr in enumerate(rows[:8]):
        cells = tr.find_all(["td", "th"])
        print(f"    row {ri}: " +
              str([(c.get_text(strip=True)[:14], c.get('colspan'), c.get('rowspan'))
                   for c in cells]))
print("\n  >>> compare BeautifulSoup's rows/spans to our parser on malformed tables.")
