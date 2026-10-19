# shellcheck shell=bash
# deploy/diskwatch.sh、cost-report.sh、install-timers.sh 共用的函数（GitHub #18/#20）。只被 source，不单独运行。
# 运行在宿主机（root），不进容器：路径按 docker 命名卷的实际挂载点解析。

DIR="${DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-deepsuck}"   # docker-compose.yml 顶层 name:
DRY_RUN="${DRY_RUN:-0}"

# log <info|warning|err> <tag> <消息>：写 journald（journalctl -t <tag>），交互运行或 MAINT_ECHO=1 时同时打印到 stderr（stdout 留给 JSON）。
log() {
  local prio="$1" tag="$2"; shift 2
  local label
  case "$prio" in err) label=ERROR ;; warning) label=WARN ;; *) label=INFO ;; esac
  local msg="$label $*"
  [ "$DRY_RUN" = 1 ] && msg="$label [dry-run] $*"
  logger -t "$tag" -p "user.$prio" -- "$msg" 2>/dev/null || true
  if [ -t 2 ] || [ "${MAINT_ECHO:-0}" = 1 ]; then printf '%s: %s\n' "$tag" "$msg" >&2; fi
}

# env_get KEY DEFAULT：环境变量优先，其次 deploy/.env 里的同名行（只按名取单个非密钥配置，不 source 整个文件）。
env_get() {
  local key="$1" def="${2:-}" val
  val="${!key:-}"
  if [ -z "$val" ] && [ -f "$DIR/deploy/.env" ]; then
    val=$(sed -n "s/^${key}=//p" "$DIR/deploy/.env" | tail -n 1)
    val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  fi
  printf '%s' "${val:-$def}"
}

# vol_path <卷名不带项目前缀> <覆盖变量名>：命名卷在宿主机上的目录。
vol_path() {
  local name="$1" override="${2:-}" p=""
  [ -n "$override" ] && p="${!override:-}"
  if [ -z "$p" ]; then
    p=$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT}_${name}" 2>/dev/null || true)
  fi
  printf '%s' "${p:-/var/lib/docker/volumes/${COMPOSE_PROJECT}_${name}/_data}"
}

docker_root() {
  local r
  r=$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)
  printf '%s' "${r:-/var/lib/docker}"
}

# int_or <值> <默认>：非整数（含小数）取整，解析不了用默认。
int_or() {
  local v="${1%%.*}"
  case "$v" in ''|*[!0-9]*) printf '%s' "$2" ;; *) printf '%s' "$((10#$v))" ;; esac
}
