"""提取器修复回归（intel/extractor-fixes）：关键词内夹分隔符、手写错字屏蔽词、#1 16 位片段、#2 中文数字量词、姓名边界。
表情写法的坐标 JS（UTF-16）与 Python（码点）不同，所以不进共享夹具，只在这里与 tests/extractor_fixes.test.js 各自断言类型和值。"""
import re

from deepsuck.engine import Session
from deepsuck.extractors import extract, stitch


def got(text):
    return {(e["type"], re.sub(r"\s", "", str(e["value"]))) for e in extract(text)}


def test_keyword_gap_space_punct_emoji():
    for t in ["加微 信 wgold_3487", "加微，信 wgold_3487", "加微😀信 wgold_3487", "加微🙏🙏信：kefu_tb2026", "微信号码事 wgold_3487"]:
        g = got(t)
        assert ("channel", "微信") in g, t
        assert any(k == "wechat" for k, _ in g), t


def test_keyword_gap_no_false_positive():
    assert got("稍微，信息我晚点发") == set()
    assert ("channel", "微信") not in got("我很信任，微，信任何人都行")


def test_issue1_16_digit_fragment_is_not_a_whole_card():
    """Fixes #1：前一回合 16 位（不过 Luhn）+ 后一回合 3 位，拼成 19 位卡号并取代 16 位片段。"""
    r = stitch(["卡号是 6221887154833655", "995，户名王某某"])
    assert [(x["type"], x["value"]) for x in r] == [("bank_card", "6221887154833655995")]
    assert r[0]["supersedes"][0]["value"] == "6221887154833655"
    s = Session("refund", "wang", rng=lambda: 0.5, now=lambda: 0)
    for t in ["卡号是 6221887154833655", "995，户名王某某"]:
        s.ingest(t)
    cards = [k for k in s.intel if k.startswith("bank_card|")]
    assert cards == ["bank_card|6221887154833655995"]
    # 带单位的后续数字不拼
    assert stitch(["卡号 6222 0202 0011 2233", "445 元"]) == []


def test_issue2_quantity_not_merged():
    """Fixes #2：全中文数字后的「两小时」「三小时」「两张」不并进号码。"""
    assert got("电话一三九零零一一二二三三两小时后再打") == {("phone", "13900112233")}
    assert ("phone", "13900112233") in got("电话一三九零零一一二二三三三小时后")
    assert ("bank_card", "6222020200112233445") in got("卡号六二二二零二零二零零一一二二三三四四五两张卡")
    assert got("买两张票") == set()


def test_block_word_handwriting_typos():
    assert stitch(["房问号 199", "0069 7308 是同事的工好"]) == []
    assert stitch(["工好 151", "0859 5928"]) == []


def test_emoji_between_numerals():
    assert ("bank_card", "6222020200112233445") in got("卡号六二二二🌹🌹零二零二🌹零零一一二二三三四四五")
    assert ("phone", "13900112233") in got("电话 一三九😊零零一一😊二二三三")
    assert got("我今年😊六十😊八岁") == set()


def test_spoken_digits_across_newline():
    assert ("phone", "18617954386") in got("电化，幺，八\n六，幺，七，九，五，四，三，八，六")


def test_name_boundaries_and_mid_sentence():
    assert ("name", "周杰") in got("户名周杰农业银行")
    assert ("name", "周杰") in got("户名周杰然后民生银航")
    assert ("name", "李强") in got("收款人叫李强找没听清")
    assert ("name", "李强") in got("收款人是我们公司财务李强，卡号6222020200112233445")
    assert ("name", "李强") in got("钱转到李强的账户上就行")
    assert not any(k == "name" for k, _ in got("转到王经理的卡上"))


def test_note_is_not_a_name():
    """EX-0013：备注「只保留姓氏」不是姓名。"""
    assert not any(k == "name" for k, _ in got("【示例数据】收款户名只保留姓氏。"))
    assert not any(k == "name" for k, _ in got("收款人是我的朋友"))
