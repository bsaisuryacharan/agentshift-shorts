"""Cinematic compositor: photoreal stills -> broadcast-style motion, no paid video model required.

Why this exists: HyperFrames/PIL slideshows read as "template video". Top Shorts creators
(Cleo Abram style) hold a rich photographic frame, move the camera through it every beat, and put sparse,
legible graphics on top. This module does the first two; app/overlay.py does the third.

    python -m app.cinematic test  shotlist.json 60,250,900      # stills for review -> work/cine_test/
    python -m app.cinematic render shotlist.json out.mp4        # full encode

shotlist.json
{ "total": 45.4, "audio": "mix.wav", "overlay_dir": "work/ovl",          # overlay_dir optional (PNG per frame)
  "shots": [ {"img":"img/s0.jpg","start":0,"focal":[0.5,0.55],"zoom":1.3,"rot":0,"flash":0.12}, ... ],
  "bursts": [ {"t":19.45,"x":0.5,"y":0.5,"n":260,"speed":1100,"life":[0.8,1.8]} ] }   # optional spark VFX
Every shot: push-in toward `focal`; on each change the outgoing frame zoom-blurs past the camera while the
incoming one opens through a circular portal. `flash` is the white pop on the cut (0.55 for impacts).
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from . import motionbank

W, H, FPS = 1080, 1920, 30


def _ease(p: float) -> float:
    return p * p * (3 - 2 * p)


THEMES = {   # BGR gains, desaturation, contrast  - documentary looks, nothing neon
    "cool": ((1.10, 1.00, 0.90), 0.12, 1.06),     # space / tech: teal shadows, cooler whites
    "warm": ((0.90, 1.00, 1.08), 0.10, 1.05),     # history / people / desert: amber
    "mono": ((1.02, 1.00, 0.98), 0.45, 1.10),     # archival / serious: near-monochrome
    "earth": ((0.96, 1.04, 1.00), 0.08, 1.04),    # nature / climate: green-leaning neutral
}


def _grade_lut(theme: str | None) -> np.ndarray | None:
    """per-channel 256-entry LUT: channel gain, pull toward grey (desaturate), contrast S-curve around mid-grey"""
    if theme not in THEMES:
        return None
    gains, desat, contrast = THEMES[theme]
    x = np.arange(256, dtype=np.float32) / 255
    lut = np.zeros((256, 1, 3), np.uint8)
    for c in range(3):
        v = x * gains[c]
        v = v * (1 - desat) + x * desat                      # desaturation approximated per channel (full grey pull happens in blend below)
        v = 0.5 + (v - 0.5) * contrast
        lut[:, 0, c] = np.clip(v * 255 + 0.5, 0, 255)
    return lut


class Cinematic:
    TR_PRE, TR_POST, K = 0.40, 0.10, 3.0

    def __init__(self, spec: dict, root: Path):
        self.spec, self.root = spec, Path(root)
        self.total = float(spec["total"])
        self.shots = spec["shots"]
        self.starts = [float(s["start"]) for s in self.shots] + [self.total + 1]
        self.vids = {i: motionbank.ClipLayer("", path=self.root / s["video"], size=(540, 960), pingpong=bool(s.get("pingpong")))
                     for i, s in enumerate(self.shots) if s.get("video")}        # real footage cutaways (app.footage)
        self.imgs = [self.vids[i].frames[0] if i in self.vids else self._load(s["img"]) for i, s in enumerate(self.shots)]
        self.base = [max(W / im.shape[1], H / im.shape[0]) for im in self.imgs]
        self.rng = np.random.default_rng(spec.get("seed", 7))
        self.parts = self._bursts(spec.get("bursts", []))
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.rr = np.sqrt((xx - W / 2) ** 2 + (yy - H / 2) ** 2)
        self.vig = (1 - 0.45 * np.clip((self.rr / (H * 0.62)) ** 2, 0, 1))[..., None].astype(np.float32)
        self.ovl_dir = (self.root / spec["overlay_dir"]) if spec.get("overlay_dir") else None
        self.ovl_step = int(spec.get("overlay_step", 1))   # overlay rendered at FPS/step; frames are held between
        self.ovl_map = {}
        if self.ovl_dir and (self.ovl_dir / "map.json").exists():           # dedup map written by app.overlay
            self.ovl_map = {int(k): int(v) for k, v in json.loads((self.ovl_dir / "map.json").read_text()).items()}
        self._ovl_cache: tuple[int, tuple | None] = (-1, None)
        self.fx = [sh.get("fx") for sh in self.shots]
        self._gy, self._gx = np.mgrid[0:240, 0:135].astype(np.float32) / np.array([240, 135], np.float32)[:, None, None]
        self.drift_tint = {"warm": (14, 40, 70), "earth": (30, 55, 35), "mono": (45, 45, 45)}.get(spec.get("theme"), (70, 48, 18))   # BGR light colour, ~45 levels at its centre
        self.layers = {n: motionbank.ClipLayer(n) for n in {f["clip"] for f in self.fx if f}}
        ys = np.arange(H, dtype=np.float32)[:, None, None]
        self.fx_mask = np.clip(1 - (ys - (H - 700)) / 300, 0.45, 1.0) * np.ones((1, W, 1), np.float32)   # calmer under the caption/UI zone
        self.vig8 = np.repeat((self.vig * 255).astype(np.uint8), 3, axis=2)
        self.lut = _grade_lut(spec.get("theme"))           # one colour grade for the whole Short so mixed sources read as one film
        g = np.random.default_rng(3)
        tiles = [cv2.resize(g.normal(0, 3.0, (H // 4, W // 4)).astype(np.float32), (W, H)) for _ in range(6)]
        self.grain = [(cv2.cvtColor(np.clip(t, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR),
                       cv2.cvtColor(np.clip(-t, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)) for t in tiles]

    # ---- assets -----------------------------------------------------------------------
    def _load(self, rel: str) -> np.ndarray:
        im = cv2.imread(str(self.root / rel))
        if im is None:
            raise FileNotFoundError(f"shot image missing: {rel}")
        im = cv2.resize(im, None, fx=1.3, fy=1.3, interpolation=cv2.INTER_LANCZOS4)
        return cv2.addWeighted(im, 1.3, cv2.GaussianBlur(im, (0, 0), 2.0), -0.3, 0)  # mild unsharp

    # ---- camera ------------------------------------------------------------------------
    def _draw(self, i: int, s: float, rot: float = 0.0, t: float = 0.0) -> np.ndarray:
        im, b = self.imgs[i], self.base[i]
        if i in self.vids:
            im = self.vids[i].raw_at(t - self.starts[i])
        h, w = im.shape[:2]
        fx, fy = self.shots[i].get("focal", (0.5, 0.5))
        k = b * s
        pull = min(1.0, max(0.0, 1 - 1 / s)) if s >= 1 else 0.0
        cx, cy = w * (0.5 + (fx - 0.5) * pull), h * (0.5 + (fy - 0.5) * pull)
        if s >= 1:
            hw, hh = W / 2 / k, H / 2 / k
            cx, cy = min(max(cx, hw), w - hw), min(max(cy, hh), h - hh)
        M = cv2.getRotationMatrix2D((cx, cy), rot, k)
        M[0, 2] += W / 2 - cx
        M[1, 2] += H / 2 - cy
        return cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    def _zoom(self, i: int, t: float) -> float:
        a, b = self.starts[i], min(self.starts[i + 1], self.total)
        p = min(1, max(0, (t - a) / max(b - a, 1e-3)))
        return float(self.shots[i].get("zoom", 1.3)) ** p

    def _rot(self, i: int, t: float) -> float:
        return float(self.shots[i].get("rot", 0.0)) * (t - self.starts[i])

    def background(self, t: float) -> np.ndarray:
        n = len(self.shots)
        i = max(j for j in range(n) if self.starts[j] <= t + self.TR_PRE) if t + self.TR_PRE < self.total + 1 else n - 1
        st = self.starts[i]
        if i > 0 and st - self.TR_PRE <= t < st + self.TR_POST:
            p = _ease((t - (st - self.TR_PRE)) / (self.TR_PRE + self.TR_POST))
            zo = float(self.shots[i - 1].get("zoom", 1.3)) * self.K ** p
            out = np.zeros((H, W, 3), np.float32)
            for d in (0.0, 0.06, 0.12):  # radial zoom blur on the outgoing frame
                out += self._draw(i - 1, zo * (1 + d * p), self._rot(i - 1, t), t).astype(np.float32)
            out /= 3
            inc = self._draw(i, 1.0, self._rot(i, t), t).astype(np.float32)
            rad = 60 + (math.hypot(W, H) / 2 + 200) * p ** 1.6
            m = np.clip((rad - self.rr) / 160, 0, 1)[..., None] * min(1, p * 2.5)
            out = out * (1 - m) + inc * m
            out += 255 * max(0, 1 - abs(t - st) / 0.1) * float(self.shots[i].get("flash", 0.12))
            return out
        return self._draw(i, self._zoom(i, t), self._rot(i, t), t)

    # ---- particles (free VFX) -----------------------------------------------------------
    def _bursts(self, bursts: list[dict]) -> np.ndarray:
        rows = []
        for b in bursts:
            lo, hi = b.get("life", (0.8, 1.8))
            for _ in range(int(b["n"])):
                a, v = self.rng.uniform(0, 2 * math.pi), b["speed"] * self.rng.uniform(0.15, 1.0)
                rows.append((b["t"], b["x"] * W, b["y"] * H, math.cos(a) * v, math.sin(a) * v,
                             self.rng.uniform(lo, hi), self.rng.uniform(1.5, 4.5)))
        return np.array(rows, np.float32) if rows else np.zeros((0, 7), np.float32)

    def particles(self, f: np.ndarray, t: float) -> np.ndarray:
        if not len(self.parts):
            return f
        a = self.parts[(self.parts[:, 0] <= t) & (self.parts[:, 0] + self.parts[:, 5] >= t)]
        if not len(a):
            return f
        layer = np.zeros((H, W, 3), np.float32)
        for t0, x, y, vx, vy, life, sz in a:
            age, fr = t - t0, 1 - (t - t0) / life
            px = x + vx * age * (1 - .35 * age)
            py = y + vy * age * (1 - .35 * age) + 30 * age * age
            if not (-20 < px < W + 20 and -20 < py < H + 20):
                continue
            col = (60 + 195 * fr, 150 + 100 * fr, 255) if fr > .55 else (40, 90 * fr + 40, 255 * fr + 60)  # BGR
            col = tuple(int(min(255, max(0, c))) for c in col)
            cv2.line(layer, (int(px - vx * .028), int(py - vy * .028)), (int(px), int(py)), col,
                     max(1, int(sz * (.5 + fr))), cv2.LINE_AA)
        return f + cv2.GaussianBlur(layer, (0, 0), 3) * 1.4 + layer

    def _shot_at(self, t: float) -> int:
        n = len(self.shots)
        return max(j for j in range(n) if self.starts[j] <= t + 0.02) if t + 0.02 < self.total + 1 else n - 1

    def drift(self, f: np.ndarray, t: float) -> np.ndarray:
        """a soft light that wanders across a motion-bank background: dark clips otherwise encode as identical frames and trip the freeze gate"""
        cx = 0.5 + 0.30 * math.sin(2 * math.pi * t / 5.0)
        cy = 0.45 + 0.22 * math.sin(2 * math.pi * t / 7.0 + 1.0)
        yy, xx = self._gy, self._gx
        g = np.exp(-(((xx - cx) ** 2) * 1.6 + ((yy - cy) ** 2)) / 0.045).astype(np.float32)
        g = cv2.resize(g, (W, H), interpolation=cv2.INTER_LINEAR)[..., None]
        tint = np.array(self.drift_tint, np.float32)
        return np.clip(f.astype(np.float32) + g * tint, 0, 255).astype(np.uint8)

    def motion(self, f: np.ndarray, t: float) -> np.ndarray:
        """moving light layer from the motion bank over the current shot (fx on the shot: clip, blend, op)"""
        i = self._shot_at(t)
        fx = self.fx[i]
        if not fx or i in self.vids:
            return f
        st = self.starts[i]
        fade = min(1.0, (t - st) / 0.35 + 0.25) if t < st + 0.35 else 1.0          # ease in after the cut
        clip = self.layers[fx["clip"]].frame_at(t - st, (W, H))
        return motionbank.blend(f, clip, float(fx.get("op", 0.5)) * fade, fx.get("blend", "screen"), self.fx_mask)

    # ---- frame --------------------------------------------------------------------------
    def _overlay(self, n: int):
        """decoded (premultiplied rgb, 1-alpha) for frame n; cached because HUD frames are held for `ovl_step` frames."""
        idx = n - n % self.ovl_step
        idx = self.ovl_map.get(idx, idx)
        if self._ovl_cache[0] == idx:
            return self._ovl_cache[1]
        o = cv2.imread(str(self.ovl_dir / f"{idx:05d}.png"), cv2.IMREAD_UNCHANGED)
        val = None
        if o is not None:
            a = o[..., 3:4]
            a3 = np.repeat(a, 3, axis=2)
            val = (cv2.multiply(o[..., :3], a3, scale=1 / 255), cv2.subtract(np.full_like(a3, 255), a3))
        self._ovl_cache = (idx, val)
        return val

    def frame(self, n: int) -> np.ndarray:
        t = n / FPS
        bg = self.background(t)
        if len(self.parts) and self.parts[0, 0] <= t:
            bg = self.particles(bg.astype(np.float32), t)
        f = np.clip(bg, 0, 255).astype(np.uint8)
        if self.lut is not None:
            f = cv2.LUT(f, self.lut)
        f = self.motion(f, t)
        i = self._shot_at(t)
        if i in self.vids and self.shots[i].get("pingpong"):
            f = self.drift(f, t)
        f = cv2.multiply(f, self.vig8, scale=1 / 255)
        fi, fo = self.spec.get("fade_in", 0.35), self.spec.get("fade_out", 0.4)
        k = (t / fi if t < fi else 1.0) * (max(0, (self.total - t) / fo) if t > self.total - fo else 1.0)
        if k < 1.0:
            f = cv2.convertScaleAbs(f, alpha=k)
        if self.ovl_dir:
            ov = self._overlay(n)
            if ov is not None:
                f = cv2.add(cv2.multiply(f, ov[1], scale=1 / 255), ov[0])
        pos, neg = self.grain[n % 6]
        return cv2.subtract(cv2.add(f, pos), neg)

    def frame_bytes(self, n: int) -> bytes:
        return self.frame(n).tobytes()

    def encode(self, out: Path, audio: Path | None, workers: int | None = None) -> None:
        """frames are independent, so render them on every core (fork shares the loaded images) and stream in order."""
        global _ACTIVE
        _ACTIVE = self
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-"]
        if audio:
            cmd += ["-i", str(audio), "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,apad[a]", "-map", "0:v", "-map", "[a]", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "192k", "-movflags", "+faststart", str(out)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        n_frames = int(self.total * FPS)
        with mp.get_context("fork").Pool(workers or os.cpu_count() or 2) as pool:
            for b in pool.imap(_frame_job, range(n_frames), chunksize=12):
                p.stdin.write(b)
        p.stdin.close()
        p.wait()


_ACTIVE: "Cinematic | None" = None


def _frame_job(n: int) -> bytes:
    return _ACTIVE.frame_bytes(n)


def main(argv: list[str]) -> int:
    mode, spec_path = argv[0], Path(argv[1])
    spec = json.loads(spec_path.read_text())
    c = Cinematic(spec, spec_path.parent)
    if mode == "test":
        out = spec_path.parent / "work" / "cine_test"
        out.mkdir(parents=True, exist_ok=True)
        for n in map(int, argv[2].split(",")):
            cv2.imwrite(str(out / f"{n:05d}.jpg"), c.frame(n), [cv2.IMWRITE_JPEG_QUALITY, 85])
        print("wrote", out)
    else:
        audio = spec_path.parent / spec["audio"] if spec.get("audio") else None
        c.encode(Path(argv[2]), audio)
        print("done", argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
