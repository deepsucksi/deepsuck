#!/usr/bin/env bash
# 磁盘与录音容量巡检（GitHub #18）。宿主机 root 运行，由 systemd timer 调度（deploy/install-timers.sh 安装）。
#
#   deploy/diskwatch.sh [--dry-run] check         根分区和 docker 数据目录使用率：>WARN% 记 WARN，>CRIT% 记 ERROR
#   deploy/diskwatch.sh [--dry-run] volumes       trace/录音卷和 voice-data 卷的大小；trace 卷接近 TRACE_MAX_MB 时告警
#   deploy/diskwatch.sh [--dry-run] run           check + volumes（deepsuck-diskwatch.timer，每 15 分钟）
#   deploy/diskwatch.sh [--dry-run] docker-prune  每周清理（deepsuck-docker-prune.timer）：先 chat-usage-prune，再 docker 清理
#   deploy/diskwatch.sh [--dry-run] chat-usage-prune  文字代理逐次台账：超过 2 天压成 .gz、超过 45 天删除（#178）
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
#   chat-usage-prune（#178）：proxy-data 卷（PROXY_DATA_HOST_DIR 可覆盖）里的 chat-usage-YYYY-MM-DD.jsonl，按文件名日期和
#   上海自然日算天数：> CHAT_USAGE_GZIP_DAYS（默认 2）压成 .gz，> CHAT_USAGE_KEEP_DAYS（默认 45）连同 .gz 删除。
#   每个文件都要 cost-latest（COST_OUT_DIR/cost-latest.json，每天 20:40 由 cost-report.sh 生成）的 mtime 晚于该文件的
#   最后写入时间才动，否则跳过并记 WARN；cost-latest 不存在时一律跳过。只动这一种文件名，不碰通话数据。
set -euo pipefail
# shellcheck source=deploy/maint-lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/maint-lib.sh"
TAG="${DISKWATCH_TAG:-deepsuck-diskwatch}"

usage() { sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

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

# 上海自然日的 epoch 天数；CHAT_USAGE_TODAY=YYYY-MM-DD 可覆盖（测试用）
cn_daynum() { echo $(( $(TZ=UTC date -d "$1" +%s) / 86400 )); }

chat_usage_prune() {
  local dir gz_days keep_days today latest latest_m f base d age m sz gsz
  local n_gz=0 n_del=0 n_skip=0 freed=0 gz_list="" del_list=""
  dir=$(vol_path proxy-data PROXY_DATA_HOST_DIR)
  gz_days=$(int_or "$(env_get CHAT_USAGE_GZIP_DAYS 2)" 2)
  keep_days=$(int_or "$(env_get CHAT_USAGE_KEEP_DAYS 45)" 45)
  if [ ! -d "$dir" ]; then log info "$TAG" "chat-usage-prune: $dir missing, nothing to do"; return 0; fi
  today=$(cn_daynum "${CHAT_USAGE_TODAY:-$(TZ=Asia/Shanghai date +%F)}")
  latest="${COST_OUT_DIR:-/var/log/deepsuck}/cost-latest.json"
  latest_m=$(stat -L -c %Y "$latest" 2>/dev/null || echo 0)
  shopt -s nullglob
  for f in "$dir"/chat-usage-20[0-9][0-9]-[0-9][0-9]-[0-9][0-9].jsonl "$dir"/chat-usage-20[0-9][0-9]-[0-9][0-9]-[0-9][0-9].jsonl.gz; do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    base=$(basename "$f"); d=${base#chat-usage-}; d=${d%%.*}
    age=$(( today - $(cn_daynum "$d") ))
    [ "$age" -gt "$gz_days" ] || continue
    case "$f" in *.gz) [ "$age" -gt "$keep_days" ] || continue ;; esac
    m=$(stat -c %Y "$f")
    if [ "$latest_m" -le "$m" ]; then
      n_skip=$((n_skip + 1))
      log warning "$TAG" "chat-usage-prune skipped $base: cost-latest $([ "$latest_m" = 0 ] && echo missing || echo "mtime $(date -d "@$latest_m" '+%F %T %z') not after file mtime $(date -d "@$m" '+%F %T %z')")"
      continue
    fi
    sz=$(stat -c %s "$f")
    if [ "$age" -gt "$keep_days" ]; then
      [ "$DRY_RUN" = 1 ] || rm -f -- "$f"
      n_del=$((n_del + 1)); freed=$((freed + sz)); del_list="$del_list $base"
    else
      case "$f" in *.gz) continue ;; esac
      if [ -e "$f.gz" ]; then n_skip=$((n_skip + 1)); log warning "$TAG" "chat-usage-prune skipped $base: $base.gz already exists"; continue; fi
      if [ "$DRY_RUN" = 1 ]; then gsz=$(gzip -c -- "$f" | wc -c)
      else gzip -9 -- "$f"; gsz=$(stat -c %s "$f.gz")
      fi
      n_gz=$((n_gz + 1)); freed=$((freed + sz - gsz)); gz_list="$gz_list $base"
    fi
  done
  shopt -u nullglob
  log info "$TAG" "chat-usage-prune $dir: compressed $n_gz [${gz_list# }] deleted $n_del [${del_list# }] skipped $n_skip, reclaimed $((freed / 1024))KB (${freed}B; gzip >${gz_days}d, delete >${keep_days}d, Asia/Shanghai)"
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
    check|volumes|run|docker-prune|chat-usage-prune) CMD="$1" ;;
    *) echo "unknown argument: $1" >&2; usage 2 >&2 ;;
  esac
  shift
done

case "${CMD:-}" in
  check) check ;;
  volumes) volumes ;;
  run) check; volumes ;;
  docker-prune) chat_usage_prune || log err "$TAG" "chat-usage-prune failed"; docker_prune ;;
  chat-usage-prune) chat_usage_prune ;;
  *) usage 2 >&2 ;;
esac
