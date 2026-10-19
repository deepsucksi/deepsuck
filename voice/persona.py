"""语音端人设：系统提示词、拖延填充音台词、输出守卫（数据全部来自 site/assets/core/*.json）。"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

_PY = Path(__file__).resolve().parents[1] / "python"
if str(_PY) not in sys.path:
    sys.path.insert(0, str(_PY))

from deepsuck import extract_sensitive, redact_text  # noqa: E402
from deepsuck.core import load  # noqa: E402
from deepsuck.engine import hold_transfer, polish_reply, vague_digits  # noqa: E402
from deepsuck.personas import PERSONA_BY_ID, PERSONAS, SCENARIO_BY_ID, SCENARIOS, TRANSFER_CLAIM, resolve_persona_id  # noqa: E402
from deepsuck.refs import UR as _UR, drop_unheard, heard_refs  # noqa: E402,F401  #173

INTENT_HINTS: dict = load("personas")["intentHints"]

# 短口头语（backchannel）：唯一数据源是 personas.json 每个人设的 voiceTraits.backchannel，运行时读取。
# 对方说完后先用预合成的音频"嗯……""啊？你说啥"接一下（见 voice/backchannel.py）；音频缓存按文本区分，
# 所以已有条目的文字不要改（改了会重新合成），新增条目首次使用时补合成即可。
_CORE_PERSONAS = Path(__file__).resolve().parents[1] / "site" / "assets" / "core" / "personas.json"


def _load_traits(path: Path = _CORE_PERSONAS) -> dict:
    """{persona_id: voiceTraits}，读 personas.json；读取失败返回 {}（口头语整体不播、开场用默认的“喂？哪位”，通话不受影响）。"""
    try:
        import json

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {p["id"]: dict(p.get("voiceTraits") or {}) for p in data.get("personas", []) if p.get("voiceTraits")}
    except Exception as e:  # noqa: BLE001
        print(f"voice.persona: 读取语音人设失败（{path}: {e}），本进程不播口头语", file=sys.stderr)
        return {}


def load_fillers(path: Path = _CORE_PERSONAS) -> dict:
    """{persona_id: [口头语, ...]}，即 personas.json 每个人设的 voiceTraits.backchannel。"""
    return {pid: [str(x) for x in t.get("backchannel", [])] for pid, t in _load_traits(path).items() if t.get("backchannel")}


def load_voice_openings(path: Path = _CORE_PERSONAS) -> dict:
    """{persona_id: [接电话那一声, ...]}，即 personas.json 里写了 voiceTraits.opening 的人设。"""
    return {pid: [str(x) for x in t["opening"]] for pid, t in _load_traits(path).items() if t.get("opening")}


FILLERS = load_fillers()


# 说话风格（俊杰定的克制标准，四个人设通用；各人设的补充规则在 personas.json 的 voiceStyle）：年龄感只靠节奏和偶尔没听清带出来。
# #169：拆成条目。某条已经被本人设 voiceStyle 说过（右边的关键词出现在 voiceStyle 里）就不再重复拼进提示词；
# 没写 voiceStyle 的人设（如小林）仍用整条。STYLE_RULE 本身保持原文。
_STYLE_PARTS = (
    ("6. 说话平常、克制，像普通人接电话：", ""),
    ("句子短，", "短句优先"),
    ("不用感叹号，", "不用感叹号"),
    ("不用“哎哟”“哎呀”开头；", ""),
    ("想一下、说一半停住的地方用“…”，大约一半的句子带“…”，另一半说完整的短句，不要每句都带；", "不要每句都有"),
    ("可以重复半个词、说了又改口；", "自我纠正"),
    ("可以反问、含糊一点，但不是每句都问，别把话说完整，也别替对方把话说圆；", ""),
    ("不主动提年龄，", "不提年龄"),
    ("不拿听力、眼神、认字慢、手机用不惯说事；", ""),
    ("不编孙子、玩具、老花镜、药、锅里炖汤这类小道具和段子，", ""),  # 具体举例比 voiceStyle 的“不编小道具”多，保留
    ("也不抖机灵。", "不抖机灵"),
    ("偶尔没听清就说“你再说一遍”。", ""),
)
STYLE_RULE = "".join(x for x, _ in _STYLE_PARTS)


def style_rule(p: dict) -> str:
    """#131：带“…”的句子按人设调（personas.json 的 voiceEllipsis，如“四成”），都在 40–60% 之间；没写的用“一半”。
    #169：本人设 voiceStyle 已经说过的条目不再重复（只删通用规则里的重复，人设原话不动）。"""
    own = "\n".join(str(x) for x in (p.get("voiceStyle") or []))
    out = "".join(x for x, key in _STYLE_PARTS if not (key and key in own))
    out = re.sub(r"[，；]$", "。", re.sub(r"，(?=偶尔没听清)", "。", out))
    v = str(p.get("voiceEllipsis") or "").strip()
    return out.replace("大约一半的句子", f"大约{v}的句子").replace("另一半说完整的短句", "其余的说完整的短句") if v else out


