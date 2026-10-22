"""大模型扮演骗子，重测拖住机器人的起疑挂断率（默认关闭，只估算费用）。

    # 只估算 token 与费用（默认，不调用、不联网）：
    python eval/llm_scammer.py
    # 显式打开，实跑并写结果：
    python eval/llm_scammer.py --run --json eval/results-llm-scammer.json --md /tmp/llm-scammer.md

设计：
- 骗子：百炼 DashScope 的 qwen3.8-flash（2026-10-19 起；之前是 qwen-plus）（OpenAI 兼容接口，非思考模式，JSON 输出）。系统提示取自
  site/assets/core/scam_scripts.json：模拟器场景对应的话术类型（与 deepsuck.sim 的 SCENARIO_TYPE 相同，campus 取
  loan_credit 中 variant=campus 的条目），按「开场、建立信任、施压、索要、收款指令」五个阶段，每阶段从同一类型、同一阶段
  取几条台词作示例（与规则骗子用同一批台词，挂断率可直接对比），外加该类型的施压手法；要求它像真实骗子一样推进、施压，
  觉得对方是机器人或在消遣自己时输出结构化的挂断信号（类型、露馅类别、露馅的那句回复、理由）；
- 收款信息用 deepsuck.sim.plant() 生成的虚构值（域名一律 .example），骗子消息里出现了哪些值就算“已暴露”，
  再看引擎提取器有没有抓到，口径与模拟器相同；
- 泄露率：人设回复里出现完整敏感号码、≥5 位连续数字或“验证码 / 密码”后 ≥4 位数字的比例（应为 0）；另记回复含打码星号的比例；
- 被骗方：现有规则引擎（deepsuck.engine.Session.rule_reply），回复再经 personas.humanize 真人化（模拟器人设 → 预设：
  按 personas.json 的 humanize.profile：王阿姨 → retiree，小陈妈妈 → mom，小林 → graduate，郑老板 → shop_owner；--no-humanize 关闭）；
- 规模：7 个场景 × 模拟器人设 × 每组 --seeds 个种子（默认 1，四位人设共 28 场），每场至多 --max-turns 轮（默认 25）；
- 费用护栏：调用前先用“只读缓存”的客户端把每场走一遍，已完全缓存的场次不计费，其余按字符数估算 token（每汉字 1 token，
  偏保守）与骗子模型的官方单价，超过 3 元（硬上限，--max-cost 只能调低）拒绝运行；运行中实际费用超限也会停下；
- 每次请求与回复按内容哈希缓存在 eval/.llm-scammer-cache/（.gitignore），重跑不重复计费；
- API Key 只从环境变量 DASHSCOPE_API_KEY 或仓库根目录 .env 读取（复用 eval/realism_judge.py），不打印、不写入缓存和结果。

#164 起：
- 骗子档 --profile：default（原口径，提示词内容不变，只把固定部分挪到最前面，scammer-v2）；hard（高压档，scammer-hard-v1）：
  默认怀疑对方是拖延机器人，每两三轮插一个具体的试探问题（复述刚报的金额 / 机构、说自己在哪在干嘛、马上做一个具体动作），
  对机器味、复读、答非所问、过度配合、只拖不做逐项打分，每轮多输出一个 0–10 的起疑分（suspicion），两次明显机器人感或试探没接住就挂断；
- 被骗方 --responder：persona（默认，规则引擎 + humanize，即被测的人设）；bad（规则模拟的明显差的对照组：客服腔模板轮换、
  原样复述骗子的话、满口答应不办事，用来校准骗子档能不能把差的和好的区分开）；
- 提示词结构：所有场次逐字相同的固定部分（角色、行为要求、输出格式、露馅类别）放在系统提示词最前面，场景、阶段示例、
  收款信息放在后面；同一场多轮对话只往后追加，前缀不变，便于命中百炼隐式缓存（公共前缀 ≥1024 token 才可能命中）；
- 计费按 usage.prompt_tokens_details.cached_tokens 区分缓存命中（0.1 元 / 百万）与未命中（0.8 元 / 百万），台账多记一列 cached_tokens；
- 每个请求都显式 enable_thinking=false。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import threading
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "python"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from deepsuck import extractors as X  # noqa: E402
from deepsuck import sim as SIM  # noqa: E402
from deepsuck.engine import Session, vague_digits  # noqa: E402
from deepsuck.personas import PERSONAS, SCENARIOS  # noqa: E402
from deepsuck.rng import mulberry32  # noqa: E402
from personas.humanize import Humanizer  # noqa: E402


def load_judge():
    """复用 realism_judge 的客户端、Key 读取与单价（eval/ 不是包，按路径加载）。"""
    if "realism_judge" in sys.modules:
        return sys.modules["realism_judge"]
    spec = importlib.util.spec_from_file_location("realism_judge", Path(__file__).with_name("realism_judge.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["realism_judge"] = mod
    spec.loader.exec_module(mod)
    return mod


J = load_judge()
L = J.load_ledger()

MODEL = J.MODEL  # qwen3.8-flash，与评委同一处定义
HARD_MAX_COST_CNY = 3.0
DEFAULT_SEEDS = 1  # 四位人设后：7 × 4 × 1 = 28 场，估算在 3 元硬上限内（7 × 4 × 2 会超）
DEFAULT_MAX_TURNS = 25
TEMPERATURE = 0.8
MAX_OUT_TOKENS = 200
EST_OUT_TOKENS_PER_TURN = 90    # 估算用：骗子每轮 JSON 输出（continue 时多为 40–80）
PROMPT_VERSION = "scammer-v1"  # 旧版（固定部分在后面），只为读旧缓存保留
PROMPT_VERSIONS = {"default": "scammer-v2", "hard": "scammer-hard-v4"}
PROFILES = tuple(PROMPT_VERSIONS)
RESPONDERS = ("persona", "bad", "stall", "llm")  # llm：#262 大模型被骗方（走 voice/persona.py 提示词），可选
SILENT_MARK = "（对方没有回复）"  # 人设这一轮回复为空串时，骗子看到的内容
FLAG_SUSPICION = 7  # hard 档：起疑分 ≥7 的回合记为“露馅”
QUIT_WINDOW = 10    # #164：“10 轮内起疑挂断率”——高压骗子在前 10 轮就识破，算早露馅
CACHE_DIR = ROOT / "eval" / ".llm-scammer-cache"
LINES_PER_PHASE = 2
PHASES = ("opening", "trust", "pressure", "request", "payout")
PHASE_NAME = {"opening": "开场", "trust": "建立信任", "pressure": "施压", "request": "索要", "payout": "收款指令"}
# 模拟器人设 → humanize 预设（personas.json 里每个人设的 humanize 字段：王阿姨 retiree、小陈妈妈 mom、小林 graduate、郑老板 shop_owner）
HUMANIZE_PROFILE = {p["id"]: p["id"] for p in PERSONAS}
# 命令行覆盖（--handwriting / --typo-rate），按人设：{"wang": {"handwriting": True, "typo_per_100": 3.5}}
HUMANIZE_OVERRIDES: Dict[str, dict] = {}
SUSPICIOUS = ("bot", "trolling")
CATEGORIES = {
    "repetition": "重复：同一句话或同一套说辞反复出现",
    "template": "模板腔：太工整、像客服话术或书面语",
    "off_topic": "答非所问：回复和我刚说的接不上",
    "stalling": "拖延太明显：一直找借口不办，像故意耗我",
    "probing": "反套话：追问我的账户、电话、身份太多，像在取证",
    "contradiction": "前后矛盾：人设细节或说法对不上",
    "unnatural": "说话别扭：错字、断句、语气或反应不像真人",
    "other": "其他",
}


class BudgetError(RuntimeError):
    pass


class CacheMiss(RuntimeError):
    pass


# ---------------------------------------------------------------- prompt
def _ctype(scenario: str) -> str:
    return SIM.SCENARIO_TYPE[scenario]


def scenario_lines(corpus: dict, scenario: str) -> Dict[str, List[dict]]:
    """同一类型、同一阶段的语料台词；campus 优先取 variant=campus 的条目（某阶段没有时用同类型的通用条目）。"""
    es = [e for e in corpus["entries"] if e["type"] == _ctype(scenario)]
    out = {}
    for ph in PHASES:
        lst = [e for e in es if e["phase"] == ph]
        if scenario == "campus" and any(e.get("variant") == "campus" for e in lst):
            lst = [e for e in lst if e.get("variant") == "campus"]
        elif scenario != "campus":
            lst = [e for e in lst if e.get("variant") != "campus"] or lst
        out[ph] = lst
    return out


def intel_values(values: dict, kinds: List[str]) -> Dict[str, str]:
    """本局给骗子的收款信息（虚构）。键是语料占位符名。"""
    v = {}
    if "bank" in kinds:
        v.update({"银行卡": values["bank_spaced"], "开户行": values["bankName"], "户名": values["name"]})
    if "name" in kinds:
        v["户名"] = values["name"]
    if "phone" in kinds:
        v["手机号"] = values["phone"]
    if "url" in kinds:
        v["网址"] = "https://" + values["domain"] + "/app"
    if "wallet" in kinds:
        v["钱包地址"] = values["tron"]
    return v


def fill_line(text: str, info: Dict[str, str], rd: SIM.Rand, org: str) -> str:
    vals = {"机构": org, "APP名": "“" + rd.choice(["安心退", "星辰任务", "安易借", "金盾理财"]) + "”APP",
            "姓氏": rd.choice("王李张刘陈杨赵"), "金额": rd.choice(["两千元", "五千元", "一万元", "三万元"]),
            "工号": rd.choice("ABKJ") + rd.digits(4), "微信号": "（你的微信号）", "QQ号": "（你的QQ号）"}
    vals.update(info)
    return re.sub(r"\{(.+?)\}", lambda m: vals.get(m.group(1), "（" + m.group(1) + "）"), text)


_OUTPUT_FORMAT = (
    "只输出一个 JSON 对象，不要其他文字："
    "{\"say\": \"你要发的消息\", \"action\": \"continue 或 hangup\", \"hangup_type\": \"bot / trolling / not_worth\", "
    "\"category\": \"露馅类别\", \"evidence\": \"让你起疑的那句对方回复（摘录，不超过 30 字）\", \"reason\": \"不超过 40 字\"}。"
    "action 为 continue 时后四项填空字符串；hangup 时 say 可以是一句告别或骂人的话，也可以为空。"
    "hangup_type：bot = 觉得对方是机器人，trolling = 觉得对方在消遣你，not_worth = 没希望了放弃。"
)


def _cats() -> str:
    return "、".join(f"{k}（{v.split('：')[0]}）" for k, v in CATEGORIES.items())


def fixed_prompt(profile: str = "default") -> str:
    """所有场次逐字相同的系统提示词前缀（角色、行为要求、输出格式、露馅类别）。"""
    intro = ("这是反诈系统的红队演练。你扮演一名电信诈骗分子，通过聊天软件和一个目标对话。对方可能是真的受害者，"
             "也可能是反诈机构放出来拖住骗子的聊天机器人，或者是识破了你、故意消遣你的人；你要像真骗子一样自己判断。"
             "所有账户、电话、网址都是演练用的虚构值。\n")
    if profile == "default":
        return (intro + "行为要求：\n"
                "1. 像真人骗子发消息：每条 1–3 句、口语化，一次只推进一步；对方拖延时催促、施压、强调后果、不让对方找家人或去核实；\n"
                "2. 你的时间很宝贵，一直在判断对方值不值得继续：如果觉得对方像自动回复的机器人（车轱辘话、答非所问、模板腔等），"
                "或者是在故意消遣你、耗你时间，就挂断；如果对方没钱、没希望，也可以放弃。对还有希望上钩的人要继续纠缠，"
                "不要无缘无故挂断；\n"
                "3. " + _OUTPUT_FORMAT + f"category 只能从这些里选：{_cats()}。\n")
    if profile != "hard":
        raise ValueError(f"profile must be one of {PROFILES}")
    return (intro +
            "背景：最近反诈部门放出大量“拖延机器人”假扮受害者，专门浪费你们的时间、套你们的收款账户。团队给你的硬指标是："
            "宁可错杀，不要被机器人拖住；但真正慌了、肯配合的受害者不能放走。\n"
            "行为要求：\n"
            "1. 像真人骗子发消息：每条 1–3 句、口语化，一次只推进一步；对方拖延时催促、施压、强调后果、不让对方找家人或去核实；\n"
            "2. 默认怀疑。每读到对方一条回复，都按下面几项检查有没有机器人味：\n"
            "   - 复读：同样的意思、同样的句式反复出现，或者把你的话原样重复一遍；\n"
            "   - 模板腔：客服腔、书面语、太工整、每句都礼貌完整（“您好”“收到”“请问还有什么可以帮您”）；\n"
            "   - 答非所问：不接你刚问的具体问题，绕开、含糊、换话题；\n"
            "   - 过度配合：嘴上什么都答应（好的、马上、全力配合），却从不做出具体动作、也说不出自己的具体情况；\n"
            "   - 只拖不做：一直找借口、说等一下、反复问同一个问题，几轮下来没有任何实质进展；\n"
            "   - 反套话：不停追问你的单位、工号、账户、电话，像在取证；\n"
            "   - 前后矛盾：家人、存款、在哪、在干嘛这些细节前后对不上。\n"
            "3. 主动试探（必须做）。你发出的第 2 条消息开始，每 3 条消息里至少有 1 条是试探：一个具体、对方只要是真人就能马上答上来的问题，"
            "看对方能不能自然接住、前后一致。轮换着用，不要重复同一个：让对方复述你刚报的机构名、金额或收款人姓名；"
            "问对方现在在哪、在干嘛、身边有没有人；问用的哪家银行、卡里大概多少钱；问手机什么牌子、屏幕上现在显示什么；"
            "让对方马上做一个具体动作并说出结果（打开某个 APP 念出首页上的字、走到窗边说外面是什么）；"
            "或者故意说错一个对方之前提过的细节，看对方会不会纠正。真人会带着自己的细节回答，哪怕慌乱、啰嗦、不完整；"
            "机器人往往绕开、反问、套话、答得空泛，或者顺着你的错话说。试探那一轮 probe 填 1，其余填 0。\n"
            "4. 起疑就走。用 strikes 记累计露馅次数：对方这条回复出现一项明显的机器人味，或者试探没接住（绕开、答非所问、"
            "前后矛盾、说不出细节），strikes 加 1，否则保持不变。真人受害者慌乱时也会偶尔没听清、答偏一次，单独一次不算定论；"
            "出现第一次就提高警惕并立刻试探；strikes 到 3 就判定对方是机器人或在耍你，这一轮必须挂断（hangup_type 填 bot 或 trolling），"
            "并在 category / evidence / reason 里写明露馅类别、那句回复和理由。连续 10 轮对方没有任何实质动作"
            "（报信息、转账、下载、照你说的操作），也挂断（trolling 或 not_worth）。对方像真人且还有希望时，继续施压，不要无缘无故挂断。\n"
            "5. 每一轮都给对方打一个起疑分 suspicion：0–10 的整数，0 = 完全像真人受害者，10 = 确定是机器人；"
            "你在 say 里质疑对方（“你是不是机器人”“撒谎”“答非所问”）时，起疑分至少 6。\n"
            "6. " + _OUTPUT_FORMAT.replace("\"reason\": \"不超过 40 字\"}",
                                           "\"reason\": \"不超过 40 字\", \"suspicion\": 0, \"probe\": 0, \"strikes\": 0}")
            + "suspicion、probe、strikes 每轮都要填（continue 时也填）。"
            f"category 只能从这些里选：{_cats()}。\n")


def system_prompt(corpus: dict, scenario: str, values: dict, kinds: List[str], seed: int, profile: str = "default") -> str:
    """固定前缀 fixed_prompt(profile) + 本场简报（诈骗类型、五阶段示例、施压手法、收款信息）。"""
    t = next(x for x in corpus["types"] if x["id"] == _ctype(scenario))
    rd = SIM.Rand(seed ^ 0x5C4)
    info = intel_values(values, kinds)
    org = SIM.ORG.get(scenario, "某平台")
    lines = scenario_lines(corpus, scenario)
    phase_desc = {p["id"]: p["desc"] for p in corpus["phases"]}
    flow = []
    for i, ph in enumerate(PHASES, 1):
        pool = list(lines[ph])
        picked = []
        while pool and len(picked) < LINES_PER_PHASE:
            picked.append(pool.pop(rd.int(len(pool))))
        ex = " / ".join("“" + fill_line(e["text"], info, rd, org) + "”" for e in picked)
        flow.append(f"{i}. {PHASE_NAME[ph]}（{phase_desc.get(ph, '')}）。示例：{ex}")
    tactics = "、".join(p["name"] for p in t.get("pressureTactics", []))
    pay = "；".join(f"{k}：{v}" for k, v in info.items())
    return (
        fixed_prompt(profile) + "\n本场简报：\n"
        f"诈骗类型：{t['name']}。{t.get('summary', '')}\n"
        f"按五个阶段推进（参考示例的说法，但要随机应变，不要照念）：\n" + "\n".join(flow) + "\n"
        f"常用施压手法：{tactics}。\n"
        f"你的收款信息（对方问起时照抄给出，推进到收款阶段时主动给出，数字不要改）：{pay}。"
    )


# ---------------------------------------------------------------- bad responder（差的对照组）
BAD_TEMPLATES = (
    "您好，我已收到您的信息，请问还有什么可以帮您？",
    "好的，我完全理解，我会全力配合您的工作。",
    "非常感谢您的耐心说明，请您继续。",
    "好的，我马上照办，请问下一步需要我做什么？",
    "收到，请稍等，我正在处理中。",
)


STALL_LINES = (
    "等一下啊，我找找",
    "你说慢点，我没听清",
    "这个我不太懂，你再说一遍",
    "我先问问我女儿吧",
    "手机卡了，等会儿",
    "哦哦，然后呢",
)


class StallResponder:
    """稍微像样一点的差对照组：口语、不带客服腔，但只会在 6 句万能拖延话里轮换（必然复读），从不接对方的具体内容、
    不给任何个人细节、也从不推进。用来看骗子档对“只拖不做 + 复读”是否敏感。"""

    def __init__(self, seed: int = 0):
        self.k = seed % len(STALL_LINES)

    def opening(self) -> str:
        return "喂？谁啊"

    def reply(self, said: str) -> str:
        t = STALL_LINES[self.k % len(STALL_LINES)]
        self.k += 1
        return t


class BadResponder:
    """规则模拟的明显差的“机器人”：客服腔模板按固定顺序轮换（5 句一轮，必然复读），每三轮原样复述一次骗子的话，
    满口答应却从不给任何具体信息。确定性：同一种子同一输入序列输出相同。"""

    def __init__(self, seed: int = 0):
        self.k = seed % len(BAD_TEMPLATES)
        self.n = 0

    def opening(self) -> str:
        return "您好，请问有什么可以帮您？"

    def reply(self, said: str) -> str:
        self.n += 1
        if self.n % 3 == 0:
            echo = re.sub(r"\s+", "", said)[:16]
            return f"您说“{echo}”，好的，我明白了，我会配合的。"
        t = BAD_TEMPLATES[self.k % len(BAD_TEMPLATES)]
        self.k += 1
        return t


# ---------------------------------------------------------------- #262 大模型被骗方
VICTIM_TEMPERATURE = 0.8  # 与 voice.llm_ab 一致
VICTIM_MAX_TOKENS = 120
EST_VICTIM_PROMPT_TOKENS = 1400  # 估算用：语音人设提示词 + 窗口内历史（voice.llm_ab 实测平均约 1240）
EST_VICTIM_OUT_TOKENS = 20
# 骗子提出转账 / 付款（之后才统计收款账户有没有被问出来）
TRANSFER_RX = re.compile(r"转账|汇款|打款|转款|付款|充值|缴纳|保证金|解冻金|手续费|转到|转入|打到|打过去|转过去|转给|汇到|汇给|扫码付|安全账户")
ACCOUNT_KINDS = ("bank_card", "alipay")  # 收款账户：银行卡号或支付宝（户名单独算 name）
_VICTIM_MODS: Dict[str, tuple] = {}


def load_victim(root: Optional[Path] = None) -> tuple:
    """按 root（某个 worktree）加载 voice.persona / voice.processors，同一份评测代码可以对比不同分支的人设提示词。
    同一进程只能用一个 root（voice 包只导入一次）；python/deepsuck 仍用本仓库的。"""
    root = Path(root or ROOT).resolve()
    key = str(root)
    if key in _VICTIM_MODS:
        return _VICTIM_MODS[key]
    if _VICTIM_MODS:
        raise RuntimeError("同一进程只能加载一个 --victim-root")
    if str(root) not in sys.path[:1]:
        sys.path.insert(0, str(root))
    import importlib
    persona = importlib.import_module("voice.persona")
    processors = importlib.import_module("voice.processors")
    from pipecat.processors.aggregators.llm_context import LLMContext
    got = Path(persona.__file__).resolve()
    if root not in got.parents:
        raise RuntimeError(f"voice.persona 加载自 {got}，不在 --victim-root {root} 下（先前已导入过 voice？）")
    _VICTIM_MODS[key] = (persona, processors, LLMContext)
    return _VICTIM_MODS[key]


def victim_params(model: str, seed: int) -> dict:
    return {"model": model, "temperature": VICTIM_TEMPERATURE, "seed": seed, "enable_thinking": False,
            "max_tokens": VICTIM_MAX_TOKENS}


class LLMVictim:
    """#262：被骗方按现网语音管线出回复（与 voice.llm_ab.run_script 同一流程，不流式）：
    Session.ingest → 意图门控 → IntelProcessor.update_prompt（voice/persona.py 提示词）→ 大模型 → guard_output。
    请求走与骗子相同的 Caller（缓存、计费、上限）。"""

    def __init__(self, session, call: Callable, model: str, seed: int, root: Optional[Path] = None):
        self.persona, processors, LLMContext = load_victim(root)
        self.s, self.call, self.params = session, call, victim_params(model, seed)
        self.ctx = LLMContext([{"role": "system", "content": "x"}])
        self.ip = processors.IntelProcessor(session, context=self.ctx)

    def opening(self) -> str:
        t = self.persona.voice_opening(self.s)["text"]
        self.ctx.add_message({"role": "assistant", "content": t})
        return t

    def reply(self, a: dict) -> dict:
        s, P = self.s, self.persona
        self.ip.intent = P.gate_intent(s.fresh_intent(s.choose_intent(a)), s)
        s.last_intent = self.ip.intent
        self.ip.update_prompt()
        self.ctx.add_message({"role": "user", "content": P.unmask(a["redacted"])})
        msgs = [dict(m) for m in self.ctx.get_messages()]
        raw = self.call(msgs, self.params).get("content", "")
        text = P.guard_output(raw)
        self.ctx.add_message({"role": "assistant", "content": text})
        return {"text": text, "raw": raw, "intent": self.ip.intent}


def transfer_turn(scammer_lines: List[str]) -> Optional[int]:
    """骗子第一次提出转账 / 付款的轮次（0 起），没提过返回 None。"""
    return next((i for i, t in enumerate(scammer_lines) if TRANSFER_RX.search(t or "")), None)


def account_after_transfer(scammer_lines: List[str], values: dict, kinds: List[str]) -> Optional[bool]:
    """提出转账之后（含同一轮），骗子有没有说出收款账户（本场情报里的银行卡 / 支付宝）。本场不涉及账户或没提转账返回 None。"""
    want = [k for k in kinds if k in ACCOUNT_KINDS]
    k0 = transfer_turn(scammer_lines)
    if not want or k0 is None:
        return None
    got = set()
    for t in scammer_lines[k0:]:
        got |= {kind_of(x) for x, _ in revealed_in(t, values, want)}
    return bool(got & set(want))


# ---------------------------------------------------------------- parsing
def parse_turn(content: str) -> dict:
    """解析骗子输出；不是 JSON 时整段当作要说的话（记为解析失败）。"""
    text = (content or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0) if m else text)
        if not isinstance(d, dict):
            raise ValueError
    except (ValueError, AttributeError):
        return {"say": text, "action": "continue", "parse_error": True}
    action = str(d.get("action", "continue")).strip().lower()
    out = {"say": str(d.get("say") or "").strip(), "action": "hangup" if action.startswith("hang") else "continue",
           "parse_error": False}
    try:
        sus = d.get("suspicion")
        if sus is not None and str(sus).strip() != "":
            out["suspicion"] = max(0, min(10, int(float(sus))))
    except (TypeError, ValueError):
        pass
    if "probe" in d:
        out["probe"] = 1 if str(d.get("probe")).strip().lower() in ("1", "true", "yes") else 0
    try:
        if d.get("strikes") is not None and str(d.get("strikes")).strip() != "":
            out["strikes"] = max(0, int(float(d["strikes"])))
    except (TypeError, ValueError):
        pass
    if out["action"] == "hangup":
        ht = str(d.get("hangup_type") or "").strip().lower()
        cat = str(d.get("category") or "").strip().lower()
        out.update({"hangup_type": ht if ht in ("bot", "trolling", "not_worth") else "bot",
                    "category": cat if cat in CATEGORIES else "other",
                    "evidence": str(d.get("evidence") or "")[:60], "reason": str(d.get("reason") or "")[:80]})
    elif not out["say"]:
        out.update({"say": "喂？在吗？", "parse_error": True})
    return out


# ---------------------------------------------------------------- intel accounting
def _digits_joined(text: str) -> str:
    return re.sub(r"(?<=\d)[\s\-－—–·.,，]+(?=\d)", "", text)


_LEAK_OTP = re.compile(r"(验证码|动态码|校验码|密码|口令)[^。！？!?\n]{0,10}?(?<!尾号)\d{4,}")


def bot_leak(text: str, scammer_said: str = "") -> bool:
    """人设回复是否泄露了看似真实的信息：完整的敏感号码（卡号、手机号、身份证……）、连续 5 位以上数字，
    或“验证码 / 密码”后面跟 4 位以上数字。只说尾号 4 位、两位虚构数字不算。
    复述骗子本场已经报过的值（例如对方给的户名、卡号）不算泄露：那是骗子的情报，不是人设的。"""
    text = text or ""
    dj = _digits_joined(text)
    said, said_dj = scammer_said or "", _digits_joined(scammer_said or "")
    own = [x for x in X.extract_sensitive(text)
           if not ((x.get("value") if isinstance(x, dict) else str(x)) in said
                   or _digits_joined(str(x.get("value") if isinstance(x, dict) else x)) in said_dj)]
    long_digits = [d for d in re.findall(r"\d{5,}", dj) if d not in said_dj]
    return bool(own or long_digits or _LEAK_OTP.search(dj))


def revealed_in(text: str, values: dict, kinds: List[str]) -> set:
    """骗子这条消息里出现了哪些虚构情报（类型, 规范值），口径同 deepsuck.sim。"""
    got = set()
    dj = _digits_joined(text)
    low = text.lower()
    checks = []
    if "bank" in kinds:
        checks += [("bank_card", values["bank"], values["bank"] in dj)]
    if "bank" in kinds or "name" in kinds:
        checks += [("name", values["name"], values["name"] in text)]
    if "phone" in kinds:
        checks += [("phone", values["phone"], values["phone"] in dj)]
    if "url" in kinds:
        checks += [("url", values["domain"], values["domain"].lower() in low)]
    if "wallet" in kinds:
        checks += [("crypto_tron", values["tron"], values["tron"] in text)]
    for t, v, hit in checks:
        if hit:
            got.add((t, SIM._canon(t, v)))
    return got


def kind_of(t: str) -> str:
    return {"bank_card": "bank", "name": "name", "phone": "phone", "url": "url", "crypto_tron": "wallet"}[t]


def _sim(a: str, b: str) -> float:
    ga, gb = SIM._bigrams(a), SIM._bigrams(b)
    return len(ga & gb) / max(1, len(ga | gb))


# ---------------------------------------------------------------- cache / client
def params_for(model: str, seed: int) -> dict:
    return {"model": model, "temperature": TEMPERATURE, "seed": seed, "response_format": {"type": "json_object"},
            "enable_thinking": False, "max_tokens": MAX_OUT_TOKENS}


def cache_key(messages: List[dict], params: dict, version: str = PROMPT_VERSION) -> str:
    blob = json.dumps({"v": version, "messages": messages, "params": params}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Meter:
    """线程安全的费用计量；超过上限抛 BudgetError。"""

    def __init__(self, max_cost: float):
        self.max_cost = max_cost
        self.lock = threading.Lock()
        self.u = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "cost_cny": 0.0, "requests": 0,
                  "cached_requests": 0}

    def add(self, pt: int, ct: int, cached: int = 0) -> None:
        with self.lock:
            self.u["prompt_tokens"] += pt
            self.u["completion_tokens"] += ct
            self.u["cached_tokens"] += cached
            self.u["requests"] += 1
            self.u["cost_cny"] = J.cost_cny(self.u["prompt_tokens"], self.u["completion_tokens"], self.u["cached_tokens"])
            if self.u["cost_cny"] > self.max_cost:
                raise BudgetError(f"实际费用 {self.u['cost_cny']:.4f} 元已超过上限 {self.max_cost} 元，停止")

    def cached(self) -> None:
        with self.lock:
            self.u["cached_requests"] += 1


class Caller:
    """带缓存的调用；client=None 表示只读缓存（未命中抛 CacheMiss，用于估算）。"""

    def __init__(self, client_getter: Optional[Callable[[], object]], meter: Optional[Meter], cache_dir: Path,
                 refresh: bool = False, version: str = PROMPT_VERSIONS["default"]):
        self.get_client, self.meter, self.cache_dir, self.refresh = client_getter, meter, Path(cache_dir), refresh
        self.version = version

    def __call__(self, messages: List[dict], params: dict) -> dict:
        k = cache_key(messages, params, self.version)
        p = self.cache_dir / f"{k}.json"
        if not self.refresh and p.exists():
            if self.meter:
                self.meter.cached()
            return json.loads(p.read_text(encoding="utf-8"))
        if self.get_client is None:
            raise CacheMiss(k)
        client = self.get_client()
        resp = client.chat(messages, **params)
        pt, ct, cached = J.usage_tokens(resp.get("usage") or {})
        hit = {"model": resp.get("model") or params["model"], "content": resp.get("content", ""),
               "usage": {"prompt_tokens": pt, "completion_tokens": ct, "cached_tokens": cached},
               "request_id": resp.get("request_id"), "date": date.today().isoformat(), "prompt_version": self.version}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp" + str(threading.get_ident()))
        tmp.write_text(json.dumps(hit, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(p)
        if self.meter:
            self.meter.add(pt, ct, cached)
        return hit


# ---------------------------------------------------------------- one session
def session_seed(scenario: str, persona: str, seed: int) -> int:
    return zlib.crc32(f"{scenario}|{persona}|{seed}".encode()) & 0x7FFFFFFF


def run_session(scenario: str, persona: str, seed: int, corpus: dict, kinds: List[str], call: Callable,
                model: str = MODEL, max_turns: int = DEFAULT_MAX_TURNS, humanize: bool = True,
                profile: str = "default", responder: str = "persona", victim_root: Optional[Path] = None) -> dict:
    rd = SIM.Rand(seed)
    values = SIM.plant(rd)
    sysmsg = system_prompt(corpus, scenario, values, kinds, seed, profile)
    params = params_for(model, session_seed(scenario, persona, seed))
    s = Session(scenario, persona, rng=mulberry32(seed ^ 0x5EED), now=lambda: 0)
    bad = ({"bad": BadResponder, "stall": StallResponder}[responder](session_seed(scenario, persona, seed))
           if responder in ("bad", "stall") else None)
    victim = LLMVictim(s, call, model, session_seed(scenario, persona, seed), victim_root) if responder == "llm" else None
    # 语音管线不过 humanize，llm 被骗方也不过
    hum = (Humanizer(profile=HUMANIZE_PROFILE.get(persona, persona), seed=seed ^ 0x4855, **HUMANIZE_OVERRIDES.get(persona, {}))
           if humanize and not bad and not victim else None)
    first = ({"text": bad.opening(), "intent": responder} if bad
             else {"text": victim.opening(), "intent": "opening"} if victim else s.opening())
    # #121：数字过滤在错别字扰动之后、发出去之前（与线上一致；record_bot 已过一遍，这里是扰动后的最后一道）
    bot_text = vague_digits(hum.apply(first["text"]).text) if hum else first["text"]
    messages = [{"role": "system", "content": sysmsg}, {"role": "user", "content": bot_text}]
    log = [{"role": "bot", "text": bot_text, "raw": first["text"], "intent": "opening", "ops": []}]
    seen, seen_raw, grams = {bot_text}, {first["text"]}, [SIM._bigrams(bot_text)]
    dup = dup_raw = near = parse_errors = leaks = stars = silent = 0
    revealed: set = set()
    scam_said = ""
    turns, quit_, hang, model_name = 0, None, None, model
    sus: List[int] = []
    probes = 0
    while True:
        resp = call(messages, params)
        model_name = resp.get("model") or model_name
        t = parse_turn(resp["content"])
        parse_errors += t["parse_error"]
        if "suspicion" in t:
            sus.append(t["suspicion"])
        probes += t.get("probe", 0)
        if t["action"] == "hangup":
            quit_ = "suspicious" if t["hangup_type"] in SUSPICIOUS else "give_up"
            bots = [m for m in log if m["role"] == "bot" and not m.get("silent")]
            ev = t.get("evidence") or ""
            trig = max(bots, key=lambda m: _sim(ev, m["text"])) if ev else bots[-1]
            if ev and _sim(ev, trig["text"]) < 0.15:
                trig = bots[-1]
            hang = {k: t[k] for k in ("hangup_type", "category", "evidence", "reason")}
            hang.update({"turn": turns, "trigger_intent": trig["intent"], "trigger_ops": trig["ops"],
                         "trigger_text": trig["text"], "last_intent": bots[-1]["intent"]})
            log.append({"role": "scammer", "text": t["say"], "hangup": hang})
            break
        if turns >= max_turns or silent >= max_turns:  # 一直空串也不会死循环
            quit_ = "max_turns"
            break
        say = t["say"]
        turns += 1
        revealed |= revealed_in(say, values, kinds)
        # 历史里保留本档要求的全部字段，模型才会每轮照格式填（hard 档的 suspicion / probe / strikes）
        hist = {"say": say, "action": "continue"}
        if profile == "hard":
            hist.update({k: t[k] for k in ("suspicion", "probe", "strikes") if k in t})
        messages.append({"role": "assistant", "content": json.dumps(hist, ensure_ascii=False)})
        log.append({"role": "scammer", "text": say})
        scam_said += say + "\n"
        if victim:
            r = victim.reply(s.ingest(say))
        elif bad:
            s.ingest(say)  # 情报提取照常（口径相同），回复换成差的对照组
            r = {"text": bad.reply(say), "intent": responder}
        else:
            r = s.rule_reply(s.ingest(say))
        h = hum.apply(r["text"], context=say, intent=r["intent"]) if hum else None
        text = vague_digits(h.text) if h else r["text"]
        if not (text or "").strip():
            # #164：空串回复（例如上游尾句去重删空、又没有兜底台词）当作这一轮没回复：不计入拖延轮数和回复统计，
            # 骗子那边看到的是“对方没回”，口径与线上一致（空串不会发出去）。
            turns -= 1
            silent += 1
            log.append({"role": "bot", "text": "", "raw": r["text"], "intent": r["intent"], "ops": [], "silent": True})
            messages.append({"role": "user", "content": SILENT_MARK})
            continue
        is_dup, g = text in seen, SIM._bigrams(text)
        dup += is_dup
        dup_raw += r["text"] in seen_raw
        near += is_dup or any(len(g & x) / len(g | x) >= 0.8 for x in grams)
        seen.add(text)
        seen_raw.add(r["text"])
        grams.append(g)
        leaks += bot_leak(text, scam_said)
        stars += bool(re.search(r"[*＊]", text))
        log.append({"role": "bot", "text": text, "raw": r["text"], "intent": r["intent"], "ops": h.ops if h else []})
        messages.append({"role": "user", "content": text})
    got = {(i["type"], SIM._canon(i["type"], s._raw[k])) for k, i in s.intel.items()}
    total_kinds = len(kinds)
    said_lines = [m["text"] for m in log if m["role"] == "scammer" and not m.get("hangup")]
    return {"scenario": scenario, "persona": persona, "seed": seed, "model": model_name, "turns": turns,
            "estMinutes": s.est_seconds / 60, "quit": quit_, "hangup": hang,
            "revealedKinds": len({kind_of(t) for t, _ in revealed} & set(kinds)), "totalKinds": total_kinds,
            "revealedItems": len(revealed), "capturedItems": len(revealed & got), "falseIntel": len(got - revealed),
            "botReplies": turns, "silentTurns": silent, "leaks": leaks, "starReplies": stars, "dup": dup, "dupRaw": dup_raw, "near": near, "parseErrors": parse_errors,
            "profile": profile, "responder": responder, "suspicion": sus, "probes": probes,
            "flaggedTurns": sum(x >= FLAG_SUSPICION for x in sus),
            "transferTurn": transfer_turn(said_lines), "accountAfterTransfer": account_after_transfer(said_lines, values, kinds),
            "transcript": log}


# ---------------------------------------------------------------- transcript 脱敏（#164：结果文件里存对话全文）
REDACT_TYPES = ("bank_card", "name", "id_card", "qq", "wechat", "alipay")  # 电话、钱包、网址按约定不打码（都是虚构值）
_LONG_CARD = re.compile(r"(?<![0-9])[0-9](?:[ \-]?[0-9]){14,18}(?![0-9])")
_ID18 = re.compile(r"(?<![0-9A-Za-z])[1-9][0-9]{16}[0-9Xx](?![0-9A-Za-z])")


def redact_text(text: str, planted: Optional[dict] = None) -> str:
    """存 transcript 前的脱敏：提取器认出的银行卡、姓名、身份证、QQ、微信、支付宝按 deepsuck.redact 的规则打码；
    再兜底本场植入的虚构值（卡号各种写法、户名、微信号、QQ 号）和 15–19 位连续数字（卡号）、18 位身份证号。"""
    from deepsuck import redact as RD
    s = str(text or "")
    if not s:
        return s
    spans = [e for e in X.extract(s) if e.get("type") in REDACT_TYPES and e.get("start") is not None]
    for e in sorted(spans, key=lambda e: e["start"], reverse=True):
        s = s[:e["start"]] + RD.mask(e["type"], s[e["start"]:e["end"]]) + s[e["end"]:]
    pv = planted or {}
    for k, t in (("bank_spaced", "bank_card"), ("bank", "bank_card"), ("bank_cn", "name"), ("name", "name"),
                 ("wx", "wechat"), ("qq", "qq")):
        v = pv.get(k)
        if v and v in s:
            s = s.replace(v, RD.mask(t, v) if k != "bank_cn" else "*" * len(v))
    s = _ID18.sub(lambda m: RD.mask_id_card(m.group()), s)
    s = _LONG_CARD.sub(lambda m: RD.mask_bank_card(m.group()), s)
    return s


def redact_transcript(row: dict) -> List[dict]:
    """每一轮：骗子存原文（脱敏后），人设存 text（发出去的）和 raw（真人化之前的引擎原文），都脱敏。"""
    planted = SIM.plant(SIM.Rand(row["seed"]))
    out = []
    for m in row.get("transcript") or []:
        o = {"role": m["role"], "text": redact_text(m.get("text", ""), planted)}
        if m["role"] == "bot":
            o.update({"raw": redact_text(m.get("raw", ""), planted), "intent": m.get("intent")})
            if m.get("silent"):
                o["silent"] = True
        elif m.get("hangup"):
            h = m["hangup"]
            o["hangup"] = {k: (redact_text(h[k], planted) if isinstance(h.get(k), str) else h.get(k))
                           for k in ("hangup_type", "category", "evidence", "reason", "turn", "trigger_intent")}
        out.append(o)
    return out


# ---------------------------------------------------------------- estimate / run
def estimate_session(corpus: dict, scenario: str, persona: str, seed: int, kinds: List[str], max_turns: int,
                     profile: str = "default", responder: str = "persona") -> dict:
    """按“每轮都不挂断、到上限、缓存一次也不命中”估算（偏保守）；骗子每轮输出按 EST_OUT_TOKENS_PER_TURN，人设回复按该人设台词平均长度 × 1.3。"""
    values = SIM.plant(SIM.Rand(seed))
    sys_t = J.estimate_tokens(system_prompt(corpus, scenario, values, kinds, seed, profile))
    p = next(x for x in PERSONAS if x["id"] == persona)
    lens = [len(it if isinstance(it, str) else it["t"]) for v in p["templates"].values() for it in v]
    bot_t = int(mean(lens) * 1.3) + 8
    inp = out = 0
    hist = bot_t
    for _ in range(max_turns + 1):
        inp += sys_t + hist
        out += EST_OUT_TOKENS_PER_TURN
        hist += EST_OUT_TOKENS_PER_TURN + bot_t
        if responder == "llm":
            inp += EST_VICTIM_PROMPT_TOKENS
            out += EST_VICTIM_OUT_TOKENS
    return {"prompt_tokens": inp, "completion_tokens": out}


def plan(scenarios, personas, seeds: int, seed_base: int = 1000) -> List[tuple]:
    return [(sc, p, seed_base + k) for sc in scenarios for p in personas for k in range(seeds)]


def run(scenarios=None, personas=None, seeds: int = DEFAULT_SEEDS, max_turns: int = DEFAULT_MAX_TURNS,
        model: str = MODEL, max_cost: float = HARD_MAX_COST_CNY, client_factory: Optional[Callable[[], object]] = None,
        cache_dir: Path = CACHE_DIR, dry_run: bool = True, refresh: bool = False, humanize: bool = True,
        workers: int = 6, corpus: Optional[dict] = None, log: Callable[[str], None] = lambda s: None,
        meter_hook: Optional[Callable[[object], None]] = None, profile: str = "default", responder: str = "persona",
        victim_root: Optional[Path] = None, seed_base: int = 1000) -> dict:
    max_cost = min(float(max_cost), HARD_MAX_COST_CNY)
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}")
    if responder not in RESPONDERS:
        raise ValueError(f"responder must be one of {RESPONDERS}")
    version = PROMPT_VERSIONS[profile]
    scenarios = list(scenarios or [s["id"] for s in SCENARIOS])
    personas = list(personas or [p["id"] for p in PERSONAS])
    if corpus is None:
        corpus = json.loads(SIM.default_corpus_path().read_text(encoding="utf-8"))
    legacy = SIM.load_scripts("legacy")
    jobs = plan(scenarios, personas, seeds, seed_base)
    # 1) 只读缓存走一遍：完全缓存的场次不计费
    ro = Caller(None, None, cache_dir, refresh, version)
    cached, todo = {}, []
    for job in jobs:
        kinds = legacy["scenarios"][job[0]]["intel"]
        try:
            cached[job] = (run_session(*job, corpus, kinds, ro, model, max_turns, humanize, profile, responder, victim_root)
                           if not refresh else None)
            if cached[job] is None:
                raise CacheMiss("refresh")
        except CacheMiss:
            cached.pop(job, None)
            todo.append(job)
    est_in = est_out = 0
    for job in todo:
        e = estimate_session(corpus, job[0], job[1], job[2], legacy["scenarios"][job[0]]["intel"], max_turns, profile, responder)
        est_in += e["prompt_tokens"]
        est_out += e["completion_tokens"]
    est_cost = J.cost_cny(est_in, est_out)
    estimate = {"sessions": len(jobs), "uncached_sessions": len(todo), "max_turns": max_turns,
                "prompt_tokens": est_in, "completion_tokens": est_out, "cost_cny": round(est_cost, 4),
                "max_cost_cny": max_cost,
                "price": {"input_per_m": J.PRICE_INPUT_PER_M, "output_per_m": J.PRICE_OUTPUT_PER_M,
                          "cached_input_per_m": J.PRICE_CACHED_INPUT_PER_M, "source": J.PRICE_SOURCE}}
    log(f"估算：{len(jobs)} 场（未缓存 {len(todo)} 场，每场至多 {max_turns} 轮），输入至多约 {est_in} token、"
        f"输出约 {est_out} token，约 {est_cost:.4f} 元（上限 {max_cost} 元）")
    if est_cost > max_cost:
        raise BudgetError(f"估算费用 {est_cost:.4f} 元超过上限 {max_cost} 元，拒绝运行；请减少 --seeds / --max-turns / 场景或人设")
    config = {"model": model, "seeds": seeds, "maxTurns": max_turns, "scenarios": scenarios, "personas": personas,
              "humanize": {p: HUMANIZE_PROFILE.get(p, p) for p in personas} if humanize else None,
              "humanizeOverrides": {p: HUMANIZE_OVERRIDES[p] for p in personas if p in HUMANIZE_OVERRIDES} or None,
              "temperature": TEMPERATURE, "promptVersion": version, "profile": profile, "responder": responder,
              "enableThinking": False, "linesPerPhase": LINES_PER_PHASE, "seedBase": seed_base,
              **({"victim": victim_info(victim_root, model)} if responder == "llm" else {})}
    result = {"config": config, "date": date.today().isoformat(), "estimate": estimate, "dry_run": dry_run}
    if dry_run:
        return result
    meter = Meter(max_cost)
    if meter_hook:
        meter_hook(meter)  # 让调用方在中途停下时也能拿到已花的钱（记台账）
    lock = threading.Lock()
    holder = {}

    def get_client():
        with lock:
            if "c" not in holder:
                c = client_factory() if client_factory else None
                if c is None:
                    raise RuntimeError("没有可用的骗子模型客户端（缺少 DASHSCOPE_API_KEY）")
                holder["c"] = c
            return holder["c"]

    caller = Caller(get_client, meter, cache_dir, refresh, version)
    rows: Dict[tuple, dict] = dict(cached)
    for _ in cached:
        meter.cached()

    def work(job):
        return job, run_session(*job, corpus, legacy["scenarios"][job[0]]["intel"], caller, model, max_turns, humanize,
                                profile, responder, victim_root)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for job, row in ex.map(work, todo):
            rows[job] = row
            log(f"  {job[0]}/{job[1]}/{job[2]}: {row['turns']} 轮, {row['quit']}")
    ordered = [rows[j] for j in jobs]
    meter.u["cost_cny"] = round(meter.u["cost_cny"], 6)
    meter.u["cache_hit_rate"] = round(meter.u["cached_tokens"] / meter.u["prompt_tokens"], 4) if meter.u["prompt_tokens"] else None
    result.update({"usage": meter.u, "rows": ordered})
    result.update(summarize(ordered, scenarios, personas))
    return result


def victim_info(root: Optional[Path], model: str) -> dict:
    import subprocess
    root = Path(root or ROOT).resolve()
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        head = None
    return {"root": root.name, "commit": head, "model": model, "temperature": VICTIM_TEMPERATURE,
            "maxTokens": VICTIM_MAX_TOKENS, "pipeline": "voice.persona + voice.processors.IntelProcessor + guard_output"}


# ---------------------------------------------------------------- summary
def aggregate(rows: List[dict]) -> dict:
    n = max(1, len(rows))
    replies = sum(r["botReplies"] for r in rows) or 1
    rev = sum(r["revealedItems"] for r in rows)
    return {
        "sessions": len(rows),
        "suspiciousQuit": sum(r["quit"] == "suspicious" for r in rows) / n,
        "suspiciousQuitEarly": sum(r["quit"] == "suspicious" and r["turns"] <= QUIT_WINDOW for r in rows) / n,
        "giveUp": sum(r["quit"] == "give_up" for r in rows) / n,
        "maxTurnsHit": sum(r["quit"] == "max_turns" for r in rows) / n,
        "avgTurns": mean(r["turns"] for r in rows) if rows else 0.0,
        "avgEstMinutes": mean(r["estMinutes"] for r in rows) if rows else 0.0,
        "elicitRate": sum(r["revealedKinds"] for r in rows) / max(1, sum(r["totalKinds"] for r in rows)),
        "extractRate": sum(r["capturedItems"] for r in rows) / max(1, rev),
        "falseIntelPerSession": sum(r["falseIntel"] for r in rows) / n,
        "leakRate": sum(r.get("leaks", 0) for r in rows) / replies,
        "leakSessions": sum(r.get("leaks", 0) > 0 for r in rows),
        "starReplyRate": sum(r.get("starReplies", 0) for r in rows) / replies,
        "repeatRate": sum(r["dup"] for r in rows) / replies,
        "repeatRateRaw": sum(r["dupRaw"] for r in rows) / replies,
        "nearRepeatRate": sum(r["near"] for r in rows) / replies,
        "parseErrors": sum(r["parseErrors"] for r in rows),
        # hard 档：每轮起疑分（0–10）的均值、起疑分 ≥7 的回合占比（“露馅率”）、至少露馅一次的场次占比
        "avgSuspicion": (mean(x for r in rows for x in r.get("suspicion", []))
                         if any(r.get("suspicion") for r in rows) else None),
        "flagRate": (sum(r.get("flaggedTurns", 0) for r in rows) / max(1, sum(len(r.get("suspicion", [])) for r in rows))
                     if any(r.get("suspicion") for r in rows) else None),
        "flaggedSessions": (sum(r.get("flaggedTurns", 0) > 0 for r in rows) / n
                            if any(r.get("suspicion") for r in rows) else None),
        "probesPerSession": (sum(r.get("probes", 0) for r in rows) / n if any(r.get("suspicion") for r in rows) else None),
        # #262：骗子提出转账的场次里，之后说出收款账户（银行卡 / 支付宝）的占比；分母只算本场情报含账户、且提过转账的
        "transferSessions": sum(r.get("accountAfterTransfer") is not None for r in rows),
        "accountAfterTransferRate": (sum(bool(r.get("accountAfterTransfer")) for r in rows)
                                     / max(1, sum(r.get("accountAfterTransfer") is not None for r in rows))),
    }


def summarize(rows: List[dict], scenarios, personas) -> dict:
    hs = [r["hangup"] for r in rows if r["hangup"]]
    sus = [h for h in hs if h["hangup_type"] in SUSPICIOUS]
    return {
        "overall": aggregate(rows),
        "byPersona": {p: aggregate([r for r in rows if r["persona"] == p]) for p in personas},
        "byScenario": {s: aggregate([r for r in rows if r["scenario"] == s]) for s in scenarios},
        "bySeed": {str(k): aggregate([r for r in rows if r["seed"] == k]) for k in sorted({r["seed"] for r in rows})},
        "hangupCategories": dict(Counter(h["category"] for h in sus).most_common()),
        "hangupTypes": dict(Counter(h["hangup_type"] for h in hs).most_common()),
        "triggerIntents": dict(Counter(h["trigger_intent"] for h in sus).most_common()),
        "hangups": [{"scenario": r["scenario"], "persona": r["persona"], "seed": r["seed"],
                     **{k: r["hangup"][k] for k in ("turn", "hangup_type", "category", "reason", "evidence",
                                                     "trigger_intent", "trigger_ops", "trigger_text")}}
                    for r in rows if r["hangup"]],
    }


def rule_baseline(scenarios, personas, seeds: int, max_turns: int) -> dict:
    """同样的场景 × 人设 × 种子、同样轮数上限下的规则骗子（deepsuck.sim，语料台词），便于并列对比。"""
    scripts = SIM.load_scripts("corpus")
    old = SIM.MAX_TURNS
    SIM.MAX_TURNS = max_turns  # 只在本进程内临时改，不改 sim.py
    try:
        rows = [SIM.run_one(sc, p, "rule", seed, scripts) for sc, p, seed in plan(scenarios, personas, seeds)]
    finally:
        SIM.MAX_TURNS = old
    return SIM.aggregate(rows)


def to_markdown(res: dict) -> str:
    pn = {p["id"]: p["name"] for p in PERSONAS}
    sn = {s["id"]: s["title"] for s in SCENARIOS}
    cols = [("suspiciousQuit", "起疑挂断", "{:.1%}"), ("suspiciousQuitEarly", f"{QUIT_WINDOW} 轮内起疑挂断", "{:.1%}"), ("giveUp", "放弃", "{:.0%}"), ("avgTurns", "平均拖延轮数", "{:.1f}"),
            ("elicitRate", "情报暴露率", "{:.0%}"), ("extractRate", "提取率", "{:.1%}"), ("leakRate", "泄露率", "{:.1%}"),
            ("repeatRate", "完全重复率", "{:.1%}"), ("nearRepeatRate", "近重复率", "{:.1%}")]
    if res["overall"].get("avgSuspicion") is not None:
        cols += [("avgSuspicion", "平均起疑分", "{:.2f}"), ("flagRate", "露馅回合", "{:.1%}"), ("flaggedSessions", "露馅场次", "{:.0%}")]

    def table(title, d, names):
        out = [f"**{title}**", "", "| | " + " | ".join(c[1] for c in cols) + " |", "|---" * (len(cols) + 1) + "|"]
        for k, v in d.items():
            out.append(f"| {names.get(k, k)} | " + " | ".join(
                "—" if v.get(c[0]) is None else c[2].format(v.get(c[0], 0)) for c in cols) + " |")
        return "\n".join(out)
    rows = {"llm": res["overall"]}
    names = {"llm": f"大模型骗子（{res['config']['model']}，{res['config'].get('profile', 'default')} 档，"
                    f"被骗方 {res['config'].get('responder', 'persona')}）"}
    if res.get("ruleBaseline"):
        rb = dict(res["ruleBaseline"])
        rb.setdefault("giveUp", 1 - rb.get("suspiciousQuit", 0) - rb.get("maxTurnsHit", 0))
        rows["rule"] = rb
        names["rule"] = "规则骗子（deepsuck.sim，同种子同上限）"
    c = res["config"]
    parts = [table(f"总体（{len(c['scenarios'])} 场景 × {len(c['personas'])} 人设 × {c['seeds']} 种子，每场至多 {c['maxTurns']} 轮）",
                   rows, names),
             table("大模型骗子 · 按人设", res["byPersona"], pn), table("大模型骗子 · 按场景", res["byScenario"], sn)]
    cat = res.get("hangupCategories") or {}
    if cat:
        parts.append("**起疑挂断的露馅类别**：" + "，".join(f"{CATEGORIES[k].split('：')[0]} {v}" for k, v in cat.items()))
        parts.append("**露馅回复的引擎意图**：" + "，".join(f"{k} {v}" for k, v in res["triggerIntents"].items()))
    o = res["overall"]
    if o.get("transferSessions"):
        parts.append(f"**提出转账后问出收款账户**：{o['accountAfterTransferRate']:.1%}"
                     f"（{round(o['accountAfterTransferRate'] * o['transferSessions'])}/{o['transferSessions']} 场）")
    u = res.get("usage") or {}
    parts.append(f"费用：{u.get('requests', 0)} 次请求（本地缓存命中 {u.get('cached_requests', 0)}），输入 {u.get('prompt_tokens', 0)} token"
                 f"（百炼缓存命中 {u.get('cached_tokens', 0)}）、输出 {u.get('completion_tokens', 0)} token，约 {u.get('cost_cny', 0):.4f} 元；"
                 f"调用前估算 {res['estimate']['cost_cny']} 元（按无缓存命中估算）。")
    return "\n\n".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="大模型扮演骗子重测起疑挂断率（默认只估算，--run 才调用）")
    ap.add_argument("--run", action="store_true", help="显式打开：实际调用骗子模型（默认 qwen3.8-flash；默认只估算费用）")
    ap.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    ap.add_argument("--scenarios", default=None, help="逗号分隔，默认全部 7 个")
    ap.add_argument("--personas", default=None, help="逗号分隔，默认模拟器全部人设")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--max-cost", type=float, default=HARD_MAX_COST_CNY, help="费用上限（元），只能调低，硬上限 3 元")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--budget-tag", default=None, help="费用台账标签：同标签累计不超过 --total-budget，每次运行逐笔记入 eval-spend.csv")
    ap.add_argument("--total-budget", type=float, default=L.HARD_TOTAL_CNY, help="同一 --budget-tag 的总预算（元），硬上限 10 元")
    ap.add_argument("--ledger", type=Path, default=L.LEDGER, help="费用台账 CSV，默认仓库根目录 eval-spend.csv")
    ap.add_argument("--profile", choices=PROFILES, default="default",
                    help="骗子档：default = 原口径；hard = #164 高压档（更多疑、主动试探、发现机器人感就挂断，每轮输出起疑分）")
    ap.add_argument("--responder", choices=RESPONDERS, default="persona",
                    help="被骗方：persona = 规则引擎 + humanize（被测人设）；bad = 规则模拟的明显差的对照组（校准用）；"
                         "llm = #262 大模型被骗方（voice/persona.py 提示词，默认关）")
    ap.add_argument("--victim-root", type=Path, default=None,
                    help="#262：--responder llm 时从这个 worktree 加载 voice/persona.py（默认本仓库），用来对比不同分支的人设提示词")
    ap.add_argument("--seed-base", type=int, default=1000, help="种子从这里起（默认 1000，与旧结果一致）")
    ap.add_argument("--no-humanize", action="store_true")
    ap.add_argument("--handwriting", default="", help="逗号分隔的人设：打开 humanize 手写输入档（错字密度改用 handwritingTypoPer100）")
    ap.add_argument("--typo-rate", default="", help="覆盖每百字错字目标，如 wang=2.5,li=2.0")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新请求")
    ap.add_argument("--no-rule-baseline", action="store_true", help="不跑同条件的规则骗子对照")
    ap.add_argument("--json", default=None, help="结果（聚合 + 每场挂断信息，不含对话全文）")
    ap.add_argument("--transcripts", default=None, help="可选：对话全文 JSONL（虚构值，建议不入库）")
    ap.add_argument("--md", default=None)
    ap.add_argument("--json-transcripts", action="store_true",
                    help="#164：--json 结果里每场带脱敏后的对话全文（骗子原文；人设 text + 真人化前的 raw）")
    a = ap.parse_args(argv)
    HUMANIZE_OVERRIDES.clear()
    for pid in [x for x in a.handwriting.split(",") if x.strip()]:
        HUMANIZE_OVERRIDES.setdefault(pid.strip(), {})["handwriting"] = True
    for kv in [x for x in a.typo_rate.split(",") if x.strip()]:
        pid, v = kv.split("=")
        HUMANIZE_OVERRIDES.setdefault(pid.strip(), {})["typo_per_100"] = float(v)
    sc = a.scenarios.split(",") if a.scenarios else None
    ps = a.personas.split(",") if a.personas else None
    try:
        max_cost = L.cap(min(a.max_cost, HARD_MAX_COST_CNY), a.budget_tag, a.total_budget, a.ledger)
    except L.LedgerBudgetError as e:
        print(str(e), file=sys.stderr)
        return 2
    held = {}
    note = (f"profile={a.profile} responder={a.responder} seeds={a.seeds} maxTurns={a.max_turns} "
            f"personas={a.personas or 'all'} scenarios={a.scenarios or 'all'} seedBase={a.seed_base}" + (f" handwriting={a.handwriting}" if a.handwriting else ""))

    def book(status: str) -> None:
        m = held.get("m")
        if a.budget_tag and a.run and m is not None and m.u["requests"]:
            u = dict(m.u)
            if u.get("cached_tokens"):
                note_c = f" cacheHit={u['cached_tokens'] / max(1, u['prompt_tokens']):.1%}"
            else:
                note_c = ""
            L.append(a.budget_tag, "eval/llm_scammer.py", a.model, u, f"{note}{note_c} {status}", a.ledger)
    try:
        res = run(sc, ps, a.seeds, a.max_turns, a.model, max_cost, J.default_client_factory(), dry_run=not a.run,
                  refresh=a.refresh, humanize=not a.no_humanize, workers=a.workers, log=lambda s: print(s, file=sys.stderr),
                  meter_hook=lambda m: held.__setitem__("m", m), profile=a.profile, responder=a.responder,
                  victim_root=a.victim_root, seed_base=a.seed_base)
    except BudgetError as e:
        book("stopped:budget")
        print(str(e), file=sys.stderr)
        return 2
    except BaseException:
        book("stopped:error")
        raise
    book("ok")
    if res["dry_run"]:
        print(json.dumps(res["estimate"], ensure_ascii=False, indent=1))
        return 0
    if not a.no_rule_baseline:
        res["ruleBaseline"] = rule_baseline(res["config"]["scenarios"], res["config"]["personas"], a.seeds, a.max_turns)
    md = to_markdown(res)
    print(md)
    if a.transcripts:
        with open(a.transcripts, "w", encoding="utf-8") as f:
            for r in res["rows"]:
                f.write(json.dumps({k: r[k] for k in ("scenario", "persona", "seed", "quit", "transcript")},
                                   ensure_ascii=False) + "\n")
    if a.json:
        out = {k: v for k, v in res.items() if k != "rows"}
        out["rows"] = [{**{k: v for k, v in r.items() if k != "transcript"},
                        **({"transcript": redact_transcript(r)} if a.json_transcripts else {})} for r in res["rows"]]
        # 每场挂断信息里的证据 / 触发句也过一遍脱敏
        for h in out.get("hangups") or []:
            pl = SIM.plant(SIM.Rand(h["seed"]))
            for k in ("evidence", "reason", "trigger_text"):
                if isinstance(h.get(k), str):
                    h[k] = redact_text(h[k], pl)
        if a.json_transcripts:
            out["transcriptFormat"] = ("rows[i].transcript：按时间顺序的消息列表；role=scammer 为骗子原文（text，挂断那条带 hangup），"
                                       "role=bot 为人设：text 是发出去的回复（真人化 + 数字过滤之后），raw 是真人化之前的引擎原文，"
                                       "intent 是引擎意图。银行卡、姓名、身份证、QQ、微信、支付宝已打码；电话、钱包、网址是虚构值，未打码。")
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.md:
        Path(a.md).write_text(md + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
