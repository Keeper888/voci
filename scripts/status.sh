#!/bin/bash
# Quick status script — run on Spark 1

echo "========================================"
echo "  VOCI PIPELINE STATUS — $(date +%H:%M:%S)"
echo "========================================"

cd ~/voci
source ~/voci-env/bin/activate 2>/dev/null

echo ""
echo "--- DOWNLOADS ---"
python3 -c "
import sqlite3
conn = sqlite3.connect('data/prod/index.db')
r = conn.execute(\"SELECT COUNT(DISTINCT show_id), COUNT(*), COALESCE(SUM(duration_seconds),0)/3600.0 FROM episodes WHERE download_state='completed'\").fetchone()
p = conn.execute(\"SELECT COUNT(*) FROM episodes WHERE download_state='pending'\").fetchone()[0]
f = conn.execute(\"SELECT COUNT(*) FROM episodes WHERE download_state='failed'\").fetchone()[0]
print(f'  Shows: {r[0]} | Episodes: {r[1]} | Hours: {r[2]:.0f}h')
print(f'  Pending: {p} | Failed: {f}')
"

echo ""
echo "--- SPARK 1 ($(hostname)) ---"
echo "  GPU: $(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader)"
echo "  Workers: $(pgrep -c -f convert_pipeline 2>/dev/null || echo 0)"
echo "  CPU: $(uptime | awk -F'load average:' '{print $2}')"
echo "  RAM: $(free -h | grep Mem | awk '{print $3 "/" $2}')"

source ~/ara-env2/bin/activate 2>/dev/null
echo "  Output:"
for w in 0 1 2; do
    if [ -d "data/moshi/worker_$w/train" ]; then
        SEGS=$(ls data/moshi/worker_$w/train/*.wav 2>/dev/null | wc -l)
        echo "    W$w: $SEGS segments"
    fi
done
OLD=$(ls data/moshi/train/*.wav 2>/dev/null | wc -l)
[ "$OLD" -gt 0 ] && echo "    Old: $OLD segments"

echo "  Last activity:"
for w in 0 1 2; do
    LINE=$(grep -E 'monologue|balance|Kept|OK |SKIP' ~/voci-convert-w$w.log 2>/dev/null | tail -1)
    [ -n "$LINE" ] && echo "    W$w: $LINE"
done

echo ""
echo "--- SPARK 2 ---"
S2="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no raven@169.254.25.92"
echo "  GPU: $($S2 'nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader 2>/dev/null')"
echo "  Workers: $($S2 'pgrep -c -f convert_pipeline 2>/dev/null || echo 0')"
echo "  Output:"
for w in 3 4 5; do
    SEGS=$($S2 "ls ~/voci/data/moshi/worker_$w/train/*.wav 2>/dev/null | wc -l")
    [ -n "$SEGS" ] && [ "$SEGS" -gt 0 ] 2>/dev/null && echo "    W$w: $SEGS segments"
done
S2OLD=$($S2 "ls ~/voci/data/moshi/train/*.wav 2>/dev/null | wc -l")
[ -n "$S2OLD" ] && [ "$S2OLD" -gt 0 ] 2>/dev/null && echo "    Old: $S2OLD segments"

echo "  Last activity:"
for w in 3 4 5; do
    LINE=$($S2 "grep -E 'monologue|balance|Kept|OK |SKIP' ~/voci-convert-w$w.log 2>/dev/null | tail -1")
    [ -n "$LINE" ] && echo "    W$w: $LINE"
done

echo ""
echo "--- TOTALS ---"
TOTAL_H=$(python3 -c "
import json, glob, os
total = 0
for d in glob.glob('data/moshi/worker_*/train') + ['data/moshi/train']:
    for f in glob.glob(os.path.join(d, '*.json')):
        total += json.load(open(f))['duration']
print(f'{total/3600:.1f}')
" 2>/dev/null)
echo "  Spark 1 moshi-ready: ${TOTAL_H}h"
echo "  Target: 500h"
echo "========================================"
