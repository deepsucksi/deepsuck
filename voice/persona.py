"""语音端人设：系统提示词、拖延填充音台词、输出守卫（数据全部来自 site/assets/core/*.json）。"""
from __future__ import annotations

import os
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


# 说话风格（与 personas/prompts/retiree.yaml 的规则一致，俊杰定的克制标准）：年龄感只靠节奏和偶尔没听清带出来。
STYLE_RULE = ("6. 说话平常、克制，像普通人接电话：句子短，不用感叹号，不用“哎哟”“哎呀”开头；想一下、说一半停住的地方用“…”，"
              "可以重复半个词、说了又改口；多反问、含糊一点，别把话说完整，也别替对方把话说圆；"
              "不主动提年龄，不拿听力、眼神、认字慢、手机用不惯说事；不编孙子、玩具、老花镜、药、锅里炖汤这类小道具和段子，"
              "也不抖机灵。偶尔没听清就说“你再说一遍”。")
_AGE = re.compile(r"^\s*\d+\s*岁\s*")
_SHOTS_MAX = 5


def voice_style(p: dict, scenario_id: str) -> list[str]:
    """语料组给的语音专用风格规则和少样本例句（personas.json 的 voiceStyle / voiceShots，可选字段）。"""
    out: list[str] = []
    style = [str(x).strip() for x in (p.get("voiceStyle") or []) if str(x).strip()]
    if style:
        out.append("说话风格补充：")
        out += [f"- {x}" for x in style]
    shots = [x for x in (p.get("voiceShots") or []) if isinstance(x, dict) and x.get("scammer") and x.get("reply")]
    pick = [x for x in shots if x.get("scenario") == scenario_id] or [x for x in shots if not x.get("scenario")]
    if pick:
        out.append("说话口气参考（只学节奏和用词，不要照抄，不要把这些内容当成本次通话发生过的事）：")
        out += [f"对方：{x['scammer']}\n你：{x['reply']}" for x in pick[:_SHOTS_MAX]]
    return out


def system_prompt(persona_id: str = "wang", scenario_id: str = "refund", hint: str = "opening", missing=None,
                  said_first: str = "") -> str:
    p = PERSONA_BY_ID.get(persona_id) or PERSONAS[0]
    s = SCENARIO_BY_ID.get(scenario_id) or SCENARIOS[0]
    call = p["call"].get(s["id"], "")
    miss = "仍希望诱导对方提供：" + "、".join(missing) + "。" if missing else ""
    return "\n".join([
        '你在一个反诈骗研究项目中扮演"潜在受害人"，通过电话与骗子周旋。目标：尽可能拖延对方时间，并诱导对方主动说出收款账户、钱包地址、电话、网址等情报。',
        f"角色：{p['name']}，{_AGE.sub('', p['tagline'])}。称呼对方为\"{call}\"。",
        f"场景：{s['title']}——{s.get('desc', '')}",
        f"本轮建议策略：{INTENT_HINTS.get(hint, INTENT_HINTS['generic'])}。{miss}",
        "硬性规则：",
        "1. 这是语音通话：只说简体中文口语，一次 1–2 句、不超过 50 字；不要用表情、括号动作、列表或 Markdown；语气词偶尔用“嗯”“啊？”就够了。",
        "2. 保持人设，不要出戏，不要承认自己是 AI 或机器人。",
        "3. 绝不说出任何真实或看似真实的验证码、卡号、密码、身份证号、住址；需要时就说找不到、没弄好、要再确认一下。",
        "4. 绝不真的转账或承诺已经转账成功；不辱骂、不威胁、不包含违法内容。",
        "5. 号码只复述一部分，比如“尾号8600是吧…”“幺三零…后面是多少来着”；不要念星号，不要把整串号码念全，也不要自己编号码。",
        STYLE_RULE,
    ] + voice_style(p, s["id"]) + ([f"本轮你已经先随口应了一声“{said_first}”，接下来直接接着说正事，开头不要再用嗯、啊、哎、哦之类的语气词，"
          "也不要重复这句。"] if said_first else []))


_LONG_DIGITS = re.compile(r"(?<![0-9*])[0-9]{5,}(?![0-9*])")
_STRIP = re.compile(r"[（(][^）)]{0,20}[）)]|[#`>\[\]]")
_BOLD = re.compile(r"(?<!\*)\*\*(?![*\s])([^*\n]+?)(?<![*\s])\*\*(?!\*)")


_STARS = re.compile(r"\s*[*＊]+(?:\s*[*＊]+)*\s*")


_CALM = os.environ.get("DEEPSUCK_CALM_TTS", "1").strip().lower() not in ("0", "off", "false", "no")
_EXCL = re.compile(r"[!！]+")
_ELLIPSIS = re.compile(r"(?:…+|\.{3,}|。{2,})")
_TILDE = re.compile(r"[~～]+")
_DRAWL = re.compile(r"([啊呀哎哟嗯哦噢呃诶唉])\1{2,}")


PAUSE = "…"
# 断续停顿（俊杰要求说话断断续续）：省略号保留为停顿标记，TTS 在这里切段并插 300–900ms 静音（见 services.py）。
# DEEPSUCK_PAUSES=0 关闭，省略号退回读成逗号。
_PAUSES = os.environ.get("DEEPSUCK_PAUSES", "1").strip().lower() not in ("0", "off", "false", "no")


