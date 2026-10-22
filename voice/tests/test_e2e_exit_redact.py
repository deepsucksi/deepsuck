"""#252 端到端：模拟一通电话（假 ASR 输入），把所有转写出口都 grep 一遍，原话出现次数必须是 0。

出口：实时推送（notify：interim / scammer / state 里的 intel）、Session.ingest 的 redacted（会话记录、进模型的文本）、
trace 写盘（voice-traces 的 jsonl）、存盘转写（records.save_transcript）、回填（redact_backfill 处理旧 trace / 旧转写）、
日志（loguru 全级别）和 stdout / stderr。以后再漏接一处出口，这里直接失败。
测试句来自 scripts/gen-fixtures.js 的 #250 组（拆字报姓 + 金额）和报名 + 逐字解释。
#254：网页（consent=true）和电话线路（SIP，consent="sip-text-only"）两条都跑；回填也覆盖 SIP 的旧 trace / 旧转写。"""
import asyncio
import json
import os
from pathlib import Path

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
# #259：charExplain[15]（「户名写耳东陈 + 姓名 + 逐字解释」ASR 漏逗号那条）原文曾让 name_say_regions 抛 KeyError；
# 片段按夹具下标取，测试文件里不写姓名原文
_CE15 = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "redact.json")
                   .read_text(encoding="utf-8"))["charExplain"][15]["text"]
LEAK_CASES.append((_CE15, (_CE15[6:9], _CE15[7:9], _CE15[-4:])))  # 「X方的X」不收：与 NORMAL 正常句重叠
# 正常词：不能被误伤
NORMAL = ["成长一千元", "东方的东西都是伟大的祖国的", "明天下午三点开会"]


def _tf(t):
    return TranscriptionFrame(text=t, user_id="u", timestamp="t")


def _count(blob: str, needles) -> int:
    return sum(blob.count(n) for n in needles)


ALL_LEAKS = tuple(n for _, ns in LEAK_CASES for n in ns)


CHANNELS = ["web", "phone"]   # phone = SIP 线路（voice/telephony/server.py：CallTrace(channel="phone")、save_transcript(..., "phone")）


@pytest.fixture(params=CHANNELS)
def call(tmp_path, request):
    """跑一通：假 ASR（interim + final）→ IntelProcessor → notify → CallTrace；最后存盘转写。"""
    env = {"TRACE_DIR": str(tmp_path / "traces"), "TRACE_MIN_FREE_MB": "0", "DATA_DIR": str(tmp_path / "data")}
    logs = []
    # DEBUG：线上 loguru 默认级别（app 不另设）。TRACE 级是 pipecat 逐帧转储（含 STT 原始帧），线上不开，见 test_app_never_enables_trace_logging
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG", format="{name}:{function}:{level} | {message} {extra}")
    pushed = []
    session = Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)
    channel = request.param
    extra = {"caller": "13800138000"} if channel == "phone" else {}
    trace = TR.CallTrace(channel=channel, consent=True, persona="wang", scenario="refund", model="m", env=env,
                         prompt_sha=lambda: "x", **extra)
    assert trace.consent == (TR.SIP_CONSENT if channel == "phone" else True)
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
        saved = REC.save_transcript(session, trace.id, channel, env=env)
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


ALL_FIXTURE_TEXT = tuple(t for t, _ in LEAK_CASES) + ALL_LEAKS + tuple(NORMAL)


def _check_change_log(err: str, channel: str, dry_run: bool):
    recs = [json.loads(x) for x in err.splitlines() if x.startswith("{") and BF.CHANGE_EVENT in x]
    assert sorted(r["kind"] for r in recs) == ["trace", "transcript"], recs
    for r in recs:
        assert set(r) == {"event", "call_id", "kind", "dry_run", "fields", "changes"}
        assert r["call_id"] == "AAAAAAAA" and r["dry_run"] is dry_run
        assert r["changes"] == sum(f["n"] for f in r["fields"]) > 0
        for f in r["fields"]:
            assert set(f) == {"path", "rules", "n"} and f["n"] >= 1 and f["rules"]
    paths = {f["path"] for r in recs for f in r["fields"]}
    assert "turn[1].asr" in paths and "feedback[%d].note" % (len(LEAK_CASES) + len(NORMAL) + 1) in paths, paths
    assert "transcript[0].text" in paths, paths
    rules = {x for r in recs for f in r["fields"] for x in f["rules"]}
    assert "split-surname" in rules, rules
    # 原文、泄漏片段、正常句、改后文本（「那个名字」）都不许出现
    assert _count(err, ALL_FIXTURE_TEXT) == 0 and "那个名字" not in err and "*" not in err, err


