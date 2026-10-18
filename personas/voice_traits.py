"""读取 personas/voice_traits.yaml（需要 PyYAML）。

    from personas.voice_traits import load, fillers
    fillers()["retiree"]    # 与 voice/persona.py 的 FILLERS 同格式：{persona_id: [口头语, ...]}
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

PATH = Path(__file__).resolve().parent / "voice_traits.yaml"


def load() -> Dict:
    try:
        import yaml  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("personas.voice_traits 需要 PyYAML：pip install pyyaml") from e
    with open(PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def personas() -> Dict[str, Dict]:
    return load()["personas"]


def fillers() -> Dict[str, List[str]]:
    """backchannel 列表，可直接替换 voice/persona.py 中的 FILLERS。"""
    return {pid: list(t["backchannel"]) for pid, t in personas().items()}


if __name__ == "__main__":
    import json
    print(json.dumps(fillers(), ensure_ascii=False, indent=2))
