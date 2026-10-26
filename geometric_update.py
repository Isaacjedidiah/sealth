# EDIT 1 — the WITH_POS prompt. Find:
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

# Replace:
CHART_DIGITISATION_PROMPT_WITH_POS = (
    "You are a chart digitisation engine (bar, line OR dot/scatter charts). Read "
    "the chart in this image and return STRICT JSON, no prose:\n"
    '{"title": "<the chart title exactly as printed>", '
    '"points": [{"series": "<series name from the legend, e.g. Revenue>", '
    '"value": <number PRINTED on/beside the bar/point>, '
    '"x_center": <horizontal PIXEL position of this bar/point centre>}], '
    '"xlabels": [{"text": "<x-axis label exactly as printed, e.g. July or Feb \'25>", '
    '"x_center": <horizontal PIXEL position of the label centre>}]}\n'
    "Rules:\n"
    "- Return EVERY bar/point you can see, for EVERY series, even if its x-axis "
    "position has NO printed label (we resolve the period by position afterwards).\n"
    "- VALUE: if a number is PRINTED on/beside the bar/point, use it EXACTLY; if a "
    "bar/point has NO printed number, ESTIMATE its value from its height/position "
    "against the y-axis scale (never drop a bar for lacking a printed number).\n"
    "- Give the chart TITLE and each point's SERIES name (from the legend) so each "
    "value can be traced to its chart and series.\n"
    "- Output ONLY the JSON object."
)

