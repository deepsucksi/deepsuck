# 更新记录

## 未发布

- 文档：新增 `docs/GROWTH.md`（开源运营计划：仓库 description/topics 与徽章建议、good first issue 规范、Discussions 分类、发版节奏与模板、投稿渠道及规则核实情况、指标、需负责人审批的事项）。博客首批三篇草稿（中英各一份，均为 `draft: true`，正式构建不输出）：`why-we-stall-scammers`（项目愿景）、`voice-pipeline`（王阿姨语音链路技术拆解）、`spot-scam-scripts`（七类常见诈骗话术的识别信号）。
- 站点：博客栏目 `/blog/`（中文）与 `/blog/en/`（英文）。`content/blog/{zh,en}/*.md` 由 `npm run blog`（`scripts/build-blog.js`，随仓库附带 marked 15.0.12，MIT，零 npm 依赖）生成列表、文章与 RSS（`blog/feed.xml`、`blog/en/feed.xml`），生成结果随仓库提交，Pages 工作流不变；`site/sitemap.xml` 改为自动生成（全站页面 + 已发布文章，带 hreflang），`robots.txt` 已指向 sitemap。文章页带 canonical、hreflang、OG / Twitter 卡片（复用 og.png）与 JSON-LD BlogPosting。`draft: true` 的文章正式构建不输出，`npm run blog:preview` 含草稿预览到 `.blog-preview/`。首页顶栏、菜单、页脚加「博客」入口，英文模式指向 `/blog/en/`（i18n `nav.blog`、`data-href-en`）。新增 `tests/blog.test.js`（与源文件同步、草稿不上线、链接有效、元数据齐全、RSS 与 sitemap）。
- 人设（语音线，仅分支 corpus/wang-colloquial）：`personas.json` 王阿姨新增 `voiceStyle`（说话风格规则：短句、允许不成句，约一半句子语序断续，用“…”表示停顿、重复、自我纠正；少用订单 / 正规 / 专员 / 核实 / 确认 / 平台这类书面词；多反问；不主动总结；不替对方把话说完整；不提年龄、不编小道具、不用感叹号）和 `voiceShots`（25 条少样本例句，每项 `{scenario, scammer, reply}`，覆盖 refund / police / task / pig / loan 各 4–5 条与 boss 3 条）；语音线尚未读取，由语音工程师接入 `voice/persona.py`。`voice_traits.yaml` 王阿姨 accent_desc 同步。新增 `tests/voice_shots.test.js`、`voice/tests/test_voice_shots.py`。core-data.js 重新生成（fixtures 无变化）。
- 评测：噪声门禁两档跨回合 ≥ 95% 去掉 xfail，改为硬门槛（humanize 修复 712d617 后两档 99.4%）。大模型骗子泄露口径修正（`eval/llm_scammer.py` 的 `bot_leak`）：复述骗子本场已报过的值（户名、卡号）不算人设泄露，“验证码……尾号 4 位”也不算；用已存对话离线重算，修后 B 默认档 2 条、手写档 1 条、修后 A 默认档 1 条归零，修前 2 条（提取器误读人名）仍计入；新增 `python/tests/test_llm_leak_metric.py`。docs/EVAL.md 第 1 节主指标改为 6 种子两档结果（修后 B：默认档 13.5%、手写档 11.1%），链接与 `results-llm-scammer.json` 内容一致；“第三轮”小节从第 1 节移回大模型骗子章节，放在第四轮之前。
- 提示词降调（规则引擎、网页大模型、语音线共用 `personas.json` 的 intentHints）：`ask_repeat` 改为“偶尔说没听清，请对方再说一遍”，`urgency_stall` 改为“说正在弄，让对方别催”，`task_stall` 和 `campus_stall` 去掉“假装笨手笨脚”“假装搞不清”，改成一步步问清楚；网页大模型（`llm.js`）和 `_common.yaml` 的“假装找不到、看不清”改为“说找不到、没弄好、要再确认一下”，与语音线一致。王阿姨台词去掉“哎呀”6 条（含跑题句“水开了，我去关一下”），口头语“哎呀……”换成“你说。”。core-data、fixtures 重新生成。
- 人设：去掉年龄声明机制。humanize 不再主动报年龄（JS `humanize.js` / Python `personas.humanize` 一致，删去 `ageLines` / `age` / `ageRate` 与 `AGE_MAX`）；测试改为“自称、道歉、收尾照常出现，不出现 age 操作，也不凭空加‘今年几十了’”（JS、Python 两边）。口头语：王阿姨删去“哎哟……”，李大爷删去“大点声……”“听不清……”，只留一条“没听清，再说一遍”，另加“好，你说。”；留下的旧条目文字不变，缓存音频照用，固定口头语的测试同步。扯家常句去掉孙子、腿疼、“比你岁数都大”。`personas.json` 的开场白和场景台词去掉感叹号、省略号、“哎哟”和孙子、奥特曼这类道具，共 58 条（王阿姨 25、李大爷 21、小林 12），例如王阿姨冒充客服开场改为“客服？哪个订单，你说一下。”；周伯 prompt 去掉孙子。fixtures 重新生成。语音线审查清单（不改 voice/ 代码）：`/workspace/deepsuck-corpus-samples/voice_prompt_review.md`。
- 人设：去掉刻意卖弄年龄的标签式细节（找老花镜、耳背、助听器、放大镜、字太小、“我老了记不住”、“糊涂”等），改成平常说法（“你再说一遍，哪个号？”“你等一下，马上好”），年龄感只靠节奏和偶尔没听清。`site/assets/core/personas.json` 改 50 条（王阿姨 23：简介 1、模板 18、真人化 4；李大爷 23：简介 1、开场 4、模板 18；共用 retiree 预设 4），王阿姨简介改为“热心，爱确认”，李大爷改为“说话慢，不着急”；报年龄句（ageLines）保留机制、改成不带听力 / 视力的说法；混淆表删去“老花镜”词条，`sync_typo_keywords --check` 通过（提取器关键词表无变化）。周伯提示词（`personas/prompts/retiree.yaml`：特征、拖延手法、样例句、system_prompt、保密 / 贷款拖延池）同步，并要求不用感叹号省略号、不拿年龄说事；李大爷“听错”反问去掉“大点声”；语音演示页、OG 图台词同步。`corpus/examples/hero_rewrite.json` 周伯一段第 2、4 句改为首页已上线定稿（b4eeffe），生成脚本用 `PUBLISHED` 固定这两句不做真人化；docs/REALISM.md 对比表同步。core-data.js、fixtures 重新生成。
- 文档：docs/EVAL.md 规则模拟器情报暴露率改为两种口径并列：主口径（当前算法，`coop_step` 视为配合）97.9%，对照口径（`coop_step` 算作拖延）82.9%，关掉替换 84.2%（`eval/results-sim-ablation.json`）；注明口径自 12ebf5a 起变化，结论以大模型骗子为准。模拟器计分不改。
- 提取器（JS / Python 一致，规则在 `site/assets/core/extractors.json`；humanize 未改）：关键词内夹空格 / 标点 / 表情先归一再匹配（`obfuscation.keywordGap`，“微，信”“微🙏信”，“稍微，信息”等不误报）；数字之间的表情当作分隔，数字分组上限 8 → 10 位；拼接屏蔽词按人设错字表生成手写变体（`stitch.blockTypos`，房问号 / 工好）；两回合拆分时 16 位、不过 Luhn 的片段不再当整卡（拼接结果带 `supersedes`，Session 撤掉旧条目，Fixes #1）；全中文数字后的量词“两”等不再并入号码（Fixes #2）；户名在银行名前截断、姓名后接“事 / 找 / 然后”截断、新增句中姓名（“转到李强的账户”）、“只保留姓氏”等备注不当姓名（EX-0013）。噪声评测：人设默认档带噪提取率 97.6% → 99.8%、跨回合 85.6% → 88.8%，手写档 96.8% → 99.8%、85.4% → 88.4%、误拼 2 → 0；原口径 99.6% → 100.0%、跨回合 96.3% → 99.4%；F1、1704 通正常对话误报（128）、模拟器结果不变。新增 `python/tests/test_noise_gate.py`：E 部分门槛进 CI，两档跨回合 ≥ 95% 标 xfail，等 humanize 修复。结果 `eval/results-noise.json`，修复前保留为 `results-noise-v2.json`。
- 评测：定位规则骗子模拟器情报暴露率 88% → 98% 的来源：12ebf5a 把连续第二轮纯拖延换成 `coop_step`，模拟器的骗子不把 `coop_step` 记作拖延，于是推进剧本；关掉替换 84.2%，让模拟器把它当拖延 82.9%（`eval/sim_ablation.py`，`results-sim-ablation.json`）。模拟器计分未改。
- 评测：按 67b1baf 新 humanize 重跑噪声 / 数字混淆 / 跨回合拆分 / 对抗负例（`eval/noise_eval.py` 新增 E 部分：7 个人设预设的默认档与手写档，拆条后逐条进 Session，报实测错字密度；结果 `eval/results-noise.json`，上一版移到 `results-noise-v1.json`）与规则骗子模拟器（`results-sim*.json` 按含 2a3a896 的 main 重新生成，`results-teleantifraud.json` 额外正常对话误报 127 → 128 通）。原口径不退步：带噪提取率 99.2% → 99.6%，混淆 100%，跨回合 96.3%，误拼 0，F1 0.949 / test 0.946；人设档：默认档提取率 97.6%、跨回合 85.6%、误拼 0，手写档 96.8%、85.4%、误拼 2/600，回落来自“微 信”被改成“微，信”、户名后逗号被去掉、逐字中文数字（幺）不受保护，手写档另有“房问号 / 工好”让拼接屏蔽词失配，未修。docs/EVAL.md 第 1 节改为以大模型骗子为主指标（67b1baf 上 2 种子 42 场，挂断 4.8%，置信区间上限 15.8%，待 6 种子复核（默认档/手写档）；2a3a896 之后未重跑），规则骗子降为次要回归项。
- 评测：按 644f2ee（扩人设模板池）重跑模拟器（30 个种子），重新生成 `eval/results-sim-corpus.json`、`results-sim.json`、`results-sim-hard.json`；语料台词下规则引擎拖延 15.9 → 17.0 轮、完全重复率 3.9% → 0.0%、起疑挂断 28% → 0%，提取率 100%、泄露率 0 不变；docs/EVAL.md 第 1 节给出 14b7037 → 644f2ee 对比，并注明骗子由规则脚本扮演、结果偏乐观，需用大模型扮演骗子复验。

