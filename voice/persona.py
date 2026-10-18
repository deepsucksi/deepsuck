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


def _load_traits(path: Path = _TRAITS_YAML) -> dict:
    """{persona_id: {字段: ...}}。优先复用 personas.voice_traits.personas()；导入不了（部署里没有该包）就直接读 YAML；
    都失败则返回 {}（口头语整体不播、开场用默认的“喂？哪位”，通话不受影响）。"""
    if path == _TRAITS_YAML:
        root = str(path.parents[1])
        if root not in sys.path:
            sys.path.append(root)
        try:
            from personas.voice_traits import personas

            return personas()
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            print(f"voice.persona: personas.voice_traits 读取失败（{e}），改为直接读 YAML", file=sys.stderr)
    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return dict(data.get("personas") or {})
    except Exception as e:  # noqa: BLE001
        print(f"voice.persona: 读取语音人设失败（{path}: {e}），本进程不播口头语", file=sys.stderr)
        return {}


def load_fillers(path: Path = _TRAITS_YAML) -> dict:
    """{persona_id: [口头语, ...]}，即 voice_traits.yaml 每个人设的 backchannel。"""
    return {pid: [str(x) for x in (t or {}).get("backchannel", [])] for pid, t in _load_traits(path).items()}


def load_voice_openings(path: Path = _TRAITS_YAML) -> dict:
    """{persona_id: [接电话那一声, ...]}，即 voice_traits.yaml 里写了 opening 的人设。"""
    return {pid: [str(x) for x in t["opening"]] for pid, t in _load_traits(path).items() if (t or {}).get("opening")}


FILLERS = load_fillers()


# 说话风格（与 personas/prompts/retiree.yaml 的规则一致，俊杰定的克制标准）：年龄感只靠节奏和偶尔没听清带出来。
STYLE_RULE = ("6. 说话平常、克制，像普通人接电话：句子短，不用感叹号，不用“哎哟”“哎呀”开头；想一下、说一半停住的地方用“…”，"
              "大约一半的句子带“…”，另一半说完整的短句，不要每句都带；可以重复半个词、说了又改口；"
              "可以反问、含糊一点，但不是每句都问，别把话说完整，也别替对方把话说圆；"
              "不主动提年龄，不拿听力、眼神、认字慢、手机用不惯说事；不编孙子、玩具、老花镜、药、锅里炖汤这类小道具和段子，"
              "也不抖机灵。偶尔没听清就说“你再说一遍”。")
_AGE = re.compile(r"^\s*\d+\s*岁\s*")
_SHOTS_MAX = 5


def voice_style(p: dict, scenario_id: str, topics=None, first_turn: bool = False) -> list[str]:
    """语料组给的语音专用风格规则和少样本例句（personas.json 的 voiceStyle / voiceShots，可选字段）。

    topics 不为 None 时（通话中），例句只留“对方台词里的话题都已经在本通电话里出现过”的那几条，
    免得例句里的链接、加微信、转账把模型往对方还没提的方向带。"""
    out: list[str] = []
    style = [str(x).strip() for x in (p.get("voiceStyle") or []) if str(x).strip()]
    if style:
        out.append("说话风格补充：")
        out += [f"- {x}" for x in style]
    shots = [x for x in (p.get("voiceShots") or []) if isinstance(x, dict) and x.get("scammer") and x.get("reply")]
    pick = [x for x in shots if x.get("scenario") == scenario_id] or [x for x in shots if not x.get("scenario")]
    if topics is not None:
        pick = [x for x in pick if topics_in(x["scammer"] + x["reply"]) <= set(topics)]
    if first_turn:  # 第一轮只给“第一句不是问句”的例句，免得照着例句一开口就反问
        pick = [x for x in pick if not first_sentence_is_question(x["reply"])]
    if pick:
        out.append("说话口气参考（只学节奏和用词，不要照抄，不要把这些内容当成本次通话发生过的事）：")
        out += [f"对方：{x['scammer']}\n你：{x['reply']}" for x in pick[:_SHOTS_MAX]]
    return out


