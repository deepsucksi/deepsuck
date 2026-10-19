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
    assert R.main(["score", "--key", keyf, "--judge", "llm", "--judge-api", "sync", "--json", str(res_path)]) == 0
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


# ---------------------------------------------------------------- #164：严格档、缓存计费、Batch
def test_cached_and_batch_pricing():
    assert J.PRICE_CACHED_INPUT_PER_M == 0.1 and J.BATCH_PRICE_FACTOR == 0.5
    full = J.cost_cny(10_000, 1_000)
    assert J.cost_cny(10_000, 1_000, 8_000) == pytest.approx((2_000 * 0.8 + 8_000 * 0.1 + 1_000 * 2.7) / 1e6)
    assert J.cost_cny(10_000, 1_000, 99_999) == pytest.approx((10_000 * 0.1 + 1_000 * 2.7) / 1e6)  # 命中数不超过输入
    assert J.cost_cny(10_000, 1_000, 8_000, batch=True) == pytest.approx(full / 2)              # Batch 半价、无缓存折扣
    assert J.usage_tokens({"prompt_tokens": 9, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 5}}) == (9, 2, 5)
    assert J.usage_tokens({"prompt_tokens": 9, "completion_tokens": 2}) == (9, 2, 0)


def test_strict_profile_prompt_and_cache_key():
    assert "扣分" in J.SYSTEM_PROMPT_STRICT and "复读" in J.SYSTEM_PROMPT_STRICT and "过于配合" in J.SYSTEM_PROMPT_STRICT
    b = [{"id": "A001", "scammer": "s", "reply": "r"}]
    p = J.request_params(b)
    assert p["enable_thinking"] is False
    assert J.cache_key(b, p, "item", "strict") != J.cache_key(b, p, "item", "default")
    assert J.cache_key(b, p, "item") == J.cache_key(b, p, "item", "default")  # 默认档的旧缓存仍可命中
    m = J.messages_for(b, "item", "strict")
    assert m[0] == {"role": "system", "content": J.SYSTEM_PROMPT_STRICT}  # 固定提示词在最前面
    with pytest.raises(ValueError):
        J.run_judge({}, {"A": []}, profile="strict", mode="batch")


class FakeBatchClient(FakeClient):
    """模拟百炼 Batch：上传 → 创建 → 前 pending_polls 次查询 in_progress → completed；第 fail_index 行返回错误。"""

    def __init__(self, pending_polls=1, fail_index=None):
        super().__init__()
        self.uploads, self.creates, self.polls = [], 0, 0
        self.pending_polls, self.fail_index = pending_polls, fail_index

    def upload_batch_file(self, data, filename="x.jsonl"):
        self.uploads.append([json.loads(x) for x in data.decode("utf-8").splitlines()])
        return "file-1"

    def create_batch(self, fid, metadata=None):
        self.creates += 1
        return {"id": "batch-1", "status": "validating"}

    def get_batch(self, bid):
        self.polls += 1
        if self.polls <= self.pending_polls:
            return {"id": bid, "status": "in_progress"}
        return {"id": bid, "status": "completed", "output_file_id": "out-1"}

    def file_content(self, fid):
        out = []
        for i, line in enumerate(self.uploads[-1]):
            if i == self.fail_index:
                out.append({"custom_id": line["custom_id"], "response": {"status_code": 400, "body": {}}, "error": {"code": "x"}})
                continue
            r = self.chat(line["body"]["messages"], **{k: v for k, v in line["body"].items() if k != "messages"})
            out.append({"custom_id": line["custom_id"], "response": {"status_code": 200, "request_id": "rq", "body": {
                "model": "qwen3.8-flash", "usage": r["usage"], "choices": [{"message": {"content": r["content"]}}]}},
                "error": None})
        return "\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n"


def test_batch_api_half_price_cache_and_resume(tmp_path):
    key, forms = _data(6)
    fake = FakeBatchClient(pending_polls=2, fail_index=0)
    out = J.run_judge(key, forms, lambda: fake, n_pairs=6, cache_dir=tmp_path, profile="strict", api="batch",
                      batch_poll=0, sleep=lambda s: None)
    lines = fake.uploads[0]
    assert fake.creates == 1 and len(lines) == 12
    body = lines[0]["body"]
    assert body["enable_thinking"] is False and body["model"] == "qwen3.8-flash"  # 顶层参数，不在 extra_body 里
    assert body["messages"][0]["content"] == J.SYSTEM_PROMPT_STRICT
    assert out["usage"]["requests"] == 11 and out["invalid_items"] == 1           # 失败行不计费、记无效
    assert out["usage"]["cost_cny"] == pytest.approx(J.cost_cny(1100, 220) / 2, abs=1e-6)
    assert out["usage"]["cached_tokens"] == 0 and out["api"] == "batch"
    # 再跑：成功的 11 题走本地缓存，只把失败的 1 题重新提交
    fake2 = FakeBatchClient(pending_polls=0)
    again = J.run_judge(key, forms, lambda: fake2, n_pairs=6, cache_dir=tmp_path, profile="strict", api="batch",
                        batch_poll=0, sleep=lambda s: None)
    assert len(fake2.uploads[0]) == 1 and again["usage"]["cached_requests"] == 11 and again["invalid_items"] == 0


