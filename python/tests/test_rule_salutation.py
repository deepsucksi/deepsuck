"""#114：规则引擎回复里的称呼 {call} 只按骗子已经说出口的场景取（heardCues，与 JS engine.js 一致）。"""
import re

from deepsuck import engine as E
from deepsuck.engine import Session
from deepsuck.personas import PERSONAS, SCENARIOS
from deepsuck.rng import mulberry32

NEUTRAL = ["喂，你好，听得到吗？", "是本人吧？我这边找你有点事。", "你现在方便说话吗？", "我等你一下。"]


def _telling_calls(p):
    """会带出场景的称呼（小伙子、小姑娘、姐姐、你 不算）。"""
    return {c for c in p["call"].values() if E.scenes_in(c)} | {"领导", "经理"}


def test_no_salutation_before_scene_is_said():
    for p in PERSONAS:
        bad = _telling_calls(p)
        for s in SCENARIOS:
            for seed in (1, 7, 42):
                ss = Session(scenario=s["id"], persona=p["id"], rng=mulberry32(seed), now=lambda: 0)
                assert ss.salutation() == ""
                ss.opening()  # 开场白按场景选（已批准台词），不在本 issue 范围；这里只看称呼
                texts = []
                for t in NEUTRAL:
                    texts.append(ss.rule_reply(ss.ingest(t))["text"])
                assert ss.heard_scenes() == [] and ss.salutation() == ""
                for x in texts:
                    hit = [c for c in bad if c in x]
                    # 已批准的台词里本来就带的词（例如“最近群里好多冒充领导的”）不算称呼
                    hit = [c for c in hit if not re.search("冒充" + c, x)]
                    assert not hit, (p["id"], s["id"], seed, x)


def test_salutation_follows_heard_scene():
    ss = Session(scenario="refund", persona="wang", rng=mulberry32(1), now=lambda: 0)
    ss.ingest("我是市公安局的民警，你的卡涉嫌洗钱。")
    assert ss.heard_scenes() == ["police"] and ss.salutation() == "警察同志"
    assert ss.fill("{call}你说慢一点") == "警察同志你说慢一点"
    ss2 = Session(scenario="police", persona="wang", rng=mulberry32(1), now=lambda: 0)
    assert ss2.fill("{call}你说慢一点") == "你说慢一点"  # 后台场景不算


def test_salutation_skips_call_that_names_another_scene():
    # 小陈妈妈在刷单场景叫对方“客服”，“客服”会带出退款场景；骗子没说客服时不用
    ss = Session(scenario="task", persona="chen", rng=mulberry32(1), now=lambda: 0)
    ss.ingest("在家也能做的兼职，点赞一单返几块钱，日结。")
    assert ss.heard_scenes() == ["task"] and ss.salutation() == ""
    ss.ingest("我是平台客服，带你做任务。")
    assert ss.salutation() == "客服"


def test_heard_scenes_order_and_implies():
    assert E.heard_scenes(["你好", "我是派出所的", "你有一笔贷款额度"]) == ["police", "loan"]
    assert E.heard_scenes(["你开过校园贷账户"]) == ["campus", "loan"]
