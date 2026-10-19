# 参与贡献 DeepSuck

感谢你愿意一起让骗子更累一点！参与本项目即表示你同意遵守[行为准则](CODE_OF_CONDUCT.md)。安全漏洞请勿公开提交，按 [SECURITY.md](SECURITY.md) 私密报告。

## 提交流程

1. 先开或认领一个 issue（缺陷、功能建议、情报数据问题都有模板；第一次参与可以从[新人任务](#新人任务good-first-issue)开始）；想法还不成熟可以先到 [Discussions](https://github.com/deepsucksi/deepsuck/discussions) 聊。
2. Fork 仓库，从最新 `main` 拉一个分支，命名 `<area>/<issue>-<slug>`，如 `intel/33-otp-redact`（area：`site` `voice` `intel` `corpus` `infra` `docs`）。一个分支只做一件事。
3. 提交信息用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：`feat(intel): …`、`fix(site): …`、`docs: …`。
4. 开 PR 到 `main`，按模板填写并写上 `Closes #N`。CI 全绿后由维护者 squash 合并，PR 标题就是最终提交标题。
5. 行为有变化时，在 [CHANGELOG.md](CHANGELOG.md)「未发布」下补一条。

## 新人任务（good first issue）

第一次参与，建议从带 [`good first issue`](https://github.com/deepsucksi/deepsuck/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22) 标签的 issue 开始；需要更多人手、但不一定适合新人的任务标 [`help wanted`](https://github.com/deepsucksi/deepsuck/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22help%20wanted%22)。

### 什么算新人任务

一个 issue 打上 `good first issue` 前需同时满足：

1. **范围小**：改动集中在 1–2 个文件，熟悉仓库后半天以内能完成。网站、文档和测试类的小问题优先。
2. **不碰 `deploy/`**：部署、服务器配置、CI 密钥和费用护栏都不在新人任务范围内。
3. **不需要云服务密钥**：不依赖云端语音或大模型接口，规则引擎和本地测试就能验证。
4. **不碰人设台词和情报数据**：`personas/`、`site/assets/core/personas.json` 等人设与台词，`corpus/` 话术语料，`site/data/intel.json` 情报数据，提取器与脱敏规则、schema，以及 `eval/`、`docs/EVAL.md` 里的评测数字，都需要先了解项目背景，由维护者处理。
5. **本地能验证**：`npm test` 能覆盖改动（涉及 Python 时再加 `npm run test:py`），issue 里写明要跑的命令和要通过的测试。
6. **写清楚、有人带**：用「新人任务」模板写明背景、要做什么、涉及文件、怎么验证、完成标准、预估难度和联系人；联系人在 48 小时内回复评论。

### 怎么认领

1. 在 issue 下留言说明你想做（例如「我来做这个」），等维护者把 issue 分配给你再开工，避免两个人做同一件事。
2. 同一时间只认领一个新人任务，做完再领下一个。
3. 做不完或卡住了，直接在 issue 里说明进度。认领后两周没有 PR 也没有进度评论，维护者会取消分配，并把标签改为 `help wanted`，留给其他人。

### 怎么提 PR

1. 按上面的「提交流程」：fork 仓库，从最新 `main` 拉分支 `<area>/<issue>-<slug>`（如 `site/83-skip-link`），一个 PR 只解决一个 issue。
2. 提交前本地跑 `npm test`，确认全部通过；提交信息与 PR 标题用 Conventional Commits，如 `fix(site): 沙盒页补跳到正文链接`。
3. PR 描述按模板填写，写上 `Closes #N`；UI 改动附桌面与手机截图；行为有变化时在 [CHANGELOG.md](CHANGELOG.md)「未发布」下补一行。
4. CI 全绿、维护者审核通过后 squash 合并。审核意见直接在 PR 里回复并追加提交即可。

### 在哪里提问

- 关于某个任务本身（范围、做法、验收）：在该 issue 下评论，联系人会回复。
- 环境搭建、本地跑不起来、不知道从哪里入手：到 Discussions 的[「问答」](https://github.com/deepsucksi/deepsuck/discussions/categories/%E9%97%AE%E7%AD%94)分类发帖。
- 请不要在 issue、PR 或讨论区贴出密钥、`.env` 内容或任何真实个人信息。

### 维护者：开新人任务

用「新人任务」模板（[`.github/ISSUE_TEMPLATE/good-first-issue.yml`](.github/ISSUE_TEMPLATE/good-first-issue.yml)）新建 issue，模板会自动加 `good first issue`，提交后再补 `area:*`。开之前先在仓库里核实问题确实存在，并对照上面的六条。

## 开发

- 纯 HTML/CSS/JS，无构建步骤。`npm start` 或 `cd site && python3 -m http.server 8080` 即可预览；完整上手见 [docs/QUICKSTART.md](docs/QUICKSTART.md)，目录与数据流见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
- 可选后端：`cp .env.example .env && npm start`（Node ≥ 18，零依赖）。
- 测试：`npm test`（Node 内置 `node:test`）。请为新的提取规则/话术规则补充测试。
- 模块为 UMD 风格：浏览器挂在 `window.DeepSuck.*`，Node 中 `require` 使用。请保持零依赖。
- **规则与台词在 `site/assets/core/*.json`**（提取正则、话术关键词、人设台词、场景样例）。改完运行 `npm run build:core` 生成 `core-data.js`；正则请只用 JS 与 Python `re` 都支持的语法（不用命名分组、`\p{}`）。
- 台词可以写成 `{"when": "流水|冻结", "t": "……"}`：只在骗子本轮提到相关词时才会出现，避免答非所问。
- 博客文章在 `content/blog/{zh,en}/*.md`，改完运行 `npm run blog` 重新生成 `site/blog/` 与 `site/sitemap.xml` 并一起提交（写法见 `content/blog/README.md`）。
- 情报库数据在 `site/data/intel.json`，必须通过 `intel.js` 的校验（`npm test` 会检查）。真实情报请走 Issue 模板提交，由维护者审核收录。

- 维护者与常驻贡献者的完整流程（分支、合并、worktree、部署、发版、完成定义）见 [docs/CONTRIBUTING-dev.md](docs/CONTRIBUTING-dev.md)，关键架构决策见 [docs/adr/](docs/adr/)。

## 规则

1. **不得提交真实个人信息**：样例台词、测试用例中的卡号、电话、地址、域名必须是虚构的（可用明显的测试号段/测试地址）。
2. **脱敏不可绕过**：任何新的展示或导出路径都必须使用 `redact.js` 的结果（`masked`），不得输出原文。
3. **只做防御**：不接受主动外呼、群发、骚扰、"反向诈骗"、攻击或入侵类功能。
4. 人设模板不得给出真实或看似真实的验证码/卡号/密码/身份证号。
5. 新增场景请在 `scenarios.js` 中写清 `goals`（希望诱导暴露的情报类型）。
6. 公开文案（站点、README、docs）不点名任何商业公司或产品，`npm test` 里的 `brand_copy` 测试会检查。

## 许可

提交即表示你同意以 Apache-2.0 许可发布你的代码贡献；提交到情报库的情报数据以 CC BY 4.0 许可发布，署名「DeepSuck (deepsuck.si)」，见 [DATA_LICENSE](DATA_LICENSE)。