@pytest.mark.parametrize("channel,consent", [("web", True), ("phone", "sip-text-only")], ids=["web", "sip"])
def test_backfill_fixes_old_traces_and_transcripts(tmp_path, capsys, channel, consent):
    d = tmp_path / "traces"
    d.mkdir()
    td = tmp_path / "transcripts"
    td.mkdir()
    a = _legacy_trace(d, "AAAAAAAA", consent)
    b = _legacy_trace(d, "BBBBBBBB", consent)
    doc = {"transcript": [{"role": "scammer", "text": t} for t, _ in LEAK_CASES] +
                         [{"role": "scammer", "text": t} for t in NORMAL]}
    tp = td / f"20261022-130000-{channel}-AAAAAAAA.json"
    tp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    # --call：只处理指定通话，dry-run 不改
    assert BF.main(["--dir", str(d), "--transcripts", str(td), "--dry-run", "--min-age", "0", "--call", "AAAAAAAA"]) == 0
    out = capsys.readouterr()
    s = json.loads(out.out)
    assert s["files_scanned"] == 1 and s["files_changed"] == 1 and s["transcripts"]["files_changed"] == 1
    # #254：dry-run 也按文件记结构化改动日志（stderr），只有编号 / 类别 / 字段路径 / 规则 / 处数，没有任何原文
    _check_change_log(out.err, channel, dry_run=True)
    assert s["sip"] == (1 if consent == "sip-text-only" else 0)
    assert _count(a.read_text(encoding="utf-8"), ALL_LEAKS) > 0
    assert BF.main(["--dir", str(d), "--transcripts", str(td), "--min-age", "0", "--call", "AAAAAAAA"]) == 0
    out = capsys.readouterr()
    _check_change_log(out.err, channel, dry_run=False)
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


def test_backfill_backup_exists_no_traceback(tmp_path, capsys):
    """#216：--backup 指向已存在的文件时不抛 traceback、不改文件，输出错误 JSON、退出码 3。"""
    d = tmp_path / "traces"
    d.mkdir()
    p = _legacy_trace(d, "DDDDDDDD")
    before = p.read_bytes()
    bk = tmp_path / "backup-x.tar"
    bk.write_bytes(b"old")
    assert BF.main(["--dir", str(d), "--no-transcripts", "--min-age", "0", "--backup", str(bk)]) == 3
    out = capsys.readouterr()
    assert json.loads(out.out)["error"] == "backup_exists" and "Traceback" not in out.err
    assert p.read_bytes() == before and bk.read_bytes() == b"old"
    # 新备份目录不存在时自动建（0700），备份文件 0600
    bk2 = tmp_path / "backups" / "backup-y.tar"
    assert BF.main(["--dir", str(d), "--no-transcripts", "--min-age", "0", "--backup", str(bk2)]) == 0
    capsys.readouterr()
    assert oct(bk2.parent.stat().st_mode & 0o777) == "0o700" and oct(bk2.stat().st_mode & 0o777) == "0o600"
    assert _count(p.read_text(encoding="utf-8"), ALL_LEAKS) == 0


