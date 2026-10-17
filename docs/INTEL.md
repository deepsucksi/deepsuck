# 公开诈骗情报库：发布策略与数据格式

> **非官方项目，与 DeepSeek 无关。** 页面：<https://deepsuck.si/intel.html> · 数据：[`site/data/intel.json`](../site/data/intel.json) · 格式：[`site/data/intel.schema.json`](../site/data/intel.schema.json)（`deepsuck.intel-library/v1`）

DeepSuck 会**公开发布**它收集到的诈骗情报，让任何人都能检索、拦截与预警。

## 发布策略

| 类型 (`type`) | 公开方式 | 示例 |
|---|---|---|
| `phone` 诈骗电话（含 400/800、座机） | **完整公开** | `10000000001` |
| `crypto_wallet` 加密钱包地址 | **完整公开** | `TDemoExample…`（TRON） |
| `url` 诈骗网址 / 域名 | **完整公开** | `https://refund-kefu.example/dl` |
| `app` 诈骗 APP / 平台名称 | **完整公开** | `示例·安心退` |
| `script` 话术 / 手法模式 | **完整公开**（不含受害人信息） | “涉嫌洗钱 → 保密 → 安全账户” |
| `bank_card` 收款银行卡 | **部分打码**：前 4 后 4 位 + 开户行 | `6222 **** **** 1234` |
| `name` 收款户名 / 姓名 | **部分打码**：只留姓 | `王**` |
| `id_card` 身份证号 | **部分打码** | `110101********1234` |
| `account` 支付宝 / 微信 / QQ / 邮箱等个人账号 | **部分打码**：首尾各留 2 位 | `ke******26` |

**为什么银行卡和姓名要打码**：大量“跑分卡”“收款卡”属于被冒用身份、被诱骗出租或出借账户的普通人（不少是学生和老人）。部分公开既能帮助比对，又不会让无辜者被网暴。

代码实现见 [`site/assets/js/intel.js`](../site/assets/js/intel.js) 的 `publishValue()`，测试见 `tests/intel.test.js`。校验器会拒绝含 7 位以上连续数字的“打码类”条目。

## 收录原则

- 只收录**诈骗方主动暴露**的信息；不收录受害人信息，不做人肉，不对任何号码发起骚扰或“反击”；
- 每条标注首次/最近出现时间、场景、话术标签、举报次数、来源（`sandbox` / `community` / `honeypot` / `public-report`）与可信度；
- 示例数据一律 `example: true`、ID 以 `EX-` 开头，并在 `notes` 中写明「示例数据」；当前库中**只有示例数据**；
- 情报仅供参考：号码可能被回收或冒用，不能作为认定依据，以公安机关认定为准。

## 提交

1. 在[沙盒](https://deepsuck.si/demo.html)选择场景，把骗子原话逐条粘贴进去（提取与打码都在浏览器本地完成）；
2. 结束对话 → 「⇪ 提交到情报库」：按上表策略生成内容并复制；
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

沙盒、Python core 与语音端提取到**网址/域名**或**钱包地址**后，会自动与公开黑名单比对，在侧栏、情报看板和导出报告（`intel[].blocklist`）中标注「⚠ 命中公开黑名单 · 来源」或「✓ 未命中」。**命中仅供参考**：域名可能被回收、地址可能被冒用，不能作为认定依据；未命中也不代表安全。

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
