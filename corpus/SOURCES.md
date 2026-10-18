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

## 话术语料 `site/assets/core/scam_scripts.json` 的来源（情报分析，2026-10-18 核实）

`site/assets/core/scam_scripts.json` 是骗子侧话术的权威版（7 类与 `corpus/scripts/*.yaml` 同名同阶段 id，另加统一的 5 阶段 `phase`）。每条都用自己的话重写，不复制原文，号码与网址一律为占位符。来源标注规则：

- 只有确实对应某一典型案例、通报段落或数据集条目的，才标 `据法院公开典型案例改写`、`据公开典型案例改写`、`据公安机关公开通报改写`、`据公开数据集改写`，并用 `sourceRef` 指明是第几个案例、哪一段或哪一个数据文件；
- 其余据多篇公开反诈宣传、类型通报归纳的，一律标 `据公开反诈宣传改写`，`sourceIds` 只是参考来源，不代表出自某个具体案件；
- 当前 181 条中 40 条有具体对应（法院案例 10、通报案例 16、通报话术段落 11、TeleAntiFraud 对话 3），141 条为反诈宣传归纳。

| 来源 | 链接 | 许可 | 类型 | 用法 |
|---|---|---|---|---|
| 公安部公布五类高发电信网络诈骗案件（公安部（共产党员网转载），2022-05-11） | https://www.12371.cn/2022/05/11/ARTI1652253767367245.shtml | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 公安部：十大电信网络诈骗类型高发 占比近80%（公安部（新华网报道），2023-06-15） | http://www.news.cn/politics/2023-06/15/c_1212199354.htm | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 2025版防范电信网络诈骗宣传手册（公安部刑侦局、国家反诈中心，2025-06-18） | https://www.gov.cn/lianbo/bumen/202506/content_7028568.htm | 未声明（公开发布页面，版权归原发布方） | 官方反诈宣传手册 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 公安部网安局发布网购消费诈骗典型案例（公安部网安局（央视网报道），2025-06-18） | https://news.cctv.com/2025/06/18/ARTIyynY2cbTUYzhL9aehole250618.shtml | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 4 条对应具体条目（sourceRef），其余仅作参考 |
| 国家网信办曝光一批电信网络诈骗典型案例（国家网信办（会同公安部等），2022-04-14） | https://www.cac.gov.cn/2022-04/14/c_1651546285887220.htm | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 4 条对应具体条目（sourceRef），其余仅作参考 |
| 河北省公安厅发布五类高发电信网络诈骗犯罪典型案例（河北省公安厅（澎湃新闻转载），2021-04） | https://m.thepaper.cn/baijiahao_12254985 | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 6 条对应具体条目（sourceRef），其余仅作参考 |
| 假“领导”，真“骗子”！新会公安为公司挽损19万（江门市公安局，2024） | https://www.jiangmen.gov.cn/jmgaj/gkmlpt/content/3/3114/post_3114131.html | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 10 条对应具体条目（sourceRef），其余仅作参考 |
| 防范提示 财务人员警惕“经理”转账指令（江苏省公安厅，2024-11-14） | https://gat.jiangsu.gov.cn/art/2024/11/14/art_89956_11418671.html | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| “领导”加微信让你汇款？“冒充领导”诈骗的升级版来了（湖北省公安厅（中新网报道），2021-01-25） | http://gat.hubei.gov.cn/bmdt/dtyw/202101/t20210125_3303901.shtml | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 收到“注销校园贷、变更贷款人身份信息”？这是怎么回事？（深圳市公安局（深圳市反电信网络诈骗中心），2022-12-10） | https://ga.sz.gov.cn/JMHD/YWZSK/XJGL_ZS/content/post_10332097.html | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 电诈案件典型案例——冒充公检法类（地方政府信息公开（转载公安机关案例），2024-03-13） | https://www.bypc.gov.cn/zfxxgk/bmdwxzjd/xzjd/ghz/fdzdgknr/cwgk/hgc/cwgk/art/2024/art_1a443ab6561a47d5bb72cbb2e8a4daa3.html | 未声明（公开发布页面，版权归原发布方） | 公安 / 网信部门公开发布 | 3 条对应具体条目（sourceRef），其余仅作参考 |
| 充分履行法律监督职能 依法严惩电信网络诈骗犯罪（专题）（最高人民检察院，2021） | https://www.spp.gov.cn/spp/dxwlzp2021/index.shtml | 未声明（公开发布页面，版权归原发布方） | 检察机关公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 不法分子假冒检察机关实施电信网络诈骗犯罪 最高检提醒广大群众谨防上当受骗（最高人民检察院（新华社报道），2018-01-27） | https://www.gov.cn/xinwen/2018-01/27/content_5261348.htm | 未声明（公开发布页面，版权归原发布方） | 检察机关公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 最高检发布检察机关依法惩治电信网络诈骗及其关联犯罪典型案例（最高人民检察院，2023-11-30） | https://www.spp.gov.cn/xwfbh/wsfbt/202311/t20231130_635188.shtml | 未声明（公开发布页面，版权归原发布方） | 检察机关公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 最高检公安部联合发布虚假征信类诈骗典型案例及防范建议（最高人民检察院、公安部，2023-01-19） | https://www.spp.gov.cn/spp/xwfbh/wsfbt/202301/t20230119_599532.shtml | 未声明（公开发布页面，版权归原发布方） | 检察机关公开发布 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 最高法发布电信网络诈骗及其关联犯罪典型案例（7件）（最高人民法院，2025-02-24） | https://www.court.gov.cn/zixun/xiangqing/455701.html | 未声明（公开发布页面，版权归原发布方） | 法院公开典型案例 / 裁判报道 | 5 条对应具体条目（sourceRef），其余仅作参考 |
| 人民法院依法惩治电信网络诈骗等侵犯财产犯罪典型案例（最高人民法院，2025） | https://www.court.gov.cn/zixun/xiangqing/490051.html | 未声明（公开发布页面，版权归原发布方） | 法院公开典型案例 / 裁判报道 | 5 条对应具体条目（sourceRef），其余仅作参考 |
| 【法庭内外】按“剧本”谈恋爱，骗得13万余元（终审裁定，引用话术本）（揭阳市中级人民法院，2024-09-26） | https://www.gdjyfy.gov.cn/jyzycourt/web/content?gid=396101&lmdm=1050 | 未声明（公开发布页面，版权归原发布方） | 法院公开典型案例 / 裁判报道 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 涿鹿法院依法宣判31被告人电信诈骗案（诈骗话术本、虚假投资App）（涿鹿县人民法院（澎湃号·政务），2019-12-30） | https://www.thepaper.cn/newsDetail_forward_5385571 | 未声明（公开发布页面，版权归原发布方） | 法院公开典型案例 / 裁判报道 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| 17名90后以投资外汇为名诈骗230万元（二审判决，业务员按话术本对话）（信阳市中级人民法院（上海市司法局 12348 转载），2018-12-15） | https://sh.12348.gov.cn/sites/12348/news-detail.jsp?category=lpa.Dynamic&entityid=0965479eef8549f7a0465c46339b0960 | 未声明（公开发布页面，版权归原发布方） | 法院公开典型案例 / 裁判报道 | 0 条对应具体条目（sourceRef），其余仅作参考 |
| TeleAntiFraud（多智能体生成的中文电话诈骗对话，ACM MM'25）（JimmyMa99/TeleAntiFraud，2025） | https://github.com/JimmyMa99/TeleAntiFraud | Apache-2.0 | 公开数据集 | 3 条对应具体条目（sourceRef），其余仅作参考 |
| DeepSuck corpus/scripts v0.1（维护者据公开反诈宣传归纳改写）（DeepSuck，2026-10-18） | https://github.com/deepsucksi/deepsuck/tree/main/corpus/scripts | 同本仓库 | 本项目既有语料 | 0 条对应具体条目（sourceRef），其余仅作参考 |

政府、检察院、法院公开页面均未声明许可，版权归原发布方：只取其中描述的作案手法与话术套路这一事实层面信息，全部重写，不保留姓名、地点、金额组合、案号与号码。TeleAntiFraud 为 Apache-2.0（Copyright 2025 Zhiming Ma），只借鉴合成对话的结构并重写，数据集本体不入库。

## 结论

- **可直接用于评测**：TeleAntiFraud（已用）、TeleAntiFraud-28k test（需 HF 账号）、FGRC-SCD（MIT）。
- **可参考结构、需改写后入库**：FGRC-SCD、Smishing-Dataset-IMC25（CC BY 4.0）。
- **不入库**：CCL2023、Telecom_Fraud_Texts_5、FBS_SMS_Dataset、confuse（许可不明或限制非商业）。
- `personas/humanize` 当前内置的是一份手工整理的小混淆表；后续可以从 pycorrector / Confused_Chinese（Apache-2.0）导入更大的表，并在 NOTICE 中注明来源。
