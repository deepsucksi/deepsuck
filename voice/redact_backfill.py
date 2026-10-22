"""用当前共享脱敏规则重新脱敏历史通话追踪（#92：跨 ASR 分段的验证码）。可重复执行。

#252：每个文字字段先过 voice.records.redact_line（与实时推送 / 存盘 / trace 写盘同一入口）；--call 只处理指定通话。
只处理存了文字的通话：start 行（没有时看 end 行）的 consent 恰为 true，或电话线路（"sip-text-only"，#254：
电话 trace 本来就存脱敏文字，与网页同一规则回填）。未同意（false）、判断不了的文件一律不改。格式见 docs/TRACE_SCHEMA.md（v1 / v2 都认）。

做法：对方（turn.asr）、人设（bot.text、turn.filler、turn.reply）各按文件里的先后顺序当作同一说话方的连续分段，
过一遍 deepsuck.redact.redact_otp_segments（只把命中的数字换成 *，长度不变；已打码的不会再变）。
只重写有改动的行，其余行原样保留；写临时文件（0600）后原子替换，保留原文件的修改时间（保留期按修改时间算）。
最近 --min-age 秒内改过、或处理期间被追加的文件（通话可能还在进行）跳过，下次再跑。

文字记录（#125）：DATA_DIR/voice/transcripts/*.json（voice/records.py 写的 Session.report()）的 transcript[].text
按时间排、带说话方（scammer / bot）过同一套 redact_dialog_segments，与 trace 同一标准；只改有改动的文件，
按原格式（indent=1）原子重写、0600、保留修改时间；--backup 时一起打进同一个 tar（路径前缀 transcripts/）。
计数放在输出 JSON 的 transcripts 下；--no-transcripts 只处理 trace。

stdout 只有计数（JSON），绝不打印任何文字内容或通话编号；stderr 的改动日志（#254）带通话编号，仍不含任何文字。
#254：每个（dry-run 时会）改动的文件往 stderr 写一行结构化日志（event=redact_backfill.change：通话编号、trace / transcript、
字段路径如 turn[3].asr、规则类别如 split-surname / fullname / phone / otp / dialog-digits、改动处数），不含原文或改后文本。
--backup 的文件已存在时输出 {"error": "backup_exists"} 并以 3 退出，不改任何文件（#216）。

    python -m voice.redact_backfill --dry-run          # 只统计会改多少
    python -m voice.redact_backfill --dry-run --call YA6PUTCA --call JT6UMS4K   # #252：只处理指定通话
    python -m voice.redact_backfill                    # 正式改写
    python -m voice.redact_backfill --dir /traces --backup /traces/backup-<时间>.tar   # 改写前把要改的文件打包（0600）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from deepsuck.redact import redact_dialog_segments  # noqa: E402



def consent_of(rows: List[Optional[dict]]):
    """start 行的 consent；没有 start 行时看 end 行；都没有返回 None。"""
    for typ in ("start", "end"):
        for r in rows:
            if isinstance(r, dict) and r.get("type") == typ and "consent" in r:
                return r.get("consent")
    return None


# ---------------------------------------------------------------- #254 结构化改动日志
# 每个（会）改动的文件一条 JSON（stderr，event=redact_backfill.change）：通话编号、文件类别、字段路径、规则类别、改动处数。
# 绝不带原文或改后文本。规则类别是事后探测（不改变输出）：按 redact_line 的步骤分段重放、比对前后差异推断。
CHANGE_EVENT = "redact_backfill.change"
_TYPE_RULE = {"name": "fullname", "phone": "phone", "bank_card": "bank_card", "id_card": "id_card", "qq": "qq",
              "wechat": "wechat", "alipay": "alipay", "email": "email", "url": "url", "amount": "amount",
              "wallet": "wallet", "otp": "otp"}


def _n_changes(old: str, new: str) -> int:
    import difflib
    return sum(1 for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if op[0] != "equal")


def rule_categories(old: str, new: str) -> List[str]:
    """推断 old → new 用到的规则类别（排好序）。只做探测，不参与产出 new。"""
    from deepsuck.extractors import extract_sensitive
    from deepsuck.redact import find_name_spans, find_otp_spans, redact_text, say_names
    from voice.callredact import redact_line

    cats = set()
    t = str(old or "")
    for _ in range(8):   # 与 redact_line 同一循环：拆字报姓 / 逐字解释整段换成「那个名字」
        nt = say_names(t, extract_sensitive(t))
        if nt == t:
            break
        t = nt
    if t != old:
        cats.add("split-surname")
    ents = extract_sensitive(t)
    for e in ents:
        if isinstance(e.get("start"), int) and e.get("sensitive") is not False and redact_text(t, [e]) != t:
            cats.add(_TYPE_RULE.get(e.get("type"), "entity:" + str(e.get("type"))))
    if find_name_spans(t, ents):
        cats.add("name-spelling")
    if find_otp_spans(t):
        cats.add("otp")
    if new != redact_line(old):
        cats.add("dialog-digits")   # redact_dialog_segments：跨段验证码 / 卡号片段 / 人设侧数字
    return sorted(cats) or ["other"]


def field_change(path: str, old: str, new: str) -> dict:
    return {"path": path, "rules": rule_categories(old, new), "n": _n_changes(old, new)}


def _call_id(p: Path, kind: str) -> str:
    return p.stem if kind == "trace" else p.stem.rsplit("-", 1)[-1]


def log_change(p: Path, kind: str, detail: list, dry_run: bool, stream=None) -> None:
    rec = {"event": CHANGE_EVENT, "call_id": _call_id(p, kind), "kind": kind, "dry_run": bool(dry_run),
           "fields": detail, "changes": sum(d["n"] for d in detail)}
    print(json.dumps(rec, ensure_ascii=False, sort_keys=True), file=stream or sys.stderr, flush=True)


SIP_CONSENT = "sip-text-only"   # 与 voice.trace.SIP_CONSENT 一致（这里不 import trace，免得拉起整套依赖）


def stores_text(consent) -> bool:
    """#254：网页已同意（True）或电话线路（sip-text-only）的 trace 存了文字，需要回填。"""
    return consent is True or consent == SIP_CONSENT


