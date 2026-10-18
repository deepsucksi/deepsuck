"""deepsuck.intake：issue 表单 -> 脱敏 -> 去重 -> 黑名单 -> intel.json PR（不联网）。"""
import json
import re
from pathlib import Path

import pytest

from deepsuck import intake

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures" / "intake"
LIB = json.loads((ROOT / "site" / "data" / "intel.json").read_text(encoding="utf-8"))
ISSUE = {"number": 42, "created_at": "2026-10-18T07:00:00Z"}
RAW_SECRETS = ["6222020200112233445", "王小明", "13912342233", "scam.receiver@example.com"]


def body(name):
    return (FIX / f"{name}.md").read_text(encoding="utf-8")


def fake_check(kind, value):
    if kind == "url":
        return {"status": "hit", "how": "parent", "sources": ["destroylist"]} if "pay-secure" in value else {"status": "clean"}
    return {"status": "clean"}


def run(name, lib=LIB, issue=ISSUE, check=fake_check):
    return intake.run(lib, body(name), issue, check=check)


def all_text(out):
    return "\n".join(list(out["files"].values()) + [out["pr_md"], out["comment_md"], json.dumps(out["summary"], ensure_ascii=False)])


# ---------- 模板与解析
def _yml_fields(path):
    """不依赖 PyYAML：按顺序取出 body 里每个字段的 type / id / label。"""
    text = path.read_text(encoding="utf-8")
    out = []
    for block in re.split(r"\n  - type: ", text)[1:]:
        kind = block.split("\n", 1)[0].strip()
        if kind == "markdown":
            continue
        fid = re.search(r"^    id: (\S+)", block, re.M).group(1)
        label = re.search(r"^      label: (.+)$", block, re.M).group(1).strip()
        out.append((fid, label, kind))
    return out


@pytest.mark.parametrize("name", list(intake.FORMS))
def test_form_definitions_match_issue_templates(name):
    assert _yml_fields(ROOT / ".github" / "ISSUE_TEMPLATE" / name) == intake.FORMS[name]


@pytest.mark.parametrize("name", ["intel-intake.yml", "intel-submission.yml"])
def test_templates_carry_trigger_label(name):
    text = (ROOT / ".github" / "ISSUE_TEMPLATE" / name).read_text(encoding="utf-8")
    assert re.search(r'^labels: \[.*"intel-submission".*\]$', text, re.M)


def _norm(v):
    if isinstance(v, str):
        return intake._strip_fence(v).strip()
    return v


@pytest.mark.parametrize("name", sorted(p.stem for p in FIX.glob("*.md")))
def test_parse_matches_issue_ops_parser(name):
    """*.parsed.json 由 issue-ops/parser v5.0.0（带模板）对同一正文实际生成。"""
    tpl = intake.detect_template(body(name))
    assert tpl == ("intel-submission.yml" if name.startswith("legacy") else "intel-intake.yml")
    mine = intake.parse_form(body(name), tpl)
    ref = json.loads((FIX / f"{name}.parsed.json").read_text(encoding="utf-8"))
    for fid, _, kind in intake.FORMS[tpl]:
        default = [] if kind == "dropdown" else ({"selected": [], "unselected": []} if kind == "checkboxes" else "")
        assert mine[fid] == _norm(ref.get(fid, default)), fid


def test_unrecognised_body_gets_help_and_no_pr():
    out = intake.run(LIB, "随便写的内容 6222020200112233445", ISSUE)
    assert not out["changed"] and not out["files"]
    assert "没有识别出" in out["comment_md"]
    assert "6222020200112233445" not in all_text(out)


