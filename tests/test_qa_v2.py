import subprocess, shutil
from pathlib import Path
import pytest
from app import qa_v2

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")

def _clip(tmp: Path, vf: str) -> Path:
    out = tmp / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", vf + ",scale=1080:1920,format=yuv420p",
                    "-f", "lavfi", "-i", "sine=f=220:d=25", "-t", "25", "-shortest", str(out)], check=True)
    return out

def test_static_picture_fails_distinct_shots(tmp_path):
    r = qa_v2.evaluate(_clip(tmp_path, "color=c=gray:s=270x480:r=30:d=25"))
    assert r["checks"]["distinct_shots"].startswith("fail")
    assert r["checks"]["vision"].startswith("fail")        # no review => never approved

def test_missing_review_never_passes(tmp_path):
    assert not qa_v2.evaluate(_clip(tmp_path, "testsrc2=s=270x480:r=30:d=25"))["passed"]

def test_glyph_audit_flags_missing_char():
    f = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not f.exists(): pytest.skip("DejaVu not installed")
    assert qa_v2.glyph_audit("abc \u20b9", f) == []          # rupee present in DejaVu
    assert qa_v2.glyph_audit("abc \u6f22", f) == ["\u6f22"]   # CJK absent -> tofu risk
