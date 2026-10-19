"""用当前共享脱敏规则重新脱敏历史通话追踪（#92：跨 ASR 分段的验证码）。可重复执行。

只处理已同意的通话：start 行（没有时看 end 行）的 consent 恰为 true。未同意（false）、电话线路（"sip-text-only"）、
判断不了的文件一律不改。格式见 docs/TRACE_SCHEMA.md（v1 / v2 都认）。

做法：对方（turn.asr）、人设（bot.text、turn.filler、turn.reply）各按文件里的先后顺序当作同一说话方的连续分段，
过一遍 deepsuck.redact.redact_otp_segments（只把命中的数字换成 *，长度不变；已打码的不会再变）。
只重写有改动的行，其余行原样保留；写临时文件（0600）后原子替换，保留原文件的修改时间（保留期按修改时间算）。
最近 --min-age 秒内改过、或处理期间被追加的文件（通话可能还在进行）跳过，下次再跑。

输出只有计数（JSON），绝不打印任何文字内容或通话编号。

    python -m voice.redact_backfill --dry-run          # 只统计会改多少
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


def redact_rows(rows: List[Optional[dict]]) -> Tuple[List[Optional[dict]], int, int]:
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
    changed_rows, fields = set(), 0
    if refs:
        fixed = redact_dialog_segments([out[i][k] for i, k in refs], roles)
        for (i, k), new in zip(refs, fixed):
            if new != out[i][k]:
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


def _backup(tar_path: Path, files: List[Path], base: Path) -> None:
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(tar_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w") as tf:
        for p in files:
            tf.add(str(p), arcname=str(p.relative_to(base)))


def run(trace_dir: Path, dry_run: bool = True, min_age: float = 600, backup: Optional[Path] = None,
        now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    stats = {"dir_exists": trace_dir.is_dir(), "dry_run": dry_run, "files_scanned": 0, "consented": 0,
             "skipped_not_consented": 0, "skipped_unknown_consent": 0, "skipped_recent": 0, "skipped_changed": 0,
             "files_changed": 0, "rows_changed": 0, "fields_changed": 0, "backup_files": 0}
    if not stats["dir_exists"]:
        return stats
    plan = []
    for p in sorted(trace_dir.glob("*.jsonl")):
        if not p.is_file() or p.is_symlink():
            continue
        stats["files_scanned"] += 1
        st = p.stat()
        raw_lines = p.read_text(encoding="utf-8", errors="strict").splitlines()
        rows = _parse([ln for ln in raw_lines])
        c = consent_of(rows)
        if c is not True:
            stats["skipped_not_consented" if c is not None else "skipped_unknown_consent"] += 1
            continue
        stats["consented"] += 1
        if now - st.st_mtime < min_age:
            stats["skipped_recent"] += 1
            continue
        new_rows, nrows, nfields = redact_rows(rows)
        if nrows:
            plan.append((p, raw_lines, rows, new_rows, st, nrows, nfields))
    if dry_run:
        stats["files_changed"] = len(plan)
        stats["rows_changed"] = sum(x[5] for x in plan)
        stats["fields_changed"] = sum(x[6] for x in plan)
        return stats
    if backup is not None and plan:
        _backup(backup, [x[0] for x in plan], trace_dir)
        stats["backup_files"] = len(plan)
    for p, raw_lines, rows, new_rows, st, nrows, nfields in plan:
        if _rewrite(p, raw_lines, rows, new_rows, st):
            stats["files_changed"] += 1
            stats["rows_changed"] += nrows
            stats["fields_changed"] += nfields
        else:
            stats["skipped_changed"] += 1
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="用当前共享脱敏规则重新脱敏已同意通话的历史追踪（只输出计数）")
    ap.add_argument("--dir", help="追踪目录，默认 TRACE_DIR（容器里是 /traces）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不改文件")
    ap.add_argument("--min-age", type=float, default=600, help="最近多少秒内改过的文件跳过（通话可能还在进行），默认 600")
    ap.add_argument("--backup", help="正式改写前把要改的文件打包到这个 tar（新建，0600；已存在则报错）")
    a = ap.parse_args(argv)
    if a.dir:
        d = Path(a.dir)
    else:
        from voice.trace import trace_dir
        d = trace_dir()
    stats = run(d, dry_run=a.dry_run, min_age=a.min_age, backup=Path(a.backup) if a.backup else None)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0 if stats["dir_exists"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