# EDIT 2 — add _build_chart_claims_with_geometry before _sonnet_read_image_with_pos. Find:
def _sonnet_read_image_with_pos(

# Replace:
def _build_chart_claims_with_geometry(chart_title, pts, xlabels, el, filename,
                                      entity_ref, firm_xaxis_cfg, title=None):
    """Build chart claims with geometry-resolved periods for the firm-x-axis case.
    Every point becomes a claim (including positions with NO printed label -- the
    geometry fills the period from the printed labels). canonical_metric =
    <chart title> | <series> | <period>. All chart values are llm_estimated."""
    from .firm_xaxis import resolve_axis_labels
    try:
        from ..shared.schema import Claim as _Claim
    except Exception:
        _Claim = None

    bars = [{"id": i, "series": p.get("series", ""),
             "value": str(p.get("value", "")),
             "x_center": p.get("x_center")}
            for i, p in enumerate(pts)]
    labs = [{"text": l.get("text", ""), "x_center": l.get("x_center")}
            for l in (xlabels or []) if l.get("x_center") is not None]

    id_to_period, status = ({}, "normal")
    if any(b.get("x_center") is not None for b in bars) and labs:
        try:
            id_to_period, status = resolve_axis_labels(
                [b for b in bars if b.get("x_center") is not None], labs,
                monthly_step=firm_xaxis_cfg.get("monthly_step", 1),
                x_tolerance=firm_xaxis_cfg.get("x_tolerance", 8))
        except Exception:
            id_to_period, status = ({}, "normal")

    prefix = (chart_title or "").strip() or (title or "").strip()

    out = []
    eid = f"{filename}-p{getattr(el, 'page', None)}-fig"
    for i, p in enumerate(pts):
        series = str(p.get("series", "") or "").strip()
        value = p.get("value")
        if value is None or str(value).strip() == "":
            continue
        period = id_to_period.get(i)
        period = None if period == "FLAG_REVIEW" else period
        name = " | ".join(x for x in (prefix, series, period) if x) or series or "value"
        claim_kwargs = dict(
            field_name=series or "value", canonical_metric=name,
            value=str(value), unit=p.get("unit"), element_type="figure",
            source_element_id=eid, page=getattr(el, "page", None),
            entity_ref=entity_ref, confidence=0.75,
            model_used="sonnet_chart_geometry")
        if period:
            claim_kwargs["as_at_date"] = period
        try:
            from ..shared.schema import CitationTier
            claim_kwargs["citation_tier"] = CitationTier.LLM_ESTIMATED
        except Exception:
            pass
        if _Claim is not None:
            out.append(_Claim(**claim_kwargs))
    return out


def _sonnet_read_image_with_pos(

# EDIT 3 — _sonnet_read_image_with_pos returns the title. Find:
    points = (data.get("points") or data.get("claims") or data.get("data") or [])
    xlabels = data.get("xlabels") or data.get("labels") or []
    norm = []
    for p in points if isinstance(points, list) else []:
        if isinstance(p, dict):
            norm.append({"label": p.get("label") or p.get("field_name") or "",
                         "value": p.get("value"),
                         "x_center": p.get("x_center")})
    return norm, (xlabels if isinstance(xlabels, list) else [])

# Replace:

    title = str(data.get("title") or "").strip()
    points = (data.get("points") or data.get("claims") or data.get("data") or [])
    xlabels = data.get("xlabels") or data.get("labels") or []
    norm = []
    for p in points if isinstance(points, list) else []:
        if isinstance(p, dict):
            norm.append({"series": p.get("series") or p.get("label") or "",
                         "value": p.get("value"),
                         "unit": p.get("unit"),
                         "x_center": p.get("x_center")})
    return title, norm, (xlabels if isinstance(xlabels, list) else [])

# EDIT 4 — the integrated firm_xaxis block. Find:
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

# Replace:
                if firm_xaxis_cfg:
                    chart_title, pts, xlabels = _sonnet_read_image_with_pos(
                        run_async_fn, llm_client, vision_model_key, content, img_b64)
                    if pts:
                        fig_claims = _build_chart_claims_with_geometry(
                            chart_title, pts, xlabels, el, filename, entity_ref,
                            firm_xaxis_cfg, title=title)
                        claims.extend(fig_claims)
################## UPDATE 20261025 ################################
# CHANGE 1 — replace the _sonnet_read_image_with_pos parsing block. Find:
    # tolerate the points living under a few keys
    points = (data.get("points") or data.get("claims") or data.get("data") or [])
    xlabels = data.get("xlabels") or data.get("labels") or []
    # normalise point field names (label/value/x_center)
    norm = []
    for p in points if isinstance(points, list) else []:
        if isinstance(p, dict):
            norm.append({"label": p.get("label") or p.get("field_name") or "",
                         "value": p.get("value"),
                         "x_center": p.get("x_center")})
    return norm, (xlabels if isinstance(xlabels, list) else [])

# Replace with
    if not isinstance(data, dict):
        data = {}
    title = str(data.get("title") or "").strip()
    points = (data.get("points") or data.get("claims") or data.get("data") or [])
    xlabels = data.get("xlabels") or data.get("labels") or []
    # DEFENSIVE: if Sonnet ignored the schema and returned period-keyed objects
    # (e.g. {"title":..., "July": {"Revenue": 80, "Cost": 30}, ...}) instead of a
    # points array, flatten them into points so nothing is lost. Each period key
    # with a dict of series->value becomes points with that period as an xlabel.
    if not points:
        flat_pts, flat_labels, _idx = [], [], 0
        for k, v in data.items():
            if k in ("title", "points", "xlabels", "labels", "claims", "data"):
                continue
            if isinstance(v, dict):                       # period -> {series: value}
                for series, val in v.items():
                    if isinstance(val, (int, float, str)):
                        flat_pts.append({"series": series, "value": val,
                                         "x_center": _idx})
                flat_labels.append({"text": str(k), "x_center": _idx})
                _idx += 1
            elif isinstance(v, (int, float, str)):        # period -> single value
                flat_pts.append({"series": "", "value": v, "x_center": _idx})
                flat_labels.append({"text": str(k), "x_center": _idx})
                _idx += 1
        if flat_pts:
            points = flat_pts
            if not xlabels:
                xlabels = flat_labels
    # normalise each point -> series / value / unit / x_center. Only keep dict
    # points with a usable value (guards against malformed output leaking raw
    # JSON fragments into the fields).
    norm = []
    for p in (points if isinstance(points, list) else []):
        if not isinstance(p, dict):
            continue
        series = p.get("series") or p.get("label") or p.get("field_name") or ""
        value = p.get("value")
        if value is None or str(value).strip() == "":
            continue
        norm.append({"series": str(series).strip(),
                     "value": value,
                     "unit": p.get("unit"),
                     "x_center": p.get("x_center")})
    norm_labels = []
    for l in (xlabels if isinstance(xlabels, list) else []):
        if isinstance(l, dict) and l.get("text"):
            norm_labels.append({"text": str(l.get("text")).strip(),
                                "x_center": l.get("x_center")})
    return title, norm, norm_labels

# CHANGE 2 — fix the title=title reference in the figure block. Find:
                        fig_claims = _build_chart_claims_with_geometry(
                            chart_title, pts, xlabels, el, filename, entity_ref,
                            firm_xaxis_cfg, title=title)

# Replace with
                        fig_claims = _build_chart_claims_with_geometry(
                            chart_title, pts, xlabels, el, filename, entity_ref,
                            firm_xaxis_cfg,
                            title=_prefix(current_title, current_section))

# CHANGE 3 — strengthen the WITH_POS prompt. Find the END of CHART_DIGITISATION_PROMPT_WITH_POS:
    "- Give the chart TITLE and each point's SERIES name (from the legend) so each "
    "value can be traced to its chart and series.\n"
    "- Output ONLY the JSON object."
)

# Replace with
    "- Give the chart TITLE and each point's SERIES name (from the legend) so each "
    "value can be traced to its chart and series.\n"
    "- CRITICAL: return the points as a flat ARRAY under the key \"points\" -- "
    "one object per bar/point with series, value, x_center. Do NOT key points by "
    "month or category. Do NOT nest objects. Follow the schema exactly.\n"
    "- Output ONLY the JSON object."
)