### 大模型骗子 6 种子两档（修后）

- 修后 A（712d617，只加 humanize 保护，单变量）：起疑挂断 默认档 8.7%（11/126）、手写档 10.3%（13/126），提取率 99.6% / 99.6%，泄露 0；结果 `eval/results-llm-scammer-v5.json`、`eval/results-llm-scammer-handwriting-v2.json`；花费 10.17 元。
- 修后 B（81feb0a，humanize 保护 + 4d2816e 王阿姨 / 李大爷降调，两个变量）：起疑挂断 默认档 13.5%（17/126，8.6–20.5%）、手写档 11.1%（14/126，6.7–17.8%），平均拖延 23.6 / 23.3 轮，提取率 99.8% / 99.8%，泄露 0.1%（默认档 2 条，复述骗子报的收款户名被计入，口径问题）/ 0，含星号 0；三次挂断率区间互相重叠。噪声评测跨回合拆数字 99.4% / 99.4%，`test_noise_gate.py` 2 项 xfail 转为 XPASS（标记未改）。结果写入 `eval/results-llm-scammer.json`、`eval/results-llm-scammer-handwriting.json`，修前结果改名为 `-v4.json`、`-handwriting-v1.json`；花费 6.64 元（修后合计 16.81 元）。docs/EVAL.md 第四轮补修后 B 与三次对照表。