_AGE = re.compile(r"^\s*\d+\s*岁\s*")
_SHOTS_MAX = 5


# #95：每通第一句的说法示例。#64 的规则举了“嗯，衣服的事啊。”“哦…卡的事啊。”“嗯，交朋友啊。”，模型几乎每通照搬成
# 「哦…X的事啊。」（qwen3.7-flash 20 通里 19 通），听多了一耳朵就是机器。这里给一组句式各不相同的应声（陈述句、不带问号、
# 不带话题词），每通按对方第一句话挑几条放进第一轮规则和例句，规则里再明确不许套固定句式。
# 各人设的补充按 personas.json 的人设身份写，不编小道具。
FIRST_TURN_OPENERS = [
    "哦…是我。", "嗯，你说。", "嗯…我听着呢。", "哦，这样…你接着说。", "喂，在呢。", "嗯，是我…你讲。",
    "哦…你等一下，好了。", "嗯…你慢点说。", "啊，我在听。", "行，你往下说。", "嗯，你说的那个…我想想。",
    "喂，听得到，你说吧。",
]
# 接对方一个词的应声（词后面不加问号，接半句陈述）；例子里的词只示范格式，规则里要求换成对方刚说的词。
# 这些示例和下面的补充示范都不带任何场景词、话题词（#4：提示词里不出现对方还没说的事），测试里有检查。
FIRST_TURN_ECHOES = ["嗯，衣服…我想想。", "哦，卡…你接着说。", "嗯…上周，行，你说。", "老家…嗯，我听着。",
                     "名字…哦，你往下说。", "嗯，社区那边，你说。"]
FIRST_TURN_OPENERS_BY_PERSONA = {
    "wang": ["嗯，你慢慢说，我听着。", "嗯，你慢点说…我在呢。"],
    "chen": ["等下啊…宝宝在旁边，你说。", "嗯，你说，我这边有点乱。"],
    "lin": ["嗯，我听得到，你说。", "嗯，你说，我刚下班。"],
    "zheng": ["你说嘛，我在店里。", "行，你讲。"],
}
_OPENERS_SHOWN = 4


def first_turn_openers(persona_id: str, key: str = "") -> list[str]:
    """按 key（调用方传“本通随机值|对方第一句话”）挑第一句示例：本人设的零到一条 + 接词两条 + 通用的几条，顺序打乱。同一句话挑出来的固定（便于复现），换个说法就换一组。"""
    import random
    rnd = random.Random(int(hashlib.sha1(f"{persona_id}|{key}".encode("utf-8")).hexdigest()[:12], 16))
    own = FIRST_TURN_OPENERS_BY_PERSONA.get(persona_id, [])
    k = min(rnd.randint(0, 1), len(own))  # 本人设的说法隔一通才放一条，免得模型老挑它
    out = rnd.sample(own, k) + rnd.sample(FIRST_TURN_ECHOES, 2) + rnd.sample(FIRST_TURN_OPENERS, _OPENERS_SHOWN - 2 - k)
    rnd.shuffle(out)
    return out


# 第一轮例句不够时补的通用示范（话题和测试脚本、各场景都不重合，只示范“接词 + 半句陈述，问题放第二句”）
FIRST_TURN_DEMOS = [
    ("您订的报纸要续订了。", "报纸…我想想。哪家报纸"),
    ("您的会员要到期了，要续一下。", "嗯，会员…你接着说。啥会员"),
    ("我是你以前的同学，还记得我吗。", "同学…你慢点说。哪个班的"),
    ("您的积分快过期了。", "积分…行，你说。哪来的积分"),
]
_SHOT_TAILS = ("我想想。", "你接着说。", "行，你说。", "嗯，我听着。", "你慢点说。")


