#!/usr/bin/env bash
# 安装 / 更新三个 systemd timer（GitHub #18、#20），幂等，可重复运行：
#   deepsuck-diskwatch.timer     每 15 分钟：磁盘使用率检查 + 录音/trace 按天数清理（deploy/diskwatch.sh run）
#   deepsuck-docker-prune.timer  每周日 04:30（+08:00）：docker builder/image prune（deploy/diskwatch.sh docker-prune）
#   deepsuck-cost.timer          每天 20:40（+08:00）：成本汇总 → /var/log/deepsuck/cost-latest.json（deploy/cost-report.sh）
#
#   cd /opt/deepsuck && git pull --ff-only && bash deploy/install-timers.sh [--dry-run]
#
# 做的事：建 /var/log/deepsuck；/etc/default/deepsuck-maint 不存在时从 deploy/maint.env.example 复制（已有不覆盖）；
# voice-data 卷里没有 cost-baseline.json 时从 deploy/cost-baseline.example.json 复制一份（已有不覆盖）；
# 把 deploy/systemd/* 里的 @DIR@ 换成仓库路径后装到 /etc/systemd/system（内容相同不动）；daemon-reload；enable --now 三个 timer。
# 不重启任何容器，不修改 crontab。卸载：systemctl disable --now deepsuck-{diskwatch,docker-prune,cost}.timer 后删 /etc/systemd/system/deepsuck-*。
set -euo pipefail
# shellcheck source=deploy/maint-lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/maint-lib.sh"
ETC="${DEEPSUCK_ETC:-/etc}"          # 测试时指向临时目录
LOG_DIR="${COST_OUT_DIR:-/var/log/deepsuck}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
TIMERS=(deepsuck-diskwatch.timer deepsuck-docker-prune.timer deepsuck-cost.timer)
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY_RUN=1 ;;
    -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done
say() { printf '[install-timers]%s %s\n' "$([ "$DRY_RUN" = 1 ] && echo ' [dry-run]')" "$*"; }
do_() { if [ "$DRY_RUN" = 1 ]; then say "would: $*"; else "$@"; fi; }

[ "$DRY_RUN" = 1 ] || [ -n "${DEEPSUCK_ETC:-}" ] || [ "$(id -u)" = 0 ] || { echo "请用 root 运行" >&2; exit 1; }
command -v python3 >/dev/null || { echo "缺少 python3（成本汇总要用）" >&2; exit 1; }

do_ mkdir -p "$LOG_DIR"
do_ chmod 750 "$LOG_DIR"

if [ ! -f "$ETC/default/deepsuck-maint" ]; then
  do_ mkdir -p "$ETC/default"
  do_ install -m 644 "$DIR/deploy/maint.env.example" "$ETC/default/deepsuck-maint"
  say "created $ETC/default/deepsuck-maint"
else
  say "keep existing $ETC/default/deepsuck-maint"
fi

data=$(vol_path voice-data VOICE_DATA_HOST_DIR)
baseline="${COST_BASELINE:-$data/cost-baseline.json}"
if [ -d "$(dirname "$baseline")" ] && [ ! -f "$baseline" ]; then
  do_ install -m 600 "$DIR/deploy/cost-baseline.example.json" "$baseline"
  say "seeded $baseline from deploy/cost-baseline.example.json (edit coupon_balance/as_of when you check the console)"
else
  say "baseline: $baseline $([ -f "$baseline" ] && echo exists || echo 'dir missing, skipped')"
fi

changed=0
[ "$DRY_RUN" = 1 ] || mkdir -p "$ETC/systemd/system"
for src in "$DIR"/deploy/systemd/*.service "$DIR"/deploy/systemd/*.timer; do
  name=$(basename "$src")
  dst="$ETC/systemd/system/$name"
  rendered=$(sed "s#@DIR@#$DIR#g" "$src")
  if [ -f "$dst" ] && [ "$(cat "$dst")" = "$rendered" ]; then
    say "unchanged $dst"
    continue
  fi
  changed=1
  if [ "$DRY_RUN" = 1 ]; then say "would install $dst"; else printf '%s\n' "$rendered" > "$dst.tmp" && chmod 644 "$dst.tmp" && mv -f "$dst.tmp" "$dst"; say "installed $dst"; fi
done

if [ "$changed" = 1 ]; then do_ "$SYSTEMCTL" daemon-reload; fi
do_ "$SYSTEMCTL" enable --now "${TIMERS[@]}"
if [ "$DRY_RUN" != 1 ]; then "$SYSTEMCTL" list-timers --all "${TIMERS[@]}" --no-pager || true; fi
say "done. 手动验证：$DIR/deploy/diskwatch.sh --dry-run run; $DIR/deploy/diskwatch.sh --dry-run docker-prune; systemctl start deepsuck-cost.service"