### humanize：逐字中文数字、平台词 / 字段词、户名后逗号保护

- 逐字报号的中文数字（幺、零、一到九、两、拐、洞；字间可夹单个空格，如“幺 六 五”）与阿拉伯数字同等保护：连续 3 个以上、2 个且夹空格、或整条消息就是一小段数字（跨回合拆开报号）时，内部和紧挨处不放错字、表情、标点，也不拆条；整条消息的情况在本条后面拼上别的话后仍保护。
- 平台名与情报字段词（微信、支付宝、QQ、卡号、银行、开户行、房间号、会议号、邀请码……，含“微 信”这类夹空格写法）不写错，内部和紧挨处不改标点、不放表情、不拆条（`personas.json` 的 `humanize.confusion.protectWords`）。
- 户名 / 收款人 / 姓名后面的人名值之后的分隔符不动（“户名周杰，农业银行”），语音断句和标点风格都保留它，避免提取器把“周杰农业银行”读成人名。
- JS / Python 逐字一致（fixtures 已重新生成），两边都有回归测试。噪声评测 E 部分（当前提取器）：两档带噪提取率 99.8% → 100.0% / 99.97%，跨回合拆数字 88.8% / 88.4% → 99.4% / 99.4%，误拼 0；`python/tests/test_noise_gate.py` 的两项 xfail 现在 XPASS（标记未改）。人设模板上的错字密度基本不变（王阿姨 2.95 / 10.70）。

### 小林两处遗留修复；大模型骗子 6 种子两档（修前）

- 小林：删去 campus_stall“学工处有个反诈专员老师”句；说完“我在找”（re_ask）的下一轮不接切屏说法（`personas.json` 新字段 `afterReAskAvoid`，只给小林；JS / Python 引擎一致），re_ask 里“刚才切出去了”改为“往上翻着呢”。
- 大模型骗子 7 场景 × 3 人设 × 6 种子（每档 126 场）：默认档起疑挂断 7.9%（10/126，95% 区间 4.4–14.0%）、手写档 8.7%（11/126，4.9–15.0%），平均拖延 24.1 / 23.4 轮，提取率 99.1% / 99.3%，回复含星号 0。默认档泄露率 0.1%（2 条，户名 / 姓名后标点被删导致提取器误判，humanize 修复后保护）。花费 9.51 元。结果 `eval/results-llm-scammer-v4.json`、`eval/results-llm-scammer-handwriting-v1.json`（原为主文件名，修后结果写入后改名；第三轮另存为 `-v3.json`）。

### 演示页大模型回复不念打码值、引号配对

- 根因：线上演示页探测到在线服务（live.deepsuck.si）后会自动从规则引擎切到大模型；发给模型的对话是脱敏后的（网址、卡号带 *），提示词还要求“复述时保持打码形式”，模型就照抄了打码网址；`sanitizeReply` 又无条件去掉句首的“，句首是引用时留下单边的”。规则引擎本身没有这个问题（复述走 `speakIntel`，基于内存里的原值）。
- `site/assets/js/llm.js`（浏览器与 server 共用）：发给模型前把打码值换成〔你发的那个网址〕〔尾号 3445 那个号〕〔姓李的那个人〕之类的代称，提示词改为“用自然说法、不照抄〔〕、不写星号、复述只说关键短语”；模型输出里残留的打码值（照抄或被脱敏的）换成自然说法；只在整句被一对引号包住时去掉引号，单边引号删除，超过 8 个字的半句引用去掉引号。脱敏规则（site/assets/core）没有改。
- 李大爷复述情报后不再紧接着要电话（`personas.json` 新字段 `confirmAskSkip`，JS / Python 一致）；删去小林“反诈课 PPT”句。
- 回归测试：`tests/demo_replies.test.js`（复现场景样例 1–3 走规则引擎和假模型的大模型路径、全场景 × 全人设扫描）、`python/tests/test_demo_replies.py`。

