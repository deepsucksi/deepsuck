"""#259：redact_line / trace.redact / 回填 fail-closed。原文只按夹具下标取，测试里不写姓名。"""
import json
import os
from pathlib import Path

import pytest
from loguru import logger

from voice import callredact as CR
from voice import redact_backfill as BF
from voice import trace as TR

T = json.loads((Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "redact.json")
               .read_text(encoding="utf-8"))["charExplain"][15]["text"]
NEEDLES = (T[6:9], T[7:9], T[-9:-5], T[-4:])


def _count(blob, needles=NEEDLES):
    return sum(blob.count(n) for n in needles)


@pytest.fixture
def boom(monkeypatch):
    """让 redact_line 里的 say_names 抛异常（模拟 #259 那类 KeyError）。"""
    import deepsuck.redact as R

    def bad(*a, **k):
        raise KeyError("head")
    monkeypatch.setattr(R, "say_names", bad)


@pytest.fixture
def logs():
    out = []
    sink = logger.add(lambda m: out.append(str(m)), level="DEBUG", format="{message} {extra}")
    yield out
    logger.remove(sink)


def test_redact_line_fail_closed(boom, logs):
    assert CR.redact_line(T) == CR.REDACT_FAIL_PLACEHOLDER
    assert CR.redact_line_checked(T) == (CR.REDACT_FAIL_PLACEHOLDER, True)
    blob = "\n".join(logs)
    assert "KeyError" in blob and _count(blob) == 0 and T not in blob


def test_redact_line_ok_not_flagged():
    out, bad = CR.redact_line_checked(T)
    assert not bad and _count(out) == 0


def test_live_interim_uses_fail_closed_path():
    src = (Path(CR.__file__).parent / "processors.py").read_text(encoding="utf-8")
    assert 'guard_output(redact_line(frame.text))' in src   # interim 走 redact_line（fail-closed）


def _start(td, cid):
    p = td / f"{cid}.jsonl"
    p.write_text(json.dumps({"schema_version": TR.SCHEMA_VERSION, "type": "start", "call_id": cid, "channel": "web",
                             "consent": True, "t": TR.iso(__import__("time").time())}) + "\n", encoding="utf-8")
    return p


def test_trace_feedback_and_client_report_fail_closed(tmp_path, boom, monkeypatch, logs):
    td = tmp_path / "t"
    td.mkdir()
    env = {"TRACE_DIR": str(td), "TRACE_MIN_FREE_MB": "0"}
    monkeypatch.setattr(TR, "_mask_self_names", lambda t: (_ for _ in ()).throw(ValueError("x")))
    cid = "AAAAAAAA"
    p = _start(td, cid)
    r1 = TR.client_report(cid, "ice_failed", reason=T, detail={"error": T}, env=env)
    assert r1["ok"] is True
    data = p.read_text(encoding="utf-8")
    assert _count(data) == 0 and CR.REDACT_FAIL_PLACEHOLDER in data
    assert _count("\n".join(logs)) == 0


def test_feedback_note_fail_closed(tmp_path, boom):
    td = tmp_path / "t"
    td.mkdir()
    env = {"TRACE_DIR": str(td), "TRACE_MIN_FREE_MB": "0"}
    cid = "BBBBBBBB"
    p = _start(td, cid)
    res = TR.feedback(cid, note=T, env=env)
    assert res.get("ok") is True, res
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["type"] == "feedback" and rows[-1]["note"] == CR.REDACT_FAIL_PLACEHOLDER
    assert _count(p.read_text(encoding="utf-8")) == 0


def _legacy(d, cid):
    rows = [{"type": "start", "call_id": cid, "consent": True},
            {"type": "turn", "call_id": cid, "asr": T, "reply": "嗯"},
            {"type": "feedback", "call_id": cid, "note": T}]
    p = d / f"{cid}.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.utime(p, (1_000_000, 1_000_000))
    return p


def test_backfill_error_masks_whole_field_and_logs_error(tmp_path, capsys, boom):
    d = tmp_path / "traces"
    d.mkdir()
    td = tmp_path / "transcripts"
    td.mkdir()
    a = _legacy(d, "AAAAAAAA")
    tp = td / "20261022-130000-web-AAAAAAAA.json"
    tp.write_text(json.dumps({"transcript": [{"role": "scammer", "text": T}, {"role": "bot", "text": "好"}]},
                             ensure_ascii=False, indent=1), encoding="utf-8")
    os.utime(tp, (1_000_000, 1_000_000))
    assert BF.main(["--dir", str(d), "--transcripts", str(td), "--min-age", "0"]) == 0
    out = capsys.readouterr()
    s = json.loads(out.out)
    assert s["files_changed"] == 1 and s["fields_error"] == 3 and s["transcripts"]["fields_error"] >= 1
    # 盘上没有原文
    assert _count(a.read_text(encoding="utf-8")) == 0 and _count(tp.read_text(encoding="utf-8")) == 0
    rows = [json.loads(x) for x in a.read_text(encoding="utf-8").splitlines()]
    assert rows[1]["asr"] == CR.REDACT_FAIL_PLACEHOLDER and rows[2]["note"] == CR.REDACT_FAIL_PLACEHOLDER
    # #255 结构化改动日志里有 error 条目：带通话编号、字段路径
    recs = [json.loads(x) for x in out.err.splitlines() if x.startswith("{") and BF.CHANGE_EVENT in x]
    errs = {(r["call_id"], r["kind"], f["path"]) for r in recs for f in r["fields"] if f["rules"] == ["error"]}
    assert ("AAAAAAAA", "trace", "turn[1].asr") in errs and ("AAAAAAAA", "trace", "feedback[2].note") in errs
    assert ("AAAAAAAA", "transcript", "transcript[0].text") in errs
    assert _count(out.out + out.err) == 0 and T not in out.err


def test_change_log_whitelist_on_manual_run(tmp_path):
    """#216：手工运行时 stderr 的字段路径 / 编号 / 规则也过同一个白名单。"""
    import io
    buf = io.StringIO()
    BF.log_change(tmp_path / "AAAAAAAA.jsonl", "trace",
                  [{"path": "turn[1].asr", "rules": ["fullname"], "n": 1},
                   {"path": T + "[0].x", "rules": [T], "n": 2}], False, stream=buf)
    BF.log_change(tmp_path / (T[:3] + ".jsonl"), "trace", [{"path": "turn[1].asr", "rules": ["otp"], "n": 1}], False,
                  stream=buf)
    blob = buf.getvalue()
    assert _count(blob) == 0 and T[:3] not in blob
    recs = [json.loads(x) for x in blob.splitlines()]
    assert recs[0]["fields"][0]["path"] == "turn[1].asr" and recs[0]["fields"][1] == {"path": "invalid", "rules": ["invalid"], "n": 2}
    assert recs[1]["call_id"] == "invalid"


def test_backup_tightens_old_tars(tmp_path, capsys):
    """#216：--backup 时旧 backup-*.tar 一并收紧到 0600。"""
    d = tmp_path / "traces"
    d.mkdir()
    bk = d / "backups"
    bk.mkdir()
    old = bk / "backup-20260101-000000.tar"
    old.write_bytes(b"")
    os.chmod(old, 0o644)
    _legacy(d, "AAAAAAAA")
    assert BF.main(["--dir", str(d), "--no-transcripts", "--min-age", "0", "--backup", str(bk / "backup-new.tar")]) == 0
    capsys.readouterr()
    assert (old.stat().st_mode & 0o777) == 0o600
    assert ((bk / "backup-new.tar").stat().st_mode & 0o777) == 0o600
