"""语音说话特征（口头语、听错反问、语速口音、停顿与扯家常节奏）。
数据唯一来源：site/assets/core/personas.json 每个人设的 ``voiceTraits`` 字段；不需要 PyYAML。

    from personas.voice_traits import personas, fillers
    fillers()["wang"]    # 与 voice/persona.py 的 FILLERS 同格式：{persona_id: [口头语, ...]}

现有人设 backchannel 开头几条是线上已合成缓存的旧条目（音频按文本缓存），只删不改字；新条目追加在末尾。
"""
from __future__ import annotations

import json
from typing import Dict, List

from .humanize.confusion import _core_path


def load() -> Dict:
    return json.loads(_core_path().read_text(encoding="utf-8"))


def personas() -> Dict[str, Dict]:
    """{persona_id: voiceTraits（附 name）}。"""
    return {p["id"]: dict(p["voiceTraits"], name=p["name"]) for p in load()["personas"] if p.get("voiceTraits")}


def fillers() -> Dict[str, List[str]]:
    """backchannel 列表，可直接替换 voice/persona.py 中的 FILLERS。"""
    return {pid: list(t["backchannel"]) for pid, t in personas().items()}


if __name__ == "__main__":
    print(json.dumps(fillers(), ensure_ascii=False, indent=2))