# ---------- 脱敏、去重、黑名单
def test_bank_card_pci_masked_dedup_and_old_format_rejected():
    out = run("intake-bank")
    lib = json.loads(out["files"]["intel.json"])
    new = [e for e in lib["entries"] if e["id"].startswith("DS-")]
    assert len(new) == 1
    e = new[0]
    assert e["id"] == "DS-2026-0042-1" and e["value"] == "622202*********3445"
    assert (e["issuer"], e["cardType"], e["bank"]) == ("中国工商银行", "借记卡", "工商银行")
    assert e["tactics"] == ["authority", "safe_account"] and e["scenario"] == "police"
    assert e["source"] == "community" and e["status"] == "active" and e["example"] is False
    assert e["tags"] == ["gh-issue-42"]
    assert "王**" in e["notes"] and "139****2233" in e["notes"]
    st = [r["status"] for r in out["summary"]["rows"]]
    assert st == ["added", "skip", "invalid"]
    assert "前 4 后 4" in out["comment_md"]
    assert "6222 02\\*\\* " not in out["comment_md"] and "`` 6222 02** **** ***3 445 ``" in out["comment_md"]  # 展示用分组
    assert out["summary"]["raw_sensitive"] is True and "编辑本 issue" in out["comment_md"]
    assert "未知的话术标签" in out["comment_md"]


@pytest.mark.parametrize("name", ["intake-bank", "intake-url", "intake-account", "legacy-sandbox", "intake-unconfirmed"])
def test_no_raw_sensitive_text_in_any_output(name):
    text = all_text(run(name))
    for s in RAW_SECRETS:
        if name == "legacy-sandbox" and s == "13912342233":
            continue  # 诈骗电话按策略完整公开
        assert s not in text and s not in re.sub(r"[\s-]", "", text)


def test_generated_files_match_repo_format_and_validate():
    out = run("intake-bank")
    lib = json.loads(out["files"]["intel.json"])
    assert intake.build_files(lib) == out["files"]
    assert out["files"]["intel.json"] == json.dumps(lib, ensure_ascii=False, indent=2)
    for e in lib["entries"]:
        assert intake.validate_entry(e) == [], e["id"]
    stix = json.loads(out["files"]["intel.stix.json"])
    assert any("622202_________3445" in o.get("pattern", "") for o in stix["objects"])
    assert "622202*********3445" in out["files"]["intel.csv"]
    assert "DS-2026-0042-1" in out["files"]["intel.rss"]
    assert lib["updatedAt"] == "2026-10-18"


def test_url_defang_blocklist_and_example_duplicate():
    out = run("intake-url")
    rows = out["summary"]["rows"]
    assert [r["status"] for r in rows] == ["added", "example", "invalid"]
    lib = json.loads(out["files"]["intel.json"])
    e = next(x for x in lib["entries"] if x["id"] == "DS-2026-0042-1")
    assert e["value"] == "https://pay-secure-refund.top/dl"
    assert e["confidence"] == "medium" and e["source"] == "sandbox" and e["firstSeen"] == "2026-10-16"
    assert "命中公开黑名单：destroylist（父域名命中）" in out["comment_md"]
    ex = next(x for x in lib["entries"] if x["id"] == "EX-0006")
    assert ex == next(x for x in LIB["entries"] if x["id"] == "EX-0006")  # 示例数据不被改动


def test_account_masked_future_date_corrected():
    out = run("intake-account")
    lib = json.loads(out["files"]["intel.json"])
    new = [e for e in lib["entries"] if e["id"].startswith("DS-")]
    assert [e["value"] for e in new] == ["sc***@example.com"]
    assert new[0]["firstSeen"] == "2026-10-18"
    assert "晚于提交时间" in out["comment_md"]
    assert [r["status"] for r in out["summary"]["rows"]] == ["added", "example"]  # ke******26 = EX-0014


def test_unconfirmed_makes_no_pr():
    out = run("intake-unconfirmed")
    assert not out["changed"] and out["files"] == {} and out["pr_md"] == ""
    assert "没有全部勾选" in out["comment_md"]


