#!/usr/bin/env bash
# 每日重跑 trace 与文字记录（#125）脱敏兜底（GitHub #107，#92 后续）：由 deepsuck-redact.timer 每天 20:30（+08:00）调度，
# 在 20:40 成本汇总之前。在运行中的 voice 容器里执行 python -m voice.redact_backfill（只改已同意通话，
# 只把新规则命中的数字换成 *，保留修改时间；规则随镜像更新）。
#
#   deploy/redact-backfill.sh [--dry-run] [--no-backup]
#
# #254：正式改写默认带 --backup，备份写到 trace 卷里的 REDACT_BACKUP_DIR（默认容器内 /traces/backups，0700，
# 文件 backup-<时间>.tar，0600），只保留 REDACT_BACKUP_KEEP_HOURS（默认 24）小时：每次运行先删 mtime 超过的 backup-*.tar。
# 备份同样是敏感数据，所以只留一天。--no-backup 或 REDACT_BACKUP=0 关掉；--dry-run 不备份。
# 备份文件已存在（同一秒跑了两次）：voice.redact_backfill 退出码 3、不改文件，这里记 ERROR（#216，不再是 traceback）。
# 计数只读输出的 JSON；容器 stderr 只认 event=redact_backfill.change 的结构化改动日志（#254），按白名单字段
# （通话编号、trace / transcript、字段路径、规则类别、处数）重新拼一行记 INFO，其余 stderr 一律丢弃，从不记原文。
# 日志：journalctl -t deepsuck-redact。rows_changed=0 记 INFO，>0 记 WARN（说明实时脱敏漏过、已事后补打码），
# 失败（容器不在、脚本报错、输出不是 JSON、trace 目录不存在）记 ERROR 并以非 0 退出（单元失败）。
set -euo pipefail
# shellcheck source=deploy/maint-lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/maint-lib.sh"
TAG="${REDACT_TAG:-deepsuck-redact}"
CONTAINER="${REDACT_CONTAINER:-${COMPOSE_PROJECT}-voice-1}"
PY="${PYTHON:-python3}"
BACKUP="${REDACT_BACKUP:-1}"
BACKUP_DIR="${REDACT_BACKUP_DIR:-/traces/backups}"
KEEP_HOURS="${REDACT_BACKUP_KEEP_HOURS:-24}"
case "$KEEP_HOURS" in ''|*[!0-9]*) echo "REDACT_BACKUP_KEEP_HOURS must be an integer" >&2; exit 2 ;; esac
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY_RUN=1 ;;
    --no-backup) BACKUP=0 ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done

# 先清理过期备份（不管这次是否 dry-run / 是否备份：过期的都该删）。find 只在备份目录这一层、只认 backup-*.tar
if [ "$DRY_RUN" != 1 ]; then
  pruned=$(docker exec "$CONTAINER" find "$BACKUP_DIR" -maxdepth 1 -type f -name 'backup-*.tar' \
             -mmin +$((KEEP_HOURS * 60)) -print -delete 2>/dev/null) || pruned=""
  n=$(printf '%s\n' "$pruned" | grep -c "^$BACKUP_DIR/backup-.*\.tar$" || true)
  [ "${n:-0}" -gt 0 ] && log info "$TAG" "pruned $n backup(s) older than ${KEEP_HOURS}h in $BACKUP_DIR"
fi

args=(python -m voice.redact_backfill)
[ "$DRY_RUN" = 1 ] && args+=(--dry-run)
if [ "$DRY_RUN" != 1 ] && [ "$BACKUP" = 1 ]; then
  args+=(--backup "$BACKUP_DIR/backup-$(date +%Y%m%d-%H%M%S).tar")
fi
errf=$(mktemp); chmod 600 "$errf"; trap 'rm -f "$errf"' EXIT
rc=0
out=$(docker exec "$CONTAINER" "${args[@]}" 2>"$errf") || rc=$?
# #254：结构化改动日志，只按白名单字段重拼（编号只认字母数字，路径 / 规则只认 [A-Za-z0-9_.:\[\]-]）
"$PY" - "$errf" <<'PYEOF' | while IFS= read -r ln; do log info "$TAG" "$ln"; done || true
import json, re, sys
ok = re.compile(r"^[A-Za-z0-9_.:\[\]-]{1,64}$")
for raw in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try:
        d = json.loads(raw)
    except ValueError:
        continue
    if not isinstance(d, dict) or d.get("event") != "redact_backfill.change":
        continue
    cid, kind = str(d.get("call_id", "")), d.get("kind")
    if not re.fullmatch(r"[A-Za-z0-9]{1,40}", cid) or kind not in ("trace", "transcript"):
        continue
    fs = []
    for f in d.get("fields") or []:
        p, rules, n = str(f.get("path", "")), [str(r) for r in f.get("rules") or []], f.get("n")
        if ok.match(p) and rules and all(ok.match(r) for r in rules) and isinstance(n, int):
            fs.append("%s:%s:%d" % (p, "+".join(rules), n))
    print("change call=%s kind=%s changes=%d fields=%s" % (cid, kind, int(d.get("changes") or 0), ",".join(fs)))
PYEOF
if [ "$rc" = 3 ]; then
  log err "$TAG" "backup file already exists in $BACKUP_DIR; nothing rewritten"
  exit 1
fi
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
s = " ".join("%s=%d" % (k, int(d.get(k) or 0)) for k in keys)
t = d.get("transcripts")
if isinstance(t, dict):  # #125：文字记录（DATA_DIR/voice/transcripts）
    s += " " + " ".join("transcripts_%s=%d" % (k, int(t.get(k) or 0))
                        for k in ("files_scanned", "files_changed", "fields_changed", "skipped_recent", "skipped_bad"))
print(s)') || line=BAD
case "$line" in
  BAD) log err "$TAG" "voice.redact_backfill output is not the expected JSON"; exit 1 ;;
  NODIR) log err "$TAG" "trace dir missing in $CONTAINER"; exit 1 ;;
esac
rows=$(printf '%s\n' "$line" | sed -n 's/.* rows_changed=\([0-9]*\).*/\1/p')
tfields=$(printf '%s\n' "$line" | sed -n 's/.*transcripts_fields_changed=\([0-9]*\).*/\1/p')
if [ "${rows:-0}" -gt 0 ] || [ "${tfields:-0}" -gt 0 ]; then
  if [ "$DRY_RUN" = 1 ]; then verb="would re-redact"; else verb="re-redacted"; fi
  log warning "$TAG" "$verb stored traces/transcripts: $line"
else
  log info "$TAG" "no changes: $line"
fi
