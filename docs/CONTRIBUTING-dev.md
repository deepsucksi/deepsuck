# 开发规范（维护者与常驻贡献者）

面向日常开发的流程约定，人和 AI 代理一视同仁。通用贡献规则（不提交真实个人信息、脱敏不可绕过、只做防御）见根目录 [CONTRIBUTING.md](../CONTRIBUTING.md)，模块全景见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 速查

```text
issue → 分支 <area>/<issue>-<slug>（独立 worktree）→ Conventional Commits → 推送 → gh pr create（Closes #N）
→ gh pr merge --squash --auto → CI 全绿后自动 squash 合并、自动删分支 → 需要时部署并公告提交号
```

## 1. 先有 issue

每项工作对应一个 issue，写清背景与验收标准，打上 `area:*`、`type:*`、`priority:*` 标签并挂到里程碑。开工时加 `status:in-progress`，被外部条件卡住加 `status:blocked` 并在评论里写清等什么；需要负责人拍板的加 `needs-owner-decision`。

## 2. 分支

- 命名：`<area>/<issue>-<slug>`，`slug` 用小写英文和连字符，例：`voice/21-turn-fallback`、`intel/33-otp-redact`。

  | area | 范围 |
  |---|---|
  | `site` | `site/`、前端 JS、站点文案 |
  | `voice` | `voice/`、电话适配 |
  | `intel` | 提取、脱敏、intake、STIX/订阅源、`python/deepsuck` |
  | `corpus` | `personas/`、`corpus/`、`eval/` |
  | `infra` | `deploy/`、CI、服务器 |
  | `docs` | 只改文档 |

- **一个 issue 一个分支、一个 PR**。顺手发现的别的问题另开 issue，不要塞进当前分支。
- **短命分支**：从最新 `origin/main` 拉出，约 2 天内合并；做不完就拆小，或关闭 PR、删分支，在 issue 里写明进度。
- 不在别人的分支上提交；不建长期集成分支；`main` 之外不保留发布分支（发布用标签）。
- 合并后远端分支自动删除。本地 worktree 由自己清理（见第 5 节）。

## 3. 提交信息：Conventional Commits

格式 `<type>(<scope>): <说明>`，`scope` 用上表的 area，说明用中文或英文，一句话讲清改了什么：

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修复缺陷 |
| `docs` | 只改文档 |
| `refactor` | 不改行为的重构 |
| `test` | 只加或改测试 |
| `chore` | 构建、依赖、CI、杂项 |

例：`fix(intel): 跨回合卡号拼接不再误吞手机号`、`docs(infra): 补充部署公告步骤`。破坏性变更在类型后加 `!`（`feat(voice)!: …`）并在正文写 `BREAKING CHANGE:`。

## 4. PR 与合并

- `main` 受保护：**禁止直接推送、强推和删除**，所有改动都走 PR；只允许 squash 合并，历史保持线性。
- PR 标题同样遵守 Conventional Commits，squash 后的提交标题就是 PR 标题；描述按模板填写，必须写 `Closes #N`（或 `Refs #N`）。
- 必须通过的检查：CI `test` 工作流（`.github/workflows/test.yml`）的五项检查全绿：`node`、`voice`、`python (3.9)`、`python (3.12)`、`deploy`，且分支与 `main` 同步。落后时执行 `gh pr update-branch <PR号>`（或在分支上 `git fetch && git rebase origin/main` 后 `git push --force-with-lease`，只限自己的分支）。
- 开启自动合并：`gh pr merge <PR号> --squash --auto`。CI 通过后 GitHub 自动 squash 合并并删除分支。不要手动绕过 CI 合并。
- **管理员绕过仅限紧急情况**（线上事故、CI 本身坏了且阻塞修复）：只能通过 PR 绕过（`gh pr merge <PR号> --squash --admin`），任何人（包括管理员和部署密钥）都不能直接推送 `main`。由负责人决定并执行，事后在相关 issue 里写明原因，并补一个正常 PR 修复根因。代理日常一律不用 `--admin`。

```bash
R=deepsucksi/deepsuck
gh pr create -R $R --base main --head <branch> --title "fix(intel): …" --body-file pr.md
gh pr merge  -R $R <PR号> --squash --auto
gh pr checks -R $R <PR号> --watch
```

## 5. git worktree：一个分支一个 worktree

开发可以在两个地方做：开发服务器（VPS）和共享电脑。需要调用大模型的评测，在共享电脑上跑。

| 位置 | 共用检出目录（只用来 `fetch` 和管理 worktree） | worktree 路径 |
|---|---|---|
| VPS | `/opt/deepsuck-dev` | `/opt/deepsuck-wt/<role>-<branch>` |
| 共享电脑 | `/workspace/deepsuck` | `/workspace/deepsuck-wt/<role>-<branch>` |

`<branch>` 里的 `/` 换成 `-`，例：分支 `voice/21-turn-fallback` 由语音线开发，worktree 为 `voice-voice-21-turn-fallback`。

硬性规定：

- **一个分支对应一个独立的 worktree**。
- **绝不在共用的检出目录 `/opt/deepsuck-dev` 和 `/workspace/deepsuck` 里 checkout 或提交**，也不在里面改文件、不动里面未提交的东西。
- 生产目录 `/opt/deepsuck` 只用来执行下面的部署命令，不在里面改文件、切分支或提交。
- 只推自己的分支；PR 合并（或关闭）后删掉对应的 worktree。
- **每完成一个阶段就推一次自己的分支**，别攒本地提交。