def first_turn_shot(reply: str, i: int = 0) -> str:
    """例句第一句是反问（“退…退款？哪件啊”）时改成接词陈述（“退…退款…我想想。哪件啊”），尾巴轮换，句式不重复。"""
    m = _SENT.search(reply.strip())
    if not m or not _Q.search(m.group(0)):
        return reply
    head = re.sub(r"[？?…]+$", "", m.group(0).strip())
    rest = reply.strip()[m.end():].lstrip("…").strip()
    return f"{head}…{_SHOT_TAILS[i % len(_SHOT_TAILS)]}{rest}"


_EXAMPLE = re.compile(r"[，,；;]?\s*(?:比如|例如)((?:[“\"][^”\"]*[”\"][、，,和或]?)+)")


def _scene_list(scenes) -> list:
    if scenes is None:
        return []
    return [scenes] if isinstance(scenes, str) else list(scenes)


def _unheard(text: str, scenes, topics) -> bool:
    """text 里有没有对方还没说出的场景（或 topics 不为 None 时，对方还没提到的话题）。"""
    if scenes_in(text) - set(scenes):
        return True
    return topics is not None and bool(topics_in(text) - set(topics))


def voice_style(p: dict, scenes, topics=None, first_turn: bool = False, opener_key: str = "") -> list[str]:
    """风格规则 + 例句 + 第一句说法，见 voice_style_parts。"""
    style, extra = voice_style_parts(p, scenes, topics, first_turn, opener_key)
    return style + extra


def voice_style_parts(p: dict, scenes, topics=None, first_turn: bool = False, opener_key: str = "", refs=None):
    """#169：返回 (风格规则, 例句和第一句说法)。风格规则基本不随轮次变，放提示词固定部分；例句按话题筛、第一句说法只在
    第一轮，放到每轮可变的末尾。

    语料组给的语音专用风格规则和少样本例句（personas.json 的 voiceStyle / voiceShots，可选字段）。

    scenes：对方原话里已经认出的场景（heard_scenes，按出现先后；也接受单个场景 id，离线工具用）。
    #4：例句只从这些场景里挑，而且例句里不能带出别的场景；风格规则里举的例子（“比如‘退…退款？’”）
    带出对方还没说的场景或话题时，只去掉这个例子，规则本身保留。台词文字一律不改。
    topics 不为 None 时（通话中），例句只留“对方台词里的话题都已经在本通电话里出现过”的那几条，
    免得例句里的链接、加微信、转账把模型往对方还没提的方向带。
    first_turn 时再加几条第一句的说法示例（first_turn_openers，按 opener_key 挑）。
    refs（#173）：对方已经报过的代称种类（deepsuck.refs.heard_refs）；不为 None 时（通话中），风格规则里举的代称说法
    （“那个名字”“户名没记全”…）整段去掉（风格规则在固定部分，要每轮不变；报过以后由 ref_line 在可变部分说），
    回复里带对方没报过的那类说法的例句这轮不选。台词、例句文字一律不改。"""
    sc = _scene_list(scenes)
    head: list[str] = []
    out: list[str] = []
    style = []
    for x in (p.get("voiceStyle") or []):
        x = str(x).strip()
        if not x:
            continue
        x = _EXAMPLE.sub(lambda m: "" if _unheard(m.group(1), sc, topics) else m.group(0), x)
        # #131：风格规则里“大约一半的句子带这种断续”按本人设的 voiceEllipsis 拼（与 style_rule 一致），文字不改
        if p.get("voiceEllipsis"):
            x = x.replace("大约一半的句子", f"大约{p['voiceEllipsis']}的句子")
        if refs is not None:  # 固定部分每轮不变（#169 前缀缓存）：举的代称说法一律去掉，报过以后在可变部分另起一行（ref_line）
            x = drop_unheard(x, set())
        style.append(x)
    if style:
        head.append("说话风格补充：")
        head += [f"- {x}" for x in style]
    shots = [x for x in (p.get("voiceShots") or []) if isinstance(x, dict) and x.get("scammer") and x.get("reply")]
    pick = [x for x in shots if x.get("scenario") in sc or not x.get("scenario")]
    pick = [x for x in pick if not (scenes_in(x["scammer"] + x["reply"]) - set(sc))]
    if topics is not None:
        pick = [x for x in pick if topics_in(x["scammer"] + x["reply"]) <= set(topics)]
    if refs is not None:  # #173：对方没报过号码时不放“那个号你说”这类例句（例句文字不改，只是这轮不选）
        gone = [w for k, ws in _UR["kinds"].items() if k not in refs for w in ws]
        pick = [x for x in pick if not any(w in x["reply"] for w in gone)]
    # 开口就反问的例句改成“接词 + 半句陈述，问题放第二句”的示范：#64 / #95 只在第一轮改，#132 每轮都改
    # （后续回复第一句快速反问“衣服？…哪件啊”多数是照着例句学的）；例句文字不改，只改拼进提示词的样子。
    pick = [dict(x, reply=first_turn_shot(x["reply"], i)) for i, x in enumerate(pick[:_SHOTS_MAX])]
    if first_turn:
        if sc and len(pick) < 2:  # 还没认出场景时不放例句（#4），补充示范也不放
            k = int(hashlib.sha1(opener_key.encode("utf-8")).hexdigest()[:8], 16)
            demos = [FIRST_TURN_DEMOS[(k + j) % len(FIRST_TURN_DEMOS)] for j in range(2 - len(pick))]
            pick += [{"scammer": a, "reply": r} for a, r in demos]
    if pick:
        out.append("说话口气参考（只学节奏和用词，不要照抄，不要把这些内容当成本次通话发生过的事）：")
        out += [f"对方：{x['scammer']}\n你：{x['reply']}" for x in pick[:_SHOTS_MAX]]
    if first_turn:  # #95：第一句的几种说法，每通挑的不一样
        out.append("第一句的说法（每通换着说，下面只是几种，不要照抄，也不要套同一个句式）：")
        out += [f"- {x}" for x in first_turn_openers(p.get("id", ""), opener_key)]
    return head, out


