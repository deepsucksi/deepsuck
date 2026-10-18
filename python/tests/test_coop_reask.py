"""coop_step 触发收窄（表单句要骗子提到表格；界面细节要骗子给出操作指令）与“已经要过的情报改成我在找”（re_ask），与 JS 一致。"""
import re

from deepsuck.engine import Session
from deepsuck.personas import PERSONAS
from deepsuck.rng import mulberry32

FORM = re.compile(r"表格|表单|证件类型|填在哪一栏|填哪儿|要填哪几栏|姓名写上|姓名填好")
UI = re.compile(r'按钮|页面|屏幕|右下角|图标|下拉框|绿色的勾|请稍候|请核对信息|首页有|"收款人"|"用途"|会议号|实时到账|允许安装|百分之')


def test_form_and_ui_lines_need_form_mention_or_instruction():
    neg = ["请提供一下您的个人信息", "你的资料我这边要核实", "你的账户涉嫌转账洗钱", "我们的APP很安全", "你配合一下调查"]
    for p in PERSONAS:
        s = Session("police", p["id"], rng=mulberry32(5), now=lambda: 0)
        for i in range(80):
            t = s.pick("coop_step", neg[i % len(neg)])
            assert not FORM.search(t) and not UI.search(t), (p["id"], t)
        s2 = Session("police", p["id"], rng=mulberry32(5), now=lambda: 0)
        got = [s2.pick("coop_step", "你先打开手机银行，点转账，然后填写这张表格") for _ in range(40)]
        assert any(UI.search(t) or FORM.search(t) for t in got), p["id"]


def test_second_ask_becomes_looking_for_it():
    lines = ["把钱转到安全账户", "你听不懂吗", "马上转账到安全账户", "转账，快点", "下载我们的APP", "下载APP啊", "怎么还没下载"]
    for p in PERSONAS:
        for seed in range(10):
            s = Session("police", p["id"], rng=mulberry32(seed), now=lambda: 0)
            s.opening()
            out = [s.rule_reply(s.ingest(x)) for x in lines]
            intents = [r["intent"] for r in out]
            assert intents.count("elicit_account") <= 1 and intents.count("elicit_url") <= 1, intents
            for r in out:
                if r["intent"] == "re_ask":
                    assert "在找" in r["text"], r["text"]
            assert "re_ask" in intents, (p["id"], seed, intents)


def test_re_ask_pool_has_no_digits_or_direct_request():
    for p in PERSONAS:
        pool = [t if isinstance(t, str) else t["t"] for t in p["templates"]["re_ask"]]
        assert len(pool) >= 10
        for t in pool:
            assert "在找" in t and not re.search(r"\d", t), t


def test_humanized_replies_never_trip_the_extractor():
    """真人化后的人设台词不能被自己的提取器当成情报（“户名 开户行”被认成户名、拆条后跨行拼出人名等）。"""
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from personas.humanize import Humanizer
    from deepsuck import extractors as X
    for p in PERSONAS:
        lines = [t if isinstance(t, str) else t["t"] for v in p["templates"].values() for t in v]
        lines = [x.replace("{call}", "小伙子").replace("{intel}", "尾号3445").replace("{ask}", "") for x in lines]
        for hw in (False, True):
            for seed in range(8):
                h = Humanizer(profile=p["id"], seed=seed, handwriting=hw)
                for x in lines:
                    out = h.apply(x, "把钱转到安全账户", intent="generic").text
                    assert not X.extract_sensitive(out), (p["id"], x, out, X.extract_sensitive(out))
