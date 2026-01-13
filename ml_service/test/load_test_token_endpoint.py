# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------
 
# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : load_test_token_endpoint.py
# @Software: PyCharm

"""
pip install aiohttp matplotlib


Concurrent load test for:
POST http://localhost:8007/api/token
JSON body: {"email": "...", "password": "..."}

Adds graph generation:
- latency_over_time.png (per-request latency vs completion time)
- latency_hist.png (latency histogram)
- latency_ecdf.png (ECDF of latency)
- status_counts.png (bar chart of status codes)

Logs:
- JSONL file with one record per request (timestamps, latency, status, etc.)
- summary.json with aggregated metrics
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

# Matplotlib is only needed if you enable --plots
# (imported lazily inside plot_results)


@dataclass
class Result:
    i: int
    ok: bool
    status: Optional[int]
    ms: float
    error: Optional[str]
    bytes: int
    start_ts: str
    end_ts: str
    start_perf: float
    end_perf: float


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(sorted_vals: List[float], p: float) -> float:
    """Nearest-rank percentile on sorted list."""
    if not sorted_vals:
        return float("nan")
    k = max(1, int(round(p / 100.0 * len(sorted_vals))))
    k = min(k, len(sorted_vals))
    return sorted_vals[k - 1]


async def worker(
        wid: int,
        session: aiohttp.ClientSession,
        url: str,
        payload: Dict[str, Any],
        q: "asyncio.Queue[int]",
        out_q: "asyncio.Queue[Result]",
        timeout_s: float,
        jitter_ms: int,
) -> None:
    while True:
        i = await q.get()
        if i is None:  # sentinel
            q.task_done()
            return

        # Optional tiny jitter to avoid perfect synchronization spikes
        if jitter_ms > 0:
            await asyncio.sleep(random.random() * (jitter_ms / 1000.0))

        start_perf = time.perf_counter()
        start_ts = utc_now_iso()

        status = None
        err = None
        b = 0
        ok = False
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_s)
            async with session.post(url, json=payload, timeout=timeout) as resp:
                status = resp.status
                body = await resp.read()
                b = len(body)

                ok = 200 <= status < 300
                if not ok:
                    snippet = body[:300].decode("utf-8", errors="replace")
                    err = f"HTTP {status}: {snippet}"
        except asyncio.TimeoutError:
            err = "timeout"
        except aiohttp.ClientError as e:
            err = f"client_error: {type(e).__name__}: {e}"
        except Exception as e:
            err = f"error: {type(e).__name__}: {e}"

        end_perf = time.perf_counter()
        end_ts = utc_now_iso()
        ms = (end_perf - start_perf) * 1000.0

        await out_q.put(
            Result(
                i=i,
                ok=ok,
                status=status,
                ms=ms,
                error=err,
                bytes=b,
                start_ts=start_ts,
                end_ts=end_ts,
                start_perf=start_perf,
                end_perf=end_perf,
            )
        )
        q.task_done()


async def logger_task(
        out_q: "asyncio.Queue[Result]",
        results: List[Result],
        log_path: Path,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        while True:
            r = await out_q.get()
            if r is None:  # sentinel
                out_q.task_done()
                return

            results.append(r)
            rec = {
                "start_ts": r.start_ts,
                "end_ts": r.end_ts,
                "request_index": r.i,
                "ok": r.ok,
                "status": r.status,
                "latency_ms": round(r.ms, 3),
                "bytes": r.bytes,
                "error": r.error,
                # perf timestamps are useful for plotting relative time
                "start_perf": r.start_perf,
                "end_perf": r.end_perf,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            out_q.task_done()


def summarize(results: List[Result]) -> Dict[str, Any]:
    total = len(results)
    oks = [r for r in results if r.ok]
    fails = [r for r in results if not r.ok]
    lat = sorted([r.ms for r in results])

    summary: Dict[str, Any] = {
        "total_requests": total,
        "success_2xx": len(oks),
        "failure": len(fails),
        "success_rate": (len(oks) / total) if total else 0.0,
        "latency_ms": {},
        "status_counts": {},
        "top_errors": [],
    }

    if total:
        summary["latency_ms"] = {
            "min": min(lat),
            "avg": statistics.mean(lat),
            "max": max(lat),
            "p50": percentile(lat, 50),
            "p90": percentile(lat, 90),
            "p95": percentile(lat, 95),
            "p99": percentile(lat, 99),
        }

    # status counts
    by_status: Dict[str, int] = {}
    for r in results:
        key = str(r.status) if r.status is not None else "NO_STATUS"
        by_status[key] = by_status.get(key, 0) + 1
    summary["status_counts"] = dict(sorted(by_status.items(), key=lambda kv: kv[0]))

    # Top errors (grouped)
    err_counts: Dict[str, int] = {}
    for r in fails:
        k = r.error or "unknown_error"
        if len(k) > 400:
            k = k[:400] + "…"
        err_counts[k] = err_counts.get(k, 0) + 1
    summary["top_errors"] = [
        {"count": v, "error": k}
        for k, v in sorted(err_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]

    return summary


def plot_results(results: List[Result], out_dir: Path, total_requests: int, concurrency: int) -> None:
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)

    if not results:
        return

    t0 = min(r.start_perf for r in results)
    points = sorted(
        ((r.end_perf - t0, r.ms, r.ok, r.status) for r in results),
        key=lambda x: x[0],
    )
    t = [p[0] for p in points]
    ms = [p[1] for p in points]
    ok = [p[2] for p in points]
    status = [p[3] for p in points]

    # Calculate stats for annotations
    avg_latency = statistics.mean(ms)
    p50 = percentile(sorted(ms), 50)
    p95 = percentile(sorted(ms), 95)
    p99 = percentile(sorted(ms), 99)
    success_rate = sum(ok) / len(ok) * 100

    # 1) Latency over time with success/failure colors
    plt.figure(figsize=(12, 6))
    success_ms = [ms[i] for i in range(len(ms)) if ok[i]]
    success_t = [t[i] for i in range(len(t)) if ok[i]]
    fail_ms = [ms[i] for i in range(len(ms)) if not ok[i]]
    fail_t = [t[i] for i in range(len(t)) if not ok[i]]

    if success_ms:
        plt.scatter(success_t, success_ms, s=10, alpha=0.6, color='green', label='Successful Requests (2xx)')
    if fail_ms:
        plt.scatter(fail_t, fail_ms, s=10, alpha=0.6, color='red', label='Failed Requests')

    plt.axhline(y=avg_latency, color='blue', linestyle='--', linewidth=1, label=f'Average Latency: {avg_latency:.1f} milliseconds')
    plt.axhline(y=p95, color='orange', linestyle='--', linewidth=1, label=f'95th Percentile: {p95:.1f} milliseconds')

    plt.xlabel("Time Since Test Start (seconds)", fontsize=11)
    plt.ylabel("Response Latency (milliseconds)", fontsize=11)
    plt.title(f"Request Response Latency Over Time\nTotal: {total_requests} requests | Concurrent Workers: {concurrency} | Success Rate: {success_rate:.1f}%", fontsize=12, fontweight='bold')
    plt.legend(loc='upper right')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "latency_over_time.png", dpi=160)
    plt.close()

    # 2) Histogram of latency with percentiles
    plt.figure(figsize=(10, 6))
    n, bins, patches = plt.hist(ms, bins=50, edgecolor='black', alpha=0.7)
    plt.axvline(x=avg_latency, color='blue', linestyle='--', linewidth=2, label=f'Average (Mean): {avg_latency:.1f} milliseconds')
    plt.axvline(x=p50, color='green', linestyle='--', linewidth=2, label=f'50th Percentile (Median): {p50:.1f} milliseconds')
    plt.axvline(x=p95, color='orange', linestyle='--', linewidth=2, label=f'95th Percentile: {p95:.1f} milliseconds')
    plt.axvline(x=p99, color='red', linestyle='--', linewidth=2, label=f'99th Percentile: {p99:.1f} milliseconds')

    plt.xlabel("Response Latency (milliseconds)", fontsize=11)
    plt.ylabel("Number of Requests", fontsize=11)
    plt.title(f"Response Latency Distribution Histogram\nDistribution of {total_requests} total requests showing how many requests fall into each latency range", fontsize=12, fontweight='bold')
    plt.legend(loc='upper right')
    plt.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    plt.savefig(out_dir / "latency_hist.png", dpi=160)
    plt.close()

    # 3) ECDF of latency with percentile markers
    ms_sorted = sorted(ms)
    n = len(ms_sorted)
    y = [(i + 1) / n * 100 for i in range(n)]
    plt.figure(figsize=(10, 6))
    plt.plot(ms_sorted, y, linewidth=2)

    # Mark key percentiles
    p50_val = percentile(ms_sorted, 50)
    p90_val = percentile(ms_sorted, 90)
    p95_val = percentile(ms_sorted, 95)
    p99_val = percentile(ms_sorted, 99)

    plt.axvline(x=p50_val, color='green', linestyle='--', alpha=0.7, label=f'50th Percentile (Median): {p50_val:.1f} milliseconds')
    plt.axvline(x=p90_val, color='orange', linestyle='--', alpha=0.7, label=f'90th Percentile: {p90_val:.1f} milliseconds')
    plt.axvline(x=p95_val, color='red', linestyle='--', alpha=0.7, label=f'95th Percentile: {p95_val:.1f} milliseconds')
    plt.axvline(x=p99_val, color='darkred', linestyle='--', alpha=0.7, label=f'99th Percentile: {p99_val:.1f} milliseconds')

    plt.xlabel("Response Latency (milliseconds)", fontsize=11)
    plt.ylabel("Cumulative Percentage of Requests (%)", fontsize=11)
    plt.title(f"Cumulative Distribution Function (ECDF) of Response Latency\nShows the percentage of requests that completed within a given latency threshold", fontsize=12, fontweight='bold')
    plt.legend(loc='lower right')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "latency_ecdf.png", dpi=160)
    plt.close()

    # 4) Status counts bar chart with percentages
    counts: Dict[str, int] = {}
    for s in status:
        key = str(s) if s is not None else "NO_STATUS"
        counts[key] = counts.get(key, 0) + 1

    labels = sorted(counts.keys(), key=lambda x: (x == "NO_STATUS", x))
    values = [counts[k] for k in labels]
    percentages = [v / total_requests * 100 for v in values]

    plt.figure(figsize=(10, 6))
    bars = plt.bar(labels, values, edgecolor='black', alpha=0.7)

    # Color bars: green for 2xx, red for errors
    for i, label in enumerate(labels):
        if label.startswith('2'):
            bars[i].set_color('green')
        elif label.startswith(('4', '5')) or label == 'NO_STATUS':
            bars[i].set_color('red')
        else:
            bars[i].set_color('orange')

    # Add value labels on bars
    for i, (bar, val, pct) in enumerate(zip(bars, values, percentages)):
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                 f'{val}\n({pct:.1f}%)',
                 ha='center', va='bottom', fontsize=9)

    plt.xlabel("HTTP Response Status Code", fontsize=11)
    plt.ylabel("Number of Requests", fontsize=11)
    plt.title(f"HTTP Response Status Code Distribution\nTotal of {total_requests} requests with count and percentage for each status code", fontsize=12, fontweight='bold')
    plt.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    plt.savefig(out_dir / "status_counts.png", dpi=160)
    plt.close()


async def main_async(args: argparse.Namespace) -> int:
    url = args.url
    payload = {"email": args.email, "password": args.password}

    q: asyncio.Queue[int] = asyncio.Queue()
    out_q: asyncio.Queue[Result] = asyncio.Queue()
    results: List[Result] = []

    for i in range(args.requests):
        q.put_nowait(i)

    connector = aiohttp.TCPConnector(limit=args.concurrency, force_close=False)
    headers = {"accept": "application/json", "Content-Type": "application/json"}

    log_path = Path(args.log)
    plots_dir = Path(args.plots_dir)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        log_task = asyncio.create_task(logger_task(out_q, results, log_path))
        workers = [
            asyncio.create_task(
                worker(
                    wid=w,
                    session=session,
                    url=url,
                    payload=payload,
                    q=q,
                    out_q=out_q,
                    timeout_s=args.timeout,
                    jitter_ms=args.jitter_ms,
                )
            )
            for w in range(args.concurrency)
        ]

        start = time.perf_counter()
        await q.join()

        for _ in workers:
            q.put_nowait(None)
        await asyncio.gather(*workers)

        await out_q.join()
        out_q.put_nowait(None)
        await log_task
        elapsed = time.perf_counter() - start

    summary = summarize(results)
    summary["elapsed_s"] = elapsed
    summary["throughput_rps"] = (len(results) / elapsed) if elapsed > 0 else 0.0
    summary_path = log_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nCompleted in {elapsed:.3f}s  (~{summary['throughput_rps']:.1f} req/s)")
    print(f"Log:     {log_path.resolve()}")
    print(f"Summary: {summary_path.resolve()}")

    if args.plots:
        plot_results(results, plots_dir, args.requests, args.concurrency)
        print(f"Plots:   {plots_dir.resolve()} (png files)")

    # Print compact console summary
    print("\n=== Summary ===")
    print(f"Total requests: {summary['total_requests']}")
    print(f"Success (2xx):  {summary['success_2xx']} ({summary['success_rate']*100:.2f}%)")
    print(f"Failures:       {summary['failure']} ({(1-summary['success_rate'])*100:.2f}%)")

    if summary["latency_ms"]:
        lm = summary["latency_ms"]
        print(
            "Latency ms: "
            f"min={lm['min']:.2f} avg={lm['avg']:.2f} max={lm['max']:.2f} "
            f"p50={lm['p50']:.2f} p90={lm['p90']:.2f} p95={lm['p95']:.2f} p99={lm['p99']:.2f}"
        )

    print("\nStatus counts:")
    for k, v in summary["status_counts"].items():
        print(f"  {k}: {v}")

    if summary["top_errors"]:
        print("\nTop failure reasons:")
        for item in summary["top_errors"]:
            print(f"  {item['count']}x  {item['error']}")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Concurrent load test for /api/token (with plots)")
    p.add_argument("--url", default="http://localhost:8007/api/token", help="Target URL")
    p.add_argument("--email", default="test@test.com", help="Email for payload")
    p.add_argument("--password", default="test123", help="Password for payload")
    p.add_argument("--concurrency", type=int, default=100, help="Number of concurrent workers")
    p.add_argument("--requests", type=int, default=5000, help="Total number of requests")
    p.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout (seconds)")
    p.add_argument("--jitter-ms", type=int, default=10, help="Random jitter per request in ms (0 disables)")

    p.add_argument("--log", default=f"logs/token_load_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
                   help="Output log path (JSONL)")
    p.add_argument("--no-plots", action="store_false", dest="plots", help="Disable PNG plot generation")
    p.add_argument("--plots-dir", default="logs/plots", help="Directory to write PNG plots")

    args = p.parse_args()
    # Plots enabled by default
    if not hasattr(args, 'plots'):
        args.plots = True
    return args


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(main_async(args)))