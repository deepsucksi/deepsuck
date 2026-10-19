"""规则/模板人设引擎（与 site/assets/js/engine.js 等价）。

Session：接收骗子消息 → 提取情报 → 识别话术 → 选择拖延意图 → 生成人设回复 → 汇总脱敏报告。
语音端（voice/）用它做拖延策略层与兜底回复。
"""
from __future__ import annotations

import math
import random
import re
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .core import load, utf16_len
from . import extractors as X
from . import redact as R
from . import tactics as T
from .personas import PERSONAS, PERSONA_BY_ID, SCENARIOS, SCENARIO_BY_ID, STALL_SECONDS, SPEAK_INTEL, DIGIT_ECHO, REPLY_POLISH, resolve_persona_id

REPORT_SCHEMA = "deepsuck.intel-report/v0.1"
VERSION = "0.4.0"


def goal_of(type_: str) -> Optional[str]:
    if type_ == "bank_card":
        return "bank"
    if type_.startswith("crypto_"):
        return "wallet"
    if type_ in ("phone", "qq", "wechat", "alipay", "email"):
        return "phone"
    if type_ == "url":
        return "url"
    if type_ == "name":
        return "name"
    return None


# #114：从骗子原话里认场景（site/assets/core/scenarios.json 的 heardCues，与 JS engine.js、voice/persona.py 同一词表）。
# 规则回复里的称呼 {call} 只按骗子已经说出口的场景取，不按后台选的场景取。
_HEARD = load("scenarios").get("heardCues") or {}
SCENE_CUES = {k: re.compile(v) for k, v in (_HEARD.get("scenes") or {}).items()}
SCENE_IMPLIES = {k: list(v) for k, v in (_HEARD.get("implies") or {}).items()}


def scenes_in(text: str) -> set:
    t = str(text or "")
    return {k for k, r in SCENE_CUES.items() if r.search(t)}


def heard_scenes(texts) -> list:
    """骗子说过的话里认出的场景，按第一次出现的先后；认出前一个场景时，implies 里的也算说过。"""
    out: list = []
    for t in texts:
        t = str(t or "")
        for k in sorted(scenes_in(t), key=lambda k: SCENE_CUES[k].search(t).start()):
            out += [x for x in [k] + SCENE_IMPLIES.get(k, []) if x not in out]
    return out


_DIGIT_TYPES = ("bank_card", "phone", "alipay", "qq")


_DE = DIGIT_ECHO
_DD = "[" + _DE["digits"] + "]"
_DJ = "[" + _DE["joiners"] + "]{0,2}"
_DM = "[" + _DE["digits"] + re.escape(_DE["masks"]) + "]"  # 数字或打码星号
_DRUN = "(?=" + _DM + "*" + _DD + ")" + _DM + "(?:" + _DJ + _DM + "){%d,}" % (_DE["minRun"] - 1)
_DRUN_D = _DD + "(?:" + _DJ + _DM + "){%d,}" % (_DE["minRun"] - 1)  # 以数字开头的串（留第一位用）
_TAILW = "(?:" + "|".join(map(re.escape, _DE["tailWords"])) + ")"
_MONEYW = "(?:" + "|".join(map(re.escape, _DE["moneyUnits"])) + ")"
_STAR = re.escape(_DE["masks"])
_DIGIT_LEAD = re.compile("(" + _DRUN_D + ")" + _DJ + "开头(?:的)?")
_DIGIT_LEAD_AFTER = re.compile("(开头|打头)(?:是|为)?" + _DJ + "(" + _DRUN_D + ")")
_DIGIT_MONEY = re.compile(_DRUN + _DJ + _MONEYW)
_DIGIT_TAIL = re.compile(_TAILW + "(?:是|为)?" + _DJ + _DRUN)
_DIGIT_RUN = re.compile(_DRUN)
# 打码姓名（#130，与 voice/persona.py 的 _unmask_names 同一规则）：张**、王*明、欧阳**，前面的“姓”一并换掉
_NAME_MASK = re.compile("(姓)?(" + "|".join(_DE["compoundSurnames"]) + "|[\u4e00-\u9fff])"
                        "(?:[" + _STAR + "](?:(?![" + _DE["nameTailStop"] + "])[\u4e00-\u9fff](?![" + _STAR + "]))?(?![0-9A-Za-z" + _STAR + "])|[" + _STAR + "]{2,4}(?![0-9A-Za-z" + _STAR + "]))")
