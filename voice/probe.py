"""语音服务端到端探针：用 aiortc 充当"浏览器"，把一段 WAV（16 kHz 单声道）当麦克风推给 /api/offer，
打印数据通道收到的转写 / 机器人回复 / 情报，统计收到的机器人音频时长。部署后可用来验证 UDP/ICE 是否通。

    python -m voice.probe --url http://127.0.0.1:7860 --wav scammer.wav --seconds 40
    python -m voice.probe --url https://live.deepsuck.si --origin https://live.deepsuck.si --wav scammer.wav

会真实调用 DashScope（按量计费，受服务端预算护栏约束）。非官方项目，与 DeepSeek 无关。
"""
from __future__ import annotations

import argparse
import asyncio
import fractions
import json
import time
import wave
from typing import Optional


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
    pc.addTransceiver(Mic(), direction="sendrecv")
    pc.addTransceiver("video", direction="recvonly")
    dc = pc.createDataChannel("chat", ordered=True)
    stats = {"bot_audio_sec": 0.0, "events": [], "connected_after": None}
    bot_pcm = bytearray()
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
    a = ap.parse_args(argv)
    st = asyncio.run(run(a.url, a.wav, a.seconds, a.persona, a.scenario, a.origin, a.out_wav, insecure=a.insecure))
    summary = {k: v for k, v in st.items() if k not in ("events", "state")}
    summary["turns"] = sum(1 for e in st.get("events", []) if e.get("type") == "scammer")
    summary["intel"] = [i.get("masked") for i in (st.get("state") or {}).get("intel", [])]
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if st.get("offer_status") == 200 and st.get("connected_after") is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
