#!/usr/bin/env python3
"""IP file history MVP, stdlib only, Python 3.10+.

No FULL/PATCH inference. Results describe *observed* files, not an approved
or complete effective library. All source directories are read-only.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import shlex
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Check the suffix before the folder name: e.g. IP/SPICE/top.cdl is a CDL.
SUFFIX_VIEWS = (
    (".lib.gz", "LIB"), (".lef.gz", "LEF"), (".gds.gz", "GDS"),
    (".oas.gz", "OAS"), (".spef.gz", "SPEF"), (".sp.gz", "SPICE"),
    (".spi.gz", "SPICE"),
    (".lef", "LEF"), (".lib", "LIB"), (".db", "DB"),
    (".gds", "GDS"), (".oas", "OAS"), (".ndm", "NDM"),
    (".v", "VERILOG"), (".sv", "VERILOG"), (".cdl", "CDL"),
    (".sp", "SPICE"), (".spi", "SPICE"), (".spice", "SPICE"),
    (".sdc", "SDC"), (".spef", "SPEF"), (".upf", "UPF"),
    (".cpf", "CPF"), (".def", "DEF"), (".sdf", "SDF"),
    (".pdf", "DOC"), (".docx", "DOC"), (".doc", "DOC"),
    (".md", "DOC"), (".txt", "DOC"),
)
VIEW_FOLDERS = {
    "LEF": "LEF", "LIB": "LIB", "LIBERTY": "LIB", "NLDM": "LIB",
    "CCS": "LIB", "DB": "DB", "GDS": "GDS", "GDSII": "GDS",
    "OAS": "OAS", "NDM": "NDM", "VERILOG": "VERILOG", "RTL": "VERILOG",
    "SPICE": "SPICE", "CDL": "CDL", "SPEF": "SPEF", "SDC": "SDC",
    "DOC": "DOC", "DOCS": "DOC", "UPF": "UPF", "CPF": "CPF",
}
IGNORED_DIRS = {".git", ".svn", "__pycache__", ".cache", "tmp", "temp"}


def view_of(relative: Path) -> str | None:
    name = relative.name.lower()
    for suffix, view in SUFFIX_VIEWS:
        if name.endswith(suffix):
            return view
    # Do not invent a file type from its folder alone when suffix is unknown.
    return None


def identity_relative_path(relative: Path) -> str:
    """Ignore only known view-root wrappers, never lowercase a file identity."""
    parts = relative.parts
    wrapper_positions = [i for i, part in enumerate(parts[:-1]) if part.upper() in VIEW_FOLDERS]
    selected = parts[wrapper_positions[-1] + 1:] if wrapper_positions else parts
    return "/".join(selected)


def file_identity(library_id: str, view: str, relative: Path) -> str:
    return f"{library_id}|{view}|{identity_relative_path(relative)}"


def config_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve(strict=False)


def scan_delivery(library: str, delivery: dict[str, Any], base: Path,
                  max_entries: int = 200000) -> dict[str, Any]:
    root = config_path(str(delivery["root"]), base)
    records: list[dict[str, str]] = []
    issues: list[str] = []
    visited_entries = 0
    if not root.is_dir():
        return {"status": "PARTIAL", "records": [], "issues": [f"目录不存在或无法访问: {root}"],
                "root": str(root)}

    def on_error(err: OSError) -> None:
        issues.append(f"目录扫描失败: {err}")

    for current, dirs, names in os.walk(root, followlinks=False, onerror=on_error):
        symlink_dirs = [name for name in dirs if (Path(current) / name).is_symlink()]
        if symlink_dirs:
            issues.append(f"存在未遍历的目录软链接: {current}: {', '.join(sorted(symlink_dirs))}")
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and d not in symlink_dirs)
        for name in sorted(names):
            visited_entries += 1
            if visited_entries > max_entries:
                issues.append(f"扫描条目超过上限 {max_entries}，文件盘点不完整")
                break
            logical = Path(current) / name
            relative = logical.relative_to(root)
            view = view_of(relative)
            if view is None:
                continue
            try:
                resolved = logical.resolve(strict=True)
                if not resolved.is_file():
                    raise OSError("不是可读取的普通文件")
                # Symlinks pointing outside a registered delivery are not silently dropped.
                if not resolved.is_relative_to(root):
                    issues.append(f"文件目标在交付目录外，未归入历史: {logical} -> {resolved}")
                    continue
                records.append({
                    "file_id": file_identity(library, view, relative),
                    "view": view,
                    "identity_path": identity_relative_path(relative),
                    "relative_path": relative.as_posix(),
                    "source_path": str(logical),
                    "resolved_path": str(resolved),
                    "version": str(delivery["id"]),
                    "order": int(delivery["order"]),
                    "library_id": library,
                })
            except (OSError, ValueError) as err:
                issues.append(f"文件无法确认: {logical} ({err})")
        if visited_entries > max_entries:
            break
    return {"status": "COMPLETE" if not issues else "PARTIAL",
            "records": records, "issues": issues, "root": str(root)}


def _snapshot(path: Path) -> tuple[int, int, int, int]:
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns


def _open_content(path: Path):
    return gzip.open(path, "rb") if path.name.lower().endswith(".gz") else path.open("rb")


def compare_content(first: str, second: str, chunk_size: int = 1024 * 1024) -> dict[str, str]:
    """Compare content without hashing; each .gz is decompressed before comparing."""
    a, b = Path(first), Path(second)
    try:
        before = _snapshot(a), _snapshot(b)
        same = True
        with _open_content(a) as fa, _open_content(b) as fb:
            while True:
                ba, bb = fa.read(chunk_size), fb.read(chunk_size)
                if ba != bb:
                    same = False
                    break
                if not ba:
                    break
        after = _snapshot(a), _snapshot(b)
        if before != after:
            return {"status": "UNVERIFIED", "reason": "比较时源文件发生变化"}
        return {"status": "SAME" if same else "CHANGED", "reason": ""}
    except (OSError, ValueError, EOFError, gzip.BadGzipFile) as err:
        return {"status": "UNVERIFIED", "reason": f"读取或解压失败: {err}"}


def build_history(library: dict[str, Any], base: Path, max_entries: int,
                  compare: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    library_id = str(library.get("library_id") or "").strip()
    if not library_id:
        raise ValueError("每个 libraries 项都必须填写唯一 library_id")
    deliveries = library.get("deliveries") or []
    if not deliveries:
        raise ValueError(f"{library_id} 缺少 deliveries")
    ids = [str(d.get("id") or "") for d in deliveries]
    orders = [d.get("order") for d in deliveries]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{library_id}: 交付 id 为空或重复")
    if any(isinstance(x, bool) or not isinstance(x, int) for x in orders) or len(orders) != len(set(orders)):
        raise ValueError(f"{library_id}: order 必须是互不相同的整数")
    sorted_deliveries = sorted(deliveries, key=lambda d: d["order"])
    inventory_rows: list[dict[str, Any]] = []
    records_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    for d in sorted_deliveries:
        result = scan_delivery(library_id, d, base, max_entries)
        inventory_rows.append({"library_id": library_id, "version": d["id"],
                               "order": d["order"], "root": result["root"],
                               "scan_status": result["status"],
                               "found_files": len(result["records"]),
                               "issues": result["issues"]})
        for item in result["records"]:
            records_by_id[item["file_id"]].append(item)
    rows: list[dict[str, Any]] = []
    for key, records in sorted(records_by_id.items()):
        records.sort(key=lambda r: r["order"])
        versions = [r["version"] for r in records]
        counts = Counter(versions)
        duplicate_versions = sorted(v for v, count in counts.items() if count > 1)
        latest = records[-1]
        previous = records[-2] if len(records) >= 2 else None
        later_unknown = any(s["scan_status"] != "COMPLETE" and s["order"] > latest["order"]
                            for s in inventory_rows)
        intermediate_unknown = previous is not None and any(
            s["scan_status"] != "COMPLETE" and previous["order"] < s["order"] < latest["order"]
            for s in inventory_rows)
        earlier_unknown = previous is None and any(
            s["scan_status"] != "COMPLETE" and s["order"] < latest["order"]
            for s in inventory_rows)
        ambiguous = bool(duplicate_versions)
        latest_state = "AMBIGUOUS" if ambiguous else "UNCERTAIN" if later_unknown else "CONFIRMED"
        previous_state = ("AMBIGUOUS" if ambiguous else
                          "UNCERTAIN" if later_unknown or intermediate_unknown or earlier_unknown else
                          "CONFIRMED" if previous is not None else "NONE")
        result = {"file_id": key, "library_id": library_id, "view": latest["view"],
                  "identity_path": latest["identity_path"], "latest": latest if not ambiguous else None,
                  "latest_status": latest_state, "previous": previous if not ambiguous else None,
                  "previous_status": previous_state,
                  "occurrences": records,
                  "comparison": {"status": "NOT_RUN", "reason": "无可确认的最新/次新文件对"},
                  "warnings": [f"同一次交付内存在重复身份: {', '.join(duplicate_versions)}"] if ambiguous else []}
        if latest["view"] == "DOC":
            result["comparison"] = {"status": "NOT_RUN", "reason": "DOC 只记录文件，不比较正文"}
        elif compare and latest_state == "CONFIRMED" and previous_state == "CONFIRMED" and previous:
            result["comparison"] = compare_content(previous["resolved_path"], latest["resolved_path"])
        rows.append(result)
    return rows, inventory_rows


_GROUP = re.compile(r"^#\s*([^#\r\n]+?)\s*#$")


def parse_formal_manifest(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Accept '#ip_name#' sections, followed by 'filename IP/LIB/' records."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    group = ""
    try:
        with path.open(encoding="utf-8-sig") as handle:
            for line_no, raw in enumerate(handle, 1):
                value = raw.strip()
                if not value:
                    continue
                heading = _GROUP.fullmatch(value)
                if heading:
                    group = heading.group(1).strip()
                    continue
                if value.startswith("#"):
                    continue
                try:
                    items = shlex.split(value, comments=False)
                except ValueError as err:
                    errors.append(f"行 {line_no}: 语法错误 {err}")
                    continue
                if len(items) != 2 or not group:
                    errors.append(f"行 {line_no}: 需要先有 #IP#，每行格式为 文件名 目录")
                    continue
                filename, directory = items
                if Path(filename).name != filename or Path(directory).is_absolute() or ".." in Path(directory).parts:
                    errors.append(f"行 {line_no}: 文件名或目录格式不安全/不支持")
                    continue
                view = view_of(Path(filename))
                records.append({"group": group, "filename": filename,
                                "directory": directory, "view": view or "UNKNOWN",
                                "line": line_no})
    except (OSError, UnicodeError) as err:
        errors.append(f"正式清单读取失败: {err}")
    return records, errors


def check_formal_manifest(config: dict[str, Any], base: Path,
                          histories: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    name = str(config.get("formal_manifest") or "").strip()
    if not name:
        return [], []
    records, errors = parse_formal_manifest(config_path(name, base))
    groups = set(config.get("formal_groups") or [str(config["ip_name"])])
    chosen = [r for r in records if r["group"] in groups]
    if not chosen:
        errors.append(f"正式清单没有找到所要求分组: {', '.join(sorted(groups))}")
    current_name_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    history_name_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    resolved_index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for h in histories:
        if h["latest"] is not None:
            current_name_index[(h["view"], Path(h["identity_path"]).name)].append(h)
        for occurrence in h["occurrences"]:
            history_name_index[(h["view"], Path(h["identity_path"]).name)].append(h)
            resolved_index[occurrence["resolved_path"]].append(occurrence)
    by_file_id = {h["file_id"]: h for h in histories}

    def formal_rank(file_id: str, version: str) -> str:
        """Compare *actual linked source* with the same logical file's RAW history.

        Unknown scan coverage is not treated as a confirmed latest/previous rank.
        """
        history = by_file_id.get(file_id)
        if not history:
            return "UNKNOWN"
        if history["latest_status"] != "CONFIRMED":
            return "RANK_UNCERTAIN"
        latest = history.get("latest") or {}
        if latest.get("version") == version:
            return "LATEST"
        if history["previous_status"] in {"UNCERTAIN", "AMBIGUOUS"}:
            return "RANK_UNCERTAIN"
        previous = history.get("previous") or {}
        if previous.get("version") == version:
            return "PREVIOUS"
        if any(item["version"] == version for item in history["occurrences"]):
            return "OLDER"
        return "UNKNOWN"

    root_value = config.get("formal_root")
    formal_root = config_path(str(root_value), base) if root_value else None
    result: list[dict[str, Any]] = []
    for item in chosen:
        record = dict(item)
        key = (item["view"], item["filename"])
        matched = {h["file_id"]: h for h in current_name_index.get(key, [])}
        historical = {h["file_id"]: h for h in history_name_index.get(key, [])}
        record["candidate_file_ids"] = sorted(matched)
        record["candidate_count"] = len(matched)
        record["published_path"] = ""
        record["observed_source"] = ""
        record["observed_source_version"] = ""
        record["raw_latest_version"] = ""
        record["raw_previous_version"] = ""
        record["raw_latest_path"] = ""
        record["formal_relation"] = "UNVERIFIED"
        record["relation_note"] = "没有已验证的正式来源链接，不能判断链接了哪个版本"
        if len(matched) == 1:
            candidate = next(iter(matched.values()))
            record["raw_latest_version"] = (candidate.get("latest") or {}).get("version", "")
            record["raw_previous_version"] = (candidate.get("previous") or {}).get("version", "")
            record["raw_latest_path"] = (candidate.get("latest") or {}).get("source_path", "")
        if len(matched) == 1:
            record["status"] = "NAME_ONLY_CANDIDATE"
        elif len(matched) > 1:
            record["status"] = "AMBIGUOUS_NAME"
        elif historical:
            record["status"] = "HISTORICAL_NAME_ONLY"
        else:
            record["status"] = "NOT_FOUND_IN_RAW_HISTORY"
        if formal_root is not None:
            published = formal_root / item["directory"] / item["filename"]
            record["published_path"] = str(published)
            if not published.is_file():
                record["status"] = "PUBLISHED_FILE_MISSING"
            else:
                try:
                    resolved = str(published.resolve(strict=True))
                    record["observed_source"] = resolved
                    if Path(resolved) == published.absolute():
                        record["status"] = "PUBLISHED_FOUND_SOURCE_UNKNOWN"
                        record["relation_note"] = "正式文件没有可验证的软链接，不能据此确认 RAW 来源"
                        result.append(record)
                        continue
                    candidates = resolved_index.get(resolved, [])
                    identities = {(r["file_id"], r["version"]) for r in candidates}
                    if len(identities) == 1:
                        match = candidates[0]
                        record["observed_source_version"] = match["version"]
                        record["status"] = "SOURCE_PATH_CONFIRMED"
                        record["candidate_file_ids"] = [match["file_id"]]
                        history = by_file_id[match["file_id"]]
                        record["raw_latest_version"] = (history.get("latest") or {}).get("version", "")
                        record["raw_previous_version"] = (history.get("previous") or {}).get("version", "")
                        record["raw_latest_path"] = (history.get("latest") or {}).get("source_path", "")
                        relation = formal_rank(match["file_id"], match["version"])
                        record["formal_relation"] = relation
                        notes = {
                            "LATEST": "正式库已链接最近观察到的 RAW 版本；不等于审批放行",
                            "PREVIOUS": "正式库链接的是次新 RAW 版本，最新版本尚未被本条引用",
                            "OLDER": "正式库链接的是更早 RAW 版本（不是次新）",
                            "RANK_UNCERTAIN": "正式源路径已找到，但 RAW 扫描不完整，版本排名未确认",
                            "UNKNOWN": "正式源路径已找到，但无法给出可靠版本排名",
                        }
                        record["relation_note"] = notes[relation]
                    elif len(identities) > 1:
                        record["status"] = "SOURCE_PATH_AMBIGUOUS"
                        record["relation_note"] = "正式链接目标对应多条 RAW 文件/版本，不能唯一确定"
                    else:
                        record["status"] = "PUBLISHED_FOUND_SOURCE_UNKNOWN"
                        record["relation_note"] = "正式文件存在，但来源不属于已记录 RAW 路径；可能是复制文件或未登记版本"
                except OSError:
                    record["status"] = "PUBLISHED_FILE_UNREADABLE"
        result.append(record)
    return result, errors


def csv_save(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_context(config: dict[str, Any], base: Path, output: Path, *, compare: bool = True,
                max_entries: int = 200000,
                cached_histories: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None) -> dict[str, Any]:
    ip_name = str(config.get("ip_name") or "").strip()
    if not ip_name:
        raise ValueError("配置缺少 ip_name")
    libraries = config.get("libraries") or []
    if not libraries:
        raise ValueError("配置缺少 libraries")
    library_ids = [str(lib.get("library_id") or "") for lib in libraries]
    if len(set(library_ids)) != len(library_ids):
        raise ValueError("library_id 重复")
    histories: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for library in libraries:
        library_id = library["library_id"]
        if cached_histories is not None and library_id in cached_histories:
            rows, scans = cached_histories[library_id]
        else:
            rows, scans = build_history(library, base, max_entries, compare)
            if cached_histories is not None:
                cached_histories[library_id] = (rows, scans)
        histories.extend(rows)
        inventory.extend(scans)
    formal, formal_errors = check_formal_manifest(config, base, histories)
    output.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    summary = {
        "ip_name": ip_name,
        "generated_at": generated,
        "scope": "历史最新观察 + 候选文件集合；不宣称当前有效/正式放行/质量通过",
        "library_count": len(libraries),
        "deliveries": len(inventory),
        "tracked_file_identities": len(histories),
        "scan_partial_count": sum(s["scan_status"] != "COMPLETE" for s in inventory),
        "uncertain_history_count": sum(h["latest_status"] != "CONFIRMED" or
                                      h["previous_status"] in {"UNCERTAIN", "AMBIGUOUS"}
                                      for h in histories),
        "same_count": sum(h["comparison"]["status"] == "SAME" for h in histories),
        "changed_count": sum(h["comparison"]["status"] == "CHANGED" for h in histories),
        "compare_unverified_count": sum(h["comparison"]["status"] == "UNVERIFIED" for h in histories),
        "formal_manifest_records": len(formal),
        "formal_source_confirmed": sum(r["status"] == "SOURCE_PATH_CONFIRMED" for r in formal),
        "formal_link_latest_count": sum(r["formal_relation"] == "LATEST" for r in formal),
        "formal_link_previous_count": sum(r["formal_relation"] == "PREVIOUS" for r in formal),
        "formal_link_older_count": sum(r["formal_relation"] == "OLDER" for r in formal),
        "formal_link_unverified_count": sum(r["formal_relation"] not in {"LATEST", "PREVIOUS", "OLDER"} for r in formal),
        "formal_errors": formal_errors,
    }
    (output / "result.json").write_text(json.dumps(
        {"summary": summary, "inventories": inventory,
         "file_histories": histories, "formal_manifest": formal},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    file_rows = []
    for h in histories:
        latest, previous = h["latest"] or {}, h["previous"] or {}
        file_rows.append({
            "IP": ip_name, "Library": h["library_id"], "View": h["view"],
            "文件身份": h["identity_path"], "历史出现次数": len(h["occurrences"]),
            "出现版本": " -> ".join(r["version"] for r in h["occurrences"]),
            "最新版本": latest.get("version", ""), "最新文件路径": latest.get("source_path", ""),
            "最新可信度": h["latest_status"],
            "次新版本": previous.get("version", ""), "次新文件路径": previous.get("source_path", ""),
            "次新可信度": h["previous_status"],
            "内容对比": h["comparison"]["status"],
            "无法确定的原因": "; ".join(h["warnings"] +
                            ([h["comparison"].get("reason", "")] if h["comparison"].get("reason") else [])),
        })
    # The business-facing file history also reports whether each RAW file identity
    # is referenced by the selected formal stage. Keep link rank distinct from
    # the 'latest observed in RAW' concept.
    relations_by_file_id: dict[str, list[str]] = defaultdict(list)
    for item in formal:
        if item["status"] == "SOURCE_PATH_CONFIRMED" and len(item["candidate_file_ids"]) == 1:
            relations_by_file_id[item["candidate_file_ids"][0]].append(item["formal_relation"])
    for file_row, history in zip(file_rows, histories):
        ranks = relations_by_file_id.get(history["file_id"])
        file_row["正式库链接状态"] = "、".join(sorted(set(ranks))) if ranks else "未确认正式引用"
    # Rewrite files.csv with the newly computed, per-file formal link summary.
    csv_save(output / "files.csv", file_rows, [
        "IP", "Library", "View", "文件身份", "历史出现次数", "出现版本", "最新版本",
        "最新文件路径", "最新可信度", "次新版本", "次新文件路径", "次新可信度",
        "内容对比", "正式库链接状态", "无法确定的原因",
    ])
    formal_rows = [{
        "IP分组": row["group"], "行号": row["line"], "文件名": row["filename"],
        "清单目录": row["directory"], "View": row["view"],
        "关联状态": row["status"], "RAW候选文件数": row["candidate_count"],
        "候选文件身份": "; ".join(row["candidate_file_ids"]),
        "正式实际文件路径": row["published_path"], "实际来源路径": row["observed_source"],
        "实际来源版本": row["observed_source_version"],
        "RAW最新版本": row["raw_latest_version"],
        "RAW次新版本": row["raw_previous_version"],
        "RAW最新文件路径": row["raw_latest_path"],
        "正式与RAW最新关系": row["formal_relation"],
        "关系说明": row["relation_note"],
    } for row in formal]
    csv_save(output / "formal.csv", formal_rows, [
        "IP分组", "行号", "文件名", "清单目录", "View", "关联状态", "RAW候选文件数",
        "候选文件身份", "正式实际文件路径", "实际来源路径", "实际来源版本",
        "RAW最新版本", "RAW次新版本", "RAW最新文件路径", "正式与RAW最新关系", "关系说明",
    ])
    csv_save(output / "inventories.csv", [
        {"Library": x["library_id"], "交付": x["version"], "顺序": x["order"],
         "目录": x["root"], "扫描状态": x["scan_status"],
         "观察文件数": x["found_files"], "扫描问题": "; ".join(x["issues"])}
        for x in inventory], ["Library", "交付", "顺序", "目录", "扫描状态", "观察文件数", "扫描问题"])
    return summary



# ---------- Batch entry: IP roster + formal file list + RAW libraries ----------

def read_ip_roster(path: Path) -> list[str]:
    """One business IP per line; blank lines and # comments are ignored."""
    result: list[str] = []
    seen: set[str] = set()
    try:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            ip = line.split("#", 1)[0].strip()
            if not ip:
                continue
            if any(ch.isspace() for ch in ip) or "/" in ip or "\\" in ip or ip in {".", ".."}:
                raise ValueError(f"IP 清单第 {line_no} 行无效：{line}")
            if ip in seen:
                raise ValueError(f"IP 清单重复：{ip}（第 {line_no} 行）")
            seen.add(ip)
            result.append(ip)
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"IP 清单读取失败：{exc}") from exc
    if not result:
        raise ValueError("IP 清单为空")
    return result


