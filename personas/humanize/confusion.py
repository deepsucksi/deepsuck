"""真人化用的混淆表与短语池。

数据的唯一来源是 ``site/assets/core/personas.json`` 的 ``humanize.confusion``（JS 端 ``site/assets/js/humanize.js``
读同一份），这里只是按原来的名字导出，便于 Python 侧引用：

- HOMOPHONE_WORDS：拼音输入法常见的整词同音/近音误选；COMMON_WORDS：日常聊天高频词的同音误写；
  PLACE_WORDS：地名、机构名的同音误写（真人样本里地名错得最多）；
- HOMOPHONE_CHARS：单字同音误用；SHAPE_CHARS：形近字（默认档少量出现）；
- HANDWRITING_CHARS：手写输入识别错的高频字（只在 handwriting 档启用）；
- DIALECT：方言词替换（只收普通话里也能看懂的程度）；
- BANNED_YOUTH_SLANG / BANNED_ESSAY_STYLE：年轻网络用语与“美篇”散文体套话，人设和真人化输出里都不能出现。

网络梗式的刻意错字（神马、孩纸、好滴、手鸡）和读起来像另一个词的（钱→前）不收，见 DELIBERATE。
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _core_path() -> Path:
    env = os.environ.get("DEEPSUCK_CORE_DIR")
    if env:
        return Path(env) / "personas.json"
    return Path(__file__).resolve().parents[2] / "site" / "assets" / "core" / "personas.json"


DATA = json.loads(_core_path().read_text(encoding="utf-8"))["humanize"]
_C = DATA["confusion"]

HOMOPHONE_WORDS = _C["homophoneWords"]
COMMON_WORDS = _C["commonWords"]
PLACE_WORDS = _C["placeWords"]
HOMOPHONE_CHARS = _C["homophoneChars"]
SHAPE_CHARS = _C["shapeChars"]
HANDWRITING_CHARS = _C["handwritingChars"]
DIALECT = {k: [(a, b) for a, b in v] for k, v in _C["dialect"].items()}

# 语音转文字的口语填充词与断句
ASR_FILLERS = _C["asrFillers"]
STUTTER_WORDS = _C["stutterWords"]

# 重复确认：复述对方的话必须带“你是说……”“你说的……”这类框架，不带框架读起来像角色互换
CONFIRM_TEMPLATES = _C["confirmTemplates"]
# 优先复述的关键短语（名词性，复述起来自然）；对方话里没有这些词时才退回短分句
ECHO_KEYWORDS = _C["echoKeywords"]
# 不复述的分句：含人称 / 称呼（复述出来像在说自己）或祈使（复述出来像在指挥对方）
ECHO_AVOID = tuple(_C["echoAvoid"])
CONFIRM_GENERIC = _C["confirmGeneric"]

# 跑题（默认池；人设可以传自己的）
DIGRESSIONS = _C["digressions"]
# 跑题句里的道具词（#129）：含这些词的跑题句不用，除非预设的 propsOk 里有
DIGRESSION_PROPS = tuple(_C.get("digressionProps", ()))

# 刻意错字 / 网络梗写法：不进入任何混淆表（测试会检查）
DELIBERATE = _C["deliberate"]

# 提取器认作“后面跟人名”的提示词：紧跟其后的标点不改、不在那里断句或拆条
NAME_CUES = _C["nameCues"]

# 平台名与情报字段词（含字间夹单个空格的写法）：不写错，内部与紧邻处不改标点、不放表情、不拆条
PROTECT_WORDS = _C["protectWords"]

# 逐字报号用的中文数字：连续 3 个以上（可夹单个空格）按数字串保护
SPOKEN_DIGITS = _C["spokenDigits"]

BANNED_YOUTH_SLANG = _C["bannedStyle"]["youthSlang"]
BANNED_ESSAY_STYLE = _C["bannedStyle"]["essayStyle"]
