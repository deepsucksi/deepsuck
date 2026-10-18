#!/bin/bash
# DeepSuck 自建 SIP 软电话（Asterisk 22 + chan_websocket）启动脚本。
# 先校验环境变量（缺密码、密码太短、没开电话入口一律拒绝启动），再把 conf/*.conf 模板渲染进 /etc/asterisk，
# 最后交给镜像自带的 entrypoint（调整 uid、chown 运行目录）启动 Asterisk。
# 只替换下面列出的变量，拨号计划里的 ${EXTEN} 等 Asterisk 变量原样保留。任何密码都不会打印。
set -euo pipefail

die() { echo "[deepsuck-sip] 拒绝启动：$*" >&2; exit 64; }
log() { echo "[deepsuck-sip] $*"; }

SIP_USER="${SIP_USER:-}"
SIP_PASSWORD="${SIP_PASSWORD:-}"
SIP_PORT="${SIP_PORT:-25060}"
SIP_TCP="${SIP_TCP:-0}"
SIP_AI_EXTEN="${SIP_AI_EXTEN:-9000}"
SIP_RTP_PORTS="${SIP_RTP_PORTS:-40100-40199}"
SIP_MAX_CALLS="${SIP_MAX_CALLS:-1}"
SIP_CODECS="${SIP_CODECS:-opus,g722,ulaw,alaw}"
SIP_MEDIA_FORMAT="${SIP_MEDIA_FORMAT:-slin16}"
SIP_ALLOW_CIDR="${SIP_ALLOW_CIDR:-}"
SIP_VOICE_URL="${SIP_VOICE_URL:-ws://127.0.0.1:7860}"
PUBLIC_IP="${SIP_PUBLIC_IP:-${VOICE_PUBLIC_IP:-}}"
VOICE_MAX_MINUTES="${VOICE_MAX_MINUTES:-5}"

