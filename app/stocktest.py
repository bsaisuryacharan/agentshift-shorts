"""Smoke test for the stock-footage fallback: python -m app.stocktest [out_dir]  (used by .github/workflows/stock-test.yml)"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from . import footage

QUERIES = ["volcano eruption", "ocean waves aerial", "northern lights", "microscope cells", "city traffic night"]


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    tiles, found = [], 0
    for i, q in enumerate(QUERIES):
        cands = footage.stock_candidates(q)
        meta = footage.fetch_stock(q, out / f"{i}.mp4")
        print(f"{q!r}: {len(cands)} candidates, ", f"ok {meta['id']}" if meta else "none passed", flush=True)
        tile = np.zeros((480, 270, 3), np.uint8)
        if meta:
            found += 1
            cap = cv2.VideoCapture(str(out / meta["file"]))
            ok, f = cap.read()
            cap.release()
            if ok:
                tile = cv2.resize(f, (270, 480))
        cv2.putText(tile, q[:22], (6, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        tiles.append(tile)
    cv2.imwrite(str(out / "sheet.jpg"), np.hstack(tiles))
    print(f"{found}/{len(QUERIES)} queries produced a usable clip")
    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("stocktest_out")))