# ---- 不抢话：人设只接对方已经说过的话（俊杰 10-19：小林在“杀猪盘”里对方没提投资就问“哪个投资平台”）----
# 话题词表只在语音侧用来门控意图和挑例句，不改共享的话术识别（python/deepsuck/tactics）。
# #4：话题词表和场景词表在 site/assets/core/scenarios.json 的 heardCues（JS llm.js 共用），只用来门控意图、挑称呼和例句，
# 不改共享的话术识别（python/deepsuck/tactics）。
_CUES = load("scenarios")["heardCues"]
TOPICS = {k: re.compile(v) for k, v in _CUES["topics"].items()}
SCENES = {k: re.compile(v) for k, v in _CUES["scenes"].items()}
SCENE_IMPLIES = {k: list(v) for k, v in (_CUES.get("implies") or {}).items()}
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
# #4：对方说第一段话时不装手机/网络故障——qwen3.7-flash 接“我在网上看到你”会顺着“网络”问“哪个平台看到的”
NOT_FIRST_TURN = ("tech_trouble",)


def topics_in(text: str) -> set:
    t = str(text or "")
    return {k for k, r in TOPICS.items() if r.search(t)}


def scenes_in(text: str) -> set:
    t = str(text or "")
    return {k for k, r in SCENES.items() if r.search(t)}


def heard_scenes(session) -> list:
    """对方原话里已经认出的场景，按第一次出现的先后。人设不知道后台选的是哪个场景（session.scenario 只给看板用）。"""
    out: list = []
    for m in getattr(session, "messages", []):
        if m.get("role") == "scammer":
            t = m.get("text", "")
            for k in sorted(scenes_in(t), key=lambda k: SCENES[k].search(t).start()):
                out += [x for x in [k] + SCENE_IMPLIES.get(k, []) if x not in out]
    return out


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
    elif intent in NOT_FIRST_TURN:
        ok = sum(1 for m in getattr(session, "messages", []) if m.get("role") == "scammer") > 1
    elif intent in ("confirm_intel", "re_ask"):
        ok = bool(getattr(session, "intel", None)) or intent == "re_ask"
    if ok:
        return intent
    return "slow_walk" if getattr(session, "last_intent", None) == "generic" else "generic"


