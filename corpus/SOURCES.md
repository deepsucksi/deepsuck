# 可复用的公开资源调研

> 调研时间：2026-10-18（北京时间）。许可证以各仓库 LICENSE 文件 / 数据集卡片当日显示为准，使用前请再次确认。“能否入库”指能否把样本文本直接放进本仓库（本仓库代码 Apache-2.0、情报数据 CC BY 4.0）；不能入库的资源仍可以在评测脚本里运行时下载。

## 中文诈骗对话 / 通话

| 名称 | 链接 | 许可证 | 内容 | 能否入库 / 用法 |
|---|---|---|---|---|
| TeleAntiFraud（GitHub 仓库，ACM MM'25） | https://github.com/JimmyMa99/TeleAntiFraud | Apache-2.0（LICENSE 文件头声明；GitHub 识别为 Other） | 多智能体生成的中文电话诈骗/正常对话文本，及数据处理框架 | 已在 `eval/teleantifraud_eval.py` 中运行时下载使用；可以入库少量改写样本（需保留署名与 NOTICE），目前仍保持不入库 |
| TeleAntiFraud-28k 公开版 | https://huggingface.co/datasets/JimmyMa99/TeleAntiFraud ，https://www.modelscope.cn/datasets/JimmyMa99/TeleAntiFraud | Apache-2.0 | 4,000/400 条二分类、27,146/6,807 条多轮 SFT，含音频 | HF 上为 gated（需登录同意条款）；适合作 EVAL 的独立测试集，运行时下载，不入库 |
| FGRC-SCD（基于 CCL2023 任务 6 合成的风险短信与对话） | https://huggingface.co/datasets/shergggggg/FGRC-SCD | MIT（数据集卡片标签） | 中文风险对话/短信，带风险类别（冒充电商物流客服、虚假网络投资理财、虚假信用服务、冒充公检法、冒充领导熟人、网络婚恋交友等）和风险点 | 许可宽松，可作为话术库扩充的参考与分类器的额外测试集；入库前仍按脱敏原则改写 |
| CCL2023 电信网络诈骗案件分类评测 | https://aistudio.baidu.com/datasetdetail/215947 | 评测数据使用协议（需登录下载，未见开源许可） | 真实案情描述的类别标注 | 只参考类别体系；不入库 |
| Telecom_Fraud_Texts_5 | https://github.com/ChangMianRen/Telecom_Fraud_Texts_5 | 仓库标 GPL-3.0，README 另写“仅限高校科研、禁止商业用途” | 正常 + 4 类诈骗文本（公检法、贷款、冒充客服、冒充领导熟人） | 条款相互冲突且含非商业限制，**不入库**；可在本地做补充评测 |

## 中文诈骗 / 垃圾短信

| 名称 | 链接 | 许可证 | 内容 | 能否入库 / 用法 |
|---|---|---|---|---|
| FBS_SMS_Dataset（CCS'20） | https://github.com/Cypher-Z/FBS_SMS_Dataset | 无许可证文件，要求注明出处并引用论文 | 约 1.4 万条伪基站短信，14 类，联系方式已匿名 | 无明确许可，**不入库**；可本地评测短信侧分类 |
| Chinese Camouflaged Spam (CCS) | https://github.com/Hypatiaalegra/Chinese-Camouflage-Spam-dataset | 未确认（调研时仓库返回 404） | 23,788 条，含原文、纠错文本、17 类意图，约 42% 含有意/无意错别字 | 暂不可用；其“伪装错别字”统计对 `humanize` 的错别字建模有参考价值，恢复后再评估 |
| Smishing-Dataset-IMC25 | https://github.com/reportsmishing/Smishing-Dataset-IMC25 | CC BY 4.0 | 公开用户举报的短信钓鱼，带诈骗类型与诱导原则标注（以英文为主） | 可入库（需署名）；主要参考其标注体系 |

## Scam-baiting（拖住骗子）项目

| 名称 | 链接 | 许可证 | 要点 | 可借鉴 |
|---|---|---|---|---|
| ai-in-the-loop（Supreme Lab） | https://github.com/supreme-lab/ai-in-the-loop | MIT | 254 段真实 scam-baiting 对话、多任务数据；评测维度含 PII 风险、互动度、对话时长 | 评测指标设计（PII 泄露、互动度、拖延时长）；英文，不直接用作中文语料 |
| ScamBuster | https://github.com/laugiov/scambuster | MIT | 邮件蜜罐，多智能体：分类、IOC 提取、人设生成、PolicyGuard、按场景自适应选人设 | 人设按诈骗类型自适应选择（UCB）、TTP 闭集标签 |
| ReplyTrap | https://github.com/mlapis/replytrap | MIT | 邮件 scam-baiting，回复间隔从几分钟到两天模拟真人 | 时间维度的真人化（回复延迟） |
| Synthetic-Data-for-Scam-Detection | https://github.com/BothBosu/Synthetic-Data-for-Scam-Detection-Leveraging-LLMs-to-Train-Deep-Learning-Models | MIT（代码）；HF 数据集 Apache-2.0 | 单/多智能体生成诈骗对话，受害人带性格设定（多疑、轻信、强硬） | 受害人性格参数化的思路 |
| BothBosu/Scammer-Conversation | https://huggingface.co/datasets/BothBosu/Scammer-Conversation | Apache-2.0 | 1,000 段英文 scammer / baiter / 正常对话 | 英文，仅参考 |
| LLM scambaiting 实测论文（Send to which account?） | https://arxiv.org/abs/2509.08493 | 论文 | 5 个月 2,600+ 次真实互动；信息披露率约 32%、人工采纳率约 70% | EVAL 指标：信息披露率（IDR）、人工采纳率（HAR）、首轮回复率 |

## 真人化（错别字 / 口语）相关

| 名称 | 链接 | 许可证 | 用途 |
|---|---|---|---|
| pycorrector | https://github.com/shibing624/pycorrector | Apache-2.0 | 中文纠错工具，自带同音/形近混淆集；可用来扩充 `personas/humanize` 的混淆表，或反过来检测“真人化”后的文本是否过于离谱 |
| Confused_Chinese | https://github.com/Macielyoung/Confused_Chinese | Apache-2.0 | 中文形近、音近字混淆集 |
| chinese_confusion | https://github.com/currenttime/chinese_confusion | MIT | 生成字级形近、音近混淆语料 |
| confuse | https://github.com/zejunwang1/confuse | 未声明许可证 | 字/词级同音、近音、形近混淆集；无许可证，**不可直接复制** |

## 结论

- **可直接用于评测**：TeleAntiFraud（已用）、TeleAntiFraud-28k test（需 HF 账号）、FGRC-SCD（MIT）。
- **可参考结构、需改写后入库**：FGRC-SCD、Smishing-Dataset-IMC25（CC BY 4.0）。
- **不入库**：CCL2023、Telecom_Fraud_Texts_5、FBS_SMS_Dataset、confuse（许可不明或限制非商业）。
- `personas/humanize` 当前内置的是一份手工整理的小混淆表；后续可以从 pycorrector / Confused_Chinese（Apache-2.0）导入更大的表，并在 NOTICE 中注明来源。