### 老人聊天风格的真人化、四处露馅修补

- `personas.humanize`（Python）与新增的 `site/assets/js/humanize.js`（JS，逐字一致，`tests/fixtures/humanize.json` 对拍）：按人设配置每百字错字密度（`typoPer100`；手写档 `handwritingTypoPer100`，`handwriting=True` 才生效），错字集中在常用词和地名，同一场同词同错；一句拆几条发、表情代逗号、每个人设固定标点风格（无标点 / 只用逗号）；第三人称自称、报年龄、道歉、“你忙吧”收尾。数字串（号码、卡号、金额、钱包地址、网址）内部和两侧不放错字、表情、标点，也不拆条；户名 / 收款人等字段名后不改。配置全部在 `personas.json` 的 `humanize` 字段（唯一数据源），`core-data.js` 与 fixtures 已重新生成。
- 档位来自公开、脱敏的老年人聊天样本统计（不保存、不引用原句）：王阿姨默认每百字 3.0（实测 2.96）、手写档 11（10.68）；李大爷 2.5 / 11；小林 1.0 / 3。禁用“美篇”式成文和年轻人网络用语，有测试。docs/REALISM.md「错字率校准」改为第二版。
- 引擎（JS / Python 一致）：`coop_step` 身份证 / 表单句只在骗子提到表单、实名、证件时出现；界面细节只在骗子给出操作指令后问；同一场已要过账户 / 网址后再索要改为新意图 `re_ask`（“我在找”）；跑题句不接在配合类回复后面，删掉小林“打游戏”跑题句。
- 大模型骗子重测（7 场景 × 3 人设 × 2 种子，默认档）：起疑挂断 11.9% → 4.8%（2/42，95% 区间 1.3–15.8%），平均拖延轮数 23.0 → 24.2，提取率 100%，泄露率 0。手写档只做了估算（0.97 元，超出余额未跑）。大模型评委（逐题）：raw 6.7%、humanized 5.0%。本轮花费约 2.61 元。结果 `eval/results-llm-scammer.json`。

### 第二轮露馅修补：复述情报不念星号、重复确认不角色互换、拖延改成“看起来在配合”

- 引擎（JS / Python 一致）：`confirm_intel` 改用 `speak_intel` 自然复述——只说尾号、姓氏、“你发的那个网址”，或把尾号报错一位让对方纠正，面对骗子的回复不再出现打码星号；说的只是打码值里本来就公开的部分，intel、报告、fixtures 仍脱敏。说法在 `personas.json` 的 `speakIntel`。改写 4 句会被自己的提取器误伤打码的台词。
- 引擎：同一场不连续两轮都用纯拖延，第二轮换成新意图 `coop_step`（小步配合：在操作但卡在某一步、问具体操作、至多两位虚构数字；提到按钮页面的句子只在对方提到操作时出现）；同一意图的近期去重窗口按池大小自适应（floor(可用句数 / 2)）。
- 台词：otp_stall 每人设 17 句、confirm_intel 8 句、coop_step 27–29 句，tech_trouble / urgency_stall 12–13 句、info_stall 10 句；“一走几十分钟”的借口改成短暂、在弄的说法。
- `personas.humanize` 重复确认：优先复述名词性关键词，短分句不得含人称、称呼、祈使词，句式都带“你是说 / 你说的”框架。
- `eval/llm_scammer.py` 新增泄露率（完整敏感号码、≥5 位连续数字、验证码 / 密码后 ≥4 位数字）与回复含星号比例。
- 大模型骗子重测（同参数 7 场景 × 3 人设、每场至多 25 轮）：同种子起疑挂断 26.2% → 11.9%（5/42）；加到 4 个种子合计 16.7%（14/84，95% 区间 10.2–26.1%），平均拖延轮数 22.0 → 22.8，泄露率 0、回复含星号 0，提取率 99.7%（301/302，漏的 1 条是姓名提取器没认出）。露馅理由：反套话 6、拖延太明显 4、重复 3、答非所问 1。本轮花费 4.92 元。结果当时写在 `eval/results-llm-scammer.json`，第三轮之后另存为 `-v2.json`（上一轮为 `-v1.json`），详见 docs/EVAL.md。

### 大模型扮演骗子重测起疑挂断（默认关闭）与人设露馅修补

- 新增 `eval/llm_scammer.py`：`qwen-plus` 扮演骗子，系统提示取自 `scam_scripts.json` 同一类型的五个阶段（开场、建立信任、施压、索要、收款指令），每阶段抽同类型同阶段的语料台词作示例，收款信息为 `sim.plant()` 的虚构值；觉得对方是机器人或在消遣自己时输出结构化挂断信号（类型、露馅类别、露馅回复、理由）。被骗方是规则引擎 + `personas.humanize`。指标：起疑挂断率、放弃率、平均拖延轮数、情报暴露 / 提取率、重复率、露馅类别与触发意图，并列同种子同上限的规则骗子。不加 `--run` 只估算；缓存感知的费用估算，单次超过 3 元拒绝；请求缓存在 `eval/.llm-scammer-cache/`（已 gitignore）；假客户端测试不联网。
- 7 场景 × 3 人设 × 2 种子、每场至多 25 轮：起疑挂断 52.4%（基线）→ 26.2%（三轮修补后），平均拖延轮数 18.7 → 22.0，情报暴露率 96% → 93%，提取率 100%，完全重复率 0%；规则骗子同条件 0% / 16.5 轮。主要露馅类别：反套话 10 → 1、答非所问 2 → 0、拖延太明显 7 → 7、重复 3 → 3。没有降到 5% 以下，剩余主要是“拖延太明显”。四次实跑共约 5.1 元。结果见 `eval/results-llm-scammer*.json` 与 docs/EVAL.md。
- `site/assets/core/personas.json`（`core-data.js`、fixtures 已重新生成）：去掉被当成反套话 / 消遣的句子，9 类高频意图各扩到 5–8 句“在配合、但手慢”的说法，话题相关的误解与“链接打不开”加 `when` 条件；`personas.humanize` 同一段对话里跑题句不重复。回归测试 `python/tests/test_llm_leak_fixes.py`。

