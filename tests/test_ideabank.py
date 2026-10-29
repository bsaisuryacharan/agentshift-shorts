import json

from app import ideabank


def test_hint_and_ideas_from_the_bank(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"formats": [{"name": "how it really works", "shape": "one mechanism"}], "hooks": ["Result first."],
                             "ideas": [{"title": "How submarines make air", "views": 9}, {"title": "AI tool demo", "views": 99, "niche": "AI tools (format only)"}],
                             "recent": [{"title": "Fresh one", "views": 50}]}))
    h = ideabank.hint(path=p)
    assert "how it really works" in h and "Result first." in h and "Fresh one" in h
    assert ideabank.ideas(path=p) == ["Fresh one", "How submarines make air"]          # format-only ideas never become topics


def test_refresh_reads_reference_channels(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"reference_channels": [{"name": "Tangent", "id": "C1"}]}))

    class R:
        def __init__(self, d): self.d = d
        def raise_for_status(self): pass
        def json(self): return self.d

    class C:
        def get(self, url, params=None, timeout=None):
            if url.endswith("/search"):
                return R({"items": [{"id": {"videoId": "v1"}, "snippet": {"title": "How X works"}}]})
            return R({"items": [{"id": "v1", "statistics": {"viewCount": "123456"}}]})
    assert ideabank.refresh("k", path=p, client=C()) == 1
    d = json.loads(p.read_text())
    assert d["recent"][0] == {"channel": "Tangent", "title": "How X works", "views": 123456, "url": "https://youtube.com/shorts/v1"}


def test_committed_bank_is_valid():
    d = ideabank.load()
    assert d["reference_channels"] and d["formats"] and d["hooks"] and ideabank.ideas()
