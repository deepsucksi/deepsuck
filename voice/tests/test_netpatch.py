import asyncio
import socket

import pytest

from voice import netpatch as N

SDP = "\r\n".join([
    "v=0", "m=audio 9 UDP/TLS/RTP/SAVPF 111",
    "a=candidate:abc 1 udp 2130706431 172.18.1.5 40012 typ host",
    "a=candidate:def 1 udp 2130706431 127.0.0.1 40013 typ host",
    "a=candidate:ghi 1 udp 1694498815 47.1.2.3 40012 typ srflx raddr 172.18.1.5 rport 40012",
    "a=candidate:jkl 1 udp 2130706431 fe80::1 40014 typ host",
    "a=end-of-candidates", ""])


def test_public_ip_candidates():
    out = N.add_public_ip_candidates(SDP, "8.8.4.4")
    lines = [l for l in out.split("\r\n") if "8.8.4.4" in l]
    assert lines == ["a=candidate:9abc 1 udp 2130706430 8.8.4.4 40012 typ host"]
    assert N.add_public_ip_candidates(SDP, "") == SDP
    with pytest.raises(ValueError):
        N.add_public_ip_candidates(SDP, "not-an-ip")


def test_parse_range():
    assert N.parse_range("") is None
    assert N.parse_range("40000-40199") == (40000, 40199)
    with pytest.raises(ValueError):
        N.parse_range("10-20")


def test_restrict_udp_ports_binds_in_range():
    import aioice.ice as ice
    orig = ice.asyncio
    try:
        assert N.restrict_udp_ports("41000-41003") == (41000, 41003)

        async def go():
            loop = ice.asyncio.get_event_loop()
            ts = []
            for _ in range(4):
                t, _p = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
                ts.append(t)
            ports = sorted(t.get_extra_info("sockname")[1] for t in ts)
            with pytest.raises(OSError):
                await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
            for t in ts:
                t.close()
            return ports

        assert asyncio.run(go()) == [41000, 41001, 41002, 41003]
    finally:
        ice.asyncio = orig