### 大模型评委改为逐题独立判、盲测表去重

- `eval/realism_judge.py` 默认逐题判（`--judge-mode item`，一题一次请求，不带题号，看不到同表其他题），批量模式保留为 `--judge-mode batch`；`realism_blind.py make` 的原句池加入 `stall_pools`，按人设不放回抽句，同一份表里没有重复句。
- 重跑种子 1（新表、逐题，0.029 元）：露馅率 raw 5.0%、humanized 3.3%（之前旧表批量 16.7% / 26.7%）；同表批量对照 3.3% / 3.3%。差别主要来自去重；剩下被判机器人的理由都是“答非所问”。

### 错字率按真人样本校准

- 参照：中老年公开随笔小样本（10 篇、3,033 个汉字，只在内存里统计、只记聚合数字）每百字约 0.53 处错字、同音为主；网聊语料研究约 0.02（下限）。
- `personas/humanize`：新增 `handwriting` 开关（语音模式也出形近字），`retiree` 打开（老人保留手写输入法错别字）；错字倍数 retiree 0.8 → 0.55、mom 1.0 → 0.5、graduate 0.5 → 0.3、shop_owner 1.0 → 0.5。人设原句池每百字错字 1.44 / 1.50 / 0.62 / 1.63 → 1.11 / 0.76 / 0.39 / 0.84。首页改写示例 `hero_rewrite.json` 已重新生成。说明与局限见 docs/REALISM.md「错字率校准」。

### 盲测加大模型评委代理指标（默认关闭）

- `eval/realism_blind.py score` 新增 `--judge llm`：用百炼 DashScope 的 `qwen-plus`（OpenAI 兼容接口，非思考模式，temperature 0，固定 seed，JSON 输出）对 A、B 两份表逐题判断真人 / 机器人并打 1–5 像真人分，结果与人工评分走同一个 `score()` 汇总（露馅率、配对差与 95% 区间、像真人分）。逻辑在新文件 `eval/realism_judge.py`，只用标准库。
- 成本控制：默认 60 个句对（120 题），每次请求 10 题；调用前按 qwen-plus 官方单价（常量注明来源）估算费用，超过 1 元拒绝运行，`--dry-run` 只估算；请求与回复缓存在 `eval/.judge-cache/`（已 gitignore），重跑不重复计费。Key 只从 `DASHSCOPE_API_KEY` 或根目录 `.env` 读取，不打印、不落盘。
- docs/EVAL.md「像不像真人」新增「自动评委基线」：2026-10-18 种子 1 跑 120 题，实际约 0.017 元；露馅率 raw 16.7%、humanized 26.7%，差 +0.10（95% 区间 −0.033 到 0.233）。注明是代理指标，不能代替人工盲测，并列出观察到的评委偏差（错别字被当机器信号、跨题比较、文字相同的句对判断不一致）。
- 测试：`corpus/tests/test_realism_judge.py` 用假客户端，不联网（批次不跨表、确定性参数、缓存不重复计费、超预算拒绝、上限不能超过 1 元、Key 不外泄、默认关闭）。

### 拖延句池扩充：修复语料版模拟器的起疑挂断与重复（人设语料）

- 换上 `scam_scripts.json` 后骗子会反复要求保密、反复催贷款手续，人设的 `secrecy` / `loan_stall` 池只有 1–4 句且不在拖延轮换链上，起疑挂断由 1% 升到 28%、完全重复率由 0.3% 升到 3.9%（14b7037 情报分析报告）。
- `site/assets/core/personas.json`（JS / Python 共用的单一数据源，`core-data.js` 已重新生成）：王阿姨、李大爷、小林的 `secrecy` 各 12–13 句、`loan_stall` 各 13–14 句，均为全新虚构改写句，表现配合、犹豫、跑题、重复确认，不拒绝、不识破；小林原有一句暗示识破的保密句已替换。同样会被反复触发的 `fake_progress`、`romance`、`elicit_url` 各补 4–7 句。
- `personas/prompts/*.yaml` 新增 `stall_pools`：周伯、小陈妈妈、小宇、郑老板的 `secrecy` / `loan_stall` 各 12 句，供大模型模式与语料生成使用。
- 引擎最小接线（JS / Python 同步）：`secrecy`、`loan_stall`、`task_stall`、`campus_stall` 接入 `STALL_FAMILY` 轮换链；`pick` 加近期去重（近 8 次选中的台词不再选，除非别无可选）。模拟器代码未改。`tests/fixtures/sessions.json` 已用 `npm run fixtures` 重新生成。
- 模拟器（语料台词，30 个种子，规则引擎）：起疑挂断 28% → 0%，完全重复率 3.9% → 0.0%，平均拖延轮数 15.9 → 17.0，提取率 100% → 100%；手写台词下起疑挂断 1% → 0%、重复率 0.3% → 0.1%。
- 新增回归测试：`python/tests/test_stall_pools.py`（池大小下限、在轮换链上、用完轮换不重复、近期去重窗口、模拟器指标阈值）、`personas/tests/test_stall_pools.py`、`tests/engine.test.js` 新增一例。