def test_backfill_still_skips_no_consent(tmp_path, capsys):
    """#254 只放开 SIP：网页未同意（false）的旧 trace 仍一律不动。"""
    d = tmp_path / "traces"
    d.mkdir()
    p = _legacy_trace(d, "CCCCCCCC", False)
    before = p.read_bytes()
    assert BF.main(["--dir", str(d), "--no-transcripts", "--min-age", "0"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["skipped_not_consented"] == 1 and s["files_changed"] == 0 and p.read_bytes() == before


def test_app_never_enables_trace_logging():
    """pipecat 在 TRACE 级逐帧打印（含 STT 送进来的原始转写帧）；服务端代码不许把日志开到 TRACE。"""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for p in list(root.glob("*.py")) + list((root / "telephony").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        assert not re.search(r"level\s*=\s*[\"']TRACE|LOGURU_LEVEL", src), p.name


# ---- trace 直接收原文的公开入口（不经上游 IntelProcessor 打码）----
# TR.feedback(note)、TR.client_report(reason / detail)、CallTrace.observe(未打码的 scammer / bot / filler 文本)。
# 只回退 trace.py 时这里必须失败（#253 审核意见）。
def _direct_trace(tmp_path):
    env = {"TRACE_DIR": str(tmp_path / "traces"), "TRACE_MIN_FREE_MB": "0", "DATA_DIR": str(tmp_path / "data")}
    trace = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="m", env=env,
                         prompt_sha=lambda: "x", feedback_key="k")
    return env, trace


def _disk(tmp_path) -> str:
    blob = []
    for root, _, files in os.walk(tmp_path):
        for f in files:
            blob.append(open(os.path.join(root, f), "rb").read().decode("utf-8", "replace"))
    return "\n".join(blob)


@pytest.mark.parametrize("case", [c for c, _ in LEAK_CASES], ids=[f"LEAK_CASES[{i}]" for i in range(len(LEAK_CASES))])
def test_trace_feedback_direct_zero_leaks(tmp_path, case):
    env, trace = _direct_trace(tmp_path)
    assert TR.feedback(trace.id, note=case, turn=1, env=env, key="k") == {"ok": True}
    rows = [json.loads(x) for x in trace.path.read_text(encoding="utf-8").splitlines()]
    assert any(r.get("type") == "feedback" and r.get("note") for r in rows)
    assert _count(_disk(tmp_path), ALL_LEAKS) == 0


@pytest.mark.parametrize("case", [c for c, _ in LEAK_CASES], ids=[f"LEAK_CASES[{i}]" for i in range(len(LEAK_CASES))])
def test_trace_client_report_direct_zero_leaks(tmp_path, case):
    env, trace = _direct_trace(tmp_path)
    res = TR.client_report(trace.id, "media_error", reason=case, detail={"error": case, "browser": case}, env=env)
    assert res == {"ok": True, "stored": True}
    assert _count(_disk(tmp_path), ALL_LEAKS) == 0


def test_trace_observe_raw_text_zero_leaks(tmp_path):
    env, trace = _direct_trace(tmp_path)
    for t, _ in LEAK_CASES:
        trace.observe({"type": "bot", "intent": "opening", "text": t})
        trace.observe({"type": "scammer", "text": t, "turn": 1})
        trace.observe({"type": "filler", "text": t})
        trace.observe({"type": "bot", "intent": "reply", "text": t})
    trace.end("client_hangup")
    assert _count(_disk(tmp_path), ALL_LEAKS) == 0


def test_trace_redact_direct():
    for t, ns in LEAK_CASES:
        assert _count(TR.redact(t), ns) == 0, t


def test_logger_exception_has_no_locals():
    """app.py / telephony/server.py 的 logger.exception：loguru diagnose 必须关掉，堆栈里不带局部变量（#253）。"""
    import io
    import re
    from pathlib import Path
    from voice import logsetup
    import voice.app  # noqa: F401
    import voice.telephony.server  # noqa: F401

    root = Path(__file__).resolve().parents[1]
    for rel in ("app.py", "telephony/server.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert re.search(r"^from \.+ import logsetup", src, re.M), rel
        assert "diagnose=True" not in src, rel
    assert logsetup.sink_options()["diagnose"] is False
    with pytest.raises(ValueError):
        logger.remove(0)  # 默认 diagnose=True 的 handler 已被移除
    buf = io.StringIO()
    hid = logsetup.configure(buf)
    try:
        def boom(text):
            secret = text + "_LOCAL"  # noqa: F841
            raise RuntimeError("x")
        try:
            boom(LEAK_CASES[0][0])
        except RuntimeError:
            logger.exception("run_bot failed")
    finally:
        logger.remove(hid)
    out = buf.getvalue()
    assert "RuntimeError" in out and "run_bot failed" in out
    assert _count(out, ALL_LEAKS) == 0 and "_LOCAL" not in out, out
