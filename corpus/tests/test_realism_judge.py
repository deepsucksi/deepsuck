"""大模型评委：只用假客户端，不联网。"""
import csv
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("realism_blind", "eval/realism_blind.py")
J = _load("realism_judge", "eval/realism_judge.py")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


class FakeClient:
    """按回复长度给分：带标点结尾判机器人，其余判真人；记录每次请求。"""

    def __init__(self, bad_ids=()):
        self.calls = []
        self.bad_ids = set(bad_ids)

    def chat(self, messages, **params):
        self.calls.append((messages, params))
        user = messages[-1]["content"]
        if not user.lstrip().startswith("共"):  # 逐题模式：只有一道题，没有题号
            reply = user.strip().splitlines()[-1].split("：", 1)[1]
            bot = 1 if reply and reply[-1] in "。！？" else 0
            d = {"bot": bot, "human": 2 if bot else 4, "unreadable": 0, "reason": "测试"}
            if any(b in reply for b in self.bad_ids):
                d["human"] = 9
            return {"content": json.dumps(d, ensure_ascii=False),
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "model": params["model"]}
        items = []
        for block in user.split("\n\n"):
            lines = block.strip().splitlines()
            if not lines or not lines[0].startswith("["):
                continue
            qid = lines[0].strip("[]")
            reply = lines[-1].split("：", 1)[1]
            bot = 1 if reply and reply[-1] in "。！？" else 0
            item = {"id": qid, "bot": bot, "human": 2 if bot else 4, "unreadable": 0, "reason": "测试"}
            if qid in self.bad_ids:
                item["human"] = 9
            items.append(item)
        return {"content": json.dumps({"items": items}, ensure_ascii=False),
                "usage": {"prompt_tokens": 1000, "completion_tokens": 200}, "model": params["model"]}


def _data(n=12, seed=1):
    data = R.make(n, seed=seed)
    forms = {f: [{"id": r["id"], "scammer": r["scammer"], "reply": r["reply"]} for r in rows]
             for f, rows in data["forms"].items()}
    return data["key"], forms


def test_selects_whole_pairs_and_batches_within_one_form():
    key, forms = _data(12)
    items = J.select_items(key, forms, n_pairs=5)
    assert len(items["A"]) == len(items["B"]) == 5
    assert {key[r["id"]]["pair"] for r in items["A"]} == {key[r["id"]]["pair"] for r in items["B"]} == set(range(5))
    batches = J.make_batches(items, batch_size=3)
    assert [len(b) for b in batches] == [3, 2, 3, 2]
    for b in batches:
        assert len({x["id"][0] for x in b}) == 1  # 同一批只来自一份表，不会同时看到同一句的两个版本


def test_request_params_are_deterministic_json():
    key, forms = _data(4)
    b = J.make_batches(J.select_items(key, forms, 4), 10)[0]
    p = J.request_params(b, seed=1)
    assert p["temperature"] == 0 and p["seed"] == 1 and p["model"] == "qwen3.8-flash"
    assert p["response_format"] == {"type": "json_object"} and p["enable_thinking"] is False
    m = J.messages_for(b)
    assert "JSON" in m[0]["content"]
    for x in b:  # 评委看到的和评测者一样：骗子消息 + 回复，没有条件信息
        assert x["id"] in m[1]["content"] and x["reply"] in m[1]["content"]
    assert "raw" not in m[1]["content"] and "humanized" not in m[1]["content"]


