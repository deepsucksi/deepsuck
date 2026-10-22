from fastapi.testclient import TestClient

from voice import app as A


def test_config_and_index():
    c = TestClient(A.create_app("rule"))
    r = c.get("/api/config").json()
    assert r["keyConfigured"] is True and r["engine"] == "rule"
    ps = r["personas"]
    assert [p["id"] for p in ps] == ["wang", "chen", "lin", "zheng"]
    assert [(p["no"], p["role"]) for p in ps] == [("01", "退休老人"), ("02", "宝妈"), ("03", "刚毕业学生"), ("04", "个体小老板")]
    for p in ps:
        assert p["photo"].startswith("/static/brand/") and c.get(p["photo"]).status_code == 200
    assert r["aliases"] == {"li": "wang", "xiaochen": "chen", "mom": "chen", "shop_owner": "zheng"}
    assert "test-key" not in str(r)  # 不回显 key
    html = c.get("/").text
    assert "DeepSuck" in html
    assert c.get("/static/voice.js").status_code == 200
    assert c.get("/static/logo.svg").status_code == 200


def test_brand_assets_whitelist():
    """R11 品牌文件：白名单内可取，类型正确；白名单外与路径穿越一律 404。"""
    c = TestClient(A.create_app("rule"))
    for name, (_, ctype) in A.BRAND_FILES.items():
        r = c.get("/static/brand/" + name)
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype), name
    assert c.get("/static/brand/nope.png").status_code == 404
    assert c.get("/static/brand/..%2F..%2F.env").status_code == 404
    html = c.get("/").text
    for ref in ("/static/brand/wordmark.svg", "/static/brand/symbol.png", "/static/brand/Manrope.ttf"):
        assert ref in html


def test_offer_without_key_is_503(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    c = TestClient(A.create_app())
    r = c.post("/api/offer", json={"sdp": "x", "type": "offer"})
    assert r.status_code == 503 and "DASHSCOPE_API_KEY" in r.json()["detail"]


def test_load_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSUCK_TEST_X", raising=False)
    monkeypatch.setattr(A, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("# c\nDEEPSUCK_TEST_X='abc'\n", encoding="utf-8")
    A.load_env()
    import os
    assert os.environ["DEEPSUCK_TEST_X"] == "abc"


def test_main_help(capsys):
    import pytest
    with pytest.raises(SystemExit):
        A.main(["--help"])
    assert "--engine" in capsys.readouterr().out


def test_offer_guards(monkeypatch, tmp_path):
    from voice import guard as G
    monkeypatch.setenv("VOICE_ALLOWED_ORIGINS", "https://live.deepsuck.si")
    lim = G.Limits(max_sessions=1)
    b = G.VoiceBudget(cap_cny=0.5, data_dir=str(tmp_path))
    app = A.create_app("rule", limits=lim, budget=b)
    c = TestClient(app)
    offer = {"sdp": "v=0", "type": "offer"}
    assert c.post("/api/offer", json=offer, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/offer", json=offer).status_code == 403  # 缺 Origin
    H = {"Origin": "https://live.deepsuck.si"}
    assert c.post("/api/offer", json={"sdp": 1, "type": "offer"}, headers=H).status_code == 400
    app.state.gate.active["busy"] = "9.9.9.9"
    r = c.post("/api/offer", json=offer, headers=H)
    assert r.status_code == 503 and "同时通话" in r.json()["detail"]
    app.state.gate.active.clear()
    tk = b.reserve(0.1); tk.asr(3000)  # 0.72 元 > 0.5 上限
    r = c.post("/api/offer", json=offer, headers=H)
    assert r.status_code == 429 and "额度" in r.json()["detail"]
    cfg = c.get("/api/config").json()
    assert cfg["budget"]["exhausted"] is True and cfg["limits"]["maxSessions"] == 1
    assert c.get("/api/voice/health").json()["budget"]["exhausted"] is True


def test_offer_slot_released_after_connect_timeout(monkeypatch):
    """浏览器从未连上（ICE 失败）时，看门狗在 VOICE_CONNECT_TIMEOUT 后释放并发名额与预占额度。"""
    from voice import guard as G
    monkeypatch.delenv("VOICE_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("VOICE_CONNECT_TIMEOUT", "1")
    from voice import dashscope_ws as ds, processors as P

    async def no_net(*a, **k):
        raise OSError("offline test")

    async def no_fillers(*a, **k):
        return {}
    monkeypatch.setattr(ds, "_connect", no_net)
    monkeypatch.setattr(P, "synth_fillers", no_fillers)
    b = G.VoiceBudget(cap_cny=5)
    app = A.create_app("rule", limits=G.Limits(max_sessions=1), budget=b)
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/api/offer", json={"sdp": "garbage", "type": "offer"})  # TestClient 会等后台通话任务结束
    assert not app.state.gate.active and b.status()["active"] == 0


def test_browser_ice_servers_turn(monkeypatch):
    import base64, hashlib, hmac
    monkeypatch.setenv("VOICE_BROWSER_STUN", "stun:stun.example:3478")
    monkeypatch.setenv("TURN_SECRET", "s3cret")
    monkeypatch.setenv("TURN_URLS", "turn:live.example:3478?transport=udp,turn:live.example:3478?transport=tcp")
    ice = A.browser_ice_servers()
    assert ice[0] == {"urls": ["stun:stun.example:3478"]}
    t = ice[1]
    assert len(t["urls"]) == 2
    exp = base64.b64encode(hmac.new(b"s3cret", t["username"].encode(), hashlib.sha1).digest()).decode()
    assert t["credential"] == exp and "s3cret" not in str(ice)


def test_health_commit_injected(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    r = TestClient(A.create_app("rule")).get("/api/voice/health").json()
    assert r["commit"] == "abc1234" and r["ok"] is True


def test_health_commit_validation(monkeypatch):
    monkeypatch.setattr(A.TR, "_git_sha", lambda root: "")
    for bad in ["", "unknown", "ABC1234", "abc123", "abc1234567890", "abc1234;rm", "v1.2.3", " ", "deadbeef\nx"]:
        monkeypatch.setenv("GIT_COMMIT", bad)
        assert A.public_commit() == "unknown", bad
    monkeypatch.delenv("GIT_COMMIT")
    assert TestClient(A.create_app("rule")).get("/api/voice/health").json()["commit"] == "unknown"
    for ok in ["0123456", "0123456789ab"]:
        monkeypatch.setenv("GIT_COMMIT", ok)
        assert A.public_commit() == ok


def test_health_commit_falls_back_to_gitmeta(monkeypatch):
    """compose 默认 unknown（未注入）时退回镜像 .gitmeta 的 HEAD，标准部署命令无需改动；非法值也不透出。"""
    monkeypatch.setenv("GIT_COMMIT", "unknown")
    monkeypatch.setattr(A.TR, "_git_sha", lambda root: "fedcba9")
    assert A.public_commit() == "fedcba9"
    monkeypatch.setattr(A.TR, "_git_sha", lambda root: "ref: x")
    assert A.public_commit() == "unknown"
