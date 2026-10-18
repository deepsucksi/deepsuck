#!/usr/bin/env bash
# 重新生成 voice/assets/ambience/*.ogg：下载原始素材（出处见 ../SOURCES.md），裁 62 秒、转 24 kHz 单声道，
# 首尾 1.5 秒交叉淡化做成无缝循环，统一到 -26 dBFS RMS 并软限幅。tv 需要 DASHSCOPE_API_KEY（约 200 字合成）。
set -euo pipefail
cd "$(dirname "$0")"; T=$(mktemp -d); OUT=..
UA="DeepSuck/0.1 (voice@deepsuck.si)"
curl -sL -A "$UA" -o "$T/k.src" "https://upload.wikimedia.org/wikipedia/commons/$(python3 -c 'import hashlib;n="Ambient_Kitchen_Sounds.wav";h=hashlib.md5(n.encode()).hexdigest();print(f"{h[0]}/{h[:2]}/{n}")')"
curl -sL -A "$UA" -o "$T/s.src" "https://upload.wikimedia.org/wikipedia/commons/$(python3 -c 'import hashlib;n="Sunday_in_the_city_street_noise1.ogg";h=hashlib.md5(n.encode()).hexdigest();print(f"{h[0]}/{h[:2]}/{n}")')"
ffmpeg -v error -y -i "$T/k.src" -ss 40 -t 62 -ac 1 -ar 24000 "$T/k.wav"
ffmpeg -v error -y -i "$T/s.src" -ss 30 -t 62 -ac 1 -ar 24000 "$T/s.wav"
(cd "$T" && python3 "$OLDPWD/tv_voice.py")
ffmpeg -v error -y -i "$T/tv_voice.wav" -af "highpass=f=250,lowpass=f=1600,aecho=0.8:0.6:40|70:0.3|0.2,apad=pad_dur=3" -t 42 -ar 24000 -ac 1 "$T/tvm.wav"
ffmpeg -v error -y -f lavfi -i "anoisesrc=c=pink:a=0.02:d=42:r=24000" -af lowpass=f=3000 -ac 1 "$T/hum.wav"
ffmpeg -v error -y -i "$T/tvm.wav" -i "$T/hum.wav" -filter_complex amix=inputs=2:normalize=0 -t 42 "$T/t.wav"
python3 - "$T" "$OUT" <<'PY'
import sys, numpy as np, soundfile as sf
T, OUT = sys.argv[1:]
for src, name in (("k", "kitchen"), ("s", "street"), ("t", "tv")):
    x, sr = sf.read(f"{T}/{src}.wav", dtype="float64")
    fade = int(1.5 * sr); body = x[:-fade].copy(); r = np.linspace(0, 1, fade)
    body[:fade] = body[:fade] * r + x[-fade:] * (1 - r)
    body *= 10 ** (-26 / 20) / np.sqrt(np.mean(body ** 2))
    sf.write(f"{OUT}/{name}.ogg", 0.7 * np.tanh(body / 0.7), sr, format="OGG", subtype="VORBIS")
PY
rm -rf "$T"