def test_batch_timeout_then_resume_without_resubmitting(tmp_path):
    fake = FakeBatchClient(pending_polls=10**6)
    clock = iter(range(0, 10**6, 100))
    with pytest.raises(J.BatchPending):
        J._batch_results(fake, [("a", [{"role": "user", "content": "诈骗消息：转账\n回复：好的"}], {"model": "m"})], tmp_path, 250, 0,
                         lambda s: None, sleep=lambda s: None, clock=lambda: next(clock))
    assert fake.creates == 1
    fake.pending_polls = 0
    fake.polls = 0
    res = J._batch_results(fake, [("a", [{"role": "user", "content": "诈骗消息：转账\n回复：好的"}], {"model": "m"})], tmp_path, 250, 0,
                           lambda s: None, sleep=lambda s: None)
    assert fake.creates == 1 and "a" in res  # 同一份输入接着等同一任务，没有重复提交


def test_batch_budget_refuses_before_upload(tmp_path, monkeypatch):
    key, forms = _data(6)
    monkeypatch.setattr(J, "PRICE_INPUT_PER_M", 100000.0)

    def factory():
        raise AssertionError("must not create a client")
    with pytest.raises(J.BudgetError):
        J.run_judge(key, forms, factory, cache_dir=tmp_path, api="batch")


def test_sync_records_cached_tokens(tmp_path):
    key, forms = _data(2)

    class Cached(FakeClient):
        def chat(self, messages, **params):
            r = super().chat(messages, **params)
            r["usage"] = {"prompt_tokens": 2000, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 1536}}
            return r
    out = J.run_judge(key, forms, Cached, n_pairs=2, cache_dir=tmp_path, api="sync")
    assert out["usage"]["cached_tokens"] == 1536 * 4
    assert out["usage"]["cost_cny"] == pytest.approx(4 * J.cost_cny(2000, 20, 1536), abs=1e-6)


def test_batch_fallback_cancels_and_goes_sync(tmp_path):
    """#164：Batch 太慢时（--batch-fallback）取消该任务、删掉本地任务号、逐题走同步接口，不会同一批题计两次费。"""
    key, forms = _data(4)
    fake = FakeBatchClient(pending_polls=10**6)
    fake.cancelled = []
    fake.cancel_batch = lambda bid: fake.cancelled.append(bid) or {"id": bid, "status": "cancelling"}
    out = J.run_judge(key, forms, lambda: fake, n_pairs=4, cache_dir=tmp_path, profile="strict", api="batch",
                      batch_timeout=-1, batch_poll=0, sleep=lambda s: None, batch_fallback=True)
    assert fake.creates == 1 and fake.cancelled == ["batch-1"]
    assert not list((tmp_path / "batches").glob("*.json"))
    assert out["usage"]["requests"] == 8 and out["invalid_items"] == 0 and out.get("batch_fallback")
    assert out["usage"]["cost_cny"] == pytest.approx(J.cost_cny(800, 160), abs=1e-6)  # 同步价，不是半价


def test_strict_prompt_lists_all_deductions_and_clears_cache_threshold():
    p = J.SYSTEM_PROMPT_STRICT
    for w in ("太书面", "太长", "复读", "过于配合", "自相矛盾", "答非所问", "露信息", "别扭", "不要扎堆给满分"):
        assert w in p
    assert J.PROMPT_VERSION_STRICT == "judge-strict-v2"
    assert len(p) > 1600  # 百炼隐式缓存要求公共前缀 ≥1024 token（实测 v2 约 1130 token）


def test_sync_workers_same_result_and_billing(tmp_path):
    key, forms = _data(6)
    a = J.run_judge(key, forms, lambda: FakeClient(), n_pairs=6, cache_dir=tmp_path / "a", profile="strict")
    b = J.run_judge(key, forms, lambda: FakeClient(), n_pairs=6, cache_dir=tmp_path / "b", profile="strict", workers=4)
    assert a["judgments"] == b["judgments"]
    assert b["usage"]["requests"] == 12 and b["usage"]["cached_requests"] == 0
    assert a["usage"]["cost_cny"] == pytest.approx(b["usage"]["cost_cny"])
