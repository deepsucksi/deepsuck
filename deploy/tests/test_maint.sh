#!/usr/bin/env bash
# deploy/diskwatch.sh、cost-report.sh、install-timers.sh 的离线测试：docker/df/logger/systemctl 全部打桩，不碰真机器。
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

# --- retention ---
old() { touch -d "@$(( $(date +%s) - $1 * 86400 - 3600 ))" "$2"; }
mk() { : > "$1"; }
for f in AAAAAAAA.jsonl AAAAAAAA.ogg BBBBBBBB.jsonl stats.json; do mk "$T/traces/$f"; done
old 31 "$T/traces/AAAAAAAA.jsonl"; old 31 "$T/traces/AAAAAAAA.ogg"; old 29 "$T/traces/BBBBBBBB.jsonl"; old 99 "$T/traces/stats.json"
mk "$T/data/voice/transcripts/x.json"; old 31 "$T/data/voice/transcripts/x.json"
mk "$T/data/voice/audio/a.wav"; old 8 "$T/data/voice/audio/a.wav"
mk "$T/data/voice/voice-usage.jsonl"; old 99 "$T/data/voice/voice-usage.jsonl"
mk "$T/data/voice-budget.json"; old 99 "$T/data/voice-budget.json"
reset; bash "$DW" --dry-run retention
[ -f "$T/traces/AAAAAAAA.jsonl" ] || fail "dry-run must not delete"; grep -q 'would delete 2 files' "$LOGFILE" || fail "dry-run summary"; pass "retention --dry-run deletes nothing"
reset; bash "$DW" retention
[ ! -e "$T/traces/AAAAAAAA.jsonl" ] && [ ! -e "$T/traces/AAAAAAAA.ogg" ] || fail "old trace not deleted"
[ -f "$T/traces/BBBBBBBB.jsonl" ] || fail "29-day trace deleted"
[ -f "$T/traces/stats.json" ] || fail "stats.json must be kept"
[ ! -e "$T/data/voice/transcripts/x.json" ] || fail "old transcript kept"
[ ! -e "$T/data/voice/audio/a.wav" ] || fail "audio > 7 days kept"
[ -f "$T/data/voice/voice-usage.jsonl" ] && [ -f "$T/data/voice-budget.json" ] || fail "usage/budget files must be kept"
grep -q 'retention deleted 2 files .* older than 30d' "$LOGFILE" || fail "retention log"; pass "retention deletes only expired traces/recordings, keeps stats/usage"
mk "$T/traces/CCCCCCCC.jsonl"; old 11 "$T/traces/CCCCCCCC.jsonl"
reset; TRACE_DAYS=10 bash "$DW" retention; [ ! -e "$T/traces/CCCCCCCC.jsonl" ] || fail "TRACE_DAYS override"
echo "TRACE_DAYS=5" > "$DIR/deploy/.env"; mk "$T/traces/DDDDDDDD.jsonl"; old 6 "$T/traces/DDDDDDDD.jsonl"
reset; bash "$DW" retention; [ ! -e "$T/traces/DDDDDDDD.jsonl" ] || fail "TRACE_DAYS from deploy/.env"; rm "$DIR/deploy/.env"
mk "$T/data/voice/transcripts/y.json"; old 400 "$T/data/voice/transcripts/y.json"
reset; VOICE_TRANSCRIPT_DAYS=0 bash "$DW" retention; [ -f "$T/data/voice/transcripts/y.json" ] || fail "VOICE_TRANSCRIPT_DAYS=0 keeps"
pass "retention days from env / deploy/.env, 0 disables transcripts"

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

# --- install-timers ---
export DEEPSUCK_ETC="$T/etc" COST_OUT_DIR="$T/log2"
rm -f "$T/data/cost-baseline.json"
reset; bash "$DIR/deploy/install-timers.sh" --dry-run > "$T/inst.txt"
[ ! -e "$T/etc/systemd" ] && [ ! -e "$T/log2" ] && [ ! -e "$T/data/cost-baseline.json" ] || fail "install --dry-run changed files"
! grep -q . "$CALLS" || fail "install --dry-run called systemctl"; pass "install-timers --dry-run changes nothing"
reset; bash "$DIR/deploy/install-timers.sh" > "$T/inst.txt"
for u in deepsuck-diskwatch deepsuck-docker-prune deepsuck-cost; do
  [ -f "$T/etc/systemd/system/$u.service" ] && [ -f "$T/etc/systemd/system/$u.timer" ] || fail "$u units"
done
grep -q "ExecStart=$DIR/deploy/diskwatch.sh run" "$T/etc/systemd/system/deepsuck-diskwatch.service" || fail "@DIR@ rendered"
! grep -rq '@DIR@' "$T/etc/systemd/system" || fail "@DIR@ left"
grep -q 'OnCalendar=\*-\*-\* 20:40:00 Asia/Shanghai' "$T/etc/systemd/system/deepsuck-cost.timer" || fail "cost timer time"
grep -q 'ROLLBACK_TAGS=' "$T/etc/default/deepsuck-maint" || fail "maint env"
[ -f "$T/data/cost-baseline.json" ] && [ -d "$T/log2" ] || fail "baseline/logdir"
grep -q 'systemctl daemon-reload' "$CALLS" && grep -q 'systemctl enable --now deepsuck-diskwatch.timer deepsuck-docker-prune.timer deepsuck-cost.timer' "$CALLS" || fail "systemctl calls"
pass "install-timers installs 3 services + 3 timers, config, baseline"
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
