"""语音端人设：系统提示词、拖延填充音台词、输出守卫（数据全部来自 site/assets/core/*.json）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_PY = Path(__file__).resolve().parents[1] / "python"
if str(_PY) not in sys.path:
    sys.path.insert(0, str(_PY))

from deepsuck import extract_sensitive, redact_text  # noqa: E402
from deepsuck.core import load  # noqa: E402
from deepsuck.personas import PERSONA_BY_ID, PERSONAS, SCENARIO_BY_ID, SCENARIOS  # noqa: E402

INTENT_HINTS: dict = load("personas")["intentHints"]

# 短口头语（backchannel）：唯一数据源是 personas/voice_traits.yaml（每个人设的 backchannel 列表），运行时读取。
# 对方说完后先用预合成的音频"嗯……""啊？你说啥"接一下（见 voice/backchannel.py）；音频缓存按文本区分，
# 所以 YAML 里已有条目的文字不要改（改了会重新合成），新增条目首次使用时补合成即可。
_TRAITS_YAML = Path(__file__).resolve().parents[1] / "personas" / "voice_traits.yaml"


def load_fillers(path: Path = _TRAITS_YAML) -> dict:
    """{persona_id: [口头语, ...]}。优先复用 personas.voice_traits.fillers()；导入不了（部署里没有该包）就直接读 YAML；
    都失败则返回 {}（口头语整体不播，通话不受影响）。"""
    if path == _TRAITS_YAML:
        root = str(path.parents[1])
        if root not in sys.path:
            sys.path.append(root)
        try:
            from personas.voice_traits import fillers

            return fillers()
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            print(f"voice.persona: personas.voice_traits 读取失败（{e}），改为直接读 YAML", file=sys.stderr)
    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {pid: [str(x) for x in t.get("backchannel", [])] for pid, t in (data.get("personas") or {}).items()}
    except Exception as e:  # noqa: BLE001
        print(f"voice.persona: 读取口头语失败（{path}: {e}），本进程不播口头语", file=sys.stderr)
        return {}


FILLERS = load_fillers()


def system_prompt(persona_id: str = "wang", scenario_id: str = "refund", hint: str = "opening", missing=None,
                  said_first: str = "") -> str:
    p = PERSONA_BY_ID.get(persona_id) or PERSONAS[0]
    s = SCENARIO_BY_ID.get(scenario_id) or SCENARIOS[0]
    call = p["call"].get(s["id"], "")
    miss = "仍希望诱导对方提供：" + "、".join(missing) + "。" if missing else ""
    return "\n".join([
        '你在一个反诈骗研究项目中扮演"潜在受害人"，通过电话与骗子周旋。目标：尽可能拖延对方时间，并诱导对方主动说出收款账户、钱包地址、电话、网址等情报。',
        f"角色：{p['name']}，{p['tagline']}。称呼对方为\"{call}\"。",
        f"场景：{s['title']}——{s.get('desc', '')}",
        f"本轮建议策略：{INTENT_HINTS.get(hint, INTENT_HINTS['generic'])}。{miss}",
        "硬性规则：",
        "1. 这是语音通话：只说简体中文口语，一次 1–2 句、不超过 50 字；不要用表情、括号动作、列表或 Markdown；可以用“哎”“嗯”“啊？”等语气词。",
        "2. 保持人设，不要出戏，不要承认自己是 AI 或机器人。",
        "3. 绝不说出任何真实或看似真实的验证码、卡号、密码、身份证号、住址；需要时就假装找不到、看不清、操作失败。",
        "4. 绝不真的转账或承诺已经转账成功；不辱骂、不威胁、不包含违法内容。",
        "5. 对方话里的 * 号是已脱敏的信息；提到号码时只说“尾号几位”之类，不要念星号，也不要自己编号码。",
    ] + ([f"本轮你已经先随口应了一声“{said_first}”，接下来直接接着说正事，开头不要再用嗯、啊、哎、哦之类的语气词，"
          "也不要重复这句。"] if said_first else []))


_LONG_DIGITS = re.compile(r"(?<![0-9*])[0-9]{5,}(?![0-9*])")
_STRIP = re.compile(r"[（(][^）)]{0,20}[）)]|[#`>\[\]]")
_BOLD = re.compile(r"(?<!\*)\*\*(?![*\s])([^*\n]+?)(?<![*\s])\*\*(?!\*)")


_STARS = re.compile(r"\s*[*＊]+(?:\s*[*＊]+)*\s*")


def speakable(text: str) -> str:
    """给 TTS 用：在 guard_output 基础上把打码星号读成停顿。"""
    return _STARS.sub("……", guard_output(text))


def guard_output(text: str) -> str:
    """输出守卫（PolicyGuard）：去掉括号动作/Markdown、脱敏、抹掉 5 位以上数字串（防止编造验证码/卡号）。"""
    s = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S)
    s = _BOLD.sub(r"\1", s)
    s = redact_text(s, extract_sensitive(s))
    s = _LONG_DIGITS.sub("……", s)
    s = _STRIP.sub("", s).strip()
    return s
