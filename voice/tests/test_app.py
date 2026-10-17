from fastapi.testclient import TestClient

from voice import app as A


def test_config_and_index():
    c = TestClient(A.create_app("rule"))
    r = c.get("/api/config").json()
    assert r["keyConfigured"] is True and r["engine"] == "rule"
    assert {p["id"] for p in r["personas"]} >= {"wang", "li", "lin"}
    assert "test-key" not in str(r)  # 不回显 key
    html = c.get("/").text
    assert "非官方项目，与 DeepSeek 无关" in html
    assert c.get("/static/voice.js").status_code == 200
    assert c.get("/static/logo.svg").status_code == 200


def test_offer_without_key_is_503(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    c = TestClient(A.create_app())
    r = c.post("/api/offer", json={"sdp": "x", "type": "offer"})
    assert r.status_code == 503 and "DASHSCOPE_API_KEY" in r.json()["detail"]


def test_load_env(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSUCK_TEST_X", raising=False)
    monkeypatch.setattr(A, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("# c\nDEEPSUCK_TEST_X='abc'\n", encoding="utf-8")
    A.load_env()
    import os
    assert os.environ["DEEPSUCK_TEST_X"] == "abc"


def test_main_help(capsys):
    import pytest
    with pytest.raises(SystemExit):
        A.main(["--help"])
    assert "--engine" in capsys.readouterr().out