def test_legacy_sandbox_template_and_rerun_idempotent():
    out = run("legacy-sandbox")
    lib = json.loads(out["files"]["intel.json"])
    new = {e["type"]: e for e in lib["entries"] if e["id"].startswith("DS-")}
    assert set(new) == {"phone", "bank_card", "crypto_wallet", "name"}
    assert new["crypto_wallet"]["chain"] == "TRON" and new["bank_card"]["bank"] == "工商银行"
    assert new["phone"]["value"] == "13912342233" and new["name"]["value"] == "李**"
    assert "Closes #42" in out["pr_md"]
    # 合并后同一 issue 被编辑重跑：不重复计数
    again = intake.run(lib, body("legacy-sandbox"), ISSUE, check=fake_check)
    assert not again["changed"]
    assert {r["status"] for r in again["summary"]["rows"]} == {"dup-same"}
    # 另一个 issue 报告同一号码：举报次数 +1，tag 追加
    other = intake.run(lib, body("legacy-sandbox"), {"number": 43, "created_at": "2026-10-19T01:00:00Z"}, check=fake_check)
    lib2 = json.loads(other["files"]["intel.json"])
    p = next(e for e in lib2["entries"] if e["type"] == "phone" and e["id"].startswith("DS-"))
    assert p["reports"] == 2 and p["tags"] == ["gh-issue-42", "gh-issue-43"]
    assert len([e for e in lib2["entries"] if e["id"].startswith("DS-")]) == 4


def test_disputed_entry_is_held_for_maintainer():
    lib = json.loads(json.dumps(LIB))
    lib["entries"].append({"id": "DS-2026-0001-1", "example": False, "type": "phone", "value": "13912342233",
                           "scenario": "refund", "firstSeen": "2026-10-01", "source": "community", "status": "disputed"})
    out = intake.run(lib, body("legacy-sandbox"), ISSUE, check=None)
    row = next(r for r in out["summary"]["rows"] if r["type"] == "phone")
    assert row["status"] == "held"


def test_leak_guard_blocks_pr(monkeypatch):
    """即使脱敏环节出错，泄露检查也会阻止 PR，且评论不回显值。"""
    real = intake.normalize_value

    def broken(t, raw, platform=None):
        r = real(t, raw, platform)
        if t == "bank_card" and r.get("raw_sensitive"):
            r = dict(r, value="6222020200112233445")
        return r

    monkeypatch.setattr(intake, "normalize_value", broken)
    monkeypatch.setattr(intake, "validate_entry", lambda e: [])
    out = run("intake-bank")
    assert not out["changed"] and out["files"] == {} and out["summary"]["leak_blocked"]
    assert "6222020200112233445" not in all_text(out)
    assert "泄露检查没有通过" in out["comment_md"]


def test_markdown_injection_is_neutralised():
    b = body("intake-url").replace("对方自称“平台理赔专员”", "@everyone <img src=x> `x` #1")
    out = intake.run(LIB, b, ISSUE, check=None)
    assert "@everyone" not in out["comment_md"] and "<img" not in out["comment_md"]


def test_cli_writes_only_fixed_github_output(tmp_path, monkeypatch):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"action": "opened", "issue": {"number": 42, "created_at": "2026-10-18T07:00:00Z",
                                                          "body": body("intake-bank")}}), encoding="utf-8")
    gh = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    assert intake.main(["process", "--event", str(ev), "--repo", str(ROOT), "--out", str(tmp_path / "o"), "--offline"]) == 0
    assert gh.read_text() == "changed=true\n"
    names = sorted(p.name for p in (tmp_path / "o" / "files").iterdir())
    assert names == ["intel.csv", "intel.json", "intel.rss", "intel.stix.json"]
    for p in (tmp_path / "o").rglob("*"):
        if p.is_file():
            assert "6222020200112233445" not in p.read_text(encoding="utf-8")


@pytest.mark.parametrize("raw,ok,value", [
    ("622202*********3445", True, "622202*********3445"),
    ("6222-0202-0011-2233-445", True, "622202*********3445"),
    ("622202******2233", True, "622202******2233"),
    ("62220202001", True, "*******2001"),
    ("6222 **** **** 1234", False, None),
    ("6222", False, None),
])
def test_normalize_bank_card(raw, ok, value):
    r = intake.normalize_value("bank_card", raw)
    assert r["ok"] is ok
    if ok:
        assert r["value"] == value


def test_issuer_from_masked_prefix_and_length():
    assert intake.issuer_of_masked("622202*********3445")["bank"] == "中国工商银行"
    assert intake.issuer_of_masked("*******2001") is None
