"""Motion bank: small, text-free looping clips (assets/motion, curated from the HyperFrames catalog) blended over the stills.

A photo with a push-in still reads as a slideshow. A moving light layer (godrays, drifting debris, aurora, lens flare)
over the photo gives it a video feel for a few KB per clip, so no video-generation model is needed.

    pick(spec)            -> one clip choice per beat  [{"clip": "godrays", "blend": "screen", "op": 0.5}, ...]
    ClipLayer(name)       -> frame_at(t) / blend(frame, t, op, blend) used by app.cinematic
Beats may name a clip themselves ("motion": "godrays") or a mood ("mood": "space"); otherwise the mood is inferred from the text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np

BANK = Path(__file__).resolve().parent.parent / "assets" / "motion"
DECODE_W, DECODE_H = 270, 480          # decoded small (memory is shared by forked workers); upscaled on blend, textures are soft anyway

MOOD_WORDS = {
    "space": ("space", "orbit", "satellite", "debris", "kessler", "planet", "moon", "mars", "star", "galaxy", "rocket", "nasa", "earth", "solar"),
    "danger": ("collapse", "crash", "disaster", "war", "fire", "explos", "doom", "extinction", "collision", "chain reaction", "catastroph"),
    "data": ("percent", "billion", "million", "rate", "chart", "population", "growth", "data", "statistic", "economy", "price"),
    "tech": ("ai", "agent", "computer", "chip", "internet", "robot", "software", "code", "network", "algorithm", "digital"),
    "calm": ("sleep", "ocean", "water", "nature", "peace", "quiet", "forest"),
    "warm": ("sun", "heat", "energy", "light", "gold", "morning"),
}


def manifest() -> list[dict]:
    p = BANK / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else []


def mood_of(text: str) -> list[str]:
    t = text.lower()
    scored = sorted(((sum(len(re.findall(r"\b" + re.escape(w), t)) for w in ws), m) for m, ws in MOOD_WORDS.items()), reverse=True)
    out = [m for n, m in scored if n > 0][:2]
    return out or ["tech"]


def pick(spec: dict, max_distinct: int = 5) -> list[dict | None]:
    """one fx per beat: explicit "motion" wins, else the best unused clip for the beat's mood; never the same clip twice in a row."""
    bank = {c["name"]: c for c in manifest() if c.get("role", "ambient") != "object" or c["name"] in {b.get("motion") for b in spec.get("beats", [])}}
    if not bank:
        return [None] * len(spec.get("beats", []))
    whole = " ".join([spec.get("title", "")] + [b.get("say", "") for b in spec["beats"]])
    base = mood_of(whole)
    out, used, last = [], [], None
    for i, b in enumerate(spec["beats"]):
        if b.get("motion") is False or b.get("dim"):
            out.append(None)
            continue
        name = b.get("motion")
        if name not in bank:
            moods = [b["mood"]] if b.get("mood") else mood_of(b.get("say", "")) + base
            def score(c):
                s = sum(2 if m in c["mood"] else 0 for m in moods[:1]) + sum(1 for m in moods[1:] if m in c["mood"])
                return (s - (3 if c["name"] in used else 0) + ((i * 7 + len(c["name"])) % 5) * 0.01, c["name"])
            cands = [c for c in bank.values() if c["name"] != last]
            if len(set(used)) >= max_distinct:
                cands = [c for c in cands if c["name"] in used] or cands
            name = max(cands, key=score)["name"]
        c = bank[name]
        used.append(name)
        last = name
        out.append({"clip": name, "blend": c["blend"], "op": 0.6 if c["blend"] == "screen" else 0.38})
    return out


class ClipLayer:
    """a looping clip decoded to float RGB at DECODE size; frame_at(t) is stateless so forked workers can call it freely."""

    def __init__(self, name: str, path: Path | None = None, size: tuple[int, int] = (DECODE_W, DECODE_H), pingpong: bool = True):
        self.pingpong = pingpong
        cap = cv2.VideoCapture(str(path or BANK / f"{name}.mp4"))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f if f.shape[1::-1] == size else cv2.resize(f, size, interpolation=cv2.INTER_AREA))
        cap.release()
        if not frames:
            raise FileNotFoundError(f"motion clip unreadable: {name}")
        self.frames = np.stack(frames)
        self.n = len(frames)

    def frame_at(self, t: float, size: tuple[int, int]) -> np.ndarray:
        """ping-pong loop (no visible seam), upscaled to size=(W,H), uint8 BGR"""
        return cv2.resize(self.raw_at(t), size, interpolation=cv2.INTER_LINEAR)

    def raw_at(self, t: float) -> np.ndarray:
        if not self.pingpong:
            return self.frames[int(max(t, 0) * self.fps) % self.n]
        k = int(max(t, 0) * self.fps) % (2 * self.n - 2 or 1)
        return self.frames[k if k < self.n else 2 * self.n - 2 - k]


def blend(f: np.ndarray, clip: np.ndarray, op: float, mode: str, lower_mask: np.ndarray | None = None) -> np.ndarray:
    """f, clip: uint8 BGR same size. screen = add light; overlay = soft colour wash. lower_mask (H,W,1 float) calms the caption area."""
    a = f.astype(np.float32) / 255
    b = clip.astype(np.float32) / 255
    k = op if lower_mask is None else op * lower_mask
    if mode == "screen":
        out = 1 - (1 - a) * (1 - b * k)
    else:
        soft = a * (0.55 + 0.9 * b)                      # soft-light-ish: clip luminance modulates the photo's own light
        out = a * (1 - k) + soft * k + b * k * 0.15
    return np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
