"""#252 端到端：模拟一通电话（假 ASR 输入），把所有转写出口都 grep 一遍，原话出现次数必须是 0。

出口：实时推送（notify：interim / scammer / state 里的 intel）、Session.ingest 的 redacted（会话记录、进模型的文本）、
trace 写盘（voice-traces 的 jsonl）、存盘转写（records.save_transcript）、回填（redact_backfill 处理旧 trace / 旧转写）、
日志（loguru 全级别）和 stdout / stderr。以后再漏接一处出口，这里直接失败。
测试句来自 scripts/gen-fixtures.js 的 #250 组（拆字报姓 + 金额）和报名 + 逐字解释。"""
import asyncio
import json
import os

import pytest
from loguru import logger
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice import records as REC
from voice import redact_backfill as BF
from voice import trace as TR
from voice.processors import IntelProcessor

# （假 ASR 句子，不许出现在任何出口里的片段）
LEAK_CASES = [
    ("转给木子李1000元", ("木子李", "木子")),
    ("弓长张三500", ("弓长张", "弓长", "张三")),
    ("我叫张伟，伟大的伟", ("张伟", "伟大的伟")),
]
# 正常词：不能被误伤
NORMAL = ["成长一千元", "东方的东西都是伟大的祖国的", "明天下午三点开会"]


def _tf(t):
    return TranscriptionFrame(text=t, user_id="u", timestamp="t")


def _count(blob: str, needles) -> int:
    return sum(blob.count(n) for n in needles)


ALL_LEAKS = tuple(n for _, ns in LEAK_CASES for n in ns)


@pytest.fixture
def call(tmp_path):
    """跑一通：假 ASR（interim + final）→ IntelProcessor → notify → CallTrace；最后存盘转写。"""
    env = {"TRACE_DIR": str(tmp_path / "traces"), "TRACE_MIN_FREE_MB": "0", "DATA_DIR": str(tmp_path / "data")}
    logs = []
    # DEBUG：线上 loguru 默认级别（app 不另设）。TRACE 级是 pipecat 逐帧转储（含 STT 原始帧），线上不开，见 test_app_never_enables_trace_logging
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG", format="{name}:{function}:{level} | {message} {extra}")
    pushed = []
    session = Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)
    trace = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="m", env=env,
                         prompt_sha=lambda: "x")
    trace.session = session

    async def notify(msg):
        pushed.append(json.loads(json.dumps(msg, ensure_ascii=False)))
        trace.observe(msg)

    p = IntelProcessor(session, context=LLMContext([{"role": "system", "content": "x"}]), notify=notify,
                       filler_prob=0.0)
    texts = [t for t, _ in LEAK_CASES] + NORMAL
    frames = []
    for t in texts:
        frames += [InterimTranscriptionFrame(text=t, user_id="u", timestamp="t"), _tf(t)]
    try:
        down, _ = asyncio.run(run_test(p, frames_to_send=frames,
                                       expected_down_frames=[InterimTranscriptionFrame, TranscriptionFrame] * len(texts)))
        trace.end("client_hangup", stats=session.stats())
        saved = REC.save_transcript(session, trace.id, "web", env=env)
    finally:
        logger.remove(sink)
    return {"env": env, "pushed": pushed, "down": down, "session": session, "trace": trace.path, "saved": saved,
            "logs": logs, "tmp": tmp_path}


def test_every_exit_zero_leaks(call, capsys):
    exits = {
        "live_push": json.dumps(call["pushed"], ensure_ascii=False),
        "ingest_redacted_session": json.dumps(call["session"].messages, ensure_ascii=False),
        "model_input": json.dumps([f.text for f in call["down"] if isinstance(f, TranscriptionFrame)], ensure_ascii=False),
        "intel": json.dumps(call["session"].intel_list(), ensure_ascii=False),
        "trace": call["trace"].read_text(encoding="utf-8"),
        "transcript": call["saved"].read_text(encoding="utf-8"),
        "logs": "\n".join(call["logs"]),
    }
    out = capsys.readouterr()
    exits["stdout_stderr"] = out.out + out.err
    # 磁盘上本通产生的所有文件（防止新加的落盘路径漏网）
    for root, _, files in os.walk(call["tmp"]):
        for f in files:
            pth = os.path.join(root, f)
            try:
                exits["disk:" + os.path.relpath(pth, call["tmp"])] = open(pth, encoding="utf-8").read()
            except UnicodeDecodeError:
                exits["disk:" + os.path.relpath(pth, call["tmp"])] = open(pth, "rb").read().decode("utf-8", "replace")
    leaks = {k: _count(v, ALL_LEAKS) for k, v in exits.items()}
    assert {k: v for k, v in leaks.items() if v} == {}, leaks
    # 每句在实时推送里都有对应的一条（不是被整段吞掉）
    scam = [m["text"] for m in call["pushed"] if m.get("type") == "scammer"]
    assert len(scam) == len(LEAK_CASES) + len(NORMAL)
    assert any("那个名字" in t or "*" in t for t in scam[:len(LEAK_CASES)]), scam


