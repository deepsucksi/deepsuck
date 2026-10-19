"""网页大模型回复的发送前过滤（#194），与 site/assets/js/llm.js 的 sanitizeReply、fixQuotes 逐字一致。

共用用例 tests/fixtures/llm_sanitize.json（Node：tests/llm_sanitize.test.js；Python：python/tests/test_llm_sanitize.py）。
由已有的 Python 实现拼起来：engine.hold_transfer（#187）、refs.mask_names / speak_masked（#130 / #157 / #172）、
redact.redact_text、engine.polish_reply（#132 / #134 / #131）；只有 fixQuotes 和整句引号、长数字、截断这几步是新写的。
网页端之后还有两道：engine.dedupe_tail（demo.js，最近三轮尾句）和 Session.record_bot 里的 vague_digits，
见 llm_pipeline。
"""
from __future__ import annotations

import re
from typing import List, Optional

from . import extractors as X
from . import redact as R
from .engine import dedupe_tail, hold_transfer, polish_reply, tail_sentence, vague_digits
from .refs import mask_names, speak_masked

_THINK = re.compile(r"<think>[\s\S]*?</think>")
_WRAP = re.compile(r"^\s*([\"“「])([\s\S]*)([\"”」])\s*$")
_LONG = re.compile(r"(?<![0-9*])[0-9]{5,}(?![0-9*])")
QUOTE_PAIRS = {"“": "”", "「": "」", "『": "』", "‘": "’"}
QUOTE_CLOSE = {v: k for k, v in QUOTE_PAIRS.items()}
QUOTE_MAX = 8
MAX_CHARS = 160


def fix_quotes(text: str) -> str:
    """引号配对：去掉单边引号；引号里超过 8 个字、为空或含省略号的引用去掉引号只留文字（llm.js fixQuotes）。
    JS 按 Array.from（码点）数下标，这里 list(str) 同样按码点。"""
    a = list(str(text or ""))
    drop, stack, dq = set(), [], -1

    def judge(o: int, e: int) -> None:
        inner = "".join(a[o + 1:e])
        if not inner.strip() or e - o - 1 > QUOTE_MAX or re.search(r"…|\.\.\.", inner):
            drop.update((o, e))

    for i, c in enumerate(a):
        if c in QUOTE_PAIRS:
            stack.append(i)
        elif c in QUOTE_CLOSE:
            k = stack[-1] if stack else -1
            if k >= 0 and a[k] == QUOTE_CLOSE[c]:
                stack.pop()
                judge(k, i)
            else:
                drop.add(i)
        elif c == '"':
            if dq < 0:
                dq = i
            else:
                judge(dq, i)
                dq = -1
    drop.update(stack)
    if dq >= 0:
        drop.add(dq)
    return "".join(c for j, c in enumerate(a) if j not in drop)


def _js_trim(s: str) -> str:
    # JS String.prototype.trim 去掉的空白（含全角空格、BOM）；Python str.strip() 还会去掉 \x1c-\x1f，这里不去
    return s.strip(" \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
                   "\u2028\u2029\u202f\u205f\u3000\ufeff")


def sanitize_reply(text: str) -> str:
    """llm.js sanitizeReply：去思考段 → 整句外层引号 → holdTransfer → 打码姓名 → 脱敏 → 打码值换自然说法 →
    5 位以上数字换“……” → 160 字截断 → 引号配对 → 口语化。"""
    s = _js_trim(_THINK.sub("", str(text or "")))
    w = _WRAP.match(s)
    if w and (w.group(3) == '"' if w.group(1) == '"' else QUOTE_PAIRS.get(w.group(1)) == w.group(3)) \
            and not re.search("[\"“”「」]", w.group(2)):
        s = w.group(2)
    s = hold_transfer(s)
    s = mask_names(s, False)
    s = R.redact_text(s, X.extract_sensitive(s))
    s = speak_masked(s, False)
    s = _LONG.sub("……", s)
    if len(s) > MAX_CHARS:
        s = s[:MAX_CHARS] + "……"
    s = fix_quotes(s)
    s = polish_reply(s)
    return _js_trim(s)


def llm_pipeline(text: str, recent_bot_texts: Optional[List[str]] = None, persona_id: Optional[str] = None) -> str:
    """网页端大模型回复发出前的整条链（代理模式：服务端和 viaProxy 各一次 sanitizeReply → demo.js dedupeTail → recordBot 的 vagueDigits），
    不含 recordBot 最后那道脱敏（record_bot 自己做）。recent_bot_texts：本场人设最近几条回复（取最后三条的尾句）。"""
    s = sanitize_reply(sanitize_reply(text))  # 代理模式（网页默认）：server/index.js 过一遍，viaProxy 收到后再过一遍
    tails = [tail_sentence(t) for t in (recent_bot_texts or [])[-3:]]
    s = dedupe_tail(s, tails, persona_id)
    return vague_digits(s)
