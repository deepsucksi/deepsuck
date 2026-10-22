"""#262：eval/llm_scammer.py 的大模型被骗方（--responder llm），只用假客户端，不联网。"""
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("pipecat")
ROOT = Path(__file__).resolve().parents[2]


def _load():
    if "llm_scammer" in sys.modules:
        return sys.modules["llm_scammer"]
    spec = importlib.util.spec_from_file_location("llm_scammer", ROOT / "eval/llm_scammer.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["llm_scammer"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


class Fake:
    """骗子请求带 response_format；第 2 轮提转账，第 3 轮报卡号。被骗方请求返回固定口语回复。"""

    def __init__(self):
        self.scam, self.victim = [], []

    def chat(self, messages, **params):
        if "response_format" not in params:
            self.victim.append((messages, params))
            return {"content": "转账…我这心里有点打鼓。", "usage": {"prompt_tokens": 50, "completion_tokens": 5}}
        self.scam.append(messages)
        k = sum(m["role"] == "assistant" for m in messages) + 1
        card = re.search(r"银行卡：([0-9 ]+)", messages[0]["content"])
        say = {1: "您好，这里是公安局，你涉嫌一个案子。", 2: "你得把钱转账到安全账户。"}.get(
            k, f"安全账户卡号 {card.group(1).strip()}，快点" if card else "快点")
        return {"content": json.dumps({"say": say, "action": "continue"}, ensure_ascii=False),
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def test_llm_victim_uses_persona_prompt_and_counts_account(tmp_path):
    fake = Fake()
    res = M.run(["police"], ["wang"], 1, 4, client_factory=lambda: fake, cache_dir=tmp_path / "c", dry_run=False,
                workers=1, responder="llm")
    r = res["rows"][0]
    assert res["config"]["responder"] == "llm" and res["config"]["victim"]["commit"] is not None
    assert len(fake.victim) == r["botReplies"] == 4
    msgs, params = fake.victim[0]
    assert params["temperature"] == M.VICTIM_TEMPERATURE and params["enable_thinking"] is False
    assert msgs[0]["role"] == "system" and "潜在受害人" in msgs[0]["content"]  # voice/persona.py 的提示词
    assert all("转账…" in m["text"] for m in r["transcript"][2::2] if m["role"] == "bot")
    assert r["transferTurn"] == 1
    kinds = M.SIM.load_scripts("legacy")["scenarios"]["police"]["intel"]
    assert "bank" in kinds
    assert r["accountAfterTransfer"] is True and res["overall"]["accountAfterTransferRate"] == 1.0
    # 同一进程换 root 会报错，避免两份 voice 混用
    with pytest.raises(RuntimeError):
        M.load_victim(tmp_path)


def test_llm_victim_estimate_counts_victim_calls():
    corpus = json.loads(M.SIM.default_corpus_path().read_text(encoding="utf-8"))
    a = M.estimate_session(corpus, "police", "wang", 1000, ["bank"], 5)
    b = M.estimate_session(corpus, "police", "wang", 1000, ["bank"], 5, responder="llm")
    assert b["prompt_tokens"] == a["prompt_tokens"] + 6 * M.EST_VICTIM_PROMPT_TOKENS
