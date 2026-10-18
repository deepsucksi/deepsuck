# 开发规范（维护者与常驻贡献者）

面向日常开发的流程约定。通用贡献规则（不提交真实个人信息、脱敏不可绕过、只做防御）见根目录 [CONTRIBUTING.md](../CONTRIBUTING.md)，模块全景见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 工作流

1. **先有 issue**：每项工作对应一个 issue，写清背景与验收标准，打上 `area:*`、`type:*`、`priority:*` 标签并挂到里程碑。
2. **开分支**：从最新 `main` 拉分支，按模块命名：

   | 前缀 | 范围 |
   |---|---|
   | `site/*` | `site/`、前端 JS、站点文案 |
   | `voice/*` | `voice/`、电话适配 |
   | `intel/*` | 提取、脱敏、intake、STIX/订阅源、`python/deepsuck` |
   | `corpus/*` | `personas/`、`corpus/`、`eval/` |
   | `infra/*` | `deploy/`、CI、服务器 |
   | `docs/*` | 只改文档 |

   例：`voice/turn-fallback-3`（末尾带 issue 号更好找）。
3. **PR 必须关联 issue**：描述里写 `Closes #N`（或 `Refs #N`），说明动机、改动、测试方式。
4. **合并**：CI 全绿后合并到 `main`；推送前先 `git pull --rebase`，多人并行时不要强推。
5. **状态**：开工时给 issue 加 `status:in-progress`，被外部条件卡住加 `status:blocked` 并在评论里写清等什么；需要负责人拍板的加 `needs-owner-decision`。

## 模块边界（摘要）

- 规则、台词、人设只改 `site/assets/core/*.json`，改完 `npm run build:core` 与 `npm run fixtures` 并提交生成物。
- 改了提取 / 脱敏 / 规范化 / 真人化任一侧实现，另一侧必须跟上，`npm test` 与 `npm run test:py` 都要过。
- `voice/` 只读 core JSON，不读 `site/` 的页面文件；`voice/telephony/` 不新增对 `voice/app.py` 的依赖。
- `deploy/` 不放业务逻辑；密钥只放服务器环境变量。

## 完成定义（DoD）

- [ ] 满足 issue 的验收标准
- [ ] 有对应测试，`npm test`、`npm run test:py`、相关的 `pytest voice/tests` / `corpus` / `personas` 全绿
- [ ] UI 改动附桌面与手机截图
- [ ] 新的展示 / 导出 / 落盘路径经过脱敏
- [ ] 不含密钥、令牌、真实个人信息；不点名其他商业公司或产品
- [ ] 行为或部署方式变了，同步更新 docs（必要时新增 ADR）

## 迭代与每日进度

- 迭代按里程碑走（如“v0.4 全流程跑通”“v0.5 电话接入”），未排期的放“后续”。
- 每日进度可直接从 GitHub 生成：

```bash
R=deepsucksi/deepsuck
gh issue list -R $R --label status:in-progress            # 进行中
gh issue list -R $R --label status:blocked                # 阻塞
gh issue list -R $R --state closed --search "closed:>=$(date -d yesterday +%F)"   # 昨日完成
gh api "repos/$R/milestones" --jq '.[]|"\(.title): 未完成 \(.open_issues) / 已完成 \(.closed_issues)"'
```

日报格式：昨日完成 / 今日计划 / 阻塞与需要决策，每项带 issue 号。
