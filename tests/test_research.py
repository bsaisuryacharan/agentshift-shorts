from app import auto, research


class R:
    status_code = 200

    def __init__(self, d): self.d = d
    def raise_for_status(self): pass
    def json(self): return self.d


def client(results):
    class C:
        def post(self, *a, **k): return R({"results": results})
    return C()


def test_no_key_keeps_wikipedia_only(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    f = {"text": "wiki text", "url": "u"}
    assert research.enrich(f, "t") is f


def test_trusted_sources_are_added_and_untrusted_dropped():
    res = [{"url": "https://www.nasa.gov/mission/voyager", "raw_content": "Voyager 1 is 24.9 billion km from Earth. " * 10},
           {"url": "https://randomblog.example/voyager", "raw_content": "made up 99 numbers " * 30},
           {"url": "https://en.wikipedia.org/wiki/Voyager_1", "raw_content": "dup " * 100},
           {"url": "https://www.nasa.gov/other", "raw_content": "second nasa page " * 30}]
    f = research.enrich({"text": "wiki text", "url": "u"}, "Voyager", "Voyager 1", key="k", client=client(res))
    assert f["extra_sources"] == ["https://www.nasa.gov/mission/voyager"]          # one page per domain, no blogs, no Wikipedia twice
    assert "SOURCE nasa.gov" in f["text"] and "randomblog" not in f["text"]
    assert auto._number_supported("24.9", f["text"], "24.9 billion km from Earth")


def test_search_failure_falls_back(monkeypatch):
    class C:
        def post(self, *a, **k):
            import httpx
            raise httpx.ConnectError("down")
    f = {"text": "wiki", "url": "u"}
    assert research.enrich(f, "t", key="k", client=C()) is f
