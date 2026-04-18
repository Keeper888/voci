#!/bin/bash
# Live monitor for Voci pipeline — run from Windows
# Usage: bash scripts/live_monitor.sh [refresh_seconds]

REFRESH=${1:-15}
SSH="ssh -i /c/Users/anton/.ssh/id_ed25519 -o ConnectTimeout=5 -o StrictHostKeyChecking=no raven@192.168.50.145"

while true; do
    clear
    $SSH bash -s << 'REMOTE'
cd ~/voci
source ~/voci-env/bin/activate 2>/dev/null

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              VOCI PIPELINE — LIVE MONITOR                       ║${NC}"
echo -e "${BOLD}║              $(date +'%Y-%m-%d %H:%M:%S')                                 ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"

# Downloads
echo ""
echo -e "${CYAN}┌─── DOWNLOADS ────────────────────────────────────────────────────┐${NC}"
python3 -c "
import sqlite3
conn = sqlite3.connect('data/prod/index.db')
r = conn.execute(\"SELECT COUNT(DISTINCT show_id), COUNT(*), COALESCE(SUM(duration_seconds),0)/3600.0 FROM episodes WHERE download_state='completed'\").fetchone()
p = conn.execute(\"SELECT COUNT(*) FROM episodes WHERE download_state='pending'\").fetchone()[0]
print(f'│  Shows: {r[0]:<6} Episodes: {r[1]:<8} Hours: {r[2]:<8.0f}  Pending: {p}')
" 2>/dev/null
DL_PID=$(pgrep -f "diverse_download\|episodes" 2>/dev/null | head -1)
if [ -n "$DL_PID" ]; then
    echo -e "│  ${GREEN}Downloader: RUNNING${NC} (PID $DL_PID)"
else
    echo -e "│  ${DIM}Downloader: IDLE${NC}"
fi
echo -e "${CYAN}└──────────────────────────────────────────────────────────────────┘${NC}"

# Spark 1
echo ""
echo -e "${YELLOW}┌─── SPARK 1 ($(hostname)) ─────────────────────────────────────────┐${NC}"
GPU=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader 2>/dev/null)
WORKERS=$(pgrep -c -f convert_pipeline 2>/dev/null || echo 0)
CPU=$(uptime | awk -F'load average:' '{print $2}' | xargs)
RAM=$(free -h | grep Mem | awk '{print $3 "/" $2}')
echo -e "│  GPU: ${BOLD}$GPU${NC}  Workers: ${BOLD}$WORKERS${NC}  CPU:$CPU  RAM: $RAM"

source ~/ara-env2/bin/activate 2>/dev/null
# Per-worker status
for w in 0 1 2; do
    LOG=~/voci-convert-w$w.log
    [ ! -f "$LOG" ] && continue

    # Current episode
    CURRENT=$(grep "Processing" $LOG 2>/dev/null | tail -1 | sed 's/.*Processing //' | sed 's/\.\.\.//')
    # Episode name from DB
    EP_ID=$(echo "$CURRENT" | tr -d '[:space:]')
    if [ -n "$EP_ID" ]; then
        SHOW_NAME=$(python3 -c "
import sqlite3
conn = sqlite3.connect('data/prod/index.db')
r = conn.execute('SELECT s.name FROM episodes e JOIN shows s ON e.show_id=s.show_id WHERE e.episode_id=?', ('$EP_ID',)).fetchone()
print(r[0][:45] if r else '?')
" 2>/dev/null)
        EP_TITLE=$(python3 -c "
import sqlite3
conn = sqlite3.connect('data/prod/index.db')
r = conn.execute('SELECT title FROM episodes WHERE episode_id=?', ('$EP_ID',)).fetchone()
print(r[0][:40] if r and r[0] else '?')
" 2>/dev/null)
    fi

    # Last action
    LAST=$(grep -E 'monologue|balance|Kept|OK |SKIP' $LOG 2>/dev/null | tail -1 | sed 's/.*\[INFO\] *//')

    # Stats
    DONE=$(grep -c 'Processing' $LOG 2>/dev/null | tr -d '\n' || echo 0)
    OKS=$(grep -c 'OK |' $LOG 2>/dev/null | tr -d '\n' || echo 0)
    SKIPS=$(grep -c 'SKIP |' $LOG 2>/dev/null | tr -d '\n' || echo 0)
    MONOS=$(grep -c 'monologue' $LOG 2>/dev/null | tr -d '\n' || echo 0)

    # Output segments
    SEGS=$(ls data/moshi/worker_$w/train/*.wav 2>/dev/null | wc -l)
    HOURS=$(python3 -c "
import json, glob
files = glob.glob('data/moshi/worker_$w/train/*.json')
t = sum(json.load(open(f))['duration'] for f in files) if files else 0
print(f'{t/3600:.2f}')
" 2>/dev/null)

    if [ -n "$LAST" ]; then
        if echo "$LAST" | grep -q "OK"; then
            COLOR=$GREEN
        elif echo "$LAST" | grep -q "monologue\|SKIP"; then
            COLOR=$RED
        else
            COLOR=$YELLOW
        fi
    else
        COLOR=$DIM
    fi

    echo -e "│  ${BOLD}W$w${NC} [$DONE processed, ${GREEN}$OKS ok${NC}, ${RED}$SKIPS skip${NC}, ${DIM}$MONOS mono${NC}] → ${GREEN}$SEGS segs${NC} (${HOURS}h)"
    echo -e "│     ${DIM}Show:${NC} $SHOW_NAME"
    echo -e "│     ${DIM}Episode:${NC} $EP_TITLE"
    echo -e "│     ${COLOR}$LAST${NC}"
done
echo -e "${YELLOW}└──────────────────────────────────────────────────────────────────┘${NC}"

# Spark 2
S2="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no raven@169.254.25.92"
echo ""
echo -e "${YELLOW}┌─── SPARK 2 ─────────────────────────────────────────────────────┐${NC}"
S2_GPU=$($S2 'nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader 2>/dev/null' 2>/dev/null)
S2_WORKERS=$($S2 'pgrep -c -f convert_pipeline 2>/dev/null || echo 0' 2>/dev/null)
echo -e "│  GPU: ${BOLD}${S2_GPU:-?}${NC}  Workers: ${BOLD}${S2_WORKERS:-?}${NC}"

for w in 3 4 5; do
    LAST=$($S2 "grep -E 'monologue|balance|Kept|OK |SKIP' ~/voci-convert-w$w.log 2>/dev/null | tail -1 | sed 's/.*\[INFO\] *//'" 2>/dev/null)
    SEGS=$($S2 "ls ~/voci/data/moshi/worker_$w/train/*.wav 2>/dev/null | wc -l" 2>/dev/null)
    CURRENT=$($S2 "grep 'Processing' ~/voci-convert-w$w.log 2>/dev/null | tail -1 | sed 's/.*Processing //' | sed 's/\.\.\.//' | tr -d '[:space:]'" 2>/dev/null)

    if [ -n "$CURRENT" ]; then
        SHOW_NAME=$(python3 -c "
import sqlite3
conn = sqlite3.connect('data/prod/index.db')
r = conn.execute('SELECT s.name FROM episodes e JOIN shows s ON e.show_id=s.show_id WHERE e.episode_id=?', ('$CURRENT',)).fetchone()
print(r[0][:45] if r else '?')
" 2>/dev/null)
    else
        SHOW_NAME="?"
    fi

    DONE=$($S2 "grep -c 'Processing' ~/voci-convert-w$w.log 2>/dev/null || echo 0" 2>/dev/null)
    OKS=$($S2 "grep -c 'OK |' ~/voci-convert-w$w.log 2>/dev/null || echo 0" 2>/dev/null)

    echo -e "│  ${BOLD}W$w${NC} [$DONE processed, ${GREEN}$OKS ok${NC}] → ${GREEN}${SEGS:-0} segs${NC}  ${DIM}$SHOW_NAME${NC}"
    [ -n "$LAST" ] && echo -e "│     $LAST"
done
echo -e "${YELLOW}└──────────────────────────────────────────────────────────────────┘${NC}"

# Totals
echo ""
echo -e "${BOLD}┌─── TOTALS ────────────────────────────────────────────────────────┐${NC}"
TOTAL=$(python3 -c "
import json, glob, os
total = 0
for d in glob.glob('data/moshi/worker_*/train') + ['data/moshi/train']:
    for f in glob.glob(os.path.join(d, '*.json')):
        total += json.load(open(f))['duration']
print(f'{total/3600:.1f}')
" 2>/dev/null)

# Add Spark 2 totals
S2_TOTAL=$($S2 "cd ~/voci && source ~/ara-env2/bin/activate && python3 -c \"
import json, glob, os
total = 0
for d in glob.glob('data/moshi/worker_*/train') + ['data/moshi/train']:
    for f in glob.glob(os.path.join(d, '*.json')):
        total += json.load(open(f))['duration']
print(f'{total/3600:.1f}')
\"" 2>/dev/null)

COMBINED=$(python3 -c "print(f'{${TOTAL:-0} + ${S2_TOTAL:-0}:.1f}')" 2>/dev/null)
PCT=$(python3 -c "print(f'{(${TOTAL:-0} + ${S2_TOTAL:-0})/500*100:.1f}')" 2>/dev/null)
BAR_FULL=$(python3 -c "
pct = (${TOTAL:-0} + ${S2_TOTAL:-0})/500
filled = int(pct * 40)
empty = 40 - filled
print('█' * filled + '░' * empty)
" 2>/dev/null)

echo -e "│  Spark 1: ${GREEN}${TOTAL:-0}h${NC}  Spark 2: ${GREEN}${S2_TOTAL:-0}h${NC}  Combined: ${BOLD}${COMBINED:-0}h${NC} / 500h"
echo -e "│  [${GREEN}${BAR_FULL}${NC}] ${PCT:-0}%"
echo -e "${BOLD}└──────────────────────────────────────────────────────────────────┘${NC}"

REMOTE

    echo ""
    echo "  Refreshing every ${REFRESH}s — Ctrl+C to stop"
    sleep $REFRESH
done