_OTHER_MASK = re.compile("[A-Za-z0-9_.:/@\\-]*[" + _STAR + "]+[A-Za-z0-9_.:/@\\-" + _STAR + "]*")
_LITERAL = sorted([(p, "T") for p in _DE["tail"]] + [(p, "O") for p in _DE["other"]], key=lambda x: -len(x[0]))
_HEARD = re.compile("|".join(map(re.escape, _DE["heardAlready"])))
_TOK = re.compile("\ue000([A-Za-z]+)([^\ue001]*)\ue001")
_SEPCH = " \u3000…,，、.．·~～-—"
_MERGE_OT = re.compile("\ue000[OT]\ue001(?:[" + re.escape(_SEPCH) + "]*\ue000[OT]\ue001)+")
_MERGE_N = re.compile("(\ue000(?:N|H)\ue001)(?:[" + re.escape(_SEPCH) + "]*\ue000(?:N|H)\ue001)+")
_CLAUSE_END = "？?！!。；;，,…\n"


def _tok(kind: str, arg: str = "") -> str:
    return "\ue000" + kind + arg + "\ue001"


# ---- 大模型回复口语化（#132、#134，配置在 personas.json 的 replyPolish；JS 在 llm.js 的 polishReply，两边逐字一致）----
_RP_FORMAL = [(a, b) for a, b in REPLY_POLISH["formal"]]
_RP_QMAX = int(REPLY_POLISH["quickQuestionMax"])
_RP_FIRST = re.compile(r"^(\s*)([^。？?！!；;\n]*?)([？?]+)")
_RP_PUNCT = re.compile(r"[…。？?！!，,、；;.\s~～]")
_RP_KEEP = int(REPLY_POLISH["ellipsisKeepPct"])
_RP_SENT = re.compile(r"[^。？！?!；;\n]+[。？！?!；;]*|\n+")
_RP_ELL = re.compile(r"…+|\.{3,}")


def polish_reply(text: str) -> str:
    """大模型回复发出前的口语化：书面词（“具体”“请问”“是否”…）换成口语说法；第一句是快速反问（去标点不超过
    quickQuestionMax 个字，如“衣服？…哪件啊”）且后面还有话时，第一句的问号换成逗号（“衣服，哪件啊”），问题留给后半句。
    换成逗号不换“…”：#131 要把带“…”的句子压在 40–60%，这里不再添“…”。
    只用于大模型回复（语音 guard_output、网页 sanitizeReply），规则引擎的已批准台词不过这一道。"""
    s = str(text or "")
    for a, b in _RP_FORMAL:
        s = s.replace(a, b)
    for _ in range(3):  # “啊？衣服？我好像没收到”：换掉一个，第一句可能还是快速反问
        m = _RP_FIRST.match(s)
        if not m:
            break
        core = _RP_PUNCT.sub("", m.group(2))
        rest = s[m.end():]
        if not (0 < len(core) <= _RP_QMAX and _RP_PUNCT.sub("", rest)):
            break
        s = m.group(1) + m.group(2).rstrip("…") + "，" + rest.lstrip("…，,").lstrip()
    return _thin_ellipsis(s)