# ---- 不抢话：人设只接对方已经说过的话（俊杰 10-19：小林在“杀猪盘”里对方没提投资就问“哪个投资平台”）----
# 话题词表只在语音侧用来门控意图和挑例句，不改共享的话术识别（python/deepsuck/tactics）。
TOPICS = {
    "url": re.compile(r"网址|网站|网页|链接|官网|平台|APP|[Aa]pp|软件|下载|安装|二维码|小程序|http|www\.|\.com|会议号|共享屏幕|屏幕共享"),
    "bank": re.compile(r"卡号|银行|账户|账号|户名|开户行|转账|转到|转给|转过来|汇款|打款|打钱|收款|付款|充值|保证金|手续费|垫付|垫|入金|流水|对公"),
    "wallet": re.compile(r"钱包|USDT|usdt|泰达|比特币|以太坊|币安|虚拟币|加密货币|数字货币|充币|链上|U币"),
    "phone": re.compile(r"电话|手机号|号码|微信|QQ|qq|加我|加一下|联系方式|私聊|Telegram|TG|飞机号|WhatsApp|专线"),
    "invest": re.compile(r"投资|理财|收益|回报|带单|导师|渠道|炒币|炒股|股票|基金|盈利|翻倍|稳赚"),
}
INTEL_TOPIC = {"bank_card": "bank", "url": "url", "phone": "phone", "qq": "phone", "wechat": "phone", "alipay": "bank",
               "email": "phone", "name": "bank"}
GOAL_TOPIC = {"bank": "bank", "name": "bank", "url": "url", "wallet": "wallet", "phone": "phone"}
# 有前提的意图：前提不满足时退回中性意图。话题来自对方说过的话，话术来自 Session.tactic_counts（整通累计）。
NEEDS_TOPIC = {"elicit_url": "url", "elicit_account": "bank", "elicit_wallet": "wallet", "elicit_contact": "phone",
               "fake_progress": "bank"}
NEEDS_TACTIC = {"otp_stall": ("otp",), "greedy": ("high_return",), "romance": ("romance",), "secrecy": ("secrecy",),
                "task_stall": ("task_rebate",), "loan_stall": ("loan_fraud",), "campus_stall": ("campus_loan",),
                "verify_identity": ("acquaintance",), "scared": ("authority", "threat", "kidnap"),
                "coop_step": ("transfer", "safe_account", "app_download", "screen_share", "otp", "task_rebate",
                              "loan_fraud", "campus_loan", "info_harvest", "crypto"),
                "urgency_stall": ("urgency", "transfer", "safe_account", "otp", "app_download")}
NEUTRAL = ("generic", "ask_repeat", "misunderstand", "tech_trouble", "slow_walk")


def topics_in(text: str) -> set:
    t = str(text or "")
    return {k for k, r in TOPICS.items() if r.search(t)}


def session_topics(session) -> set:
    """本通电话里对方已经提到过的话题（对方的话 + 已抽到的情报类型）。"""
    out: set = set()
    for m in getattr(session, "messages", []):
        if m.get("role") == "scammer":
            out |= topics_in(m.get("text", ""))
    for i in getattr(session, "intel", {}).values():
        typ = i.get("type", "")
        out.add("wallet" if typ.startswith("crypto_") else INTEL_TOPIC.get(typ, ""))
    out.discard("")
    return out


def gate_intent(intent: str, session) -> str:
    """意图门控：套情报类意图只在对方已经提到平台/链接/账户/转账/联系方式后才用，其他有前提的意图同理；
    否则退回中性意图（generic，上一轮已经是 generic 就用 slow_walk）。"""
    topics = session_topics(session)
    tactics = set(getattr(session, "tactic_counts", {}) or {})
    ok = True
    if intent in NEEDS_TOPIC:
        ok = NEEDS_TOPIC[intent] in topics
    elif intent in NEEDS_TACTIC:
        ok = bool(tactics & set(NEEDS_TACTIC[intent]))
    elif intent in ("confirm_intel", "re_ask"):
        ok = bool(getattr(session, "intel", None)) or intent == "re_ask"
    if ok:
        return intent
    return "slow_walk" if getattr(session, "last_intent", None) == "generic" else "generic"


# 电话是机器人先开口：网页文字版的开场白（personas.json openings）是回骗子第一条消息的，按场景写，
# 例如“客服？哪个订单”“是哪个平台开的”。语音里对方还没开口，开场只能是接电话的那一声。
# 每个人设接电话的那一声同样只在 personas/voice_traits.yaml（字段 opening）里写，运行时读取；没写的人设用默认的“喂？哪位”。
VOICE_OPENINGS = load_voice_openings()


def voice_opening(session) -> dict:
    lst = VOICE_OPENINGS.get(session.persona["id"]) or ["喂？哪位"]
    return session.record_bot(lst[int(session.rng() * len(lst)) % len(lst)], "opening")


