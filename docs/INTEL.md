# 公开诈骗情报库：发布策略与数据格式

> 页面：<https://deepsuck.si/intel.html> · 数据：[`site/data/intel.json`](../site/data/intel.json) · 格式：[`site/data/intel.schema.json`](../site/data/intel.schema.json)（`deepsuck.intel-library/v1`）

DeepSuck 会**公开发布**它收集到的诈骗情报，让任何人都能检索、拦截与预警。

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
4. 维护者审核后以 `DS-YYYY-xxxx` 编号收录（`source: community`）。

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
| `redact_text(text, entities)` | 原始文本 + 上一步的列表 | `str`，把每个片段替换为 `masked`（缺省时按 `type` 现算）；`sensitive is False` 或无下标的项跳过 | 生成可落盘的脱敏文本 |
| `mask(type_, value)` | 情报类型 + 单个值 | `str` 打码值；未知类型按通用账号规则保守打码 | 单值打码（如写入结构化字段） |

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
- 标记为 TLP:WHITE（即 TLP 2.0 的 TLP:CLEAR）；ID 由条目 ID 确定性生成（UUIDv4 形式），同一输入总是得到同一输出，便于增量导入；
- 已用 OASIS [cti-stix-validator](https://github.com/oasis-open/cti-stix-validator)（schema 取自 [cti-stix2-json-schemas](https://github.com/oasis-open/cti-stix2-json-schemas)）校验：`Valid`，0 警告。

## 银行卡 BIN 查询（v0.5）

提取到银行卡号时，在本地按卡号前缀（BIN，最长匹配 + 卡号长度校验）判断**发卡行与卡种**，写入 `meta.issuer`；上下文没提到开户行时，`meta.bank` 用 BIN 推断值（`meta.bankFrom: "bin"`）。查询不联网、卡号不外传；`meta.issuer` 不重复记录 BIN 数字本身（打码值里已经有前 6 位）；提交与情报库条目用 `issuer`、`cardType` 字段携带发卡行与卡种。

- 数据：[hexindai/bcbc](https://github.com/hexindai/bcbc) 的 `data/bin.csv` + `data/name.csv`（MIT，Copyright (c) 2018 - 2020 Runrioter），1697 个 BIN 前缀、275 家发卡机构，固定在 commit `de63182`；许可证随数据附在 [`site/assets/core/cardbin.LICENSE.txt`](../site/assets/core/cardbin.LICENSE.txt)；
- 更新：`node scripts/fetch-cardbin.js [--ref <commit>]` 重新生成 `site/assets/core/cardbin.json`，再运行 `npm run build:core && npm run fixtures`；
- JS：`DeepSuck.cardbin.lookup(卡号)`；Python：`deepsuck.cardbin.lookup(卡号)`，命令行 `python -m deepsuck.cardbin <卡号>`（只输出发卡行信息，不回显卡号）；
- BIN 表并非官方注册表，可能过时或不全，结果仅供参考；收款卡常属于被冒用、被诱骗出租的普通人，发卡行信息不能用于对持卡人的任何认定。
