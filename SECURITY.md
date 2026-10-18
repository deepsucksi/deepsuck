# 安全策略 / Security Policy

## 支持的版本 / Supported versions

只对 `main` 分支和最新发布版本提供安全修复。Security fixes are provided for `main` and the latest release only.

## 报告漏洞 / Reporting a vulnerability

**请不要通过公开 issue、PR 或 Discussions 报告安全问题。** 请使用 GitHub 私密漏洞报告：
<https://github.com/deepsucksi/deepsuck/security/advisories/new>（仓库 Security 页 → Report a vulnerability）。

**Please do not report security issues in public issues, pull requests or discussions.** Use GitHub private vulnerability reporting instead (link above).

请尽量包含 / Please include:

- 受影响的组件与版本或提交号 / affected component and version or commit
- 复现步骤或概念验证 / steps to reproduce or a proof of concept
- 影响评估 / impact

报告中请不要附带真实个人信息或可用的密钥；如确需示例，请打码。Do not include real personal data or working secrets.

## 处理流程 / What to expect

- 3 个工作日内确认收到，7 天内给出初步评估。We aim to acknowledge within 3 business days and assess within 7 days.
- 修复后发布安全公告并致谢报告者（除非你希望匿名）。We publish an advisory after the fix and credit reporters unless they prefer anonymity.

## 范围 / Scope

特别关注：脱敏被绕过（未打码的卡号、姓名、账号被展示或导出）、密钥泄露、代理被滥用产生费用、情报 intake 流程被注入。Of particular interest: redaction bypass, secret exposure, proxy abuse that incurs cost, and injection into the intel intake pipeline.

真实诈骗线索请走情报提交模板或报警（110），不属于安全漏洞。Real scam reports belong in the intel submission form or with the police, not here.
