"""语音服务端到端探针：用 aiortc 充当"浏览器"，把一段 WAV（16 kHz 单声道）当麦克风推给 /api/offer，
打印数据通道收到的转写 / 机器人回复 / 情报，统计收到的机器人音频时长。部署后可用来验证 UDP/ICE 是否通。

    python -m voice.probe --url http://127.0.0.1:7860 --wav scammer.wav --seconds 40
    python -m voice.probe --url https://live.deepsuck.si --origin https://live.deepsuck.si --wav scammer.wav

会真实调用 DashScope（按量计费，受服务端预算护栏约束）。

强制只走 TURN 中继（验证 UDP 被封时的兜底，GitHub #3）：
    python -m voice.probe --url https://live.deepsuck.si --origin https://live.deepsuck.si --wav x.wav --relay tcp
--relay tcp 只用 turn:...?transport=tcp，--relay tls 只用 turns:；凭据从 POST /api/ice 现取，只生成 relay 候选。

模拟打断（#94）：--barge-in 在 WAV 放完后，等人设开始说正式回复（收到回复通知、且听到人设的声音）时，
把 WAV 里第一段话再推一遍，服务端应在这一轮的 trace 里记 interrupted=true；结果在 barge_in。

退出码（JSON 汇总里的 exit / exit_reason 同步给出）：
  0  正常：/api/offer 200，连上并收到机器人音频
  2  /api/offer 被拒（非 200，例如 403 来源不符、429 限频、503 名额已满）
  3  offer 成功但媒体没连上（ICE/DTLS 失败：多半是 UDP 端口或 VOICE_PUBLIC_IP）
  4  连上了但整段时间没收到任何机器人音频
  5  探测本身正常，但 --json-out 写文件失败
  6  --relay 模式下没拿到中继候选（/api/ice 没给对应的 TURN 地址，或 TURN 连不上 / 凭据被拒）
"""
from __future__ import annotations

import argparse
import asyncio
import fractions
import json
import sys
import time
import wave
from typing import Optional


LOUD_RMS = 200.0  # 机器人音频帧“有声”阈值（int16 RMS）


def speech_segments(pcm: bytes, rate: int = 16000, frame_ms: int = 20, rms: float = 300.0, gap_s: float = 0.6):
    """按能量切出 WAV 里的说话段，返回 [(start_s, end_s)]；间隔小于 gap_s 的合并。"""
    import numpy as np

    x = np.frombuffer(pcm, dtype=np.int16).astype("float64")
    n = rate * frame_ms // 1000
    segs = []
    for i in range(0, len(x) - n + 1, n):
        if float(np.sqrt(np.mean(x[i:i + n] ** 2))) > rms:
            t = i / rate
            if segs and t - segs[-1][1] <= gap_s:
                segs[-1][1] = t + frame_ms / 1000
            else:
                segs.append([t, t + frame_ms / 1000])
    return [(round(a, 2), round(b, 2)) for a, b in segs]


def barge_clip(pcm: bytes, rate: int = 16000, min_s: float = 1.2) -> bytes:
    """打断用的一段话：WAV 里第一段说话（至少 min_s 秒，不够就往后多取一点）。"""
    segs = speech_segments(pcm, rate)
    if not segs:
        return b""
    a, b = segs[0]
    b = max(b, a + min_s)
    return pcm[int(a * rate) * 2:int(b * rate) * 2]


def window_flags(segs, t0: float, times: list) -> list:
    """每段骗子话结束到下一段开始之间是否出现过某类事件（例如服务端通知的填充音）。"""
    out = []
    for i, (_, end) in enumerate(segs):
        lo, hi = t0 + end, (t0 + segs[i + 1][0] if i + 1 < len(segs) else float("inf"))
        out.append(any(lo < t < hi for t in times))
    return out


def client_e2e(segs, t0: float, loud: list) -> list:
    """每段骗子话结束 → 浏览器收到第一帧有声机器人音频（毫秒）；下一段开始前没收到则为 None。"""
    out = []
    for i, (_, end) in enumerate(segs):
        lo = t0 + end
        hi = t0 + segs[i + 1][0] if i + 1 < len(segs) else float("inf")
        hit = next((t for t in loud if lo < t < hi), None)
        out.append(None if hit is None else int(round((hit - lo) * 1000)))
    return out


