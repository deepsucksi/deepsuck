"""底噪映射（#11 新人设）：小陈妈妈 → living_room，郑老板 → shop；人设 id 还没进 personas.json 时也能用。"""
import asyncio

import numpy as np
import pytest

from voice import ambience as A
from voice import dashscope_ws as ds
from voice.persona_ids import canonical


def test_new_persona_mapping():
    assert A.choose("chen", "1") == "living_room" and A.choose("zheng", "1") == "shop"
    # 定稿前的候选写法都归一过来
    for pid in ("xiaochen", "mom", "Chen", " chen "):
        assert A.choose(pid, "1") == "living_room"
    for pid in ("shop_owner", "zhenglaoban", "ZHENG"):
        assert A.choose(pid, "1") == "shop"
    # 老映射不变，李大爷的 tv 先保留
    assert A.choose("wang", "1") == "kitchen" and A.choose("lin", "1") == "street" and A.choose("li", "1") == "tv"
    # 未知人设退回厨房；强制和关闭照旧
    assert A.choose("nobody", "1") == "kitchen"
    assert A.choose("chen", "shop") == "shop" and A.choose("wang", "living_room") == "living_room"
    assert A.choose("zheng", "off") is None


def test_mapping_targets_exist():
    assert set(A.BY_PERSONA.values()) <= set(A.SOUNDS)
    assert canonical("wang") == "wang" and canonical("") == ""


@pytest.mark.parametrize("name", ["living_room", "shop"])
def test_new_assets_format(name):
    sf = pytest.importorskip("soundfile")
    f = A.SOUNDS[name]
    assert f.exists() and f.stat().st_size < 600_000
    info = sf.info(str(f))
    assert (info.samplerate, info.channels, info.format, info.subtype) == (24000, 1, "OGG", "VORBIS")
    assert info.duration > 30  # 够长，循环不明显
    x, _ = sf.read(str(f), dtype="float64")
    rms = 20 * np.log10(np.sqrt(np.mean(x ** 2)))
    assert -27.5 < rms < -24.5
    assert np.abs(x).max() <= 0.75  # 软限幅：0.7 * tanh，留一点编码余量
    # 首尾能接上：循环点两侧电平不跳
    n = 24000 // 4
    a, b = np.sqrt(np.mean(x[:n] ** 2)), np.sqrt(np.mean(x[-n:] ** 2))
    assert abs(20 * np.log10(a / b)) < 6


@pytest.mark.parametrize("pid,name", [("chen", "living_room"), ("zheng", "shop"), ("xiaochen", "living_room")])
def test_new_persona_mixer(pid, name):
    m = A.make_mixer(pid, "1")
    if m is None:
        pytest.skip("pipecat / soundfile 不可用")
    asyncio.run(m.start(16000))
    out = np.frombuffer(asyncio.run(m.mix(b"\x00\x00" * 320)), dtype=np.int16)
    assert len(out) == 320 and np.abs(out).max() > 0
    rms = np.sqrt(np.mean(np.frombuffer(m._sounds[name], dtype=np.int16).astype(float) ** 2)) * A.volume() / 32768
    assert 20 * np.log10(rms) < -35


def test_new_persona_voices():
    assert ds.persona_voice("chen", env={}) == ds.VoiceSpec("longanli_v3", "cosyvoice-v3-flash", None)
    assert ds.persona_voice("zheng", env={}) == ds.VoiceSpec("longsanshu_v3", "cosyvoice-v3-flash", None)
    assert ds.persona_voice("shop_owner", env={}).voice == "longsanshu_v3"
    vd = "cosyvoice-v3.5-flash-vd-chenc-0123456789abcdef"
    vs = ds.persona_voice("xiaochen", env={"DEEPSUCK_VOICE_CHEN": vd})
    assert vs.voice == vd and vs.model == "cosyvoice-v3.5-flash" and vs.instruction is None
    # 老人设不受影响
    assert ds.persona_voice("wang", env={}).voice == "longlaoyi_v3"


def test_designs_cover_new_personas():
    from voice import design_voice as dv
    for pid in ("chen", "zheng"):
        model, prefix, prompt, preview = dv.DESIGNS[pid]
        assert model == "cosyvoice-v3.5-flash" and prefix.isalnum() and len(prefix) <= 10
        assert "！" not in preview and "!" not in preview
