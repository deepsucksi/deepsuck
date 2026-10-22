#!/usr/bin/env bash
# deploy/diskwatch.sh、cost-report.sh、redact-backfill.sh、install-timers.sh 的离线测试：docker/df/logger/systemctl 全部打桩，不碰真机器。
#   bash deploy/tests/test_maint.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
BIN="$T/bin"; mkdir -p "$BIN" "$T/traces" "$T/data/voice/transcripts" "$T/data/voice/audio" "$T/proxy" "$T/etc" "$T/log"
fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "ok - $*"; }

cat > "$BIN/logger" <<'S'
#!/usr/bin/env bash
tag=""; prio=""
while [ $# -gt 0 ]; do case "$1" in -t) tag="$2"; shift 2 ;; -p) prio="$2"; shift 2 ;; --) shift; break ;; *) break ;; esac; done
echo "$tag|$prio|$*" >> "$LOGFILE"
S
cat > "$BIN/df" <<'S'
#!/usr/bin/env bash
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/fake 40000000 ${FAKE_USED:-10000000} 30000000 ${FAKE_PCT:-36}% /"
S
cat > "$BIN/docker" <<'S'
#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
case "$1 ${2:-}" in
  "image inspect") for t in ${FAKE_TAGS:-}; do [ "$t" = "$3" ] && exit 0; done; exit 1 ;;
  "info -f"*|"info "*) echo /var/lib/docker ;;
  "volume inspect") exit 1 ;;
  "system df") echo "Images=1.2GB (40%)"; echo "Build Cache=300MB" ;;
  "builder prune") echo "Total:  300MB" ;;
  "exec "*) case "$*" in *" python "*) ;; *) exit "${FAKE_AUX_RC:-0}" ;; esac   # #254：find / mkdir 等辅助 exec 不吃 FAKE_EXEC_*
            [ -n "${FAKE_EXEC_ERR:-}" ] && echo "$FAKE_EXEC_ERR" >&2
            [ -n "${FAKE_EXEC_OUT:-}" ] && printf '%s\n' "$FAKE_EXEC_OUT"
            exit "${FAKE_EXEC_RC:-0}" ;;
  "image prune") echo "Total reclaimed space: 0B" ;;