def headline(server: dict, client: dict, lat: list) -> dict:
    """一眼能看的几项：对方说完到听到第一个声音（含口头语，服务端/客户端）与正式回复首包（服务端）。"""
    return {"first_audible_p50": (server.get("first_audible") or {}).get("p50"),
            "client_first_audible_p50": client.get("p50"),
            "reply_first_packet_p50": (server.get("e2e_reply") or {}).get("p50"),
            "filler_turns": sum(1 for t in lat if t.get("filler")), "turns": len(lat)}


SCAMMER_LINES = [
    "喂，您好，我是淘宝客服，您上周买的那件衣服有质量问题。",
    "我们这边要给您双倍理赔，您先加一下我们的理赔专员。",
    "您需要下载一个叫安心理赔的APP，我把链接发给您。",
    "理赔款要打到您的银行卡上，您用的是哪个银行的卡？",
    "您先往我们的安全账户转一笔保证金，到账后马上退给您。",
    "收款户名写张三就行，卡号我现在念给您。",
]


async def make_scammer_wav(path: str, gap_s: float = 9.0, lead_s: float = 7.0, voice: str = "longanyang") -> list:
    """用 CosyVoice 合成固定的骗子台词（计费：约 150 字），拼成 16k WAV：lead 静音 + (台词 + gap 静音)×N。"""
    from .dashscope_ws import synthesize

    buf = bytearray(b"\x00" * int(16000 * 2 * lead_s))
    for line in SCAMMER_LINES:
        async for c in synthesize(line, voice=voice, sample_rate=16000):
            buf.extend(c)
        buf.extend(b"\x00" * int(16000 * 2 * gap_s))
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(buf))
    return speech_segments(bytes(buf))


def pick_relay(ice_servers: list, mode: str) -> Optional[dict]:
    """从 /api/ice 的结果里挑出唯一一条 TURN 地址：tcp → turn:...?transport=tcp，tls → turns:。"""
    for srv in ice_servers or []:
        urls = srv.get("urls") or []
        urls = [urls] if isinstance(urls, str) else urls
        for u in urls:
            if mode == "tls" and u.startswith("turns:"):
                return {"urls": [u], "username": srv.get("username"), "credential": srv.get("credential")}
            if mode == "tcp" and u.startswith("turn:") and "transport=tcp" in u:
                return {"urls": [u], "username": srv.get("username"), "credential": srv.get("credential")}
    return None


def force_relay_policy() -> None:
    """aiortc 没暴露 iceTransportPolicy：给它的 ICE 连接参数补上 aioice 的 TransportPolicy.RELAY（只收集中继候选）。"""
    import aiortc.rtcicetransport as rit
    from aioice.ice import TransportPolicy

    if getattr(rit.connection_kwargs, "_relay_only", False):
        return
    orig = rit.connection_kwargs

    def relay_kwargs(servers):
        kw = orig(servers)
        kw["transport_policy"] = TransportPolicy.RELAY
        return kw

    relay_kwargs._relay_only = True
    rit.connection_kwargs = relay_kwargs


def candidate_types(sdp: str) -> dict:
    out: dict = {}
    for line in sdp.splitlines():
        if line.startswith("a=candidate:"):
            parts = line.split()
            if "typ" in parts:
                t = parts[parts.index("typ") + 1]
                out[t] = out.get(t, 0) + 1
    return out