def redact_rows(rows: List[Optional[dict]], detail: Optional[list] = None) -> Tuple[List[Optional[dict]], int, int]:
    """返回（新行列表、改动的行数、改动的字段数）。rows 里不是 dict 的（坏行）原样保留。

    #120：两边说话人按时间排（turn 行内依次是 asr、filler、reply），用 redact_dialog_segments 连起来判断：
    同一说话方跨段验证码、跨说话方验证码、卡号片段、人设侧连续 3 位以上数字兜底。"""
    out = [dict(r) if isinstance(r, dict) else r for r in rows]
    refs, roles = [], []   # [(行号, 字段)]
    for i, r in enumerate(out):
        if not isinstance(r, dict):
            continue
        if r.get("type") == "turn":
            for key, role in (("asr", "scammer"), ("filler", "bot"), ("reply", "bot")):
                if isinstance(r.get(key), str):
                    refs.append((i, key))
                    roles.append(role)
        elif r.get("type") == "bot" and isinstance(r.get("text"), str):
            refs.append((i, "text"))
            roles.append("bot")
    for i, r in enumerate(out):   # #252：其余存原话的字段（反馈备注、前端上报原因）也过 redact_line
        if isinstance(r, dict):
            for key in {"feedback": ("note",), "client_error": ("reason",), "client_connected": ("reason",),
                        "end": ("reason",)}.get(r.get("type"), ()):
                if isinstance(r.get(key), str):
                    refs.append((i, key))
                    roles.append(None)
    changed_rows, fields = set(), 0
    if refs:
        from voice.records import redact_line  # #252：trace 与存盘 / 实时推送同一个入口，拆字报姓先整段换掉
        lined = [redact_line(out[i][k]) for i, k in refs]
        speech = [n for n, ro in enumerate(roles) if ro is not None]
        seg = redact_dialog_segments([lined[n] for n in speech], [roles[n] for n in speech])
        fixed = list(lined)
        for n, t in zip(speech, seg):
            fixed[n] = t
        for (i, k), new in zip(refs, fixed):
            if new != out[i][k]:
                if detail is not None:   # #254：只记字段路径、规则类别、改动处数，不记文字
                    detail.append(field_change(f"{out[i].get('type')}[{i}].{k}", out[i][k], new))
                out[i][k] = new
                changed_rows.add(i)
                fields += 1
    return out, len(changed_rows), fields


def _parse(raw_lines: List[str]) -> List[Optional[dict]]:
    rows = []
    for ln in raw_lines:
        try:
            v = json.loads(ln)
            rows.append(v if isinstance(v, dict) else None)
        except ValueError:
            rows.append(None)
    return rows


