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

grep -q "已更新" "$T/out" || fail "rerun summary missing"
if grep -qE "live-config|DNS" "$T/out"; then fail "first-deploy hints shown on rerun"; fi
grep -q "自建 SIP 软电话" "$T/out" || { cat "$T/out"; fail "SIP newly enabled but SIP guide missing"; }
grep -q "UDP 25060" "$T/out" && grep -q "UDP 40100-40199" "$T/out" || fail "SIP ports missing in guide"
grep -q "分机：9000" "$T/out" && grep -q "Linphone" "$T/out" && grep -q "Zoiper" "$T/out" || fail "SIP guide incomplete"
grep -q "账号：$(getenv SIP_USER)" "$T/out" || fail "SIP_USER not shown"
grep -q "grep -n ^SIP_PASSWORD" "$T/out" || fail "password location hint missing"
if grep -qF "$(getenv SIP_PASSWORD)" "$T/out"; then fail "SIP_PASSWORD printed"; fi
echo "ok - SIP newly enabled on rerun: SIP guide without DNS/live-config, no password"

# 1b) 紧接着再跑一次：只有摘要，没有 SIP 说明
run_bootstrap WITH_SIP=1 || { cat "$T/out"; fail "rerun after SIP enable exited non-zero"; }
grep -q "已更新" "$T/out" || fail "summary missing"
if grep -qE "自建 SIP 软电话|Linphone|live-config|DNS" "$T/out"; then cat "$T/out"; fail "guide shown on plain rerun"; fi
echo "ok - plain rerun with SIP already enabled prints summary only"

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

# 3b) 首次部署（没有 .env）：输出 DNS / live-config 提示，不输出「已更新」，Key 不出现在输出里
setup
run_bootstrap LIVE_DOMAIN=live.example.com ACME_EMAIL=ops@example.com DASHSCOPE_API_KEY=test-not-a-real-key \
  || { cat "$T/out"; fail "first run exited non-zero"; }
[ -f "$T/opt/deploy/.env" ] || fail ".env not created"
grep -q "DNS" "$T/out" && grep -q "live-config.js" "$T/out" || { cat "$T/out"; fail "first-deploy hints missing"; }
if grep -q "已更新" "$T/out"; then fail "rerun summary shown on first deploy"; fi
if grep -q "test-not-a-real-key" "$T/out"; then fail "key leaked to output"; fi
run_bootstrap || fail "rerun after first deploy exited non-zero"
if grep -qE "live-config|DNS" "$T/out"; then fail "hints shown on rerun after first deploy"; fi
echo "ok - first deploy shows hints, rerun does not"

# 3c) 首次部署就带 WITH_SIP=1：完整下一步提示，含 SIP 说明，不含密码
setup
run_bootstrap WITH_SIP=1 LIVE_DOMAIN=live.example.com ACME_EMAIL=ops@example.com DASHSCOPE_API_KEY=test-not-a-real-key \
  || { cat "$T/out"; fail "first run with SIP exited non-zero"; }
grep -q "DNS" "$T/out" && grep -q "live-config.js" "$T/out" || fail "first-deploy hints missing (SIP)"
grep -q "自建 SIP 软电话" "$T/out" && grep -q "分机：9000" "$T/out" && grep -q "账号：$(getenv SIP_USER)" "$T/out" || { cat "$T/out"; fail "SIP guide missing on first deploy"; }
if grep -qF "$(getenv SIP_PASSWORD)" "$T/out"; then fail "SIP_PASSWORD printed on first deploy"; fi
if grep -q "已更新" "$T/out"; then fail "summary shown on first deploy"; fi
echo "ok - first deploy with WITH_SIP=1 shows full hints including SIP guide"

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
