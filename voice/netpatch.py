"""服务器部署用的 WebRTC 网络补丁（只在设置了对应环境变量时生效）。

1. restrict_udp_ports("40000-40199")：aioice 默认在随机 UDP 端口上收集候选，防火墙没法只开一段端口。
   这里把 aioice 绑定端口限制在给定区间内（逐个尝试空闲端口）。每路通话约占 1–3 个端口（每个网卡地址一个）。
2. add_public_ip_candidates(sdp, ip)：云服务器（阿里云轻量等）网卡上只有内网 IP，公网 IP 是 1:1 NAT 映射；
   给应答 SDP 里每个 IPv4 host 候选补一条"公网 IP + 同端口"的候选，浏览器就能直接打到服务器，
   不依赖 STUN（与 mediasoup announcedIp / Janus nat_1_1_mapping 同理）。
"""
from __future__ import annotations

import ipaddress
import random
import types
from typing import Optional, Tuple


def parse_range(spec: str) -> Optional[Tuple[int, int]]:
    spec = (spec or "").strip()
    if not spec:
        return None
    lo, _, hi = spec.partition("-")
    lo_i, hi_i = int(lo), int(hi or lo)
    if not (1024 <= lo_i <= hi_i <= 65535):
        raise ValueError(f"无效的 UDP 端口区间: {spec}")
    return lo_i, hi_i


class _LoopProxy:
    def __init__(self, loop, lo: int, hi: int):
        self._loop, self._lo, self._hi = loop, lo, hi

    def __getattr__(self, name):
        return getattr(self._loop, name)

    async def create_datagram_endpoint(self, factory, local_addr=None, **kw):
        if not local_addr or local_addr[1] != 0:
            return await self._loop.create_datagram_endpoint(factory, local_addr=local_addr, **kw)
        n = self._hi - self._lo + 1
        start = random.randrange(n)
        last: Optional[OSError] = None
        for i in range(n):
            port = self._lo + (start + i) % n
            try:
                return await self._loop.create_datagram_endpoint(factory, local_addr=(local_addr[0], port), **kw)
            except OSError as e:
                last = e
        raise last or OSError(f"UDP 端口 {self._lo}-{self._hi} 已用尽")


def restrict_udp_ports(spec: str) -> Optional[Tuple[int, int]]:
    """把 aioice 的 UDP 候选端口限制在区间内；spec 为空则不做任何事。返回生效的区间。"""
    rng = parse_range(spec)
    if not rng:
        return None
    import asyncio as real_asyncio

    import aioice.ice as ice

    lo, hi = rng
    shim = types.ModuleType("asyncio_portrange_shim")
    shim.__dict__.update({k: getattr(real_asyncio, k) for k in dir(real_asyncio) if not k.startswith("__")})
    shim.get_event_loop = lambda: _LoopProxy(real_asyncio.get_event_loop(), lo, hi)
    shim.get_running_loop = lambda: _LoopProxy(real_asyncio.get_running_loop(), lo, hi)
    ice.asyncio = shim
    return rng


def add_public_ip_candidates(sdp: str, public_ip: str) -> str:
    """在每条私网 IPv4 host 候选后追加一条公网 IP 候选（同端口）。"""
    if not public_ip:
        return sdp
    ipaddress.IPv4Address(public_ip)  # 校验
    out, seen = [], set()
    for line in sdp.split("\r\n"):
        out.append(line)
        if not line.startswith("a=candidate:"):
            continue
        parts = line[len("a=candidate:"):].split()
        # foundation component transport priority ip port typ host ...
        if len(parts) < 8 or parts[6] != "typ" or parts[7] != "host" or parts[2].lower() != "udp":
            continue
        try:
            addr = ipaddress.ip_address(parts[4])
        except ValueError:
            continue
        if addr.version != 4 or not addr.is_private or addr.is_loopback:
            continue
        key = (parts[1], parts[5])
        if key in seen:
            continue
        seen.add(key)
        np = list(parts)
        np[0] = "9" + parts[0][:30]          # 新 foundation
        np[3] = str(max(1, int(parts[3]) - 1))  # 优先级略低于原候选
        np[4] = public_ip
        out.append("a=candidate:" + " ".join(np))
    return "\r\n".join(out)
