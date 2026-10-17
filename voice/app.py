"""DeepSuck 语音演示（非官方项目，与 DeepSeek 无关）。

    python -m voice.app            # http://localhost:7860 ，浏览器麦克风扮演"骗子"
    python -m voice.app --engine rule   # 不调用大模型，规则引擎出话（仍需 ASR/TTS）

级联管线：浏览器麦克风 →(SmallWebRTC)→ Paraformer 实时 ASR → 情报抽取/话术识别/策略选择
→ qwen-plus（OpenAI 兼容接口）→ 输出守卫 → CosyVoice TTS →(SmallWebRTC)→ 浏览器扬声器。
需要 DASHSCOPE_API_KEY（见 voice/.env.example）。仅供研究/演示，请勿用来拨打真实电话。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
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

from .dashscope_ws import PERSONA_VOICES  # noqa: E402
from .persona import system_prompt  # noqa: E402

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


def public_config(engine: str) -> dict:
    return {
        "keyConfigured": has_key(),
        "engine": engine,
        "models": {"llm": LLM_MODEL, "asr": ASR_MODEL, "tts": TTS_MODEL},
        "personas": [{"id": p["id"], "name": p["name"], "tagline": p["tagline"],
                      "voice": PERSONA_VOICES.get(p["id"])} for p in PERSONAS],
        "scenarios": [{"id": s["id"], "title": s["title"]} for s in SCENARIOS],
    }


def build_pipeline(transport, session: Session, notify, *, engine: str = "llm", fillers=None,
                   blocklist=None, stt=None, tts=None, llm=None):
    """组装管线；stt/tts/llm 可注入（测试用）。返回 (pipeline, intel_processor, context)。"""
    from pipecat.pipeline.pipeline import Pipeline

    from .processors import BotTextTap, GuardTextFilter, IntelProcessor
    from .services import CosyVoiceTTSService, ParaformerSTTService

    pid = session.persona["id"]
    stt = stt or ParaformerSTTService(model=ASR_MODEL, sample_rate=IN_RATE)
    tts = tts or CosyVoiceTTSService(voice=PERSONA_VOICES.get(pid, "longlaoyi_v3"), model=TTS_MODEL,
                                     text_filters=[GuardTextFilter()])
    if engine == "rule":
        intel = IntelProcessor(session, notify=notify, mode="rule", fillers=fillers, filler_rate=OUT_RATE,
                               blocklist=blocklist)
        return Pipeline([transport.input(), stt, intel, tts, transport.output()]), intel, None

    from pipecat.audio.vad.silero import SileroVADAnalyzer
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
    agg = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))
    intel = IntelProcessor(session, context=context, notify=notify, mode="llm", fillers=fillers,
                           filler_rate=OUT_RATE, blocklist=blocklist)
    tap = BotTextTap(intel)
    pipeline = Pipeline([transport.input(), stt, intel, agg.user(), llm, tap, tts, transport.output(),
                         agg.assistant()])
    return pipeline, intel, context


async def run_bot(connection, persona: str, scenario: str, engine: str) -> None:
    """一次通话：SmallWebRTC 连接 → 管线 → 开场白。"""
    from pipecat.frames.frames import TTSSpeakFrame
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from deepsuck.blocklist import Client

    from .processors import synth_fillers

    session = Session(scenario=scenario, persona=persona, engine=f"voice-{engine}")
    transport = SmallWebRTCTransport(webrtc_connection=connection, params=TransportParams(
        audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE))

    async def notify(msg: dict) -> None:
        try:
            connection.send_app_message({"type": "deepsuck", "data": msg})
        except Exception as e:
            logger.debug(f"notify failed: {e}")

    fillers = await synth_fillers(session.persona["id"], PERSONA_VOICES.get(session.persona["id"], "longlaoyi_v3"),
                                  OUT_RATE)
    pipeline, intel, context = build_pipeline(transport, session, notify, engine=engine, fillers=fillers,
                                              blocklist=Client())
    task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE))

    @transport.event_handler("on_client_connected")
    async def _connected(_t, _c):
        msg = session.opening()
        if context is not None:
            context.add_message({"role": "assistant", "content": msg["text"]})
        await notify({"type": "bot", "text": msg["text"], "intent": "opening"})
        await notify(intel.snapshot())
        await task.queue_frames([TTSSpeakFrame(msg["text"])])

    @transport.event_handler("on_client_disconnected")
    async def _gone(_t, _c):
        session.end()
        logger.info(f"call ended: {session.stats()}")
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)


def create_app(engine: str = "llm"):
    from pipecat.transports.smallwebrtc.request_handler import (
        SmallWebRTCPatchRequest,
        SmallWebRTCRequest,
        SmallWebRTCRequestHandler,
    )

    app = FastAPI(title="DeepSuck voice (非官方项目，与 DeepSeek 无关)")
    handler = SmallWebRTCRequestHandler()

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/logo.svg")
    async def logo():
        return FileResponse(ROOT / "site" / "assets" / "logo.svg", media_type="image/svg+xml")

    @app.get("/api/config")
    async def config():
        return JSONResponse(public_config(engine))

    @app.post("/api/offer")
    async def offer(request: Request, background: BackgroundTasks):
        if not has_key():
            raise HTTPException(503, "未配置 DASHSCOPE_API_KEY：请复制 voice/.env.example 为 voice/.env 并填入")
        body: Dict[str, Any] = await request.json()
        persona, scenario = body.get("persona") or "wang", body.get("scenario") or "refund"
        req = SmallWebRTCRequest(sdp=body["sdp"], type=body["type"], pc_id=body.get("pc_id"))

        async def on_conn(conn):
            background.add_task(run_bot, conn, persona, scenario, engine)

        return await handler.handle_web_request(req, on_conn)

    @app.patch("/api/offer")
    async def ice(request: Request):
        from pipecat.transports.smallwebrtc.request_handler import IceCandidate

        body = await request.json()
        cands = [IceCandidate(candidate=c["candidate"], sdp_mid=c["sdp_mid"], sdp_mline_index=c["sdp_mline_index"])
                 for c in body.get("candidates", [])]
        await handler.handle_patch_request(SmallWebRTCPatchRequest(pc_id=body["pc_id"], candidates=cands))
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.app", description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--engine", choices=["llm", "rule"], default="llm")
    args = ap.parse_args(argv)
    load_env()
    if not has_key():
        logger.warning("未检测到 DASHSCOPE_API_KEY：页面可以打开，但无法开始通话。见 voice/README.md")
    import uvicorn

    uvicorn.run(create_app(args.engine), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
