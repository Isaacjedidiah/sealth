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
