"""命令行入口。本阶段不写网站目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from karazhan_tool.analyze import load_rules, normalize_unordered, run_analysis
from karazhan_tool.compare import summarize_diff
from karazhan_tool.config import RaidConfig, load_config
from karazhan_tool.golden import extract_metrics, load_json
from karazhan_tool.hashing import canonical_sha256, sha256_file
from karazhan_tool.items import export_arcane_items, write_table
from karazhan_tool.parser.evidence import read_lines
from karazhan_tool.parser.events import iter_events, summarize
from karazhan_tool.parser.roster import freeze_roster, roster_to_dict
from karazhan_tool.render.model import build_model
from karazhan_tool.review_pack import build_review_pack, dump_pack
from karazhan_tool.site import check_gate, publish
from karazhan_tool.validate import validate


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="karazhan_tool", description="卡塔赞战斗日志本地分析工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    roster = subparsers.add_parser("roster", help="冻结本场玩家名单")
    roster.add_argument("--config", required=True, type=Path)
    roster.add_argument("--out", type=Path)

    digest = subparsers.add_parser("hash-inputs", help="计算输入文件 SHA-256")
    digest.add_argument("--config", required=True, type=Path)

    freeze = subparsers.add_parser("freeze-baseline", help="把现有分析与网页快照冻结为黄金基准")
    freeze.add_argument("--config", required=True, type=Path)
    freeze.add_argument("--force", action="store_true")

    parsed = subparsers.add_parser("parse", help="把战斗日志解析为本地事件，不写网站")
    parsed.add_argument("--config", required=True, type=Path)
    parsed.add_argument("--out", type=Path)

    analyzed = subparsers.add_parser("analyze", help="运行规则，输出分析、发现与黄金差异，不写网站")
    analyzed.add_argument("--config", required=True, type=Path)
    analyzed.add_argument("--rules", type=Path)

    for name, text in (
        ("render", "由分析结果生成网站展示数据到 output/，不写网站"),
        ("validate", "自动校验分析、发现与展示数据"),
        ("review-pack", "生成 AI 精简复核包"),
        ("run", "依次执行 analyze、render、validate、review-pack"),
    ):
        command = subparsers.add_parser(name, help=text)
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--rules", type=Path)

    published = subparsers.add_parser("publish", help="门禁全部通过且显式确认后写入 reports/")
    published.add_argument("--config", required=True, type=Path)
    published.add_argument("--confirm", action="store_true", help="用户已明确授权发布")

    evidence = subparsers.add_parser("evidence", help="按行号或发现编号取出少量原始日志")
    evidence.add_argument("--config", required=True, type=Path)
    evidence.add_argument("--line", type=int)
    evidence.add_argument("--finding")
    evidence.add_argument("--before", type=int, default=2)
    evidence.add_argument("--after", type=int, default=2)
    evidence.add_argument("--raw", action="store_true")

    resists = subparsers.add_parser("item-resists", help="从物品数据库导出装备自带奥抗表")
    resists.add_argument("--db", required=True, type=Path)
    resists.add_argument("--config", required=True, type=Path, action="append", help="可多次给出；扫描其 CustomData 中出现过的装备")
    resists.add_argument("--out", type=Path, default=Path("config") / "equipment_arcane_resistance.json")

    args = parser.parse_args(argv)
    if args.command == "item-resists":
        files = []
        for path in args.config:
            config = load_config(path)
            listed = (config.raw.get("analysis") or {}).get("custom_data_files") or [str(config.custom_data)]
            files.extend(Path(item) for item in listed if Path(item) not in files)
        table = export_arcane_items(args.db, files)
        write_table(table, args.out)
        resisting = sum(1 for item in table["items"].values() if item["arcane"])
        print(f"已写入 {args.out}：{len(table['items'])} 件按ID查到（{resisting} 件有奥抗），"
              f"{len(table['names'])} 件按名称查到，{len(table['pending'])} 件待补")
        return 0
    if args.command == "roster":
        return _roster(args.config, args.out)
    if args.command == "hash-inputs":
        return _hash_inputs(args.config)
    if args.command == "freeze-baseline":
        return _freeze_baseline(args.config, args.force)
    if args.command == "parse":
        return _parse(args.config, args.out)
    if args.command == "analyze":
        return _analyze(args.config, args.rules)
    if args.command == "render":
        return _render(args.config)
    if args.command == "validate":
        return _validate(args.config, args.rules)
    if args.command == "review-pack":
        return _review_pack(args.config, args.rules)
    if args.command == "run":
        for step in (
            lambda: _analyze(args.config, args.rules),
            lambda: _render(args.config),
            lambda: _validate(args.config, args.rules),
            lambda: _review_pack(args.config, args.rules),
        ):
            code = step()
            if code != 0:
                return code
        print("已完成本地分析。等待 AI 复核 review-pack.json 并写出 review-result.json 后再 publish。")
        return 0
    if args.command == "publish":
        return _publish(args.config, args.confirm)
    if args.command == "evidence":
        if args.finding:
            return _finding_evidence(args.config, args.finding, args.before, args.after)
        if args.line is None:
            parser.error("evidence 需要 --line 或 --finding")
        return _evidence(args.config, args.line, args.before, args.after, args.raw)
    parser.error("未知命令")
    return 2


def _analyze(config_path: Path, rules_path: Path | None) -> int:
    config = load_config(config_path)
    rules = load_rules(rules_path or _repo_root() / "config" / "rules.json")
    frozen = _freeze(config)
    result = run_analysis(config, frozen.roster, rules)
    destination = _repo_root() / "output" / config.date
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "analysis.json").write_text(
        json.dumps(result.report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    _dump(destination / "roster.json", roster_to_dict(frozen.roster, date=config.date, warnings=frozen.warnings))
    _dump(destination / "findings.json", {"schema_version": 1, "date": config.date, "findings": result.findings})
    _dump(destination / "name-issues.json", {"schema_version": 1, "date": config.date, "issues": result.name_issues})
    golden = golden_diff(config.date, result.report, rules)
    _dump(destination / "golden-diff.json", golden)
    ranking = result.report["error_summary"]["ranking"]
    low = sum(1 for item in result.findings if item["confidence"] != "high")
    print(f"已写入 {destination}")
    print(f"发现 {len(result.findings)} 条，非高置信 {low} 条，姓名歧义 {len(result.name_issues)} 处")
    print(f"错误排行第一 {ranking[0]['player']} {ranking[0]['count']} 次")
    if golden["available"]:
        print(f"黄金差异 {golden['total']} 处 {golden['sections']}")
        for item in golden["samples"][:10]:
            print(f"  {item['path']}  {item['expected']} => {item['actual']}")
    return 0


def _stage(config) -> Path:
    return _repo_root() / "output" / config.date


def _load_stage(stage: Path, name: str):
    path = stage / name
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {path}，请先运行前一步")
    return load_json(path)


def _render(config_path: Path) -> int:
    config = load_config(config_path)
    stage = _stage(config)
    report = _load_stage(stage, "analysis.json")
    notes = (config.raw.get("analysis") or {}).get("display_notes") or {}
    model = build_model(report, notes)
    site = stage / "site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "data.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    shutil.copyfile(_template_page(), site / "index.html")
    golden = _repo_root() / "tests" / "golden" / config.date / "display.json"
    print(f"已写入 {site}")
    if golden.is_file():
        same = sha256_file(golden) == sha256_file(site / "data.json")
        print("展示数据与黄金快照逐字节一致" if same else "展示数据与黄金快照不一致：%s" % summarize_diff(load_json(golden), model, 5))
    return 0


def _template_page() -> Path:
    return _repo_root() / "templates" / "report.html"


def _validate(config_path: Path, rules_path: Path | None) -> int:
    config = load_config(config_path)
    stage = _stage(config)
    approved = int((config.raw.get("analysis") or {}).get("approved_golden_diffs") or 0)
    result = validate(
        _load_stage(stage, "analysis.json"),
        _load_stage(stage, "findings.json")["findings"],
        _load_stage(stage, "site/data.json"),
        golden=_load_stage(stage, "golden-diff.json"),
        approved_golden_diffs=approved,
        name_issues=_load_stage(stage, "name-issues.json")["issues"],
    )
    _dump(stage / "validation.json", result)
    for item in result["checks"]:
        if not item["ok"] or item["detail"]:
            print(("通过 " if item["ok"] else "失败 ") + item["id"] + ("  " + item["detail"] if item["detail"] else ""))
    print("自动校验通过" if result["ok"] else "自动校验失败：" + "、".join(result["failed"]))
    return 0 if result["ok"] else 1


def _review_pack(config_path: Path, rules_path: Path | None) -> int:
    config = load_config(config_path)
    stage = _stage(config)
    rules_file = rules_path or _repo_root() / "config" / "rules.json"
    analysis = config.raw.get("analysis") or {}
    roster_warnings = _load_stage(stage, "roster.json").get("warnings") or []
    hashes = {
        "combat_log": "sha256:" + _cached_sha(config.combat_log),
        "raw_combat_log": "sha256:" + _cached_sha(config.raw_combat_log),
        "custom_data": "sha256:" + _cached_sha(config.custom_data),
        "config": "sha256:" + sha256_file(config.source_path),
        "rules": "sha256:" + sha256_file(rules_file),
        "code": "sha256:" + _code_sha(),
        "analysis": "sha256:" + sha256_file(stage / "analysis.json"),
        "display": "sha256:" + sha256_file(stage / "site" / "data.json"),
    }
    for path in analysis.get("custom_data_files") or []:
        hashes["custom_data:" + Path(path).name] = "sha256:" + _cached_sha(Path(path))
    table = load_rules(rules_file).get("equipment_arcane_resistance")
    if table:
        hashes["equipment_arcane_resistance"] = "sha256:" + sha256_file(_repo_root() / table)
    pack = build_review_pack(
        date=config.date,
        input_hashes=hashes,
        report=_load_stage(stage, "analysis.json"),
        findings=_load_stage(stage, "findings.json")["findings"],
        name_issues=_load_stage(stage, "name-issues.json")["issues"],
        golden=_load_stage(stage, "golden-diff.json"),
        validation=_load_stage(stage, "validation.json"),
        warnings=list(roster_warnings) + ([analysis["gear_snapshot_note"]] if analysis.get("gear_snapshot_note") else []),
        display_notes=analysis.get("display_notes") or {},
        combat_log=config.combat_log,
    )
    path = stage / "review-pack.json"
    dump_pack(path, pack)
    result_path = stage / "review-result.json"
    print(f"已写入 {path}，{path.stat().st_size} 字节，待复核 {pack['summary']['selected_for_review']} 条，分 {len(pack['findings'])} 组")
    print(f"复核包哈希 sha256:{sha256_file(path)}")
    if result_path.is_file():
        result = load_json(result_path)
        if (result.get("input_hashes") or {}).get("review_pack") != "sha256:" + sha256_file(path):
            print("已有的 review-result.json 对应旧证据包，已失效")
    return 0


def _publish(config_path: Path, confirm: bool) -> int:
    config = load_config(config_path)
    stage = _stage(config)
    problems = check_gate(stage)
    if problems:
        print("禁止发布：")
        for item in problems:
            print("  " + item)
        return 1
    if not confirm:
        print(f"门禁全部通过。需要用户明确授权后加 --confirm 才会写入 reports/{config.date}/")
        return 0
    for path in publish(stage, _repo_root(), config.date, _template_page()):
        print(f"已写入 {path}")
    return 0


def _finding_evidence(config_path: Path, finding_id: str, before: int, after: int) -> int:
    config = load_config(config_path)
    findings = _load_stage(_stage(config), "findings.json")["findings"]
    match = next((item for item in findings if item["finding_id"] == finding_id), None)
    if match is None:
        print(f"没有发现 {finding_id}")
        return 1
    print(f"{match['finding_id']}  {match['player']}  {match['issue']}  置信度 {match['confidence']}")
    for evidence in match.get("evidence_lines", []):
        print(f"[{evidence['purpose']}]")
        for item in read_lines(config.combat_log, evidence["line"], before=before, after=after):
            mark = ">" if item["focus"] else " "
            print(f"{mark} {item['line']}: {item['text']}")
    return 0


def _cached_sha(path: Path) -> str:
    cache_path = _repo_root() / "output" / "hash-cache.json"
    cache = load_json(cache_path) if cache_path.is_file() else {}
    stat = path.stat()
    key = str(path)
    entry = cache.get(key)
    if entry and entry["bytes"] == stat.st_size and entry["mtime_ns"] == stat.st_mtime_ns:
        return entry["sha256"]
    digest = sha256_file(path)
    cache[key] = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return digest


def _code_sha() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def golden_diff(date: str, report: dict, rules: dict) -> dict:
    path = _repo_root() / "tests" / "golden" / date / "analysis.json"
    if not path.is_file():
        return {"available": False, "total": None, "sections": {}, "samples": []}
    paths = rules.get("unordered_golden_paths") or []
    expected = normalize_unordered(load_json(path), paths)
    actual = normalize_unordered(json.loads(json.dumps(report, ensure_ascii=False)), paths)
    summary = summarize_diff(expected, actual)
    summary["available"] = True
    summary["golden_sha256"] = sha256_file(path)
    return summary


def _dump(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _roster(config_path: Path, out_path: Path | None) -> int:
    config = load_config(config_path)
    result = _freeze(config)
    payload = roster_to_dict(result.roster, date=config.date, warnings=result.warnings)
    payload["input_hashes"] = {
        "custom_data": _file_record(config.custom_data),
        "raw_combat_log": _file_record(config.raw_combat_log),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"已写入 {out_path}")
    print(f"冻结名单 {payload['roster_size']} 人")
    if result.roster.logger is not None:
        print(f"记录者 {result.roster.logger.name} {result.roster.logger.guid}")
    for warning in result.warnings:
        print(f"警告：{warning}")
    return _compare_golden_roster(config.golden_analysis, [player.name for player in result.roster.players])


def _parse(config_path: Path, out_path: Path | None) -> int:
    config = load_config(config_path)
    frozen = _freeze(config)
    destination = out_path or (_repo_root() / "output" / config.date / "events.jsonl")
    destination.parent.mkdir(parents=True, exist_ok=True)

    def recorded():
        with destination.open("w", encoding="utf-8") as handle:
            for event in iter_events(
                config.combat_log,
                frozen.roster,
                date=config.date,
                start=config.raid_start,
                end=config.raid_end,
                known_units=config.known_units,
            ):
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
                yield event

    summary = summarize(recorded(), frozen.roster)
    summary["schema_version"] = 1
    summary["date"] = config.date
    summary["window"] = {"start": config.raid_start, "end": config.raid_end}
    summary["roster_size"] = len(frozen.roster.players)
    summary["events_path"] = str(destination)
    summary_path = destination.with_name("parse-summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {destination}")
    print(f"事件 {summary['events']} 条，未识别 {summary['unparsed']} 条，姓名歧义 {summary['ambiguous_names']} 条")
    for item in summary["by_type"].items():
        print(f"{item[1]}	{item[0]}")
    for item in summary["unparsed_templates"]:
        print(f"未识别模板 {item['count']}	{item['template']}")
    return 0


def _evidence(config_path: Path, line: int, before: int, after: int, raw: bool) -> int:
    config = load_config(config_path)
    path = config.raw_combat_log if raw else config.combat_log
    for item in read_lines(path, line, before=before, after=after):
        mark = ">" if item["focus"] else " "
        print(f"{mark} {item['line']}: {item['text']}")
    return 0


def _freeze(config):
    return freeze_roster(
        custom_data=config.custom_data,
        raw_combat_log=config.raw_combat_log,
        date=config.date,
        timezone=config.timezone,
        raid_start=config.raid_start,
        raid_end=config.raid_end,
        zone_names=config.zone_names,
        logger_guid=config.logger_guid,
        logger_name=config.logger_name,
        roster_overrides=config.roster_overrides,
        class_overrides=config.class_overrides,
        encounter_windows=_encounter_windows(config),
    )


def _encounter_windows(config: RaidConfig) -> tuple[tuple[str, str], ...]:
    windows = []
    for item in config.raw.get("encounters") or []:
        for attempt in item.get("attempts") or [item]:
            windows.append((attempt["start"], attempt["end"]))
    return tuple(windows)


def _compare_golden_roster(analysis_path: Path | None, names: list[str]) -> int:
    if analysis_path is None or not analysis_path.is_file():
        print("没有黄金分析 JSON，跳过名单对比")
        return 0
    expected = load_json(analysis_path)["metadata"]["roster"]
    got = set(names)
    wanted = set(expected)
    extra = sorted(got - wanted)
    missing = sorted(wanted - got)
    if not extra and not missing and len(names) == len(expected):
        print(f"与黄金名单一致，共 {len(expected)} 人")
        return 0
    if extra:
        print("多出的名字：" + "、".join(extra))
    if missing:
        print("缺少的名字：" + "、".join(missing))
    return 1


def _hash_inputs(config_path: Path) -> int:
    config = load_config(config_path)
    for label, path in (
        ("combat_log", config.combat_log),
        ("raw_combat_log", config.raw_combat_log),
        ("custom_data", config.custom_data),
    ):
        record = _file_record(path)
        print(f"{label}\t{record['sha256']}\t{record['bytes']}\t{path}")
    return 0


def _freeze_baseline(config_path: Path, force: bool) -> int:
    config = load_config(config_path)
    if config.golden_analysis is None or config.golden_display is None:
        print("日期配置缺少 golden_sources.analysis 或 golden_sources.display")
        return 1
    destination = _repo_root() / "tests" / "golden" / config.date
    destination.mkdir(parents=True, exist_ok=True)
    copies = {
        "analysis.json": config.golden_analysis,
        "display.json": config.golden_display,
    }
    if config.golden_page is not None:
        copies["page.html"] = config.golden_page
    for name, source in copies.items():
        target = destination / name
        if target.exists() and not force:
            print(f"已存在，未覆盖：{target}")
            return 1
        if not source.is_file():
            print(f"找不到黄金来源：{source}")
            return 1
        shutil.copyfile(source, target)
        print(f"已冻结 {source} -> {target}")

    analysis = load_json(destination / "analysis.json")
    display = load_json(destination / "display.json")
    metrics = extract_metrics(analysis)
    if not _write_json(destination / "metrics.json", metrics, force):
        return 1
    hashes = {
        "schema_version": 1,
        "date": config.date,
        "files": {
            name: _file_record(destination / name)
            for name in ("analysis.json", "display.json", "metrics.json", "page.html")
            if (destination / name).is_file()
        },
        "canonical_sha256": {
            "analysis": canonical_sha256(analysis),
            "display": canonical_sha256(display),
            "metrics": canonical_sha256(metrics),
        },
        "external_inputs": {
            "combat_log": _file_record(config.combat_log),
            "raw_combat_log": _file_record(config.raw_combat_log),
            "custom_data": _file_record(config.custom_data),
        },
        "declared_inputs": config.declared_inputs,
        "input_notes": list(config.input_notes),
    }
    if not _write_json(destination / "hashes.json", hashes, force):
        return 1
    first = metrics["error_ranking"][0]
    print(
        f"黄金名单 {metrics['roster_size']} 人，"
        f"错误排行第一 {first['player']} {first['count']} 次"
    )
    return 0


def _write_json(path: Path, payload: dict, force: bool) -> bool:
    if path.exists() and not force:
        print(f"已存在，未覆盖：{path}")
        return False
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True


def _file_record(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
