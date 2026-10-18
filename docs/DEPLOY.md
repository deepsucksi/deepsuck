# 上线“实时服务”：大模型对话 + 语音演示（docs/DEPLOY.md）

> 静态站（https://deepsuck.si）继续由 GitHub Pages 托管、零成本；
> 本文只讲**可选**的实时服务 `live.deepsuck.si`：文字沙盒的大模型回复（Node 代理）+ 浏览器麦克风语音演示（Pipecat）。
> 没有实时服务时，一切照常——沙盒自动用规则引擎。

```
浏览器 ──HTTPS──▶ deepsuck.si（GitHub Pages，静态）
   │  live-config.js 配了 api 时：
   ├──HTTPS──▶ live.deepsuck.si ─ Caddy(80/443，自动证书)
   │                                ├─ /api/chat /api/health ─▶ proxy（Node，127.0.0.1:8787）─▶ DashScope qwen-plus
   │                                └─ / /api/config /api/offer ─▶ voice（Pipecat，127.0.0.1:7860）─▶ DashScope Paraformer / qwen3.7-flash / CosyVoice
   └──UDP 40000–40199（WebRTC 音频，直连服务器公网 IP）──▶ voice
```

部署包在 [`deploy/`](../deploy)：`Dockerfile.proxy`、`Dockerfile.voice`、`docker-compose.yml`、`caddy/Caddyfile`、`.env.example`、`bootstrap.sh`。

---

## 1. 推荐服务器

**阿里云轻量应用服务器 · 中国香港 · 通用型 2 vCPU / 2 GiB / 40 GB ESSD / 峰值 200 Mbps，系统选 Ubuntu 22.04 或 24.04（或 Debian 12）。**

- 香港地域**不需要 ICP 备案**，内地访问延迟低；DashScope（北京）从香港调用正常。
- 实测内存（2026-10-18，本仓库 docker compose，见第 6 节）：

  | 组件 | 空闲 | 1 路通话 | 2 路并发通话（峰值） |
  |---|---|---|---|
  | voice（Pipecat + Silero VAD + aiortc） | 52–64 MB | ~187 MB | **245–253 MB**（cgroup memory.peak） |
  | proxy（Node） | 9–14 MB | — | — |
  | caddy | 14 MB | — | — |
  | dockerd + containerd | ~125 MB | — | — |

  合计峰值约 **420 MB + 系统 ~200 MB ≈ 0.6 GB**。2 GiB 留足余量（构建镜像、日志、突发）；
  **2 vCPU / 1 GiB 也能跑**（bootstrap 会自动加 1 GB swap），但首次构建镜像时会比较慢、余量小，只建议预算极紧时用。
- CPU：2 路并发通话实测平均 ~0.4 核（本机），换算轻量服务器 vCPU 约 0.6–0.8 核，2 vCPU 足够。
- 带宽/流量：每路通话 Opus 音频上下行合计约 0.1 Mbps，200 Mbps 峰值绰绰有余。

价格（2026-10 公开报价，**以阿里云购买页为准**）：2C2G 约 **56 元/月**；2C1G 约 34 元/月。

## 2. 需要放行的端口（轻量服务器控制台 → 防火墙）

