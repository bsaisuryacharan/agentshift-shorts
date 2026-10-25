"""The upload pack: everything needed to publish an approved Short from YouTube Studio in one paste (uploading itself stays the owner's step).

    build(spec, credit_files) -> text; also saved as publish.md by callers
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FORMAT_TAG = {"what_if": "what if", "how_it_works": "how it works", "myth_vs_fact": "myth vs fact", "unsolved": "mystery", "ranked": "top 5", "versus": "versus", "timeline": "history", "scale": "scale", "story": "story"}
STOP = {"what", "if", "the", "a", "an", "of", "to", "in", "on", "and", "for", "with", "we", "could", "would", "how", "why", "is", "are", "was"}


def tags(spec: dict) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", spec["title"] + " " + str(spec.get("series_label", ""))) if w.lower() not in STOP]
    out = []
    for w in words + ["shorts", "science", "explained", "agent shift"] + ([FORMAT_TAG.get(spec.get("format"), "")] if spec.get("format") else []):
        if w not in out:
            out.append(w)
    return out[:8]


def parts(spec: dict, credit_files: list[Path]) -> dict:
    """the pieces of the upload pack as data (title, description, tags, pinned comment)"""
    title = spec["title"].strip()
    title = (title if len(title) <= 88 else title[:87].rstrip() + "…") + " #shorts"
    srcs = "\n".join(f"- {v}" for v in (spec.get("sources") or {}).values() if str(v).startswith("http"))
    cred = []
    for f in credit_files:
        try:
            for v in json.loads(Path(f).read_text()).values():
                if "artist" in v:
                    cred.append(f"- {v['file']} - {str(v['artist'])[:50]}, {v['license']} ({v['url']})")
                else:
                    cred.append(f"- {v.get('title', v.get('file'))} - {v.get('center', 'NASA')}, {v.get('license', '')} ({v.get('source', '')})")
        except (OSError, ValueError):
            continue
    hook = spec["beats"][0]["say"]
    desc = f"{hook}\n\nSources:\n{srcs}\n" + ("\nPictures and footage:\n" + "\n".join(cred) + "\n" if cred else "") + f"\n#shorts #science #agentshift #{FORMAT_TAG.get(spec.get('format'), 'explained').replace(' ', '')}"
    topic = re.sub(r"(?i)^what if\s+", "", spec["title"]).rstrip("?. ")
    return {"title": title, "description": desc, "tags": tags(spec), "pinned": f"Which part of “{topic[:70]}” surprised you most? Tell us below."}


def build(spec: dict, credit_files: list[Path]) -> str:
    p = parts(spec, credit_files)
    return (f"UPLOAD PACK\n\nTITLE:\n{p['title']}\n\nDESCRIPTION:\n{p['description']}\n\nTAGS:\n{', '.join(p['tags'])}\n\nPINNED COMMENT:\n{p['pinned']}\n\n"
            "SETTINGS:\n- Audience: not made for kids\n- Altered or synthetic content: YES (AI-generated narration and some generated pictures)\n"
            "- Visibility: Public (if YouTube forces Private because the API project is not audited, set it to Public in Studio)\n- Best posting time: 19:00 IST\n\n"
            "Send /approve to approve it: it is then uploaded to YouTube automatically (public).")
