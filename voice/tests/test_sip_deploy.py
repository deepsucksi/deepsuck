"""deploy/ 自建 SIP 软电话 profile 的静态检查：compose、Asterisk 配置模板、entrypoint 校验与渲染。
不需要 Docker、不起 Asterisk；entrypoint 用 DEEPSUCK_SIP_RENDER_ONLY 渲染到临时目录。"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
SIP = DEPLOY / "sip"
CONF = SIP / "conf"

GOOD_ENV = {
    "VOICE_TELEPHONY": "1", "VOICE_TELEPHONY_TOKEN": "tok" + "0123456789abcdef" * 2,
    "VOICE_TELEPHONY_ADAPTERS": "ws-raw,asterisk-ws", "SIP_USER": "ds1a2b3c4d",
    "SIP_PASSWORD": "pw" + "fedcba9876543210" * 2, "SIP_PORT": "25060", "SIP_AI_EXTEN": "9000",
    "SIP_RTP_PORTS": "40100-40199", "VOICE_PUBLIC_IP": "203.0.113.7", "VOICE_MAX_MINUTES": "5",
}


def compose():
    return yaml.safe_load((DEPLOY / "docker-compose.yml").read_text())


def env_example():
    out = {}
    for line in (DEPLOY / ".env.example").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def active_lines(name):
    return [ln.split(";", 1)[0].strip() for ln in (CONF / name).read_text().splitlines()
            if ln.split(";", 1)[0].strip()]


# ---- compose ----

def test_sip_service_off_by_default_and_limited():
    svc = compose()["services"]["sip"]
    assert svc["profiles"] == ["sip"]
    assert re.fullmatch(r"andrius/asterisk:22\.\d+\.\d+-alpine-3\.\d+", svc["image"])  # 固定版本，可直接拉取
    assert svc["mem_limit"].startswith("${SIP_MEM_LIMIT:-") and svc["mem_limit"].endswith("m}")
    assert svc["cap_drop"] == ["ALL"] and "no-new-privileges:true" in svc["security_opt"]
    assert svc["network_mode"] == "host"
    assert "env_file" not in svc  # 不把 DASHSCOPE_API_KEY 等整份 .env 交给 Asterisk
    env = svc["environment"]
    assert env["SIP_PASSWORD"] == "${SIP_PASSWORD:-}"  # 不能用 :?，否则默认部署（不开 sip）也会报错
    assert env["SIP_VOICE_URL"] == "ws://127.0.0.1:7860"
    assert "./sip:/deepsuck:ro" in svc["volumes"]
    # 其他服务都不在 sip profile 里，默认部署不受影响
    for name, s in compose()["services"].items():
        if name != "sip":
            assert "sip" not in (s.get("profiles") or [])


def test_env_example_ports_do_not_overlap():
    env = env_example()
    assert env["SIP_PASSWORD"] == "" and env["SIP_USER"] == ""
    assert env["SIP_PORT"] not in ("5060", "5061")
    lo, hi = map(int, env["SIP_RTP_PORTS"].split("-"))
    # 开 sip 时网页语音改用 40000-40099（bootstrap.sh 自动改），两段不重叠且都在服务器已开的 40000-40199 内
    assert 40000 <= lo and hi <= 40199 and lo > 40099
    assert "40000-40099" in (DEPLOY / "bootstrap.sh").read_text()
    for k in ("SIP_USER", "SIP_PASSWORD", "SIP_PORT", "SIP_AI_EXTEN", "SIP_RTP_PORTS", "SIP_TCP", "SIP_MAX_CALLS",
              "SIP_CODECS", "SIP_ALLOW_CIDR", "SIP_PUBLIC_IP", "SIP_LOG_DIR", "SIP_MEM_LIMIT"):
        assert k in env, k
        assert f"`{k}`" in (ROOT / "docs" / "PHONE.md").read_text(), k


def test_caddy_does_not_expose_asterisk_ws():
    text = (DEPLOY / "caddy" / "Caddyfile").read_text()
    block = re.search(r"handle /telephony/asterisk-ws\* \{\s*respond 404\s*\}", text)
    assert block and block.start() < text.index("reverse_proxy 127.0.0.1:7860")


# ---- Asterisk 配置模板 ----

def test_modules_whitelist_excludes_risky_modules():
    lines = active_lines("modules.conf")
    assert "autoload = no" in lines
    loaded = {ln.split("=", 1)[1].strip() for ln in lines if ln.startswith("load")}
    for bad in ("res_pjsip_outbound_registration.so", "res_pjsip_endpoint_identifier_anonymous.so",
                "res_pjsip_endpoint_identifier_ip.so", "res_ari.so", "res_manager_devicestate.so", "chan_iax2.so",
                "app_voicemail.so", "res_pjsip_config_wizard.so", "app_system.so", "func_shell.so", "res_agi.so",
                "app_originate.so", "pbx_spool.so", "res_pjsip_refer.so", "res_pjsip_messaging.so"):
        assert bad not in loaded, bad
    for need in ("chan_pjsip.so", "res_pjsip_authenticator_digest.so", "chan_websocket.so",
                 "res_websocket_client.so", "res_security_log.so", "codec_opus_open_source.so"):
        assert need in loaded, need


def test_management_interfaces_disabled():
    assert "enabled = no" in active_lines("http.conf")
    assert "enabled = no" in active_lines("manager.conf")
    assert "enabled = no" in active_lines("ari.conf")


def test_pjsip_has_single_authenticated_endpoint_and_no_trunk():
    text = "\n".join(active_lines("pjsip.conf"))
    assert "type = registration" not in text and "type = identify" not in text
    assert "outbound_auth" not in text and "anonymous" not in text.lower()
    assert text.count("type = endpoint") == 1 and text.count("type = auth") == 1
    assert "auth = ${SIP_USER}-auth" in text and "context = deepsuck-in" in text
    assert "endpoint_identifier_order = username" in text
    assert "max_contacts = 1" in text and "allow_transfer = no" in text and "direct_media = no" in text


def test_dialplan_only_ai_extension():
    lines = active_lines("extensions.conf")
    contexts = [ln for ln in lines if ln.startswith("[")]
    assert contexts == ["[general]", "[deepsuck-in]"]
    exts = sorted({m.group(1) for ln in lines if (m := re.match(r"exten\s*=>\s*([^,]+),", ln))})
    assert exts == sorted(["${SIP_AI_EXTEN}", "i", "t"])  # 没有 _X. 之类的模式，其他号码 PJSIP 直接 404
    dials = [ln for ln in lines if "Dial(" in ln]
    assert len(dials) == 1 and "Dial(WebSocket/deepsuck/" in dials[0]
    assert not any(re.search(r"(PJSIP|SIP|IAX2|Local)/", ln) for ln in lines)


def test_websocket_client_points_to_local_voice_with_token():
    lines = active_lines("websocket_client.conf")
    assert "uri = ${SIP_VOICE_URL}/telephony/asterisk-ws" in lines  # token 不进 URL（访问日志会记录 URL）
    assert "password = ${SIP_TOKEN}" in lines
    assert "tls_enabled = no" in lines


# ---- entrypoint：校验 + 渲染 ----

needs_tools = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("envsubst")),
                                 reason="需要 bash 和 envsubst（gettext）")


def render(tmp_path, **override):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **GOOD_ENV, **override}
    env = {k: v for k, v in env.items() if v is not None}
    out = tmp_path / "etc"
    out.mkdir(exist_ok=True)
    env["DEEPSUCK_SIP_RENDER_ONLY"] = str(out)
    p = subprocess.run(["bash", str(SIP / "entrypoint.sh")], env=env, capture_output=True, text=True, timeout=30)
    return p, out


@needs_tools
@pytest.mark.parametrize("override", [
    {"SIP_PASSWORD": None}, {"SIP_PASSWORD": ""}, {"SIP_PASSWORD": "short123"},
    {"SIP_PASSWORD": "has;semicolon_0123456789"}, {"SIP_PASSWORD": "ds1a2b3c4d", "SIP_USER": "ds1a2b3c4d"},
    {"SIP_USER": ""}, {"SIP_USER": "bad user"}, {"VOICE_TELEPHONY": "0"}, {"VOICE_TELEPHONY_TOKEN": ""},
    {"VOICE_TELEPHONY_ADAPTERS": "ws-raw"}, {"SIP_AI_EXTEN": "9*"}, {"SIP_PORT": "80"},
    {"SIP_RTP_PORTS": "40199-40100"}, {"SIP_VOICE_URL": "ws://203.0.113.9:7860"}, {"SIP_CODECS": "g729"},
    {"SIP_ALLOW_CIDR": "1.2.3.0/24;evil"}, {"VOICE_PUBLIC_IP": "not-an-ip"},
])
def test_entrypoint_refuses_bad_env(tmp_path, override):
    p, out = render(tmp_path, **override)
    assert p.returncode == 64, p.stdout + p.stderr
    assert "拒绝启动" in p.stderr
    assert not list(out.iterdir())
    secret = override.get("SIP_PASSWORD") or GOOD_ENV["SIP_PASSWORD"]
    assert secret not in p.stdout + p.stderr and GOOD_ENV["VOICE_TELEPHONY_TOKEN"] not in p.stdout + p.stderr


@needs_tools
def test_entrypoint_renders_configs(tmp_path):
    p, out = render(tmp_path, SIP_TCP="1", SIP_ALLOW_CIDR="198.51.100.0/24,192.0.2.10/32")
    assert p.returncode == 0, p.stderr
    log = p.stdout + p.stderr
    assert GOOD_ENV["SIP_PASSWORD"] not in log and GOOD_ENV["VOICE_TELEPHONY_TOKEN"] not in log
    files = {f.name: f.read_text() for f in out.iterdir()}
    assert set(files) == {f.name for f in CONF.glob("*.conf")}
    pj = files["pjsip.conf"]
    assert "bind = 0.0.0.0:25060" in pj and "protocol = tcp" in pj.replace("protocol=tcp", "protocol = tcp")
    assert "external_media_address=203.0.113.7" in pj and "local_net=10.0.0.0/8" in pj
    assert "[ds1a2b3c4d]" in pj and f"password = {GOOD_ENV['SIP_PASSWORD']}" in pj
    assert "deny=0.0.0.0/0.0.0.0" in pj and "permit=198.51.100.0/24" in pj and "permit=192.0.2.10/32" in pj
    assert "allow = opus,g722,ulaw,alaw" in pj
    assert "${" not in pj
    # 密码只出现在 pjsip.conf，token 只出现在 websocket_client.conf
    assert [n for n, t in files.items() if GOOD_ENV["SIP_PASSWORD"] in t] == ["pjsip.conf"]
    assert [n for n, t in files.items() if GOOD_ENV["VOICE_TELEPHONY_TOKEN"] in t] == ["websocket_client.conf"]
    ext = files["extensions.conf"]
    assert "exten => 9000,1," in ext and "Dial(WebSocket/deepsuck/c(slin16)f(json),15)" in ext
    assert "TIMEOUT(absolute)=330" in ext and "${EXTEN}" in ext and "${CALLERID(num)}" in ext  # Asterisk 变量原样保留
    assert "rtpstart = 40100" in files["rtp.conf"] and "rtpend = 40199" in files["rtp.conf"]
    assert "maxcalls = 4" in files["asterisk.conf"]
    assert "uri = ws://127.0.0.1:7860/telephony/asterisk-ws\n" in files["websocket_client.conf"]


@needs_tools
def test_entrypoint_without_public_ip_or_tcp(tmp_path):
    p, out = render(tmp_path, VOICE_PUBLIC_IP="")
    assert p.returncode == 0, p.stderr
    pj = (out / "pjsip.conf").read_text()
    assert "external_media_address" not in pj and "protocol = tcp" not in pj and "type = acl" not in pj
    assert "公网" in p.stdout + p.stderr  # 提醒没有公网 IP


# ---- bootstrap.sh 回归（桩替换 docker/systemctl 等，见 deploy/tests/test_bootstrap.sh） ----

def test_bootstrap_script_regressions():
    r = subprocess.run(["bash", str(DEPLOY / "tests" / "test_bootstrap.sh")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
