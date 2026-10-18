#!/usr/bin/env bash
# 重新生成 voice/assets/ambience/*.ogg：下载原始素材（出处见 ../SOURCES.md），裁 62 秒、转 24 kHz 单声道，
# 首尾 1.5 秒交叉淡化做成无缝循环，统一到 -26 dBFS RMS 并软限幅。tv 需要 DASHSCOPE_API_KEY（约 200 字合成）。
#
#   tools/build.sh                      # 全部重做
#   tools/build.sh living_room shop     # 只做指定的几段（其余文件不动）
set -euo pipefail
cd "$(dirname "$0")"; T=$(mktemp -d); OUT=..; HERE=$PWD
trap 'rm -rf "$T"' EXIT
UA="DeepSuck/0.1 (voice@deepsuck.si)"
NAMES="${*:-kitchen street tv living_room shop}"
want() { [[ " $NAMES " == *" $1 "* ]]; }
commons() { curl -fsL -A "$UA" -o "$2" "https://upload.wikimedia.org/wikipedia/commons/$(python3 -c 'import hashlib,sys;n=sys.argv[1];h=hashlib.md5(n.encode()).hexdigest();print(f"{h[0]}/{h[:2]}/{n}")' "$1")"; }
# freesound 的 CC0 素材取官方试听版（HQ mp3，免登录）；编号与作者见 SOURCES.md
freesound() { curl -fsL -A "$UA" -o "$2" "https://cdn.freesound.org/previews/$1-hq.mp3"; }

if want kitchen; then
  commons Ambient_Kitchen_Sounds.wav "$T/k.src"
  ffmpeg -v error -y -i "$T/k.src" -ss 40 -t 62 -ac 1 -ar 24000 "$T/kitchen.wav"
fi
if want street; then
  commons Sunday_in_the_city_street_noise1.ogg "$T/s.src"
  ffmpeg -v error -y -i "$T/s.src" -ss 30 -t 62 -ac 1 -ar 24000 "$T/street.wav"
fi
if want tv; then
  (cd "$T" && python3 "$HERE/tv_voice.py")
  ffmpeg -v error -y -i "$T/tv_voice.wav" -af "highpass=f=250,lowpass=f=1600,aecho=0.8:0.6:40|70:0.3|0.2,apad=pad_dur=3" -t 42 -ar 24000 -ac 1 "$T/tvm.wav"
  ffmpeg -v error -y -f lavfi -i "anoisesrc=c=pink:a=0.02:d=42:r=24000" -af lowpass=f=3000 -ac 1 "$T/hum.wav"
  ffmpeg -v error -y -i "$T/tvm.wav" -i "$T/hum.wav" -filter_complex amix=inputs=2:normalize=0 -t 42 "$T/tv.wav"
fi
if want living_room; then
  # 客厅：窗外/隔壁远处的小孩玩耍声（低通 900 Hz + 压缩 + 短回声，只剩远处的嬉闹轮廓，听不出字），
  # 叠一层自制的低频房间底噪（棕噪声，固定种子）
  freesound 274/274988_3620380 "$T/lr.src"
  ffmpeg -v error -y -ss 62 -t 62 -i "$T/lr.src" -ac 1 -ar 24000 \
    -af "highpass=f=150,lowpass=f=900,lowpass=f=900,acompressor=threshold=0.05:ratio=6:attack=5:release=200,aecho=0.8:0.5:35|60:0.25|0.15,volume=-4dB" "$T/kids.wav"
  ffmpeg -v error -y -f lavfi -i "anoisesrc=c=brown:a=0.02:d=62:r=24000:s=11" -af "lowpass=f=400,highpass=f=40,volume=-4dB" -ac 1 "$T/room.wav"
  ffmpeg -v error -y -i "$T/kids.wav" -i "$T/room.wav" -filter_complex amix=inputs=2:normalize=0 -t 62 "$T/living_room.wav"
fi
if want shop; then
  # 店铺：便利店店内环境（冰柜、门铃、脚步、远处顾客）只取前 46 秒（之后有成段对话），低通 1500 Hz + 压缩把零星人声糊掉；
  # 叠五金店空店底噪（冷柜/灯管嗡声）补平稳度
  freesound 149/149444_221578 "$T/sh1.src"
  freesound 257/257695_4028838 "$T/sh2.src"
  ffmpeg -v error -y -ss 0 -t 46 -i "$T/sh1.src" -ac 1 -ar 24000 \
    -af "highpass=f=80,lowpass=f=1500,lowpass=f=1500,acompressor=threshold=0.08:ratio=4:attack=5:release=250" "$T/sh1.wav"
  ffmpeg -v error -y -stream_loop 1 -i "$T/sh2.src" -t 46 -ac 1 -ar 24000 -af "highpass=f=40,lowpass=f=3000,volume=14dB" "$T/sh2.wav"
  ffmpeg -v error -y -i "$T/sh1.wav" -i "$T/sh2.wav" -filter_complex amix=inputs=2:normalize=0 -t 46 "$T/shop.wav"
fi

python3 - "$T" "$OUT" $NAMES <<'PY'
import sys, numpy as np, soundfile as sf
T, OUT, *names = sys.argv[1:]
for name in names:
    x, sr = sf.read(f"{T}/{name}.wav", dtype="float64")
    if x.ndim > 1:
        x = x.mean(axis=1)
    fade = int(1.5 * sr); body = x[:-fade].copy(); r = np.linspace(0, 1, fade)
    body[:fade] = body[:fade] * r + x[-fade:] * (1 - r)
    body *= 10 ** (-26 / 20) / np.sqrt(np.mean(body ** 2))
    sf.write(f"{OUT}/{name}.ogg", 0.7 * np.tanh(body / 0.7), sr, format="OGG", subtype="VORBIS")
    print(f"{name}.ogg")
PY