# firm xaxis
    elements = sorted(detected_bars, key=lambda b: float(b.get('x_center', 0)))

    # --- STEP 1: cluster markers at the SAME x into raw groups (stacked bars,
    #     a bar + its dot, overlapping series share ONE x-position). ---
    raw = []
    for element in elements:
        x = float(element.get("x_center", 0))
        if raw and abs(x - raw[-1]["x_center"]) <= x_tolerance:
            raw[-1]["elements"].append(element)
            raw[-1]["x_center"] = sum(float(e.get("x_center", 0))
                                      for e in raw[-1]["elements"]) / len(raw[-1]["elements"])
        else:
            raw.append({"x_center": x, "elements": [element]})

    # --- STEP 2: derive the EVEN grid step from the gaps between raw groups.
    #     Using the MEDIAN positive gap makes the step robust to a missing
    #     position (a gap that is 2x the step) or an extra marker. ---
    typical_gap = None
    if len(raw) >= 2:
        gaps = [raw[i+1]["x_center"] - raw[i]["x_center"] for i in range(len(raw)-1)]
        pos = [g for g in gaps if g > 0]
        typical_gap = median(pos) if pos else None

    # --- STEP 3: place each raw group on an EVEN GRID. slot_index = how many
    #     steps it sits from the FIRST group. A missing period leaves a GAP in
    #     the indices (so the month maths stays correct); two groups a double-gap
    #     apart get indices 0 and 2, NOT 0 and 1. This fixes:
    #       * leading unlabeled period dropped (it still gets its own index),
    #       * off-by-N from phantom/merged slots (index comes from position),
    #       * stacked bars / dots sharing a position (same index). ---
    slots = []
    if typical_gap and typical_gap > 0:
        x0 = raw[0]["x_center"]
        used = {}
        for g in raw:
            idx = int(round((g["x_center"] - x0) / typical_gap))
            if idx in used:
                # two groups collapsed onto one index: keep separate by nudging
                # the later one forward (defensive; rare).
                idx = max(used) + 1
            used[idx] = True
            slots.append({"x_center": g["x_center"], "elements": g["elements"],
                          "slot_index": idx})
    else:
        for i, g in enumerate(raw):
            slots.append({"x_center": g["x_center"], "elements": g["elements"],
                          "slot_index": i})

# another update 20261026
    # align each printed label to its nearest slot. A label's x can sit a little
    # off its bar (multi-word labels, centring differences, CROWDED charts where
    # bars are close together), so we use a GENEROUS threshold and NEVER drop a
    # label that carries a YEAR -- losing the year anchor is worse than a
    # slightly-off alignment, and is the main cause of "years not added" and of
    # crowded charts collecting nothing. A label landing on an already-claimed
    # slot takes the next-nearest free slot instead of overwriting.
    def _has_year(txt):
        t = re.sub(r"\s+", " ", str(txt).replace("'", "").replace("`", "").strip())
        return bool(re.search(r"\b\d{2,4}\b", t)) or bool(re.search(r"\d{2}$", t))

    assignments = {}
    # place year-bearing labels FIRST (they anchor the timeline), then the rest,
    # each nearest-first, skipping slots already taken.
    ordered = sorted(detected_labels,
                     key=lambda l: (not _has_year(l.get("text", "")),
                                    float(l.get("x_center", 0))))
    for label in ordered:
        if not slots:
            break
        lx = float(label.get("x_center", 0))
        text = label.get("text", "")
        is_year = _has_year(text)
        cands = sorted(slots, key=lambda s: abs(s["x_center"] - lx))
        placed = False
        for cand in cands:
            if cand["slot_index"] in assignments:
                continue                      # slot already has a label
            # reject only NON-year labels that are implausibly far. On a CROWDED
            # chart (small gap) the absolute offset can exceed the gap even for a
            # correct label, so allow up to ~1.0 gap, and never below a small
            # pixel floor so tight charts aren't over-rejected.
            if typical_gap and not is_year:
                tol = max(1.0 * typical_gap, 12.0)   # pixel floor for crowded charts
                if abs(cand["x_center"] - lx) > tol:
                    break
            assignments[cand["slot_index"]] = text
            placed = True
            break
        # a year label that found no free slot still anchors on its nearest slot
        if not placed and is_year:
            assignments[cands[0]["slot_index"]] = text
