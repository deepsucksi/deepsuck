<!-- 标题用 Conventional Commits：<type>(<scope>): <说明>，例如 fix(intel): 跨回合卡号拼接误报。合并时以 PR 标题作为 squash 提交信息。 -->
<!-- Title follows Conventional Commits: <type>(<scope>): <summary>. The PR title becomes the squash commit message. -->

## 关联 issue / Related issue

Closes #

## 改动说明 / What & why

-

## 测试 / Testing

- [ ] `npm test`
- [ ] `npm run test:py` / `pytest corpus personas` / `pytest voice/tests`（涉及 Python 时）
- 其他验证方式 / Other checks:

## 截图 / Screenshots

<!-- UI 改动请附桌面与手机截图；无 UI 改动写“无”。 -->

## 是否需要部署 / Deployment

- [ ] 不需要 / No
- [ ] 需要：合并后在服务器执行部署命令（见 docs/CONTRIBUTING-dev.md「部署」）/ Yes, deploy after merge
- [ ] 需要改服务器环境变量或 `deploy/.env`（在下方写清变量名，不写值）

## 自查 / Checklist

- [ ] 不含密钥、令牌、密码、`.env` 内容 / No secrets or tokens
- [ ] 不含真实个人信息（卡号、电话、姓名、地址均为虚构或已打码）/ No real personal data
- [ ] 公开文案不点名任何商业公司或产品 / No commercial company or product names in public text
- [ ] 分支只做这一个 issue，CI 全绿 / One issue per branch, CI green
- [ ] 行为或部署方式有变化时已更新 docs 与 CHANGELOG「未发布」/ Docs and CHANGELOG updated if behavior changed
