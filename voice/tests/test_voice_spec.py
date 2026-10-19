import re
import asyncio
import json
from pathlib import Path

from voice import dashscope_ws as ds
from voice.processors import fillers_missing, synth_fillers

VD = "cosyvoice-v3.5-flash-vd-wangdb-0123456789abcdef"


def test_default_is_system_voice():
    vs = ds.persona_voice("wang", env={})
    assert vs == ds.VoiceSpec("longlaoyi_v3", "cosyvoice-v3-flash", None)


def test_designed_voice_infers_model_and_ignores_instruction_for_system_voice():
    vs = ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD})
    assert vs.model == "cosyvoice-v3.5-flash" and vs.voice == VD
    # 系统音色不支持指令：设了也不发
    vs2 = ds.persona_voice("lin", env={"DEEPSUCK_VOICE_LIN_INSTRUCTION": "请用东北话表达。"})
    assert vs2.instruction is None


def test_instruction_toggle(monkeypatch):
    on = ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD, "DEEPSUCK_VOICE_WANG_INSTRUCTION": "请用东北话表达。"})
    assert on.instruction == "请用东北话表达。"
    for off in ("0", "off", "", " none "):
        assert ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD,
                                             "DEEPSUCK_VOICE_WANG_INSTRUCTION": off}).instruction is None
    monkeypatch.setitem(ds.DEFAULT_INSTRUCTIONS, "wang", "请用东北话表达。")
    assert ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD}).instruction == "请用东北话表达。"
    assert ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD,
                                         "DEEPSUCK_VOICE_WANG_INSTRUCTION": "0"}).instruction is None


def test_explicit_model_wins_and_global_default():
    vs = ds.persona_voice("lin", env={"DEEPSUCK_TTS_MODEL": "cosyvoice-v3-plus"})
    assert vs.model == "cosyvoice-v3-plus"
    vs = ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD, "DEEPSUCK_VOICE_WANG_MODEL": "x"})
    assert vs.model == "x"


def test_new_persona_voices():
    """#95：小陈妈妈用设计音色（只认环境变量，没配退回默认音色，自托管能用），郑老板 longsanshu_v3。"""
    assert ds.persona_voice("chen", env={}) == ds.VoiceSpec(ds.DEFAULT_VOICE, "cosyvoice-v3-flash", None, 1.0)
    assert ds.persona_voice("zheng", env={}) == ds.VoiceSpec("longsanshu_v3", "cosyvoice-v3-flash", None, 1.0)
    for pid in ("chen", "zheng"):
        assert ds.persona_voice(pid, env={f"DEEPSUCK_VOICE_{pid.upper()}": "longxx_v3"}).voice == "longxx_v3"
    assert ds.persona_voice("wang", env={}).voice == "longlaoyi_v3"


def test_run_task_tts_instruction():
    p = ds.run_task_tts("t", "m", "v", 24000)["payload"]["parameters"]
    assert "instruction" not in p
    p = ds.run_task_tts("t", "m", "v", 24000, instruction="请用东北话表达。")["payload"]["parameters"]
    assert p["instruction"] == "请用东北话表达。"


def test_cache_tag_separates_instruction():
    a = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", None)
    b = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", "请用东北话表达。")
    assert a.cache_tag == VD and b.cache_tag != a.cache_tag


def test_synth_fillers_passes_model_and_instruction(tmp_path):
    calls = []

    async def synth(line, voice, sample_rate, **kw):
        calls.append((voice, kw))
        yield b"\x10\x27" * 4000

    vs = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", "请用东北话表达。")
    got = asyncio.run(synth_fillers("wang", vs, 24000, synth=synth, cache_dir=tmp_path))
    assert got and not fillers_missing("wang", vs, 24000, got)
    assert all(v == VD and kw == {"model": "cosyvoice-v3.5-flash", "instruction": "请用东北话表达。"} for v, kw in calls)
    assert all(vs.cache_tag in f.name for f in tmp_path.iterdir())
    # 关掉指令是另一套缓存
    off = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", None)
    assert asyncio.run(synth_fillers("wang", off, 24000, synth=synth, cache_dir=tmp_path, cached_only=True)) == {}


def test_stream_service_sends_instruction():
    from voice.services import CosyVoiceStreamTTSService

    sent = []

    class WS:
        async def send(self, m):
            sent.append(json.loads(m))

    s = CosyVoiceStreamTTSService(voice=VD, model="cosyvoice-v3.5-flash", instruction="请用东北话表达。", key="k")
    s._websocket = WS()
    asyncio.run(s._open_task("ctx"))
    p = sent[0]["payload"]
    assert p["model"] == "cosyvoice-v3.5-flash" and p["parameters"]["instruction"] == "请用东北话表达。"


