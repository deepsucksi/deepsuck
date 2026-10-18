#!/usr/bin/env bash
# DeepSuck 实时服务一键部署（全新 Ubuntu 22.04+/Debian 12+，root 运行）。
#
#   curl -fsSL https://raw.githubusercontent.com/deepsucksi/deepsuck/main/deploy/bootstrap.sh -o bootstrap.sh
#   sudo DASHSCOPE_API_KEY=sk-xxx ACME_EMAIL=you@example.com bash bootstrap.sh
#
# 可选环境变量：LIVE_DOMAIN（默认 live.deepsuck.si）、REPO、BRANCH、DIR（默认 /opt/deepsuck）、
#   WITH_TURN=1（同时启动 coturn）、SWAP_MB（内存 < 2G 时自动建 swap，默认 1024）、SKIP_DOCKER_INSTALL=1。
# 重复运行是安全的：已有 deploy/.env 不会被覆盖（Key 不会丢），只会更新代码并重建容器。
set -euo pipefail

LIVE_DOMAIN="${LIVE_DOMAIN:-live.deepsuck.si}"
REPO="${REPO:-https://github.com/deepsucksi/deepsuck.git}"
BRANCH="${BRANCH:-main}"
DIR="${DIR:-/opt/deepsuck}"
SWAP_MB="${SWAP_MB:-1024}"
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
if [ ! -f .env ]; then
  if [ -z "${DASHSCOPE_API_KEY:-}" ]; then
    if [ -t 0 ]; then read -rsp "DashScope API Key（输入不回显）: " DASHSCOPE_API_KEY; echo; else die "请通过环境变量 DASHSCOPE_API_KEY 提供 Key"; fi
  fi
  [ -n "$DASHSCOPE_API_KEY" ] || die "DASHSCOPE_API_KEY 为空"
  umask 077
  cp .env.example .env
  setv() { # 安全替换 KEY=VALUE（通过 ENVIRON 传值，值里有特殊字符也安全）
    K="$1" V="$2" awk '{ if (index($0, ENVIRON["K"] "=") == 1) print ENVIRON["K"] "=" ENVIRON["V"]; else print }' .env > .env.tmp
    mv .env.tmp .env
  }
  setv DASHSCOPE_API_KEY "$DASHSCOPE_API_KEY"
  setv LIVE_DOMAIN "$LIVE_DOMAIN"
  setv ACME_EMAIL "${ACME_EMAIL:-admin@${LIVE_DOMAIN#*.}}"
  setv VOICE_ALLOWED_ORIGINS "https://$LIVE_DOMAIN,https://deepsuck.si"
  setv VOICE_PUBLIC_IP "$PUBLIC_IP"
  setv PRIVATE_IP "$PRIVATE_IP"
  if [ "${WITH_TURN:-0}" = 1 ]; then
    setv TURN_SECRET "$(openssl rand -hex 24)"
    setv TURN_URLS "turn:$LIVE_DOMAIN:3478?transport=udp,turn:$LIVE_DOMAIN:3478?transport=tcp"
  fi
  chmod 600 .env
  unset DASHSCOPE_API_KEY
else
  log "  已存在 .env，保留（如需修改：nano $DIR/deploy/.env 后 docker compose up -d）"
fi

# 主机防火墙（若启用了 ufw）；云厂商控制台的防火墙需另外放行，见 docs/DEPLOY.md
if command -v ufw >/dev/null && ufw status | grep -q active; then
  udp=$(grep -E '^VOICE_UDP_PORTS=' .env | cut -d= -f2); udp=${udp:-40000-40199}
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw allow "${udp/-/:}/udp" >/dev/null
  [ "${WITH_TURN:-0}" = 1 ] && { ufw allow 3478 >/dev/null; ufw allow 49160:49200/udp >/dev/null; }
fi

log "7/7 构建并启动容器（首次约 3–6 分钟）"
profiles=""; [ "${WITH_TURN:-0}" = 1 ] && profiles="--profile turn"
docker compose $profiles up -d --build
for i in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:8787/api/health >/dev/null 2>&1 && curl -fsS --max-time 3 http://127.0.0.1:7860/api/voice/health >/dev/null 2>&1; then
    log "服务已就绪 ✓"; break
  fi
  sleep 3
  [ "$i" = 60 ] && { docker compose ps; die "服务没有在 3 分钟内就绪：docker compose logs --tail=100"; }
done
docker compose ps
cat <<MSG

  下一步：
  1) DNS：添加 A 记录  ${LIVE_DOMAIN%%.*} → $PUBLIC_IP（Caddy 会在解析生效后自动申请证书）
  2) 云控制台防火墙放行：TCP 80、443；UDP 443；UDP $(grep -E '^VOICE_UDP_PORTS=' .env | cut -d= -f2)$( [ "${WITH_TURN:-0}" = 1 ] && echo '；TCP/UDP 3478、UDP 49160-49200' )
  3) 打开 https://$LIVE_DOMAIN/ 试语音；curl https://$LIVE_DOMAIN/api/health 看文字代理
  4) 在仓库 site/assets/js/live-config.js 里把 api 设为 'https://$LIVE_DOMAIN' 并推送，主站沙盒即切到大模型
  更新：cd $DIR && git pull && cd deploy && docker compose up -d --build
MSG