esac
S
cat > "$BIN/systemctl" <<'S'
#!/usr/bin/env bash
echo "systemctl $*" >> "$CALLS"
S
chmod +x "$BIN"/*
export PATH="$BIN:$PATH" LOGFILE="$T/log.txt" CALLS="$T/calls.txt" MAINT_ECHO=0
export TRACE_HOST_DIR="$T/traces" VOICE_DATA_HOST_DIR="$T/data" PROXY_DATA_HOST_DIR="$T/proxy"
export DIR="$T/repo" DISKWATCH_PATHS="/"
# 仓库拷贝（不带 deploy/.env，避免读到开发机配置）
mkdir -p "$DIR" && cp -r "$ROOT/deploy" "$ROOT/voice" "$DIR/" && rm -f "$DIR/deploy/.env"
DW="$DIR/deploy/diskwatch.sh"
reset() { : > "$LOGFILE"; : > "$CALLS"; }

# --- check：阈值（严格大于）---
reset; FAKE_PCT=36 bash "$DW" check
grep -q '^deepsuck-diskwatch|user.info|INFO disk / 36% used' "$LOGFILE" || fail "36% should be INFO"; pass "check 36% -> INFO"
reset; FAKE_PCT=80 bash "$DW" check; grep -q 'user.info|INFO disk / 80%' "$LOGFILE" || fail "80% is not > 80"; pass "check 80% -> INFO (strict >)"
reset; FAKE_PCT=81 bash "$DW" check; grep -q 'user.warning|WARN disk / 81% .* > 80%' "$LOGFILE" || fail "81% should WARN"; pass "check 81% -> WARN"
reset; FAKE_PCT=91 bash "$DW" check; grep -q 'user.err|ERROR disk / 91% .* > 90%' "$LOGFILE" || fail "91% should ERROR"; pass "check 91% -> ERROR"
reset; FAKE_PCT=85 DISKWATCH_WARN_PCT=90 DISKWATCH_CRIT_PCT=95 bash "$DW" check; grep -q 'INFO disk / 85%' "$LOGFILE" || fail "custom thresholds"; pass "check thresholds configurable"
reset; DISKWATCH_PATHS="/ $T /nonexistent" bash "$DW" check; [ "$(grep -c 'disk /' "$LOGFILE")" = 1 ] || fail "same mount reported once"; pass "check dedupes mounts, skips missing paths"

# --- volumes：只统计不删 ---
old() { touch -d "@$(( $(date +%s) - $1 * 86400 - 3600 ))" "$2"; }
for f in AAAAAAAA.jsonl BBBBBBBB.jsonl stats.json; do : > "$T/traces/$f"; old 99 "$T/traces/$f"; done
head -c 200000 /dev/zero > "$T/traces/AAAAAAAA-scammer.ogg"; old 99 "$T/traces/AAAAAAAA-scammer.ogg"
: > "$T/data/voice/transcripts/x.json"; old 400 "$T/data/voice/transcripts/x.json"
before=$(find "$T/traces" "$T/data" -type f | sort)
reset; bash "$DW" volumes
grep -q '^deepsuck-diskwatch|user.info|INFO volumes voice-traces=[0-9]*KB (audio [0-9]*KB, 2 calls) voice-data=[0-9]*KB; traces 0% of TRACE_MAX_MB=1024' "$LOGFILE" || fail "volumes info line"
reset; bash "$DW" run
[ "$before" = "$(find "$T/traces" "$T/data" -type f | sort)" ] || fail "diskwatch must never delete call data"
grep -q 'INFO disk /' "$LOGFILE" && grep -q 'INFO volumes' "$LOGFILE" || fail "run = check + volumes"
pass "volumes logs sizes, run = check + volumes, deletes nothing (even 99-day-old traces)"
head -c 1000000 /dev/zero > "$T/traces/big.ogg"
reset; TRACE_MAX_MB=1 bash "$DW" volumes; grep -q 'user.err|ERROR volumes .*traces [0-9]*% of TRACE_MAX_MB=1 > 90% (recording stops at 100%)' "$LOGFILE" || fail "trace cap ERROR"
echo "TRACE_MAX_MB=2" > "$DIR/deploy/.env"; head -c 1550000 /dev/zero > "$T/traces/big.ogg"
reset; bash "$DW" volumes; grep -q 'WARN volumes .* of TRACE_MAX_MB=2 > 80%' "$LOGFILE" || fail "TRACE_MAX_MB from deploy/.env + WARN"
rm -f "$DIR/deploy/.env" "$T/traces/big.ogg"
pass "volumes warns/errors as trace volume approaches TRACE_MAX_MB (from env or deploy/.env)"

# --- docker-prune ---
reset; FAKE_TAGS="" bash "$DW" docker-prune && fail "missing rollback tag must fail" || true
grep -q 'user.err|ERROR docker-prune skipped: rollback image deepsuck-caddy:rollback-887ac0 not found' "$LOGFILE" || fail "missing tag log"
! grep -q 'prune' "$CALLS" || fail "pruned without rollback tag"; pass "docker-prune skips + ERROR when rollback tag missing"
reset; FAKE_TAGS="deepsuck-caddy:rollback-887ac0" bash "$DW" --dry-run docker-prune
! grep -q 'builder prune\|image prune' "$CALLS" || fail "dry-run pruned"; grep -q 'INFO \[dry-run\] docker-prune would run' "$LOGFILE" || fail "dry-run log"; pass "docker-prune --dry-run runs nothing"
reset; FAKE_TAGS="a:1 b:2" ROLLBACK_TAGS="a:1 b:2" bash "$DW" docker-prune
grep -q 'docker builder prune -f --filter until=168h' "$CALLS" && grep -q 'docker image prune -f' "$CALLS" || fail "prune commands"
grep -q 'docker-prune freed 0MB on /var/lib/docker' "$LOGFILE" || fail "freed log"; pass "docker-prune runs both prunes and logs freed space"

# --- cost-report ---
command -v python3 >/dev/null || fail "python3 needed"
cat > "$DIR/deploy/.env" <<'S'
DASHSCOPE_API_KEY=sk-should-never-be-exported
PRICE_ASR_PER_SEC=0.001
S
cp "$ROOT/deploy/cost-baseline.example.json" "$T/data/cost-baseline.json"
reset; COST_OUT_DIR="$T/log" bash "$DIR/deploy/cost-report.sh" --dry-run --day 2026-10-19 > "$T/dry.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["day"]=="2026-10-19"; assert d["prices"]["asr_per_sec"]==0.001, d["prices"]' "$T/dry.json" || fail "dry-run json / price from .env"
[ -z "$(ls -A "$T/log")" ] || fail "dry-run wrote files"; pass "cost-report --dry-run prints JSON, writes nothing, takes PRICE_* from deploy/.env"
reset; COST_OUT_DIR="$T/log" bash "$DIR/deploy/cost-report.sh" --day 2026-10-18
COST_OUT_DIR="$T/log" bash "$DIR/deploy/cost-report.sh" --day 2026-10-19
[ "$(readlink "$T/log/cost-latest.json")" = cost-2026-10-19.json ] || fail "latest symlink"
[ -f "$T/log/cost-2026-10-18.json" ] || fail "older file kept"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$T/log/cost-latest.json" || fail "latest json"
grep -q '^deepsuck-cost|user.info|INFO wrote .*cost-2026-10-19.json: day=2026-10-19 total_list=0.0000' "$LOGFILE" || fail "cost log"
grep -q 'balance_est=291.71' "$LOGFILE" || fail "baseline in summary"
! grep -rq 'sk-should-never' "$T/log" "$LOGFILE" || fail "key leaked"
[ -z "$(find "$T/log" -name '.cost*')" ] || fail "temp files left"
pass "cost-report writes cost-DAY.json + atomic cost-latest.json symlink"
rm "$DIR/deploy/.env"

# --- redact-backfill（#107）---
RB="$DIR/deploy/redact-backfill.sh"
J0='{"backup_files": 0, "consented": 7, "dir_exists": true, "dry_run": false, "fields_changed": 0, "files_changed": 0, "files_scanned": 7, "rows_changed": 0, "skipped_changed": 0, "skipped_not_consented": 2, "skipped_recent": 0, "skipped_unknown_consent": 0}'
J3='{"consented": 7, "dir_exists": true, "fields_changed": 4, "files_changed": 2, "files_scanned": 9, "rows_changed": 3}'
reset; FAKE_EXEC_OUT="$J0" FAKE_EXEC_ERR="pipecat banner 验证码是 3827" bash "$RB"
grep -q '^docker exec deepsuck-voice-1 python -m voice.redact_backfill --backup /traces/backups/backup-[0-9]\{8\}-[0-9]\{6\}\.tar$' "$CALLS" || fail "redact exec command (default --backup, #254)"
grep -q "^docker exec deepsuck-voice-1 find /traces/backups -maxdepth 1 -type f -name backup-\*.tar -mmin +1440 -print -delete$" "$CALLS" || fail "prune backups older than 24h (#254)"
grep -q '^deepsuck-redact|user.info|INFO no changes: files_scanned=7 consented=7 files_changed=0 rows_changed=0 ' "$LOGFILE" || fail "rows=0 -> INFO"
! grep -q '3827\|验证码\|banner' "$LOGFILE" || fail "container stderr leaked into log"
pass "redact-backfill rows_changed=0 -> INFO, container stderr not logged"
reset; FAKE_EXEC_OUT="$J3" bash "$RB"
grep -q '^deepsuck-redact|user.warning|WARN re-redacted stored traces/transcripts: files_scanned=9 consented=7 files_changed=2 rows_changed=3 fields_changed=4' "$LOGFILE" || fail "rows>0 -> WARN"
pass "redact-backfill rows_changed>0 -> WARN with counts"
JT='{"consented": 7, "dir_exists": true, "fields_changed": 0, "files_changed": 0, "files_scanned": 7, "rows_changed": 0, "transcripts": {"dir_exists": true, "files_scanned": 30, "files_changed": 5, "fields_changed": 8, "skipped_recent": 0, "skipped_bad": 0}}'
reset; FAKE_EXEC_OUT="$JT" bash "$RB"
grep -q 'user.warning|WARN re-redacted stored traces/transcripts: .* rows_changed=0 .*transcripts_files_scanned=30 transcripts_files_changed=5 transcripts_fields_changed=8' "$LOGFILE" || fail "transcripts changes -> WARN"
reset; FAKE_EXEC_OUT="${JT/\"fields_changed\": 8/\"fields_changed\": 0}" bash "$RB"
grep -q 'user.info|INFO no changes: .*transcripts_fields_changed=0' "$LOGFILE" || fail "transcripts 0 -> INFO"
pass "redact-backfill logs transcripts counts (#125)"
reset; FAKE_EXEC_OUT="$J3" bash "$RB" --dry-run
grep -q '^docker exec deepsuck-voice-1 python -m voice.redact_backfill --dry-run$' "$CALLS" || fail "dry-run passes --dry-run"
grep -q 'user.warning|WARN \[dry-run\] would re-redact' "$LOGFILE" || fail "dry-run log"
! grep -q 'find\|--backup' "$CALLS" || fail "dry-run must not back up or prune"
pass "redact-backfill --dry-run passes through"
reset; FAKE_EXEC_OUT="$J0" bash "$RB" --no-backup
grep -q '^docker exec deepsuck-voice-1 python -m voice.redact_backfill$' "$CALLS" || fail "--no-backup"
reset; FAKE_EXEC_OUT="$J0" REDACT_BACKUP_DIR=/traces/bk REDACT_BACKUP_KEEP_HOURS=2 bash "$RB"
grep -q -- '--backup /traces/bk/backup-' "$CALLS" && grep -q 'find /traces/bk .* -mmin +120 ' "$CALLS" || fail "backup dir / keep hours configurable"
pass "redact-backfill backups: default on, --no-backup, dir / retention configurable (#254)"
CH='{"call_id": "AAAAAAAA", "changes": 2, "dry_run": false, "event": "redact_backfill.change", "fields": [{"n": 1, "path": "turn[1].asr", "rules": ["split-surname"]}, {"n": 1, "path": "feedback[7].note", "rules": ["phone"]}], "kind": "trace"}'
BADCH='{"call_id": "木子李", "changes": 1, "event": "redact_backfill.change", "fields": [{"n": 1, "path": "转给木子李", "rules": ["x"]}], "kind": "trace"}'
reset; FAKE_EXEC_OUT="$J3" FAKE_EXEC_ERR="$CH
$BADCH
Traceback 验证码 3827" bash "$RB"
grep -q '^deepsuck-redact|user.info|INFO change call=AAAAAAAA kind=trace changes=2 fields=turn\[1\].asr:split-surname:1,feedback\[7\].note:phone:1$' "$LOGFILE" || fail "structured change log"
! grep -q '木子\|3827\|Traceback\|验证码' "$LOGFILE" || fail "change log must be whitelisted"
pass "redact-backfill forwards whitelisted structured change log only (#254)"
reset; FAKE_EXEC_RC=3 FAKE_EXEC_OUT='{"dir_exists": true, "error": "backup_exists"}' bash "$RB" && fail "backup exists must fail" || true
grep -q 'user.err|ERROR backup file already exists in /traces/backups; nothing rewritten' "$LOGFILE" || fail "backup exists -> ERROR (#216)"
pass "redact-backfill backup exists -> ERROR, no traceback (#216)"
reset; FAKE_EXEC_OUT="$J0" bash "$RB"
grep -q "^docker exec deepsuck-voice-1 sh -c mkdir -p -m 0700 \"\$1\" && chmod 0700 \"\$1\" _ /traces/backups$" "$CALLS" || fail "backup dir 0700"
[ "$(grep -c ' find /traces/backups ' "$CALLS")" = 2 ] || fail "prune before and on exit"
reset; FAKE_EXEC_RC=1 bash "$RB" && fail "exec failure must exit non-zero" || true
[ "$(grep -c ' find /traces/backups .*-mmin +1440 -print -delete$' "$CALLS")" = 2 ] || fail "prune must still run (before + EXIT trap) when backfill fails"
tail -n 1 "$CALLS" | grep -q ' find /traces/backups ' || fail "EXIT trap prune is last"
reset; FAKE_EXEC_OUT="not json" bash "$RB" && fail "bad json must fail" || true
tail -n 1 "$CALLS" | grep -q ' find /traces/backups ' || fail "prune on abnormal exit (bad json)"
reset; FAKE_AUX_RC=1 FAKE_EXEC_OUT="$J0" bash "$RB" && fail "backup dir failure must exit non-zero" || true
grep -q 'user.err|ERROR cannot prepare backup dir /traces/backups (0700)' "$LOGFILE" || fail "backup dir failure -> ERROR"
! grep -q ' python -m voice.redact_backfill' "$CALLS" || fail "no backfill without backup dir"
pass "redact-backfill backup dir 0700; 24h prune runs before backfill and again on any exit, incl. failures (#254)"
reset; FAKE_EXEC_RC=1 FAKE_EXEC_ERR="Traceback 验证码 3827" bash "$RB" && fail "exec failure must exit non-zero" || true
grep -q '^deepsuck-redact|user.err|ERROR voice.redact_backfill failed in deepsuck-voice-1 (exit 1)' "$LOGFILE" || fail "exec failure -> ERROR"
! grep -q '3827\|Traceback' "$LOGFILE" || fail "traceback leaked"
reset; FAKE_EXEC_OUT="not json" bash "$RB" && fail "bad json must fail" || true
grep -q 'user.err|ERROR voice.redact_backfill output is not the expected JSON' "$LOGFILE" || fail "bad json -> ERROR"
reset; FAKE_EXEC_OUT='{"dir_exists": false}' bash "$RB" && fail "missing dir must fail" || true
grep -q 'user.err|ERROR trace dir missing' "$LOGFILE" || fail "missing dir -> ERROR"
reset; FAKE_EXEC_OUT="$J0" REDACT_CONTAINER=other-voice bash "$RB"; grep -q '^docker exec other-voice ' "$CALLS" || fail "container override"
pass "redact-backfill failures (exec error, bad JSON, missing dir) -> ERROR + non-zero; container configurable"
grep -q -- "-mmin +\$((KEEP_HOURS \* 60)) -print -delete" "$RB" || fail "redact-backfill backups must be pruned (#254: keep 24h, was: no backups)"

# --- chat-usage-prune（#178）：文字代理逐次台账 >2 天压缩、>45 天删除，等 cost-latest 读完 ---
P="$T/proxy"; CL="$T/costlog"; mkdir -p "$CL"
cu_setup() {
  rm -f "$P"/chat-usage-* "$CL"/*
  for d in 2026-10-19 2026-10-17 2026-10-16 2026-10-14 2026-08-20; do
    printf '{"ts":"%sT01:00:00.000Z","day":"%s","usage":{"prompt_tokens":10}}\n%.0s' "$d" "$d" $(seq 1 200) > "$P/chat-usage-$d.jsonl"
  done
  printf '{"day":"2026-10-15"}\n' | gzip -c > "$P/chat-usage-2026-10-15.jsonl.gz"
  for d in 2026-09-18 2026-09-04 2026-09-03; do printf '{"day":"%s"}\n' "$d" | gzip -c > "$P/chat-usage-$d.jsonl.gz"; done  # 31 / 45（边界，保留）/ 46 天
  echo '{}' > "$P/chat-budget.json"
  for f in "$P"/chat-usage-* "$P/chat-budget.json"; do old 2 "$f"; done
  touch "$P/chat-usage-2026-10-14.jsonl"                     # 最后写入晚于 cost-latest：要跳过
  echo '{}' > "$CL/cost-2026-10-18.json"; touch -d "@$(( $(date +%s) - 3600 ))" "$CL/cost-2026-10-18.json"
  ln -sfn cost-2026-10-18.json "$CL/cost-latest.json"
}
CU() { CHAT_USAGE_TODAY=2026-10-19 COST_OUT_DIR="$CL" bash "$DW" "$@"; }
cu_setup; cp "$P/chat-usage-2026-10-16.jsonl" "$T/cu-orig.jsonl"
reset; CU chat-usage-prune
for d in 2026-10-19 2026-10-17 2026-10-14; do [ -f "$P/chat-usage-$d.jsonl" ] || fail "chat-usage-$d.jsonl must stay"; done
[ ! -e "$P/chat-usage-2026-10-16.jsonl" ] && gzip -t "$P/chat-usage-2026-10-16.jsonl.gz" || fail "3-day-old file should be gzipped"
gzip -dc "$P/chat-usage-2026-10-16.jsonl.gz" | cmp -s - "$T/cu-orig.jsonl" || fail "gz content must match"
[ -f "$P/chat-usage-2026-10-15.jsonl.gz" ] || fail "existing .gz within 30 days kept"
[ -f "$P/chat-usage-2026-09-18.jsonl.gz" ] && [ -f "$P/chat-usage-2026-09-04.jsonl.gz" ] || fail "31- and 45-day .gz kept (delete only >45)"
[ ! -e "$P/chat-usage-2026-09-03.jsonl.gz" ] && [ ! -e "$P/chat-usage-2026-08-20.jsonl" ] || fail ">45-day files deleted"
[ -f "$P/chat-budget.json" ] || fail "chat-budget.json untouched"
grep -q '^deepsuck-diskwatch|user.warning|WARN chat-usage-prune skipped chat-usage-2026-10-14.jsonl: cost-latest mtime .* not after file mtime' "$LOGFILE" || fail "skip WARN"
grep -Eq '^deepsuck-diskwatch\|user.info\|INFO chat-usage-prune .*: compressed 1 \[chat-usage-2026-10-16.jsonl\] deleted 2 \[chat-usage-2026-0(8-20.jsonl|9-03.jsonl.gz) chat-usage-2026-0(8-20.jsonl|9-03.jsonl.gz)\] skipped 1, reclaimed [0-9]+KB \([0-9]+B; gzip >2d, delete >45d, Asia/Shanghai\)' "$LOGFILE" || fail "summary log: $(cat "$LOGFILE")"
pass "chat-usage-prune gzips >2d, deletes >45d (by filename day), skips files newer than cost-latest, logs to diskwatch"
cu_setup; before=$(find "$P" -type f | sort)
reset; CU --dry-run chat-usage-prune
[ "$before" = "$(find "$P" -type f | sort)" ] || fail "dry-run changed files"
grep -q 'INFO \[dry-run\] chat-usage-prune .*compressed 1 .*deleted 2 ' "$LOGFILE" || fail "dry-run summary"
pass "chat-usage-prune --dry-run changes nothing"
cu_setup; rm -f "$CL/cost-latest.json"; before=$(find "$P" -type f | sort)
reset; CU chat-usage-prune
[ "$before" = "$(find "$P" -type f | sort)" ] || fail "no cost-latest -> must not touch"
[ "$(grep -c 'WARN chat-usage-prune skipped .*cost-latest missing' "$LOGFILE")" = 4 ] || fail "missing cost-latest WARN per file"
grep -q 'INFO chat-usage-prune .*compressed 0 \[\] deleted 0 \[\] skipped 4, reclaimed 0KB' "$LOGFILE" || fail "summary when skipped"
pass "chat-usage-prune skips everything when cost-latest is missing"
cu_setup
reset; FAKE_TAGS="deepsuck-caddy:rollback-887ac0" CU docker-prune
[ -f "$P/chat-usage-2026-10-16.jsonl.gz" ] || fail "weekly docker-prune runs chat-usage-prune"
awk -F'|' '/chat-usage-prune .*compressed/{a=NR} /docker-prune freed/{b=NR} END{exit !(a && b && a < b)}' "$LOGFILE" || fail "chat-usage-prune before docker prune"
cu_setup
reset; FAKE_TAGS="" CU docker-prune && fail "missing rollback tag still fails" || true
[ -f "$P/chat-usage-2026-10-16.jsonl.gz" ] || fail "chat-usage-prune runs even when docker prune is skipped"
pass "weekly docker-prune (#18) runs chat-usage-prune first, independent of rollback-tag check"
rm -f "$P"/chat-usage-* "$P/chat-budget.json"

# --- install-timers ---
export DEEPSUCK_ETC="$T/etc" COST_OUT_DIR="$T/log2"
rm -f "$T/data/cost-baseline.json"
reset; bash "$DIR/deploy/install-timers.sh" --dry-run > "$T/inst.txt"
[ ! -e "$T/etc/systemd" ] && [ ! -e "$T/log2" ] && [ ! -e "$T/data/cost-baseline.json" ] || fail "install --dry-run changed files"
! grep -q . "$CALLS" || fail "install --dry-run called systemctl"; pass "install-timers --dry-run changes nothing"
reset; bash "$DIR/deploy/install-timers.sh" > "$T/inst.txt"
for u in deepsuck-diskwatch deepsuck-docker-prune deepsuck-redact deepsuck-cost; do
  [ -f "$T/etc/systemd/system/$u.service" ] && [ -f "$T/etc/systemd/system/$u.timer" ] || fail "$u units"
done
grep -q "ExecStart=$DIR/deploy/diskwatch.sh run" "$T/etc/systemd/system/deepsuck-diskwatch.service" || fail "@DIR@ rendered"
! grep -rq '@DIR@' "$T/etc/systemd/system" || fail "@DIR@ left"
grep -q 'OnCalendar=\*-\*-\* 20:40:00 Asia/Shanghai' "$T/etc/systemd/system/deepsuck-cost.timer" || fail "cost timer time"
grep -q 'OnCalendar=\*-\*-\* 20:30:00 Asia/Shanghai' "$T/etc/systemd/system/deepsuck-redact.timer" || fail "redact timer time (before 20:40 cost)"
grep -q "ExecStart=$DIR/deploy/redact-backfill.sh$" "$T/etc/systemd/system/deepsuck-redact.service" || fail "redact service ExecStart"
grep -q 'ROLLBACK_TAGS=' "$T/etc/default/deepsuck-maint" || fail "maint env"
[ -f "$T/data/cost-baseline.json" ] && [ -d "$T/log2" ] || fail "baseline/logdir"
grep -q 'systemctl daemon-reload' "$CALLS" && grep -q 'systemctl enable --now deepsuck-diskwatch.timer deepsuck-docker-prune.timer deepsuck-redact.timer deepsuck-cost.timer' "$CALLS" || fail "systemctl calls"
pass "install-timers installs 4 services + 4 timers, config, baseline"
echo "ROLLBACK_TAGS=custom:1" > "$T/etc/default/deepsuck-maint"; echo '{"coupon_balance": 1}' > "$T/data/cost-baseline.json"
reset; bash "$DIR/deploy/install-timers.sh" > "$T/inst.txt"
grep -q 'custom:1' "$T/etc/default/deepsuck-maint" && grep -q '"coupon_balance": 1' "$T/data/cost-baseline.json" || fail "overwrote existing config"
! grep -q 'daemon-reload' "$CALLS" || fail "reload without change"; grep -q 'unchanged' "$T/inst.txt" || fail "idempotent message"
pass "install-timers is idempotent (keeps config/baseline, no reload when unchanged)"

if command -v systemd-analyze >/dev/null; then
  for f in "$T"/etc/systemd/system/*.timer; do
    systemd-analyze calendar "$(sed -n 's/^OnCalendar=//p' "$f")" >/dev/null || fail "calendar in $f"
  done
  pass "timer OnCalendar expressions parse"
fi
echo "all maint tests passed"