def _rewrite(path: Path, raw_lines: List[str], rows, new_rows, st: os.stat_result) -> bool:
    lines = [ln if (o == n) else json.dumps(n, ensure_ascii=False)
             for ln, o, n in zip(raw_lines, rows, new_rows)]
    data = "".join(x + "\n" for x in lines).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".backfill-", suffix=".tmp", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        now = path.stat()
        if now.st_size != st.st_size or now.st_mtime_ns != st.st_mtime_ns:   # 处理期间被追加：放弃，下次再跑
            os.unlink(tmp)
            return False
        os.replace(tmp, path)
        return True
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _backup(tar_path: Path, files: List[Path], base: Path, extra: Optional[List[Tuple[Path, str]]] = None) -> None:
    tar_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(tar_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w") as tf:
        for p in files:
            tf.add(str(p), arcname=str(p.relative_to(base)))
        for p, arc in extra or []:
            tf.add(str(p), arcname=arc)


# ---------------------------------------------------------------- 文字记录（#125）
def redact_transcript(doc: dict, detail: Optional[list] = None) -> Tuple[dict, int]:
    """返回（新文档、改动的条数）。只动 transcript[].text（字符串）；其他字段原样。"""
    msgs = doc.get("transcript") if isinstance(doc, dict) else None
    if not isinstance(msgs, list):
        return doc, 0
    refs = [i for i, m in enumerate(msgs) if isinstance(m, dict) and isinstance(m.get("text"), str)]
    if not refs:
        return doc, 0
    from voice.records import redact_line  # #250：旧记录里漏掉的拆字报姓按同一规则补打
    fixed = redact_dialog_segments([redact_line(msgs[i]["text"]) for i in refs], [msgs[i].get("role") for i in refs])
    out = dict(doc)
    out["transcript"] = [dict(m) if isinstance(m, dict) else m for m in msgs]
    n = 0
    for i, t in zip(refs, fixed):
        if t != msgs[i]["text"]:
            if detail is not None:
                detail.append(field_change(f"transcript[{i}].text", msgs[i]["text"], t))
            out["transcript"][i]["text"] = t
            n += 1
    return out, n


def _rewrite_json(path: Path, doc: dict, st: os.stat_result) -> bool:
    data = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".backfill-", suffix=".tmp", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        now = path.stat()
        if now.st_size != st.st_size or now.st_mtime_ns != st.st_mtime_ns:
            os.unlink(tmp)
            return False
        os.replace(tmp, path)
        return True
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _want(p: Path, calls) -> bool:
    """#252 --call：trace 文件名是 <编号>.jsonl，文字记录是 <时间>-<渠道>-<编号>.json。"""
    if not calls:
        return True
    stem = p.stem
    return stem in calls or any(stem.endswith("-" + c) for c in calls)


def plan_transcripts(tdir: Optional[Path], min_age: float, now: float, calls=None) -> Tuple[dict, list]:
    stats = {"dir_exists": bool(tdir and tdir.is_dir()), "files_scanned": 0, "skipped_recent": 0, "skipped_bad": 0,
             "skipped_changed": 0, "files_changed": 0, "fields_changed": 0}
    plan: list = []
    if not stats["dir_exists"]:
        return stats, plan
    for p in sorted(tdir.glob("*.json")):
        if not p.is_file() or p.is_symlink() or not _want(p, calls):
            continue
        stats["files_scanned"] += 1
        st = p.stat()
        if now - st.st_mtime < min_age:
            stats["skipped_recent"] += 1
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8", errors="strict"))
        except (ValueError, UnicodeDecodeError):
            stats["skipped_bad"] += 1
            continue
        detail: list = []
        new, n = redact_transcript(doc, detail)
        if n:
            plan.append((p, new, st, n, detail))
    return stats, plan


def run(trace_dir: Path, dry_run: bool = True, min_age: float = 600, backup: Optional[Path] = None,
        now: Optional[float] = None, transcripts: Optional[Path] = None, calls=None) -> dict:
    now = time.time() if now is None else now
    tstats, tplan = plan_transcripts(transcripts, min_age, now, calls) if transcripts is not None else (None, [])
    stats = {"dir_exists": trace_dir.is_dir(), "dry_run": dry_run, "files_scanned": 0, "consented": 0, "sip": 0,
             "skipped_not_consented": 0, "skipped_unknown_consent": 0, "skipped_recent": 0, "skipped_changed": 0,
             "files_changed": 0, "rows_changed": 0, "fields_changed": 0, "backup_files": 0}
    if tstats is not None:
        stats["transcripts"] = tstats
    plan = []
    if not stats["dir_exists"]:
        trace_dir = None
    for p in (sorted(trace_dir.glob("*.jsonl")) if trace_dir is not None else []):
        if not p.is_file() or p.is_symlink() or not _want(p, calls):
            continue
        stats["files_scanned"] += 1
        st = p.stat()
        raw_lines = p.read_text(encoding="utf-8", errors="strict").splitlines()
        rows = _parse([ln for ln in raw_lines])
        c = consent_of(rows)
        if not stores_text(c):
            stats["skipped_not_consented" if c is not None else "skipped_unknown_consent"] += 1
            continue
        stats["consented"] += 1
        if c == SIP_CONSENT:
            stats["sip"] += 1
        if now - st.st_mtime < min_age:
            stats["skipped_recent"] += 1
            continue
        detail = []
        new_rows, nrows, nfields = redact_rows(rows, detail)
        if nrows:
            plan.append((p, raw_lines, rows, new_rows, st, nrows, nfields, detail))
    for x in tplan:
        log_change(x[0], "transcript", x[4], dry_run)
    for x in plan:
        log_change(x[0], "trace", x[7], dry_run)
    if dry_run:
        stats["files_changed"] = len(plan)
        stats["rows_changed"] = sum(x[5] for x in plan)
        stats["fields_changed"] = sum(x[6] for x in plan)
        if tstats is not None:
            tstats["files_changed"] = len(tplan)
            tstats["fields_changed"] = sum(x[3] for x in tplan)
        return stats
    if backup is not None and (plan or tplan):
        _backup(backup, [x[0] for x in plan], trace_dir, [(x[0], "transcripts/" + x[0].name) for x in tplan])
        stats["backup_files"] = len(plan) + len(tplan)
    for p, new, st, n, _ in tplan:
        if _rewrite_json(p, new, st):
            tstats["files_changed"] += 1
            tstats["fields_changed"] += n
        else:
            tstats["skipped_changed"] += 1
    for p, raw_lines, rows, new_rows, st, nrows, nfields, _ in plan:
        if _rewrite(p, raw_lines, rows, new_rows, st):
            stats["files_changed"] += 1
            stats["rows_changed"] += nrows
            stats["fields_changed"] += nfields
        else:
            stats["skipped_changed"] += 1
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="用当前共享脱敏规则重新脱敏已同意通话和电话线路的历史追踪（只输出计数）")
    ap.add_argument("--dir", help="追踪目录，默认 TRACE_DIR（容器里是 /traces）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不改文件")
    ap.add_argument("--min-age", type=float, default=600, help="最近多少秒内改过的文件跳过（通话可能还在进行），默认 600")
    ap.add_argument("--transcripts", help="文字记录目录，默认 DATA_DIR/voice/transcripts（容器里是 /data/voice/transcripts）")
    ap.add_argument("--no-transcripts", action="store_true", help="只处理 trace，不处理文字记录")
    ap.add_argument("--backup", help="正式改写前把要改的文件打包到这个 tar（新建，0600；已存在则报错）")
    ap.add_argument("--call", action="append", default=[], help="只处理这些通话编号（可重复，或逗号分隔）")
    a = ap.parse_args(argv)
    calls = {c.strip() for x in a.call for c in x.split(",") if c.strip()} or None
    if a.dir:
        d = Path(a.dir)
    else:
        from voice.trace import trace_dir
        d = trace_dir()
    if a.no_transcripts:
        td = None
    elif a.transcripts:
        td = Path(a.transcripts)
    else:
        from voice.records import transcript_dir
        td = transcript_dir()
    bk = Path(a.backup) if a.backup else None
    if bk is not None and not a.dry_run and (bk.exists() or bk.is_symlink()):
        # #216：备份文件已存在时不再抛 traceback，只给一行错误 JSON、退出码 3，什么都不改
        print(json.dumps({"error": "backup_exists", "dir_exists": d.is_dir()}, sort_keys=True))
        return 3
    try:
        stats = run(d, dry_run=a.dry_run, min_age=a.min_age, backup=bk, transcripts=td, calls=calls)
    except FileExistsError:   # 检查后、写之前被别人建了同名备份
        print(json.dumps({"error": "backup_exists", "dir_exists": d.is_dir()}, sort_keys=True))
        return 3
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0 if stats["dir_exists"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
