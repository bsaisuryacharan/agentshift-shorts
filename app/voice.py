"""Voice + sound: parallel neural TTS with per-word timestamps, then a mastered mix.

Fast: every beat is synthesised concurrently (asyncio.gather) -> a 45 s Short's voice takes ~5 s, not ~40 s.
Free: edge-tts. Set AGENT_CA_BUNDLE=/path/ca.pem if your network uses a TLS proxy.

timing.json:  {"total": s, "segments": [{"key","text","start","dur","words":[{"w","s","e"}]}]}
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

GAP = 0.18
ASSETS = Path(__file__).parent / "assets"


def _ff(*a: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)


def _dur(p: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]))


async def _seg(text: str, voice: str, rate: str, path: Path) -> list[dict]:
    import edge_tts
    if os.environ.get("AGENT_CA_BUNDLE"):
        import ssl
        import edge_tts.communicate as c
        c._SSL_CTX = ssl.create_default_context(cafile=os.environ["AGENT_CA_BUNDLE"])
    words = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"w": ch["text"], "s": ch["offset"] / 1e7, "e": (ch["offset"] + ch["duration"]) / 1e7})
    return words


async def _seg_retry(sem: asyncio.Semaphore, *a) -> list[dict]:
    async with sem:                       # a few at a time: the free endpoint rejects bursts of 8+
        for attempt in range(4):
            try:
                return await _seg(*a)
            except Exception:             # NoAudioReceived / transient WS errors
                if attempt == 3:
                    raise
                await asyncio.sleep(0.8 * (attempt + 1))


async def synth(spec: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    beats = spec["beats"]
    paths = [out / f"seg{i}.mp3" for i in range(len(beats))]
    sem = asyncio.Semaphore(int(os.environ.get("TTS_CONCURRENCY", "4")))
    results = await asyncio.gather(*[_seg_retry(sem, b["say"], spec.get("voice", "en-US-AndrewNeural"), spec.get("rate", "+10%"), p)
                                     for b, p in zip(beats, paths)])
    t, segs = 0.0, []
    sil = out / "gap.mp3"
    _ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(GAP), "-c:a", "libmp3lame", str(sil))
    lst = out / "list.txt"
    with open(lst, "w") as f:
        for b, p, words in zip(beats, paths, results):
            d = _dur(p)
            segs.append({"key": b["key"], "text": b["say"], "start": round(t, 3), "dur": round(d, 3),
                         "words": [{"w": w["w"], "s": round(t + w["s"], 3), "e": round(t + w["e"], 3)} for w in words]})
            f.write(f"file '{p.resolve()}'\nfile '{sil.resolve()}'\n")
            t += d + GAP
    _ff("-f", "concat", "-safe", "0", "-i", str(lst), "-ar", "44100", "-ac", "1", str(out / "narration.wav"))
    timing = {"id": spec.get("id"), "total": round(_dur(out / "narration.wav"), 3), "segments": segs}
    (out / "timing.json").write_text(json.dumps(timing, indent=1, ensure_ascii=False))
    return timing


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def word_time(timing: dict, key: str, word: str, nth: int = 0, default: float | None = None) -> float:
    seg = next(s for s in timing["segments"] if s["key"] == key)
    hits = [w["s"] for w in seg["words"] if norm(w["w"]).startswith(norm(word))]
    if len(hits) > nth:
        return hits[nth]
    if default is not None:
        return default
    raise KeyError(f"word '{word}' (#{nth}) not found in beat '{key}'")


def _sfx(out: Path) -> Path:
    d = out / "sfx"
    d.mkdir(exist_ok=True)
    _ff("-f", "lavfi", "-i", "anoisesrc=d=0.5:c=pink:a=0.6", "-af",
        "highpass=f=300,lowpass=f=6000,afade=t=in:d=0.25:curve=exp,afade=t=out:st=0.28:d=0.22,volume=0.9", str(d / "whoosh.wav"))
    _ff("-f", "lavfi", "-i", "aevalsrc=0.9*sin(2*PI*(110-70*t)*t)*exp(-6*t):s=44100:d=0.7", str(d / "impact.wav"))
    _ff("-f", "lavfi", "-i", "aevalsrc=0.35*(sin(2*PI*1320*t)+0.6*sin(2*PI*1980*t))*exp(-7*t):s=44100:d=0.6", str(d / "ding.wav"))
    _ff("-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*(500+1800*t)*t)*exp(-3*t):s=44100:d=0.35", str(d / "pop.wav"))
    return d


def mix(spec: dict, timing: dict, out: Path, total: float, bed: Path | None = None) -> Path:
    """voice + ducked music bed + SFX, EBU R128 normalised to -14 LUFS (single pass, TP -1.5)."""
    sfx = _sfx(out)
    hits = [(s["start"] - 0.12, "whoosh", 0.8) for s in timing["segments"][1:]]
    for b in spec["beats"]:
        for word, kind, vol in b.get("sfx", []):
            hits.append((word_time(timing, b["key"], word, default=next(s["start"] for s in timing["segments"] if s["key"] == b["key"])), kind, vol))
    inputs = ["-i", str(out / "narration.wav"), "-stream_loop", "-1", "-i", str(bed or ASSETS / "bed01.wav")]
    filt = ["[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=0:%.2f,asplit=2[vo][sc]" % total,
            f"[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{total:.2f},volume=0.30,afade=t=out:st={total-1.2:.2f}:d=1.2[mus]",
            "[mus][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck]"]
    labels = ["[vo]", "[duck]"]
    for i, (t, kind, vol) in enumerate(hits):
        inputs += ["-i", str(sfx / f"{kind}.wav")]
        ms = max(0, int(t * 1000))
        filt.append(f"[{i+2}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={vol},adelay={ms}|{ms}[h{i}]")
        labels.append(f"[h{i}]")
    filt.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,atrim=0:{total:.2f},"
                "loudnorm=I=-14:TP=-1.5:LRA=11[out]")
    dest = out / "mix.wav"
    _ff(*inputs, "-filter_complex", ";".join(filt), "-map", "[out]", "-ac", "2", "-ar", "44100", str(dest))
    return dest