def test_normal_words_untouched(call):
    scam = [m["text"] for m in call["pushed"] if m.get("type") == "scammer"][len(LEAK_CASES):]
    for want, got in zip(NORMAL, scam):
        assert REC.redact_line(want) == want
        assert "那个名字" not in got and "*" not in got, (want, got)
    turns = [json.loads(x) for x in call["trace"].read_text(encoding="utf-8").splitlines()]
    asr = " ".join(r.get("asr", "") for r in turns if r.get("type") == "turn")
    for w in NORMAL:
        assert w.replace("。", "") in asr.replace("。", ""), (w, asr)


def _legacy_trace(d, cid, consent=True):
    rows = [{"type": "start", "call_id": cid, "consent": consent}]
    for n, (t, _) in enumerate(LEAK_CASES, 1):
        rows.append({"type": "turn", "call_id": cid, "n": n, "asr": t, "reply": "嗯", "filler": None})
    for n, t in enumerate(NORMAL, len(LEAK_CASES) + 1):
        rows.append({"type": "turn", "call_id": cid, "n": n, "asr": t, "reply": "好"})
    rows.append({"type": "feedback", "call_id": cid, "note": LEAK_CASES[0][0], "turn": 1})
    rows.append({"type": "end", "call_id": cid, "consent": consent, "reason": "client_hangup"})
    p = d / f"{cid}.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.utime(p, (1_000_000, 1_000_000))
    return p


def test_backfill_fixes_old_traces_and_transcripts(tmp_path, capsys):
    d = tmp_path / "traces"
    d.mkdir()
    td = tmp_path / "transcripts"
    td.mkdir()
    a = _legacy_trace(d, "AAAAAAAA")
    b = _legacy_trace(d, "BBBBBBBB")
    doc = {"transcript": [{"role": "scammer", "text": t} for t, _ in LEAK_CASES] +
                         [{"role": "scammer", "text": t} for t in NORMAL]}
    tp = td / "20261022-130000-web-AAAAAAAA.json"
    tp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    # --call：只处理指定通话，dry-run 不改
    assert BF.main(["--dir", str(d), "--transcripts", str(td), "--dry-run", "--min-age", "0", "--call", "AAAAAAAA"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["files_scanned"] == 1 and s["files_changed"] == 1 and s["transcripts"]["files_changed"] == 1
    assert _count(a.read_text(encoding="utf-8"), ALL_LEAKS) > 0
    assert BF.main(["--dir", str(d), "--transcripts", str(td), "--min-age", "0", "--call", "AAAAAAAA"]) == 0
    out = capsys.readouterr()
    assert _count(out.out + out.err, ALL_LEAKS) == 0 and "AAAAAAAA" not in out.out
    assert _count(a.read_text(encoding="utf-8"), ALL_LEAKS) == 0
    assert _count(tp.read_text(encoding="utf-8"), ALL_LEAKS) == 0
    assert _count(b.read_text(encoding="utf-8"), ALL_LEAKS) > 0          # 没点名的通话不动
    for w in NORMAL:
        assert w in a.read_text(encoding="utf-8") and w in tp.read_text(encoding="utf-8")
    # 全量再跑一次：其余通话也修掉；可重复执行
    assert BF.main(["--dir", str(d), "--transcripts", str(td), "--min-age", "0"]) == 0
    capsys.readouterr()
    assert _count(b.read_text(encoding="utf-8"), ALL_LEAKS) == 0
    assert BF.main(["--dir", str(d), "--transcripts", str(td), "--min-age", "0"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["files_changed"] == 0 and s["transcripts"]["files_changed"] == 0


def test_app_never_enables_trace_logging():
    """pipecat 在 TRACE 级逐帧打印（含 STT 送进来的原始转写帧）；服务端代码不许把日志开到 TRACE。"""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for p in list(root.glob("*.py")) + list((root / "telephony").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        assert not re.search(r"level\s*=\s*[\"']TRACE|LOGURU_LEVEL", src), p.name