VPS：

```bash
git -C /opt/deepsuck-dev fetch origin
git -C /opt/deepsuck-dev worktree add /opt/deepsuck-wt/<role>-<branch> -b <branch> origin/main
# 工作、提交、推送自己的分支……
git -C /opt/deepsuck-dev worktree remove /opt/deepsuck-wt/<role>-<branch>   # PR 合并或关闭后
git -C /opt/deepsuck-dev worktree prune
```

共享电脑：

```bash
git -C /workspace/deepsuck fetch origin && git -C /workspace/deepsuck worktree add /workspace/deepsuck-wt/<role>-<branch> -b <branch> origin/main
# 工作、提交、推送自己的分支……
git -C /workspace/deepsuck worktree remove /workspace/deepsuck-wt/<role>-<branch>   # PR 合并或关闭后
git -C /workspace/deepsuck worktree prune
```

- 推送认证：VPS 上用部署密钥（只能推分支，推 `main` 会被拒绝）；共享电脑上远端走 HTTPS，推送时临时借用已登录的 `gh` 作为 git 凭据助手，例如 `git -c credential.helper= -c credential.helper='!gh auth git-credential' push -u origin <branch>`。不在文档、命令或日志里写令牌。
- 开 PR、合并用已登录的 `gh`。

### 停止进程：只停自己启动的

共享电脑上多人和多个代理同时在跑测试、评测，**不许按名字杀进程**（`pkill -f pytest`、`pkill node`、`killall …` 都不行），只能用自己记下的 PID 停自己启动的进程。按名字杀会误伤别人正在跑的测试和付费评测，费用台账也会对不上。

```bash
npm test > /tmp/<role>-test.log 2>&1 &
echo $! > /tmp/<role>-test.pid          # 后台启动时记下 PID
kill "$(cat /tmp/<role>-test.pid)"      # 停的时候只停这个 PID
```

## 6. 部署

只部署已合并到 `main` 的提交：

```bash
cd /opt/deepsuck && git pull --ff-only && cd deploy && docker compose up -d --build
git -C /opt/deepsuck log -1 --format='%h %s'   # 记下部署的提交
```

部署后做冒烟检查（站点首页、`/api/health`、语音页），然后**公告**：在对应 PR 或 issue 下评论「已部署 `<短提交号>`」，并在团队频道同步一行“已部署 `<短提交号>`：<PR 标题>（#PR）”。改了 `deploy/.env` 或服务器配置时，公告里写变量名，不写值。更多细节见 [DEPLOY.md](DEPLOY.md)。

## 7. 版本与发布

- 版本号遵守 [SemVer](https://semver.org/lang/zh-CN/)：标签 `v0.4.0`、`v0.4.1`、`v0.5.0`……；`package.json` 的 `version` 与标签一致。
- [CHANGELOG.md](../CHANGELOG.md) 采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式：日常 PR 往「未发布」下的 `新增 / 变更 / 修复 / 移除 / 安全` 小节追加条目。
- **里程碑即版本**：里程碑名与版本对应（如 `v0.4 全流程跑通` → `v0.4.0`），里程碑里的 issue 全部关闭才发布。
- 发布步骤（负责人或指定代理执行）：
  1. 开一个 `docs/<issue>-release-vX.Y.Z` PR：把「未发布」改成 `## [X.Y.Z] - YYYY-MM-DD`，更新 `package.json` 版本，squash 合并。
  2. 在合并后的 `main` 上打标签并发布，说明取自 CHANGELOG 对应小节，下面附自动生成的 PR 列表（分类见 `.github/release.yml`）：

```bash
R=deepsucksi/deepsuck; V=0.4.0
awk -v v="$V" '$0 ~ "^## \\["v"\\]"{f=1;next} /^## /{f=0} f' CHANGELOG.md > /tmp/notes.md
gh release create "v$V" -R $R --target main --title "v$V" --notes-file /tmp/notes.md --generate-notes
```

  3. 关闭对应里程碑，部署并公告。

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

## 密钥扫描（#224）

仓库里只能出现变量名，不能出现值。绝不读取、复制、上传俊杰本机（Mac）上的任何密钥、令牌、`.env` 或配置文件，命令一律不带 machineId。

推送前自己扫一遍：

```bash
pip install pre-commit && pre-commit install   # 之后每次 git commit 自动扫暂存区
gitleaks git --redact .                         # 手动扫全部历史
```

**推送前密钥扫描必须成功；扫描失败或没有运行，一律禁止推送（#229）。** 推荐在仓库公共 git 目录装 pre-push 钩子（`.git/hooks/pre-push`，所有 worktree 共用）：用 gitleaks 8.21.2 和 `.gitleaks.toml` 扫描待推送范围（新分支扫 `origin/main..本地提交`），找不到 gitleaks、版本不对、有命中或出错都退出非零、拒绝推送；再配合上面的 `pre-commit install` 在提交时拦截。

CI 的 node job 也会扫全部历史，命中就失败。确认是误报（比如公开测试地址）才在 `.gitleaks.toml` 的 allowlist 里放行，并在 PR 里写明理由；拿不准先停下来问负责人。
