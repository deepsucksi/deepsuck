"""GitHub #3：UDP 被封时走 TURN over TCP/TLS 443。临时凭据、/api/ice、前端上报写进同一编号的追踪、
Caddy 443 分流、coturn 只听本机、probe 强制中继。全部离线。"""
import base64
import hashlib
import hmac
import json
import re
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from voice import probe
from voice import trace as TR

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
URLS = "turn:live.example:443?transport=tcp,turns:live.example:443?transport=tcp"


def _app(monkeypatch, tmp_path, origins=None):
    from voice import app as A
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("TRACE_MIN_FREE_MB", "0")
    if origins:
        monkeypatch.setenv("VOICE_ALLOWED_ORIGINS", origins)
    else:
        monkeypatch.delenv("VOICE_ALLOWED_ORIGINS", raising=False)
    return A.create_app("rule")


def _lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---- 临时凭据 ----
def test_turn_credentials_short_lived_hmac(monkeypatch):
    from voice import app as A
    monkeypatch.setenv("TURN_SECRET", "s3cret-for-test")
    monkeypatch.setenv("TURN_URLS", URLS)
    ice = A.browser_ice_servers(now=1_000_000)
    t = ice[-1]
    exp, _ = t["username"].split(":")
    assert int(exp) == 1_000_000 + 600  # 默认 10 分钟
    want = base64.b64encode(hmac.new(b"s3cret-for-test", t["username"].encode(), hashlib.sha1).digest()).decode()
    assert t["credential"] == want and "s3cret-for-test" not in json.dumps(ice)
    assert t["urls"] == URLS.split(",")
    assert A.browser_ice_servers(now=1)[-1]["username"] != A.browser_ice_servers(now=1)[-1]["username"]  # 每次新的
    monkeypatch.setenv("TURN_TTL", "5")
    assert A.turn_ttl() == 60
    monkeypatch.setenv("TURN_TTL", "999999")
    assert A.turn_ttl() == 3600
    monkeypatch.setenv("TURN_TTL", "abc")
    assert A.turn_ttl() == 600
    assert A.browser_ice_servers(include_turn=False) == []


def test_config_has_no_turn_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("TURN_SECRET", "s3cret-for-test")
    monkeypatch.setenv("TURN_URLS", URLS)
    c = TestClient(_app(monkeypatch, tmp_path))
    cfg = c.get("/api/config").json()
    assert cfg["turn"] is True and "credential" not in json.dumps(cfg) and "s3cret" not in json.dumps(cfg)


def test_api_ice_issues_fresh_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("TURN_SECRET", "s3cret-for-test")
    monkeypatch.setenv("TURN_URLS", URLS)
    c = TestClient(_app(monkeypatch, tmp_path, origins="https://live.example"))
    assert c.post("/api/ice", json={}).status_code == 403
    assert c.post("/api/ice", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    r = c.post("/api/ice", json={}, headers={"Origin": "https://live.example"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    j = r.json()
    assert j["ttl"] == 600 and j["iceServers"][-1]["credential"] and "s3cret" not in r.text
    codes = [c.post("/api/ice", json={}, headers={"Origin": "https://live.example"}).status_code for _ in range(25)]
    assert 429 in codes  # 同一 IP 每分钟 20 次


def test_api_ice_without_turn(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path))
    j = c.post("/api/ice", json={}).json()
    assert j == {"iceServers": [], "ttl": None}
    assert c.get("/api/config").json()["turn"] is False


# ---- 前端上报 ----
def test_client_report_writes_into_same_trace(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path))
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m")
    r = c.post("/api/client-report", json={"trace_id": t.id, "stage": "ice_timeout", "reason": "超时 来自 10.1.2.3",
                                          "detail": {"ice": "checking", "relayOffered": True, "local": "host/udp:2 relay/tcp:1",
                                                     "elapsedMs": 20003, "sdp": "v=0 secret", "browser": "Safari 18 macOS"}})
    assert r.json() == {"ok": True}
    c.post("/api/client-report", json={"trace_id": t.id, "stage": "connected", "detail": {"path": "relay/tcp"}})
    t.end("connect_timeout")
    rows = _lines(t.path)
    err = next(x for x in rows if x["type"] == "client_error")
    assert err["stage"] == "ice_timeout" and "10.1.2.3" not in json.dumps(err) and "<ip>" in err["reason"]
    assert err["detail"]["relayOffered"] is True and err["detail"]["elapsedMs"] == 20003 and "sdp" not in err["detail"]
    ok = next(x for x in rows if x["type"] == "client_connected")
    assert ok["detail"]["path"] == "relay/tcp"
    stats = json.loads((Path(TR.trace_dir()) / "stats.json").read_text())
    day = next(iter(stats.values()))
    assert day["clientIceTimeout"] == 1 and day["clientConnected"] == 1 and day["clientRelay"] == 1
    from voice import trace_cli
    out = trace_cli.render(TR.load(t.id))
    assert "前端上报失败: ice_timeout" in out and "前端已接通: path=relay/tcp" in out


def test_client_report_without_consent_only_counts(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path))
    off = TR.CallTrace(channel="web", consent=False, persona="lin", scenario="pig", model="m")
    assert c.post("/api/client-report", json={"trace_id": off.id, "stage": "ice_failed"}).status_code == 200
    assert c.post("/api/client-report", json={"stage": "offer_failed", "reason": "HTTP 429"}).status_code == 200
    assert not off.path.exists()
    assert c.post("/api/client-report", json={"stage": "rm -rf"}).status_code == 400
    assert c.post("/api/client-report", content=b"[]", headers={"Content-Type": "application/json"}).status_code == 400
    assert c.post("/api/client-report", json={"trace_id": "../../x", "stage": "ice_failed"}).status_code == 200
    day = next(iter(json.loads((Path(TR.trace_dir()) / "stats.json").read_text()).values()))
    assert day["clientIceFailed"] == 2 and day["clientOfferFailed"] == 1


