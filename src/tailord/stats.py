"""Local LLM usage and cost statistics."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tailord.config import Config


@dataclass(frozen=True)
class UsageCall:
    ts: datetime
    kind: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
    wall_time_ms: int | None
    source: str
    source_id: str


def _int_or_zero(value: object) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_since(value: str, *, now: datetime) -> tuple[datetime, str]:
    raw = value.strip().lower()
    if raw.endswith("d"):
        days = int(raw[:-1])
        return now - timedelta(days=days), f"last {days} day{'s' if days != 1 else ''}"
    if raw.endswith("h"):
        hours = int(raw[:-1])
        return now - timedelta(hours=hours), f"last {hours} hour{'s' if hours != 1 else ''}"
    try:
        days = int(raw)
        return now - timedelta(days=days), f"last {days} day{'s' if days != 1 else ''}"
    except ValueError:
        pass
    parsed = _parse_ts(value)
    if parsed is None:
        raise ValueError("--since must be like 30d, 7d, 24h, or an ISO-8601 timestamp")
    return parsed, f"since {parsed.date().isoformat()}"


def _events_rows(path: Path, cutoff: datetime) -> list[UsageCall]:
    if not path.exists():
        return []

    rows: list[UsageCall] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"warning: skipping malformed {path}:{line_no}: {e}", file=sys.stderr)
            continue
        ts = _parse_ts(event.get("ts"))
        if ts is None or ts < cutoff:
            continue
        rows.append(
            UsageCall(
                ts=ts,
                kind=str(event.get("kind") or "unknown"),
                model=event.get("model") if isinstance(event.get("model"), str) else None,
                input_tokens=_int_or_zero(event.get("input_tokens")),
                output_tokens=_int_or_zero(event.get("output_tokens")),
                cache_creation_tokens=_int_or_zero(event.get("cache_creation_tokens")),
                cache_read_tokens=_int_or_zero(event.get("cache_read_tokens")),
                cost_usd=_float_or_zero(event.get("cost_usd")),
                wall_time_ms=_int_or_zero(event.get("wall_time_ms")),
                source="events.jsonl",
                source_id=str(line_no),
            )
        )
    return rows


def _bridge_rows(path: Path, cutoff: datetime) -> list[UsageCall]:
    if not path.exists():
        return []

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        print(f"warning: could not read {path}: {e}", file=sys.stderr)
        return []

    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "job_runs" not in tables:
            return []

        columns = {row[1] for row in conn.execute("PRAGMA table_info(job_runs)")}
        required = {
            "job_id",
            "phase",
            "attempt",
            "completed_at",
            "model",
            "input_tokens",
            "output_tokens",
            "cache_creation_tokens",
            "cache_read_tokens",
            "cost_usd",
            "wall_time_ms",
        }
        if not required.issubset(columns):
            return []

        cutoff_ms = int(cutoff.timestamp() * 1000)
        rows: list[UsageCall] = []
        query = """
            SELECT job_id, phase, attempt, completed_at, model, input_tokens, output_tokens,
                   cache_creation_tokens, cache_read_tokens, cost_usd, wall_time_ms
            FROM job_runs
            WHERE status = 'done'
              AND completed_at >= ?
              AND cost_usd IS NOT NULL
            ORDER BY completed_at
        """
        for row in conn.execute(query, (cutoff_ms,)):
            (
                job_id,
                phase,
                attempt,
                completed_at,
                model,
                input_tokens,
                output_tokens,
                cache_creation_tokens,
                cache_read_tokens,
                cost_usd,
                wall_time_ms,
            ) = row
            if completed_at is None:
                continue
            rows.append(
                UsageCall(
                    ts=datetime.fromtimestamp(completed_at / 1000, tz=timezone.utc),
                    kind=f"bridge-{phase}",
                    model=model if isinstance(model, str) else None,
                    input_tokens=_int_or_zero(input_tokens),
                    output_tokens=_int_or_zero(output_tokens),
                    cache_creation_tokens=_int_or_zero(cache_creation_tokens),
                    cache_read_tokens=_int_or_zero(cache_read_tokens),
                    cost_usd=_float_or_zero(cost_usd),
                    wall_time_ms=_int_or_zero(wall_time_ms),
                    source="jobs.db",
                    source_id=f"{job_id}:{phase}:{attempt}",
                )
            )
        return rows
    finally:
        conn.close()


def load_usage_calls(vault: Path, cutoff: datetime) -> list[UsageCall]:
    state_dir = vault / ".tailord"
    rows = [
        *_bridge_rows(state_dir / "jobs.db", cutoff),
        *_events_rows(state_dir / "events.jsonl", cutoff),
    ]
    return sorted(rows, key=lambda row: row.ts)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, int(len(ordered) * 0.95 + 0.999999) - 1)
    return ordered[index]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _fmt_money(value: float) -> str:
    if value == 0:
        return "$0.00"
    if abs(value) < 0.01:
        return f"${value:.4f}"
    return f"${value:.2f}"


def _fmt_int(value: float) -> str:
    return f"{round(value):,}"


def _fmt_duration(ms: float | None) -> str:
    if ms is None:
        return "n/a"
    if ms < 1000:
        return f"{round(ms)}ms"
    seconds = round(ms / 1000)
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    return f"{minutes}m {rem:02d}s"


def _avg(values: list[float]) -> float:
    return sum(values) / len(values)


def _cache_hit_rate(rows: list[UsageCall]) -> float | None:
    read = sum(row.cache_read_tokens for row in rows)
    total = read + sum(row.input_tokens + row.cache_creation_tokens for row in rows)
    if total == 0:
        return None
    return read / total


def _print_topline(rows: list[UsageCall], label: str) -> None:
    print(f"Jobs ({label})".ljust(40) + f"n={len(rows)}")
    hit_rate = _cache_hit_rate(rows)
    if hit_rate is not None:
        print(f"  Cache hit rate                       {hit_rate:.0%}")

    eval_rows = [row for row in rows if row.kind == "bridge-evaluate"]
    generate_rows = [row for row in rows if row.kind == "bridge-generate"]
    if len(rows) < 5:
        print("  Sample too small for stable averages or p95.")
        if eval_rows or generate_rows:
            print("  Bridge eval p95 cost                 (sample too small)")
            print("  Bridge generate p95 cost             (sample too small)")
        return

    costs = [row.cost_usd for row in rows]
    wall = [row.wall_time_ms for row in rows if row.wall_time_ms is not None]
    print(f"  Average cost per call                {_fmt_money(_avg(costs))}")
    print(f"  Median / p95                         {_fmt_money(_median(costs))} / {_fmt_money(_p95(costs))}")
    print(f"  Average wall time                    {_fmt_duration(_avg(wall) if wall else None)}")

    for label, subset in (("eval", eval_rows), ("generate", generate_rows)):
        if not subset:
            continue
        sub_costs = [row.cost_usd for row in subset]
        value = _fmt_money(_p95(sub_costs)) if len(subset) >= 5 else "(sample too small)"
        print(f"  Bridge {label} p95 cost {' ' * (16 - len(label))}{value}")


def _print_group(rows: list[UsageCall], field: str) -> None:
    groups: dict[str, list[UsageCall]] = defaultdict(list)
    for row in rows:
        key = getattr(row, field) or "(unknown)"
        groups[str(key)].append(row)

    print(f"\nBy {field}:")
    for key, group_rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(group_rows) < 5:
            print(f"  {key:<20} n={len(group_rows):<3} (sample too small)")
            continue
        costs = [row.cost_usd for row in group_rows]
        print(
            f"  {key:<20} n={len(group_rows):<3} "
            f"avg {_fmt_money(_avg(costs)):<8} p95 {_fmt_money(_p95(costs))}"
        )


def _print_token_mix(rows: list[UsageCall]) -> None:
    if not rows:
        return
    if len(rows) < 5:
        print("\nToken mix: sample too small")
        return
    n = len(rows)
    fresh = sum(row.input_tokens + row.cache_creation_tokens for row in rows) / n
    cached = sum(row.cache_read_tokens for row in rows) / n
    output = sum(row.output_tokens for row in rows) / n
    print("\nToken mix (per call, average):")
    print(f"  Input  (fresh)                    {_fmt_int(fresh)}")
    print(f"  Input  (cached)                   {_fmt_int(cached)}")
    print(f"  Output                            {_fmt_int(output)}")


def _write_csv(rows: list[UsageCall]) -> None:
    fieldnames = [
        "ts",
        "kind",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_creation_tokens",
        "cache_read_tokens",
        "cost_usd",
        "wall_time_ms",
        "source",
        "source_id",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "ts": row.ts.isoformat().replace("+00:00", "Z"),
            "kind": row.kind,
            "model": row.model or "",
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cache_creation_tokens": row.cache_creation_tokens,
            "cache_read_tokens": row.cache_read_tokens,
            "cost_usd": f"{row.cost_usd:.8f}",
            "wall_time_ms": row.wall_time_ms if row.wall_time_ms is not None else "",
            "source": row.source,
            "source_id": row.source_id,
        })


def print_usage_stats(
    *,
    since: str = "30d",
    by: list[str] | None = None,
    csv_output: bool = False,
) -> int:
    now = datetime.now(timezone.utc)
    try:
        cutoff, label = _parse_since(since, now=now)
    except (TypeError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2

    vault = Config.load().vault
    rows = load_usage_calls(vault, cutoff)
    if csv_output:
        _write_csv(rows)
        return 0

    _print_topline(rows, label)
    if not rows:
        print(f"  No usage rows found in {vault / '.tailord'}.")
        return 0
    for field in by or []:
        _print_group(rows, field)
    _print_token_mix(rows)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize local LLM token usage and cost")
    parser.add_argument("--since", default="30d", help="lookback window, e.g. 7d or 24h")
    parser.add_argument("--by", choices=["kind", "model"], action="append")
    parser.add_argument("--csv", action="store_true", help="print one row per call as CSV")
    args = parser.parse_args(argv)
    return print_usage_stats(since=args.since, by=args.by, csv_output=args.csv)


if __name__ == "__main__":
    raise SystemExit(main())
