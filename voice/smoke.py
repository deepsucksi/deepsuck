"""真实 DashScope 冒烟测试（需要 DASHSCOPE_API_KEY，会产生极少量费用）。

python -m voice.smoke [--out screenshots/wangayi-sample.wav]
  1) qwen-plus（OpenAI 兼容）以王阿姨人设回复一句；
  2) CosyVoice（longlaoyi_v3）把这句话合成为 16k WAV；
  3) Paraformer 实时识别把这段 WAV 再转回文字（往返校验）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
import wave

from .dashscope_ws import persona_voice, synthesize, transcribe_pcm
from .persona import system_prompt


def chat(prompt: str, persona: str = "wang", scenario: str = "refund") -> str:
    base = os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    body = {"model": os.environ.get("LLM_MODEL", "qwen-plus"), "max_tokens": 80, "temperature": 0.8,
            "messages": [{"role": "system", "content": system_prompt(persona, scenario)},
                         {"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["DASHSCOPE_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


async def main_async(out: str) -> int:
    t0 = time.time()
    reply = chat("阿姨您好，我是淘宝客服，您买的商品有质量问题，要给您双倍理赔，您先下载个APP。")
    print(f"[1] qwen-plus ✓ {time.time() - t0:.1f}s：{reply}")
    t0 = time.time()
    _vs = persona_voice("wang")
    pcm = b"".join([c async for c in synthesize(reply, voice=_vs.voice, model=_vs.model,
                                                  instruction=_vs.instruction, sample_rate=16000)])
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm)
    print(f"[2] CosyVoice ✓ {time.time() - t0:.1f}s：{len(pcm) / 32000:.1f}s 音频 → {out}")
    t0 = time.time()
    text = await transcribe_pcm(pcm, sample_rate=16000)
    print(f"[3] Paraformer ✓ {time.time() - t0:.1f}s：{text}")
    return 0 if text else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="wangayi-sample.wav")
    a = ap.parse_args()
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("跳过：未设置 DASHSCOPE_API_KEY")
        return 0
    return asyncio.run(main_async(a.out))


if __name__ == "__main__":
    sys.exit(main())
