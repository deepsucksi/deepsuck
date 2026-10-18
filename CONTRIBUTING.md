# 参与贡献 DeepSuck

感谢你愿意一起让骗子更累一点！参与本项目即表示你同意遵守[行为准则](CODE_OF_CONDUCT.md)。安全漏洞请勿公开提交，按 [SECURITY.md](SECURITY.md) 私密报告。

## 提交流程

1. 先开或认领一个 issue（缺陷、功能建议、情报数据问题都有模板）；想法还不成熟可以先到 [Discussions](https://github.com/deepsucksi/deepsuck/discussions) 聊。
2. Fork 仓库，从最新 `main` 拉一个分支，命名 `<area>/<issue>-<slug>`，如 `intel/33-otp-redact`（area：`site` `voice` `intel` `corpus` `infra` `docs`）。一个分支只做一件事。
3. 提交信息用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：`feat(intel): …`、`fix(site): …`、`docs: …`。
4. 开 PR 到 `main`，按模板填写并写上 `Closes #N`。CI 全绿后由维护者 squash 合并，PR 标题就是最终提交标题。
5. 行为有变化时，在 [CHANGELOG.md](CHANGELOG.md)「未发布」下补一条。

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
