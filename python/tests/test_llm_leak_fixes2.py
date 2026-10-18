"""第二轮大模型骗子露馅修补回归：复述情报不带打码星号、对外产物仍脱敏、纯拖延不连续两轮、验证码拖延句池与自适应去重窗口。"""
import json
import re

from deepsuck import extractors as X
from deepsuck import redact as R
from deepsuck.engine import Session
from deepsuck.personas import PERSONAS, SPEAK_INTEL
from deepsuck.rng import mulberry32

# 虚构测试数据
RAW = {
    "card": "6222020200112233445",
    "phone": "13900112233",
    "name": "王建国",
    "url": "https://refund-tb-kefu.top/dl",
    "tron": "TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe",
    "qq": "2876543210",
    "wechat": "kefu_tb2026",
}
LINES = [
    f"收款卡号 {RAW['card']}，户名{RAW['name']}，工商银行",
    f"有问题打 {RAW['phone']}，或者加QQ {RAW['qq']}，微信 {RAW['wechat']}",
    f"下载 APP：{RAW['url']}",
    f"USDT 转到 TRC20 地址 {RAW['tron']}",
]


def _texts(lst):
    return [it if isinstance(it, str) else it["t"] for it in lst]


def _run(persona, seed, lines):
    s = Session("police", persona, rng=mulberry32(seed), now=lambda: 0)
    s.opening()
    out = [s.rule_reply(s.ingest(x)) for x in lines]
    return s, out


def test_confirm_intel_has_no_mask_stars_and_no_raw_value():
    for p in PERSONAS:
        for seed in range(30):
            s, out = _run(p["id"], seed, LINES)
            for r in out:
                if r["intent"] != "confirm_intel":
                    continue
                assert not re.search(r"[*＊]", r["text"]), r["text"]
                for v in RAW.values():
                    assert v not in r["text"], (v, r["text"])
                assert "{" not in r["text"], r["text"]


def test_public_outputs_stay_masked():
    for p in PERSONAS:
        s, _ = _run(p["id"], 7, LINES)
        rep = json.dumps(s.report(), ensure_ascii=False)
        for v in RAW.values():
            assert v not in rep, v
        masked = {i["type"]: i["masked"] for i in s.intel_list()}
        assert masked["bank_card"] == R.mask_bank_card(RAW["card"])
        assert masked["phone"] == R.mask_phone(RAW["phone"])
        assert "*" in masked["name"]


def test_spoken_tail_only_reveals_what_mask_already_shows():
    s = Session("police", "wang", rng=mulberry32(1), now=lambda: 0)
    for e in X.extract_sensitive(" ".join(LINES)):
        for k in range(40):
            said = s.speak_intel({"type": e["type"], "label": e["label"], "masked": e["masked"]}, e["value"])
            assert "*" not in said and e["value"] not in said
            for run in re.findall(r"[0-9A-Za-z]{2,}", said):
                if run == "QQ":
                    continue
                # 说出的数字 / 字母串必须是打码值里本来就公开的尾部（或把尾号报错一位）
                tail = e["masked"][-len(run):]
                assert run == tail or sorted(run) == sorted(tail) or run[:-1] == tail[:-1], (e["type"], said)
            assert R.redact_text(said, X.extract_sensitive(said)) == said, said


def test_speak_intel_forms_cover_types_and_wrong_digit():
    for k in ("bank_card", "phone", "name", "url", "crypto", "default"):
        assert SPEAK_INTEL[k]
    s = Session("police", "lin", rng=lambda: 0.99, now=lambda: 0)  # 取最后一种说法：尾号报错一位
    said = s.speak_intel({"type": "bank_card", "label": "银行卡号", "masked": R.mask_bank_card(RAW["card"])}, RAW["card"])
    assert said == "卡号尾号3454"


def test_no_template_redacts_itself():
    # 机器人台词被自己的提取器误判（“户名写谁的”“收款人电话”）会在对外文本里出现星号
    for p in PERSONAS:
        lines = [t for lst in p["templates"].values() for t in _texts(lst)] + list(p["asks"].values())
        for t in lines:
            for call in set(p["call"].values()) | {""}:
                u = t.replace("{call}", call).replace("{intel}", "").replace("{ask}", "")
                assert R.redact_text(u, X.extract_sensitive(u)) == u, (p["id"], u)
                assert not re.search(r"\d{5,}", u), u


def test_no_two_pure_stall_turns_in_a_row():
    stall_lines = ["你快点，别磨蹭", "验证码发我", "听不懂吗？赶紧的", "就差你了", "你到底弄好没有", "嗯", "好的"]
    for p in PERSONAS:
        for seed in range(20):
            s = Session("police", p["id"], rng=mulberry32(seed), now=lambda: 0)
            s.opening()
            prev = None
            for i in range(30):
                r = s.rule_reply(s.ingest(stall_lines[(i * 3 + seed) % len(stall_lines)]))
                assert not (prev in Session.PURE_STALL and r["intent"] in Session.PURE_STALL), (p["id"], seed, i, prev, r)
                prev = r["intent"]


def test_coop_step_never_leaks():
    for p in PERSONAS:
        t = _texts(p["templates"]["coop_step"])
        assert len(set(t)) >= 16, (p["id"], len(t))
        for x in t:
            assert not re.search(r"\d{3,}", re.sub(r"106", "", x)), x  # 至多两位虚构数字（“106 开头”是短信号段）


def test_otp_pool_size_and_adaptive_window():
    for p in PERSONAS:
        pool = _texts(p["templates"]["otp_stall"])
        assert len(set(pool)) >= 16, (p["id"], len(pool))
        s = Session("police", p["id"], rng=mulberry32(3), now=lambda: 0)
        picks = [s.pick("otp_stall", "验证码发我") for _ in range(60)]
        n, w = len(pool), len(pool) // 2
        assert len(set(picks[:n])) == n  # 一轮内不重复
        for i, x in enumerate(picks):
            assert x not in picks[max(0, i - w):i], (p["id"], i)  # 重置后也不回到最近 floor(n/2) 次说过的
