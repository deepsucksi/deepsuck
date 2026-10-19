"""#92 历史追踪重新脱敏：只改已同意通话、只改命中的数字、可重复执行、保留修改时间、输出只有计数。"""
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
    assert s["files_scanned"] == 6 and s["consented"] == 3 and s["skipped_not_consented"] == 2
    assert s["skipped_unknown_consent"] == 1
    assert s["files_changed"] == 2 and s["rows_changed"] == 4 and s["fields_changed"] == 4
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before          # dry-run 不改
    assert "验证码" not in out and "AAAAAAAA" not in out

    bk = tmp_path / "bk.tar"
    assert BF.main(["--dir", str(d), "--min-age", "0", "--backup", str(bk)]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["files_changed"] == 2 and s["rows_changed"] == 4 and s["backup_files"] == 2
    assert oct(os.stat(bk).st_mode & 0o777) == "0o600"
    with tarfile.open(bk) as tf:
        assert sorted(tf.getnames()) == ["AAAAAAAA.jsonl", "DDDDDDDD.jsonl"]
    rows = [json.loads(x) for x in (d / "AAAAAAAA.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["asr"] for r in rows if r["type"] == "turn"] == ["验证码是 **", "** **", "那你先转 3000 元"]
    a = os.stat(d / "AAAAAAAA.jsonl")
    assert a.st_mtime == 1_000_000 and oct(a.st_mode & 0o777) == "0o600"
    for n in ("BBBBBBBB.jsonl", "CCCCCCCC.jsonl", "EEEEEEEE.jsonl", "FFFFFFFF.jsonl"):
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