# #73：号码规则里不放具体数字当例子（原来是“尾号8600是吧…”“幺三零…”，qwen3.7-flash 被问尾号时会把 8600 原样说出来）。
# 提示词里任何地方都不要写具体号码；要举例就用“后四位”“开头几位”这类说法（voice/tests/test_digit_leak.py 会检查）。
RULE_DIGITS = ("5. 号码只复述对方自己报过的一部分：只说对方报的那串号码的后四位，或者只说开头几位、后面就说“后面是多少来着”；"
               "不要念星号，不要把整串号码念全，也不要自己编号码。问到你自己的卡号、尾号、手机号、验证码，"
               "就说找不到、记不清、要去翻一下，不报号码。")

NO_LEAK_RULE = "你不知道对方打电话来干什么，只接对方已经说过的话；对方没提到的事一概不先提，也不要猜对方的目的。"
# #64：每通电话人设的第一条回复不抢着反问（qwen3.7-flash 18 通里 17 通第一句就是问句，林姐还顺嘴问出了对方没提的事）
FIRST_TURN_RULE = ("这是对方开口说的第一段话。你这一条的第一句只是应一声、接住对方的话，是陈述句，句尾用句号，"
                   "不带问号，也不用“啊？”收尾，格式像“哦…是我。”“嗯，衣服的事啊。”“哦…卡的事啊。”“嗯，交朋友啊。”；"
                   "第一句里不要把对方的词重复一遍再问（不要“衣服？”“卡？”这种）。"
                   "第二句可以不说；要问（包括上面建议策略里的追问）都放到第二句，只问对方刚才那段话里亲口说过的词，"
                   "不问对方是从哪儿、怎么找到你的。")
_Q = re.compile(r"[？?]")
_SENT = re.compile(r"[^。？！?!；;\n]+[。？！?!；;]*")


def first_sentence_is_question(text: str) -> bool:
    m = _SENT.search(str(text or "").strip())
    return bool(m and _Q.search(m.group(0)))


def system_prompt(persona_id: str = "wang", scenario_id: str = "refund", hint: str = "opening", missing=None,
                  said_first: str = "", topics=None, first_turn: bool = False) -> str:
    """语音人设提示词。场景名和描述不进提示词（只给后台分析和看板用）；scenario_id 只决定称呼和例句。
    missing：对方已经提到、但还没说清楚的情报（调用方按话题过滤，见 IntelProcessor.update_prompt）。
    topics：对方已经提到的话题（session_topics）；None 表示不过滤例句（离线工具用）。
    first_turn：对方刚说完第一段话（本通电话人设的第一条回复），加 FIRST_TURN_RULE。"""
    p = PERSONA_BY_ID.get(persona_id) or PERSONAS[0]
    s = SCENARIO_BY_ID.get(scenario_id) or SCENARIOS[0]
    call = p["call"].get(s["id"], "")
    miss = "对方已经提到、但还没说清楚的：" + "、".join(missing) + "，可以顺着问一句。" if missing else ""
    return "\n".join([
        '你在一个反诈骗研究项目中扮演"潜在受害人"，接到一个陌生电话。目标：尽可能拖延对方时间；对方自己报出来的东西，再顺着让对方说清楚。',
        f"角色：{p['name']}，{_AGE.sub('', p['tagline'])}。称呼对方为\"{call}\"。",
        NO_LEAK_RULE,
        f"本轮建议策略：{INTENT_HINTS.get(hint, INTENT_HINTS['generic'])}。{miss}",
        "硬性规则：",
        "1. 这是语音通话：只说简体中文口语，一次 1–2 句、不超过 50 字；不要用表情、括号动作、列表或 Markdown；语气词偶尔用“嗯”“啊？”就够了。",
        "2. 保持人设，不要出戏，不要承认自己是 AI 或机器人。",
        "3. 绝不说出任何真实或看似真实的验证码、卡号、密码、身份证号、住址；需要时就说找不到、没弄好、要再确认一下。",
        "4. 绝不真的转账或承诺已经转账成功；不辱骂、不威胁、不包含违法内容。",
        RULE_DIGITS,
        STYLE_RULE,
    ] + voice_style(p, s["id"], topics, first_turn) + ([f"本轮你已经先随口应了一声“{said_first}”，接下来直接接着说正事，开头不要再用嗯、啊、哎、哦之类的语气词，"
          "也不要重复这句。"] if said_first else []) + ([FIRST_TURN_RULE] if first_turn else []))


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
