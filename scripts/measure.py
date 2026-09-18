#!/usr/bin/env python3
"""Client-side load + latency measurement (stdlib only, no deps).
Pure functions percentiles()/summarize() are unit-tested (tests/test_measure.py);
run_load() fires real HTTP with a thread pool. Used by measure-api.ps1.
Usage: python scripts/measure.py --base http://127.0.0.1:8080
         --mode health|jobs --requests 200 --concurrency 10
"""
import argparse
import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def percentiles(samples):
    """Nearest-rank p50/p95/p99 + max/mean (unit-tested). Empty -> zeros."""
    if not samples:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "mean": 0.0}
    s = sorted(samples)
    n = len(s)

    def at(p):
        return s[min(n - 1, math.ceil(p / 100 * n) - 1)]

    return {"p50": round(at(50), 1), "p95": round(at(95), 1),
            "p99": round(at(99), 1), "max": round(s[-1], 1),
            "mean": round(sum(s) / n, 1)}


def summarize(results, elapsed):
    """results: list of (ok, latency_ms, status). Pure (unit-tested)."""
    oks = [lat for ok, lat, _ in results if ok]
    errs = len(results) - len(oks)
    out = {"requests": len(results), "errors": errs,
           "error_rate": round(errs / len(results), 4) if results else 0.0,
           "rps": round(len(results) / elapsed, 1) if elapsed else 0.0}
    out.update(percentiles(oks))
    return out


def fire(base, mode, timeout=10):
    t0 = time.time()
    try:
        if mode == "health":
            req = urllib.request.Request(base + "/health")
        else:
            req = urllib.request.Request(
                base + "/api/v1/jobs",
                data=b'{"type":"load","patient_id":1}',
                headers={"Content-Type": "application/json"})
        status = urllib.request.urlopen(req, timeout=timeout).status
        return (200 <= status < 300, (time.time() - t0) * 1000, status)
    except Exception as e:  # HTTPError/timeout/refused: all are data points
        return (False, (time.time() - t0) * 1000, getattr(e, "code", "ERR"))


def run_load(base, mode, requests, concurrency, timeout=10):
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        out = list(ex.map(lambda _: fire(base, mode, timeout), range(requests)))
    return summarize(out, time.time() - t0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--mode", choices=["health", "jobs"], default="health")
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=10)
    a = ap.parse_args()
    print(json.dumps(run_load(a.base, a.mode, a.requests, a.concurrency), indent=1))
