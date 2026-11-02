"""
Benchmark the cnf translation end to end: parse and translate a cnf
document, reporting throughput.

Usage: python3 benchmark.py [path]

The default document is tmp/benchmark.cnf, overridable by file path
just as CNF_BENCH_FILE overrides the Go side.
"""

import os
import sys
import time

from cnfembed import cnf


def main():
    path = "tmp/benchmark.cnf"
    if os.environ.get("CNF_BENCH_FILE"):
        path = os.environ["CNF_BENCH_FILE"]
    data = open(path, "rb").read()

    # Correctness first: one pass must succeed and hold one json value.
    out = cnf.to_json(data)
    import json
    json.loads(out)
    out_len = len(out)

    # Warmup, then timed runs - enough iterations for a stable number.
    runs = 5
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        result = cnf.to_json(data)
        t1 = time.perf_counter()
        assert len(result) == out_len
        times.append(t1 - t0)

    mb = len(data) / (1024 * 1024)
    best = min(times)
    print(f"File:     {path}  ({mb:.1f} MB, {len(data)} bytes)")
    print(f"JSON out: {out_len} bytes")
    print(f"Runs:     {runs}")
    for i, t in enumerate(sorted(times)):
        ts = f"{t * 1000:.1f} ms"
        print(f"   Run {i + 1}: {ts:<10} {mb / t:>6.2f} MB/s")
    bs = f"{best * 1000:.1f} ms"
    print(f"Best:     {bs:<10} {mb / best:>6.2f} MB/s")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
