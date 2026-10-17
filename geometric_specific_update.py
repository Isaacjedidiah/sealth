# MODULE 1: hybrid_extraction.py

# Change 1a — hybrid_extract_document signature. Find:

                            team=None, report_type=None, entity_ref=None,

                            vision_model_key: str = "tier2",
                            use_sonnet: bool = False) -> list:

# Replace with:

                            vision_model_key: str = "tier2",
                            use_sonnet: bool = False,
                            firm_xaxis_cfg=None) -> list:

# Change 1b — the figure block (attach resolved periods for the configured firm). Find:

                pts = _sonnet_read_image(
                    run_async_fn, llm_client, vision_model_key,
                    CHART_DIGITISATION_PROMPT, content, img_b64)
                if pts:
                    claims.extend(sonnet_points_to_claims(pts, el, filename, entity_ref))
                else:
                    claims.extend(desc_claims)   # vision found nothing -> keep desc

# Replace with:

                pts = _sonnet_read_image(
                    run_async_fn, llm_client, vision_model_key,
                    CHART_DIGITISATION_PROMPT, content, img_b64)
                if pts:
                    fig_claims = sonnet_points_to_claims(pts, el, filename, entity_ref)
                    # FIRM-SPECIFIC x-axis period resolution (only when configured
                    # for this firm). Re-reads the figure for positions, resolves
                    # the period per observation slot, and stamps it on each chart
                    # claim. Unconfigured firms skip this entirely.
                    if firm_xaxis_cfg:
                        try:
                            from .firm_xaxis import resolve_periods_for_figure
                            vp, _valid = resolve_periods_for_figure(
                                img_b64, run_async_fn, llm_client,
                                model_key=vision_model_key,
                                monthly_step=firm_xaxis_cfg.get("monthly_step", 1),
                                x_tolerance=firm_xaxis_cfg.get("x_tolerance", 8))
                            for c in fig_claims:
                                key = (str(getattr(c, "field_name", "") or ""),
                                       str(getattr(c, "value", "") or ""))
                                period = vp.get(key)
                                if period:
                                    # stamp the resolved period onto the claim
                                    setattr(c, "as_at_date", period)
                        except Exception:
                            pass
                    claims.extend(fig_claims)
                else:
                    claims.extend(desc_claims)   # vision found nothing -> keep desc

# MODULE 2: ai_parse_pipeline.py

# Change 2 — resolve the firm config + pass it to hybrid. Find:

            claims = hybrid_extract_document(
                ai_parse_response=parsed, filename=fname,
                team=sub["team"], report_type=sub["report_type"],
                entity_ref=sub.get("entity_ref"),
                use_sonnet=option_a, llm_client=llm_client,
                run_async_fn=run_async_fn, crop_figure_image=crop_fn)

#Replace with:

            # firm-specific x-axis config (None for unconfigured firms -> no-op)
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