def _read_manifest_groups(path: Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    records, errors = parse_formal_manifest(path)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["group"]].append(record)
    return groups, errors


def _exact_name_match(ip: str, library: dict[str, Any]) -> bool:
    # Never prefix/substring-match different business identities.
    names = {str(library.get("library_id") or ""),
             str(library.get("library_name") or ""),
             str(library.get("name") or "")}
    library_id = str(library.get("library_id") or "")
    names.add(library_id.rsplit(".", 1)[-1])
    return ip in names


def _formal_group_sources(
        rows: list[dict[str, Any]], formal_root: Path | None,
        libraries: list[dict[str, Any]], base: Path) -> tuple[list[str], list[str]]:
    """Return uniquely proven library owners from real formal -> RAW references."""
    if formal_root is None:
        return [], []
    version_roots: list[tuple[Path, str]] = []
    for lib in libraries:
        for d in lib.get("deliveries") or []:
            version_roots.append((config_path(str(d["root"]), base), str(lib["library_id"])))
    owners: set[str] = set()
    issues: list[str] = []
    for row in rows:
        published = formal_root / row["directory"] / row["filename"]
        if not published.exists() or not published.is_file():
            continue
        try:
            source = published.resolve(strict=True)
        except OSError:
            continue
        if source == published.absolute():
            continue
        best_len = -1
        best: set[str] = set()
        for root, owner in version_roots:
            if source.is_relative_to(root):
                n = len(root.parts)
                if n > best_len:
                    best_len, best = n, {owner}
                elif n == best_len:
                    best.add(owner)
        if len(best) == 1:
            owners.update(best)
        elif len(best) > 1:
            issues.append(f"正式文件来源映射到多个 Library：{published}")
    return sorted(owners), issues