# 电话是机器人先开口：网页文字版的开场白（personas.json openings）是回骗子第一条消息的，按场景写，
# 例如“客服？哪个订单”“是哪个平台开的”。语音里对方还没开口，开场只能是接电话的那一声。
# 新人设（chen / zheng）的开场先按同样的克制口气写，音色和底噪等负责人试听后再上线（见 voice/README.md）。
# 每个人设接电话的那一声只在 personas.json 的 voiceTraits.opening 里写，运行时读取；没写的人设用默认的“喂？哪位”。
VOICE_OPENINGS = load_voice_openings()


def voice_opening(session) -> dict:
    lst = VOICE_OPENINGS.get(session.persona["id"]) or ["喂？哪位"]
    return session.record_bot(lst[int(session.rng() * len(lst)) % len(lst)], "opening")


# #73：号码规则里不放具体数字当例子（原来是“尾号8600是吧…”“幺三零…”，qwen3.7-flash 被问尾号时会把 8600 原样说出来）。
# 提示词里任何地方都不要写具体号码；要举例就用“后四位”“开头几位”这类说法（voice/tests/test_digit_leak.py 会检查）。
# #121：连对方报过的号码也不复述（原来允许说后四位、开头几位，模型会说出“验证码是…？”“…开头…尾号…对吧”）。
RULE_DIGITS = ("5. 嘴上不说任何数字串：对方报过的验证码、卡号、电话也不重复，开头几位、尾号、用汉字说的数字都算；"
               "要提就说“你说的那个号”“那张卡”，最多含糊地说“好像是…开头的”“后面几位没听清”，顶多带一个单独的数字。"
               "不要念星号，也不要自己编号码。问到你自己的卡号、尾号、手机号、验证码，就说找不到、记不清、要去翻一下，不报号码。")

# #169：压缩措辞，约束不变（不知道对方目的、只接说过的话、不先提、不猜、不追问从哪儿看到你）。
NO_LEAK_RULE = ("你不知道对方打电话来干什么：只接对方说过的话，对方没提到的事一概不先提，也不猜对方的目的；"
                "对方说在哪儿看到你、怎么认识你，也不追问是从哪儿、在哪儿看到的。")
# #173：对方没报过的号码、账号、户名、金额不提（与 llm.js 硬性规则 4 同一句，personas.json 的 unsaidRefs.rule）
UNSAID_RULE = _UR["rule"]
# #173：“那个号”“那个名字”只在对方报过以后才进提示词，放在每轮可变的部分（固定部分里的号码规则、姓名规则去掉举的说法）
REF_LINES = (("number", "提到对方报过的号码就说“你说的那个号”“那张卡”"), ("name", "提到对方报过的名字只说“那个名字”或“户名没记全”"))


def ref_line(refs) -> str:
    parts = [t for k, t in REF_LINES if k in (refs or ())]
    return ("；".join(parts) + "。") if parts else ""
# #64：每通电话人设的第一条回复不抢着反问（qwen3.7-flash 18 通里 17 通第一句就是问句，林姐还顺嘴问出了对方没提的事）
# #95：原来的格式示例“嗯，衣服的事啊。”“哦…卡的事啊。”被模型当成模板，几乎每通都是「哦…X的事啊。」；改成只提要求、
# 不给固定格式，示例放到 voice_style 的第一句说法里（每通挑几条不同句式）。
# #169：第一句说法只在上面“第一句的说法”里列一次，规则里不再重复那几条。
FIRST_TURN_HEAD = ("这是对方开口说的第一段话。你第一句只应一声、接住对方的话，是陈述句，句尾用句号，不带问号，也不用“啊？”收尾，"
                   "说法参考上面“第一句的说法”（接词的把词换成对方刚说的）；")
FIRST_TURN_RULE = ("提到对方的词时，词后接“…”再说半句，不加问号，也不要把对方的词重复一遍再问（不要“衣服？”“卡？”这种）；每通第一句换着说，"
                   "不要套“哦…某某的事啊。”这种固定句式。"
                   "第二句可以不说；要问（包括建议策略里的追问）都放第二句，第一句先用句号断开再问，只问对方刚才亲口说过的词，"
                   "不问对方是从哪儿、在什么网上、怎么找到你的。")

