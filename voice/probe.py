"""语音服务端到端探针：用 aiortc 充当"浏览器"，把一段 WAV（16 kHz 单声道）当麦克风推给 /api/offer，
打印数据通道收到的转写 / 机器人回复 / 情报，统计收到的机器人音频时长。部署后可用来验证 UDP/ICE 是否通。

    python -m voice.probe --url http://127.0.0.1:7860 --wav scammer.wav --seconds 40
    python -m voice.probe --url https://live.deepsuck.si --origin https://live.deepsuck.si --wav scammer.wav

会真实调用 DashScope（按量计费，受服务端预算护栏约束）。
"""
from __future__ import annotations

import argparse
import asyncio
import fractions
import json
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


async def run(url: str, wav: Optional[str], seconds: float, persona: str, scenario: str, origin: Optional[str],
              out_wav: Optional[str] = None, quiet: bool = False, insecure: bool = False) -> dict:
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

        async def recv(self):
            if self.t0 is None:
                self.t0 = time.time()
            self.n += 1
            await asyncio.sleep(max(0, self.t0 + self.n * 0.02 - time.time()))
            chunk = pcm[self.pos:self.pos + 640]
            self.pos += 640
            chunk = chunk + b"\x00" * (640 - len(chunk))
            f = AudioFrame.from_ndarray(np.frombuffer(chunk, dtype=np.int16).reshape(1, -1), format="s16", layout="mono")
            f.sample_rate, f.pts, f.time_base = 16000, (self.n - 1) * 320, fractions.Fraction(1, 16000)
            return f

    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    mic = Mic()
    pc.addTransceiver(mic, direction="sendrecv")
    pc.addTransceiver("video", direction="recvonly")
    dc = pc.createDataChannel("chat", ordered=True)
    stats = {"bot_audio_sec": 0.0, "events": [], "connected_after": None}
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
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False) if insecure else None) as s:
        async with s.post(url.rstrip("/") + "/api/offer", headers=headers, json={
                "sdp": pc.localDescription.sdp, "type": "offer", "persona": persona, "scenario": scenario}) as r:
            body = await r.json(content_type=None)
            stats["offer_status"] = r.status
            if r.status != 200:
                stats["error"] = body
                await pc.close()
                return stats
    await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
    deadline = time.time() + seconds
    while time.time() < deadline and pc.connectionState not in ("failed", "closed"):
        await asyncio.sleep(0.2)
    stats["final_state"] = pc.connectionState
    await pc.close()
    if out_wav and bot_pcm:
        with wave.open(out_wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(stats.get("bot_rate", 48000)); w.writeframes(bytes(bot_pcm))
    stats["bot_audio_sec"] = round(stats["bot_audio_sec"], 1)
    if mic.t0 is not None and pcm:
        segs = speech_segments(pcm)
        stats["client_e2e_ms"] = client_e2e(segs, mic.t0, loud)
        stats["client_filler"] = window_flags(segs, mic.t0, stats.get("fillers", []))
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.probe", description=__doc__.splitlines()[0])
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
    a = ap.parse_args(argv)
    if a.make_wav:
        print(json.dumps({"segments": asyncio.run(make_scammer_wav(a.make_wav))}))
        if not a.wav:
            return 0
    st = asyncio.run(run(a.url, a.wav, a.seconds, a.persona, a.scenario, a.origin, a.out_wav, insecure=a.insecure))
    summary = {k: v for k, v in st.items() if k not in ("events", "state", "fillers")}
    summary["turns"] = sum(1 for e in st.get("events", []) if e.get("type") == "scammer")
    summary["intel"] = [i.get("masked") for i in (st.get("state") or {}).get("intel", [])]
    from .latency import percentile, summarize
    lat = st.get("latency", [])
    summary["server"] = summarize(lat)
    ce = [x for x in st.get("client_e2e_ms", []) if x is not None]
    summary["client_e2e"] = {"n": len(ce), "p50": percentile(ce, 50), "p90": percentile(ce, 90)}
    print(json.dumps(summary, ensure_ascii=False))
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "turns": lat, "client_e2e_ms": st.get("client_e2e_ms"),
                       "client_filler": st.get("client_filler"),
                       "events": st.get("events")}, f, ensure_ascii=False, indent=1)
    return 0 if st.get("offer_status") == 200 and st.get("connected_after") is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
