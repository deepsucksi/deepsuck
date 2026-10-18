"""DeepSuck 语音演示。

    python -m voice.app            # http://localhost:7860 ，浏览器麦克风扮演"骗子"
    python -m voice.app --engine rule   # 不调用大模型，规则引擎出话（仍需 ASR/TTS）

级联管线：浏览器麦克风 →(SmallWebRTC)→ Paraformer 实时 ASR → 情报抽取/话术识别/策略选择
→ qwen-plus（OpenAI 兼容接口）→ 输出守卫 → CosyVoice TTS →(SmallWebRTC)→ 浏览器扬声器。
需要 DASHSCOPE_API_KEY（见 voice/.env.example）。仅供研究/演示，请勿用来拨打真实电话。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
for p in (ROOT / "python",):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from deepsuck.engine import Session  # noqa: E402
from deepsuck.personas import PERSONAS, SCENARIOS  # noqa: E402

from . import guard as G  # noqa: E402
from . import records as REC  # noqa: E402
from .disclosure import disclosure_text  # noqa: E402
from .dashscope_ws import PERSONA_VOICES  # noqa: E402
from .persona import system_prompt  # noqa: E402
from . import backchannel as BC  # noqa: E402

LLM_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.environ.get("DEEPSUCK_LLM_MODEL", "qwen-plus")
TTS_MODEL = os.environ.get("DEEPSUCK_TTS_MODEL", "cosyvoice-v3-flash")
ASR_MODEL = os.environ.get("DEEPSUCK_ASR_MODEL", "paraformer-realtime-v2")
OUT_RATE = 24000
IN_RATE = 16000


def load_env() -> None:
    """读取 voice/.env 与仓库根目录 .env（若存在）；已有环境变量优先。"""
    for f in (Path(__file__).resolve().parent / ".env", ROOT / ".env"):
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def has_key() -> bool:
    return bool(os.environ.get("DASHSCOPE_API_KEY"))


def browser_ice_servers() -> list:
    """给浏览器的 ICE 服务器。VOICE_BROWSER_STUN 逗号分隔；配置 TURN_SECRET + TURN_URLS 时下发临时 TURN 凭据
    （coturn use-auth-secret / REST API 约定：username = 过期时间戳:随机串，credential = base64(HMAC-SHA1(secret, username))）。"""
    out = []
    stun = [u.strip() for u in os.environ.get("VOICE_BROWSER_STUN", "").split(",") if u.strip()]
    if stun:
        out.append({"urls": stun})
    secret, urls = os.environ.get("TURN_SECRET", ""), [u.strip() for u in os.environ.get("TURN_URLS", "").split(",") if u.strip()]
    if secret and urls:
        user = f"{int(time.time()) + 3600}:{uuid.uuid4().hex[:8]}"
        cred = base64.b64encode(hmac.new(secret.encode(), user.encode(), hashlib.sha1).digest()).decode()
        out.append({"urls": urls, "username": user, "credential": cred})
    return out


def server_ice_servers() -> list:
    """服务端（aiortc）用的 STUN：用来发现公网 IP（srflx 候选）。VOICE_SERVER_STUN 为空则不用。"""
    return [u.strip() for u in os.environ.get("VOICE_SERVER_STUN", "").split(",") if u.strip()][:1]


def public_config(engine: str, limits: Optional[G.Limits] = None, budget: Optional[G.VoiceBudget] = None) -> dict:
    lim = limits or G.Limits()
    return {
        "keyConfigured": has_key(),
        "iceServers": browser_ice_servers(),
        "limits": {"maxSessions": lim.max_sessions, "maxMinutes": lim.max_minutes, "maxTurns": lim.max_turns,
                   "idleSeconds": lim.idle_seconds, "perIpPerHour": lim.per_ip_per_hour, "perIpPerDay": lim.per_ip_per_day},
        "budget": budget.status() if budget is not None else None,
        "engine": engine,
        "models": {"llm": LLM_MODEL, "asr": ASR_MODEL, "tts": TTS_MODEL},
        "personas": [{"id": p["id"], "name": p["name"], "tagline": p["tagline"],
                      "voice": PERSONA_VOICES.get(p["id"])} for p in PERSONAS],
        "scenarios": [{"id": s["id"], "title": s["title"]} for s in SCENARIOS],
    }


def build_pipeline(transport, session: Session, notify, *, engine: str = "llm", fillers=None,
                   blocklist=None, stt=None, tts=None, llm=None, meter=None, profile: str = "web",
                   vad_analyzer=None, recorder=None):
    """组装管线；stt/tts/llm/vad_analyzer 可注入（测试用）。返回 (pipeline, intel_processor, context)。

    profile 选延迟/打断参数（voice/tuning.py）："web" 浏览器，"phone" 电话线路。
    recorder 为 voice.records.AudioRecorder 时（KEEP_AUDIO=1）在输入后、输出前各插一个录音点。
    """
    from pipecat.pipeline.pipeline import Pipeline

    from .interrupt import user_turn_strategies
    from .processors import BotTextTap, FillerProcessor, GuardTextFilter, IntelProcessor
    from .services import CosyVoiceStreamTTSService, CosyVoiceTTSService, ParaformerSTTService
    from .tuning import get_profile, vad_params

    prof = get_profile(profile)
    pid = session.persona["id"]
    stt = stt or ParaformerSTTService(model=ASR_MODEL, sample_rate=IN_RATE, meter=meter,
                                      max_sentence_silence=prof.asr_max_silence_ms)
    if tts is None:
        voice = PERSONA_VOICES.get(pid, "longlaoyi_v3")
        if os.environ.get("DEEPSUCK_TTS_STREAM", "1") == "0":  # 回退：每句一连接的旧实现
            tts = CosyVoiceTTSService(voice=voice, model=TTS_MODEL, text_filters=[GuardTextFilter()], meter=meter)
        else:
            tts = CosyVoiceStreamTTSService(voice=voice, model=TTS_MODEL, text_filters=[GuardTextFilter()],
                                            meter=meter, clause_min_chars=prof.tts_clause_min_chars)
    fillers = {} if fillers is None else fillers
    backchannel = None
    if BC.enabled():  # 短口头语：从已合成好的那几条里挑（同一个字典，后台补齐的也算）
        backchannel = BC.Backchannel(lambda: [k for k, v in list(fillers.items()) if v])
    filler = FillerProcessor(fillers, sample_rate=OUT_RATE, delay_ms=prof.filler_delay_ms, notify=notify,
                             backchannel=backchannel, backchannel_delay_ms=prof.backchannel_delay_ms)
    if vad_analyzer is None:
        from pipecat.audio.vad.silero import SileroVADAnalyzer

        vad_analyzer = SileroVADAnalyzer(params=vad_params(prof))
    strategies = user_turn_strategies(prof.interrupt_min_chars)

    if engine == "rule":
        # 规则模式也要能打断：VAD 在 STT 前，回合处理器在 STT 后，开口超过门槛就广播打断
        from pipecat.processors.audio.vad_processor import VADProcessor
        from pipecat.turns.user_turn_processor import UserTurnProcessor

        intel = IntelProcessor(session, notify=notify, mode="rule", fillers=fillers, filler_rate=OUT_RATE,
                               filler_prob=0.0, blocklist=blocklist, backchannel=backchannel)
        intel.meter = meter
        turns = UserTurnProcessor(user_turn_strategies=strategies)
        procs = [transport.input(), VADProcessor(vad_analyzer=vad_analyzer), stt, turns, intel, filler, tts,
                 transport.output()]
        return Pipeline(_with_taps(procs, recorder)), intel, None

    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )

    if llm is None:
        from pipecat.services.qwen.llm import QwenLLMService

        llm = QwenLLMService(api_key=os.environ.get("DASHSCOPE_API_KEY"), base_url=LLM_BASE_URL,
                             settings=QwenLLMService.Settings(model=LLM_MODEL, temperature=0.8, max_tokens=120))
    context = LLMContext([{"role": "system", "content": system_prompt(pid, session.scenario["id"], "opening")}])
    agg = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(
        vad_analyzer=vad_analyzer, user_turn_strategies=strategies))
    # 填充音改由 FillerProcessor 按延迟触发，IntelProcessor 不再随机插播
    intel = IntelProcessor(session, context=context, notify=notify, mode="llm", fillers=fillers,
                           filler_rate=OUT_RATE, filler_prob=0.0, blocklist=blocklist, backchannel=backchannel)
    intel.meter = meter
    tap = BotTextTap(intel)
    procs = [transport.input(), stt, intel, agg.user(), llm, filler, tap, tts, transport.output(), agg.assistant()]
    return Pipeline(_with_taps(procs, recorder)), intel, context


def _with_taps(procs: list, recorder) -> list:
    """procs[0] 是 transport.input()，倒数第一或第二个是 transport.output()（llm 模式后面还有 assistant 聚合器）。"""
    if recorder is None:
        return procs
    from .records import AudioTap

    out_idx = len(procs) - 1 if len(procs) and procs[-1].__class__.__name__ != "LLMAssistantAggregator" \
        else len(procs) - 2
    return ([procs[0], AudioTap(recorder, "in")] + procs[1:out_idx] + [AudioTap(recorder, "out")]
            + procs[out_idx:])


async def run_bot(connection, persona: str, scenario: str, engine: str, *, limits: Optional[G.Limits] = None,
                  budget: Optional[G.VoiceBudget] = None, ticket: Optional[G.Ticket] = None,
                  on_done=None, connect_timeout: Optional[float] = None) -> None:
    """一次通话：SmallWebRTC 连接 → 管线 → 开场白；看门狗按时长/轮数/静默/预算挂断。"""
    from pipecat.frames.frames import EndFrame, TTSSpeakFrame
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from deepsuck.blocklist import Client

    from .processors import fillers_missing, synth_fillers

    limits = limits or G.Limits()
    budget = budget or G.VoiceBudget()
    if connect_timeout is None:
        connect_timeout = G._env_f("VOICE_CONNECT_TIMEOUT", 30)
    st = {"t0": time.time(), "connected": None, "heard": time.time()}
    wd: Optional[asyncio.Task] = None
    bg_fill: Optional[asyncio.Task] = None
    session = recorder = None
    call_id = ""
    try:
        session = Session(scenario=scenario, persona=persona, engine=f"voice-{engine}")
        call_id = uuid.uuid4().hex[:12]
        recorder = REC.recorder_for(call_id)  # KEEP_AUDIO=1 才录音
        transport = SmallWebRTCTransport(webrtc_connection=connection, params=TransportParams(
            audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE))

        async def notify(msg: dict) -> None:
            try:
                connection.send_app_message({"type": "deepsuck", "data": msg})
            except Exception as e:
                logger.debug(f"notify failed: {e}")

        pid = session.persona["id"]
        pvoice = PERSONA_VOICES.get(pid, "longlaoyi_v3")
        # 开场不等 TTS：先用缓存的填充音，缺的在后台补齐（同一个字典，合成好就能用）
        fillers = await synth_fillers(pid, pvoice, OUT_RATE, cached_only=True)
        if fillers_missing(pid, pvoice, OUT_RATE, fillers):
            bg_fill = asyncio.create_task(synth_fillers(pid, pvoice, OUT_RATE, meter=ticket, out=fillers))
        pipeline, intel, context = build_pipeline(transport, session, notify, engine=engine, fillers=fillers,
                                                  blocklist=Client(), meter=ticket, recorder=recorder)
        intel.on_heard = lambda: st.__setitem__("heard", time.time())
        from .latency import LatencyObserver
        from .tuning import get_profile

        lat = LatencyObserver(vad_stop_secs=get_profile("web").vad_stop_secs, notify=notify)
        task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE,
                                                            enable_metrics=True, enable_usage_metrics=True),
                            observers=[lat])

        @transport.event_handler("on_client_connected")
        async def _connected(_t, _c):
            st["connected"] = st["heard"] = time.time()
            msg = session.opening()
            if context is not None:
                context.add_message({"role": "assistant", "content": msg["text"]})
            await notify({"type": "limits", "maxMinutes": limits.max_minutes, "maxTurns": limits.max_turns})
            disc = disclosure_text()
            if disc:
                await notify({"type": "bot", "text": disc, "intent": "disclosure"})
            await notify({"type": "bot", "text": msg["text"], "intent": "opening"})
            await notify(intel.snapshot())
            await task.queue_frames([TTSSpeakFrame(t) for t in (disc, msg["text"]) if t])

        @transport.event_handler("on_client_disconnected")
        async def _gone(_t, _c):
            session.end()
            await lat.flush()
            from .latency import summarize
            logger.info(f"call ended: {session.stats()} usage={ticket.usage if ticket else None} "
                        f"latency={summarize(lat.turns)}")
            await task.cancel()

        async def watchdog():
            while True:
                await asyncio.sleep(1)
                now = time.time()
                if st["connected"] is None:
                    if now - st["t0"] > connect_timeout:  # ICE 没连上（多半是 UDP 端口没放行）
                        logger.warning("WebRTC 连接超时，释放名额（检查防火墙 UDP 端口 / VOICE_PUBLIC_IP）")
                        await task.cancel()
                        return
                    continue
                why = G.end_reason(started=st["connected"], last_heard=st["heard"],
                                   turns=session.stats()["scammerMessages"], limits=limits, ticket=ticket,
                                   budget=budget, now=now)
                if why:
                    logger.info(f"guard: ending call ({why})")
                    intel.closing = True  # 不再处理新转写，避免继续花钱
                    await notify({"type": "limit", "reason": why, "text": G.END_NOTE[why]})
                    await notify({"type": "bot", "text": G.END_TEXT[why], "intent": "hangup"})
                    await task.queue_frames([TTSSpeakFrame(G.END_TEXT[why]), EndFrame()])
                    await asyncio.sleep(8)  # 给告别语播放时间；EndFrame 正常走完时本任务会被取消
                    await task.cancel()
                    return

        wd = asyncio.create_task(watchdog())
        await PipelineRunner(handle_sigint=False).run(task)
    except Exception as e:
        logger.exception(f"run_bot failed: {e}")
    finally:
        for t in (wd, bg_fill):
            if t is not None:
                t.cancel()
        if recorder is not None:
            recorder.close()
        if session is not None:
            session.end()
            REC.save_transcript(session, call_id, "web")
        if ticket is not None:
            ticket.close()
        if on_done is not None:
            on_done()
        try:
            await connection.disconnect()
        except Exception:
            pass


def client_ip(request) -> str:
    if os.environ.get("TRUST_PROXY") == "1":
        xff = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
        if xff:
            return xff[-1]
    return request.client.host if request.client else "unknown"


def allowed_origins() -> list:
    return [o.strip().rstrip("/") for o in os.environ.get("VOICE_ALLOWED_ORIGINS", "").split(",") if o.strip()]


def create_app(engine: str = "llm", limits: Optional[G.Limits] = None, budget: Optional[G.VoiceBudget] = None):
    from pipecat.transports.smallwebrtc.connection import IceServer
    from pipecat.transports.smallwebrtc.request_handler import (
        SmallWebRTCPatchRequest,
        SmallWebRTCRequest,
        SmallWebRTCRequestHandler,
    )

    from .netpatch import add_public_ip_candidates, restrict_udp_ports

    limits = limits or G.Limits.from_env()
    budget = budget or G.VoiceBudget(G._env_f("VOICE_DAILY_BUDGET_CNY", limits.daily_budget_cny),
                                     G.Prices.from_env(), os.environ.get("DATA_DIR") or None)
    gate = G.Gate(limits)
    ports = restrict_udp_ports(os.environ.get("VOICE_UDP_PORTS", ""))
    public_ip = os.environ.get("VOICE_PUBLIC_IP", "").strip()
    origins = allowed_origins()
    if ports or public_ip:
        logger.info(f"WebRTC: UDP 端口 {ports or '随机'}，公网 IP 候选 {public_ip or '无'}，服务端 STUN {server_ice_servers() or '无'}")

    app = FastAPI(title="DeepSuck voice")

    @app.on_event("startup")
    async def _retention():
        # 通话留存：启动时清一次过期文件，之后每小时一次
        logger.info(f"通话留存策略: {REC.describe()}")
        app.state.cleanup_task = asyncio.create_task(REC.cleanup_loop())

    @app.on_event("shutdown")
    async def _retention_stop():
        t = getattr(app.state, "cleanup_task", None)
        if t is not None:
            t.cancel()

    @app.on_event("startup")
    async def _prewarm():
        # 部署时预先合成全部人设的填充音（一次性，几百字符；结果缓存在卷里，重启不再花钱）
        if has_key() and os.environ.get("VOICE_PREWARM", "0") == "1":
            from .processors import synth_fillers

            async def go():
                for p in PERSONAS:
                    await synth_fillers(p["id"], PERSONA_VOICES.get(p["id"], "longlaoyi_v3"), OUT_RATE)
                logger.info("filler cache warmed")
            asyncio.create_task(go())

    app.state.gate, app.state.budget, app.state.limits = gate, budget, limits
    handler = SmallWebRTCRequestHandler(ice_servers=[IceServer(urls=u) for u in server_ice_servers()])
    known_pcs: Dict[str, str] = {}  # pc_id -> sid（重协商不重复计数）

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/logo.svg")
    async def logo():
        return FileResponse(ROOT / "site" / "assets" / "logo.svg", media_type="image/svg+xml")

    @app.get("/api/config")
    async def config():
        return JSONResponse(public_config(engine, limits, budget), headers={"Cache-Control": "no-store"})

    @app.get("/api/voice/health")
    async def health():
        return {"ok": True, "keyConfigured": has_key(), "active": len(gate.active), "maxSessions": limits.max_sessions,
                "budget": budget.status()}

    @app.post("/api/offer")
    async def offer(request: Request, background: BackgroundTasks):
        if not has_key():
            raise HTTPException(503, "未配置 DASHSCOPE_API_KEY：请复制 voice/.env.example 为 voice/.env 并填入")
        if origins and request.headers.get("origin", "").rstrip("/") not in origins:
            raise HTTPException(403, "origin not allowed")
        body: Dict[str, Any] = await request.json()
        persona, scenario = str(body.get("persona") or "wang"), str(body.get("scenario") or "refund")
        if not isinstance(body.get("sdp"), str) or len(body["sdp"]) > 20000 or body.get("type") != "offer":
            raise HTTPException(400, "bad offer")
        pc_id = body.get("pc_id")
        renegotiate = bool(pc_id and pc_id in known_pcs)
        ticket = sid = None
        if not renegotiate:
            if budget.exhausted():
                raise HTTPException(429, G.END_NOTE["budget"] + "，明天再来（网页文字版沙盒不受影响）")
            sid = uuid.uuid4().hex
            denied = gate.admit(client_ip(request), sid)
            if denied:
                raise HTTPException(denied[0], denied[1])
            ticket = budget.reserve(budget.session_cost_cap(limits), sid)
            if ticket is None:
                gate.release(sid)
                raise HTTPException(429, G.END_NOTE["budget"] + "，明天再来（网页文字版沙盒不受影响）")
        req = SmallWebRTCRequest(sdp=body["sdp"], type=body["type"], pc_id=pc_id)
        started = {"v": False}

        async def on_conn(conn):
            started["v"] = True

            def done(_sid=sid, _pc=conn.pc_id):
                gate.release(_sid)
                known_pcs.pop(_pc, None)

            background.add_task(run_bot, conn, persona, scenario, engine, limits=limits, budget=budget,
                                ticket=ticket, on_done=done)

        try:
            ans = await handler.handle_web_request(req, on_conn)
        except Exception:
            if ticket is not None:
                ticket.close()
                gate.release(sid)
            raise
        if not renegotiate and not started["v"] and ticket is not None:  # 没有建立新连接
            ticket.close()
            gate.release(sid)
        if isinstance(ans, dict):
            if ans.get("pc_id") and sid:
                known_pcs[ans["pc_id"]] = sid
            if public_ip and ans.get("sdp"):
                ans["sdp"] = add_public_ip_candidates(ans["sdp"], public_ip)
        return ans

    @app.patch("/api/offer")
    async def ice(request: Request):
        from pipecat.transports.smallwebrtc.request_handler import IceCandidate

        body = await request.json()
        cands = [IceCandidate(candidate=c["candidate"], sdp_mid=c["sdp_mid"], sdp_mline_index=c["sdp_mline_index"])
                 for c in body.get("candidates", [])]
        await handler.handle_patch_request(SmallWebRTCPatchRequest(pc_id=body["pc_id"], candidates=cands))
        return {"status": "ok"}

    # 电话入口（默认关闭；需 VOICE_TELEPHONY=1 + VOICE_TELEPHONY_TOKEN，见 voice/telephony/README.md）
    from .telephony.server import add_telephony_routes

    app.state.telephony = add_telephony_routes(app, engine=engine, limits=limits, budget=budget, gate=gate)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main(argv: Optional[list] = None) -> int:
    load_env()
    ap = argparse.ArgumentParser(prog="python -m voice.app", description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=os.environ.get("VOICE_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("VOICE_PORT", "7860")))
    ap.add_argument("--engine", choices=["llm", "rule"], default=os.environ.get("VOICE_ENGINE", "llm"))
    args = ap.parse_args(argv)
    if not has_key():
        logger.warning("未检测到 DASHSCOPE_API_KEY：页面可以打开，但无法开始通话。见 voice/README.md")
    import uvicorn

    uvicorn.run(create_app(args.engine), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
