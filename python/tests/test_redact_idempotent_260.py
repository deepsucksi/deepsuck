"""#260 / #265：redact_line 幂等 L(L(x))==L(x)；拆字解释整段换成「那个名字」，不残留「耳*」。

仅解释姓怎么写的拆字例句可直接写在测试里；完整姓名仍从 fixtures 按索引取。"""
import json
from pathlib import Path

import pytest

from voice.callredact import redact_line

ROOT = Path(__file__).resolve().parents[2]
CE = json.loads((ROOT / "tests/fixtures/redact.json").read_text(encoding="utf-8"))["charExplain"]

# inv-2030 基线曾失败的 11 句（假名 / 假地址）+ 拆字解释句 + P67EYWIG 类已打码残片
IDEM_CASES = [
    "http://192.168.1.10:8080/admin 登录",
    "弓长张伟大的",
    "户名是弓长张三丰",
    "户名木子李四",
    "户名耳东陈立",
    "收款人叫有名的名对吧",
    "收款人叫李四",
    "收款人叫李强找没听清",
    "收款人叫王建国",
    "收款人姓张伟",
    "耳东陈，立刻转",
    # #265：只露部件不露姓的拆字解释（无完整姓名）
    "耳东陈，耳朵的耳东边的东",
    "耳东陈耳朵的耳东边的东",
    "耳东陈，东方的东",
    # 已打码残片再跑应稳定（生产长通话 P67EYWIG 类）
    "户名是张*。",
    "收款人叫李*",
    "户名是弓长张**",
]


@pytest.mark.parametrize("text", IDEM_CASES)
def test_redact_line_idempotent(text):
    once = redact_line(text)
    assert redact_line(once) == once


def test_char_explain_15_no_ear_star():
    """#265：charExplain[15] 整段统一占位，不残留「耳*」。"""
    t = CE[15]["text"]
    out = redact_line(t)
    assert out == redact_line(out)
    assert "耳*" not in out
    assert "耳东" not in out
    assert "陈" not in out
    assert "那个名字" in out


@pytest.mark.parametrize("text", [
    "耳东陈，耳朵的耳东边的东",
    "耳东陈耳朵的耳东边的东",
])
def test_split_explain_whole_phrase(text):
    """只解释姓怎么写：整段换成「那个名字」，部件与姓都不留。"""
    out = redact_line(text)
    assert out == "那个名字"
    assert redact_line(out) == out
