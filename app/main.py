from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .analytics import channel_analytics
from .assets import adopt_source_images, nasa_beat_queries
from .creative import (
    creative_brief,
    default_treatments,
    learn_from_reviews,
    prioritize_treatments,
    recent_feedback,
    refine_treatment,
    render_candidate,
)
from .delivery import authorize_youtube, discover_telegram_chat_id, publish_youtube, telegram
from .growth_audit import audit_run
from .models import RunManifest
from .playbook import write_playbook
from .providers import (
    ProviderError,
    generate_script,
    review_candidate,
    review_video,
)
from .qa import hard_gate
from .render import audio_duration, make_srt, narrate
from .settings import Settings
from .store import Store
from .teacher import supervise
from .trends import analyze, discover


def choose_visualizable_idea(settings: Settings, store: Store, run_dir: Path):
    """Find a sourced topic with enough first-party visual material before spending on voice/script.

    Failures are remembered by source URL. This is bounded operational learning, not an attempt to
    change editorial policy or download arbitrary new tools.
    """
    excluded = store.rejected_source_urls()
    failures: list[str] = []
    for attempt in range(1, settings.max_regeneration_attempts + 1):
        idea = discover(settings, store.recent_scripts(), excluded)
        source = idea.sources[0]
        probe_dir = run_dir / "topic_probes" / f"attempt-{attempt}"
        try:
            images, provenance = adopt_source_images(source, probe_dir / "assets")
            if len(images) < 4:
                raise ProviderError("Fewer than four usable first-party source images are available; a repetitive automatic treatment is forbidden.")
        except ProviderError as error:
            reason = f"Source-asset gate v2: {error}"
            store.save_source_rejection(str(source.url), idea.title, reason, datetime.now(UTC).isoformat())
            excluded.add(str(source.url))
            failures.append(f"{idea.title}: {reason}")
            continue
        Store.write_json(run_dir / "assets" / "provenance.json", provenance)
        return idea, images, provenance, failures
    raise ProviderError("No current topic had enough verified visual material after bounded retries. " + " | ".join(failures))


