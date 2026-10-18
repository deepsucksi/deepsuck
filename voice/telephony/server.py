"""把电话适配器挂到 voice.app 的 FastAPI 上：WS /telephony/{adapter}，一条 WebSocket = 一通电话。

默认关闭。需要同时设置：
  VOICE_TELEPHONY=1                启用电话入口
  VOICE_TELEPHONY_TOKEN=<随机串>   桥接方必须带 ?token=... 或 Authorization: Bearer ...（常量时间比较）
可选：
  VOICE_TELEPHONY_ADAPTERS=ws-raw,pipecat-ws   允许的适配器（默认只开 ws-raw）
  VOICE_TELEPHONY_PERSONA=wang / VOICE_TELEPHONY_SCENARIO=refund
  VOICE_TELEPHONY_DISCLOSURE=...   开场前的告知语（默认“本通话由智能助理接听”）；设为 off 可关闭

与浏览器入口共用并发名额、每日预算和时长/轮数/静默护栏；每个主叫号码按“每 IP”规则限频。
只接听、不外呼：本模块没有任何发起呼叫的代码。
"""
from __future__ import annotations

import asyncio
import hmac
import os
import time
import uuid
from typing import Callable, List, Optional

from fastapi import WebSocket
from loguru import logger

from .base import CallInfo, TelephonyAdapter, get_adapter, list_adapters

DEFAULT_DISCLOSURE = "本通话由智能助理接听。"
IN_RATE, OUT_RATE = 16000, 24000


def enabled() -> bool:
    return os.environ.get("VOICE_TELEPHONY", "0") == "1"


def allowed_adapters() -> List[str]:
    raw = os.environ.get("VOICE_TELEPHONY_ADAPTERS", "ws-raw")
    return [a.strip() for a in raw.split(",") if a.strip() in list_adapters()]


def mask_number(num: str) -> str:
    """日志里的号码只留后 4 位。"""
    d = "".join(c for c in str(num or "") if c.isdigit())
    return f"***{d[-4:]}" if len(d) >= 4 else ("***" if d else "")


def token_ok(websocket) -> bool:
    want = os.environ.get("VOICE_TELEPHONY_TOKEN", "")
    if not want:
        return False
    got = websocket.query_params.get("token", "")
    auth = websocket.headers.get("authorization", "")
    if not got and auth.lower().startswith("bearer "):
        got = auth[7:].strip()
    return bool(got) and hmac.compare_digest(got.encode(), want.encode())


def disclosure_text() -> str:
    t = os.environ.get("VOICE_TELEPHONY_DISCLOSURE", DEFAULT_DISCLOSURE).strip()
    return "" if t.lower() == "off" else t


async def run_call(websocket, adapter: TelephonyAdapter, call: CallInfo, *, engine: str, persona: str, scenario: str,
                   limits, budget, ticket=None, build: Optional[Callable] = None) -> None:
    """一通电话：适配器 transport → 与浏览器版同一条管线 → 开场白；看门狗按护栏挂断。"""
    from pipecat.frames.frames import EndFrame, TTSSpeakFrame
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask

    from deepsuck.engine import Session

    from .. import guard as G

    session = Session(scenario=scenario, persona=persona, engine=f"phone-{engine}")
    transport = adapter.create_transport(websocket, call, session_timeout=limits.max_minutes * 60 + 30
                                         if limits.max_minutes > 0 else None)

    async def notify(msg: dict) -> None:  # 电话没有看板；情报留在 session 里，通话结束记日志
        return None

    if build is None:
        from .. import app as A
        from ..dashscope_ws import PERSONA_VOICES
        from ..processors import synth_fillers
        from deepsuck.blocklist import Client

        pid = session.persona["id"]
        fillers = await synth_fillers(pid, PERSONA_VOICES.get(pid, "longlaoyi_v3"), OUT_RATE, cached_only=True)
        pipeline, intel, context = A.build_pipeline(transport, session, notify, engine=engine, fillers=fillers,
                                                    blocklist=Client(), meter=ticket)
    else:
        pipeline, intel, context = build(transport, session, notify)
    st = {"connected": None, "heard": time.time()}
    if intel is not None:
        intel.on_heard = lambda: st.__setitem__("heard", time.time())
    task = PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE,
                                                        enable_usage_metrics=True))

    @transport.event_handler("on_client_connected")
    async def _connected(_t, _c):
        st["connected"] = st["heard"] = time.time()
        msg = session.opening()
        if context is not None:
            context.add_message({"role": "assistant", "content": msg["text"]})
        frames = [TTSSpeakFrame(t) for t in (disclosure_text(), msg["text"]) if t]
        await task.queue_frames(frames)

    @transport.event_handler("on_client_disconnected")
    async def _gone(_t, _c):
        await task.cancel()

    async def watchdog():
        while True:
            await asyncio.sleep(1)
            if st["connected"] is None:
                continue
            why = G.end_reason(started=st["connected"], last_heard=st["heard"],
                               turns=session.stats()["scammerMessages"], limits=limits, ticket=ticket,
                               budget=budget, now=time.time())
            if why:
                logger.info(f"telephony guard: ending call {call.call_id} ({why})")
                if intel is not None:
                    intel.closing = True
                await task.queue_frames([TTSSpeakFrame(G.END_TEXT[why]), EndFrame()])
                await asyncio.sleep(8)
                await task.cancel()
                return

    wd = asyncio.create_task(watchdog())
    try:
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        wd.cancel()
        session.end()
        logger.info(f"phone call ended: provider={call.provider} from={mask_number(call.from_number)} "
                    f"stats={session.stats()} usage={ticket.usage if ticket else None}")


def add_telephony_routes(app, *, engine: str, limits, budget, gate, build: Optional[Callable] = None) -> bool:
    """在 app 上注册 WS /telephony/{adapter_name}。未启用或未配置 token 时不注册，返回 False。"""
    if not enabled():
        return False
    if not os.environ.get("VOICE_TELEPHONY_TOKEN"):
        logger.warning("VOICE_TELEPHONY=1 但未设置 VOICE_TELEPHONY_TOKEN：电话入口不启用")
        return False
    names = allowed_adapters()
    logger.info(f"telephony: 启用适配器 {names}")

    @app.websocket("/telephony/{adapter_name}")
    async def telephony_ws(websocket: WebSocket, adapter_name: str):
        if adapter_name not in names or not token_ok(websocket):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        adapter = get_adapter(adapter_name)
        try:
            call = await asyncio.wait_for(adapter.accept(websocket), 10)
        except Exception as e:
            logger.warning(f"telephony handshake failed ({adapter_name}): {e}")
            await websocket.close(code=1003)
            return
        sid = uuid.uuid4().hex
        caller = f"tel:{call.from_number or call.call_id}"
        if budget.exhausted() or gate.admit(caller, sid):
            logger.info(f"telephony: rejected call from {mask_number(call.from_number)} (limits)")
            await websocket.close(code=1013)
            gate.release(sid)
            return
        ticket = budget.reserve(budget.session_cost_cap(limits), sid)
        if ticket is None:
            gate.release(sid)
            await websocket.close(code=1013)
            return
        try:
            await run_call(websocket, adapter, call, engine=engine,
                           persona=os.environ.get("VOICE_TELEPHONY_PERSONA", "wang"),
                           scenario=os.environ.get("VOICE_TELEPHONY_SCENARIO", "refund"),
                           limits=limits, budget=budget, ticket=ticket, build=build)
        except Exception as e:
            logger.exception(f"telephony call failed: {e}")
        finally:
            ticket.close()
            gate.release(sid)

    return True