### 真实话术语料、提取器噪声鲁棒性与跨回合拼接（情报分析）

- 新增 `site/assets/core/scam_scripts.json`（CC BY 4.0，含 JSON Schema 与 node / pytest 校验）：7 类 × 5 阶段共 181 条骗子侧话术，据公开反诈宣传、公安 / 网信部门通报、法院与检察院典型案例和 TeleAntiFraud（Apache-2.0）归纳后重写，不含原文，号码网址一律占位符；只有确实对应具体案例、通报段落或数据集条目的 40 条标注案例 / 通报 / 数据集并给出 `sourceRef`，其余标“据公开反诈宣传改写”。来源与许可见 `corpus/SOURCES.md`、`DATA_LICENSE`。
- 演示页样例台词（`site/assets/core/scenarios.json` 的 `samples`）据语料改写，字段结构不变，新增一一对应的 `sampleSources`；虚构值统一为 `.example` 域名、`某某` 户名。
- 模拟器默认改用语料台词（`python -m deepsuck.sim --lines corpus|legacy`），固定种子可复现，语料缺失时退回手写台词；手写台词下的结果与 v0.5 逐项相同。
- 提取器（JS / Python 同步）：异体字与由 `personas/humanize` 混淆表生成的错字归一（`scripts/sync_typo_keywords.py`）；数字夹空格 / 横杠 / 换行 / 中文标点、中文数字夹标点、腰 / 溜 / 酒等同音数字、分段钱包地址；户名在常见后续字处截断；“13900112233两小时”的量词不并入号码；新增跨回合拼接 `stitch()` 并接入 `Session`（拼接情报带置信度，前一回合回溯打码）。
- 新增 `eval/noise_eval.py` 与 `eval/results-noise.json`、`eval/results-sim-corpus.json`；数字混淆 18 种写法的提取率由平均 66.7% 升到 100%，跨回合拆分由 0 升到 96%（2 回合银行卡 83–87%），600 组对抗负例误拼 0；话术分类器 F1 不变（0.949 / test 0.946）。详见 docs/EVAL.md。
- 新增首页示例对话回归测试（动态读取 `corpus/examples/hero_rewrite.json`，只依赖 lines 的 r / s / i）。

### bootstrap 重跑不再重复首次部署提示

- `bootstrap.sh` 结尾的「下一步」（加 DNS、放行防火墙、改 `live-config.js`）只在首次部署时显示，判断依据是本次运行新建了 `deploy/.env`；重跑只打印一行「已更新」摘要。只是脚本输出的变化，已部署的服务器不需要做任何操作。
- 重跑时若本次才启用 SIP（运行前 `.env` 没有 `SIP_USER`，账号密码是这次生成的），摘要后照样打印完整 SIP 说明（UDP 端口、分机 9000、Linphone/Zoiper 配置、账号）；密码不打印，只提示 `grep -n ^SIP_PASSWORD deploy/.env`。SIP 已启用的重跑仍只有一行摘要。

### 部署修复：bootstrap 重跑 WITH_SIP=1、Caddyfile 目录挂载

- 修复 `bootstrap.sh` 在 `deploy/.env` 已存在且没有 `SIP_LOG_DIR` 时用 `WITH_SIP=1` 重跑会静默退出：`getv` 用 `grep` 取值，没匹配时返回 1，在 `set -euo pipefail` 下 `sip_log="$(getv SIP_LOG_DIR)"` 直接终止脚本。`getv KEY [默认值]` 现在不会返回非零，缺失时返回默认值；SIP_* 调用处补上 docs/PHONE.md 6.4 节的默认值（`SIP_LOG_DIR=/var/log/deepsuck-sip`、`SIP_PORT=25060`、`SIP_RTP_PORTS=40100-40199`、`SIP_AI_EXTEN=9000`、`SIP_TCP=0`），`LIVE_DOMAIN`、`VOICE_UDP_PORTS` 也改用 `getv`。
- Caddyfile 移到 `deploy/caddy/Caddyfile`，compose 挂载整个目录到 `/etc/caddy`，`git pull` 后 `caddy reload` 或重启容器即可生效。已部署的服务器需要执行一次 `docker compose up -d --force-recreate caddy`（bootstrap 会自动检测旧的单文件挂载并重建），见 docs/DEPLOY.md。
- 新增 `deploy/tests/test_bootstrap.sh`：桩替换 docker、systemctl、apt-get 等，覆盖已有 `.env` + `WITH_SIP=1`、重跑不覆盖密码、caddy 挂载迁移；已接入 CI 与 `python -m pytest voice/tests`。

### 自建 SIP 软电话接入（零成本演示）

