# 公开诈骗情报库：发布策略与数据格式

> 页面：<https://deepsuck.si/intel.html> · 数据：[`site/data/intel.json`](../site/data/intel.json) · 格式：[`site/data/intel.schema.json`](../site/data/intel.schema.json)（`deepsuck.intel-library/v1`）

DeepSuck 会**公开发布**它收集到的诈骗情报，让任何人都能检索、拦截与预警。

**数据许可**：情报数据（`site/data/intel.json`、`intel.csv`、`intel.rss`、`intel.stix.json` 及其生成物）以 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode) 许可发布，再使用时请署名「DeepSuck (deepsuck.si)」并注明许可，详见根目录 [`DATA_LICENSE`](../DATA_LICENSE)；代码仍为 Apache-2.0。许可写在 `intel.json` 顶层的 `license` / `licenseUrl` / `attribution`、RSS 的 `<copyright>`、STIX 的 statement 标记里；CSV 为保证可直接解析不加注释行，以本文和 `DATA_LICENSE` 为准。

## 发布策略

| 类型 (`type`) | 公开方式 | 示例 |
|---|---|---|
| `phone` 诈骗电话（含 400/800、座机） | **完整公开** | `10000000001` |
| `crypto_wallet` 加密钱包地址 | **完整公开** | `TDemoExample…`（TRON） |
| `url` 诈骗网址 / 域名 | **完整公开** | `https://refund-kefu.example/dl` |
| `app` 诈骗 APP / 平台名称 | **完整公开** | `示例·安心退` |
| `script` 话术 / 手法模式 | **完整公开**（不含受害人信息） | “涉嫌洗钱 → 保密 → 安全账户” |
| `bank_card` 收款银行卡 | **部分打码**（PCI DSS）：16–19 位只留前 6 位（BIN）与后 4 位，中间全部打码；附开户行与 BIN 推断的发卡行、卡种。非标准长度（8–15 位）只留后 4 位，少于 8 位全部打码 | `622202*********1234`（中国工商银行 · 借记卡） |
| `name` 收款户名 / 姓名 | **部分打码**：只留姓 | `王**` |
| `id_card` 身份证号 | **部分打码** | `110101********1234` |
| `account` 支付宝 / 微信 / QQ / 邮箱等个人账号 | **部分打码**：首尾各留 2 位 | `ke******26` |

**为什么银行卡和姓名要打码**：大量“跑分卡”“收款卡”属于被冒用身份、被诱骗出租或出借账户的普通人（不少是学生和老人）。部分公开既能帮助比对，又不会让无辜者被网暴。

代码实现见 [`site/assets/js/intel.js`](../site/assets/js/intel.js) 的 `publishValue()`，测试见 `tests/intel.test.js`。校验器会拒绝含 7 位以上连续数字的“打码类”条目。银行卡另须符合 PCI 打码格式（`^\d{6}\*{6,9}\d{4}$` 或只留后 4 位的短卡号），旧的“前 4 后 4”格式会被拒绝。

## 收录原则

- 只收录**诈骗方主动暴露**的信息；不收录受害人信息，不做人肉，不对任何号码发起骚扰或“反击”；
- 每条标注首次/最近出现时间、场景、话术标签、举报次数、来源（`sandbox` / `community` / `honeypot` / `public-report`）与可信度；
- 示例数据一律 `example: true`、ID 以 `EX-` 开头，并在 `notes` 中写明「示例数据」；当前库中**只有示例数据**；
- 情报仅供参考：号码可能被回收或冒用，不能作为认定依据，以公安机关认定为准。

## 提交

