#!/usr/bin/env bash
# bootstrap.sh 回归测试：不需要 root、Docker、网络。外部命令（docker、systemctl、apt-get、git、curl……）全部用桩替换。
#   bash deploy/tests/test_bootstrap.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

setup() {
  T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
  mkdir -p "$T/bin" "$T/opt/.git" "$T/etc/fail2ban/jail.d" "$T/etc/logrotate.d"
  cp -r "$ROOT/deploy" "$T/opt/deploy"; rm -f "$T/opt/deploy/.env"
  # 桩：记录调用，什么也不做
  for c in apt-get systemctl git fallocate mkswap swapon sysctl; do
    printf '#!/bin/sh\necho "%s $*" >> "%s/calls"\n' "$c" "$T" > "$T/bin/$c"
  done
  printf '#!/bin/sh\necho "swapon $*" >> "%s/calls"; echo /swapfile\n' "$T" > "$T/bin/swapon"  # 假装已有 swap
  printf '#!/bin/sh\necho 0\n' > "$T/bin/id"
  printf '#!/bin/sh\necho 10.0.0.2\n' > "$T/bin/hostname"
  printf '#!/bin/sh\ncase "$*" in *meta-data*) exit 22;; *ipify*) echo 203.0.113.7;; esac\nexit 0\n' > "$T/bin/curl"
  printf '#!/bin/sh\necho "ufw $*" >> "%s/calls"; [ "$1" = status ] && echo "Status: active"; exit 0\n' "$T" > "$T/bin/ufw"
  printf '#!/bin/sh\necho "docker $*" >> "%s/calls"\ncase "$*" in *" ps sip"*) echo "sip Up";; esac\nexit 0\n' "$T" > "$T/bin/docker"
  printf '#!/bin/sh\nexit 0\n' > "$T/bin/sleep"
  # 宿主机日志目录不可写：只记录，不真的动 /var/log
  for c in mkdir touch chown chmod; do
    real="$(command -v "$c")"
    printf '#!/bin/sh\nfor a; do case "$a" in /var/log/*) echo "%s $*" >> "%s/calls"; exit 0;; esac; done\nexec %s "$@"\n' "$c" "$T" "$real" > "$T/bin/$c"
  done
  chmod +x "$T/bin/"*
}

run_bootstrap() {
  env -i PATH="$T/bin:/usr/bin:/bin" HOME="$T" DIR="$T/opt" DEEPSUCK_ETC="$T/etc" SKIP_FAIL2BAN=1 "$@" \
    bash "$ROOT/deploy/bootstrap.sh" > "$T/out" 2>&1
}

getenv() { grep -E "^$1=" "$T/opt/deploy/.env" | tail -1 | cut -d= -f2-; }

# 1) 已有 .env、里面没有任何 SIP_* 变量，再用 WITH_SIP=1 运行：不能被 set -e 静默打断
setup
grep -vE '^(SIP_|VOICE_TELEPHONY|VOICE_UDP_PORTS)' "$T/opt/deploy/.env.example" > "$T/opt/deploy/.env"
sed -i 's/^LIVE_DOMAIN=.*/LIVE_DOMAIN=live.example.com/; s/^ACME_EMAIL=.*/ACME_EMAIL=ops@example.com/' "$T/opt/deploy/.env"
grep -q '^LIVE_DOMAIN=live.example.com' "$T/opt/deploy/.env" || echo 'LIVE_DOMAIN=live.example.com' >> "$T/opt/deploy/.env"
if ! run_bootstrap WITH_SIP=1; then cat "$T/out"; fail "existing .env + WITH_SIP=1 exited non-zero"; fi
grep -q "7/7" "$T/out" || { cat "$T/out"; fail "did not reach step 7"; }
[ "$(getenv SIP_PORT)" = 25060 ] || fail "SIP_PORT not written"
[ "$(getenv SIP_RTP_PORTS)" = 40100-40199 ] || fail "SIP_RTP_PORTS not written"
[ "$(getenv SIP_AI_EXTEN)" = 9000 ] || fail "SIP_AI_EXTEN not written"
[ "$(getenv VOICE_UDP_PORTS)" = 40000-40099 ] || fail "VOICE_UDP_PORTS not split"
[ "$(getenv VOICE_TELEPHONY)" = 1 ] || fail "VOICE_TELEPHONY not enabled"
[ -n "$(getenv SIP_USER)" ] && [ "$(getenv SIP_PASSWORD | wc -c)" -ge 17 ] || fail "SIP credentials not generated"
[ "$(stat -c %a "$T/opt/deploy/.env")" = 600 ] || fail ".env not 600"
grep -q "mkdir -p /var/log/deepsuck-sip" "$T/calls" || fail "SIP_LOG_DIR default not used"
grep -q "/var/log/deepsuck-sip" "$T/etc/logrotate.d/deepsuck-sip" || fail "logrotate not written"
grep -q "ufw allow 25060/udp" "$T/calls" || fail "SIP_PORT default not opened in ufw"
grep -q "ufw allow 40100:40199/udp" "$T/calls" || fail "SIP RTP not opened in ufw"
grep -q -- "--profile sip up -d --build" "$T/calls" || fail "sip profile not started"
if grep -q "SIP_PASSWORD=" "$T/out"; then fail "password leaked to output"; fi
echo "ok - existing .env without SIP vars + WITH_SIP=1"

