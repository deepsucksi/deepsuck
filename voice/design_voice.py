"""在自己的百炼账号里创建人设的设计音色（CosyVoice 声音设计，创建免费，合成按字符计费）。

    python -m voice.design_voice wang            # 创建，打印要填进 .env 的两行
    python -m voice.design_voice wang --preview out.wav

设计音色 ID 只属于创建它的账号，换了 API key 要重新创建。创建后把打印出的
DEEPSUCK_VOICE_WANG=... 写进 .env（或部署环境），重启语音服务即可；不设则回退到系统音色。
key 只从环境变量 DASHSCOPE_API_KEY 读取，不打印。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request

from .dashscope_ws import api_key

URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"

# 人设 → (目标模型, 前缀, 声音描述, 试听句)。描述就是线上选定那版（2026-10 试听对比第 12 段）。
DESIGNS = {
    "wang": ("cosyvoice-v3.5-flash", "wangdb",
             "老年女性，六十五岁左右，退休会计，声音略沙哑，中低音，语速偏慢，说话有点犹豫、爱拖长音，"
             "语气热心唠叨，像在家接电话，说话带浓重的东北口音，嗓门敞亮",
             "喂，哪位？哦，退款是吧。你慢点说，我记一下。"),
}


def create(pid: str, key: str):
    model, prefix, prompt, preview = DESIGNS[pid]
    body = {"model": "voice-enrollment",
            "input": {"action": "create_voice", "target_model": model, "voice_prompt": prompt,
                      "preview_text": preview, "prefix": prefix, "language_hints": ["zh"]},
            "parameters": {"sample_rate": 24000, "response_format": "wav"}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=120))
    o = d["output"]
    return o["voice_id"], base64.b64decode(o.get("preview_audio", {}).get("data") or b"")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.design_voice", description=__doc__.splitlines()[0])
    ap.add_argument("persona", choices=sorted(DESIGNS))
    ap.add_argument("--preview", help="把试听音频写到这个 wav 文件")
    a = ap.parse_args(argv)
    try:
        vid, wav = create(a.persona, api_key())
    except urllib.error.HTTPError as e:
        print(f"创建失败：HTTP {e.code} {e.read().decode()[:300]}", file=sys.stderr)
        return 1
    if a.preview and wav:
        with open(a.preview, "wb") as f:
            f.write(wav)
    up = a.persona.upper()
    print(f"DEEPSUCK_VOICE_{up}={vid}")
    print(f"# DEEPSUCK_VOICE_{up}_INSTRUCTION=请用东北话表达。   # 可选：方言指令，默认不加")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