1. 在[沙盒](https://deepsuck.si/demo.html)选择场景，把骗子原话逐条粘贴进去（提取与打码都在浏览器本地完成）；
2. 结束对话 → 「提交到情报库」：按上表策略生成内容并复制；
3. 打开 [GitHub 情报提交模板](https://github.com/deepsucksi/deepsuck/issues/new?template=intel-submission.yml)，内容会自动预填，补充时间与渠道后提交；
   单条手动提交可以用 [结构化提交模板](https://github.com/deepsucksi/deepsuck/issues/new?template=intel-intake.yml)（类型、值、话术片段、来源、场景等分字段填写）；
4. 机器人自动打码、去重、做黑名单比对，生成待审核的 PR 并在 issue 里回复结果（见下文「GitHub 自动收录」）；维护者审核合并后以 `DS-YYYY-NNNN-k` 编号收录（`NNNN` 为 issue 号）。

**请勿提交**受害人信息、未打码的银行卡号 / 身份证号 / 全名，或沙盒里的虚构样例台词。

## 下架与申诉

号码被回收再分配、银行卡被冒用、域名已易主……请使用 [下架申诉模板](https://github.com/deepsucksi/deepsuck/issues/new?template=intel-appeal.yml)，**只需填写条目 ID**，无需公开个人信息。维护者会先把条目标记为 `disputed`（页面隐藏具体值），核实后改为 `removed`（默认不展示）或恢复。

## 举报渠道（优先）

- 已经转账或正在被骗：**立即拨打 110**，并联系银行尝试止付；
- **96110**：全国反诈预警劝阻专线（接到 96110 来电请务必接听）；
- **国家反诈中心 App** →「我要举报」：电话、短信、网址、APP、收款账户等线索；
- **12321**：垃圾短信、骚扰电话、不良网址举报。

## 公开黑名单比对（v0.3）

沙盒、Python core 与语音端提取到**网址/域名**或**钱包地址**后，会自动与公开黑名单比对，在侧栏、情报看板和导出报告（`intel[].blocklist`）中标注「命中公开黑名单 · 来源」或「未命中黑名单」。**命中仅供参考**：域名可能被回收、地址可能被冒用，不能作为认定依据；未命中也不代表安全。

| 数据源 | 类型 | 许可证 | 获取方式 |
|---|---|---|---|
| [destroylist](https://github.com/phishdestroy/destroylist) | 钓鱼/诈骗域名（约 22 万） | MIT | **构建时**拉取 |
| [Phishing.Database](https://github.com/Phishing-Database/Phishing.Database) `phishing-domains-ACTIVE` | 钓鱼域名（约 39 万） | MIT | **构建时**拉取 |
| [ScamSniffer scam-database](https://github.com/scamsniffer/scam-database) `blacklist/address.json` | EVM 诈骗地址 | GPL-3.0 | **运行时**从 GitHub 拉取，不随本仓库分发 |
| [OFAC SDN 加密地址](https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses)（ETH / TRON / USDT / BTC） | 受制裁地址 | 美国政府公开数据；整理脚本 MIT | **运行时**拉取 |

实现要点（数据源配置见 [`site/assets/core/blocklists.json`](../site/assets/core/blocklists.json)）：

- **域名不入库**：`scripts/fetch-blocklists.js`（`npm run blocklists`）在 GitHub Pages 部署前拉取两份 MIT 列表，合并去重（约 60 万条）后按 `FNV-1a(域名) % 256` 分成 256 片写入 `site/data/blocklist/d/xx.txt`（每片约 65 KB，gzip 后约 20 KB），附 `meta.json` 与 `LICENSES.txt`。仓库体积不变。
- **按需查询、不外传**：浏览器只拉取被查域名及其父域所在的 1–3 个分片（来自 deepsuck.si 本身），查询内容不会发给第三方。父域命中（如 `login.evil.top` 命中 `evil.top`）会标注“父域名命中”。
- **钱包运行时拉取**：只在提取到对应链的地址时才下载整表（ScamSniffer 约 120 KB），本地比对；GPL 数据不进入本仓库与站点产物。
- **报告不泄露原值**：报告中只记录 `status / how / sources / updated`，不写入被比对的网址或地址原文。
- Python：`python -m deepsuck.blocklist <网址或地址>`，默认查询 `https://deepsuck.si/data/blocklist/`，也可 `--base site/data/blocklist` 指向本地构建产物；钱包列表缓存在 `~/.cache/deepsuck`。

## 脱敏接口 `deepsuck.redact`（Python）

供语音 / 电话转写等文字记录在落盘或展示前直接调用。实现在 [`python/deepsuck/redact.py`](../python/deepsuck/redact.py)，与站点 [`site/assets/js/redact.js`](../site/assets/js/redact.js) 逐项等价（`tests/fixtures/redact.json` 由 JS 生成，Python 测试逐条比对）。纯标准库，无网络、无密钥。

### 入口函数

| 函数 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `extract_sensitive(text)`（`deepsuck.extractors`） | `str`，原始转写文本，可含空格、连字符、中文数字（如“六二二二……”） | `list[dict]`，每项含 `type`、`label`、`value`（原值，只留内存）、`masked`（打码值）、`start`/`end`（在**原始文本**中的下标）、`sensitive`、`meta` | 找出敏感片段 |
| `redact_text(text, entities)` | 原始文本 + 上一步的列表 | `str`，把每个片段替换为 `masked`（缺省时按 `type` 现算）；`sensitive is False` 或无下标的项跳过；另外按上下文给验证码打码（见下） | 生成可落盘的脱敏文本 |
| `mask(type_, value)` | 情报类型 + 单个值 | `str` 打码值；未知类型按通用账号规则保守打码 | 单值打码（如写入结构化字段） |

验证码不是情报实体，`redact_text` 另按上下文打码（`find_otp_spans(text)` 可单独调用，JS 为 `redactText` / `findOtpSpans`）：只在“验证码、动态码、动态密码、校验码、短信码、确认码、安全码、OTP”前 16 个字或后 8 个字以内（中间不夹阿拉伯数字，至多跨 2 个句末标点）出现 4–8 位数字时，把数字逐个换成 `*`、分隔符保留，例如“验证码是 4 7 2 9 1 5”→“验证码是 * * * * * *”、“校验码⋯四七二⋯九一五”→“校验码⋯***⋯***”。数字之间允许空格、“…”“⋯”“...”、连字符，可用中文数字逐位读出，两段各不超过 4 位时可用“，”“、”连接。不打码：手机号、卡号等实体（照常由实体规则打码）、紧挨字母 / 数字 / `*` 的数字（订单号、已打码值）、前面是“尾号 / 后四位 / 金额 / 工号 / 订单号 / ¥”等、后面是“元 / 块 / 分钟 / 位 / 个”等单位的数字，以及离关键词远的普通数字。规则在 `site/assets/core/extractors.json` 的 `redact.otp`，JS 与 Python 共用（#33）。

跨 ASR 分段（#92）：语音识别会把一串验证码切成几段（“验证码是 38”“27 15”），逐段判断时都不打码。`redact_otp_segments(texts)`（JS `redactOtpSegments`；`find_otp_spans_segments` / `findOtpSpansSegments` 返回各段下标）接收同一通电话、**同一说话方**按时间排的连续分段，以每段为中心连同前后各 `segWindow`（2）段用空格拼接，按上面同一套规则再判断，命中的数字映射回各段换成 `*`（长度不变，可重复调用）。拼接处两侧的数字串之间只有空白、句读或“嗯 / 啊 / 那个”时可连成一串（合计不超过 8 位）。对逐段 `redact_text` 之后的文本调用。调用点：`Session.ingest`（JS / Python，本段和前 2 段对方的话）、`voice/trace.py` 落盘（对方、人设各自一串，落盘晚 3 段，看得到前后 2 段）、`voice/records.py` 文字记录（按角色）；历史 trace 用 `python -m voice.redact_backfill` 重跑。

`mask`、`redact_text`、`extract_sensitive` 也可直接 `from deepsuck import ...`。另有按类型的 `mask_bank_card`、`mask_phone`、`mask_id_card` 等函数，类型到函数的映射见 `MASKERS`。

### 各类型打码规则

| `type` | 规则 | 示例（输入 → 输出） |
|---|---|---|
| `bank_card` | PCI DSS：16–19 位留前 6 位（BIN）与后 4 位，中间全打码；8–15 位只留后 4 位；少于 8 位全打码。空格、连字符先去掉 | `6222 0202 0011 2233 445` → `622202*********3445`；`6222020200112233` → `622202******2233`；`62220202001` → `*******2001`；`6222021` → `*******` |
| `phone` / `hotline` | 11 位手机号留前 3 后 4（`+86` 前缀去掉）；400/800 号留前 3 后 4；其他留首尾各 2 位 | `13912342233` → `139****2233`；`4001234567` → `400-***-4567` |
| `id_card` | 留前 6 位（地区码）与后 4 位，中间固定 8 个 `*`；`x` 转大写；不足 10 位全打码 | `11010119900101123x` → `110101********123X` |
| `name` | 只留姓（首字） | `王小明` → `王**` |
| `qq` | 首尾各留 2 位 | `12345678` → `12****78` |
| `wechat` | 首尾各留 2 位，中间最多 6 个 `*`；4 位及以下只留首字 | `wxid_abc12345` → `wx******45` |
| `alipay` | 邮箱按 `email`；11 位手机号按 `phone`；其他按 `wechat` | `13912342233` → `139****2233` |
| `email` | 用户名留前 2 位，域名保留 | `scam@example.com` → `sc***@example.com` |
| `url` | 协议与顶级域保留，域名主体留首尾各 2 位，路径换成 `/***` | `https://pay-secure.top/a` → `https://pa***re.top/***` |
| `crypto_btc` / `crypto_eth` / `crypto_tron` | 留前 4 位（`0x`、`bc1` 开头留前 6 位）与后 4 位 | `TXyz1234567890abcdEFGH5678` → `TXyz...5678` |
| 其他 | 按 `wechat` 规则 | `abcdefgh` → `ab****gh` |

银行卡的 `meta` 里另有 `issuer`（BIN 推断的发卡行、卡种，如 `中国工商银行`、`借记卡`）与 `luhn`、`digits`，可与打码值一起保存。

### 调用示例

```python
from deepsuck.extractors import extract_sensitive
from deepsuck.redact import mask, redact_text

line = "骗子：转到 6222 0202 0011 2233 445，户名王小明，电话 13912342233，QQ 12345678"
entities = extract_sensitive(line)
safe = redact_text(line, entities)
# safe == "骗子：转到 622202*********3445，户名王**，电话 139****2233，QQ 12****78"

card = next(e for e in entities if e["type"] == "bank_card")
record = {"type": "bank_card", "value": card["masked"],
          "issuer": card["meta"]["issuer"]["bank"], "cardType": card["meta"]["issuer"]["cardTypeName"]}
# {'type': 'bank_card', 'value': '622202*********3445', 'issuer': '中国工商银行', 'cardType': '借记卡'}

redact_text("他说卡号是六二二二零二零二零零一一二二三三四四五", extract_sensitive("他说卡号是六二二二零二零二零零一一二二三三四四五"))
# "他说卡号是622202*********3445"（中文数字也能识别，下标指向原文）

mask("id_card", "11010119900101123x")  # "110101********123X"
```

注意：

- 只把 `redact_text` 的结果或 `masked` 写入日志、数据库或模型上下文；`value` 是原值，不要落盘。
- `redact_text` 只替换 `extract_sensitive` 识别到的片段。识别不到的写法（比如口述里夹了无关字）不会被打码，落盘前可以再用正则兜底，比如抹掉 ≥7 位的连续数字。
- 打码结果是确定的：同一输入总是得到同一输出，可直接用于去重。

### 银行卡分组展示 `format_card_groups` / `formatCardGroups`

只用于**展示**：把打码后的卡号每 4 位一组，方便人眼核对位数。Python 为 `deepsuck.redact.format_card_groups(v)`，JS 为 `DeepSuck.redact.formatCardGroups(v)`（`site/assets/js/redact.js`），两边结果由 `tests/fixtures/redact.json` 的 `groups` 逐条比对。

| 存储值（`mask_bank_card` 结果） | 展示值 |
|---|---|
| `622202*********3445`（19 位） | `6222 02** **** ***3 445` |
| `622202******2233`（16 位） | `6222 02** **** 2233` |
| `*******2001`（11 位） | `**** ***2 001` |

- 输入里的空格、连字符先去掉，所以对已分组的值再调用一次结果不变；含数字和 `*` 以外字符的值（如 `王**`）原样返回。
- **存储、导出、STIX、CSV/RSS、去重键一律用不分组的原格式**（`622202*********3445`）。情报页卡片用分组格式展示，“复制”按钮复制的仍是原格式；情报提交机器人的 issue 评论和 PR 表格里也用分组格式展示。

## GitHub 自动收录（IssueOps）

工作流 [`.github/workflows/intel-intake.yml`](../.github/workflows/intel-intake.yml)，核心逻辑在 [`python/deepsuck/intake.py`](../python/deepsuck/intake.py)（测试 `python/tests/test_intake.py`，不联网）。

**触发**：issue 带 `intel-submission` 标签（两个情报提交模板都会自动加上），事件为 opened / edited / labeled / reopened。PR、已关闭的 issue 和机器人触发的事件都不处理。提交者编辑 issue 后会重新处理，并更新同一条机器人评论。

**流程**：

1. 解析表单：支持结构化模板 `intel-intake.yml` 和沙盒预填用的 `intel-submission.yml`（逐行解析 `- 类型：`值`` 格式）。解析结果的形状与 issue-ops/parser 一致，测试里用该 Action 对同一批正文的真实输出做比对。
2. 脱敏：按发布策略调用 `deepsuck.redact`：银行卡用 PCI 打码（只接受前 6 后 4 或完整卡号，旧的“前 4 后 4”格式会被拒绝，因为推断不了 BIN），并按 BIN 补上发卡行和卡种；姓名只留姓；账号按所选平台打码。话术片段和补充说明再跑一遍 `redact_text`；身份证号不接受自动收录。
3. 去重：电话按数字、钱包按地址、网址去掉协议后比较。重复的条目举报次数 +1，并更新 `lastSeen`，同时打上 `gh-issue-N` 标签，同一个 issue 重跑不会重复计数。与示例数据相同的不收录；申诉中或已下架的交给维护者人工处理。
4. 黑名单比对：网址和钱包地址与公开黑名单比对（见上文），命中的条目可信度设为 `medium`，否则为 `low`。比对失败不影响收录。
5. 生成文件：重新生成 `site/data/intel.json`、`intel.stix.json`、`intel.csv`、`intel.rss`，格式与仓库里的完全一致，并开出 PR（分支 `intel-intake/issue-N`）。

**安全约定**：

- **绝不自动合并**。工作流只开 PR，PR 正文附维护者审核清单。
- **最小权限**。工作流默认没有任何权限：解析 issue 的 job 只读（`contents: read`），建 PR 的 job 只有 `contents: write` 和 `pull-requests: write`，评论的 job 只有 `issues: write`。三个 job 之间用 artifact 传递结果，第三方 Action 都锁定到 commit SHA。
- **防脚本注入**。issue 标题和正文不出现在任何 `run:` 脚本里：正文由 Python 直接从 `$GITHUB_EVENT_PATH` 读取，其余数据走环境变量或文件；写入 `GITHUB_OUTPUT` 的只有固定的 `changed=true/false`。
- **不回显原文**：PR 和评论里只有按策略处理后的公开值；评论文本会转义 Markdown/HTML，并打断 `@` 提及和 `#` 引用。输出前还有一道泄露检查：如果任何输出里出现了打码类原值（≥7 位数字串、未打码的姓名或账号），就不生成 PR，评论也不显示具体值。原文里有未打码的信息时，评论会请提交者编辑 issue 删掉；维护者也可以在编辑历史里删除旧版本，必要时隐藏或删除这个 issue。
- **没有用 issue-ops/parser 解析**：这个 Action 会把 issue 正文原样打印到公开的 Actions 日志里，提交者事后删改也去不掉，所以改用仓库内的解析器。issue-ops/parser 只作为测试基准使用。

**仓库设置**：需要打开 Settings → Actions → General → Workflow permissions 下的 “Allow GitHub Actions to create and approve pull requests”（已由负责人打开）。默认的 `GITHUB_TOKEN` 权限保持只读即可，工作流在 job 里单独声明需要的写权限。触发用的 `intel-submission` 标签和 `needs-review` 标签都已经存在。

**验证方式**：

- 本地：`cd python && python -m pytest tests/test_intake.py`。也可以构造事件文件试跑：`python -m deepsuck.intake process --event event.json --repo .. --out /tmp/intake --offline`，然后查看 `/tmp/intake/{pr.md,comment.md,files/}`。
- 线上：用任一情报提交模板提交一条示例 issue，例如“诈骗网址/域名”填一个 `.example` 域名。确认三个 job 依次运行、出现分支 `intel-intake/issue-N` 和一个待审核的 PR，issue 下有一条机器人评论；再编辑 issue，确认 PR 和评论都被更新而不是重复创建。测试完关闭 PR 和 issue 即可，分支会随 PR 一起删除。
- 由 `GITHUB_TOKEN` 创建的 PR 不会触发其他工作流（GitHub 的限制），所以 `test` 工作流不会自动运行。维护者可以关闭再重新打开 PR，或推一个空提交来触发 CI。

## 公开订阅源（CSV / RSS）

| 地址 | 格式 |
|---|---|
| <https://deepsuck.si/data/intel.rss> | RSS 2.0：每条情报一个 item，`guid` 为 `deepsuck-intel:<id>`，链接到情报页的筛选结果 |
| <https://deepsuck.si/data/intel.csv> | CSV（UTF-8 BOM、CRLF），列与情报页“下载 CSV”一致：`id, example, type, value, chain, bank, issuer, cardType, scenario, tactics, firstSeen, lastSeen, reports, source, confidence, status, notes` |

- 只输出 `status: active` 的条目，申诉中（`disputed`）和已下架（`removed`）的条目不输出。
- `value` 是库里按发布策略处理后的公开值：银行卡为 PCI 打码值（不分组），姓名和账号已打码。打码类条目如果没有通过打码校验，整次生成会失败，不会输出。
- 输出是确定的，只依赖 `intel.json`。改了 `intel.json` 后运行 `npm run build:intel`，会重新生成 STIX、CSV 和 RSS；`python/tests/test_feeds.py` 和 `tests/intel.test.js` 会检查生成文件是否最新，并检查 CSV 与页面导出逐字节一致。
- 许可：RSS 的 channel 带 `<copyright>`（CC BY 4.0，署名 DeepSuck (deepsuck.si)），`<description>` 里也注明；CSV 文件内不加注释行（会破坏解析），同样按 CC BY 4.0 发布，见 [`DATA_LICENSE`](../DATA_LICENSE)。

## STIX 2.1 导出（v0.5）

公开情报库同时发布 STIX 2.1 Bundle：[`site/data/intel.stix.json`](../site/data/intel.stix.json)，可直接导入 OpenCTI、MISP 或 TAXII 服务。

```bash
cd python
pip install stix2            # 可选：OASIS 官方库，用于解析/校验/序列化；不装也能导出，结果逐字节一致
python -m deepsuck.stix ../site/data/intel.json -o ../site/data/intel.stix.json   # 改了 intel.json 后重新生成（pytest 会检查是否同步）
python -m deepsuck.stix 沙盒提交.json                                              # deepsuck.intel-submission/v1 → stdout
```

| 情报库类型 | STIX 对象 | pattern |
|---|---|---|
| `phone` | Indicator | `[phone-number:value = '…']` |
| `crypto_wallet` | Indicator | `[cryptocurrency-wallet:value = '…']` |
| `url` | Indicator | `[url:value = '…']`（纯域名为 `[domain-name:value = '…']`） |
| `app` | Indicator | `[software:name = '…']` |
| `script` | Note（指向场景） | — |
| 场景 `scenario` | Attack Pattern，Indicator 以 `indicates` 关系指向它 | — |
| `bank_card` | Indicator（只用 PCI 打码值） | `[payment-card:card_number LIKE '622202_________1234']`（`_` 匹配一位被打码的数字），附 `x_deepsuck_bank / x_deepsuck_issuer / x_deepsuck_card_type`；不符合打码格式的值不导出 |
| `account` / `name` / `id_card` | **不导出** | 打码值无法用于匹配，且可能属于被冒用的普通人 |

- 只导出 `status: active` 的条目；`disputed` / `removed` 不导出；
- `phone-number`、`cryptocurrency-wallet` 沿用 OpenCTI 的可观测类型命名；场景、来源、举报次数、链、示例标记以 `x_deepsuck_*` 顶层属性给出，并用 `extension-definition`（`toplevel-property-extension`）声明；
- 标记为 TLP:WHITE（即 TLP 2.0 的 TLP:CLEAR）；另有一个 `definition_type: statement` 的 marking-definition（名称 `DeepSuck data license: CC BY 4.0`，声明许可、法律文本链接与署名 DeepSuck (deepsuck.si)），identity 与其余全部对象的 `object_marking_refs` 都同时引用这两个标记（沙盒提交的导出不带许可标记）；ID 由条目 ID 确定性生成（UUIDv4 形式），同一输入总是得到同一输出，便于增量导入；
- 已用 OASIS [cti-stix-validator](https://github.com/oasis-open/cti-stix-validator)（schema 取自 [cti-stix2-json-schemas](https://github.com/oasis-open/cti-stix2-json-schemas)）校验：`Valid`，0 警告。

## 银行卡 BIN 查询（v0.5）

提取到银行卡号时，在本地按卡号前缀（BIN，最长匹配 + 卡号长度校验）判断**发卡行与卡种**，写入 `meta.issuer`；上下文没提到开户行时，`meta.bank` 用 BIN 推断值（`meta.bankFrom: "bin"`）。查询不联网、卡号不外传；`meta.issuer` 不重复记录 BIN 数字本身（打码值里已经有前 6 位）；提交与情报库条目用 `issuer`、`cardType` 字段携带发卡行与卡种。

- 数据：[hexindai/bcbc](https://github.com/hexindai/bcbc) 的 `data/bin.csv` + `data/name.csv`（MIT，Copyright (c) 2018 - 2020 Runrioter），1697 个 BIN 前缀、275 家发卡机构，固定在 commit `de63182`；许可证随数据附在 [`site/assets/core/cardbin.LICENSE.txt`](../site/assets/core/cardbin.LICENSE.txt)；
- 更新：`node scripts/fetch-cardbin.js [--ref <commit>]` 重新生成 `site/assets/core/cardbin.json`，再运行 `npm run build:core && npm run fixtures`；
- JS：`DeepSuck.cardbin.lookup(卡号)`；Python：`deepsuck.cardbin.lookup(卡号)`，命令行 `python -m deepsuck.cardbin <卡号>`（只输出发卡行信息，不回显卡号）；
- BIN 表并非官方注册表，可能过时或不全，结果仅供参考；收款卡常属于被冒用、被诱骗出租的普通人，发卡行信息不能用于对持卡人的任何认定。

## 诈骗话术语料（v0.6）

[`site/assets/core/scam_scripts.json`](../site/assets/core/scam_scripts.json)（`deepsuck.core.scam-scripts/v1`，格式定义 [`scam_scripts.schema.json`](../site/assets/core/scam_scripts.schema.json)）收录骗子侧的典型说法，用于训练与评测“拖住”机器人、话术识别和反诈宣传，仅限防御用途。数据以 CC BY 4.0 发布（见 [DATA_LICENSE](../DATA_LICENSE)），各来源许可见文件内 `sources[].license` 与 [corpus/SOURCES.md](../corpus/SOURCES.md)。

- **结构**：`types[]` 7 类（冒充客服、冒充公检法、冒充领导熟人、杀猪盘、刷单返利、投资理财、贷款征信；id、阶段与施压手法与 `corpus/scripts/*.yaml` 一致）；`phases[]` 统一 5 阶段（开场 / 建立信任 / 施压 / 索要钱款信息 / 收款指令）；`entries[]` 共 181 条，每条有 `type`、`phase`、`stage`（yaml 阶段 id）、`text`、`keywords`、`pressure`（施压手法 id）、`tactics`（当前分类器识别结果）、`intel`（句中情报占位符类型）、`sourceType` / `sourceLabel` / `sourceIds` / `sourceRef` / `sourceUrls`；
- **来源标注**：只有确实对应某个典型案例、通报段落或数据集条目的才标案例 / 通报 / 数据集，并用 `sourceRef` 指明；其余一律标“据公开反诈宣传改写”。分布：反诈宣传归纳 141 条，通报案例 16、通报话术段落 11、法院典型案例 10、TeleAntiFraud 对话 3；
- **脱敏**：句子里不出现任何号码、网址、账号，情报一律写成 `{银行卡}`、`{手机号}`、`{网址}`、`{户名}` 等占位符（`placeholders` 给出类型与虚构示例值，域名一律 `.example`）；测试检查无 6 位以上数字、无手机号、无网址、无打码星号、无 emoji；
- **使用者**：模拟器（`python -m deepsuck.sim`，默认 `--lines corpus`）、`eval/realism_blind.py --scammer-file site/assets/core/scam_scripts.json`；演示页样例台词 `site/assets/core/scenarios.json` 的 `samples` 据它改写，与之一一对应的 `sampleSources[]`（`sourceType`、`label`、`sourceId`、`sourceRef`、`url`）给出来源标注，页面可直接显示 `label`。演示样例需要能被提取，所以其中保留了虚构的完整测试值（`.example` 域名、`某某` 户名、仓库测试用卡号与手机号），不是真实号码。

## 提取器噪声鲁棒性与跨回合拼接（v0.6）

规则都在 [`site/assets/core/extractors.json`](../site/assets/core/extractors.json)，JS 与 Python 两份实现逐字节对齐（`tests/fixtures/*.json` 共享夹具，含 `stitch.json`）：

- **异体字与错别字**：`obfuscation.variantChars`（帐 / 帳 / 賬 → 账，戶 → 户，號、碼、銀、錢、轉、證、驗、機、電、話、網）；`obfuscation.typoKeywords` 由 `scripts/sync_typo_keywords.py` 从 `personas/humanize` 的混淆表生成（只收等长替换，排除歧义与本身就是关键词的变体），测试检查与混淆表同步，不另维护一套；
- **数字混淆**：全角、圈码、中文 / 大写数字、幺 / 两、腰 / 妖、溜、久 / 酒；数字之间夹空格、横杠、换行、中文标点时，只有拼起来是合法手机号或像银行卡（Luhn、62 开头或命中 BIN）才拼接，带单位的数字与标准分组写法不受影响；ETH / TRON 地址分段也会拼回；
- **跨回合拼接**：`extractors.stitch(turns)` / `deepsuck.extractors.stitch(turns)` 对同一说话方相邻至多 3 个回合（`stitch.window`），把上一回合末尾与下一回合开头的数字片段拼起来，输出 `confidence`、`turns`、`parts`（各回合的位置与打码切片）、`meta.stitched`；避免误拼：已经完整的号码不再与相邻数字拼接，更正句（“不对，…”）、带单位的数字、工号 / 订单号 / 验证码旁的数字不参与，低于 `minConfidence` 的丢弃。`Session` 每收到一句骗子消息就对最近几个回合做拼接，新情报写入 `intel`，此前已显示的片段回溯打码；
- 指标与局限见 [EVAL.md](EVAL.md) 第 1 部分“噪声与跨回合拼接”。
