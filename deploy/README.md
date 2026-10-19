# deploy/

部署脚本和 compose 配置。完整的上线步骤、费用护栏、故障排查见 [docs/DEPLOY.md](../docs/DEPLOY.md)。

## 运维 / 排查：查看配置时不展开密钥（#119）

- 查看 compose 配置一律用 `docker compose --profile sip config --no-interpolate`（在 `deploy/` 目录下）。
- **不要**运行不带 `--no-interpolate` 的 `docker compose config`：它会把 `.env` 里的密钥（`SIP_PASSWORD`、`DASHSCOPE_API_KEY`、`TRACE_ADMIN_TOKEN`、`TURN_SECRET` 等）原样展开成明文打到终端和日志里。
- 要确认某个变量设没设，只看变量名、不看值：

  ```bash
  grep -o '^[A-Z_]*=' .env                                                    # .env 里设了哪些变量
  docker compose --profile sip config --no-interpolate | grep -o '\${[A-Z_]*' | sort -u   # compose 引用了哪些变量
  ```

- 不要 `cat .env`、`printenv`、`docker compose exec <服务> env`，也不要把这些输出贴进 issue、PR 或聊天。
- 万一已经打出来了：当作泄露处理，告诉负责人安排轮换对应的密钥。

其他排查见 [docs/DEPLOY.md 第 7 节](../docs/DEPLOY.md#7-故障排查)。
