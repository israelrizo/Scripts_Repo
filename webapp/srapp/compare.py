"""Run comparison against a baseline: per-transaction deltas, verdicts, trend and CSV export."""
import csv
import io
import json

from . import projects
from .config import Config
from .report import _script_name

METRICS = {"p95": "p95", "avg": "avg", "p90": "p90", "p99": "p99"}


def _bpath(project):
    d = Config.INSTANCE_DIR / "baselines"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{project}.json"


def baselines(project):
    p = _bpath(project)
    return json.loads(p.read_text()) if p.exists() else {}


def set_baseline(project, run_name):
    projects.result_dir(project, run_name)
    b = baselines(project)
    b[_script_name(run_name)] = run_name
    _bpath(project).write_text(json.dumps(b, indent=2))


def default_selection(project):
    results = [r for r in projects.list_results(project) if r["has_report"]]
    if not results:
        return None, []
    latest = results[0]["name"]
    script = _script_name(latest)
    base = baselines(project).get(script)
    if not base or base == latest:
        same = [r["name"] for r in results if _script_name(r["name"]) == script and r["name"] != latest]
        base = same[0] if same else None
    return base, [latest]


def _pct(new, old):
    if new is None or old in (None, 0):
        return None
    return round((new - old) * 100.0 / old, 1)


def build(project, base, others, metric="p95", threshold=10.0):
    metric = METRICS.get(metric, "p95")
    runs = [r for r in [base] + [o for o in others if o != base] if r]
    stats = {r: projects.result_stats(project, r) for r in runs}
    tx_names = sorted({t for s in stats.values() for t in s if t != "Total"})
    b = stats.get(base, {}) if base else {}

    rows = []
    counts = {r: {"regressed": 0, "improved": 0, "same": 0} for r in runs[1:]}
    for name in ["Total"] + tx_names:
        cells = []
        for r in runs:
            s = stats[r].get(name)
            cell = {"run": r, "s": s, "delta": None, "err_delta": None, "verdict": "missing" if not s else "base"}
            if s and r != base and base:
                bs = b.get(name)
                if not bs:
                    cell["verdict"] = "new"
                else:
                    cell["delta"] = _pct(s.get(metric), bs.get(metric))
                    cell["err_delta"] = round((s.get("error_pct") or 0) - (bs.get("error_pct") or 0), 2)
                    worse = (cell["delta"] or 0) > threshold or cell["err_delta"] > 1
                    better = (cell["delta"] or 0) < -threshold and cell["err_delta"] <= 0
                    cell["verdict"] = "regressed" if worse else ("improved" if better else "same")
                    if name != "Total":
                        counts[r][cell["verdict"]] += 1
            cells.append(cell)
        rows.append({"name": name, "cells": cells})

    trend = []
    if base or runs:
        script = _script_name(base or runs[0])
        for r in sorted(projects.list_results(project), key=lambda x: x["mtime"]):
            if _script_name(r["name"]) == script and r["summary"]:
                trend.append({"run": r["name"], "mtime": r["mtime"], **r["summary"]})
    return {"runs": runs, "base": base, "metric": metric, "threshold": threshold, "rows": rows,
            "counts": counts, "trend": trend, "stats": stats}


def to_csv(data):
    buf = io.StringIO()
    w = csv.writer(buf)
    head = ["transaction"]
    for r in data["runs"]:
        short = r.replace("Ejecucion_", "")
        head += [f"{short} samples", f"{short} error_pct", f"{short} avg", f"{short} p90", f"{short} p95",
                 f"{short} p99", f"{short} tps", f"{short} delta_{data['metric']}_pct", f"{short} verdict"]
    w.writerow(head)
    for row in data["rows"]:
        line = [row["name"]]
        for c in row["cells"]:
            s = c["s"] or {}
            line += [s.get("samples"), s.get("error_pct"), s.get("avg"), s.get("p90"), s.get("p95"), s.get("p99"),
                     s.get("tps"), c["delta"], c["verdict"]]
        w.writerow(line)
    return buf.getvalue()
