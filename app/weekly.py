"""Weekly cloud job: refresh trend signals and the owner's channel analytics, then rebuild the committed insights the picker reads.

    python -m app.weekly            # runs in .github/workflows/weekly-insights.yml (cron) - nothing runs on the owner's Mac

Secrets it can use (all optional; without them the parts that need them are skipped and say so):
  YOUTUBE_API_KEY      YouTube Data API key -> popular Shorts in the region (trend signals)
  YOUTUBE_TOKEN_JSON   the content of token.json (yt-analytics.readonly scope) -> the owner's own channel numbers
The token is written to a temp file for the API client and deleted afterwards; it is never printed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    status: dict[str, str] = {}
    tok_path = None
    if os.environ.get("YOUTUBE_TOKEN_JSON"):
        fd, tok_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write(os.environ["YOUTUBE_TOKEN_JSON"])
        os.environ["YOUTUBE_TOKEN_FILE"] = tok_path
    try:
        from .settings import Settings
        settings = Settings()
        try:
            from .trends import analyze
            report = analyze(settings)
            status.update({k: str(v) for k, v in report.source_status.items()})
            status["signals"] = str(len(report.signals))
        except Exception as e:  # noqa: BLE001 - a weak signal must not stop the insights rebuild
            status["trends"] = f"failed: {type(e).__name__}"
    finally:
        if tok_path:
            Path(tok_path).unlink(missing_ok=True)
    from . import insights
    out = insights.build()
    old = insights.load()
    if old.get("performance"):                                   # written hourly by app.monitor: keep it when the weekly rebuild replaces the file
        out["performance"] = old["performance"]
    insights.OUT.parent.mkdir(parents=True, exist_ok=True)
    insights.OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({"status": status, "hint": insights.hint()}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