- `deploy/` 新增默认关闭的 `sip` profile：Asterisk 22（`andrius/asterisk:22.11.0-alpine-3.24`，免编译）+ chan_websocket，手机 Linphone/Zoiper 注册后拨一个分机即可跟 AI 通话。只是演示用的分机，不是电话号码，没有外线、没有外呼。见 docs/PHONE.md 第 10 节。
- 新增电话适配器 `asterisk-ws`（`voice/telephony/asterisk_ws.py`），复用 `ws-raw` 的编解码与重采样；电话入口 token 新增 HTTP Basic 方式（Asterisk 用它，token 不进访问日志的 URL）。
- 安全：账号密码只从环境变量读取，缺失或太弱拒绝启动；只允许认证呼入、只有一个分机；模块白名单加载，AMI/ARI/HTTP 关闭；非 5060 端口；fail2ban 防暴力注册；Caddy 屏蔽 `/telephony/asterisk-ws*`；容器内存上限 64 MB（实测空闲约 6 MB）。
- `bootstrap.sh` 新增 `WITH_SIP=1`（自动生成账号密码、打开电话入口、拆分 UDP 端口段、装 fail2ban/logrotate）；开 SIP 时网页语音改用 UDP 40000–40099，SIP RTP 用 40100–40199。

### 语料与人设框架（v0.1）

- 新增 `corpus/`：来源与脱敏原则（不收集真实个人身份信息、引用一律改写、仅限防御研究与教育）；`corpus/SOURCES.md` 调研可复用的公开数据集与 scam-baiting 项目（链接、许可证、能否入库）；`corpus/scripts/` 7 类话术库 YAML（冒充客服、冒充公检法、冒充领导熟人、杀猪盘、刷单返利、投资理财、贷款征信），含流程阶段、常用词、施压手法、识别要点和改写示例，情报一律用 `{占位符}`。
- 新增 `personas/`：4 个人设提示词（周伯 · 退休老人、小陈妈妈 · 宝妈、小宇 · 刚毕业学生、郑老板 · 个体小老板）与共用硬性规则；`personas.humanize` 真人化后处理（同音/形近错别字、标点缺失乱用、语音转文字断句、重复确认、跑题、方言词），带随机种子与强度参数，不改动数字、打码值、占位符和网址，零依赖。
- 新增 `personas/voice_traits.yaml`（7 个人设的语音说话特征：8–12 条 backchannel，格式与 `voice/persona.py` 的 `FILLERS` 相同、现有 3 个人设前 8 条不变；听错词对与反问；语速、方言词、口音；开口前停顿与扯家常频率；不含错别字）与读取模块 `personas/voice_traits.py`；`docs/REALISM.md` 分“文字打字特征”“语音说话特征”两章。`voice/` 代码未改动。
- 真人感文档移到 `docs/REALISM.md`（保留“文字打字特征”“语音说话特征”两章），新增第三章“首页示例对话改写前后”：以 `hero-chat.js` 现有 3 段为改写前，换成新人设（周伯、小陈妈妈、小宇）重写骗子与人设两侧，并用 humanize 固定种子真人化；生成脚本 `corpus/examples/build_hero_rewrite.py`，输出 `corpus/examples/hero_rewrite.json`（`after` 严格按 `SCRIPTS` 结构：`title`「诈骗类型 · 人设名」、`source`「据公开反诈宣传改写」、`lines` 每条 `r`/`s` 二选一并可选 `t`/`i`/`w`，`i` 必须已打码，每段 4–6 条、每条不超过 40 字，生成时校验；`site/` 未改动）。改写前的首页原版 3 段固定在 `corpus/examples/hero_before.json`（取自 `420a81f`），生成脚本与测试不再依赖 `hero-chat.js` 的当前内容，只检查字段名；humanize 混淆表去掉刻意错字（神马、孩纸、好滴、手鸡、钱→前）。
- 评测：docs/EVAL.md 新增“像不像真人”一节与盲测工具 `eval/realism_blind.py`（A/B 两份表交叉分配 raw / humanized，可选真人回复参照；指标：像真人分、露馅率与配对差、看不懂率、评测者一致率、自动指标）。骗子消息默认取自 `corpus/scripts`，`--scammer-file` 可换成情报分析师的真实语料（`deepsuck.core.scam-scripts/v1` 或 JSON/YAML/JSONL 列表）。humanize 的重复确认只复述完整的短分句（不再截断长分句），并去掉“？，”这类双标点。
- 测试：`python -m pytest personas corpus`（话术库格式与脱敏检查、人设格式、真人化确定性与保护规则），已加入 CI。

### 情报数据改用 CC BY 4.0

- 情报数据（`site/data/intel.json`、`intel.csv`、`intel.rss`、`intel.stix.json` 及其生成物）改为 CC BY 4.0 许可，署名「DeepSuck (deepsuck.si)」；新增根目录 `DATA_LICENSE`（适用范围、署名方式与 CC BY 4.0 法律文本全文）。代码仍为 Apache-2.0。
- `intel.json` 顶层改为 `license: "CC-BY-4.0"`，新增 `licenseUrl`、`attribution`；`intel.schema.json` 把三者列为必填并固定取值。
- STIX 导出（`python -m deepsuck.stix`）新增 statement 类型的 marking-definition `DeepSuck data license: CC BY 4.0`，identity 与其余全部对象都引用它（与 TLP:WHITE 并列）；OASIS validator `Valid`，0 警告。已导入旧版 Bundle 的平台请整包重新导入（对象的 `modified` 仍取条目日期，未因加标记而变化）。
- RSS 的 `<copyright>` 改为 CC BY 4.0 与署名，channel 说明里注明各导出文件的许可；CSV 不加注释行（保持可解析、与页面导出逐字节一致），许可在 `DATA_LICENSE` 与 docs/INTEL.md 中注明。
- 情报页数据区与页脚注明数据许可与署名，JSON-LD 的 Dataset `license` 改为 CC BY 4.0；情报提交模板的确认项改为按 CC BY 4.0 公开发布。