def test_run_scores_with_shared_summary_and_caches(tmp_path):
    key, forms = _data(12)
    fake = FakeClient()
    out = J.run_judge(key, forms, lambda: fake, n_pairs=12, batch_size=5, cache_dir=tmp_path, mode="batch")
    assert len(fake.calls) == 6 and out["usage"]["requests"] == 6
    assert out["usage"]["prompt_tokens"] == 6000 and out["usage"]["completion_tokens"] == 1200
    assert out["usage"]["cost_cny"] == pytest.approx(6000 * 0.8e-6 + 1200 * 2.7e-6)
    assert len(out["ratings"]) == 24 and out["invalid_items"] == 0
    assert set(out["ratings"][0]) == {"id", "rater", "human", "bot", "unreadable"}
    res = R.score(key, out["ratings"])  # 与人工评测同一个汇总函数
    assert set(res["conditions"]) == {"raw", "humanized"}
    assert res["detected_diff_humanized_minus_raw"]["pairs"] == 12
    # 重跑全部命中缓存：不再调用，也不计费
    fake2 = FakeClient()
    again = J.run_judge(key, forms, lambda: fake2, n_pairs=12, batch_size=5, cache_dir=tmp_path, mode="batch")
    assert fake2.calls == [] and again["usage"]["cost_cny"] == 0 and again["usage"]["cached_requests"] == 6
    assert again["estimate"]["cost_cny"] == 0 and again["ratings"] == out["ratings"]
    # 换种子就是新的请求
    fake3 = FakeClient()
    J.run_judge(key, forms, lambda: fake3, n_pairs=12, batch_size=5, seed=2, cache_dir=tmp_path, mode="batch")
    assert len(fake3.calls) == 6


def test_budget_refuses_before_any_call(tmp_path, monkeypatch):
    key, forms = _data(12)
    called = []
    monkeypatch.setattr(J, "PRICE_INPUT_PER_M", 100000.0)
    with pytest.raises(J.BudgetError):
        J.run_judge(key, forms, lambda: called.append(1), cache_dir=tmp_path)
    assert called == [] and not any(tmp_path.iterdir())


def test_max_cost_cannot_exceed_one_yuan(tmp_path, monkeypatch):
    key, forms = _data(12)
    tokens = J.run_judge(key, forms, None, dry_run=True, cache_dir=tmp_path)["estimate"]["prompt_tokens"]
    monkeypatch.setattr(J, "PRICE_INPUT_PER_M", 2.0 * 1e6 / tokens)  # 估算约 2 元
    fake = FakeClient()
    with pytest.raises(J.BudgetError, match="上限 1.0 元"):  # --max-cost 100 也被压到 1 元
        J.run_judge(key, forms, lambda: fake, max_cost=100, cache_dir=tmp_path)
    assert fake.calls == []


def test_default_60_pairs_estimate_is_cheap(tmp_path):
    key, forms = _data(60)
    out = J.run_judge(key, forms, None, dry_run=True, cache_dir=tmp_path)
    est = out["estimate"]
    assert est["mode"] == "item" and est["items"] == 120 and est["batches"] == 120  # 默认逐题：一题一次请求
    assert 0 < est["cost_cny"] < 0.1 and out["ratings"] == [] and not any(tmp_path.iterdir())
    est_b = J.run_judge(key, forms, None, dry_run=True, cache_dir=tmp_path, mode="batch")["estimate"]
    assert est_b["batches"] == 12 and est_b["cost_cny"] < est["cost_cny"]


def test_invalid_items_are_dropped(tmp_path):
    key, forms = _data(4)
    bad = forms["A"][0]["id"]
    out = J.run_judge(key, forms, lambda: FakeClient(bad_ids=[bad]), cache_dir=tmp_path, mode="batch")
    assert out["invalid_items"] == 1 and bad not in out["judgments"]
    out = J.run_judge(key, forms, lambda: FakeClient(bad_ids=[forms["A"][0]["reply"]]), cache_dir=tmp_path / "i")
    assert out["invalid_items"] >= 1 and forms["A"][0]["id"] not in out["judgments"]
    assert J.parse_judgments("not json", [{"id": "A001"}]) == {}
    assert J.parse_judgments('{"items":[{"id":"X9","bot":1,"human":2}]}', [{"id": "A001"}]) == {}