def _version_sort_number(name: str) -> int | None:
    """Use only recognized date (YYYYMMDD) or V + numeric version patterns."""
    match = re.fullmatch(r"[vV](\d+)", name)
    if match:
        return int(match.group(1))
    match = re.search(r"(?<!\d)(20\d{6})(?!\d)", name)
    if match:
        try:
            from datetime import datetime as dt
            dt.strptime(match.group(1), "%Y%m%d")
        except ValueError:
            return None
        return int(match.group(1))
    return None


def discover_raw_libraries(raw_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Strict sample layout: raw_root/Vendor/Library/Delivery/{LEF,LIB,...}.

    Never infer delivery order from alphabetical sorting or filesystem mtime.
    Complex layouts should be supplied in the explicit `libraries` config.
    """
    if not raw_root.is_dir():
        raise ValueError(f"RAW 根目录不存在：{raw_root}")
    result: list[dict[str, Any]] = []
    issues: list[str] = []
    for vendor in sorted(raw_root.iterdir()):
        if not vendor.is_dir() or vendor.is_symlink() or vendor.name.startswith("."):
            continue
        for lib_root in sorted(vendor.iterdir()):
            if not lib_root.is_dir() or lib_root.is_symlink():
                continue
            children = [d for d in lib_root.iterdir() if d.is_dir() and not d.name.startswith(".")]
            delivery_dirs = [d for d in children if not d.is_symlink()
                             and _version_sort_number(d.name) is not None]
            if not delivery_dirs:
                continue
            if len(delivery_dirs) != len(children):
                issues.append(f"存在未识别或软链接交付目录，需显式登记：{lib_root}")
                continue
            order_types = {"VERSION" if re.fullmatch(r"[vV]\d+", d.name) else "DATE" for d in delivery_dirs}
            if len(order_types) != 1:
                issues.append(f"交付目录混用版本号和日期，无法确认顺序：{lib_root}")
                continue
            ranks = [_version_sort_number(d.name) for d in delivery_dirs]
            if len(set(ranks)) != len(ranks):
                issues.append(f"无法确定唯一交付顺序，已跳过：{lib_root}")
                continue
            deliveries = [{"id": d.name, "order": _version_sort_number(d.name), "root": str(d)}
                          for d in delivery_dirs]
            result.append({"library_id": f"{vendor.name}.{lib_root.name}",
                           "library_name": lib_root.name,
                           "deliveries": sorted(deliveries, key=lambda row: row["order"])})
    if not result:
        issues.append("未自动发现可识别的 Library：请按示例目录布局放置 RAW，或在配置中明确提供 libraries")
    return result, issues


def _safe_output_name(ip: str) -> str:
    # Reversible-looking display is not needed, but output paths must not collide.
    import hashlib
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "_", ip).strip("._-")[:70] or "ip"
    return f"{readable}_{hashlib.sha256(ip.encode('utf-8')).hexdigest()[:8]}"


def build_workbench_registry(reports: list[dict[str, Any]], libraries: list[dict[str, Any]],
                             base: Path, formal_root: Path | None,
                             formal_manifest: str = "") -> tuple[dict[str, Any], list[str]]:
    """Create a candidate registry without changing any existing workbench configuration."""
    lib_by_id = {str(item["library_id"]): item for item in libraries}
    owners: dict[str, set[str]] = defaultdict(set)
    for report in reports:
        for library_id in report["libraries"]:
            owners[library_id].add(report["ip"])
    issues = [f"Library {library_id} 对应多个业务 IP（{', '.join(sorted(ips))}）；工作台登记候选已跳过"
              for library_id, ips in sorted(owners.items()) if len(ips) > 1]
    entries = []
    for report in reports:
        for library_id in report["libraries"]:
            if len(owners[library_id]) != 1:
                continue
            library = lib_by_id[library_id]
            vendor, _, library_name = library_id.partition(".")
            entry = {"id": _safe_output_name(report["ip"] + ":" + library_id),
                     "name": report["ip"], "business_ip": report["ip"],
                     "library_id": library_id, "vendor": vendor,
                     "library_name": str(library.get("library_name") or library_name or library_id),
                     "mapping_basis": report["mapping_basis"],
                     "raw_versions": [{"id": str(delivery["id"]),
                                       "path": str(config_path(str(delivery["root"]), base)),
                                       "delivery_order": delivery["order"]}
                                      for delivery in library.get("deliveries") or []],
                     "checks": {}}
            if formal_root is not None:
                entry["formal_nl_root"] = str(formal_root)
            if formal_manifest:
                entry["formal_manifest"] = str(config_path(formal_manifest, base))
                entry["formal_groups"] = list(report.get("formal_groups") or [])
            entries.append(entry)
    return {"ips": entries}, issues


def run_roster(config_file: Path, output: Path, *, compare: bool = True,
               max_entries: int = 200000) -> dict[str, Any]:
    """Drive ALL requested IPs from ipall.list, with explicit or source-proven mapping."""
    config_file = config_file.resolve()
    config = json.loads(config_file.read_text(encoding="utf-8-sig"))
    base = config_file.parent
    if not config.get("ip_list"):
        return run_context(config, base, output, compare=compare, max_entries=max_entries)
    ips = read_ip_roster(config_path(str(config["ip_list"]), base))
    raw_manifest = str(config.get("formal_manifest") or "").strip()
    if not raw_manifest:
        raise ValueError("批量模式必须配置 formal_manifest（你的第二份正式文件清单）")
    manifest_groups, manifest_errors = _read_manifest_groups(config_path(raw_manifest, base))
    libraries = config.get("libraries") or []
    discovery_issues: list[str] = []
    if not libraries and config.get("raw_root"):
        libraries, discovery_issues = discover_raw_libraries(config_path(str(config["raw_root"]), base))
    elif not libraries:
        raise ValueError("需要配置 raw_root（自动发现）或 libraries（复杂目录手工登记一次）")
    ids = [str(lib.get("library_id") or "") for lib in libraries]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("libraries 的 library_id 不可为空或重复")
    lib_by_id = {lib["library_id"]: lib for lib in libraries}
    ip_map = config.get("ip_library_map") or {}
    if not isinstance(ip_map, dict):
        raise ValueError("ip_library_map 应为 {IP: [LibraryID]} 字典")
    unknown_ips = set(ip_map) - set(ips)
    if unknown_ips:
        raise ValueError(f"ip_library_map 里有不在 ipall.list 的 IP：{sorted(unknown_ips)}")
    formal_root = config_path(str(config["formal_root"]), base) if config.get("formal_root") else None
    group_map = config.get("formal_group_map") or {}
    output.mkdir(parents=True, exist_ok=True)
    cached: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    rows: list[dict[str, Any]] = []
    all_reports: list[dict[str, Any]] = []
    for ip in ips:
        group_names = group_map.get(ip, [ip])
        if isinstance(group_names, str):
            group_names = [group_names]
        group_names = list(dict.fromkeys(group_names))
        group_rows = [item for name in group_names for item in manifest_groups.get(name, [])]
        warnings: list[str] = []
        if not group_rows:
            warnings.append("正式文件清单未找到对应 IP 分组")
        if ip in ip_map:
            chosen = ip_map[ip]
            if isinstance(chosen, str):
                chosen = [chosen]
            chosen = list(dict.fromkeys(chosen))
            missing = set(chosen) - set(lib_by_id)
            if missing:
                raise ValueError(f"{ip} 的 Library 映射不存在：{sorted(missing)}")
            basis = "EXPLICIT_MAPPING"
        else:
            linked, linked_issues = _formal_group_sources(group_rows, formal_root, libraries, base)
            warnings.extend(linked_issues)
            exact = [lib["library_id"] for lib in libraries if _exact_name_match(ip, lib)]
            if linked_issues:
                chosen, basis = [], "AMBIGUOUS_FORMAL_SOURCE"
            elif linked:
                chosen, basis = linked, "FORMAL_REAL_SOURCE"
            elif len(exact) == 1:
                chosen, basis = exact, "EXACT_LIBRARY_NAME"
            elif len(exact) > 1:
                chosen, basis = [], "AMBIGUOUS_NAME"
                warnings.append(f"库名称相同且不唯一：{exact}")
            else:
                chosen, basis = [], "UNMAPPED"
                warnings.append("业务 IP 名与 RAW Library 名不同，且没有可验证正式来源；需要确认一次映射")
        status = "READY" if chosen and group_rows else "PARTIAL" if chosen else "UNMAPPED"
        ip_path = f"ips/{_safe_output_name(ip)}"
        report: dict[str, Any] = {"ip": ip, "mapping_basis": basis, "libraries": chosen,
                                  "formal_groups": group_names, "formal_records": len(group_rows),
                                  "status": status, "warnings": warnings,
                                  "detail_path": ip_path if chosen else ""}
        if chosen:
            context = {"ip_name": ip, "libraries": [lib_by_id[name] for name in chosen],
                       "formal_manifest": config["formal_manifest"], "formal_groups": group_names,
                       "formal_root": config.get("formal_root")}
            ip_summary = run_context(context, base, output / ip_path,
                                     compare=compare, max_entries=max_entries,
                                     cached_histories=cached)
            report["summary"] = ip_summary
        all_reports.append(report)
        rows.append({"IP": ip, "Library": ", ".join(chosen), "匹配依据": basis,
                     "结果状态": status, "正式清单条数": len(group_rows),
                     "明细目录": ip_path if chosen else "",
                     "问题": "; ".join(warnings)})
    csv_save(output / "ip_overview.csv", rows,
             ["IP", "Library", "匹配依据", "结果状态", "正式清单条数", "明细目录", "问题"])
    registry, registry_issues = build_workbench_registry(all_reports, libraries, base, formal_root, raw_manifest)
    registry_path = output / "workbench_registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_json = {"schema": "ip_roster_history.v1", "ip_list": str(config["ip_list"]),
                   "formal_manifest": raw_manifest, "requested_ip_count": len(ips),
                   "ready_count": sum(r["status"] == "READY" for r in all_reports),
                   "unmapped_count": sum(r["status"] == "UNMAPPED" for r in all_reports),
                   "ip_results": all_reports, "manifest_errors": manifest_errors,
                   "discovery_issues": discovery_issues,
                   "workbench_registry": str(registry_path), "workbench_registry_issues": registry_issues,
                   "unlisted_formal_groups": sorted(set(manifest_groups) - {
                       name for ip in ips for name in ([group_map.get(ip)] if isinstance(group_map.get(ip), str)
                                                      else group_map.get(ip, [ip]))})}
    (output / "ip_overview.json").write_text(json.dumps(report_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"requested_ip_count": len(ips), "ready_count": report_json["ready_count"],
            "unmapped_count": report_json["unmapped_count"],
            "manifest_errors": manifest_errors, "discovery_issues": discovery_issues,
            "workbench_registry": str(registry_path), "workbench_registry_issues": registry_issues,
            "overview": str(output / "ip_overview.csv")}


def run(config_file: Path, output: Path, *, compare: bool = True,
        max_entries: int = 200000) -> dict[str, Any]:
    config_file = config_file.resolve()
    config = json.loads(config_file.read_text(encoding="utf-8-sig"))
    return run_context(config, config_file.parent, output, compare=compare, max_entries=max_entries)


def main() -> int:
    parser = argparse.ArgumentParser(description="按文件出现记录计算最新/次新，比较内容，核对正式文件清单")
    parser.add_argument("--config", required=True, type=Path, help="配置文件；可使用 ip_list + formal_manifest 批量模式")
    parser.add_argument("--out", required=True, type=Path, help="结果输出目录")
    parser.add_argument("--no-compare", action="store_true", help="只找版本，不读取文件内容")
    parser.add_argument("--max-entries", type=int, default=200000, help="每次交付的扫描条目上限")
    args = parser.parse_args()
    if args.max_entries <= 0:
        parser.error("--max-entries 必须大于 0")
    try:
        summary = run_roster(args.config, args.out, compare=not args.no_compare, max_entries=args.max_entries)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as err:
        parser.exit(2, f"失败：{err}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n输出目录：{args.out.resolve()}（批量模式查看 ip_overview.csv）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
