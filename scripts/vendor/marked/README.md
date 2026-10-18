# marked（随仓库附带的第三方库）

- 版本：marked 15.0.12（MIT，见同目录 `LICENSE.md`），文件取自 npm 包 `lib/marked.cjs`，未改动。
- npm 包 sha256：`39a847a896af15b2846f927da55d444619ea55a55c236e10333056474b793aaa`（`marked-15.0.12.tgz`）
- 用途：`scripts/build-blog.js` 把 `content/blog/` 下的 Markdown 转成静态 HTML。
- 为什么随仓库附带而不是写进 `dependencies`：仓库目前零依赖，CI 与 Pages 工作流只跑 `npm test`、不装依赖。附带一个文件就不用改两个工作流、不用引入 lockfile。15.x 是最后一个支持 Node 18 的大版本，与 `package.json` 的 `engines` 一致。
- 升级：`npm pack marked@<版本>`，解包后把 `package/lib/marked.cjs` 和 `package/LICENSE.md` 拷到这里，更新本文件的版本和 sha256，再跑 `npm run blog && npm test`。
