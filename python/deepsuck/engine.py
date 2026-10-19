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

from .core import utf16_len
from . import extractors as X
from . import redact as R
from . import tactics as T
from .personas import PERSONAS, PERSONA_BY_ID, SCENARIOS, SCENARIO_BY_ID, STALL_SECONDS, SPEAK_INTEL, resolve_persona_id

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


_DIGIT_TYPES = ("bank_card", "phone", "alipay", "qq")


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

    def fill(self, tpl: str, vars: Optional[dict] = None) -> str:
        call = self.persona["call"].get(self.scenario["id"], "")
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
        """对骗子复述情报的说法：不念打码星号，只说尾号 / 姓氏 /“你发的那个网址”，或把尾号报错一位让对方纠正。

        说出来的只是打码值里本来就公开的部分（尾号、姓氏），所以对外的 transcript 不需要再打码。
        """
        typ = item["type"]
        forms = SPEAK_INTEL.get("crypto" if typ.startswith("crypto_") else typ) or SPEAK_INTEL["default"]
        f = forms[math.floor(self.rng() * len(forms))]
        masked = str(item["masked"])
        raw = "" if raw is None else str(raw)
        d = re.sub(r"[^0-9]", "", raw) if typ in _DIGIT_TYPES else raw
        t = next((d[-k:] for k in (4, 2) if len(d) > k and masked.endswith(d[-k:])), "")
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
            # confirmAskSkip：复述完情报不紧接着要这些（如李大爷复述后马上要电话，会被当成反套话），留给之后的 elicit_*
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
