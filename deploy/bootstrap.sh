#!/usr/bin/env bash
# DeepSuck 实时服务一键部署（全新 Ubuntu 22.04+/Debian 12+，root 运行）。
#
#   curl -fsSL https://raw.githubusercontent.com/deepsucksi/deepsuck/main/deploy/bootstrap.sh -o bootstrap.sh
#   sudo LIVE_DOMAIN=live.example.com ACME_EMAIL=you@example.com DASHSCOPE_API_KEY=sk-xxx bash bootstrap.sh
#
# 首次运行必填：LIVE_DOMAIN、ACME_EMAIL（没有默认值）、DASHSCOPE_API_KEY。
# Key 不想出现在命令行/历史里：先写进一个 600 权限的文件，再 set -a; . 该文件; set +a 后运行。
# 可选环境变量：REPO、BRANCH、DIR（默认 /opt/deepsuck）、
#   WITH_TURN=1（同时启动 coturn）、WITH_SIP=1（自建 SIP 软电话：Asterisk + fail2ban，docs/PHONE.md 第 10 节；
#   自动生成分机账号/密码并打开电话入口，已有 .env 只补空值）、SKIP_FAIL2BAN=1、SWAP_MB（内存 < 2G 时自动建 swap，默认 1024）、SKIP_DOCKER_INSTALL=1。
# 重复运行是安全的：已有 deploy/.env 不会被覆盖（Key 不会丢），只会更新代码并重建容器。
set -euo pipefail

LIVE_DOMAIN="${LIVE_DOMAIN:-}"
ACME_EMAIL="${ACME_EMAIL:-}"
REPO="${REPO:-https://github.com/deepsucksi/deepsuck.git}"
BRANCH="${BRANCH:-main}"
DIR="${DIR:-/opt/deepsuck}"
SWAP_MB="${SWAP_MB:-1024}"
ETC="${DEEPSUCK_ETC:-/etc}"  # 仅供测试把 fail2ban/logrotate 配置写到临时目录
log() { printf '\033[1;33m[deepsuck]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[deepsuck] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "请用 root 运行（sudo bash bootstrap.sh）"
. /etc/os-release 2>/dev/null || true
case "${ID:-}" in ubuntu|debian) ;; *) log "未测试的发行版 ${ID:-?}，继续尝试……" ;; esac

log "1/7 基础软件包"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git openssl >/dev/null

log "2/7 swap（小内存机器防 OOM）"
mem_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 2600 ] && ! swapon --show | grep -q .; then
  fallocate -l "${SWAP_MB}M" /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count="$SWAP_MB" status=none
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -q vm.swappiness=10; echo 'vm.swappiness=10' > /etc/sysctl.d/99-deepsuck.conf
  log "  已创建 ${SWAP_MB}MB swap（内存 ${mem_mb}MB）"
fi

log "3/7 Docker"
if [ "${SKIP_DOCKER_INSTALL:-0}" != 1 ] && ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || die "缺少 docker compose 插件"

log "4/7 拉取代码 → $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q "$BRANCH" && git -C "$DIR" reset -q --hard "origin/$BRANCH"
else
  git clone -q --depth 1 -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR/deploy"

log "5/7 探测 IP"
meta() { curl -fsS --max-time 2 "http://100.100.100.200/latest/meta-data/$1" 2>/dev/null || true; }  # 阿里云元数据
PUBLIC_IP="${VOICE_PUBLIC_IP:-$(meta eipv4)}"
[ -n "$PUBLIC_IP" ] || PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || curl -fsS --max-time 5 https://ifconfig.me || true)"
PRIVATE_IP="${PRIVATE_IP:-$(meta private-ipv4)}"
[ -n "$PRIVATE_IP" ] || PRIVATE_IP="$(hostname -I | awk '{print $1}')"
log "  公网 $PUBLIC_IP / 内网 $PRIVATE_IP"

