# 参与贡献 DeepSuck

感谢你愿意一起让骗子更累一点！

## 开发

- 纯 HTML/CSS/JS，无构建步骤。`npm start` 或 `cd site && python3 -m http.server 8080` 即可预览；完整上手见 [docs/QUICKSTART.md](docs/QUICKSTART.md)，目录与数据流见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
- 可选后端：`cp .env.example .env && npm start`（Node ≥ 18，零依赖）。
- 测试：`npm test`（Node 内置 `node:test`）。请为新的提取规则/话术规则补充测试。
- 模块为 UMD 风格：浏览器挂在 `window.DeepSuck.*`，Node 中 `require` 使用。请保持零依赖。
- **规则与台词在 `site/assets/core/*.json`**（提取正则、话术关键词、人设台词、场景样例）。改完运行 `npm run build:core` 生成 `core-data.js`；正则请只用 JS 与 Python `re` 都支持的语法（不用命名分组、`\p{}`）。
- 台词可以写成 `{"when": "流水|冻结", "t": "……"}`：只在骗子本轮提到相关词时才会出现，避免答非所问。
- 情报库数据在 `site/data/intel.json`，必须通过 `intel.js` 的校验（`npm test` 会检查）。真实情报请走 Issue 模板提交，由维护者审核收录。

## 规则

1. **不得提交真实个人信息**：样例台词、测试用例中的卡号、电话、地址、域名必须是虚构的（可用明显的测试号段/测试地址）。
2. **脱敏不可绕过**：任何新的展示或导出路径都必须使用 `redact.js` 的结果（`masked`），不得输出原文。
3. **只做防御**：不接受主动外呼、群发、骚扰、"反向诈骗"、攻击或入侵类功能。
4. 人设模板不得给出真实或看似真实的验证码/卡号/密码/身份证号。
5. 新增场景请在 `scenarios.js` 中写清 `goals`（希望诱导暴露的情报类型）。
6. 提交信息建议使用简洁的中文或英文，PR 描述中说明动机与测试方式。

## 许可

提交即表示你同意以 Apache-2.0 许可发布你的贡献。
