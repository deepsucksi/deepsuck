"""#95：小陈妈妈 → 客厅 living_room、郑老板 → 店铺 shop；设计音色语速；tv 底噪已删除。"""
import asyncio

import numpy as np
import pytest

from voice import ambience as A
from voice import dashscope_ws as ds

VD = "cosyvoice-v3.5-flash-vd-chenc-0123456789abcdef"


def test_persona_mapping_follows_personas_json():
    assert A.BY_PERSONA == {"wang": "kitchen", "chen": "living_room", "lin": "street", "zheng": "shop"}
    assert set(A.BY_PERSONA.values()) <= set(A.SOUNDS)
    # 别名走 personas.json 的 aliases，不另起一套
    assert A.ALIASES == {"li": "wang", "xiaochen": "chen", "mom": "chen", "shop_owner": "zheng"}
    for pid in ("xiaochen", "mom"):
        assert A.choose(pid, "1") == "living_room"
    assert A.choose("shop_owner", "1") == "shop"
    assert A.choose("li", "1") == "kitchen"
    assert A.choose("nobody", "1") == A.DEFAULT_SOUND == "kitchen"
    assert A.choose("chen", "shop") == "shop" and A.choose("wang", "living_room") == "living_room"
    assert A.choose("zheng", "off") is None


def test_tv_removed():
    assert "tv" not in A.SOUNDS
    assert not (A.DIR / "tv.ogg").exists() and not (A.DIR / "tools" / "tv_voice.py").exists()
    assert A.choose("wang", "tv") == "kitchen"  # 强制 tv 不再生效，按人设选
    src = (A.DIR / "SOURCES.md").read_text(encoding="utf-8")
    assert "living_room.ogg" in src and "shop.ogg" in src and "| `tv.ogg`" not in src


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
    assert np.abs(x).max() <= 0.75  # 软限幅
    n = 24000 // 4
    a, b = np.sqrt(np.mean(x[:n] ** 2)), np.sqrt(np.mean(x[-n:] ** 2))
    assert abs(20 * np.log10(a / b)) < 6  # 循环点两侧电平不跳


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


def test_chen_designed_voice_rate_and_fallback():
    vs = ds.persona_voice("chen", env={"DEEPSUCK_VOICE_CHEN": VD})
    assert vs == ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", None, ds.DESIGNED_RATES["chen"])
    assert 0.6 <= vs.rate < 1.0
    assert ds.persona_voice("xiaochen", env={"DEEPSUCK_VOICE_CHEN": VD}) == vs  # 别名
    # 没配设计音色：退回默认音色，原速（倍率是按设计音色实测定的）
    assert ds.persona_voice("chen", env={}).rate == 1.0
    # 环境变量覆盖，越界截断，乱填用默认
    assert ds.persona_voice("chen", env={"DEEPSUCK_VOICE_CHEN": VD, "DEEPSUCK_VOICE_CHEN_RATE": "0.9"}).rate == 0.9
    assert ds.persona_voice("chen", env={"DEEPSUCK_VOICE_CHEN": VD, "DEEPSUCK_VOICE_CHEN_RATE": "9"}).rate == 2.0
    assert ds.persona_voice("chen", env={"DEEPSUCK_VOICE_CHEN": VD, "DEEPSUCK_VOICE_CHEN_RATE": "x"}).rate == vs.rate
    assert ds.persona_voice("zheng", env={"DEEPSUCK_VOICE_ZHENG_RATE": "1.1"}).rate == 1.1
    assert ds.persona_voice("shop_owner", env={}).voice == "longsanshu_v3"
    # 王阿姨不受影响
    assert ds.persona_voice("wang", env={}) == ds.VoiceSpec("longlaoyi_v3", "cosyvoice-v3-flash", None, 1.0)


def test_rate_in_cache_tag_and_run_task():
    assert ds.VoiceSpec(VD, "m").cache_tag == VD
    assert ds.VoiceSpec(VD, "m", rate=0.75).cache_tag == f"{VD}-r0.75"
    assert ds.run_task_tts("t", "m", "v", 24000, 0.75)["payload"]["parameters"]["rate"] == 0.75


def test_fillers_pass_rate(tmp_path):
    from voice import processors as P
    seen = []

    async def synth(text, voice, sample_rate, **kw):
        seen.append(kw)
        yield b"\x10\x27" * 2400

    vs = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", None, 0.75)
    asyncio.run(P.synth_fillers("chen", vs, 24000, synth=synth, cache_dir=tmp_path))
    assert seen and all(k.get("rate") == 0.75 and k.get("model") == "cosyvoice-v3.5-flash" for k in seen)
    assert all("-r0.75-" in f.name for f in tmp_path.iterdir())


def test_build_pipeline_passes_rate():
    import inspect
    from voice import app
    src = inspect.getsource(app.build_pipeline)
    assert src.count("rate=vs.rate") == 2


def test_chen_design_description():
    from voice import design_voice as dv
    model, prefix, prompt, preview = dv.DESIGNS["chen"]
    assert model == "cosyvoice-v3.5-flash" and prefix == "chenc"
    assert "！" not in preview and "!" not in preview