log "6/7 写入 deploy/.env"
# getv KEY [默认值]：取 .env 里最后一个 KEY= 的值；缺失或为空时返回默认值。
# grep 没匹配会返回 1，在 set -euo pipefail 下 v=$(getv ...) 会让脚本静默退出，所以这里吞掉非零。
getv() {
  local v=""
  v="$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-)" || true
  printf '%s' "${v:-${2:-}}"
}
setv() { # 安全替换 KEY=VALUE（通过 ENVIRON 传值，值里有特殊字符也安全）；旧 .env 里没有这一行就追加
  if grep -qE "^$1=" .env; then
    K="$1" V="$2" awk '{ if (index($0, ENVIRON["K"] "=") == 1) print ENVIRON["K"] "=" ENVIRON["V"]; else print }' .env > .env.tmp
    cat .env.tmp > .env && rm -f .env.tmp
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
sip_env() { # WITH_SIP=1：只补空值，不覆盖已有账号密码；密码不打印
  [ "$(getv VOICE_TELEPHONY)" = 1 ] || setv VOICE_TELEPHONY 1
  [ -n "$(getv VOICE_TELEPHONY_TOKEN)" ] || setv VOICE_TELEPHONY_TOKEN "$(openssl rand -hex 24)"
  case ",$(getv VOICE_TELEPHONY_ADAPTERS)," in
    *,asterisk-ws,*) ;;
    ,,) setv VOICE_TELEPHONY_ADAPTERS asterisk-ws ;;
    *) setv VOICE_TELEPHONY_ADAPTERS "$(getv VOICE_TELEPHONY_ADAPTERS),asterisk-ws" ;;
  esac
  # 网页语音（aioice）用前半段，Asterisk RTP 用后半段，互不抢端口
  case "$(getv VOICE_UDP_PORTS)" in ""|40000-40199) setv VOICE_UDP_PORTS 40000-40099 ;; esac
  [ -n "$(getv SIP_RTP_PORTS)" ] || setv SIP_RTP_PORTS 40100-40199
  [ -n "$(getv SIP_USER)" ] || setv SIP_USER "ds$(openssl rand -hex 4)"
  [ -n "$(getv SIP_PASSWORD)" ] || setv SIP_PASSWORD "$(openssl rand -hex 16)"
  [ -n "$(getv SIP_PORT)" ] || setv SIP_PORT 25060
  [ -n "$(getv SIP_AI_EXTEN)" ] || setv SIP_AI_EXTEN 9000
  log "  自建 SIP 已开启：账号密码在 deploy/.env（grep -E '^SIP_(USER|PASSWORD|PORT|AI_EXTEN)=' $DIR/deploy/.env）"
}
FIRST_RUN=0  # 本次运行新建了 .env 才算首次部署；重跑只打印简短摘要
SIP_NEW=0    # 本次运行才生成 SIP 账号（运行前 .env 里没有 SIP_USER）：重跑也打印完整 SIP 说明
if [ ! -f .env ]; then
  FIRST_RUN=1
  [ -n "$LIVE_DOMAIN" ] || die "请设置 LIVE_DOMAIN（你自己的域名，例如 live.example.com）"
  [ -n "$ACME_EMAIL" ] || die "请设置 ACME_EMAIL（证书邮箱）"
  if [ -z "${DASHSCOPE_API_KEY:-}" ]; then
    if [ -t 0 ]; then read -rsp "DashScope API Key（输入不回显）: " DASHSCOPE_API_KEY; echo; else die "请通过环境变量 DASHSCOPE_API_KEY 提供 Key"; fi
  fi
  [ -n "$DASHSCOPE_API_KEY" ] || die "DASHSCOPE_API_KEY 为空"
  umask 077
  cp .env.example .env
  setv DASHSCOPE_API_KEY "$DASHSCOPE_API_KEY"
  setv LIVE_DOMAIN "$LIVE_DOMAIN"
  setv ACME_EMAIL "$ACME_EMAIL"
  setv VOICE_ALLOWED_ORIGINS "https://$LIVE_DOMAIN,https://deepsuck.si"
  setv VOICE_PUBLIC_IP "$PUBLIC_IP"
  setv PRIVATE_IP "$PRIVATE_IP"
  if [ "${WITH_TURN:-0}" = 1 ]; then
    setv TURN_SECRET "$(openssl rand -hex 24)"
    setv TURN_URLS "turn:$LIVE_DOMAIN:443?transport=tcp,turns:$LIVE_DOMAIN:443?transport=tcp"
  fi
  if [ "${WITH_SIP:-0}" = 1 ]; then SIP_NEW=1; sip_env; fi
  chmod 600 .env
  unset DASHSCOPE_API_KEY
else
  LIVE_DOMAIN="$(getv LIVE_DOMAIN)"
  [ -n "$LIVE_DOMAIN" ] || die "deploy/.env 里 LIVE_DOMAIN 为空"
  log "  已存在 .env，保留（如需修改：nano $DIR/deploy/.env 后 docker compose up -d）"
  if [ "${WITH_SIP:-0}" = 1 ]; then
    [ -n "$(getv SIP_USER)" ] || SIP_NEW=1
    (umask 077; sip_env); chmod 600 .env
  fi
fi

# 自建 SIP：security 日志目录 + fail2ban 防暴力注册 + 日志轮转
if [ "${WITH_SIP:-0}" = 1 ]; then
  sip_log="$(getv SIP_LOG_DIR /var/log/deepsuck-sip)"
  mkdir -p "$sip_log" && touch "$sip_log/security" && chown -R 1000:1000 "$sip_log" && chmod 750 "$sip_log"
  if [ "${SKIP_FAIL2BAN:-0}" != 1 ]; then
    apt-get install -y -qq fail2ban >/dev/null
    sed "s#/var/log/deepsuck-sip#$sip_log#" sip/fail2ban/deepsuck-sip.conf > "$ETC"/fail2ban/jail.d/deepsuck-sip.conf
    systemctl enable fail2ban >/dev/null 2>&1 || true
    systemctl restart fail2ban >/dev/null 2>&1 || log "  fail2ban 没能启动，请检查：fail2ban-client status deepsuck-sip"
  fi
  sed "s#/var/log/deepsuck-sip#$sip_log#" sip/logrotate.conf > "$ETC"/logrotate.d/deepsuck-sip
