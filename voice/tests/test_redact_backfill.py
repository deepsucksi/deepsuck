"""#92 历史追踪重新脱敏：只改已同意通话和电话线路（#254）、只改命中的数字、可重复执行、保留修改时间、输出只有计数。"""
import json
import os
import tarfile

from voice import redact_backfill as BF


def _w(p, rows, mtime=1_000_000):
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.chmod(p, 0o600)
    os.utime(p, (mtime, mtime))


def _call(consent, asr=("验证码是 38", "27 15", "那你先转 3000 元"), v1=False):
    sv = {} if v1 else {"schema_version": 2, "call_id": "AAAAAAAA"}
    rows = [{**sv, "type": "start", "consent": consent}, {**sv, "type": "bot", "kind": "opening", "text": "喂"}]
    rows += [{**sv, "type": "turn", "turn": i, "asr": a, "reply": "嗯", "consent": consent} for i, a in enumerate(asr, 1)]
    rows.append({**sv, "type": "end", "consent": consent})
    return rows


def test_dry_run_counts_then_rewrites_consented_only(tmp_path, capsys):
    d = tmp_path / "traces"
    d.mkdir()
    _w(d / "AAAAAAAA.jsonl", _call(True))
    _w(d / "BBBBBBBB.jsonl", _call(False))
    _w(d / "CCCCCCCC.jsonl", _call("sip-text-only"))
    _w(d / "DDDDDDDD.jsonl", _call(True, v1=True))
    _w(d / "EEEEEEEE.jsonl", _call(True, asr=("验证码收到了吧", "金额 5000", "下午 3 点")))
    (d / "FFFFFFFF.jsonl").write_text('{"type": "turn", "asr": "验证码 38"}\nnot json\n', encoding="utf-8")
    before = {p.name: p.read_bytes() for p in d.iterdir()}

    assert BF.main(["--dir", str(d), "--dry-run", "--min-age", "0"]) == 0
    out = capsys.readouterr().out
    s = json.loads(out)
    assert s["files_scanned"] == 6 and s["consented"] == 4 and s["sip"] == 1 and s["skipped_not_consented"] == 1
    assert s["skipped_unknown_consent"] == 1
    assert s["files_changed"] == 3 and s["rows_changed"] == 6 and s["fields_changed"] == 6
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before          # dry-run 不改
    assert "验证码" not in out and "AAAAAAAA" not in out

    bk = tmp_path / "bk.tar"
    assert BF.main(["--dir", str(d), "--min-age", "0", "--backup", str(bk)]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["files_changed"] == 3 and s["rows_changed"] == 6 and s["backup_files"] == 3
    assert oct(os.stat(bk).st_mode & 0o777) == "0o600"
    with tarfile.open(bk) as tf:
        assert sorted(tf.getnames()) == ["AAAAAAAA.jsonl", "CCCCCCCC.jsonl", "DDDDDDDD.jsonl"]
    rows = [json.loads(x) for x in (d / "AAAAAAAA.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["asr"] for r in rows if r["type"] == "turn"] == ["验证码是 **", "** **", "那你先转 3000 元"]
    a = os.stat(d / "AAAAAAAA.jsonl")
    assert a.st_mtime == 1_000_000 and oct(a.st_mode & 0o777) == "0o600"
    for n in ("BBBBBBBB.jsonl", "EEEEEEEE.jsonl", "FFFFFFFF.jsonl"):
        assert (d / n).read_bytes() == before[n]                              # 未同意 / 无改动 / 判断不了：原样
    # 未改动的行字节不变
    old = before["AAAAAAAA.jsonl"].decode().splitlines()
    new = (d / "AAAAAAAA.jsonl").read_text(encoding="utf-8").splitlines()
    assert old[0] == new[0] and old[1] == new[1] and old[-1] == new[-1] and old[4] == new[4]

    # 可重复执行：第二次什么都不改
    assert BF.main(["--dir", str(d), "--min-age", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["files_changed"] == 0


def test_recent_files_skipped_and_missing_dir(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    p = d / "AAAAAAAA.jsonl"
    _w(p, _call(True), mtime=2_000_000)
    s = BF.run(d, dry_run=False, min_age=600, now=2_000_100)
    assert s["skipped_recent"] == 1 and s["files_changed"] == 0
    assert BF.run(tmp_path / "nope")["dir_exists"] is False


def test_persona_and_scammer_joined_for_otp():
    """#120：跨段窗口覆盖两边说话人——骗子问验证码、人设下一句报数字；人设侧连续 3 位以上数字兜底。"""
    rows = [{"type": "start", "consent": True}, {"type": "turn", "asr": "把验证码念一下", "reply": "嗯…四七"},
            {"type": "turn", "asr": "还有呢", "reply": "二九"},
            {"type": "turn", "asr": "先转 300 元", "filler": "嗯…验证码是472？", "reply": "好，下午三点"}]
    new, n, f = BF.redact_rows(rows)
    assert [r.get("reply") for r in new[1:]] == ["嗯…**", "**", "好，下午三点"]
    assert new[3]["filler"] == "嗯…验证码是***？" and new[3]["asr"] == "先转 300 元"
    assert n == 3 and f == 3
    assert BF.redact_rows(new)[1] == 0


def test_bot_rows_and_card_fragments():
    rows = [{"type": "bot", "kind": "opening", "text": "喂，你好"},
            {"type": "turn", "asr": "卡号 6222 开头", "reply": "6222开头…尾号0123对吧"},
            {"type": "turn", "asr": "我是 138 开头的号码", "reply": "138开头…后面是零零幺三"}]
    new, n, _ = BF.redact_rows(rows)
    assert new[1]["asr"] == "卡号 **** 开头" and new[1]["reply"] == "****开头…尾号****对吧"
    assert new[2]["asr"] == "我是 138 开头的号码" and new[2]["reply"] == "***开头…后面是****"
    assert new[0] == rows[0] and n == 2


# ---------------- 文字记录（#125） ----------------
def _tdoc():
    return {"schema": "deepsuck.report/v1", "channel": "web", "intel": [{"type": "bank_card", "masked": "622202*********3445"}],
            "transcript": [{"role": "scammer", "text": "验证码收到没有", "at": 0, "intent": None, "tactics": []},
                           {"role": "bot", "text": "嗯…验证码是472？", "at": 1, "intent": "otp_stall", "tactics": []},
                           {"role": "scammer", "text": "我是 138 开头的号码，先转 300 元", "at": 2, "intent": None, "tactics": []},
                           {"role": "bot", "text": "138开头…后面是零零幺三", "at": 3, "intent": "generic", "tactics": []},
                           {"role": "bot", "text": "我只有五百块，三点半到", "at": 4, "intent": "generic", "tactics": []}]}


def _wj(p, doc, mtime=1_000_000):
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(p, 0o600)
    os.utime(p, (mtime, mtime))


def test_transcripts_dry_run_backup_rewrite_and_idempotent(tmp_path):
    tr, td = tmp_path / "traces", tmp_path / "transcripts"
    tr.mkdir()
    td.mkdir()
    _wj(td / "20261019-114231-web-AAAAAAAA.json", _tdoc())
    _wj(td / "20261019-114232-web-BBBBBBBB.json", {"transcript": [{"role": "scammer", "text": "你好"}]})
    (td / "20261019-114233-web-CCCCCCCC.json").write_text("{坏", encoding="utf-8")
    os.utime(td / "20261019-114233-web-CCCCCCCC.json", (1_000_000, 1_000_000))
    _wj(td / "20261019-114234-web-DDDDDDDD.json", _tdoc(), mtime=2_000_000)   # 太新，跳过
    s = BF.run(tr, dry_run=True, transcripts=td, now=2_000_100)
    t = s["transcripts"]
    assert (t["files_scanned"], t["files_changed"], t["fields_changed"], t["skipped_bad"], t["skipped_recent"]) == (4, 1, 2, 1, 1)
    assert json.loads((td / "20261019-114231-web-AAAAAAAA.json").read_text(encoding="utf-8")) == _tdoc()
    bak = tmp_path / "bak.tar"
    s = BF.run(tr, dry_run=False, transcripts=td, backup=bak, now=2_000_100)
    assert s["transcripts"]["files_changed"] == 1 and s["backup_files"] == 1
    with tarfile.open(bak) as tf:
        assert tf.getnames() == ["transcripts/20261019-114231-web-AAAAAAAA.json"]
    p = td / "20261019-114231-web-AAAAAAAA.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert [m["text"] for m in d["transcript"]] == ["验证码收到没有", "嗯…验证码是***？", "我是 138 开头的号码，先转 300 元",
                                                   "***开头…后面是****", "我只有五百块，三点半到"]
    assert d["intel"] == _tdoc()["intel"] and d["channel"] == "web"
    assert p.stat().st_mtime == 1_000_000 and oct(p.stat().st_mode & 0o777) == "0o600"
    assert p.read_text(encoding="utf-8") == json.dumps(d, ensure_ascii=False, indent=1)
    assert BF.run(tr, dry_run=True, transcripts=td, now=2_000_100)["transcripts"]["fields_changed"] == 0


def test_transcripts_same_rule_as_trace():
    from deepsuck.redact import redact_dialog_segments
    doc = _tdoc()
    new, n = BF.redact_transcript(doc)
    msgs = doc["transcript"]
    assert [m["text"] for m in new["transcript"]] == redact_dialog_segments([m["text"] for m in msgs], [m["role"] for m in msgs])
    assert n == 2 and BF.redact_transcript({"x": 1}) == ({"x": 1}, 0)


def test_main_reports_transcripts_and_can_skip(tmp_path, capsys):
    tr, td = tmp_path / "traces", tmp_path / "transcripts"
    tr.mkdir()
    td.mkdir()
    _wj(td / "a.json", _tdoc())
    assert BF.main(["--dir", str(tr), "--transcripts", str(td), "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["transcripts"]["fields_changed"] == 2 and "472" not in json.dumps(out)
    assert BF.main(["--dir", str(tr), "--no-transcripts", "--dry-run"]) == 0
    assert "transcripts" not in json.loads(capsys.readouterr().out)
