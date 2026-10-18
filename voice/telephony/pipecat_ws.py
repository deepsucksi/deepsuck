"""Twilio 类媒体流适配器（name = "pipecat-ws"）：直接复用 Pipecat 自带的握手解析与 serializer。

支持 Pipecat 能自动识别的 Twilio / Telnyx / Plivo / Exotel 媒体流（8 kHz μ-law WebSocket）。
这些服务商在国内基本拿不到号码，主要用于海外部署、协议联调，或接入兼容 Twilio Media Streams
协议的第三方网关（jambonz、部分 SBC）。

主动挂断（auto_hang_up）需要服务商凭据，只从环境变量读取、绝不打印：
  TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN、TELNYX_API_KEY、PLIVO_AUTH_ID / PLIVO_AUTH_TOKEN。
没有凭据时关闭 auto_hang_up，通话结束只断开媒体流。
"""
from __future__ import annotations

import os

from .base import CallInfo, TelephonyAdapter, register_adapter

PROVIDERS = ("twilio", "telnyx", "plivo", "exotel")


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def build_serializer(call: CallInfo):
    """按 provider 构造 Pipecat 自带的 serializer。"""
    p = call.provider
    if p == "twilio":
        from pipecat.serializers.twilio import TwilioFrameSerializer as S
        sid, tok = _env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN")
        return S(stream_sid=call.stream_id, call_sid=call.call_id or None, account_sid=sid or None,
                 auth_token=tok or None, params=S.InputParams(auto_hang_up=bool(sid and tok and call.call_id)))
    if p == "telnyx":
        from pipecat.serializers.telnyx import TelnyxFrameSerializer as S
        key = _env("TELNYX_API_KEY")
        enc = str(call.extra.get("outbound_encoding") or "PCMU")
        return S(stream_id=call.stream_id, outbound_encoding=enc, inbound_encoding="PCMU",
                 call_control_id=call.call_id or None, api_key=key or None,
                 params=S.InputParams(auto_hang_up=bool(key and call.call_id)))
    if p == "plivo":
        from pipecat.serializers.plivo import PlivoFrameSerializer as S
        aid, tok = _env("PLIVO_AUTH_ID"), _env("PLIVO_AUTH_TOKEN")
        return S(stream_id=call.stream_id, call_id=call.call_id or None, auth_id=aid or None,
                 auth_token=tok or None, params=S.InputParams(auto_hang_up=bool(aid and tok and call.call_id)))
    if p == "exotel":
        from pipecat.serializers.exotel import ExotelFrameSerializer as S
        return S(stream_sid=call.stream_id, call_sid=call.call_id or None)
    raise ValueError(f"unsupported provider: {p}")


@register_adapter
class PipecatTelephonyAdapter(TelephonyAdapter):
    name = "pipecat-ws"
    description = "Twilio / Telnyx / Plivo / Exotel 媒体流（复用 Pipecat 内置 serializer）"

    async def accept(self, websocket) -> CallInfo:
        from pipecat.runner.utils import parse_telephony_websocket

        kind, data = await parse_telephony_websocket(websocket)
        if kind not in PROVIDERS:
            raise ValueError(f"unrecognized telephony handshake: {kind}")
        get = data.get if hasattr(data, "get") else dict(data).get
        extra = {}
        if get("outbound_encoding"):
            extra["outbound_encoding"] = get("outbound_encoding")
        return CallInfo(provider=kind, call_id=str(get("call_id") or ""), stream_id=str(get("stream_id") or ""),
                        from_number=str(get("from") or ""), to_number=str(get("to") or ""),
                        encoding="pcmu", sample_rate=8000, extra=extra)

    def create_serializer(self, call: CallInfo):
        return build_serializer(call)