fi

# 主机防火墙（若启用了 ufw）；云厂商控制台的防火墙需另外放行，见 docs/DEPLOY.md
if command -v ufw >/dev/null && ufw status | grep -q active; then
  udp="$(getv VOICE_UDP_PORTS 40000-40199)"
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw allow "${udp/-/:}/udp" >/dev/null
  if [ "${WITH_SIP:-0}" = 1 ]; then
    rtp="$(getv SIP_RTP_PORTS 40100-40199)"; ufw allow "${rtp/-/:}/udp" >/dev/null
    ufw allow "$(getv SIP_PORT 25060)/udp" >/dev/null
    if [ "$(getv SIP_TCP 0)" = 1 ]; then ufw allow "$(getv SIP_PORT 25060)/tcp" >/dev/null; fi
  fi
fi

log "7/7 构建并启动容器（首次约 3–6 分钟）"
profiles=""; [ "${WITH_TURN:-0}" = 1 ] && profiles="--profile turn"
[ "${WITH_SIP:-0}" = 1 ] && profiles="$profiles --profile sip"
docker compose $profiles up -d --build
# 迁移：旧版把 deploy/Caddyfile 按单文件挂到 /etc/caddy/Caddyfile，git pull 换 inode 后容器读不到新内容。
# 现在挂载整个 deploy/caddy/ 目录；若 caddy 容器仍是旧的单文件挂载，强制重建一次（以后不再需要）。
caddy_id="$(docker compose ps -q caddy 2>/dev/null || true)"
if [ -n "$caddy_id" ] && docker inspect -f '{{range .Mounts}}{{println .Destination}}{{end}}' "$caddy_id" 2>/dev/null | grep -qx /etc/caddy/Caddyfile; then
  log "  Caddyfile 改为目录挂载，重建 caddy 容器（一次性）"
  docker compose up -d --force-recreate caddy
fi
for i in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:8787/api/health >/dev/null 2>&1 && curl -fsS --max-time 3 http://127.0.0.1:7860/api/voice/health >/dev/null 2>&1; then
    log "服务已就绪 ✓"; break
  fi
  sleep 3
  [ "$i" = 60 ] && { docker compose ps; die "服务没有在 3 分钟内就绪：docker compose logs --tail=100"; }
done
[ "${WITH_SIP:-0}" = 1 ] && { sleep 3; docker compose ps sip | grep -q Up || { docker compose logs --tail=30 sip; die "sip 容器没有启动（见上面的 [deepsuck-sip] 提示）"; }; }
docker compose ps
sip_msg=""
if [ "${WITH_SIP:-0}" = 1 ]; then  # 账号可以显示；密码一律不打印，只给出 .env 里的位置
  sip_port="$(getv SIP_PORT 25060)"; sip_exten="$(getv SIP_AI_EXTEN 9000)"
  sip_msg="
  自建 SIP 软电话（docs/PHONE.md 第 10 节）：
    云防火墙放行 UDP $sip_port（SIP 信令）$( [ "$(getv SIP_TCP 0)" = 1 ] && echo "、TCP $sip_port")和 UDP $(getv SIP_RTP_PORTS 40100-40199)（RTP 音频）
    接 AI 的分机：$sip_exten（拨其他号码一律 404）
    账号：$(getv SIP_USER)；密码不在这里显示，查看：grep -n ^SIP_PASSWORD $DIR/deploy/.env
    Linphone：选“使用 SIP 账号”，用户名填账号，密码填上面的密码，域名填 $PUBLIC_IP:$sip_port，传输 UDP，媒体加密选“无”，登录后拨 $sip_exten
    Zoiper：添加账号输入 账号@$PUBLIC_IP:$sip_port 和密码，自动探测卡住时手动选 SIP UDP，关闭 STUN，拨 $sip_exten
    更新时带上 profile：docker compose --profile sip up -d --build"
fi
if [ "$FIRST_RUN" = 1 ]; then
cat <<MSG

  下一步：
  1) DNS：添加 A 记录  ${LIVE_DOMAIN%%.*} → $PUBLIC_IP（Caddy 会在解析生效后自动申请证书）
  2) 云控制台防火墙放行：TCP 80、443；UDP 443；UDP $(getv VOICE_UDP_PORTS 40000-40199)
  3) 打开 https://$LIVE_DOMAIN/ 试语音；curl https://$LIVE_DOMAIN/api/health 看文字代理
  4) 在仓库 site/assets/js/live-config.js 里把 api 设为 'https://$LIVE_DOMAIN' 并推送，主站沙盒即切到大模型
  更新：cd $DIR && git pull && cd deploy && docker compose up -d --build${sip_msg}
MSG
else
  rev="$(git -C "$DIR" rev-parse --short HEAD 2>/dev/null || true)"
  log "已更新：$BRANCH${rev:+@$rev}，容器已重建，https://$LIVE_DOMAIN/ 沿用现有 .env${sip_msg:+（含自建 SIP）}"
  if [ "$SIP_NEW" = 1 ]; then printf '%s\n' "$sip_msg"; fi
fi
