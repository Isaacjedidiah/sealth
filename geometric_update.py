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