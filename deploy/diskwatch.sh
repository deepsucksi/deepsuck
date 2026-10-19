#!/usr/bin/env bash
# 磁盘与录音容量巡检（GitHub #18）。宿主机 root 运行，由 systemd timer 调度（deploy/install-timers.sh 安装）。
#
#   deploy/diskwatch.sh [--dry-run] check         根分区和 docker 数据目录使用率：>WARN% 记 WARN，>CRIT% 记 ERROR
#   deploy/diskwatch.sh [--dry-run] volumes       trace/录音卷和 voice-data 卷的大小；trace 卷接近 TRACE_MAX_MB 时告警
#   deploy/diskwatch.sh [--dry-run] run           check + volumes（deepsuck-diskwatch.timer，每 15 分钟）
#   deploy/diskwatch.sh [--dry-run] docker-prune  每周 docker 清理（deepsuck-docker-prune.timer）
#
# 只写日志（logger -t deepsuck-diskwatch），不开 issue、不需要 GitHub token：journalctl -t deepsuck-diskwatch
#
# 配置（环境变量，或 /etc/default/deepsuck-maint，见 deploy/maint.env.example）：
#   DISKWATCH_WARN_PCT=80  DISKWATCH_CRIT_PCT=90
#   DISKWATCH_PATHS="/ <docker 根目录> /var/lib/containerd"（同一分区只报一次，不存在的跳过）
#   TRACE_MAX_MB（缺省读 deploy/.env，默认 1024）：trace 卷超过它的 WARN_PCT/CRIT_PCT 记 WARN/ERROR（到 100% 容器会停录音）。
#   本脚本不删任何通话数据：trace 和录音由容器内 voice/trace.py 按 TRACE_DAYS / TRACE_AUDIO_DAYS 清理，
#   文字记录 / 原始音频由 voice/records.py 按 VOICE_TRANSCRIPT_DAYS / KEEP_AUDIO_DAYS 清理（docs/TRACE_SCHEMA.md）。
#   ROLLBACK_TAGS="deepsuck-caddy:rollback-887ac0"：docker 清理前必须都在，缺任何一个就跳过清理并记 ERROR。
set -euo pipefail
# shellcheck source=deploy/maint-lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/maint-lib.sh"
TAG="${DISKWATCH_TAG:-deepsuck-diskwatch}"

usage() { sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

check() {
  local warn crit root p src pct avail mnt seen=" " worst=0
  warn=$(int_or "$(env_get DISKWATCH_WARN_PCT 80)" 80)
  crit=$(int_or "$(env_get DISKWATCH_CRIT_PCT 90)" 90)
  root=$(docker_root)
  for p in ${DISKWATCH_PATHS:-/ $root /var/lib/containerd}; do
    [ -e "$p" ] || continue
    read -r src pct avail mnt < <(df -Pk "$p" | awk 'NR==2{gsub("%","",$5); print $1, $5, $4, $6}')
    case "$seen" in *" $mnt "*) continue ;; esac
    seen="$seen$mnt "
    pct=$(int_or "$pct" 0)
    local msg="disk $mnt ${pct}% used, avail $((avail / 1024))MB (dev $src, checked $p)"
    if [ "$pct" -gt "$crit" ]; then log err "$TAG" "$msg > ${crit}%"; worst=2
    elif [ "$pct" -gt "$warn" ]; then log warning "$TAG" "$msg > ${warn}%"; [ "$worst" -ge 1 ] || worst=1
    else log info "$TAG" "$msg"
    fi
  done
  return 0
}

# volumes：只读统计，不删文件。trace 卷 = 文字 *.jsonl + 录音 *.ogg（TRACE_AUDIO_DIR 默认就在卷内）。
volumes() {
  local warn crit tr dt max_mb tr_kb ogg_kb n_jsonl dt_kb pct
  warn=$(int_or "$(env_get DISKWATCH_WARN_PCT 80)" 80)
  crit=$(int_or "$(env_get DISKWATCH_CRIT_PCT 90)" 90)
  tr=$(vol_path voice-traces TRACE_HOST_DIR); dt=$(vol_path voice-data VOICE_DATA_HOST_DIR)
  max_mb=$(int_or "$(env_get TRACE_MAX_MB 1024)" 1024)
  tr_kb=$(du -sk "$tr" 2>/dev/null | cut -f1); tr_kb=$(int_or "$tr_kb" 0)
  ogg_kb=$(find "$tr" -name '*.ogg' -type f -printf '%k\n' 2>/dev/null | awk '{s+=$1} END{print s+0}')
  n_jsonl=$(find "$tr" -name '*.jsonl' -type f 2>/dev/null | wc -l)
  dt_kb=$(du -sk "$dt" 2>/dev/null | cut -f1); dt_kb=$(int_or "$dt_kb" 0)
  local msg="volumes voice-traces=${tr_kb}KB (audio ${ogg_kb}KB, ${n_jsonl} calls) voice-data=${dt_kb}KB"
  if [ "$max_mb" -gt 0 ]; then
    pct=$((tr_kb * 100 / (max_mb * 1024)))
    msg="$msg; traces ${pct}% of TRACE_MAX_MB=${max_mb}"
    if [ "$pct" -gt "$crit" ]; then log err "$TAG" "$msg > ${crit}% (recording stops at 100%)"; return 0
    elif [ "$pct" -gt "$warn" ]; then log warning "$TAG" "$msg > ${warn}%"; return 0
    fi
  fi
  log info "$TAG" "$msg"
}

docker_prune() {
  local t root before after
  for t in ${ROLLBACK_TAGS:-$(env_get ROLLBACK_TAGS deepsuck-caddy:rollback-887ac0)}; do
    if ! docker image inspect "$t" >/dev/null 2>&1; then
      log err "$TAG" "docker-prune skipped: rollback image $t not found"
      return 1
    fi
  done
  root=$(docker_root)
  before=$(df -Pk "$root" | awk 'NR==2{print $3}')
  if [ "$DRY_RUN" = 1 ]; then
    local reclaim
    reclaim=$(docker system df --format '{{.Type}}={{.Reclaimable}}' 2>/dev/null | tr '\n' ' ' || true)
    log info "$TAG" "docker-prune would run: docker builder prune -f --filter until=168h; docker image prune -f (rollback tags ok; reclaimable now: ${reclaim:-?})"
    return 0
  fi
  local out1 out2
  out1=$(docker builder prune -f --filter until=168h 2>&1 | tail -n 1)
  out2=$(docker image prune -f 2>&1 | tail -n 1)
  after=$(df -Pk "$root" | awk 'NR==2{print $3}')
  log info "$TAG" "docker-prune freed $(((before - after) / 1024))MB on $root (used ${before}KB -> ${after}KB; builder: ${out1:-?}; image: ${out2:-?})"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY_RUN=1 ;;
    -h|--help) usage 0 ;;
    check|volumes|run|docker-prune) CMD="$1" ;;
    *) echo "unknown argument: $1" >&2; usage 2 >&2 ;;
  esac
  shift
done

case "${CMD:-}" in
  check) check ;;
  volumes) volumes ;;
  run) check; volumes ;;
  docker-prune) docker_prune ;;
  *) usage 2 >&2 ;;
esac
