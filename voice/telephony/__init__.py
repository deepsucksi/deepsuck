"""DeepSuck 电话接入抽象层：把各种来电媒体流（运营商 SIP 网关、FreeSWITCH/Asterisk、Twilio 类媒体流）
统一映射成 Pipecat transport，复用 voice/ 里同一条级联管线。

    from voice.telephony import get_adapter, list_adapters
    adapter = get_adapter("ws-raw")          # 通用 SIP 网关 / FreeSWITCH WebSocket 媒体流
    call = await adapter.accept(websocket)   # 握手，拿到 CallInfo
    transport = adapter.create_transport(websocket, call)

默认不启用；只接听、不外呼。见 voice/telephony/README.md。
"""
from .base import CallInfo, TelephonyAdapter, get_adapter, list_adapters, register_adapter  # noqa: F401
from . import ws_raw, pipecat_ws, asterisk_ws  # noqa: F401,E402  注册内置适配器