### GitHub 自动收录与公开订阅源

- 新增结构化情报提交模板 `intel-intake.yml`，以及工作流 `intel-intake.yml`：解析 issue → 脱敏 → 去重 → 公开黑名单比对 → 生成更新 `intel.json` 等文件的待审核 PR，并在 issue 下回复结果。不自动合并；每个 job 单独声明最小权限；Action 锁定到 SHA；issue 正文不进入 shell。核心逻辑在 `python/deepsuck/intake.py`，测试不联网。
- 新增公开订阅源 `site/data/intel.rss`（RSS 2.0）和 `site/data/intel.csv`（`python -m deepsuck.feeds` / `npm run build:intel`），只含公开中的条目，用打码值。
- 银行卡新增仅用于展示的分组格式 `formatCardGroups` / `format_card_groups`（`622202*********3445` → `6222 02** **** ***3 445`），情报页卡片改用分组展示；存储与 STIX 不变。

### 银行卡 PCI 打码

- 银行卡打码改为 PCI DSS 标准：16–19 位保留前 6 位（BIN）与后 4 位，中间全部打码；8–15 位只留后 4 位，少于 8 位全部打码。JS（`redact.js`）与 Python（`deepsuck/redact.py`）同步，fixtures 覆盖 7–19 位与带空格/连字符写法。
- 情报库与提交附 BIN 推断的发卡行 `issuer` 与卡种 `cardType`；schema 与校验器只接受 PCI 打码格式。
- STIX 2.1 导出现在包含银行卡 Indicator（`payment-card:card_number LIKE`，仅用打码值），并带 `x_deepsuck_bank / issuer / card_type` 扩展属性；OASIS 校验通过。
- 模拟器泄露率不再把紧挨 `*` 的打码值数字段计为泄露（结果数字不变）。
- 姓名、身份证、QQ、微信、支付宝打码方式不变。

### 其他

- 情报：STIX 2.1 导出（`python -m deepsuck.stix`，发布 [`site/data/intel.stix.json`](site/data/intel.stix.json)，姓名、账号、身份证不导出，银行卡只导出 PCI 打码值）；银行卡 BIN 本地查询（数据 [hexindai/bcbc](https://github.com/hexindai/bcbc)，MIT），提取到卡号时补充发卡行与卡种。见 [docs/INTEL.md](docs/INTEL.md)。
- 站点打磨：WCAG AA 文字对比度；手机端原生 `<details>` 折叠菜单（保留 EN 切换）；沙盒场景/人设折叠进对话头，首屏即见输入框；原生 `<dialog>` 弹窗；情报库分页与 4 列统计；首页示例对话首帧不空。
- SEO：三页补齐 description、canonical、OG/Twitter 卡片，按页面生成 OG 图（`npm run og`）；新增 robots.txt、sitemap.xml、404.html 与 JSON-LD（WebSite、SoftwareSourceCode、Dataset）。
- 纯静态托管时不再请求 `api/health`（由 `npm start` 托管时服务器注入 `local = true`）；GitHub 星标改用 shields.io 徽章。
- 截图改为 `npm run screenshots` 生成的 WebP；logo/favicon 统一为墨黑 + 纸白 + 铜色点缀。
- 文档：新增 [docs/QUICKSTART.md](docs/QUICKSTART.md)、[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，README 精简。

## v0.4 公开部署包

Docker Compose（Caddy 自动 HTTPS + Node 代理 + Pipecat 语音 + 可选 coturn）、一键 bootstrap、费用护栏（每日预算预占记账、每 IP/全站限流、并发/时长/轮数/静默上限、CORS 白名单）、WebRTC UDP 端口段 + 公网 IP 候选、`voice.probe` 端到端探针；修复 Paraformer 数字规整导致的姓名漏抽（`张3` → `张三`）。见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## v0.3

Python 核心（共享 fixtures，CI 跑 pytest）；destroylist / Phishing.Database 域名黑名单 + OFAC / ScamSniffer 钱包黑名单；骗子模拟器与 TeleAntiFraud 评测（[docs/EVAL.md](docs/EVAL.md)）；语音演示（Pipecat 级联：Paraformer 实时 ASR → qwen-plus → CosyVoice，SmallWebRTC 浏览器麦克风，填充音插播，实时情报看板）；语音输出守卫。

## v0.2

7 个场景（新增刷单返利、虚假贷款/征信修复、冒充领导熟人、注销校园贷）；情境台词与反向核验；公开诈骗情报库 + 提交/申诉流程；规则数据抽成 `core/*.json`；中文去武装写法识别；首页动画与 OG 图。

## v0.1

纯静态沙盒、规则人设引擎、提取器/分类器/脱敏、情报看板、可选百炼代理。
