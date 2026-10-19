#!/usr/bin/env bash
# 每日重跑 trace 脱敏兜底（GitHub #107，#92 后续）：由 deepsuck-redact.timer 每天 20:30（+08:00）调度，
# 在 20:40 成本汇总之前。在运行中的 voice 容器里执行 python -m voice.redact_backfill（只改已同意通话，
# 只把新规则命中的数字换成 *，保留修改时间；规则随镜像更新）。
#
#   deploy/redact-backfill.sh [--dry-run]
#
# 不带 --backup：不在卷里或宿主机留改写前的备份（备份同样是敏感数据）。
# 只读脚本输出的计数 JSON，不打印任何文字内容或通话编号；容器的 stderr 丢弃。
# 日志：journalctl -t deepsuck-redact。rows_changed=0 记 INFO，>0 记 WARN（说明实时脱敏漏过、已事后补打码），
# 失败（容器不在、脚本报错、输出不是 JSON、trace 目录不存在）记 ERROR 并以非 0 退出（单元失败）。
set -euo pipefail
# shellcheck source=deploy/maint-lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/maint-lib.sh"
TAG="${REDACT_TAG:-deepsuck-redact}"
CONTAINER="${REDACT_CONTAINER:-${COMPOSE_PROJECT}-voice-1}"
PY="${PYTHON:-python3}"
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY_RUN=1 ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done

args=(python -m voice.redact_backfill)
[ "$DRY_RUN" = 1 ] && args+=(--dry-run)
rc=0
out=$(docker exec "$CONTAINER" "${args[@]}" 2>/dev/null) || rc=$?
if [ "$rc" != 0 ]; then
  log err "$TAG" "voice.redact_backfill failed in $CONTAINER (exit $rc)"
  exit 1
fi
# 只取最后一行 JSON 的计数字段
line=$(printf '%s\n' "$out" | tail -n 1 | "$PY" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except ValueError:
    print("BAD"); sys.exit(0)
if not isinstance(d, dict) or not d.get("dir_exists"):
    print("NODIR"); sys.exit(0)
keys = ("files_scanned", "consented", "files_changed", "rows_changed", "fields_changed", "skipped_not_consented",
        "skipped_unknown_consent", "skipped_recent", "skipped_changed")
print(" ".join("%s=%d" % (k, int(d.get(k) or 0)) for k in keys))') || line=BAD
case "$line" in
  BAD) log err "$TAG" "voice.redact_backfill output is not the expected JSON"; exit 1 ;;
  NODIR) log err "$TAG" "trace dir missing in $CONTAINER"; exit 1 ;;
esac
rows=$(printf '%s\n' "$line" | sed -n 's/.*rows_changed=\([0-9]*\).*/\1/p')
if [ "${rows:-0}" -gt 0 ]; then
  if [ "$DRY_RUN" = 1 ]; then verb="would re-redact"; else verb="re-redacted"; fi
  log warning "$TAG" "$verb stored traces: $line"
else
  log info "$TAG" "no changes: $line"
fi
