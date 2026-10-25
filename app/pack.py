"""The upload pack: everything needed to publish an approved Short from YouTube Studio in one paste (uploading itself stays the owner's step).

    build(spec, credit_files) -> text; also saved as publish.md by callers
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STOP = {"what", "if", "the", "a", "an", "of", "to", "in", "on", "and", "for", "with", "we", "could", "would", "how", "why", "is", "are", "was"}


def tags(spec: dict) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", spec["title"] + " " + str(spec.get("series_label", ""))) if w.lower() not in STOP]
    out = []
    for w in words + ["shorts", "science", "explained", "what if", "space", "agent shift"]:
        if w not in out:
            out.append(w)
    return out[:8]


def build(spec: dict, credit_files: list[Path]) -> str:
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
    desc = f"{hook}\n\nSources:\n{srcs}\n" + (f"\nPictures and footage:\n" + "\n".join(cred) + "\n" if cred else "") + "\n#shorts #science #whatif #agentshift"
    topic = re.sub(r"(?i)^what if\s+", "", spec["title"]).rstrip("?. ")
    pinned = f"Which part of “{topic[:70]}” surprised you most? Tell us below."
    return (f"UPLOAD PACK\n\nTITLE:\n{title}\n\nDESCRIPTION:\n{desc}\n\nTAGS:\n{', '.join(tags(spec))}\n\nPINNED COMMENT:\n{pinned}\n\n"
            "SETTINGS:\n- Audience: not made for kids\n- Altered or synthetic content: YES (AI-generated narration and some generated pictures)\n"
            "- Visibility: upload as Private first, check the copyright/audit result, then schedule\n- Suggested time: 19:00 IST")
