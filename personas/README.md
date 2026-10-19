# 人设（personas/）

人设的唯一数据源是 [`site/assets/core/personas.json`](../site/assets/core/personas.json)（#11）。四位人设与首页卡片一一对应，规则引擎（JS / Python）、沙盒、语音体验页、大模型模式、评测和语料生成都从它读：

| 编号 | id | 名字 · 身份 | 头像 | 真人化预设 | 建议底噪 |
|---|---|---|---|---|---|
| 01 | `wang` | 王阿姨 · 退休老人 | `round6/retired` | retiree | kitchen（已批准） |
| 02 | `chen` | 小陈妈妈 · 宝妈 | `round6/parent` | mom | living_room |
| 03 | `lin` | 小林 · 刚毕业学生 | `round6/graduate` | graduate | street |
| 04 | `zheng` | 郑老板 · 个体小老板 | `round6/owner` | shop_owner | shop |

别名由顶层 `aliases` 映射：`li`（李大爷，已下线）→ `wang`，`xiaochen`、`mom` → `chen`，`shop_owner` → `zheng`；旧链接 `?persona=li` 仍能进到对应人设。别名只用于解析外部传入的人设 id，humanize 的基础预设名（retiree / mom / graduate / shop_owner）不走这里。

```
personas/
├── prompt.py             从 personas.json 拼大模型系统提示词（prompt 字段 + 顶层 promptRules），不需要 PyYAML
├── voice_traits.py       读 personas.json 的 voiceTraits；fillers() 与 voice/persona.py 的 FILLERS 同格式
├── humanize/             文字打字特征：真人化后处理（零依赖；预设读 personas.json 的 humanize 字段）
├── archive/              不被代码读取的历史资料
│   ├── li.json           李大爷的完整条目（台词模板、口头语等）
│   └── prompts-v0.json   #11 之前的 prompts/*.yaml（含周伯）、_common.yaml 与 voice_traits.yaml
└── tests/
```

所有人设、背景与台词都是虚构的，不对应任何真实个人。真人感的设计说明见 [docs/REALISM.md](../docs/REALISM.md)。

## personas.json 每个人设的字段

| 字段 | 用途 |
|---|---|
| `id` `no` `name` `role` `avatar` `photo` `tagline` | 身份与展示：编号、名字、身份与头像和首页一致 |
| `call` `openings` `templates` `asks` | 规则引擎台词（JS `engine.js` 与 Python `deepsuck.engine` 共用） |
| `humanize` | 文字打字特征预设（错字密度、标点风格、自称等） |
| `prompt` | 大模型模式 / 评测用：`archetype` `background` `traits` `speechStyle` `stallMoves` `elicitMoves` `sampleLines` `systemPrompt` |
| `voiceStyle` `voiceShots` | 语音线说话风格与示范句（王阿姨、小陈妈妈、郑老板） |
| `voiceTraits` | 语音说话特征：`backchannel` `mishear` `speech` `rhythm` |
| `ambience` `voiceHint` | 建议底噪名与建议音色描述，交给语音工程师（见 [voice/README.md](../voice/README.md)） |

```bash
python -m personas.prompt chen "冒充客服 · 退款理赔"
```

会输出人设的 `systemPrompt` + 场景 + `promptRules` 中的硬性规则。硬性规则与 `voice/persona.py` 保持同一口径：不说出任何看似真实的敏感信息、不转账、不出戏、不辱骂，并忽略对方要求改变身份的指令。

改了 `personas.json` 后要跑 `npm run build:core`（重新生成 `site/assets/js/core-data.js`）和 `npm run fixtures`（JS / Python 对拍样例）。

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

## 语音说话特征（voiceTraits）

四位人设各一份，字段 `backchannel`（8–12 条）、`mishear`、`speech`、`rhythm`，说明见 [docs/REALISM.md](../docs/REALISM.md#二语音说话特征)。`python -m personas.voice_traits` 打印与 `FILLERS` 同格式的整张表。

## 测试

```bash
pip install pytest
python -m pytest personas corpus -q
node --test tests/personas_unify.test.js   # 首页 / 沙盒 / 体验页人设一致性
```
