"""Real-time monitor for Voci pipeline — downloads + conversion on both Sparks."""
import json
import glob
import sqlite3
import subprocess
import time
import sys
from pathlib import Path


def run_ssh(cmd, timeout=10):
    """Run command on Spark 1."""
    try:
        r = subprocess.run(
            ["ssh", "-i", str(Path.home() / ".ssh/id_ed25519"),
             "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
             "raven@192.168.50.145", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return "UNREACHABLE"


def run_spark2(cmd, timeout=10):
    """Run command on Spark 2 via Spark 1."""
    return run_ssh(f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no raven@169.254.25.92 '{cmd}'", timeout=timeout+5)


def clear():
    print("\033[2J\033[H", end="")


def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    while True:
        clear()
        print("=" * 70)
        print("  VOCI PIPELINE MONITOR")
        print("=" * 70)

        # Downloads
        dl_info = run_ssh("cd ~/voci && source ~/voci-env/bin/activate && python3 -c \"\nimport sqlite3\nconn = sqlite3.connect('data/prod/index.db')\nr = conn.execute(\\\"SELECT COUNT(DISTINCT show_id), COUNT(*), COALESCE(SUM(duration_seconds),0)/3600.0 FROM episodes WHERE download_state='completed'\\\").fetchone()\nprint(f'{r[0]}|{r[1]}|{r[2]:.1f}')\nr2 = conn.execute(\\\"SELECT COUNT(*) FROM episodes WHERE download_state='pending'\\\").fetchone()\nprint(r2[0])\n\"")
        dl_parts = dl_info.split("\n")
        if len(dl_parts) >= 2:
            shows, eps, hours = dl_parts[0].split("|")
            pending = dl_parts[1]
            print(f"\n  DOWNLOADS")
            print(f"  Shows: {shows} | Episodes: {eps} | Hours: {hours}h")
            print(f"  Pending: {pending}")

        # Spark 1 conversion
        s1_gpu = run_ssh("nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null")
        s1_workers = run_ssh("pgrep -c -f convert_pipeline 2>/dev/null || echo 0")
        s1_cpu = run_ssh("uptime | awk -F'load average:' '{print $2}'")

        s1_stats = run_ssh("cd ~/voci && source ~/ara-env2/bin/activate && python3 -c \"\nimport json, glob, os\ntotal_segs = 0; total_h = 0\nfor d in glob.glob('data/moshi/worker_*/train') + ['data/moshi/train']:\n    files = glob.glob(os.path.join(d, '*.json'))\n    total_segs += len(files)\n    total_h += sum(json.load(open(f))['duration'] for f in files)\nprint(f'{total_segs}|{total_h/3600:.1f}')\n\"", timeout=15)

        print(f"\n  SPARK 1 (spark-9000)")
        print(f"  GPU: {s1_gpu} | Workers: {s1_workers} | CPU: {s1_cpu}")
        if "|" in s1_stats:
            segs, hours = s1_stats.split("|")
            print(f"  Output: {segs} segments, {hours}h moshi-ready")

        # Recent activity
        for w in range(3):
            last = run_ssh(f"grep -E 'monologue|balance|Kept|OK |SKIP' ~/voci-convert-w{w}.log 2>/dev/null | tail -1")
            if last:
                print(f"  W{w}: {last}")

        # Spark 2 conversion
        s2_gpu = run_spark2("nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null")
        s2_workers = run_spark2("pgrep -c -f convert_pipeline 2>/dev/null || echo 0")

        s2_stats = run_spark2("cd ~/voci && source ~/ara-env2/bin/activate && python3 -c \"\nimport json, glob, os\ntotal_segs = 0; total_h = 0\nfor d in glob.glob('data/moshi/worker_*/train') + ['data/moshi/train']:\n    files = glob.glob(os.path.join(d, '*.json'))\n    total_segs += len(files)\n    total_h += sum(json.load(open(f))['duration'] for f in files)\nprint(f'{total_segs}|{total_h/3600:.1f}')\n\"", timeout=15)

        print(f"\n  SPARK 2 (spark-f5af)")
        print(f"  GPU: {s2_gpu} | Workers: {s2_workers}")
        if "|" in (s2_stats or ""):
            segs, hours = s2_stats.split("|")
            print(f"  Output: {segs} segments, {hours}h moshi-ready")

        for w in range(3, 6):
            last = run_spark2(f"grep -E 'monologue|balance|Kept|OK |SKIP' ~/voci-convert-w{w}.log 2>/dev/null | tail -1")
            if last:
                print(f"  W{w}: {last}")

        # Totals
        print(f"\n  {'=' * 50}")
        print(f"  TARGET: 500h moshi-ready conversational data")
        print(f"  Refreshing every {interval}s — Ctrl+C to stop")
        print(f"  {time.strftime('%H:%M:%S')}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