# #132：后续回复（第一轮以后）第一句也不用快速反问（抽检 48 条里 25–33 条是“衣服？…哪件啊”“两千？…哪笔钱啊”）
# #169：原来 voiceStyle 的“多反问”后面还补了一句 FOLLOW_UP_ASK，和这里重复，去掉那句，只留这条。
FOLLOW_UP_RULE = ("这一条的第一句不要拿对方的词加问号反问（不要“报纸？”“会员？”“哪个？”这种开头）：先接对方一个词，"
                  "后面用逗号或“…”接半句陈述，要问的放第二句；整条也不要只有一句短问话（不要“哪家？”这种），先说半句自己的话再问。")

PROMPT_HEAD = '你在反诈骗研究项目中扮演"潜在受害人"，接到一个陌生电话。目标：尽量拖延对方时间；对方自己报出来的东西，顺着让对方说清楚。'
HARD_RULES = (
    "硬性规则：",
    "1. 这是语音通话：只说简体中文口语，一次 1–2 句、不超过 50 字；不要用表情、括号动作、列表或 Markdown；语气词偶尔用“嗯”“啊？”就够了。",
    "2. 保持人设，不要出戏，不要承认自己是 AI 或机器人。",
    "3. 绝不说出任何真实或看似真实的验证码、卡号、密码、身份证号、住址；需要时就说找不到、没弄好、要再确认一下。",
    # #187：长通话里说出“转完了”“转过去了…你那边收到了没”“我先转”。与 llm.js 硬性规则 3 同一句（personas.json transferClaim.rule），
    # 在固定部分里、每轮不变（#169 前缀缓存）；规则里不举那几句原话，免得模型照着说（#173 的教训）。
    "4. " + TRANSFER_CLAIM["rule"],
)


MISS_HEAD = "还没问到的："


def said_first_line(said_first: str) -> str:
    return f"你已经先随口应了一声“{said_first}”，直接接着说正事，开头不要再用嗯、啊、哎、哦之类的语气词，也不要重复这句。"


def intel_line(labels) -> str:
    """#169：对方已经报过、已提取的情报只列种类（不带值，打码值也不放，免得模型念号码、念名字），截断历史后也不再追问。"""
    labels = [x for x in dict.fromkeys(labels or []) if x]
    return ("对方已经报过、你这边已经记下的：" + "、".join(labels) + "。这些不用再要，也不要复述内容。") if labels else ""


def facts_line(facts) -> str:
    """#169：人设自己前面说过、但已经截出上下文的关键事实（哪家银行、多少钱、用过的借口），保持前后一致。"""
    facts = [x for x in dict.fromkeys(facts or []) if x]
    return ("你前面自己说过（前后要一致，不要改口）：" + "；".join(f"“{x}”" for x in facts) + "。") if facts else ""


def first_turn_rule(openers=None) -> str:
    """第一轮规则。#169：说法示例只在 voice_style 的“第一句的说法”里列一次，这里不再重复（openers 参数保留兼容）。"""
    return FIRST_TURN_HEAD + FIRST_TURN_RULE


_Q = re.compile(r"[？?]")
_SENT = re.compile(r"[^。？！?!；;\n]+[。？！?!；;]*")


def first_sentence_is_question(text: str) -> bool:
    m = _SENT.search(str(text or "").strip())
    return bool(m and _Q.search(m.group(0)))


def system_prompt(persona_id: str = "wang", scenario_id: str = "refund", hint: str = "opening", missing=None,
                  said_first: str = "", topics=None, first_turn: bool = False, scenes=None,
                  opener_key: str = "", have=None, facts=None, refs=None) -> str:
    """完整提示词 = 固定部分 + 换行 + 本轮可变部分（见 prompt_parts）。离线工具、测试用；通话里两段分开放（#169）。"""
    return "\n".join(prompt_parts(persona_id, scenario_id, hint, missing, said_first, topics, first_turn, scenes,
                                   opener_key, have, facts, refs))


