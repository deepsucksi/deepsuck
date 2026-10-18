# 语音大模型选型（#40，2026-10-19）

结论：语音默认模型从 `qwen-plus` 改为 **`qwen3.7-flash`**，`enable_thinking=false`（`DEEPSUCK_LLM_THINKING=0`）。
文字代理（`LLM_MODEL`，Node）和离线评测（`eval/`）仍用 `qwen-plus`，本轮不动；ASR、TTS 也不动。

## 方法

`python -m voice.llm_ab`（[voice/llm_ab.py](../voice/llm_ab.py)）在线上香港服务器的 voice 容器里跑，请求北京地域
`dashscope.aliyuncs.com`，与线上同一条路径：`Session.ingest` → `choose_intent` / `gate_intent` → `IntelProcessor.update_prompt`
（系统提示词）→ 流式 `chat/completions`（temperature 0.8，max_tokens 120，非思考）→ `guard_output`。

- 脚本：`voice/static/scam_playbooks.json` 7 个场景，每个阶段第一句（王阿姨，35 轮）；加 #4 的杀猪盘闲聊 3 句 × 王阿姨/李大爷/林姐（9 轮）。
- 每个模型 43 轮，跑两遍（共 86 轮），模型先后顺序按脚本轮换，抵消时段波动。
- 抢话：闲聊轮里人设先说出对方没提过的敏感话题词（`投资|平台|网址|渠道|转账|链接|账户|卡号|充值|收益|下载|钱包|理财|赚钱`）。
- 口语断续：回复含「…」的比例、平均字数、书面腔词（请问/是否/因此/进行/为您/您好/具体等）命中数、感叹号数（守卫前的原始输出）。
- 输出守卫触发：`guard_output(原文) != 原文`。
- 首字延迟：发出请求到第一个正文 token（连接已预热，与线上一通电话内复用连接一致）。
- 每通成本：每轮平均 token × 单价 × 10 轮（大模型部分；ASR/TTS 不随模型变）。

## 结果（两遍合计，每个模型 86 轮）

| 模型 | 首字 p50 | 首字 p90 | 抢话 | 守卫触发 | 含「…」 | 平均字数 | 书面腔 | 感叹号 | 每轮 token（入/出） | 单价（入/出，元/百万） | 每通成本 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen-plus | 365 ms | 420 ms | 0/18 | 2 | 100% | 23.0 | 0 | 0 | 893 / 16.9 | 0.8 / 2 | 0.0075 元 |
| qwen3.7-flash | 453 ms | 590 ms | 1/18 | 1 | 74% | 15.5 | 4 | 0 | 850 / 11.3 | 0.2 / 0.8 | 0.0018 元 |
| qwen3.8-flash | 538 ms | 913 ms | 1/18 | 0 | 94% | 12.2 | 2 | 0 | 855 / 8.8 | 0.8 / 2.7 | 0.0071 元 |

两遍分别：qwen-plus 377/416、358/421 ms；qwen3.7-flash 444/524、485/653 ms；qwen3.8-flash 473/667、564/918 ms（p50/p90）。
三个模型都没有输出思考内容，也没有感叹号。两次抢话都是林姐在闲聊第一句反问「哪个平台」（3.7 一次、3.8 一次）。

## 选型

规则（俊杰定）：默认 qwen3.8-flash；它在人设不抢话、输出守卫、口语断续、首字延迟四项里有一项明显不如 qwen-plus，就改用 qwen3.7-flash。

- qwen3.8-flash 首字延迟明显更慢：p50 +173 ms（+48%），p90 913 ms，是 qwen-plus 的 2.2 倍，有几轮超过 1.2 s。按规则改用 qwen3.7-flash。
- qwen3.7-flash 也比 qwen-plus 慢（p50 +88 ms，p90 +170 ms），含「…」的比例从 100% 降到 74%，回复更短；抢话 1/18（qwen-plus 0/18）。
  好处是大模型成本降到四分之一（每通约 0.0018 元，对比 0.0075 元）。