def run(dry_run: bool = False) -> RunManifest:
    settings = Settings()
    missing = settings.validate_production()
    if missing and not dry_run:
        raise ProviderError("Production configuration incomplete: " + ", ".join(missing))
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_dir = settings.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(run_id=run_id, created_at=datetime.now(UTC), status="started")
    store = Store(settings.data_dir)
    stage_notes: list[dict[str, object]] = []
    try:
        idea, images, provenance, topic_failures = choose_visualizable_idea(settings, store, run_dir)
        manifest.idea = idea
        manifest.errors.extend(topic_failures)
        trend_status = json.loads((settings.data_dir / "latest_trend_report.json").read_text(encoding="utf-8")).get("source_status", {})
        stage_notes.append({"stage": "trend_and_source", "status": "pass", "topic": idea.title,
                            "source": str(idea.sources[0].url), "source_status": trend_status,
                            "usable_first_party_images": len(images), "corrections": topic_failures})
        if dry_run:
            manifest.status = "dry_run_complete"; return manifest
        script = generate_script(settings, idea.title, idea.sources); manifest.script = script
        stage_notes.append({"stage": "script", "status": "pass", "hook_words": len(script.hook.split()),
                            "narration_words": len(script.narration.split()), "body_beats": len(script.body)})
        write_playbook(settings.data_dir / "industry_playbook.json")
        Store.write_json(run_dir / "fact_ledger.json", {
            "sources": [{"id": f"S{index}", **source.model_dump(mode="json")} for index, source in enumerate(idea.sources, 1)],
            "claims": [claim.model_dump(mode="json") for claim in script.claims],
        })
        audio = narrate(settings, script, run_dir / "narration.mp3")
        lines = [script.hook, *script.body, script.ending]
        # Once factual beats exist, refresh the optional NASA catalog media with beat-specific
        # queries (for example Explorer 1 or Ranger 7) rather than relying on a broad JPL search.
        # The initial source gate remains before narration spending; this second pass corrects
        # visual-to-claim alignment without adding unverified third-party assets.
        if "nasa.gov" in str(idea.sources[0].url).lower():
            images, provenance = adopt_source_images(
                idea.sources[0], run_dir / "script_aligned_assets", visual_queries=nasa_beat_queries(lines),
            )
            if len(images) < 4:
                raise ProviderError("Beat-aligned official media pass produced fewer than four usable images.")
            Store.write_json(run_dir / "assets" / "provenance.json", provenance)
        images = align_images_to_beats(images, provenance, lines)
        make_srt(lines, run_dir / "captions.srt", audio_duration(audio))
        # Three materially different art directions use the same verified source imagery. Each is
        # evaluated from its actual decoded frames, then one winner is allowed past review.
        candidates: list[tuple[float, str, object, object]] = []
        prior_scripts = store.recent_scripts()
        learning_path = settings.data_dir / "creative_learning.json"
        retained_feedback = recent_feedback(learning_path)
        for base_treatment in prioritize_treatments(default_treatments(), learning_path):
            treatment = refine_treatment(base_treatment, {**retained_feedback, **manifest.creative_reviews})
            candidate_dir = run_dir / "candidates" / treatment.id
            Store.write_json(candidate_dir / "treatment.json", treatment.model_dump())
            Store.write_json(candidate_dir / "creative_brief.json", creative_brief(lines, treatment))
            candidate, contact_sheet = render_candidate(images, lines, audio, treatment, candidate_dir / "candidate.mp4")
            qa = hard_gate(candidate, script, prior_scripts)
            (candidate_dir / "qa.json").write_text(qa.text(), encoding="utf-8")
            if not qa.passed:
                manifest.errors.append(f"{treatment.id} hard QA rejected: {qa.text()}")
                stage_notes.append({"stage": "technical_qa", "treatment": treatment.id, "status": "reject", "details": qa.checks})
                continue
            stage_notes.append({"stage": "technical_qa", "treatment": treatment.id, "status": "pass", "details": qa.checks})
            try:
                visual = review_candidate(settings, script, treatment, contact_sheet)
            except ProviderError as error:
                # A reviewer outage rejects this candidate but must not abort rendering/testing of
                # the remaining art directions. Never translate reviewer unavailability into approval.
                manifest.errors.append(f"{treatment.id} visual review unavailable: {error}")
                stage_notes.append({"stage": "visual_review", "treatment": treatment.id, "status": "unavailable", "details": str(error)[:500]})
                continue
            manifest.creative_reviews[treatment.id] = visual
            Store.write_json(candidate_dir / "visual_review.json", visual.model_dump())
            stage_notes.append({"stage": "visual_review", "treatment": treatment.id,
                                "status": "pass" if visual.approved() else "reject",
                                "scores": visual.model_dump(exclude={"repair_notes"}), "corrections": visual.repair_notes})
            if visual.approved():
                candidates.append((visual.average, treatment.id, candidate, qa))
        Store.write_json(run_dir / "creative_reviews.json", {key: value.model_dump() for key, value in manifest.creative_reviews.items()})
        if not candidates:
            learn_from_reviews(learning_path, manifest.creative_reviews, None)
            # A visual-review rejection is a creative-quality churn verdict. The small primary
            # pool stays viable only if quality iteration can retry the same source later;
            # only the copied reason (asset gate, verification) permanently excludes a source.
            raise ProviderError("All three creative candidates were rejected by visual review; see creative_reviews.json.")
        _, treatment_id, winner, qa = max(candidates, key=lambda item: item[0])
        video = run_dir / "final.mp4"; shutil.copy2(winner, video); manifest.video = video
        manifest.selected_treatment = treatment_id
        (run_dir / "qa.json").write_text(qa.text(), encoding="utf-8")
        review = review_video(settings, script, qa.text()); manifest.review = review
        Store.write_json(run_dir / "review.json", review.model_dump())
        stage_notes.append({"stage": "editorial_review", "status": "pass" if review.approved(settings.min_review_score) else "reject",
                            "scores": review.model_dump(exclude={"notes"}), "corrections": review.notes})
        if not review.approved(settings.min_review_score): raise ProviderError("Editorial review rejected: " + review.notes)
        learn_from_reviews(learning_path, manifest.creative_reviews, treatment_id)
        telegram(settings, video, script, review.notes)
        stage_notes.append({"stage": "telegram_delivery", "status": "pass", "mode": settings.publish_mode})
        if settings.publish_mode == "schedule":
            manifest.errors.append("Scheduled: " + publish_youtube(settings, video, script))
        store.save_approved(run_id, script.title, script.narration, str(video), manifest.created_at.isoformat())
        manifest.status = "released"
    except Exception as error:  # noqa: BLE001 - a pipeline run must persist every failure in its manifest
        manifest.status = "rejected"; manifest.errors.append(str(error))
    finally:
        Store.write_json(run_dir / "teacher_notes.json", {"run_id": run_id, "created_at": datetime.now(UTC).isoformat(),
                                                            "status": manifest.status, "stages": stage_notes,
                                                            "errors": manifest.errors})
        Store.write_json(run_dir / "manifest.json", manifest.model_dump(mode="json"))
    return manifest


