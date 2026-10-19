"""#194：不一口答应就紧跟着要号码、户名（personas.json eagerAsk.rule）：语音 FOLLOW_UP_RULE 从它拼，只在每轮变化的部分，
不进 #169 固定前缀；与 tests/eager_ask.test.js（网页 llm.js 硬性规则 8）同一句。"""
import json
import subprocess
from pathlib import Path

from deepsuck.personas import EAGER_ASK
from voice import persona as P

ROOT = Path(__file__).resolve().parents[2]
PJ = json.loads((ROOT / "site" / "assets" / "core" / "personas.json").read_text(encoding="utf-8"))


def test_rule_from_personas_json():
    assert EAGER_ASK["rule"] == PJ["eagerAsk"]["rule"]
    assert EAGER_ASK["rule"] in P.FOLLOW_UP_RULE
    assert EAGER_ASK["rule"] not in (ROOT / "voice" / "persona.py").read_text(encoding="utf-8")  # 不留第二份文字


def test_only_in_turn_part_and_fixed_prefix_stable():
    for pid in ("wang", "chen", "lin", "zheng"):
        fixed_a, turn_a = P.prompt_parts(pid, "refund", "generic", [], first_turn=False, scenes=["refund"], refs=set())
        fixed_b, turn_b = P.prompt_parts(pid, "refund", "elicit_account", ["收款账户"], first_turn=False,
                                         scenes=["refund"], refs={"number"})
        assert fixed_a == fixed_b
        assert EAGER_ASK["rule"] not in fixed_a
        assert EAGER_ASK["rule"] in turn_a and EAGER_ASK["rule"] in turn_b


def test_same_sentence_as_web_rule_8():
    js = ("const P=require('./site/assets/js/personas.js'),S=require('./site/assets/js/scenarios.js'),"
          "L=require('./site/assets/js/llm.js');"
          "process.stdout.write(L.systemPrompt(P.BY_ID.wang,S.BY_ID.refund,'generic',[]).split('\\n').find(x=>x.startsWith('8. ')))")
    line = subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert EAGER_ASK["rule"] in line