def _fnv(text: str) -> int:
    """FNV-1a 32 位，按 UTF-16 码元算（JS 端 charCodeAt 同一结果），用来确定性地挑句子。"""
    h = 0x811C9DC5
    b = text.encode("utf-16-le")
    for i in range(0, len(b), 2):
        h ^= b[i] | (b[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _thin_ellipsis(s: str) -> str:
    """#131：带“…”的句子按 ellipsisKeepPct 确定性地留一部分（按句子文字的哈希挑），没留下的句子把“…”换成逗号
    （句首去掉，句尾去掉或换句号）；“退…退款”这种重复字中间的“…”是结巴，不动（这句照样算带“…”）。"""
    out = []
    for sent in _RP_SENT.findall(s):
        if not _RP_ELL.search(sent) or _fnv(sent) % 100 < _RP_KEEP:
            out.append(sent)
            continue
        def sub(m, sent=sent):
            a, b = m.start(), m.end()
            prev = sent[a - 1] if a else ""
            nxt = sent[b] if b < len(sent) else ""
            if prev and prev == nxt:
                return m.group(0)
            if not prev.strip() or prev in "，,、":
                return ""
            if not nxt:
                return "。"
            if nxt in "。？！?!；;，,、":
                return ""
            return "，"
        out.append(_RP_ELL.sub(sub, sent))
    return "".join(out)


def vague_digits(text: str) -> str:
    """人设回复发出前的过滤（#121 数字、#130 打码片段与叠词；与 engine.js 的 vagueDigits 逐字一致）。

    1. 连续 3 位及以上的数字（阿拉伯、全角、中文数字，混写、夹空格顿号短横、夹打码星号都算）换成含糊说法：
       “6222开头” → “好像是6开头的”、“开头是6222” → “开头好像是6”（只留第一位）；“尾号0123”“后面是零零幺三” → “后面几位没听清”；
       “2000块” → “那么些钱”；其余 → “那几个数没听清”。
    2. 打码片段：打码姓名（“张**”“王*明”“欧阳**”，前面的“姓”一并换掉）→ “那个名字”，其余带 * 的 → “那个号”（网址 / 邮箱各有说法）。
    3. 叠词去重：相邻的“没听清”类说法合并成一处；句子里已经有“没听清”这类意思时，后面的不再叠一个分句——在句末就去掉，在句中换成“那串数”。
       原文里已经写出来的这类说法同样参与去重。
    每类说法有几种，按原句字符码之和轮换。放在错别字扰动之后、语音合成之前；单个、两个数字不动。
    """
    if not text:
        return text
    src = str(text)
    h = sum(ord(c) for c in src)
    s = src
    for p, k in _LITERAL:
        s = s.replace(p, _tok(k))
    s = _DIGIT_LEAD.sub(lambda m: _tok("L", m.group(1)[0]), s)
    s = _DIGIT_LEAD_AFTER.sub(lambda m: m.group(1) + _tok("A", m.group(2)[0]), s)
    s = _DIGIT_TAIL.sub(_tok("T"), s)
    s = _DIGIT_MONEY.sub(_tok("M"), s)
    s = _DIGIT_RUN.sub(_tok("O"), s)
    s = _NAME_MASK.sub(lambda m: m.group(0) if len(m.group(2)) == 1 and m.group(2) in _DE["notSurname"] else _tok("N"), s)
    s = _OTHER_MASK.sub(lambda m: _tok("E" if "@" in m.group() else "U" if re.search(r"[A-Za-z]{2,}\.|\.[A-Za-z]{2,}", m.group()) else "H"), s)
    if "\ue000" not in s:
        return s
    s = _MERGE_OT.sub(lambda m: _tok("T" if "\ue000T" in m.group() else "O"), s)
    s = _MERGE_N.sub(lambda m: m.group(1), s)
    parts = _TOK.split(s)  # [文字, 类型, 参数, 文字, 类型, 参数, ..., 文字]
    plain = "".join(parts[0::3])
    full_used = bool(_HEARD.search(plain))
    out = [parts[0]]
    n = 0
    for i in range(1, len(parts), 3):
        kind, arg, after = parts[i], parts[i + 1], parts[i + 2]
        k = n
        n += 1
        pick = lambda lst, k=k: lst[(h + k) % len(lst)]  # noqa: E731
        if kind in ("O", "T"):
            if not full_used:
                out.append(pick(_DE["tail"] if kind == "T" else _DE["other"]))
                full_used = True
            elif (not after or after[0] in _CLAUSE_END) and (not out[-1] or out[-1][-1] in _SEPCH + _CLAUSE_END):
                out[-1] = out[-1].rstrip(_SEPCH + _CLAUSE_END)  # 自成一个分句的多余一处：连前面的标点一起去掉
            else:
                out.append(pick(_DE["short"]))
        elif kind == "L":
            out.append(pick(_DE["lead"]).replace("{d}", arg) + "的")
        elif kind == "A":
            out.append(pick(_DE["leadAfter"]).replace("{d}", arg))
        elif kind == "M":
            out.append(pick(_DE["money"]))
        elif kind == "N":
            out.append(_DE["name"])
        else:
            out.append({"E": _DE["maskEmail"], "U": _DE["maskUrl"]}.get(kind, _DE["mask"]))
        out.append(after)
    return "".join(out)


def _wrong_digit(t: str) -> str:
    """把尾号报错一位（让对方纠正）：末两位不同则对调，否则末位 +1。"""
    if len(t) >= 2 and t[-1] != t[-2]:
        return t[:-2] + t[-1] + t[-2]
    return t[:-1] + str((int(t[-1]) + 1) % 10)


def _round(x: float) -> int:  # JS Math.round
    return int(math.floor(x + 0.5))


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


class Session:
    def __init__(self, scenario: Optional[str] = None, persona: Optional[str] = None,
                 rng: Optional[Callable[[], float]] = None, now: Optional[Callable[[], float]] = None,
                 engine: str = "rule"):
        self.scenario = SCENARIO_BY_ID.get(scenario) or SCENARIOS[0]
        self.persona = PERSONA_BY_ID.get(resolve_persona_id(persona)) or PERSONAS[0]
        self.rng = rng or random.random
        self.now = now or (lambda: time.time() * 1000)
        self.engine_name = engine
        self.started_at = self.now()
        self.ended_at = None
        self.messages: list = []
        self.intel: dict = {}
        self._raw: dict = {}  # 原始值只留在内存
        self.context: dict = {}
        self.tactic_counts: dict = {}
        self.used: dict = {}
        self.est_seconds = 0
        self.turn = 0
        self.asked: dict = {}  # 本场已经索要过的情报目标（bank / url / phone / wallet / name）
        self.last_intent = None
        self._recent_picks: list = []  # 近 RECENT_N 次选中的台词（近期去重）
        self._recent: list = []  # 最近几个骗子回合的原文（只在内存里，用于跨回合拼接；不进 report）
        self._intent_hist: dict = {}  # 每个意图最近选中的台词（按池大小自适应的去重窗口）
        self._last_new: list = []  # 本回合新情报的 (条目, 原值)，只在内存里，用于自然复述

    # 拖延类意图的"兄弟"顺序：某个意图的台词用完时换一种拖法，而不是立刻重复同一句
    # secrecy（被要求保密）与 loan_stall（贷款 / 征信类拖延）也在链上：语料版骗子会反复要求保密、反复催贷款手续
    STALL_FAMILY = ["urgency_stall", "tech_trouble", "slow_walk", "ask_repeat", "misunderstand", "info_stall", "generic",
                    "secrecy", "loan_stall", "task_stall", "campus_stall"]
    # 近期去重：近 RECENT_N 次选中的台词不再选（除非别无可选），跨意图生效；
    # 另外同一意图最近 floor(可用台词数 / 2) 次选过的也不选（池子越大窗口越大，用完一轮重置后不会马上回到刚说过的）
    RECENT_N = 8
    # 纯拖延意图：同一场不连续两轮都用纯拖延，第二轮换成"小步配合"（coop_step）——看起来在配合、卡在某一步、问具体操作
    ELICIT_GOAL = {"elicit_account": "bank", "elicit_url": "url", "elicit_contact": "phone", "elicit_wallet": "wallet"}
    PURE_STALL = ["otp_stall", "urgency_stall", "tech_trouble", "slow_walk", "ask_repeat", "misunderstand", "info_stall",
                  "generic"]

    def exhausted(self, intent: str) -> bool:
        lst = self.persona["templates"].get(intent)
        if not lst:
            return True
        used = self.used.get(intent) or []
        return all(not isinstance(it, str) or i in used for i, it in enumerate(lst))

    def fresh_intent(self, intent: str) -> str:
        fam = self.STALL_FAMILY
        if intent not in fam or not self.exhausted(intent):
            return intent
        start = fam.index(intent)
        for k in range(1, len(fam)):
            alt = fam[(start + k) % len(fam)]
            if not self.exhausted(alt):
                return alt
        return intent

    # ---- 模板 ----
    def template_list(self, intent):
        return self.persona["templates"].get(intent) or self.persona["templates"]["generic"]

    def pick(self, intent: str, ctx: str = "") -> str:
        lst = self.template_list(intent)
        ctx = str(ctx or "")
        used = self.used.setdefault(intent, [])

        avoid = getattr(self, "avoid_re", None)

        def ok(i):
            it = lst[i]
            if avoid is not None and avoid.search(it if isinstance(it, str) else it["t"]):
                return False
            return isinstance(it, str) or bool(it["re"].search(ctx))

        avail, ctx_hits = [], []
        for i in range(len(lst)):
            if not ok(i):
                continue
            avail.append(i)
            if i not in used and not isinstance(lst[i], str):
                ctx_hits.append(i)
        if not avail:
            g = self.persona["templates"]["generic"]
            it = g[math.floor(self.rng() * len(g))]
            return it if isinstance(it, str) else it["t"]
        recent = self._recent_picks
        hist = self._intent_hist.setdefault(intent, [])
        w = len(avail) // 2
        recent_i = hist[-w:] if w > 0 else []

        def text(i):
            it = lst[i]
            return it if isinstance(it, str) else it["t"]

        def fresh(i):
            return text(i) not in recent and text(i) not in recent_i
        unused = [i for i in avail if i not in used]
        pool = [i for i in ctx_hits if fresh(i)] or [i for i in unused if fresh(i)] or ctx_hits or unused
        if not pool:
            used.clear()
            pool = [i for i in avail if fresh(i)] or avail
        idx = pool[math.floor(self.rng() * len(pool))]
        used.append(idx)
        it = lst[idx]
        recent.append(text(idx))
        del recent[:-self.RECENT_N]
        hist.append(text(idx))
        del hist[:-len(lst)]
        return it if isinstance(it, str) else it["t"]

    def heard_scenes(self) -> list:
        return heard_scenes(m.get("text", "") for m in self.messages if m.get("role") == "scammer")

    def salutation(self) -> str:
        """称呼：按骗子已经说出口的场景取（第一个有称呼的）；称呼本身会带出骗子没说的场景（例如“客服”“警官”）就不用。
        骗子还没说出场景时为空（模板里的 {call} 都在句首或问句后，空着读起来通顺）。"""
        heard = self.heard_scenes()
        for x in heard:
            c = self.persona["call"].get(x, "")
            if c and not (scenes_in(c) - set(heard)):
                return c
        return ""

    def fill(self, tpl: str, vars: Optional[dict] = None) -> str:
        call = self.salutation()
        vars = vars or {}

        def rep(m):
            k = m.group(1)
            if k == "call":
                return call
            v = vars.get(k)
            return "" if v is None else str(v)
        return re.sub(r"\s+$", "", re.sub(r"\{([A-Za-z0-9_]+)\}", rep, tpl))

    # ---- 目标 ----
    def have_goal(self, goal: str) -> bool:
        return any(goal_of(i["type"]) == goal for i in self.intel.values())

    def missing_goals(self):
        return [g for g in self.scenario["goals"] if not self.have_goal(g)]

    # ---- 对话 ----
    def opening(self) -> dict:
        lst = self.persona["openings"].get(self.scenario["id"]) or self.persona["templates"]["generic"]
        it = lst[math.floor(self.rng() * len(lst))]
        return self.record_bot(self.fill(it if isinstance(it, str) else it["t"]), "opening")

    def ingest(self, raw_text: str) -> dict:
        self.turn += 1
        entities = X.extract(raw_text)
        tactics = T.classify(raw_text)
        redacted = R.redact_text(raw_text, entities)
        new_intel = []
        self._last_new = []
        for e in entities:
            if e["sensitive"]:
                key = e["type"] + "|" + re.sub(r"[\s-]", "", str(e["value"])).lower()
                if key not in self.intel:
                    self.intel[key] = {"type": e["type"], "label": e["label"], "masked": e["masked"],
                                       "meta": e["meta"], "count": 0, "firstSeenTurn": self.turn}
                    self._raw[key] = e["value"]
                    new_intel.append(self.intel[key])
                    self._last_new.append((self.intel[key], e["value"]))
                self.intel[key]["count"] += 1
            else:
                bucket = self.context.setdefault(e["type"], {})
                bucket[e["value"]] = bucket.get(e["value"], 0) + 1
        for t in tactics:
            self.tactic_counts[t["id"]] = self.tactic_counts.get(t["id"], 0) + 1
        # 跨回合拼接：语音回合被切断时，卡号 / 手机号会分在相邻两三句里
        recent = self._recent
        recent.append({"raw": "" if raw_text is None else str(raw_text), "entities": entities, "extra": [], "msg": len(self.messages)})
        W = X._ST.get("window", 3)
        del recent[:-W]
        stitched_now = []
        if len(recent) > 1:
            for e in X.stitch([r["raw"] for r in recent]):
                if e["turns"][-1] != len(recent) - 1:
                    continue  # 只处理以本回合结尾的拼接
                key = e["type"] + "|" + e["value"]
                # #1：拼接结果取代被单回合误认成整卡的那一段（从情报与该回合的脱敏实体里去掉，避免重叠打码）
                for sup in e.get("supersedes") or []:
                    sk = sup["type"] + "|" + re.sub(r"[\s-]", "", str(sup["value"])).lower()
                    old = self.intel.pop(sk, None)
                    self._raw.pop(sk, None)
                    if old is not None:
                        new_intel[:] = [x for x in new_intel if x is not old]
                        self._last_new[:] = [x for x in self._last_new if x[0] is not old]
                    ents = recent[sup["turn"]]["entities"]
                    ents[:] = [x for x in ents if not (x["type"] == sup["type"] and x.get("start") == sup["start"]
                                                       and x.get("end") == sup["end"])]
                for p in e["parts"]:
                    recent[p["turn"]]["extra"].append({"type": e["type"], "start": p["start"], "end": p["end"],
                                                       "masked": p["masked"], "sensitive": True})
                for p in e["parts"]:
                    r = recent[p["turn"]]
                    if p["turn"] < len(recent) - 1 and r["msg"] < len(self.messages):
                        self.messages[r["msg"]]["text"] = R.redact_text(r["raw"], r["entities"] + r["extra"])
                stitched_now.append(e)
                # #8：断续报卡号拆成三个回合时，前两回合先拼出一段 16–18 位（62 开头）的“卡号”，第三回合拼出完整卡号后撤掉那段前缀
                if e["type"] == "bank_card":
                    for pk in [k for k, it in self.intel.items() if it["type"] == "bank_card" and (it.get("meta") or {}).get("stitched")
                               and k != key and len(str(self._raw.get(k, ""))) < len(e["value"]) and e["value"].startswith(str(self._raw.get(k, "")))]:
                        old = self.intel.pop(pk)
                        self._raw.pop(pk, None)
                        new_intel[:] = [x for x in new_intel if x is not old]
                        self._last_new[:] = [x for x in self._last_new if x[0] is not old]
                if key not in self.intel:
                    self.intel[key] = {"type": e["type"], "label": e["label"], "masked": e["masked"],
                                       "meta": e["meta"], "count": 0, "firstSeenTurn": self.turn}
                    self._raw[key] = e["value"]
                    new_intel.append(self.intel[key])
                    self._last_new.append((self.intel[key], e["value"]))
                self.intel[key]["count"] += 1
        if stitched_now:
            redacted = R.redact_text(raw_text, entities + recent[-1]["extra"])
        self.est_seconds += 10 + _round(utf16_len(str(raw_text)) * 0.6)
        analysis = {
            "turn": self.turn,
            "redacted": redacted,
            "tactics": tactics,
            "newIntel": [{"type": i["type"], "label": i["label"], "masked": i["masked"]} for i in new_intel],
            "entities": [{"type": e["type"], "label": e["label"], "masked": e["masked"], "sensitive": e["sensitive"]}
                         for e in entities + stitched_now],
        }
        self.messages.append({"role": "scammer", "text": redacted, "t": self.now(),
                              "tactics": [t["id"] for t in tactics], "intel": analysis["newIntel"]})
        # #92：验证码被 ASR 切成几段（「验证码是 38」「27 15」）时，和前几段对方的话连起来再判断一次，
        # 本段与前几段（已脱敏文本）里命中的数字一起补打码
        idx = [i for i, m in enumerate(self.messages) if m.get("role") == "scammer"][-(R.otp_seg_window() + 1):]
        if len(idx) > 1:
            fixed = R.redact_otp_segments([self.messages[i]["text"] for i in idx])
            for i, t in zip(idx, fixed):
                self.messages[i]["text"] = t
            analysis["redacted"] = fixed[-1]
        # #120：两边说话人连起来再看一次（人设问验证码、对方下一句报数字；卡号前缀和尾号分在两句），只回写对方的话
        win = self.messages[max(0, len(self.messages) - (2 * R.otp_seg_window() + 1)):]
        both = R.redact_dialog_segments([m["text"] for m in win], [m.get("role") for m in win])
        for m, t in zip(win, both):
            if m.get("role") == "scammer":
                m["text"] = t
        analysis["redacted"] = both[-1]
        return analysis

    def choose_intent(self, a: dict) -> str:
        has = {t["id"] for t in a["tactics"]}
        r = self.rng()
        if a["newIntel"]:
            return "confirm_intel"
        if "otp" in has:
            return "otp_stall"
        if "acquaintance" in has and "transfer" not in has and self.used.get("verify_count", 0) < 2:
            self.used["verify_count"] = self.used.get("verify_count", 0) + 1
            return "verify_identity"
        if "safe_account" in has or "transfer" in has:
            if "crypto" in has and not self.have_goal("wallet"):
                return "elicit_wallet"
            if not self.have_goal("bank") and not self.have_goal("wallet"):
                return "elicit_account"
            return "fake_progress"
        if "crypto" in has and not self.have_goal("wallet"):
            return "elicit_wallet"
        if "app_download" in has:
            return "tech_trouble" if self.have_goal("url") else "elicit_url"
        flavor = ("task_stall" if "task_rebate" in has else "loan_stall" if "loan_fraud" in has
                  else "campus_stall" if "campus_loan" in has else None)
        if flavor and self.last_intent != flavor:
            return flavor
        if ("authority" in has or "threat" in has) and not self.used.get("scared_once"):
            self.used["scared_once"] = True
            return "scared"
        if "secrecy" in has:
            return "secrecy"
        if "high_return" in has:
            return "greedy" if self.have_goal("url") else "elicit_url"
        if "info_harvest" in has:
            return "info_stall"
        if "off_platform" in has and not self.have_goal("phone"):
            return "elicit_contact"
        if "romance" in has:
            return "romance"
        if "urgency" in has:
            return "urgency_stall"
        if "threat" in has or "authority" in has:
            return "ask_repeat" if r < 0.5 else "misunderstand"
        missing = self.missing_goals()
        if missing and self.turn % 3 == 0:
            return {"bank": "elicit_account", "wallet": "elicit_wallet", "phone": "elicit_contact",
                    "url": "elicit_url", "name": "elicit_account"}[missing[0]]
        stalls = ["ask_repeat", "misunderstand", "tech_trouble", "slow_walk", "generic"]
        return stalls[math.floor(r * len(stalls))]

    def speak_intel(self, item: dict, raw) -> str:
        """对骗子复述情报的说法：不念打码星号，只说姓氏 /“你说的那张卡”/“你发的那个网址”。

        #121 起号码类一个数字都不复述（尾号、开头几位都不说）；说出来的最多是姓氏，对外的 transcript 不需要再打码。
        """
        typ = item["type"]
        forms = SPEAK_INTEL.get("crypto" if typ.startswith("crypto_") else typ) or SPEAK_INTEL["default"]
        f = forms[math.floor(self.rng() * len(forms))]
        masked = str(item["masked"])
        raw = "" if raw is None else str(raw)
        d = re.sub(r"[^0-9]", "", raw) if typ in _DIGIT_TYPES else raw
        t = next((d[-k:] for k in (4, 2) if len(d) > k and masked.endswith(d[-k:])), "")
        if re.search(r"[0-9]", t):
            t = ""  # #121：号码一个数字都不复述（尾号也不说），带 {t}/{x} 的说法退回“你说的那个…”
        s = raw[:1] if typ == "name" and raw[:1] and masked.startswith(raw[:1]) else ""
        if (("{t}" in f or "{x}" in f) and not t) or ("{x}" in f and not t.isdigit()) or ("{s}" in f and not s):
            f = SPEAK_INTEL["default"][0]
        return (f.replace("{t}", t).replace("{x}", _wrong_digit(t) if t.isdigit() else t)
                 .replace("{s}", s).replace("{label}", item["label"]))

    def rule_reply(self, analysis: dict) -> dict:
        prev_intent = self.last_intent
        intent = self.fresh_intent(self.choose_intent(analysis))
        if (intent in self.PURE_STALL and self.last_intent in self.PURE_STALL
                and self.persona["templates"].get("coop_step")):
            intent = "coop_step"
        # 可选的意图门控（默认无；语音端用它保证只接对方已经说过的话，见 voice/persona.py gate_intent）
        gate = getattr(self, "intent_gate", None)
        if gate is not None:
            intent = gate(intent)
        # 同一场已经要过的情报不再直接索要，改成"我在找"（re_ask）
        goal = self.ELICIT_GOAL.get(intent)
        if goal:
            if self.asked.get(goal) and self.persona["templates"].get("re_ask"):
                intent = "re_ask"
            self.asked[goal] = True
        self.last_intent = intent
        vars = {}
        if intent == "confirm_intel":
            vars["intel"] = "，".join(self.speak_intel(i, raw) for i, raw in self._last_new)
            missing = self.missing_goals()
            asks = self.persona["asks"]
            g0 = missing[0] if missing else None
            # confirmAskSkip：复述完情报不紧接着要这些（如复述后马上要电话，会被骗子当成反套话），留给之后的 elicit_*
            skip = g0 in (self.persona.get("confirmAskSkip") or [])
            vars["ask"] = (asks.get(g0) if g0 and not skip and not self.asked.get(g0) else None) or asks["none"]
            if g0 and not skip:
                self.asked[g0] = True
        # afterReAskAvoid：刚说完"我在找"（re_ask）的下一轮不接这些说法（如小林"切出去了"，连着说像找借口拖）
        av = self.persona.get("afterReAskAvoid")
        self.avoid_re = re.compile(av) if av and prev_intent == "re_ask" else None
        text = self.fill(self.pick(intent, analysis["redacted"]), vars)
        self.avoid_re = None
        return self.record_bot(text, intent)

    def reply(self, raw_text: str) -> dict:
        """便捷方法：ingest + rule_reply。"""
        return self.rule_reply(self.ingest(raw_text))

    def record_bot(self, text: str, intent: str) -> dict:
        text = vague_digits(text)  # #121：规则和大模型的回复都不带连续 3 位以上的数字
        safe = R.redact_text(text, X.extract_sensitive(text))
        stall = STALL_SECONDS.get(intent) or 30
        self.est_seconds += stall + _round(utf16_len(safe) * 0.12)
        msg = {"role": "bot", "text": safe, "t": self.now(), "intent": intent}
        self.messages.append(msg)
        return msg

    def typing_delay(self, text: str) -> float:
        return min(6500, 700 + utf16_len(str(text)) * self.persona["msPerChar"] * (0.6 + self.rng() * 0.5))

    def end(self):
        if not self.ended_at:
            self.ended_at = self.now()

    def stats(self) -> dict:
        end = self.ended_at or self.now()
        return {
            "messages": len(self.messages),
            "scammerMessages": sum(1 for m in self.messages if m["role"] == "scammer"),
            "botMessages": sum(1 for m in self.messages if m["role"] == "bot"),
            "wallClockSeconds": _round((end - self.started_at) / 1000),
            "estimatedScammerSeconds": self.est_seconds,
            "intelCount": len(self.intel),
            "riskScore": T.risk_score(self.tactic_counts),
            "tacticKinds": len(self.tactic_counts),
        }

    def intel_list(self) -> list:
        out = []
        for i in self.intel.values():
            o = {"type": i["type"], "label": i["label"], "masked": i["masked"], "meta": i["meta"],
                 "count": i["count"], "firstSeenTurn": i["firstSeenTurn"]}
            if "blocklist" in i:
                o["blocklist"] = i["blocklist"]
            out.append(o)
        return out

    def raw_intel(self) -> list:
        """原始值（仅内存，用于黑名单比对/情报库提交；不要写进报告）。"""
        return [{"key": k, "type": i["type"], "raw": self._raw[k], "masked": i["masked"]} for k, i in self.intel.items()]

    def annotate(self, key: str, blocklist: dict) -> None:
        """记录黑名单比对结果（只含状态与来源名，不含原值）。"""
        if key in self.intel:
            self.intel[key]["blocklist"] = blocklist

    def tactic_list(self) -> list:
        lst = [{"id": k, "label": T.BY_ID[k]["label"] if k in T.BY_ID else k, "count": c}
               for k, c in self.tactic_counts.items()]
        return sorted(lst, key=lambda x: -x["count"])

    def report(self) -> dict:
        return {
            "schema": REPORT_SCHEMA,
            "generator": f"DeepSuck {VERSION}",
            "generatedAt": _iso(self.now()),
            "disclaimer": "本报告由 DeepSuck 生成，所有敏感信息均已脱敏，仅用于防诈研究与教育，不得用于骚扰、报复或任何违法用途。",
            "session": {
                "scenario": {"id": self.scenario["id"], "title": self.scenario["title"]},
                "persona": {"id": self.persona["id"], "name": self.persona["name"]},
                "engine": self.engine_name,
                "startedAt": _iso(self.started_at),
                "endedAt": _iso(self.ended_at) if self.ended_at else None,
            },
            "stats": self.stats(),
            "intel": self.intel_list(),
            "context": self.context,
            "tactics": self.tactic_list(),
            "transcript": [{"role": m["role"], "text": m["text"], "at": _iso(m["t"]), "intent": m.get("intent"),
                            "tactics": m.get("tactics")} for m in self.messages],
        }
