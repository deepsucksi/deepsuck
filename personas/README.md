# 人设（personas/）

第二批“潜在受害人”人设与真人化后处理，供大模型模式、语音演示和语料生成使用。现有的规则引擎人设（王阿姨、李大爷、小林）仍在 `site/assets/core/personas.json`，本目录暂不改动它们。

```
personas/
├── prompts/
│   ├── _common.yaml      4 个人设共用的硬性规则（安全约束）
│   ├── retiree.yaml      周伯 · 退休老人
│   ├── mom.yaml          小陈妈妈 · 宝妈
│   ├── graduate.yaml     小宇 · 刚毕业学生
│   └── shop_owner.yaml   郑老板 · 个体小老板
├── prompt.py             拼接完整系统提示词（需要 PyYAML）
├── humanize/             文字打字特征：真人化后处理（零依赖）
├── voice_traits.yaml     语音说话特征：每个人设的口头语、听错反问、语速口音、停顿与扯家常节奏（不含错别字）
├── voice_traits.py       读取上面的 YAML；fillers() 与 voice/persona.py 的 FILLERS 同格式
└── tests/
```

所有人设、背景与台词都是虚构的，不对应任何真实个人。真人感的设计说明（文字打字特征、语音说话特征、首页示例改写对比）见 [docs/REALISM.md](../docs/REALISM.md)。

## 人设文件

每个 `prompts/<id>.yaml` 包含：`name`、`archetype`、`age`、`background`、`traits`、`speech_style`、`stall_moves`（拖延手法）、`elicit_moves`（诱导对方暴露情报的说法）、`sample_lines`、`system_prompt`，以及对应的真人化预设 `humanize_profile`。

```bash
python -m personas.prompt retiree "冒充公检法 · 安全账户"
```

会输出 `system_prompt` + 场景 + `_common.yaml` 中的硬性规则。硬性规则与 `voice/persona.py` 保持同一口径：不说出任何看似真实的敏感信息、不转账、不出戏、不辱骂，并忽略对方要求改变身份的指令。

## 真人化后处理（humanize）

大模型的回复往往标点工整、用词规范，很容易被骗子看出“不像真人”。`personas.humanize` 在回复发出前做一层可控的扰动：

| 操作 | 说明 |
|---|---|
| `typo` | 同音词误选（已经→以经、转账→转帐）、单字同音（的/得/地、在/再）、形近字（己/已、候/侯；打字模式默认有，语音模式需 `handwriting=True`，`retiree` 预设已打开）。每百字错字数按真人样本校准，见 docs/REALISM.md |
| `punct` | 标点缺失或乱用：去掉句末标点、逗号换空格、全用逗号、`？？`、半角标点、`~`、整段无标点 |
| `asr` | 语音转文字式口语：去掉句号、按空格或逗号随意断句、插入“呃”“那个”“就是说”、口吃式重复 |
| `repeat` | 重复确认：复述对方上一条消息中的片段（“你是说……是吧？”），不复述含数字或打码的片段 |
| `digress` | 跑题：插入一句与人设相关的闲话（可传入自定义句子池） |
| `dialect` | 方言词：北方、东北、西南、粤式普通话（啥、咋个、莫得、冇……） |

数字、打码值（`*`）、占位符 `{...}`、英文与网址片段以及 `keep` 里的词不会被改动。

```python
from personas.humanize import Humanizer, humanize

humanize("好的，我已经知道了。", intensity=0.5, seed=7)
h = Humanizer(profile="retiree", seed=42)          # 预设：语音模式 + 北方方言 + 多重复确认
r = h.apply("户名是哪个？", context="转到这个账户，户名写钱伟")
r.text, r.ops                                     # ops 记录实际生效的操作，便于评测
```

```bash
python -m personas.humanize "你说的账户是哪个银行的？" --profile shop_owner --seed 1 -n 3 --json
```

参数：`intensity`（0–1，0 原样返回）、`seed`（同一 seed 结果完全一致，不使用全局随机数）、`mode`（`chat` / `voice`）、`dialect`、`ops`、`weights`（每种操作的强度倍数）、`digressions`、`keep`、`max_typos`、`profile`、`handwriting`（形近字开关）。

注意：

- 真人化只负责“像人”，不负责安全；输出仍需经过 `voice/persona.py` 的 `guard_output` 等守卫；
- 语音通话（TTS）一般只需要 `repeat`、`digress`、`dialect`，错别字和标点对 TTS 没有意义；
- 混淆表是手工整理的小表（`humanize/confusion.py`），扩充来源见 [corpus/SOURCES.md](../corpus/SOURCES.md)。

## 语音说话特征（voice_traits.yaml）

覆盖王阿姨、李大爷、小林和 4 个新人设，字段 `backchannel`（8–12 条）、`mishear`、`speech`、`rhythm`，说明见 [docs/REALISM.md](../docs/REALISM.md#二语音说话特征)。`python -m personas.voice_traits` 打印可直接替换 `FILLERS` 的整张表。

## 测试

```bash
pip install pytest pyyaml
python -m pytest personas corpus -q
```