def test_calm_tts_text():
    from voice.persona import calm, speakable
    assert calm("哎呀！退款啊？那太好了！！") == "哎呀。退款啊？那太好了。"
    assert calm("我找找……你等会儿啊~~") == "我找找…你等会儿啊"
    assert calm("我找找……你等会儿啊~~", pauses=False) == "我找找，你等会儿啊"
    assert calm("啊啊啊，真的？") == "啊，真的？"
    assert calm("嗯……", pauses=False) == "嗯"
    assert calm("退…退款？哪…哪个啊。。。") == "退…退款？哪…哪个啊…"
    assert speakable("好的！", calm_tts=False) == "好的！"
    assert speakable("卡号是 6222 **** 3456！") == "卡号是 那几个数没听清。"  # #121：号码整串换成含糊说法


def test_voice_prompt_is_restrained():
    from voice.persona import system_prompt
    for pid in ("wang", "chen", "lin", "zheng"):
        sp = system_prompt(pid, "refund")
        assert "不用感叹号" in sp and "“…”" in sp and "老花镜" in sp and "看不清" not in sp
        assert "62 岁" not in sp and "62岁" not in sp


def test_split_pause_and_range():
    from voice.persona import pause_range, split_pause
    assert split_pause("退…") == ("退", True)
    assert split_pause("…款？") == ("款？", False)
    assert split_pause("我好像…没买吧。") == ("我好像，没买吧。", False)
    assert pause_range("300-900") == (300, 900) and pause_range("0") == (0, 0) and pause_range("x") == (300, 900)


def test_stream_tts_inserts_pause_between_tasks(monkeypatch):
    from voice.services import CosyVoiceStreamTTSService
    import json
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame, TTSStoppedFrame
    from pipecat.tests.utils import SleepFrame, run_test
    from voice.tests.test_latency import _stream_connect
    monkeypatch.setenv("DEEPSUCK_PAUSE_MS", "500")
    connect = _stream_connect()
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000, clause_min_chars=4)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("退…"), LLMTextFrame("退款？哪…哪个啊。"),
              LLMFullResponseEndFrame(), SleepFrame(0.5)]
    down, _ = asyncio.run(run_test(tts, frames_to_send=frames))
    ws = connect.made[0]
    texts = [json.loads(m)["payload"]["input"]["text"] for m in ws.sent if json.loads(m)["header"]["action"] == "continue-task"]
    assert texts == ["退", "退款？", "哪", "哪个啊。"]
    assert ws.actions().count("run-task") == 3 and tts.pauses == 2 and tts.connects == 1
    gaps = [f for f in down if isinstance(f, TTSAudioRawFrame) and len(f.audio) == 24000 and not any(f.audio)]
    assert len(gaps) == 2
    assert sum(isinstance(f, TTSStoppedFrame) for f in down) == 1


def test_stream_tts_turn_ending_on_pause_still_stops(monkeypatch):
    from voice.services import CosyVoiceStreamTTSService
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSStoppedFrame
    from pipecat.tests.utils import SleepFrame, run_test
    from voice.tests.test_latency import _stream_connect
    connect = _stream_connect()
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("我好像…"), SleepFrame(0.3), LLMFullResponseEndFrame(), SleepFrame(0.3)]
    down, _ = asyncio.run(run_test(tts, frames_to_send=frames))
    assert sum(isinstance(f, TTSStoppedFrame) for f in down) == 1


def test_ambience_choice_and_mixer(monkeypatch):
    import numpy as np
    from voice import ambience as A
    assert A.choose("wang", "1") == "kitchen" and A.choose("lin", "1") == "street"
    assert A.choose("chen", "1") == "living_room" and A.choose("zheng", "1") == "shop"
    import json
    core = json.loads((Path(A.__file__).resolve().parents[1] / "site/assets/core/personas.json").read_text(encoding="utf-8"))
    assert {p["id"]: p["ambience"] for p in core["personas"]} == {
        "wang": "kitchen", "chen": "living_room", "lin": "street", "zheng": "shop"}
    assert A.choose("wang", "0") is None and A.choose("wang", "street") == "street"
    for f in A.SOUNDS.values():
        assert f.exists() and f.stat().st_size < 600_000
    m = A.make_mixer("wang", "1")
    asyncio.run(m.start(8000))  # 电话 8k：加载时重采样
    out = np.frombuffer(asyncio.run(m.mix(b"\x00\x00" * 160)), dtype=np.int16)
    assert len(out) == 160 and np.abs(out).max() > 0
    rms = np.sqrt(np.mean(np.frombuffer(m._sounds["kitchen"], dtype=np.int16).astype(float) ** 2)) * A.volume() / 32768
    assert 20 * np.log10(rms) < -35  # 混进去后的底噪足够低
    assert A.make_mixer("wang", "off") is None


def test_system_prompt_uses_voice_style_and_shots():
    from voice import persona as P

    sp = P.system_prompt("wang", "refund")
    wang = P.PERSONA_BY_ID["wang"]
    assert wang["voiceStyle"][0] in sp
    shots = [x for x in wang["voiceShots"] if x["scenario"] == "refund"]
    assert shots and shots[0]["reply"] in sp
    other = [x for x in wang["voiceShots"] if x["scenario"] != "refund"]
    assert all(x["reply"] not in sp for x in other)
    assert "不用感叹号" in sp
    # 字段缺失时退回原提示词，不报错
    assert P.voice_style({}, "refund") == []
    assert P.voice_style({"voiceShots": [{"scenario": "x", "scammer": "a", "reply": "b"}]}, "refund") == []