async def run(url: str, wav: Optional[str], seconds: float, persona: str, scenario: str, origin: Optional[str],
              out_wav: Optional[str] = None, quiet: bool = False, insecure: bool = False,
              consent: bool = False, relay: Optional[str] = None, flag: Optional[str] = None,
              barge_in: bool = False) -> dict:
    import aiohttp
    import numpy as np
    from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
    from av import AudioFrame

    pcm = b""
    if wav:
        with wave.open(wav, "rb") as w:
            assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, "需要 16k 单声道 16-bit WAV"
            pcm = w.readframes(w.getnframes())

    class Mic(MediaStreamTrack):
        kind = "audio"

        def __init__(self):
            super().__init__()
            self.pos, self.t0, self.n = 0, None, 0
            self.inject = b""  # --barge-in：WAV 放完后插进来的一段话

        async def recv(self):
            if self.t0 is None:
                self.t0 = time.time()
            self.n += 1
            await asyncio.sleep(max(0, self.t0 + self.n * 0.02 - time.time()))
            if self.inject:
                chunk, self.inject = self.inject[:640], self.inject[640:]
            else:
                chunk = pcm[self.pos:self.pos + 640]
                self.pos += 640
            chunk = chunk + b"\x00" * (640 - len(chunk))
            f = AudioFrame.from_ndarray(np.frombuffer(chunk, dtype=np.int16).reshape(1, -1), format="s16", layout="mono")
            f.sample_rate, f.pts, f.time_base = 16000, (self.n - 1) * 320, fractions.Fraction(1, 16000)
            return f

    from aiortc import RTCIceServer

    ice_servers: list = []
    stats_relay: dict = {}
    if relay:
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False) if insecure else None) as s:
            async with s.post(url.rstrip("/") + "/api/ice", headers=headers, json={}) as r:
                ice_body = await r.json(content_type=None) if r.status == 200 else {}
        srv = pick_relay((ice_body or {}).get("iceServers") or [], relay)
        if srv is None:
            return {"offer_status": None, "error": f"/api/ice 没有 {relay} 类 TURN 地址", "relay": {"mode": relay}}
        force_relay_policy()
        ice_servers = [RTCIceServer(urls=srv["urls"], username=srv["username"], credential=srv["credential"])]
        stats_relay = {"mode": relay, "url": srv["urls"][0], "ttl": (ice_body or {}).get("ttl")}
    pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))
    mic = Mic()
    pc.addTransceiver(mic, direction="sendrecv")
    pc.addTransceiver("video", direction="recvonly")
    dc = pc.createDataChannel("chat", ordered=True)
    stats = {"bot_audio_sec": 0.0, "events": [], "connected_after": None}
    fb_key = ""
    if relay:
        stats["relay"] = stats_relay
    bot_pcm = bytearray()
    loud: list = []
    t_start = time.time()

    @dc.on("message")
    def on_msg(m):
        try:
            d = json.loads(m)
        except Exception:
            return
        if d.get("type") != "deepsuck":
            return
        e = d["data"]
        if e.get("type") == "filler":
            stats.setdefault("fillers", []).append(time.time())
            if not quiet:
                print(f"[{time.time() - t_start:5.1f}s] filler   {e.get('text')}")
            return
        if e.get("type") == "latency":
            stats.setdefault("latency", []).append(e)
            if not quiet:
                print(f"[{time.time() - t_start:5.1f}s] latency  {e}")
            return
        if e.get("type") in ("scammer", "bot", "limit", "limits"):
            stats["events"].append(e)
            if (barge_in and e.get("type") == "bot" and e.get("intent") not in ("opening", "disclosure", "hangup")
                    and "barge_in" not in stats and mic.pos >= len(pcm)):
                stats["_barge_armed"] = time.time()
            if not quiet:
                print(f"[{time.time() - t_start:5.1f}s] {e.get('type'):8s} {e.get('text') or e}")
        elif e.get("type") == "state":
            stats["state"] = e

    @pc.on("connectionstatechange")
    async def on_state():
        if pc.connectionState == "connected" and stats["connected_after"] is None:
            stats["connected_after"] = round(time.time() - t_start, 2)

    async def sink(track):
        while True:
            try:
                fr = await track.recv()
            except Exception:
                return
            stats["bot_audio_sec"] += fr.samples / fr.sample_rate
            arr16 = fr.to_ndarray().reshape(-1).astype("float64")
            if arr16.size and float(np.sqrt(np.mean(arr16 * arr16))) > LOUD_RMS:
                loud.append(time.time())
                armed = stats.get("_barge_armed")
                if armed and time.time() - armed > 0.3 and "barge_in" not in stats:
                    clip = barge_clip(pcm)
                    mic.inject = clip
                    stats.pop("_barge_armed", None)
                    stats["barge_in"] = {"at": round(time.time() - t_start, 2), "clip_sec": round(len(clip) / 32000, 2)}
                    if not quiet:
                        print(f"[{time.time() - t_start:5.1f}s] barge-in 人设说话时插话 {stats['barge_in']['clip_sec']}s")
            if out_wav:
                stats["bot_rate"] = fr.sample_rate
                arr = fr.to_ndarray().reshape(-1)
                ch = len(fr.layout.channels)
                bot_pcm.extend(arr.reshape(-1, ch)[:, 0].astype("int16").tobytes() if ch > 1 else arr.astype("int16").tobytes())

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            asyncio.ensure_future(sink(track))

    await pc.setLocalDescription(await pc.createOffer())
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.05)
    if relay:
        stats["relay"]["local_candidates"] = candidate_types(pc.localDescription.sdp)
        if set(stats["relay"]["local_candidates"]) != {"relay"}:
            stats["error"] = "没有拿到中继候选（TURN 不通或凭据被拒）"
            stats["offer_status"] = None
            await pc.close()
            return stats
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False) if insecure else None) as s:
        async with s.post(url.rstrip("/") + "/api/offer", headers=headers, json={
                "sdp": pc.localDescription.sdp, "type": "offer", "persona": persona, "scenario": scenario,
                "consent": bool(consent)}) as r:
            body = await r.json(content_type=None)
            stats["offer_status"] = r.status
            if r.status == 200 and isinstance(body, dict) and body.get("trace_id"):
                stats["trace_id"] = body["trace_id"]
                fb_key = body.get("feedback_key") or ""  # 只在内存里用，不写进 stats / json-out
                if not quiet:
                    print(f"[{time.time() - t_start:5.1f}s] trace    通话编号 {body['trace_id']}")
            if r.status != 200:
                stats["error"] = body
                await pc.close()
                return stats
    await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
    deadline = time.time() + seconds
    while time.time() < deadline and pc.connectionState not in ("failed", "closed"):
        await asyncio.sleep(0.2)
    stats["final_state"] = pc.connectionState
    if stats.get("trace_id") and stats.get("connected_after") is not None:
        # 同网页一样上报接通路径，写进同一编号的追踪（验证 #3 的上报链路）
        try:
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            path = f"relay/{'tls' if relay == 'tls' else 'tcp'}" if relay else "direct"
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False) if insecure else None) as s:
                async with s.post(url.rstrip("/") + "/api/client-report", headers=headers, json={
                        "trace_id": stats["trace_id"], "stage": "connected",
                        "detail": {"path": path, "browser": "aiortc probe",
                                   "elapsedMs": int(stats["connected_after"] * 1000)}}) as r:
                    stats["client_report"] = r.status
        except Exception as e:
            stats["client_report"] = f"{type(e).__name__}"
    try:
        await pc.close()
    except Exception as e:  # 关闭时的清理异常不影响探测结果
        stats["close_error"] = f"{type(e).__name__}: {e}"
    if flag is not None and stats.get("trace_id"):
        # 模拟页面的“这通有问题”：带本通的 feedback_key 提交；再用错的口令试一次，应被拒（403）
        try:
            await asyncio.sleep(2)  # 等服务端写完结束行
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            fu = url.rstrip("/") + f"/api/feedback/{stats['trace_id']}"
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False) if insecure else None) as s:
                async with s.post(fu, headers=headers, json={"key": fb_key, "note": flag}) as r:
                    stats["feedback"] = r.status
                async with s.post(fu, headers=headers, json={"key": "wrong-key", "note": "x"}) as r:
                    stats["feedback_wrong_key"] = r.status
        except Exception as e:
            stats["feedback"] = f"{type(e).__name__}"
    if out_wav and bot_pcm:
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(stats.get("bot_rate", 48000)); w.writeframes(bytes(bot_pcm))
    stats["bot_audio_sec"] = round(stats["bot_audio_sec"], 1)
    stats.pop("_barge_armed", None)
    if barge_in and "barge_in" not in stats:
        stats["barge_in"] = {"at": None, "note": "WAV 放完后没等到人设的正式回复"}
    if mic.t0 is not None and pcm:
        segs = speech_segments(pcm)
        stats["client_e2e_ms"] = client_e2e(segs, mic.t0, loud)
        stats["client_filler"] = window_flags(segs, mic.t0, stats.get("fillers", []))
    return stats


