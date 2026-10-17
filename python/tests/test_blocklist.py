import json

from conftest import fixture
from deepsuck import Session
from deepsuck import blocklist as BL

FX = fixture("blocklist")


def test_fixture_parity():
    for c in FX["fnv"]:
        assert BL.fnv1a(c["input"]) == c["hash"]
        assert BL.shard_of(c["input"]) == c["shard"]
    for c in FX["hosts"]:
        h = BL.host_of(c["input"])
        assert h == c["host"], c["input"]
        if h:
            assert BL.candidates(h) == c["candidates"]
    for c in FX["wallets"]:
        assert BL.wallet_key(c["input"]) == c["key"]


def _fake_client():
    shards = {}
    for d, bits in {"evil-demo.example": 1, "refund-tb-kefu.example": 3, "only-pdb.example": 2}.items():
        shards.setdefault(BL.shard_of(d), []).append(f"{d}\t{bits}")
    files = {"x/meta.json": json.dumps({"generatedAt": "2026-10-18T00:00:00Z", "total": 3,
                                         "sources": [{"name": "destroylist"}, {"name": "Phishing.Database"}]})}
    for sid, lines in shards.items():
        files[f"x/d/{sid}.txt"] = "\n".join(lines)
    for s in BL.WALLET_SOURCES:
        files[s["url"]] = (json.dumps(["0xabcdef0123456789abcdef0123456789abcdef01"]) if s["format"] == "json-array"
                           else "TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe\n")

    def fetch(u):
        if u in files:
            return files[u]
        if u.startswith("x/d/"):
            return ""
        raise IOError("404")
    return BL.Client("x", fetch_text=fetch)


def test_domain_and_wallet():
    c = _fake_client()
    r = c.check_domain("https://refund-tb-kefu.example/dl")
    assert r["status"] == "hit" and r["how"] == "exact" and r["sources"] == ["destroylist", "Phishing.Database"]
    r = c.check_domain("login.evil-demo.example")
    assert r["status"] == "hit" and r["how"] == "parent"
    assert c.check_domain("good.example")["status"] == "clean"
    assert c.check("crypto_eth", "0xABCDEF0123456789ABCDEF0123456789ABCDEF01")["status"] == "hit"
    assert c.check("crypto_tron", "TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDf")["status"] == "clean"
    assert BL.Client("nope", fetch_text=lambda u: (_ for _ in ()).throw(IOError())).check_domain("a.example")["status"] == "unavailable"


def test_annotate_session_no_leak():
    s = Session("refund", "wang")
    s.ingest("下载链接 https://refund-tb-kefu.example/dl ，USDT 打到 TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe")
    _fake_client().annotate_session(s)
    st = {i["type"]: i["blocklist"]["status"] for i in s.intel_list()}
    assert st == {"url": "hit", "crypto_tron": "hit"}
    js = json.dumps(s.report(), ensure_ascii=False)
    assert "refund-tb-kefu.example" not in js and "TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe" not in js