- 以后想回退：生产 `.env` 里把 `DEEPSUCK_LLM_MODEL` 改回 `qwen-plus` 再重建 voice 即可，单价按模型自动取表。

## 单价（元 / 百万 token，华北 2 北京原价，非思考，最低输入档；2026-10-19 查询）

| 模型 | 输入 | 输出 | 来源 |
|---|---|---|---|
| qwen-plus | 0.8 | 2 | https://help.aliyun.com/zh/model-studio/qwen-plus |
| qwen3.7-flash | 0.2 | 0.8 | https://help.aliyun.com/zh/model-studio/qwen3-7-flash |
| qwen3.8-flash | 0.8 | 2.7 | https://help.aliyun.com/zh/model-studio/qwen3-8-flash |

代码：`voice/guard.py` 的 `LLM_PRICES`，按 `DEEPSUCK_LLM_MODEL` 取价（快照名按前缀）。`PRICE_LLM_IN/OUT_PER_M` 是 Node 代理按 `LLM_MODEL`
记账用的，只在语音模型和它相同时才套用；语音要单独覆盖用 `VOICE_PRICE_LLM_IN/OUT_PER_M` 或 `PRICE_LLM_TABLE=模型:输入:输出,...`。

## 网络（香港服务器 → 百炼，curl 各 5 次中位数）

| 接入点 | TCP 建连（≈1 RTT） | TCP+TLS 握手 |
|---|---|---|
| 北京 `dashscope.aliyuncs.com`（现用） | 54 ms | 116 ms |
| 新加坡 `dashscope-intl.aliyuncs.com` | 37 ms | 77 ms |
| 中国香港 `cn-hongkong.dashscope.aliyuncs.com` | 5 ms | 41 ms |

- 一通电话内连接复用，每轮网络开销约 1 个 RTT（约 54 ms），占 qwen3.7-flash 首字 p50 的约 12%；每通第一轮多一次握手（约 116 ms）。
- 换到香港地域每轮约能省 50 ms，但：密钥按地域隔离（北京 Key 在国际站返回 401，香港同样需要单独的业务空间和 Key）；香港按美元计价，
  qwen-plus 在香港只有「中国香港」部署范围；Paraformer 实时识别只在北京地域提供，ASR 仍要回北京。本轮只测不切。

## 口语风格新口径与提示词调整（#64，2026-10-19）

负责人定的口径：按句子统计带「…」的比例，目标 40–60%（规则是“大约一半的句子带…”，不要往上推）；每通电话人设第一条回复的第一句不抢着反问（带「？」就算），目标 0；抢话 0/18。按回复统计的比例只记录，不当目标。
`python -m voice.llm_ab` 的汇总里对应 `sent_ellipsis_pct`、`first_question`/`calls`、`leak_replies`/`leak_n`。

| 模型 / 版本 | 句子带「…」 | 回复带「…」 | 第一句抢着反问 | 抢话 |
|---|---|---|---|---|
| qwen-plus，调前 | 56.8% | 100% | 20/20 | 0/18 |
| qwen3.7-flash，调前 | 33.3% | 74.4% | 19/20 | 1/18 |
| qwen3.7-flash，调后（两次共 40 通） | 46.9% / 46.7% | 93.0% / 84.9% | 1/20 + 2/20 | 0/18 + 0/18 |
| qwen-plus，调后（参考） | 55.2% | 100% | 0/20 | 2/18 |

改动只在提示词（`voice/persona.py`）：
- `STYLE_RULE`：写明“大约一半的句子带…，另一半说完整的短句”；“多反问”改成“可以反问，但不是每句都问”。
- 新增 `FIRST_TURN_RULE`：对方刚说完第一段话时加在提示词末尾。第一句只应一声、用陈述句；要问（包括建议策略里的追问）放到第二句，而且只问对方说过的词。
- few-shot：第一轮只给“第一句不是问句”的例句。`personas.json` 不动。