def test_api_key_lookup_never_leaks(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("# c\nDASHSCOPE_API_KEY='sk-test-123'\n", encoding="utf-8")
    assert J.load_api_key([env]) == "sk-test-123"
    assert J.load_api_key([tmp_path / "missing"]) is None
    c = J.DashScopeClient("sk-test-123")
    assert "sk-test" not in repr(c)
    assert "sk-test" not in capsys.readouterr().out


def test_cli_default_off_and_llm_with_fake_client(tmp_path, monkeypatch, capsys):
    assert R.main(["make", "--n", "6", "--seed", "1", "--out-dir", str(tmp_path)]) == 0
    capsys.readouterr()
    keyf = str(tmp_path / "key.json")
    with pytest.raises(SystemExit):  # 默认关闭：没有评分表也没有 --judge llm 就报错，不会调用
        R.main(["score", "--key", keyf])
    fake = FakeClient()
    monkeypatch.setattr(J, "default_client_factory", lambda *a, **k: (lambda: fake))
    monkeypatch.setattr(J, "CACHE_DIR", tmp_path / "cache")
    assert R.main(["score", "--key", keyf, "--judge", "llm", "--dry-run"]) == 0
    assert fake.calls == []
    res_path = tmp_path / "judge.json"
    assert R.main(["score", "--key", keyf, "--judge", "llm", "--json", str(res_path)]) == 0
    res = json.loads(res_path.read_text(encoding="utf-8"))["llm_judge"]
    assert len(fake.calls) == 12 and res["items"] == 12 and res["mode"] == "item" and "代理指标" in res["note"]
    assert set(res["score"]["conditions"]) == {"raw", "humanized"}
    with open(tmp_path / "judge-llm.csv", encoding="utf-8-sig") as f:
        assert len(list(csv.DictReader(f))) == 12


def test_cli_missing_key_does_not_run(tmp_path, monkeypatch, capsys):
    assert R.main(["make", "--n", "4", "--seed", "1", "--out-dir", str(tmp_path)]) == 0
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(J, "ROOT", tmp_path)
    monkeypatch.setattr(J, "load_api_key", lambda env_files=None: None)
    monkeypatch.setattr(J, "CACHE_DIR", tmp_path / "cache")
    assert R.main(["score", "--key", str(tmp_path / "key.json"), "--judge", "llm"]) == 3
    assert "DASHSCOPE_API_KEY" in capsys.readouterr().err


def test_item_mode_sees_one_item_only(tmp_path):
    """逐题模式：每次请求只有一道题，不带题号，看不到同一份表的其他题；缓存与批量模式分开。"""
    key, forms = _data(6)
    fake = FakeClient()
    out = J.run_judge(key, forms, lambda: fake, n_pairs=6, cache_dir=tmp_path)
    assert out["mode"] == "item" and len(fake.calls) == 12 and len(out["ratings"]) == 12
    all_replies = [r["reply"] for rows in forms.values() for r in rows]
    for messages, params in fake.calls:
        user = messages[-1]["content"]
        assert messages[0]["content"] == J.SYSTEM_PROMPT_ITEM and "items" not in messages[0]["content"]
        assert not any(r["id"] in user for rows in forms.values() for r in rows)
        # 拆成几条发的回复在题面上用“／”连成一行（realism_judge 的单行化函数）
        assert sum(1 for x in set(all_replies) if "回复：" + " ／ ".join(y.strip() for y in x.splitlines() if y.strip()) + "\n" in user) == 1
        assert params["max_tokens"] == J.OUT_TOKENS_OVERHEAD + J.OUT_TOKENS_PER_ITEM
    assert J.parse_judgments('{"bot": 1, "human": 2, "unreadable": 0}', [{"id": "B007"}])["B007"]["bot"] == 1
    fake_b = FakeClient()
    J.run_judge(key, forms, lambda: fake_b, n_pairs=6, cache_dir=tmp_path, mode="batch")
    assert len(fake_b.calls) == 2  # 不同模式不共用缓存
    with pytest.raises(ValueError):
        J.run_judge(key, forms, None, dry_run=True, cache_dir=tmp_path, mode="x")