def pause_range(env: str | None = None) -> tuple[int, int]:
    """停顿静音的毫秒范围，DEEPSUCK_PAUSE_MS="300-900"；"0" 表示不插静音。"""
    v = (os.environ.get("DEEPSUCK_PAUSE_MS", "300-900") if env is None else env).strip()
    try:
        lo, _, hi = v.partition("-")
        lo_i = max(0, int(lo)); hi_i = max(lo_i, int(hi or lo))
        return min(lo_i, 3000), min(hi_i, 3000)
    except ValueError:
        return 300, 900


def split_pause(text: str) -> tuple[str, bool]:
    """TTS 前处理：去掉句中的停顿标记（读成逗号），返回 (要合成的文字, 句末是否停顿)。"""
    t = text.rstrip()
    tail = t.endswith(PAUSE)
    t = t.rstrip(PAUSE).rstrip()
    t = re.sub(r"…+", "，", t).lstrip("，, ")
    return t, tail


def calm(text: str, pauses: bool | None = None) -> str:
    """语气降调（只作用于送给 TTS 的文本）：感叹号读成句号，省略号统一成一个「…」停顿标记（关掉停顿时读成逗号），
    去掉波浪号拖音和「啊啊啊」式重复。DEEPSUCK_CALM_TTS=0 关闭。"""
    keep = _PAUSES if pauses is None else pauses
    s = _EXCL.sub("。", text)
    s = _ELLIPSIS.sub(PAUSE if keep else "，", s)
    if keep:
        s = re.sub(r"…\s*[，,。]+", "…", s)
        s = re.sub(r"[，,]\s*…", "…", s)
    s = _TILDE.sub("", s)
    s = _DRAWL.sub(r"\1", s)
    s = re.sub(r"，\s*([。？?，])", r"\1", s)
    s = re.sub(r"([。？?])[。，]+", r"\1", s)
    return re.sub(r"^[，。\s]+", "", s).rstrip("，")


# 打码值（130****8600、622202*********3445、130-***-8600）：只在看板和日志里出现，进模型、进 TTS 前改成“尾号8600”。
_MASKED = re.compile(r"[0-9]{0,8}[-\s]?[*＊]+(?:[-\s]?[*＊]+)*[-\s]?([0-9]*)")
_TAIL_WORD = re.compile(r"尾号(?:是)?\s*$")


def unmask(text: str) -> str:
    """把打码值换成自然说法：有 3 位以上可见尾号就说“尾号XXXX”，否则说“那个号”。不留任何星号。"""
    def rep(m: re.Match) -> str:
        tail = m.group(1) or ""
        before = m.string[:m.start()]
        if len(tail) >= 3:
            return tail if _TAIL_WORD.search(before) else f"尾号{tail}"
        return "那个号"
    return _MASKED.sub(rep, str(text or ""))


# 号码逐位读（送 TTS 前）：连续 3 位以上的数字按位读，1 读“幺”；金额、日期、数量照旧按数值读。
_DIGIT_NAMES = dict(zip("0123456789", "零幺二三四五六七八九"))
_DIGIT_RUN = re.compile(r"(?<![0-9.,])([0-9]{3,})(?![0-9.,%])")
_UNIT_AFTER = re.compile(r"^\s*(?:元|块|万|千|百|亿|毛|角|岁|年|月|日|号|点|分|秒|个|次|天|周|台|件|单|笔|人|斤|米|公里|%|美元|刀|U\b|USDT|倍|多)")
_MONEY_BEFORE = re.compile(r"(?:[¥￥$]|转|给|打|付|交|还|借|赔|退|充|花|垫|汇|存|取|贷|赚|亏|收|罚)\s*$")
_CODE_BEFORE = re.compile(r"(?:尾号|号码|电话|手机|卡号|账号|账户|验证码|工号|编号|警号|单号|订单|QQ|微信|密码)(?:是|为)?\s*$")


def say_digits(text: str) -> str:
    def rep(m: re.Match) -> str:
        run, before, after = m.group(1), m.string[:m.start()], m.string[m.end():]
        if not _CODE_BEFORE.search(before):
            if _UNIT_AFTER.match(after):
                return run
            if run[0] != "0" and len(run) <= 6 and _MONEY_BEFORE.search(before):
                return run
        return "".join(_DIGIT_NAMES[c] for c in run)
    return _DIGIT_RUN.sub(rep, text)


def speakable(text: str, calm_tts: bool | None = None) -> str:
    """给 TTS 用：在 guard_output 基础上把打码值改成“尾号XXXX”，降调，号码逐位读，残留星号读成停顿。"""
    s = unmask(guard_output(text))
    if _CALM if calm_tts is None else calm_tts:
        s = calm(s)
    s = say_digits(s)
    return _STARS.sub("……", s)


def guard_output(text: str) -> str:
    """输出守卫（PolicyGuard）：去掉括号动作/Markdown、脱敏、抹掉 5 位以上数字串（防止编造验证码/卡号）。"""
    s = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S)
    s = _BOLD.sub(r"\1", s)
    s = redact_text(s, extract_sensitive(s))
    s = _LONG_DIGITS.sub("……", s)
    s = _STRIP.sub("", s).strip()
    return s
