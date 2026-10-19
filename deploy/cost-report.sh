#!/usr/bin/env bash
# 每晚的成本汇总（GitHub #20）：宿主机 root 运行 python3 -m voice.cost --json，由 deepsuck-cost.timer 每天 20:40（+08:00）调度。
#
#   deploy/cost-report.sh [--dry-run] [--day YYYY-MM-DD]
#
# 输出 $COST_OUT_DIR/cost-YYYY-MM-DD.json（默认 /var/log/deepsuck），再把 cost-latest.json 符号链接原子地指向它。
# voice/cost.py 只用标准库，直接用宿主机 python3 跑仓库里的代码，不进容器、不用重建镜像；
# 数据从命名卷的宿主机目录（docker volume inspect 的 Mountpoint）只读取用：voice-traces（每通一个 <call_id>.jsonl，
# 同意与否都有，docs/TRACE_SCHEMA.md）、voice-data（voice-budget.json、cost-baseline.json）、proxy-data（chat-budget.json）。
# 怎么解析 trace 由 voice/cost.py 决定（随仓库更新），本脚本只负责路径、调度和落盘。
# 单价：从 deploy/.env 按名取 PRICE_* / *_LLM_MODEL 等非密钥配置（不 source 整个文件，Key 不进环境）。
# --dry-run：照常计算并打印到 stdout，不写文件、不动链接。日志：journalctl -t deepsuck-cost
set -euo pipefail
# shellcheck source=deploy/maint-lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/maint-lib.sh"
TAG="${COST_TAG:-deepsuck-cost}"
DAY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY_RUN=1 ;;
    --day) DAY="${2:?--day needs YYYY-MM-DD}"; shift ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
DAY="${DAY:-$(TZ=Asia/Shanghai date +%F)}"
case "$DAY" in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;; *) echo "bad --day: $DAY" >&2; exit 2 ;; esac

OUT_DIR="${COST_OUT_DIR:-/var/log/deepsuck}"
DATA=$(vol_path voice-data VOICE_DATA_HOST_DIR)
TRACES=$(vol_path voice-traces TRACE_HOST_DIR)
PROXY=$(vol_path proxy-data PROXY_DATA_HOST_DIR)
BASELINE="${COST_BASELINE:-$DATA/cost-baseline.json}"
EVAL="${COST_EVAL_SPEND:-/var/lib/deepsuck/eval-spend.csv}"
PY="${PYTHON:-python3}"

for k in DEEPSUCK_LLM_MODEL LLM_MODEL PRICE_LLM_TABLE PRICE_LLM_IN_PER_M PRICE_LLM_OUT_PER_M \
         VOICE_PRICE_LLM_IN_PER_M VOICE_PRICE_LLM_OUT_PER_M PRICE_ASR_PER_SEC PRICE_TTS_PER_10K_CHARS \
         COST_ASR_FREE_SEC_PER_MONTH COST_ALERT_PCT; do
  v=$(env_get "$k" "")
  if [ -n "$v" ]; then export "$k=$v"; fi
done

run_cost() {
  (cd "$DIR" && "$PY" -m voice.cost --day "$DAY" --json --data "$DATA" --traces "$TRACES" \
     --chat-budget "$PROXY/chat-budget.json" --baseline "$BASELINE" --eval-spend "$EVAL")
}

summary() {  # 从 JSON 摘一行给日志
  "$PY" -c '
import json, sys
d = json.load(open(sys.argv[1]))
b = d.get("baseline") or {}
s = "day=%s total_list=%.4f total_after_free=%.4f" % (d["day"], d["total_list"], d["total_after_free"])
if "balance_est" in b: s += " balance_est=%.2f" % b["balance_est"]
if "month_pct" in b: s += " month_pct=%.1f%%" % b["month_pct"]
miss = [k for k, v in (d.get("sources") or {}).items() if isinstance(v, dict) and not v.get("found") and k != "voice_usage"]  # #5 v2 起不再有 voice-usage.jsonl
if miss: s += " missing=" + ",".join(miss)
print(("ALERT " if b.get("alert") else "") + s)' "$1"
}

if [ "$DRY_RUN" = 1 ]; then
  run_cost
  log info "$TAG" "computed $DAY (data=$DATA traces=$TRACES proxy=$PROXY); would write $OUT_DIR/cost-$DAY.json and relink cost-latest.json"
  exit 0
fi

mkdir -p "$OUT_DIR"
tmp=$(mktemp "$OUT_DIR/.cost-$DAY.XXXXXX")
trap 'rm -f "$tmp" "$OUT_DIR/.cost-latest.tmp"' EXIT
if ! run_cost > "$tmp"; then
  log err "$TAG" "voice.cost failed for $DAY"
  exit 1
fi
chmod 640 "$tmp"
mv -f "$tmp" "$OUT_DIR/cost-$DAY.json"
ln -sfn "cost-$DAY.json" "$OUT_DIR/.cost-latest.tmp"
mv -Tf "$OUT_DIR/.cost-latest.tmp" "$OUT_DIR/cost-latest.json"   # rename(2)：原子替换链接
line=$(summary "$OUT_DIR/cost-$DAY.json")
case "$line" in
  ALERT*) log warning "$TAG" "coupon usage reached alert threshold: ${line#ALERT }" ;;
  *) log info "$TAG" "wrote $OUT_DIR/cost-$DAY.json: $line" ;;
esac
find "$OUT_DIR" -maxdepth 1 -name 'cost-20*.json' -mtime +"$(int_or "${COST_KEEP_DAYS:-180}" 180)" -delete