# 2) 再跑一次：账号密码不变（只补空值）；SIP_LOG_DIR 显式设置时使用该值
pw="$(getenv SIP_PASSWORD)"
echo "SIP_LOG_DIR=/var/log/custom-sip" >> "$T/opt/deploy/.env"
: > "$T/calls"
run_bootstrap WITH_SIP=1 || { cat "$T/out"; fail "second run exited non-zero"; }
[ "$(getenv SIP_PASSWORD)" = "$pw" ] || fail "SIP_PASSWORD overwritten"
grep -q "mkdir -p /var/log/custom-sip" "$T/calls" || fail "SIP_LOG_DIR from .env not used"
echo "ok - rerun keeps credentials, honours SIP_LOG_DIR"

# 3) 不带 WITH_SIP 运行已有 .env：不写入 SIP 变量
setup
grep -vE '^(SIP_|VOICE_TELEPHONY)' "$T/opt/deploy/.env.example" | sed 's/^LIVE_DOMAIN=.*/LIVE_DOMAIN=live.example.com/' > "$T/opt/deploy/.env"
run_bootstrap || { cat "$T/out"; fail "plain rerun exited non-zero"; }
if grep -qE '^SIP_' "$T/opt/deploy/.env"; then fail "SIP vars written without WITH_SIP"; fi
echo "ok - existing .env without WITH_SIP"

# 4) 旧服务器迁移：caddy 容器仍是单文件挂载时，bootstrap 自动 force-recreate caddy 一次
printf '#!/bin/sh\necho "docker $*" >> "%s/calls"\ncase "$*" in *"ps -q caddy"*) echo abc123;; inspect*) echo /data; echo /etc/caddy/Caddyfile;; esac\nexit 0\n' "$T" > "$T/bin/docker"
: > "$T/calls"
run_bootstrap || { cat "$T/out"; fail "migration run exited non-zero"; }
grep -q "compose up -d --force-recreate caddy" "$T/calls" || fail "old single-file caddy mount not recreated"
printf '#!/bin/sh\necho "docker $*" >> "%s/calls"\ncase "$*" in *"ps -q caddy"*) echo abc123;; inspect*) echo /data; echo /etc/caddy;; esac\nexit 0\n' "$T" > "$T/bin/docker"
: > "$T/calls"
run_bootstrap || fail "post-migration run exited non-zero"
if grep -q "force-recreate" "$T/calls"; then fail "recreated caddy although already migrated"; fi
echo "ok - caddy mount migration is automatic and one-off"

# 5) compose 挂载整个 caddy 目录，不再单文件挂载
grep -q -- "- ./caddy:/etc/caddy:ro" "$ROOT/deploy/docker-compose.yml" || fail "caddy dir mount missing"
if grep -q "/etc/caddy/Caddyfile" "$ROOT/deploy/docker-compose.yml"; then fail "single-file Caddyfile mount still present"; fi
[ -f "$ROOT/deploy/caddy/Caddyfile" ] || fail "deploy/caddy/Caddyfile missing"
echo "ok - caddy directory mount"
echo "all bootstrap tests passed"
