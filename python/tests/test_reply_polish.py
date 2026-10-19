"""#132、#134：大模型回复口语化后处理（deepsuck.engine.polish_reply，JS llm.js polishReply 逐字一致）。"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.engine import polish_reply  # noqa: E402

CASES = [
    ("衣服？…哪件啊", "衣服，哪件啊"),
    ("两千？…哪笔钱啊。", "两千，哪笔钱啊。"),
    ("哦，哪个银行？我卡多", "哦，哪个银行，我卡多"),
    ("你是谁？", "你是谁？"),                       # 只有一句问话：不动
    ("你说的这个到底是哪个单位的？你再说", "你说的这个到底是哪个单位的？你再说"),  # 第一句长：不动
    ("具体怎么弄啊？", "到底怎么弄啊？"),
    ("你说具体点，我记一下。", "你说清楚点，我记一下。"),
    ("请问是否要先交钱", "那个是不是要先交钱"),
]
WRITTEN = re.compile(r"请问|是否|因此|然而|此外|首先|其次|进行|以便|为您|请您|感谢您|非常抱歉|您好|相关|了解到|具体|需要注意")


@pytest.mark.parametrize("src,want", CASES)
def test_polish(src, want):
    assert polish_reply(src) == want
    assert polish_reply(want) == want  # 幂等


def test_no_written_words_left():
    for w in WRITTEN.pattern.split("|"):
        assert not WRITTEN.search(polish_reply(f"嗯…{w}这个事我不太懂。")), w


def test_js_parity():
    srcs = [c[0] for c in CASES] + ["退…退款？哪儿的…你说哪件", "啥？你说啥", "嗯？…", "“安心退”？是这个吗"]
    js = subprocess.run(["node", "-e", "const L=require('./site/assets/js/llm.js');"
                         "console.log(JSON.stringify(JSON.parse(process.argv[1]).map(L.polishReply)))", json.dumps(srcs)],
                        cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert json.loads(js) == [polish_reply(s) for s in srcs]


def test_wired_into_voice_guard_and_prompts():
    from voice.persona import FOLLOW_UP_RULE, guard_output, system_prompt
    assert guard_output("衣服？…具体哪件啊") == "衣服，到底哪件啊"
    assert FOLLOW_UP_RULE in system_prompt("lin", "refund", "generic", [], topics=set(), scenes=["refund"])
    assert FOLLOW_UP_RULE not in system_prompt("lin", "refund", "generic", [], topics=set(), scenes=["refund"], first_turn=True)


def test_voice_ellipsis_target_per_persona():
    import json as _j
    from voice.persona import PERSONA_BY_ID, style_rule, system_prompt
    for pid in ("wang", "chen", "lin", "zheng"):
        v = PERSONA_BY_ID[pid]["voiceEllipsis"]
        assert v in ("四成", "四五成", "一半", "五成", "五六成")  # 都在 40–60% 之间
        # #169：voiceStyle 已经写了断续比例的人设，通用规则里不再重复这条；整份提示词里仍按 voiceEllipsis 给出比例
        sp = system_prompt(pid, "refund")
        assert f"大约{v}的句子带“…”" in style_rule(PERSONA_BY_ID[pid]) or f"大约{v}的句子带这种断续" in sp
        assert "大约一半的句子" not in sp
    assert "大约一半的句子" in style_rule({})