# ---- 校验 ----
[ "${VOICE_TELEPHONY:-0}" = 1 ] || die "VOICE_TELEPHONY 不是 1：voice 服务没开电话入口，SIP 打进来也接不到 AI"
case ",${VOICE_TELEPHONY_ADAPTERS:-ws-raw}," in *,asterisk-ws,*) ;; *) die "VOICE_TELEPHONY_ADAPTERS 里没有 asterisk-ws";; esac
[ -n "${VOICE_TELEPHONY_TOKEN:-}" ] || die "VOICE_TELEPHONY_TOKEN 为空"
[[ "$VOICE_TELEPHONY_TOKEN" =~ ^[A-Za-z0-9._~-]{16,200}$ ]] || die "VOICE_TELEPHONY_TOKEN 需为 16 位以上字母/数字/._~-（openssl rand -hex 24 生成）"
[ -n "$SIP_USER" ] || die "SIP_USER 为空（分机账号，例如 openssl rand -hex 4 生成一个不好猜的名字）"
[[ "$SIP_USER" =~ ^[A-Za-z0-9_.-]{3,32}$ ]] || die "SIP_USER 只能是 3-32 位字母/数字/_.-"
[ -n "$SIP_PASSWORD" ] || die "SIP_PASSWORD 为空（openssl rand -hex 16 生成）"
[ "${#SIP_PASSWORD}" -ge 16 ] || die "SIP_PASSWORD 太短（至少 16 位）"
[[ "$SIP_PASSWORD" =~ ^[A-Za-z0-9._~+=-]+$ ]] || die "SIP_PASSWORD 只能含字母/数字/._~+=-（避免 Asterisk 配置里的注释符等特殊字符）"
[ "$SIP_PASSWORD" != "$SIP_USER" ] || die "SIP_PASSWORD 不能与 SIP_USER 相同"
[[ "$SIP_PORT" =~ ^[0-9]+$ ]] && [ "$SIP_PORT" -ge 1024 ] && [ "$SIP_PORT" -le 65535 ] || die "SIP_PORT 需为 1024-65535"
[ "$SIP_PORT" != 5060 ] && [ "$SIP_PORT" != 5061 ] || log "警告：SIP_PORT=$SIP_PORT 是默认端口，扫描器最多，建议换掉"
[[ "$SIP_AI_EXTEN" =~ ^[0-9]{3,8}$ ]] || die "SIP_AI_EXTEN 需为 3-8 位数字"
[[ "$SIP_RTP_PORTS" =~ ^([0-9]+)-([0-9]+)$ ]] || die "SIP_RTP_PORTS 格式应为 起-止，例如 40100-40199"
SIP_RTP_START="${BASH_REMATCH[1]}"; SIP_RTP_END="${BASH_REMATCH[2]}"
[ "$SIP_RTP_START" -ge 1024 ] && [ "$SIP_RTP_START" -lt "$SIP_RTP_END" ] && [ "$SIP_RTP_END" -le 65535 ] || die "SIP_RTP_PORTS 区间无效"
[[ "$SIP_MAX_CALLS" =~ ^[1-9]$ ]] || die "SIP_MAX_CALLS 需为 1-9"
[[ "$SIP_CODECS" =~ ^(opus|g722|ulaw|alaw)(,(opus|g722|ulaw|alaw))*$ ]] || die "SIP_CODECS 只支持 opus,g722,ulaw,alaw 的组合"
case "$SIP_MEDIA_FORMAT" in slin16|slin|ulaw|alaw) ;; *) die "SIP_MEDIA_FORMAT 只支持 slin16/slin/ulaw/alaw";; esac
[[ "$SIP_VOICE_URL" =~ ^ws://(127\.0\.0\.1|localhost|\[::1\]|voice)(:[0-9]+)?$ ]] || die "SIP_VOICE_URL 只允许连本机/容器内网的 voice（ws://127.0.0.1:7860）"
[ -z "$PUBLIC_IP" ] || [[ "$PUBLIC_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "VOICE_PUBLIC_IP/SIP_PUBLIC_IP 不是 IPv4 地址"
[[ "$VOICE_MAX_MINUTES" =~ ^[0-9]+$ ]] || VOICE_MAX_MINUTES=5
[ "$VOICE_MAX_MINUTES" -gt 0 ] || VOICE_MAX_MINUTES=30
SIP_MAX_SECONDS=$(( VOICE_MAX_MINUTES * 60 + 30 ))
SIP_MAX_CHANNELS=$(( SIP_MAX_CALLS * 2 + 2 ))

# ---- 渲染 ----
NAT=""
if [ -n "$PUBLIC_IP" ]; then
  NAT="external_media_address=$PUBLIC_IP
external_signaling_address=$PUBLIC_IP"
else
  log "警告：没有 VOICE_PUBLIC_IP，SDP 里会写容器看到的地址；公网手机可能单通/无声"
fi
for n in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 127.0.0.0/8; do NAT="$NAT
local_net=$n"; done
TCP=""
if [ "$SIP_TCP" = 1 ]; then
  TCP="[transport-tcp]
type=transport
protocol=tcp
bind=0.0.0.0:$SIP_PORT
allow_reload=no
$NAT"
fi
ACL=""
if [ -n "$SIP_ALLOW_CIDR" ]; then
  [[ "$SIP_ALLOW_CIDR" =~ ^[0-9./,]+$ ]] || die "SIP_ALLOW_CIDR 格式应为逗号分隔的 IPv4 CIDR"
  ACL="[deepsuck-acl]
type=acl
deny=0.0.0.0/0.0.0.0"
  IFS=, read -ra cidrs <<<"$SIP_ALLOW_CIDR"
  for c in "${cidrs[@]}"; do ACL="$ACL
permit=$c"; done
fi
SIP_TOKEN="$VOICE_TELEPHONY_TOKEN"
export SIP_USER SIP_PASSWORD SIP_PORT SIP_AI_EXTEN SIP_RTP_START SIP_RTP_END SIP_MAX_CALLS SIP_CODECS \
  SIP_MEDIA_FORMAT SIP_VOICE_URL SIP_TOKEN SIP_MAX_SECONDS SIP_MAX_CHANNELS NAT TCP ACL
VARS='$SIP_USER $SIP_PASSWORD $SIP_PORT $SIP_AI_EXTEN $SIP_RTP_START $SIP_RTP_END $SIP_MAX_CALLS $SIP_CODECS $SIP_MEDIA_FORMAT $SIP_VOICE_URL $SIP_TOKEN $SIP_MAX_SECONDS $SIP_MAX_CHANNELS $NAT $TCP $ACL'

SRC="$(dirname "$0")/conf"
# DEEPSUCK_SIP_RENDER_ONLY=<目录>：只校验并渲染到该目录后退出（单元测试用，不碰 /etc/asterisk）
ETC="${DEEPSUCK_SIP_RENDER_ONLY:-/etc/asterisk}"
[ "$ETC" != / ] || die "渲染目录不能是 /"
umask 027
# 只留我们自己的配置：镜像自带的 100 多个示例配置全部移走，模块按 modules.conf 白名单加载
ind=""
if [ -f "$ETC/indications.conf" ]; then ind="$(sed 's/^country *=.*/country=cn/' "$ETC/indications.conf")"; fi  # 忙音等提示音沿用镜像自带的
find "$ETC" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
[ -z "$ind" ] || printf '%s\n' "$ind" > "$ETC/indications.conf"
for f in "$SRC"/*.conf; do
  envsubst "$VARS" < "$f" > "$ETC/$(basename "$f")"
done
unset SIP_PASSWORD SIP_TOKEN VOICE_TELEPHONY_TOKEN
[ -z "${DEEPSUCK_SIP_RENDER_ONLY:-}" ] || { log "已渲染到 $ETC"; exit 0; }
chown -R asterisk:asterisk "$ETC"
proto=UDP; [ "$SIP_TCP" = 1 ] && proto=UDP+TCP
log "分机账号 $SIP_USER，AI 分机 $SIP_AI_EXTEN；SIP $proto 端口 $SIP_PORT，RTP UDP $SIP_RTP_START-$SIP_RTP_END，公网 IP ${PUBLIC_IP:-未设置}，最多 $SIP_MAX_CALLS 路"
exec /usr/local/bin/entrypoint.sh "$@"
