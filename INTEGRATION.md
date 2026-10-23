# Wiring the upgrade into shorts_factory

New files (nothing existing was overwritten):
`app/cinematic.py`, `app/overlay.py`, `app/qa_v2.py`, `docs/{AUDIT,STYLE_BIBLE,TOOLS,AGENT_INSTRUCTIONS}.md`, `skills/*/SKILL.md`, `tests/test_qa_v2.py`, `examples/shotlist.example.json`.
Extra deps: `opencv-python-headless numpy fonttools playwright` (add to `pyproject.toml`).

## Minimal edits to existing code
1. **`app/loop.py::run`** — after `render()`, replace `observe()`'s pass logic with:
   ```python
   from . import qa_v2
   sheet = qa_v2.contact_sheet(video_path, work/"sheet.jpg")
   vision = _vision_review(sheet)            # existing helper; MUST return scores, not {"skipped":...}
   res = qa_v2.evaluate(video_path, overlay_dir, onscreen_text, FONT, vision if "scores" in vision else None)
   if not res["passed"]: findings += [c for c,v in res["checks"].items() if v != "pass"]
   ```
   `{"skipped": ...}` must map to `None` so the run fails instead of passing blind (audit finding 4).
2. **`app/frames.py`** — keep the HyperFrames templates, but make them transparent HUD layers (`#root{background:transparent}`) and render the picture with `app.cinematic`.
3. **Captions** — change the caption band from 1428–1772 to `bottom:540px; right:150px` (audit finding 5).
4. **Retire `render.make_srt` even-split** — use per-word timing (finding 7).
5. **`providers.review_video`** — stop using it as the visual gate (text-only).
6. **`.github/workflows/daily-production.yml`** — `pip install opencv-python-headless playwright && playwright install chromium`; keep `PUBLISH_MODE=review`.

Run `pytest tests/test_qa_v2.py` and `python -m app.qa_v2 <video>` to confirm.

## Update: one-command pipeline
New modules `app/{voice,hud,stills,produce}.py`, assets in `app/assets/`, example `examples/doomsday.json`, guide `docs/PRODUCE.md`. `python -m app.loop produce --spec <spec.json>` runs voice -> HUD -> cinematic render -> `qa_v2` gate. Deps added to `pyproject.toml`; CI needs `playwright install chromium` and ffmpeg.