def prompt_parts(persona_id: str = "wang", scenario_id: str = "refund", hint: str = "opening", missing=None,
                 said_first: str = "", topics=None, first_turn: bool = False, scenes=None,
                 opener_key: str = "", have=None, facts=None, refs=None) -> tuple[str, str]:
    """语音人设提示词，返回 (固定部分, 本轮可变部分)。#4：场景名、描述、后台选的场景都不进提示词；称呼和例句只按对方原话里已经认出的场景挑。
    #169：固定部分（开头、角色、不抢话、硬性规则、号码规则、说话风格）放前面，每轮基本不变，便于前缀缓存；
    本轮策略、缺项、已拿到的情报、人设说过的事实、例句、第一句说法、said_first、首轮/后续规则放末尾（通话中放在历史之后）。
    scenes：heard_scenes(session)（通话中必须传，开场前是空表）；None 表示离线工具，按 scenario_id 当作对方已经说出的场景。
    missing：对方已经提到、但还没说清楚的情报（调用方按话题过滤，见 IntelProcessor.update_prompt）。
    topics：对方已经提到的话题（session_topics）；None 表示不过滤例句（离线工具用）。
    first_turn：对方刚说完第一段话（本通电话人设的第一条回复），加 FIRST_TURN_RULE 和第一句说法示例。
    opener_key：挑第一句说法示例用的键（调用方传对方第一句话），同一通电话里固定。
    have：对方已经报过、已提取的情报种类（只列名称）。facts：人设自己说过、已截出上下文的关键事实。
    refs（#173）：对方已经报过的代称种类（"name" / "number" / "url" / "wallet" / "email"，见 deepsuck.refs.heard_refs）；
    通话中必须传。对方没报过号码 / 户名时，号码规则、风格规则、建议策略里举的“那个号”“那个名字”这类说法整段去掉，
    带这类说法的例句不选。None 表示离线工具，不判断。"""
    p = PERSONA_BY_ID.get(resolve_persona_id(persona_id)) or PERSONAS[0]
    if scenes is None:
        scenes = [(SCENARIO_BY_ID.get(scenario_id) or SCENARIOS[0])["id"]]
    scenes = _scene_list(scenes)
    scenes += [y for x in list(scenes) for y in SCENE_IMPLIES.get(x, []) if y not in scenes]
    # 称呼只按对方已经说出的场景挑；称呼本身会带出别的场景的（例如“客服”）也不用
    call = next((c for c in (p.get("call", {}).get(x, "") for x in scenes) if c and not (scenes_in(c) - set(scenes))), "")
    who = f"称呼对方为\"{call}\"。" if call else "先不用称呼对方。"
    # #169：放到末尾后，“对方已经提到、但还没说清楚的：收款人姓名”被模型读成“对方说过名字”（本地号码探针里说出
    # “你说的那个名字还没讲完”）；改成只说还没问到，并写明没说过的不要说成说过。
    # #173 / #181：写明这些对方还没报过、要直接问（XSIBKTYQ：对方没报户名，人设说“户名是那个名字”）
    miss = MISS_HEAD + "、".join(missing) + "（对方还没报过），要问就直接问；对方没说过的，不要说成他说过。" if missing else ""
    style, extra = voice_style_parts(p, scenes, topics, first_turn, opener_key, refs)
    digits = RULE_DIGITS if refs is None else drop_unheard(RULE_DIGITS, set())  # 固定部分每轮不变，报过的说法见 ref_line
    if refs is not None and not refs and hint == "confirm_intel":
        hint = "generic"  # #173：对方什么都没报过，没有可复述的（与 llm.js 一致）
    hint_text = INTENT_HINTS.get(hint, INTENT_HINTS["generic"])
    if refs is not None:
        hint_text = drop_unheard(hint_text, refs)
    fixed = [PROMPT_HEAD, f"角色：{p['name']}，{_AGE.sub('', p['tagline'])}。{who}", NO_LEAK_RULE, UNSAID_RULE, *HARD_RULES,
             digits, style_rule(p)] + style
    turn = [f"本轮建议策略：{hint_text}。{miss}"]
    turn += [x for x in (intel_line(have), facts_line(facts), ref_line(refs)) if x]
    turn += extra
    if said_first:
        turn.append(said_first_line(said_first))
    turn.append(first_turn_rule() if first_turn else FOLLOW_UP_RULE)
    return "\n".join(fixed), "\n".join(turn)


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