EXIT_REASONS = {0: "ok", 2: "offer_rejected", 3: "media_not_connected", 4: "no_bot_audio", 5: "json_out_failed",
                6: "relay_unavailable"}


def exit_code(st: dict) -> int:
    """按探测结果给出退出码（见模块说明）。连通性以“收到过机器人音频或数据通道消息”为准，
    不只看 aiortc 的 connectionstatechange（该事件在部分网络/版本下可能漏报）。"""
    if st.get("relay") and st.get("offer_status") is None:
        return 6
    if st.get("offer_status") != 200:
        return 2
    heard = st.get("bot_audio_sec", 0) > 0
    got_data = bool(st.get("events")) or bool(st.get("latency")) or st.get("state") is not None
    if st.get("connected_after") is None and not heard and not got_data:
        return 3
    if not heard:
        return 4
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.probe", description=__doc__.splitlines()[0],
                                 epilog="退出码" + __doc__.split("退出码", 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:7860")
    ap.add_argument("--wav")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--persona", default="wang")
    ap.add_argument("--scenario", default="refund")
    ap.add_argument("--origin")
    ap.add_argument("--out-wav")
    ap.add_argument("--insecure", action="store_true", help="不校验 HTTPS 证书（本地 Caddy 自签名测试用）")
    ap.add_argument("--make-wav", help="先用 CosyVoice 合成固定骗子台词到这个路径（计费，约 150 字）")
    ap.add_argument("--json-out", help="把逐轮延迟与汇总写到 JSON 文件")
    ap.add_argument("--relay", choices=["tcp", "tls"],
                    help="只走 TURN 中继：tcp = turn:...?transport=tcp，tls = turns:（凭据从 /api/ice 现取）")
    ap.add_argument("--consent", action="store_true",
                    help="同意保存录音（通话追踪；同意才存录音和脱敏文字）；服务端返回的通话编号打印在 trace_id")
    ap.add_argument("--barge-in", action="store_true",
                    help="WAV 放完后，在人设说正式回复时把第一段话再推一遍，模拟打断（trace 应记 interrupted=true）")
    ap.add_argument("--flag", metavar="说明",
                    help="挂断后模拟页面“这通有问题”提交这句说明（并用错口令试一次，应 403）；结果在 feedback")
    a = ap.parse_args(argv)
    if a.make_wav:
        print(json.dumps({"segments": asyncio.run(make_scammer_wav(a.make_wav))}))
        if not a.wav:
            return 0
    st = asyncio.run(run(a.url, a.wav, a.seconds, a.persona, a.scenario, a.origin, a.out_wav, insecure=a.insecure,
                         consent=a.consent, relay=a.relay, flag=a.flag, barge_in=a.barge_in))
    summary = {k: v for k, v in st.items() if k not in ("events", "state", "fillers")}
    summary["turns"] = sum(1 for e in st.get("events", []) if e.get("type") == "scammer")
    summary["intel"] = [i.get("masked") for i in (st.get("state") or {}).get("intel", [])]
    from .latency import percentile, summarize
    lat = st.get("latency", [])
    summary["server"] = summarize(lat)
    ce = [x for x in st.get("client_e2e_ms", []) if x is not None]
    summary["client_e2e"] = {"n": len(ce), "p50": percentile(ce, 50), "p90": percentile(ce, 90)}
    summary["headline"] = headline(summary["server"], summary["client_e2e"], lat)
    code = exit_code(st)
    if a.json_out:
        try:
            with open(a.json_out, "w", encoding="utf-8") as f:
                json.dump({"summary": {**summary, "exit": code, "exit_reason": EXIT_REASONS[code]}, "turns": lat,
                           "client_e2e_ms": st.get("client_e2e_ms"), "client_filler": st.get("client_filler"),
                           "events": st.get("events")}, f, ensure_ascii=False, indent=1)
        except OSError as e:
            print(f"probe: 写 --json-out 失败: {e}", file=sys.stderr)
            code = code or 5
    summary["exit"], summary["exit_reason"] = code, EXIT_REASONS[code]
    print(json.dumps(summary, ensure_ascii=False))
    if code:
        print(f"probe: exit {code} ({EXIT_REASONS[code]})", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
