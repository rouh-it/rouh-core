"""``python manage.py synapse_bench``: Synapse measured on fictional data, for nothing, whole.

Petar, by voice on 3 October 2026: a repeatable benchmark that loads fictional items into a
throwaway dataset, with the embeddings stubbed so it costs nothing, times link candidates and
search at the median and the 95th percentile, and fails when link candidates take over 50 ms or
search over 300 ms at the 95th percentile. On 4 October 2026 (card 1125) it became the measure of
six scaling changes, one at a time, so it measures whether the answers are right too: planted
cases for ranking, permissions, links and traversal, every result checked again for leaks, and
the CPU, memory and disk it took (`rouh/synapse/benchmark.py` says what each case is).

    python manage.py synapse_bench                               # 10,000 then 100,000
    python manage.py synapse_bench --sizes 100000 --keep /srv/bench/100k --json out.json
    python manage.py synapse_bench --variant before='{}' --variant after='{"words_backend": "bm25"}'
    python manage.py synapse_bench --gate --gate-sizes 100000 --keep ~/synapse-bench/100k --pg-search
                                                                 # the nightly run's scale check

- A PostgreSQL of its own in a folder (`rouh/testing/postgres.py`), on the same settings as Rouh's
  own (PostgreSQL's defaults), migrated by this checkout: nothing touches Rouh's database, and
  the folder is gone afterwards unless `--keep` names it (then it stays, stopped, and a second
  run loads only what is missing). `--pg-search` starts it with ParadeDB's pg_search loaded.
- Each `--variant label=json` is a Tune override measured on the same data in the same run, so a
  change is measured against what it changes with nothing else moving; none means one, as tuned.
- A size the disk or memory cannot safely take is not tried: it is reported, with why (`--max-disk-gb`).
- Exit 1 when a limit is broken at `--check-at` items or more, or when anything leaked, at any size.

The inner run is this same command with `--inside`, in a process pointed at the throwaway database,
so it times whatever code is in the checkout it is run from.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rouh.synapse.benchmark import LIMITS

REPO = Path(__file__).resolve().parents[3]
#: Card 1125's scale gate (Petar, 4 October 2026): targets to validate at these sizes, not promises.
GATE_SIZES = (1_000_000, 10_000_000, 50_000_000)


class Command(BaseCommand):
    help = "Measure Synapse's search, link candidates, permissions and traversal on fictional items."

    def add_arguments(self, parser):
        parser.add_argument("--sizes", default="10000,100000", help="the owner's item counts, rising, comma separated")
        parser.add_argument("--samples", type=int, default=200, help="link candidate and search runs per size")
        parser.add_argument("--json", default="", help="write every number here")
        parser.add_argument("--keep", default="", help="a folder to keep the database in; run again with the "
                                                        "same folder and only what is missing is loaded")
        parser.add_argument("--timeout-s", type=int, default=30, help="one statement's limit, seconds")
        parser.add_argument("--variant", action="append", default=[], help="label=json Tune override, repeatable")
        parser.add_argument("--stage", default="", help="a name for this run, written into the results")
        parser.add_argument("--pg-search", action="store_true", help="start the database with pg_search loaded")
        parser.add_argument("--max-disk-gb", type=float, default=150, help="never grow the database past this")
        parser.add_argument("--mwm-mb", type=int, default=4096, help="maintenance_work_mem for building indexes")
        parser.add_argument("--writes", action="store_true", help="measure storing and the queue too (card 1125 change 5)")
        parser.add_argument("--hnsw", default="", help="rebuild the vector index with these HNSW settings, "
                                                       "an experiment: m=32,ef_construction=128")
        parser.add_argument("--hot-days", type=int, default=0, help="partial indexes over the last N days (change 4); 0 drops them")
        parser.add_argument("--check-at", type=int, default=100_000, help="the limits apply from this many items")
        parser.add_argument("--gate-sizes", default="", help="the gate at these sizes instead of 1, 10 and 50 million "
                                                              "(the nightly run's: 100000, since it was decided on 4 October "
                                                              "2026 that no million-item dataset is built)")
        parser.add_argument("--gate", action="store_true", help="card 1125's scale gate: 1, 10 and 50 million items, "
                                                                "the limits checked from 1,000,000, any size the "
                                                                "machine cannot safely take said and not tried")
        parser.add_argument("--inside", action="store_true", help=argparse_hidden())
        parser.add_argument("--out", default="", help=argparse_hidden())
        parser.add_argument("--postmaster", type=int, default=0, help=argparse_hidden())
        parser.add_argument("--data-dir", default="", help=argparse_hidden())

    def handle(self, *args, **o):
        if o["gate"]:
            gate = sorted(int(x) for x in str(o["gate_sizes"] or "").split(",") if x.strip()) or list(GATE_SIZES)
            o["sizes"], o["check_at"] = ",".join(str(x) for x in gate), gate[0]
        sizes = sorted(int(x) for x in str(o["sizes"]).split(",") if x.strip())
        variants = parse_variants(o["variant"])
        if o["inside"]:
            from rouh.synapse import benchmark

            got = benchmark.inside(sizes, int(o["samples"]), int(o["timeout_s"]), self.stdout.write,
                                   variants=variants, postmaster=o["postmaster"] or None, mwm_mb=int(o["mwm_mb"]),
                                   max_disk_gb=float(o["max_disk_gb"]), data_dir=o["data_dir"], writes=o["writes"],
                                   hot_days=int(o["hot_days"]), hnsw=o["hnsw"])
            Path(o["out"]).write_text(json.dumps(got, indent=1, default=str))
            return
        from rouh.testing import postgres

        folder = (Path(o["keep"]) if o["keep"] else Path(tempfile.mkdtemp(prefix="synapse-bench-"))).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        data = folder / "pg" / "data"
        if o["keep"] and (data / "postmaster.pid").exists():
            # Kept from an earlier run and still running: stopped first, then started again below.
            subprocess.run([os.path.join(postgres.bin_dir(), "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
                           capture_output=True, timeout=120)
        # A kept database that once had pg_search must load it ever after, or every query fails.
        marker = folder / "pg-search-loaded"
        if o["pg_search"]:
            marker.write_text("pg_search is installed in this database: it is started with it loaded\n")
        o["pg_search"] = o["pg_search"] or marker.exists()
        extra = "-c shared_preload_libraries=pg_search" if o["pg_search"] else ""
        cluster = postgres.start(folder / "pg", name="bench", options=extra)
        command = " ".join(["python manage.py synapse_bench"] + [a for a in sys.argv[2:]])
        try:
            env = {**os.environ, **cluster.env(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
            self.stdout.write(f"A throwaway database in {folder}; migrating it.")
            postgres.migrate(env)
            pm = int((data / "postmaster.pid").read_text().split()[0])
            out = folder / "result.json"
            done = subprocess.run([sys.executable, "manage.py", "synapse_bench", "--inside", "--sizes",
                                   ",".join(map(str, sizes)), "--samples", str(o["samples"]),
                                   "--timeout-s", str(o["timeout_s"]), "--out", str(out), "--postmaster", str(pm),
                                   "--mwm-mb", str(o["mwm_mb"]), "--max-disk-gb", str(o["max_disk_gb"]),
                                   "--data-dir", str(data)] + (["--writes"] if o["writes"] else []) + ["--hot-days", str(o["hot_days"])] + (["--hnsw", o["hnsw"]] if o["hnsw"] else [])
                                  + [f"--variant={v['label']}={json.dumps(v['override'])}" for v in variants],
                                  cwd=str(REPO), env=env)
            if done.returncode != 0 or not out.exists():
                raise CommandError("the benchmark itself stopped; see above")
            got = json.loads(out.read_text())
        finally:
            postgres.stop(cluster)
            if not o["keep"]:
                shutil.rmtree(folder, ignore_errors=True)
        got.update({"stage": o["stage"], "code": _commit(), "command": command, "limits": LIMITS,
                    "check_at": o["check_at"], "pg_search_loaded": bool(o["pg_search"])})
        failed = check(got, o["check_at"])
        got["passed"] = not failed
        got["failed"] = failed
        got["verdict"] = verdict(got)
        if o["json"]:
            Path(o["json"]).write_text(json.dumps(got, indent=1, default=str))
        self.stdout.write(table(got))
        self.stdout.write("\n".join(got["verdict"]))
        if failed:
            self.stdout.write("FAILED: " + "; ".join(failed))
            sys.exit(1)
        self.stdout.write("Passed.")


def argparse_hidden():
    import argparse
    return argparse.SUPPRESS


def parse_variants(given: list[str]) -> list[dict]:
    out = []
    for v in given:
        label, _, override = v.partition("=")
        try:
            parsed = json.loads(override or "{}")
        except ValueError as exc:
            raise CommandError(f"--variant {label}: not JSON: {exc}") from exc
        out.append({"label": label.strip() or f"v{len(out) + 1}", "override": parsed})
    return out or [{"label": "as_tuned", "override": {}}]


def _commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def check(got: dict, check_at: int) -> list[str]:
    failed = []
    for size in got["sizes"]:
        if not size.get("variants"):
            continue
        for label, v in size["variants"].items():
            where = f"{label} at {size['items']:,} items"
            if v["leaks"]["total"]:
                failed.append(f"{where}: {v['leaks']['total']} leaks ({json.dumps(v['leaks'])})")
            if size["items"] < check_at:
                continue
            lc, se = v["link_candidates"]["p95_ms"], v["search"]["p95_ms"]
            if lc is None or lc > LIMITS["link_candidates_p95_ms"]:
                failed.append(f"{where}: link candidates p95 {lc} ms, over {LIMITS['link_candidates_p95_ms']} ms")
            if se is None or se > LIMITS["search_p95_ms"]:
                failed.append(f"{where}: search p95 {se} ms, over {LIMITS['search_p95_ms']} ms")
            for name in ("link_candidates", "search", "search_minority_reader"):
                if v[name].get("errors"):
                    failed.append(f"{where}: {name} failed {v[name]['errors']} times")
    return failed


def table(got: dict) -> str:
    lines = [f"Synapse benchmark {got.get('stage') or ''}, code {got.get('code') or '?'}, {got.get('samples')} runs each",
             f"{'items':>10} {'variant':<16} | {'link p50':>8} {'p95':>6} | {'search p50':>10} {'p95':>6} | "
             f"{'minority p95':>12} | {'ranking':>7} {'links':>6} {'walk':>5} | {'leaks':>5}"]
    for s in got["sizes"]:
        if not s.get("variants"):
            lines.append(f"{s['items']:>10,} not measured (database about {s.get('estimated_db_gb')} GB): {s.get('why')}")
            continue
        for label, v in s["variants"].items():
            qv = v["quality"]
            lines.append(f"{s['items']:>10,} {label:<16} | {_ms(v['link_candidates']['p50_ms']):>8} "
                         f"{_ms(v['link_candidates']['p95_ms']):>6} | {_ms(v['search']['p50_ms']):>10} "
                         f"{_ms(v['search']['p95_ms']):>6} | {_ms(v['search_minority_reader']['p95_ms']):>12} | "
                         f"{qv['ranking_hit_rate']:>7} {qv['link_candidate_recall']:>6} {qv['walk_recall']!s:>5} | "
                         f"{v['leaks']['total']:>5}")
    lines.append(f"Limits from {got.get('check_at', 0):,} items: link candidates p95 <= "
                 f"{LIMITS['link_candidates_p95_ms']} ms, search p95 <= {LIMITS['search_p95_ms']} ms; no leaks anywhere.")
    return "\n".join(lines)


def verdict(got: dict) -> list[str]:
    """One line per size and configuration: passed, failed and why, or not measured and why."""
    out = []
    for s in got["sizes"]:
        if not s.get("variants"):
            out.append(f"{s['items']:,} items: NOT MEASURED, {s.get('why')} (about {s.get('estimated_db_gb')} GB, "
                       f"at the {s.get('bytes_per_item')} bytes an item measured so far)")
            continue
        for label, v in s["variants"].items():
            lc, se = v["link_candidates"]["p95_ms"], v["search"]["p95_ms"]
            ok = (lc is not None and lc <= LIMITS["link_candidates_p95_ms"] and se is not None
                  and se <= LIMITS["search_p95_ms"] and not v["leaks"]["total"])
            out.append(f"{s['items']:,} items, {label}: {'PASS' if ok else 'FAIL'}: link candidates p95 {lc} ms "
                       f"(target {LIMITS['link_candidates_p95_ms']}), search p95 {se} ms (target "
                       f"{LIMITS['search_p95_ms']}), leaks {v['leaks']['total']}")
    return out


def _ms(v) -> str:
    return "-" if v is None else f"{v:g}"