def align_images_to_beats(images: list[Path], provenance: list[dict[str, str]], lines: list[str]) -> list[Path]:
    """Prefer a source image whose alt text shares subject terms with each narrated beat.

    Every beat draws from the *unused* pool only while it lasts — repeating an asset several
    beats apart reads as visual monotony on a contact sheet (independent review flagged the
    former soft-penalty scheme). If a publisher gives no meaningful alt text, source order is
    retained instead of fabricating visual semantics.
    """
    if len(images) != len(provenance):
        raise ProviderError("Source-image provenance is incomplete; visual alignment is unsafe.")
    asset_words = [set(re.findall(r"[a-z]{4,}", item.get("alt_text", "").lower())) for item in provenance]
    assigned: list[Path] = []; used: set[int] = set()
    for index, line in enumerate(lines):
        line_words = set(re.findall(r"[a-z]{4,}", line.lower()))
        untouched = [asset_index for asset_index in range(len(images)) if asset_index not in used]
        if not untouched:  # more narrated beats than distinct assets; rotate honestly
            untouched = [index % len(images)]
        scores = [len(line_words & asset_words[asset_index]) for asset_index in untouched]
        best = max(range(len(untouched)),
                   key=lambda rank: (scores[rank], -abs(untouched[rank] - index), -rank))
        used.add(untouched[best]); assigned.append(images[untouched[best]])
    return assigned


def cli() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=["run", "analyze-trends", "monitor-analytics", "audit-growth", "authorize-youtube", "telegram-chat-id", "teacher-loop"]); parser.add_argument("--dry-run", action="store_true"); parser.add_argument("--run-dir", type=Path); parser.add_argument("--target", type=int, default=3); parser.add_argument("--max-attempts", type=int, default=9)
    args = parser.parse_args(); settings = Settings()
    if args.command == "authorize-youtube": authorize_youtube(settings); print("YouTube OAuth token saved."); return
    if args.command == "telegram-chat-id": print(discover_telegram_chat_id(settings)); return
    if args.command == "monitor-analytics": print(json.dumps(channel_analytics(settings), indent=2)); return
    if args.command == "analyze-trends": print(analyze(settings).model_dump_json(indent=2)); return
    if args.command == "teacher-loop":
        print(json.dumps(supervise(settings, target=args.target, max_attempts=args.max_attempts), indent=2)); return
    if args.command == "audit-growth":
        run_dir = args.run_dir or max(settings.output_dir.glob("20*"), key=lambda path: path.stat().st_mtime)
        print(json.dumps(audit_run(settings, run_dir), indent=2)); return
    result = run(args.dry_run); print(result.model_dump_json(indent=2))
    if result.status == "rejected": raise SystemExit(1)


if __name__ == "__main__": cli()
