#!/usr/bin/env bash
# 磁盘与录音容量巡检（GitHub #18）。宿主机 root 运行，由 systemd timer 调度（deploy/install-timers.sh 安装）。
#
#   deploy/diskwatch.sh [--dry-run] check         根分区和 docker 数据目录使用率：>WARN% 记 WARN，>CRIT% 记 ERROR
#   deploy/diskwatch.sh [--dry-run] retention     录音 / trace / 文字记录按天数清理（规则与容器内一致，见下）
#   deploy/diskwatch.sh [--dry-run] run           check + retention（deepsuck-diskwatch.timer，每 15 分钟）
#   deploy/diskwatch.sh [--dry-run] docker-prune  每周 docker 清理（deepsuck-docker-prune.timer）
#
# 只写日志（logger -t deepsuck-diskwatch），不开 issue、不需要 GitHub token：journalctl -t deepsuck-diskwatch
#
# 配置（环境变量，或 /etc/default/deepsuck-maint，见 deploy/maint.env.example）：
#   DISKWATCH_WARN_PCT=80  DISKWATCH_CRIT_PCT=90
#   DISKWATCH_PATHS="/ <docker 根目录> /var/lib/containerd"（同一分区只报一次，不存在的跳过）
#   TRACE_DAYS / VOICE_TRANSCRIPT_DAYS / KEEP_AUDIO_DAYS：缺省读 deploy/.env，与容器内 voice/trace.py、voice/records.py
#     用同一套天数和后缀，只删过期文件。容器自己每天/每小时也清，两边删的是同一批文件，谁先到谁删，互不冲突；
#     宿主机这份是兜底（容器停着、或 VOICE_TRACE=0 时历史文件也会按期删）。stats.json、voice-usage.jsonl 不在清理范围。
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
  local tr dt
  tr=$(vol_path voice-traces TRACE_HOST_DIR); dt=$(vol_path voice-data VOICE_DATA_HOST_DIR)
  log info "$TAG" "sizes traces=$(du -sk "$tr" 2>/dev/null | cut -f1)KB voice-data=$(du -sk "$dt" 2>/dev/null | cut -f1)KB"
  return 0
}

# purge <目录> <天数> <后缀...>：只看目录第一层、修改时间早于 N 天的普通文件（与 trace.py/records.py 一致）。
purge() {
  local d="$1" days="$2"; shift 2
  [ -d "$d" ] || return 0
  local args=() ext n kb
  for ext in "$@"; do args+=(-o -name "*$ext"); done
  local find_expr=(-maxdepth 1 -type f \( "${args[@]:1}" \) -mmin "+$((days * 1440))")
  n=$(find "$d" "${find_expr[@]}" | wc -l)
  [ "$n" -gt 0 ] || return 0
  kb=$(find "$d" "${find_expr[@]}" -printf '%k\n' | awk '{s+=$1} END{print s+0}')
  if [ "$DRY_RUN" = 1 ]; then
    log info "$TAG" "retention would delete $n files (${kb}KB) older than ${days}d in $d"
  else
    find "$d" "${find_expr[@]}" -delete
    log info "$TAG" "retention deleted $n files (${kb}KB) older than ${days}d in $d"
  fi
}

retention() {
  local tr dt tdays rdays adays
  tr=$(vol_path voice-traces TRACE_HOST_DIR); dt=$(vol_path voice-data VOICE_DATA_HOST_DIR)
  tdays=$(int_or "$(env_get TRACE_DAYS 30)" 30); [ "$tdays" -ge 1 ] || tdays=1
  rdays=$(int_or "$(env_get VOICE_TRANSCRIPT_DAYS 30)" 30)
  adays=$(int_or "$(env_get KEEP_AUDIO_DAYS 7)" 7); [ "$adays" -ge 1 ] || adays=1; [ "$adays" -le 7 ] || adays=7
  purge "$tr" "$tdays" .jsonl .ogg
  purge "$dt/voice/audio" "$adays" .wav
  if [ "$rdays" -gt 0 ]; then purge "$dt/voice/transcripts" "$rdays" .json; fi
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
    check|retention|run|docker-prune) CMD="$1" ;;
    *) echo "unknown argument: $1" >&2; usage 2 >&2 ;;
  esac
  shift
done

case "${CMD:-}" in
  check) check ;;
  retention) retention ;;
  run) check; retention ;;
  docker-prune) docker_prune ;;
  *) usage 2 >&2 ;;
esac
