"""voice.probe 的退出码语义（不联网：run() 用假结果替换）。"""
import json

import pytest

from voice import probe

OK = {"offer_status": 200, "connected_after": 0.7, "bot_audio_sec": 12.0, "events": [{"type": "bot"}]}


@pytest.mark.parametrize("st,code", [
    (OK, 0),
    # aiortc 漏报 connectionstatechange（connected_after 为空）但音频、数据都到了：旧实现在这里返回 1
    ({**OK, "connected_after": None}, 0),
    ({"offer_status": 403, "error": {"error": "origin"}}, 2),
    ({"offer_status": 200, "connected_after": None, "bot_audio_sec": 0.0, "events": []}, 3),
    ({"offer_status": 200, "connected_after": 0.5, "bot_audio_sec": 0.0, "events": []}, 4),
])
def test_exit_code(st, code):
    assert probe.exit_code(st) == code


def _fake_run(st):
    async def run(*a, **k):
        return dict(st)
    return run


def test_main_prints_exit_reason_and_returns_code(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(probe, "run", _fake_run({**OK, "connected_after": None}))
    out = tmp_path / "p.json"
    assert probe.main(["--json-out", str(out)]) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["exit"] == 0 and summary["exit_reason"] == "ok"
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["exit"] == 0


def test_main_json_out_failure_is_exit_5_but_summary_still_printed(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(probe, "run", _fake_run(OK))
    assert probe.main(["--json-out", str(tmp_path / "no-such-dir" / "p.json")]) == 5
    cap = capsys.readouterr()
    assert json.loads(cap.out.strip().splitlines()[-1])["exit_reason"] == "json_out_failed"
    assert "json-out" in cap.err


def test_main_offer_rejected(monkeypatch, capsys):
    monkeypatch.setattr(probe, "run", _fake_run({"offer_status": 503, "error": {}}))
    assert probe.main([]) == 2
    assert "offer_rejected" in capsys.readouterr().err


def test_help_documents_exit_codes(capsys):
    with pytest.raises(SystemExit):
        probe.main(["--help"])
    out = capsys.readouterr().out
    assert "退出码" in out and "media_not_connected" not in out and "ICE" in out
