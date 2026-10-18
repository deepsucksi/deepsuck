"""公开黑名单比对（与 site/assets/js/blocklist.js 等价）。

- 域名：destroylist、Phishing.Database（MIT）。读取 scripts/fetch-blocklists.js 生成的分片目录，
  可以是本地目录（site/data/blocklist）或线上 https://deepsuck.si/data/blocklist/（只拉取 1–3 个分片）。
- 钱包：ScamSniffer（GPL-3.0）、OFAC SDN 列表，运行时从 GitHub 拉取（缓存在 ~/.cache/deepsuck），不随本仓库分发。

命中仅供参考，不能作为认定依据。

CLI：python -m deepsuck.blocklist https://xxx.top/dl 0xabc...  [--base DIR_OR_URL]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .core import load

_C = load("blocklists")
SHARDS: int = _C["domainShards"]
PARENT_MIN: int = _C["domainParentMinLabels"]
SOURCES = _C["sources"]
DOMAIN_SOURCES = [s for s in SOURCES if s["kind"] == "domain"]
WALLET_SOURCES = [s for s in SOURCES if s["kind"] == "wallet"]
DEFAULT_BASE = os.environ.get("DEEPSUCK_BLOCKLIST_BASE", "https://deepsuck.si/data/blocklist/")
UA = "deepsuck-python (+https://deepsuck.si)"


def fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch) & 0xFF
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def shard_of(domain: str) -> str:
    return f"{fnv1a(domain) % SHARDS:02x}"


def host_of(v) -> Optional[str]:
    s = str(v or "").strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    s = re.sub(r"^//", "", s)
    s = re.split(r"[/?#]", s)[0]
    s = re.sub(r":[0-9]+$", "", s)
    s = re.sub(r"\.+$", "", s)
    if "@" in s:
        s = s[s.rfind("@") + 1:]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z0-9-]{2,}", s) or re.fullmatch(r"[0-9]+(\.[0-9]+){3}", s):
        return None
    return s


def candidates(host: str) -> List[str]:
    parts = host.split(".")
    return [".".join(parts[i:]) for i in range(0, len(parts) - PARENT_MIN + 1)]


def parse_shard(text: str) -> Dict[str, int]:
    out = {}
    for line in (text or "").split("\n"):
        if not line:
            continue
        if "\t" in line:
            d, b = line.split("\t", 1)
            try:
                out[d] = int(b) or 1
            except ValueError:
                out[d] = 1
        else:
            out[line] = 1
    return out


def wallet_key(addr) -> str:
    s = str(addr or "").strip()
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", s) or s.lower().startswith("bc1"):
        return s.lower()
    return s


def parse_wallet_list(text: str, fmt: str) -> set:
    if fmt == "json-array":
        try:
            items = json.loads(text)
        except ValueError:
            items = []
    else:
        items = (text or "").splitlines()
    return {wallet_key(a) for a in (str(x).strip() for x in items) if a and not a.startswith("#")}


def _cache_dir() -> Path:
    p = Path(os.environ.get("DEEPSUCK_CACHE_DIR", Path.home() / ".cache" / "deepsuck"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def http_text(url: str, ttl: int = 6 * 3600, timeout: float = 20) -> str:
    """GET 文本，带磁盘缓存（默认 6 小时）。"""
    f = _cache_dir() / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".txt")
    if f.exists() and time.time() - f.stat().st_mtime < ttl:
        return f.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (固定的公开 https 地址)
        text = r.read().decode("utf-8", "replace")
    f.write_text(text, encoding="utf-8")
    return text


class Client:
    """同步客户端。base 为分片目录（本地路径或 URL）；fetch_text(url) 可注入以便测试。"""

    def __init__(self, base: Optional[str] = None, fetch_text: Optional[Callable[[str], str]] = None):
        base = base or DEFAULT_BASE
        self.base = base if base.endswith("/") else base + "/"
        self._local = not re.match(r"^https?://", self.base)
        self._fetch = fetch_text or self._default_fetch
        self._meta = None
        self._meta_loaded = False
        self._shards: Dict[str, Dict[str, int]] = {}
        self._wallets: Dict[str, Optional[set]] = {}

    def _default_fetch(self, url: str) -> str:
        if not re.match(r"^https?://", url):
            return Path(url).read_text(encoding="utf-8")
        return http_text(url)

    def meta(self) -> Optional[dict]:
        if not self._meta_loaded:
            self._meta_loaded = True
            try:
                self._meta = json.loads(self._fetch(self.base + "meta.json"))
            except Exception:
                self._meta = None
        return self._meta

    def _shard(self, sid: str) -> Dict[str, int]:
        if sid not in self._shards:
            self._shards[sid] = parse_shard(self._fetch(self.base + "d/" + sid + ".txt"))
        return self._shards[sid]

    def check_domain(self, v) -> dict:
        host = host_of(v)
        if not host:
            return {"status": "skip"}
        m = self.meta()
        if not m:
            return {"status": "unavailable"}
        try:
            cands = candidates(host)
            for i, d in enumerate(cands):
                bits = self._shard(shard_of(d)).get(d, 0)
                if bits:
                    srcs = [s["name"] for k, s in enumerate(m["sources"]) if bits & (1 << k)]
                    return {"status": "hit", "how": "exact" if i == 0 else "parent", "sources": srcs,
                            "listed": d, "updated": m.get("generatedAt")}
            return {"status": "clean", "updated": m.get("generatedAt"), "total": m.get("total")}
        except Exception:
            return {"status": "unavailable"}

    def _wallet_set(self, src: dict) -> Optional[set]:
        if src["id"] not in self._wallets:
            try:
                self._wallets[src["id"]] = parse_wallet_list(self._fetch(src["url"]), src.get("format", "lines"))
            except Exception:
                return None
        return self._wallets[src["id"]]

    def check_wallet(self, addr: str, type_: Optional[str] = None) -> dict:
        srcs = [s for s in WALLET_SOURCES if not type_ or type_ in s["chains"]]
        if not srcs:
            return {"status": "skip"}
        key = wallet_key(addr)
        sets = [self._wallet_set(s) for s in srcs]
        ok = sum(1 for x in sets if x is not None)
        if not ok:
            return {"status": "unavailable"}
        hits = [s["name"] for s, st in zip(srcs, sets) if st is not None and key in st]
        return {"status": "hit", "how": "exact", "sources": hits} if hits else {"status": "clean", "checked": ok}

    def check(self, type_: str, raw: str) -> dict:
        if type_ in ("url", "email"):
            return self.check_domain(raw.split("@")[-1] if type_ == "email" else raw)
        if type_.startswith("crypto_"):
            return self.check_wallet(raw, type_)
        return {"status": "skip"}

    def annotate_session(self, session) -> None:
        """对会话里尚未比对的网址/钱包情报做黑名单比对，结果写入 intel[...]['blocklist']（只含来源名，不含原值）。"""
        for item in session.raw_intel():
            key = item["key"]
            if "blocklist" in session.intel[key]:
                continue
            r = self.check(item["type"], item["raw"])
            if r["status"] != "skip":
                session.annotate(key, {k: v for k, v in r.items() if k in ("status", "how", "sources", "updated")})


def _guess_type(v: str) -> str:
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", v):
        return "crypto_eth"
    if re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", v):
        return "crypto_tron"
    if re.fullmatch(r"(bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})", v, re.I):
        return "crypto_btc"
    return "url"


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="DeepSuck 黑名单比对")
    ap.add_argument("values", nargs="+", help="网址/域名/钱包地址")
    ap.add_argument("--base", default=None, help="域名分片目录或 URL（默认 %s）" % DEFAULT_BASE)
    a = ap.parse_args(argv)
    c = Client(a.base)
    for v in a.values:
        print(v, json.dumps(c.check(_guess_type(v), v), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