| 端口 | 协议 | 用途 | 必需 |
|---|---|---|---|
| 22 | TCP | SSH（建议只放行自己的 IP） | 是 |
| 80 | TCP | Let's Encrypt 签证书（HTTP-01）+ 跳转 HTTPS | 是 |
| 443 | TCP | HTTPS（语音页面、/api/*） | 是 |
| 443 | UDP | HTTP/3（可选，Caddy 默认开启） | 可选 |
| **40000–40199** | **UDP** | **WebRTC 音频（`VOICE_UDP_PORTS`）** | 是 |
| 25060（`SIP_PORT`） | UDP（`SIP_TCP=1` 时另加 TCP） | 自建 SIP 软电话信令（仅 `WITH_SIP=1` / `--profile sip`，[PHONE.md 第 10 节](PHONE.md)） | 可选 |

开自建 SIP 时，40000–40199 拆成两段：40000–40099 给网页语音（`VOICE_UDP_PORTS`），40100–40199 给 SIP 的 RTP（`SIP_RTP_PORTS`），防火墙规则不用改。

### 需要 TURN 吗？——默认**不需要**

- 服务器有公网 IP（轻量服务器是 1:1 NAT：网卡上是内网 IP，公网 IP 由云平台映射，端口不变）。
  `VOICE_PUBLIC_IP` 让语音服务在 SDP 应答里额外声明“公网 IP + 同端口”的候选（同 mediasoup `announcedIp` / Janus `nat_1_1_mapping`），
  浏览器无论在家用路由器、手机 4G/5G 还是对称型 NAT 后面，都能主动打到服务器；服务器从入站检查学到浏览器的对端反射地址，不依赖任何 STUN。
- aioice 默认用随机 UDP 端口，`voice/netpatch.py` 把它限制在 `VOICE_UDP_PORTS`，所以防火墙只需开这一段（每路通话占 1–3 个端口，200 个足够）。
- 只有**访客网络完全封 UDP**（部分公司/校园网、不转发 UDP 的代理/VPN）才连不上。这时启用 coturn：`WITH_TURN=1`，
  或手动在 `.env` 填 `TURN_SECRET`（`openssl rand -hex 32`）、`TURN_URLS=turn:域名:443?transport=tcp,turns:域名:443?transport=tcp`，
  再 `docker compose --profile turn up -d coturn && docker compose up -d --build caddy voice`。

### TURN 走 443（不用另开端口）

Caddy 镜像带 [caddy-l4](https://github.com/mholt/caddy-l4)（`deploy/Dockerfile.caddy`），在 443 上 TLS 解密之前先看连接头几个字节：

| 连接 | 判断 | 去向 |
|---|---|---|
| 明文 TURN（`turn:域名:443?transport=tcp`） | 前 8 字节是 STUN 头（magic cookie `2112A442`） | 本机 coturn `127.0.0.1:3478` |
| TURN over TLS（`turns:域名:443?transport=tcp`） | TLS，且没带 `h2` / `http/1.1` / `acme-tls/1` ALPN | Caddy 用本站证书解开；里面是 STUN 就转 coturn，否则带 PROXY 协议转本机 `127.0.0.1:8444` 照常当网站服务 |
| 浏览器 HTTPS、证书续期 | 其余 | 照常进 HTTP，不受影响 |

coturn 只监听 `127.0.0.1`，中继地址用内网 IP、只允许中继到本机内网 IP（语音服务），所以 3478 和中继端口段都**不需要**对公网开放。
凭据：`POST /api/ice` 在开始通话前现发 coturn REST 临时凭据（HMAC-SHA1，`TURN_TTL` 默认 600 秒），不落盘；页面配置 `/api/config` 里不带凭据。
限制：只中继到本机、总配额 12 个分配、每路 200 kbps、coturn 内存上限 64 MB。

验证（只走中继，计费一通）：`python -m voice.probe --url https://域名 --origin https://域名 --wav x.wav --relay tcp`（或 `--relay tls`）。

## 3. 一键部署（约 10 分钟）

前提：已有服务器 root 登录；手上有 DashScope（百炼，**北京地域**）API Key。

```bash
ssh root@<服务器公网IP>
curl -fsSL https://raw.githubusercontent.com/deepsucksi/deepsuck/main/deploy/bootstrap.sh -o bootstrap.sh
LIVE_DOMAIN='live.你的域名' ACME_EMAIL='你的邮箱' DASHSCOPE_API_KEY='sk-...' bash bootstrap.sh
# 不想把 Key 留在 shell 历史里：只传 LIVE_DOMAIN 和 ACME_EMAIL，Key 会提示输入（不回显）；
# 或者写进 600 权限的文件：  set -a; . /root/deepsuck.env; set +a; bash bootstrap.sh
```

`LIVE_DOMAIN` 和 `ACME_EMAIL` **必填，没有默认值**：bootstrap.sh 缺了会退出，`docker compose` 读到空值也会直接报错，
避免用别人的域名或邮箱去申请证书。

脚本做的事：装 git/curl → 内存 < 2.6 GB 且没有 swap 时建 swap（默认 1 GB，`SWAP_MB=2048` 可调） → 装 Docker（get.docker.com）→ clone 到 `/opt/deepsuck` →
从阿里云元数据（`100.100.100.200`）探测公网/内网 IP → 生成 `deploy/.env`（权限 600；Key 只在这里）→ 若有 ufw 自动放行端口 →
`docker compose up -d --build` → 等健康检查通过。可重复运行（不覆盖已有 `.env`）。
首次部署（本次运行新建了 `deploy/.env`）结尾会打印下面 DNS、防火墙、`live-config.js` 的提示；重跑只打印一行「已更新」摘要。
例外：重跑时带 `WITH_SIP=1` 且本次才生成 SIP 账号（运行前 `.env` 里没有 `SIP_USER`），会在摘要后打印完整 SIP 说明：要放行的 UDP 端口（`SIP_PORT` 与 RTP 段）、接 AI 的分机（默认 9000）、Linphone/Zoiper 配置和账号。密码一律不打印，用 `grep -n ^SIP_PASSWORD /opt/deepsuck/deploy/.env` 查看。首次部署带 `WITH_SIP=1` 时，SIP 说明附在下一步提示里。

然后：

1. **DNS**：在 deepsuck.si 的 DNS 处加 `A  live  <服务器公网IP>`（TTL 600）。解析生效后 Caddy 自动申请证书（看 `docker compose logs caddy`）。
2. **防火墙**：按第 2 节在轻量服务器控制台放行端口。
3. **验证**：
   ```bash
   curl https://live.deepsuck.si/api/health          # 文字代理：llmConfigured=true，看 limits / budget
   curl https://live.deepsuck.si/api/voice/health    # 语音：keyConfigured=true，active=0
   ```
   浏览器打开 `https://live.deepsuck.si/` → 开始通话。也可在自己电脑上跑端到端探针（真实计费，几分钱）：
   ```bash
   pip install -r voice/requirements.txt
   python -m voice.probe --url https://live.deepsuck.si --origin https://live.deepsuck.si --wav 一段16k单声道.wav --seconds 30
   # 输出 connected_after（秒）、bot_audio_sec、turns、intel；connected_after 为 null = UDP 不通，查防火墙 / VOICE_PUBLIC_IP
   ```
4. **接到主站**：把 `site/assets/js/live-config.js` 里的 `api: ''` 改成 `api: 'https://live.deepsuck.si'`，推送到 main。
   之后沙盒会探测 `/api/health`：可用且当日额度没用完就自动用大模型，导航栏出现「语音演示」；任何失败都回退规则引擎。
5. **百炼控制台再加一道保险**：费用中心设置**预算告警**；用单独的 API Key（只给这个服务用，泄露可单独作废）。

日常运维：

```bash
cd /opt/deepsuck && git pull && cd deploy && docker compose up -d --build   # 更新
docker compose logs -f --tail=100 voice                                     # 日志
nano /opt/deepsuck/deploy/.env && docker compose up -d                       # 改护栏参数
docker compose exec voice cat /data/voice-budget.json                       # 当日语音用量
docker compose exec proxy cat /data/chat-budget.json                        # 当日文字用量
docker compose down                                                         # 停服（不会产生任何 DashScope 费用）
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile        # 改了 deploy/caddy/Caddyfile 后生效（或 docker compose restart caddy）
```

### Caddyfile 改为目录挂载（2026-10 一次性迁移）

旧版把 `deploy/Caddyfile` 按单个文件绑定挂载到容器的 `/etc/caddy/Caddyfile`。`git pull` 替换文件时 inode 会变，容器里看到的仍是旧内容，只能手动 force-recreate。现在 Caddyfile 移到 `deploy/caddy/Caddyfile`，整个 `deploy/caddy/` 目录挂载到容器的 `/etc/caddy`（只读）。

已经部署的服务器，这次 `git pull` 之后执行一次：

```bash
cd /opt/deepsuck && git pull && cd deploy
docker compose up -d --build
docker compose up -d --force-recreate caddy   # 仅这一次，把旧的单文件挂载换成目录挂载
docker compose exec caddy ls /etc/caddy        # 应看到 Caddyfile
```

重新运行 `bootstrap.sh` 的话会自动检测旧挂载并重建 caddy，不用手动执行。此后修改 Caddyfile 只需 `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile` 或 `docker compose restart caddy`，不再需要 force-recreate。

## 4. 费用护栏（默认值，全部可在 `deploy/.env` 调）

**文字对话（server/guard.js）**

| 变量 | 默认 | 说明 |
|---|---|---|
| `CHAT_DAILY_BUDGET_CNY` | **2 元/天** | 按 DashScope 返回的 usage token 实时记账；每次调用前按“估算输入 + max_tokens 输出”**预占**，超额直接 429，不打上游 |
| `RATE_LIMIT_PER_MIN` / `RATE_LIMIT_PER_DAY` | 20 / 300 | 每 IP |
| `GLOBAL_RATE_PER_MIN` | 60 | 全站 |
| `CHAT_MAX_TURNS` | 40 | 每局骗子发言轮数上限 |
| `LLM_MAX_TOKENS` | 120 | 每次回复输出上限（回复本来就要求 ≤ 80 字） |
| `ALLOWED_ORIGINS` | deepsuck.si、www.deepsuck.si | CORS 白名单；`/api/chat` 无 Origin 或不在白名单 → 403 |

**语音演示（voice/guard.py）**

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_DAILY_BUDGET_CNY` | **5 元/天** | ASR 按发送音频秒数、TTS 按字符、LLM 按 usage token 实时记账；**开局按本局最坏花费预占**（默认参数下 ≈ 0.33 元），并发也不会超额；用完当天新通话 429，进行中的通话会礼貌告别后挂断 |
| `VOICE_MAX_SESSIONS` | **2** | 同时通话路数，满了 503 |
| `VOICE_MAX_MINUTES` | 5 | 每局最长时长 |
| `VOICE_MAX_TURNS` | 30 | 每局轮数 |
| `VOICE_IDLE_SECONDS` | 60 | 静默自动挂断（浏览器一直在推音频，ASR 按时长计费，静默也花钱） |
| `VOICE_PER_IP_PER_HOUR` / `_PER_DAY` | 4 / 10 | 每 IP 通话次数 |
| `VOICE_ALLOWED_ORIGINS` | live.deepsuck.si、deepsuck.si | `/api/offer` 的 Origin 白名单 |
| `VOICE_CONNECT_TIMEOUT` | 30 秒 | WebRTC 没连上就释放名额与预占额度 |

其它：Caddy 限制请求体 64 KB；应用只监听 127.0.0.1；账本按北京时间自然日存到卷里（重启不清零）；
只有 proxy/voice 容器拿到 Key；`/api/health`、`/api/config` 只返回百分比，不回显 Key。

**电话入口与留存（默认全部关闭，详见 [PHONE.md 第 6 节](PHONE.md#6-环境变量清单供-deploy-使用)）**

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_TELEPHONY` | `0` | `1` 才挂载 `WS /telephony/{adapter}`（经 Caddy 转发到语音服务） |
| `VOICE_TELEPHONY_TOKEN` | 空 | 开电话时必填；为空时拒绝所有电话连接 |
| `VOICE_TELEPHONY_ADAPTERS` | `ws-raw` | `ws-raw`、`pipecat-ws` |
| `VOICE_AI_DISCLOSURE` / `_TEXT` | `0` / 默认文案 | 开场白前播告知语（网页和电话共用） |
| `VOICE_TRANSCRIPTS` / `VOICE_TRANSCRIPT_DAYS` | `1` / `30` | 脱敏文字记录及保留天数 |
| `KEEP_AUDIO` / `KEEP_AUDIO_DAYS` | `0` / `7` | 原始音频，最长 7 天 |

容器内 `DATA_DIR=/data` 固定挂命名卷 `voice-data`（留存文件在 `/data/voice/{transcripts,audio}/`），重建容器不会丢；
查看：`docker compose exec voice ls /data/voice`。

## 5. 月度费用估算

单价（2026-10 百炼北京地域原价，以控制台为准）：文字代理 qwen-plus 输入 0.8 元/百万 token、输出 2 元/百万 token；语音默认 qwen3.7-flash（非思考）输入 0.2、输出 0.8 元/百万 token（选型见 [LLM_AB.md](LLM_AB.md)）；
paraformer-realtime-v2 0.00024 元/秒（每月 10 小时免费）；cosyvoice-v3-flash 1 元/万字符。
改用设计音色（`DEEPSUCK_VOICE_WANG=cosyvoice-v3.5-flash-vd-...`）时，合成按 cosyvoice-v3.5-flash 0.8 元/万字符计（约每句 0.004 元），创建音色免费，保有费以百炼控制台计费页为准，见 [voice/README.md](../voice/README.md)（2026-10-18 查询）。

实测单次用量（本仓库 `voice.probe`，王阿姨 × 冒充客服）：

| 场景 | ASR | TTS | LLM | 合计 |
|---|---|---|---|---|
| 33 秒语音通话（2 轮） | 32.9 s → 0.0079 元 | 114 字 → 0.0114 元 | 843 in / 68 out → 0.0008 元 | **≈ 0.02 元** |
| 推算 5 分钟满时长通话 | 0.072 元 | ~0.08–0.1 元 | ~0.01 元 | **≈ 0.17–0.19 元** |
| 一条文字回复（短对话 / 长对话） | — | — | 300–1500 in / ~40 out | **0.0003–0.0013 元** |

TTS（字符计费）是语音的大头，ASR 次之，大模型最便宜。

| 项目 | 封顶（护栏全打满，30 天） | 典型（每天 10 通 3 分钟语音 + 300 条文字回复） |
|---|---|---|
| 服务器 2C2G 香港轻量 | 56 元 | 56 元 |
| 语音 DashScope | ≤ 5 × 30 = **150 元** | ≈ 10 × 0.11 × 30 ≈ 33 元（ASR 前 10 小时免费，实际约 25 元） |
| 文字 DashScope | ≤ 2 × 30 = **60 元** | ≈ 300 × 0.0008 × 30 ≈ 7 元 |
| **合计** | **≤ 266 元/月** | **≈ 90–100 元/月** |

想更省：`VOICE_DAILY_BUDGET_CNY=2`（封顶 60 元/月）、`VOICE_ENGINE=rule`（不调大模型）、`VOICE_MAX_MINUTES=3`。
只上文字代理不上语音：`docker compose up -d proxy caddy`（同时把 `deploy/caddy/Caddyfile` 的默认路由去掉），1C1G 就够。

## 6. 本地验证记录（2026-10-18，未购买任何云资源）

在开发机上用 Docker 26 + compose 2.26 跑完整栈（`LIVE_DOMAIN=localhost`，Caddy 内部 CA 签发证书）：

- `https://localhost/api/health`（通过）；带 `Origin: https://deepsuck.si` 的 `/api/chat` 返回 qwen-plus 回复（通过）；预检 204 + `Access-Control-Allow-Origin`（通过）；
  恶意 Origin / 无 Origin → 403（通过）；100 KB 请求体 → 413（通过）。
- 静态站本地起在 8080、`DEEPSUCK_LIVE.api` 指向 `https://localhost`：沙盒调用 `https://localhost/api/health` 与 `/api/chat`，回复标注“大模型”，导航栏出现语音入口（通过）。
- 语音：`voice.probe` 经 Caddy → 容器真实通话，Paraformer 把“户名写张三”转成“张3”，现已正确抽取为收款户名 `张*`（通过）；
  服务端 UDP 端口落在 40000–40199（通过）；2 路并发通话 + 第 3 路 503（通过）。
- 预算护栏：`CHAT_DAILY_BUDGET_CNY=0.0012` → 第 4 次起 429 `budget` 且不再打上游（通过）；
  `VOICE_DAILY_BUDGET_CNY=0.15` + `VOICE_MAX_MINUTES=0.4` → 第 2 路因预占不足 429、第 1 路 24 秒时“锅里还炖着汤呢，我先挂了啊”并断开（通过）。
- TURN 走 443：本地 caddy-l4 + coturn，aiortc 只收集中继候选（relay-only），`turn:…:443?transport=tcp` 与 `turns:…:443?transport=tcp` 都能连通；同时 h2 / http1.1 / 不带 ALPN 的 HTTPS 请求照常（通过）。

**尚未在真实云服务器上验证**：公网 IP 候选在阿里云 1:1 NAT 下的连通性、证书签发、国内各运营商 UDP 到香港的质量。上线后先跑第 3 节的 `voice.probe`。

## 7. 故障排查

| 现象 | 排查 |
|---|---|
| 语音页一直“连接中”，30 秒后断开 | UDP 40000–40199 没放行；或 `VOICE_PUBLIC_IP` 为空/错误（`grep VOICE_PUBLIC_IP deploy/.env`）。拿不到公网 IP 时可设 `VOICE_SERVER_STUN=stun:stun.l.google.com:19302` |
| 每次接通都慢 ~5 秒 | 设置了 `VOICE_SERVER_STUN` 但 STUN 不通；有公网 IP 时留空 |
| 证书申请失败 | DNS 未生效或 80 端口没放行；`docker compose logs caddy` |
| 主站沙盒没切到大模型 | `live-config.js` 没改 / 浏览器缓存；`ALLOWED_ORIGINS` 要包含页面的 Origin；`/api/health` 里 `budget.exhausted` |
| 503 当前同时通话已满 | 正常护栏（`VOICE_MAX_SESSIONS`） |
| 改了 Caddyfile 不生效 | 确认改的是 `deploy/caddy/Caddyfile`；`docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`。若 `docker inspect` 里 caddy 仍挂载 `/etc/caddy/Caddyfile` 单文件，执行一次 `docker compose up -d --force-recreate caddy` |
| `WITH_SIP=1` 重跑 bootstrap 在第 6 步后无输出退出 | 旧版 bootstrap 在 `.env` 缺少 `SIP_LOG_DIR` 等变量时会被 `set -e` 打断，更新到最新代码后重跑即可 |
| 容器被 OOM 杀 | 1 GB 机器：确认 swap 已开（`swapon --show`），或把 `VOICE_MAX_SESSIONS=1` |