def test_client_report_capped_per_call(tmp_path):
    env = {"TRACE_DIR": str(tmp_path / "t"), "TRACE_MIN_FREE_MB": "0"}
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", env=env)
    for _ in range(30):
        TR.client_report(t.id, "ice_failed", "x", env=env)
    assert sum(1 for r in _lines(t.path) if r["type"] == "client_error") == TR.MAX_CLIENT_REPORTS


def test_client_report_origin(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path, origins="https://live.example"))
    assert c.post("/api/client-report", json={"stage": "ice_failed"}).status_code == 403


# ---- 部署：443 分流、coturn 只听本机 ----
def test_caddyfile_muxes_turn_on_443():
    s = (DEPLOY / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    assert "servers :443" in s and "listener_wrappers" in s and "layer4" in s
    lw = s[s.index("listener_wrappers"):]
    assert lw.index("layer4") < lw.index("\n\t\t\ttls\n")  # layer4 在 TLS 解密之前
    pats = re.findall(r"regexp (\S+) 8 hex", s)
    assert len(pats) == 2 and all("{" not in p for p in pats)  # 花括号会被 Caddy 当占位符吃掉
    assert re.fullmatch(pats[0].replace("$", "") + "$", "000100002112A442")  # STUN Binding 头
    assert not re.match(pats[0], "16030100C8010000")  # TLS ClientHello 不算
    assert "not tls alpn h2 http/1.1 acme-tls/1" in s  # 浏览器 HTTPS 与证书续期不受影响
    assert s.count("proxy 127.0.0.1:{$TURN_PORT:3478}") == 2
    assert "proxy_protocol v2" in s and "allow 127.0.0.1/32" in s
    # 两个站点共用一份路由，/api/traces* 在两处都是 404
    assert s.count("import live") == 2 and "bind 127.0.0.1" in s and "handle /api/traces*" in s


def test_compose_caddy_l4_and_coturn_local_only():
    c = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    caddy = c["services"]["caddy"]
    assert caddy["build"]["dockerfile"] == "deploy/Dockerfile.caddy" and caddy["image"] == "deepsuck-caddy"
    df = (DEPLOY / "Dockerfile.caddy").read_text(encoding="utf-8")
    assert "github.com/mholt/caddy-l4@" in df and "CADDY_L4_VERSION=v" in df and "GOFLAGS=-p=1" in df
    turn = c["services"]["coturn"]
    cmd = turn["command"]
    assert "turn" in turn["profiles"] and "ports" not in turn
    assert "--listening-ip=127.0.0.1" in cmd and "--no-udp" in cmd and "--use-auth-secret" in cmd
    assert "--denied-peer-ip=0.0.0.0-255.255.255.255" in cmd and "--allowed-peer-ip=${PRIVATE_IP}" in cmd
    assert "--external-ip" not in cmd and turn["mem_limit"] == "64m"
    env = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    assert "TURN_TTL=600" in env and ":443?transport=tcp" in env
    boot = (DEPLOY / "bootstrap.sh").read_text(encoding="utf-8")
    assert ":443?transport=tcp" in boot and "ufw allow 3478" not in boot


# ---- probe 强制中继 ----
def test_probe_pick_relay_and_candidates():
    ice = [{"urls": ["stun:x"]}, {"urls": URLS.split(","), "username": "u", "credential": "c"}]
    assert probe.pick_relay(ice, "tcp")["urls"] == ["turn:live.example:443?transport=tcp"]
    assert probe.pick_relay(ice, "tls")["urls"] == ["turns:live.example:443?transport=tcp"]
    assert probe.pick_relay([{"urls": "turn:x:3478?transport=udp"}], "tcp") is None
    sdp = "a=candidate:1 1 udp 1 172.17.0.1 49160 typ relay raddr 0.0.0.0 rport 0\r\na=candidate:2 1 udp 2 1.2.3.4 5 typ host"
    assert probe.candidate_types(sdp) == {"relay": 1, "host": 1}
    assert probe.exit_code({"relay": {"mode": "tcp"}, "offer_status": None}) == 6
    assert probe.EXIT_REASONS[6] == "relay_unavailable"


def test_probe_force_relay_policy():
    import aiortc.rtcicetransport as rit
    from aioice.ice import TransportPolicy
    orig = rit.connection_kwargs
    try:
        probe.force_relay_policy()
        probe.force_relay_policy()  # 幂等
        assert rit.connection_kwargs([])["transport_policy"] == TransportPolicy.RELAY
    finally:
        rit.connection_kwargs = orig


# ---- 页面：连接状态与失败提示 ----
def test_page_shows_connection_state_and_help():
    js = (ROOT / "voice" / "static" / "voice.js").read_text(encoding="utf-8")
    html = (ROOT / "voice" / "static" / "index.html").read_text(encoding="utf-8")
    assert "CONNECT_TIMEOUT_MS" in js and '"/api/ice"' in js and '"/api/client-report"' in js
    for s in ("正在连接", "已接通", "连接失败", "ice_timeout", "ice_failed", "offer_failed"):
        assert s in js
    assert 'id="netHelp"' in html and "换一个网络" in html and "关闭代理" in html
    assert ".net-help[hidden]" in html