def test_speakable_reads_numbers_digitwise_and_no_stars():
    from voice.persona import say_digits, speakable, unmask

    s = speakable("130****8600？尾号是8600？你再说一遍。", calm_tts=True)
    assert "*" not in s and "＊" not in s
    # #121：语音合成前的数字过滤——号码、开头几位、尾号都不念，只留一个数字
    assert not re.search(r"[0-9零幺一二三四五六七八九]{2,}", s), s
    assert say_digits("幺三零…你说130开头") == "幺三零…你说幺三零开头"  # say_digits 本身不变，过滤在它前面
    assert speakable("号码是130开头的吧", calm_tts=True) == "号码是好像是1开头的吧"
    assert "那么些钱" in speakable("要我转300元？", calm_tts=True)
    assert "300" not in speakable("先转300过去？", calm_tts=True)
    assert "2026" not in speakable("2026年的事", calm_tts=True)
    assert speakable("先转5块？", calm_tts=True) == "先转5块？"  # 单个、两个数字照旧
    assert say_digits("验证码是032") == "验证码是零三二"
    assert say_digits("工号110") == "工号幺幺零"
    # 打码值给模型前改成自然说法
    # #121：打码值给模型、给 TTS 前一律改成“那个号”，不带出可见尾号
    assert unmask("我的号是130****8600") == "我的号是那个号"
    assert unmask("卡号622202*********3445") == "卡号那个号"
    assert unmask("尾号是130-***-8600") == "尾号是那几位"
    assert unmask("号码 ****") == "号码那个号"
    assert unmask("*0123。") == "那个号。"  # 跨回合报号时上一段被打码，只剩一个星号


def test_unmask_masked_names_say_that_name_not_number_phrase():
    """#136：姓名类打码（汉字姓 + 星号）与语料、人设统一换成“那个名字”（不保留姓氏），不念成“张那个号”；
    不留星号、不带数字。号码类仍是“那个号”。"""
    from voice.persona import guard_output, speakable, unmask

    assert unmask("户名张**") == "户名那个名字"
    assert unmask("你转到这张卡，户名张**") == "你转到这张卡，户名那个名字"
    assert unmask("户名是：李**。") == "户名是：那个名字。"
    # 中间打码：王*明 整个换掉，末字也不念
    assert unmask("收款人王*明") == "收款人那个名字"
    assert unmask("找王*明办") == "找那个名字办"
    # 复姓：常见复姓整体当姓（欧阳** → 那个名字，不会剩下“欧”）；脱敏只留首字时（mask_name("欧阳娜娜") == "欧***"）按首字处理，结果相同
    assert unmask("户名欧阳**") == "户名那个名字"
    assert unmask("欧阳*锋说的") == "那个名字说的"
    assert unmask("户名欧***") == "户名那个名字"
    assert unmask("李*") == "那个名字"
    assert unmask("他姓张**") == "他那个名字"  # 前面的“姓”一并换掉，不说“姓那个名字”
    for t in ("户名张**", "收款人王*明", "户名欧阳**", "李*", "户名是张**对吧？", "他叫张**"):
        for out in (unmask(t), speakable(t, calm_tts=True)):
            assert "那个名字" in out and "那个号" not in out, (t, out)
            assert "*" not in out and "＊" not in out and not any(c.isdigit() for c in out), (t, out)
            assert not any(x in out for x in "张王李欧阳"), (t, out)  # 不保留姓氏
        assert guard_output(unmask(t)) == unmask(t), t  # 换完的说法过输出守卫不会再被打码
    # 送 TTS：模型照抄“户名是张**”时，守卫的户名规则会把“是张**”打成“***”，所以先换说法
    assert speakable("户名是张**对吧？", calm_tts=True) == "户名是那个名字对吧？"
    assert speakable("户名张**", calm_tts=True) == "户名那个名字"
    # 号码 / 卡号类回归不变（星号前是数字或“号/码/卡/是”等字）
    assert unmask("我的号是130****8600") == "我的号是那个号"
    assert unmask("卡号622202*********3445") == "卡号那个号"
    assert unmask("尾号是130-***-8600") == "尾号是那几位"
    assert unmask("尾号是****") == "尾号是那几位"
    assert unmask("号码 ****") == "号码那个号"
    assert unmask("号码****") == "号码那个号"
    assert unmask("卡号****3445") == "卡号那个号"
    assert unmask("QQ 28******10") == "QQ 那个号"
    assert unmask("张**1234") == "张那个号"  # 星号后跟数字是号码，不是姓名
    assert unmask("转到 621700*********0123，户名李**") == "转到 那个号，户名那个名字"
    assert speakable("卡号622202*********3445", calm_tts=True) == "卡号那几个数没听清"
