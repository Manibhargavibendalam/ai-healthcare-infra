"""Unit tests for scripts/measure.py pure math. No engine, no network."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location(
        "measure", ROOT / "scripts" / "measure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m = load()


def test_percentiles_known_values():
    s = list(range(1, 101))  # 1..100
    p = m.percentiles(s)
    assert (p["p50"], p["p95"], p["p99"], p["max"]) == (50, 95, 99, 100)
    assert p["mean"] == 50.5


def test_percentiles_small_and_empty():
    assert m.percentiles([7.0])["p50"] == 7.0
    assert m.percentiles([]) == {"p50": 0.0, "p95": 0.0, "p99": 0.0,
                                 "max": 0.0, "mean": 0.0}


def test_summarize_rates_and_errors():
    res = [(True, 10.0, 200)] * 90 + [(False, 5.0, 500)] * 10
    s = m.summarize(res, 10.0)
    assert s["requests"] == 100 and s["errors"] == 10
    assert s["error_rate"] == 0.1 and s["rps"] == 10.0
    assert s["p50"] == 10.0  # errors excluded from latency math


def test_summarize_empty():
    s = m.summarize([], 0.0)
    assert s["requests"] == 0 and s["rps"] == 0.0