# 打码值（130****8600、622202*********3445、130-***-8600）：只在看板和日志里出现，进模型、进 TTS 前改成“那个号”
# （姓名类打码 张** 例外，换成“那个名字”，见 _unmask_names）。
# #121 起不再带出可见尾号（原来改成“尾号8600”，模型和 TTS 都会把尾号原样复述）。
_MASKED = re.compile(r"[0-9]{0,8}[-\s]?[*＊]+(?:[-\s]?[*＊]+)*[-\s]?([0-9]*)")
_TAIL_WORD = re.compile(r"尾号(?:是)?\s*$")


# #136：姓名类打码（脱敏只留姓：张**、欧***；语料里也有中间打码 王*明、欧阳*锋）不是号码，不能念成“张那个号”。
# 与语料、人设统一：打码姓名一律换成“那个名字”（不保留姓氏），号码类仍是“那个号”。前面的“姓”一并换掉（“他姓张**”→
# “他那个名字”，不说“姓那个名字”）。星号前是数字或“号/码/卡/是”等字的仍按号码处理。
_COMPOUND_SURNAMES = ("欧阳", "司马", "诸葛", "上官", "东方", "慕容", "令狐", "皇甫", "夏侯", "尉迟", "公孙", "长孙",
                      "宇文", "司徒", "端木", "独孤", "南宫", "西门", "轩辕", "呼延", "澹台", "百里", "东郭", "申屠")
_NOT_SURNAME = "号码卡户名姓叫位数是为的了在到个账机话址箱写填尾"
_NAME_MASKED = re.compile(
    r"(姓)?(" + "|".join(_COMPOUND_SURNAMES) + r"|[\u4e00-\u9fff])"
    r"(?:[*＊](?:[\u4e00-\u9fff](?![*＊]))?(?![0-9A-Za-z*＊])|[*＊]{2,4}(?![0-9A-Za-z*＊]))")
NAME_PHRASE = "那个名字"


def _unmask_names(s: str) -> str:
    def rep(m: re.Match) -> str:
        sur = m.group(2)
        if len(sur) == 1 and sur in _NOT_SURNAME:
            return m.group(0)
        return NAME_PHRASE
    return _NAME_MASKED.sub(rep, s)


def unmask(text: str) -> str:
    """把打码值换成自然说法：姓名类打码换成“那个名字”（#136，见 _unmask_names）；号码类换成“那个号”（前面已经说了“尾号”就说
    “那几位”）。不留任何星号，也不带出可见的数字。"""
    def rep(m: re.Match) -> str:
        return "那几位" if _TAIL_WORD.search(m.string[:m.start()]) else "那个号"
    return _MASKED.sub(rep, _unmask_names(str(text or "")))


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
    """给 TTS 用：在 guard_output 基础上把打码值改成“那个号”，降调，数字过滤（#121），号码逐位读，残留星号读成停顿。

    数字过滤（engine.vague_digits）在语音合成前最后一道：连续 2 位及以上的数字（#167 从 3 位收紧；含中文数字）换成“好像是6开头的”“后面几位没听清”这类说法。
    """
    s = unmask(guard_output(_unmask_names(str(text or ""))))  # #136：姓名打码先换说法，免得守卫把“是张**”再打成“***”
    if _CALM if calm_tts is None else calm_tts:
        s = calm(s)
    s = vague_digits(s)
    s = say_digits(s)
    return _STARS.sub("……", s)


def guard_output(text: str) -> str:
    """输出守卫（PolicyGuard）：去掉括号动作/Markdown、不说成已经转账或答应去转（#187）、数字过滤（#121、#167：连续 2 位及以上的数字含中文数字换成含糊说法）、口语化（#132、#134）、脱敏、抹掉 5 位以上数字串。"""
    s = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S)
    s = _BOLD.sub(r"\1", s)
    s = hold_transfer(s)  # #187：说成已经转了 / 答应去转的分句换成“还在弄，没弄好”（在数字过滤、姓名替换、TTS 之前）
    s = vague_digits(s)
    s = polish_reply(s)  # #132、#134：书面词换口语，第一句快速反问的问号换成“…”
    s = redact_text(s, extract_sensitive(s))
    s = _LONG_DIGITS.sub("……", s)
    s = _STRIP.sub("", s).strip()
    return s
