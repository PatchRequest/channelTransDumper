"""Command line of the benchmark: snapshot, pool, judging rounds, evaluate."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from ..db import DatabaseError, connect_read_only
from ..embedding import LocalEmbedder
from . import dataset, judging, runner, snapshot
from .variants import VARIANTS

BENCHMARK_DIR = Path("benchmark")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="channeltrans-bench", description=__doc__)
    parser.add_argument("--cases", type=Path, default=BENCHMARK_DIR / "cases.json")
    parser.add_argument("--judgments", type=Path, default=BENCHMARK_DIR / "judgments.json")
    commands = parser.add_subparsers(dest="command", required=True)

    snap = commands.add_parser("snapshot", help="freeze a consistent copy of a database")
    snap.add_argument("source", type=Path)
    snap.add_argument("destination", type=Path)

    variants = ",".join(VARIANTS)
    pool = commands.add_parser("pool", help="write unjudged candidates for relevance judging")
    pool.add_argument("--db", type=Path, required=True, help="snapshot to query")
    pool.add_argument("--variants", default=variants)
    pool.add_argument("--depth", type=int, default=30)
    pool.add_argument("--split", choices=["dev", "test"])
    pool.add_argument("--kind", choices=["fact", "sweep"], help="only cases of this kind")
    pool.add_argument("--out", type=Path, required=True)

    jp = commands.add_parser("judge-pack", help="split a pool into judge packages with controls")
    jp.add_argument("--db", type=Path, required=True, help="snapshot the pool was built on")
    jp.add_argument("--pool", type=Path, required=True)
    jp.add_argument("--out", type=Path, required=True, help="new directory for the packages")
    jp.add_argument("--size", type=int, default=judging.PACKAGE_SIZE, help="candidates per package")
    jp.add_argument("--seed", type=int, default=0)

    jc = commands.add_parser("judge-collect", help="check graded packages, write grades for import")
    jc.add_argument("dir", type=Path, help="directory written by judge-pack, with grades-NN.json")

    imp = commands.add_parser("import-judgments", help="merge graded pool entries")
    imp.add_argument("grades", type=Path, nargs="+", help="JSON: case ID → span key → grade")

    ev = commands.add_parser("evaluate", help="metric table per variant")
    ev.add_argument("--db", type=Path, required=True, help="snapshot to query")
    ev.add_argument("--variants", default=variants)
    ev.add_argument("--split", choices=["dev", "test"], required=True)
    ev.add_argument("--record", metavar="NOTE", help="append the table to benchmark/RESULTS.md")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        _run(args)
    except (snapshot.SnapshotError, DatabaseError, ValueError, KeyError) as exc:
        sys.exit(f"Error: {exc}")


def _run(args: argparse.Namespace) -> None:
    if args.command == "snapshot":
        print(json.dumps(snapshot.create_snapshot(args.source, args.destination), indent=2))
        return
    if args.command == "judge-collect":
        _judge_collect(args)
        return
    if args.command == "import-judgments":
        judgments = dataset.load_judgments(args.judgments)
        added = sum(
            runner.merge_grades(judgments, json.loads(path.read_text())) for path in args.grades
        )
        dataset.save_judgments(args.judgments, judgments)
        print(f"Added {added} judgments.")
        return

    snapshot.load_manifest(args.db)  # only frozen snapshots are measured
    if args.command == "judge-pack":
        with closing(connect_read_only(args.db)) as conn:
            _judge_pack(
                args, conn, dataset.load_cases(args.cases), dataset.load_judgments(args.judgments)
            )
        return
    cases = [
        c
        for c in dataset.load_cases(args.cases)
        if args.split in (None, c.split) and getattr(args, "kind", None) in (None, c.kind)
    ]
    judgments = dataset.load_judgments(args.judgments)
    variants = args.variants.split(",")
    unknown = set(variants) - VARIANTS.keys()
    if unknown:
        raise ValueError(f"Unknown variants: {', '.join(sorted(unknown))}")
    embedder = LocalEmbedder()
    with closing(connect_read_only(args.db)) as conn:
        if args.command == "pool":
            pool = runner.build_pool(conn, embedder, cases, judgments, variants, args.depth)
            args.out.write_text(json.dumps(pool, indent=1, ensure_ascii=False) + "\n")
            print(f"{sum(len(c['candidates']) for c in pool)} candidates in {len(pool)} cases.")
            return
        evaluation = runner.evaluate(conn, embedder, cases, judgments, variants)
    table = runner.format_table(evaluation.rows)
    skipped = (
        f"Skipped {len(evaluation.unjudged_cases)} cases without relevant judgments: "
        + ", ".join(evaluation.unjudged_cases)
        if evaluation.unjudged_cases
        else "All cases judged."
    )
    print(table, skipped, sep="\n\n")
    if args.record:
        _record(args, table, skipped)


def _judge_pack(
    args: argparse.Namespace,
    conn: sqlite3.Connection,
    cases: list[dataset.Case],
    judgments: dataset.Judgments,
) -> None:
    pool = json.loads(args.pool.read_text())
    packed = judging.pack(conn, pool, cases, judgments, size=args.size, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=False)
    template = (BENCHMARK_DIR / "judge-prompt.md").read_text()
    for number, package in enumerate(packed.packages):
        path = args.out / f"package-{number:02d}.json"
        path.write_text(json.dumps(package, indent=1, ensure_ascii=False) + "\n")
        prompt = template.replace("{PACKAGE}", str(path.resolve())).replace(
            "{GRADES}", str((args.out / f"grades-{number:02d}.json").resolve())
        )
        (args.out / f"prompt-{number:02d}.md").write_text(prompt)
        print(f"package-{number:02d}: {sum(len(c['candidates']) for c in package)} candidates")
    manifest = packed.manifest | {"pool": str(args.pool.resolve()), "packages": len(packed.packages)}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"{len(manifest['controls'])} controls, {len(manifest['overlap'])} candidates graded twice. "
          "Give each judge its prompt-NN.md, then run judge-collect.")


def _judge_collect(args: argparse.Namespace) -> None:
    manifest = json.loads((args.dir / "manifest.json").read_text())
    count = manifest["packages"]
    packages = [json.loads((args.dir / f"package-{n:02d}.json").read_text()) for n in range(count)]
    grades = [json.loads((args.dir / f"grades-{n:02d}.json").read_text()) for n in range(count)]
    pool = json.loads(Path(manifest["pool"]).read_text())
    collected = judging.collect(
        packages, grades, manifest, pool, dataset.load_judgments(args.judgments)
    )
    for control in collected.failed_controls:
        print(f"control failed: package {control['package']}, case {control['case_id']}, "
              f"expected {control['expect']}, got {control['grade']} ({control['key']})")
    equal, pairs = collected.agreement
    print(f"controls passed: {collected.controls - len(collected.failed_controls)}/{collected.controls}; "
          f"judges agreed on {equal}/{pairs} candidates graded twice, "
          f"{collected.two_apart} two grades apart")
    out = args.dir / "import.json"
    out.write_text(json.dumps(collected.grades, indent=1) + "\n")
    print(f"{sum(map(len, collected.grades.values()))} grades written to {out}; "
          "review the checks above, then run import-judgments on it.")


def _record(args: argparse.Namespace, table: str, skipped: str) -> None:
    manifest = snapshot.load_manifest(args.db)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src"], capture_output=True, text=True, check=True
    ).stdout.strip()
    entry = (
        f"\n## {datetime.now(UTC).date()} – {args.record}\n\n"
        f"- code: `{commit}`{' (uncommitted changes in src/)' if dirty else ''}\n"
        f"- snapshot: `{args.db.name}` ({manifest['passages']} passages, "
        f"created {manifest['created_at']})\n"
        f"- split: {args.split}\n"
        f"- cases: `{args.cases}`, judgments: `{args.judgments}` "
        f"(fingerprint `{dataset.fingerprint(args.cases, args.judgments)}`)\n"
        f"- {skipped}\n\n{table}\n"
    )
    with (BENCHMARK_DIR / "RESULTS.md").open("a") as results:
        results.write(entry)
