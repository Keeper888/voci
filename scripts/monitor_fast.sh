#!/bin/bash
# Fast monitor — runs ON Spark 1, no double SSH hops
# Usage from Windows: ssh -i C:/Users/anton/.ssh/id_ed25519 raven@192.168.50.145 "bash ~/voci/scripts/monitor_fast.sh"
# Or with watch: ssh -t -i C:/Users/anton/.ssh/id_ed25519 raven@192.168.50.145 "watch -n 10 -c bash ~/voci/scripts/monitor_fast.sh"

cd ~/voci 2>/dev/null
source ~/voci-env/bin/activate 2>/dev/null

G='\033[0;32m'
R='\033[0;31m'
Y='\033[1;33m'
C='\033[0;36m'
B='\033[1m'
D='\033[2m'
N='\033[0m'

echo ""
echo -e "${B}══════ VOCI PIPELINE $(date +'%H:%M:%S') ══════${N}"

# Downloads
python3 -c "
import sqlite3
c = sqlite3.connect('data/prod/index.db')
r = c.execute(\"SELECT COUNT(DISTINCT show_id), COUNT(*), COALESCE(SUM(duration_seconds),0)/3600.0 FROM episodes WHERE download_state='completed'\").fetchone()
p = c.execute(\"SELECT COUNT(*) FROM episodes WHERE download_state='pending'\").fetchone()[0]
print(f'DL: {r[0]} shows, {r[1]} eps, {r[2]:.0f}h | pending: {p}')
" 2>/dev/null

echo ""
echo -e "${Y}SPARK 1${N} GPU:${B}$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader)${N} W:$(pgrep -c -f convert_pipeline 2>/dev/null)"

source ~/ara-env2/bin/activate 2>/dev/null
for w in 0 1 2; do
    LOG=~/voci-convert-w$w.log
    [ ! -f "$LOG" ] && continue
    EP=$(grep "Processing" $LOG | tail -1 | grep -oP '[a-f0-9]{16}')
    if [ -n "$EP" ]; then
        INFO=$(python3 -c "
import sqlite3
c = sqlite3.connect('data/prod/index.db')
r = c.execute('SELECT s.name, e.title FROM episodes e JOIN shows s ON e.show_id=s.show_id WHERE e.episode_id=?',('$EP',)).fetchone()
if r: print(f'{r[0][:30]} | {(r[1] or \"?\")[:30]}')
else: print('?')
" 2>/dev/null)
    fi
    DONE=$(grep -c 'Processing' $LOG)
    OKS=$(grep -c 'OK |' $LOG)
    SEGS=$(ls data/moshi/worker_$w/train/*.wav 2>/dev/null | wc -l)
    LAST=$(grep -E 'monologue|balance|Kept|OK |SKIP' $LOG | tail -1 | grep -oP '(Speaker balance|Skipping|Kept|OK |SKIP).*')
    echo -e " W$w [${G}${OKS}ok${N}/${DONE}] ${G}${SEGS}seg${N} ${D}${INFO:-?}${N}"
    [ -n "$LAST" ] && echo -e "    ${LAST}"
done

# Spark 2 (quick check only)
S2W=$(ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no raven@169.254.25.92 'pgrep -c -f convert_pipeline 2>/dev/null' 2>/dev/null)
S2G=$(ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no raven@169.254.25.92 'nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader 2>/dev/null' 2>/dev/null)
echo ""
echo -e "${Y}SPARK 2${N} GPU:${B}${S2G:-?}${N} W:${S2W:-?}"

# Totals
echo ""
S1H=$(python3 -c "
import json, glob, os
t = 0
for d in glob.glob('data/moshi/worker_*/train') + ['data/moshi/train']:
    for f in glob.glob(os.path.join(d, '*.json')): t += json.load(open(f))['duration']
print(f'{t/3600:.1f}')
" 2>/dev/null)
S2H=$(ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no raven@169.254.25.92 "cd ~/voci && python3 -c \"
import json, glob, os
t = 0
for d in glob.glob('data/moshi/worker_*/train') + ['data/moshi/train']:
    for f in glob.glob(os.path.join(d, '*.json')): t += json.load(open(f))['duration']
print(f'{t/3600:.1f}')
\"" 2>/dev/null)
TOTAL=$(python3 -c "print(f'{${S1H:-0}+${S2H:-0}:.1f}')")
PCT=$(python3 -c "p=${S1H:-0}+${S2H:-0};print(f'{p/500*100:.0f}')")
BAR=$(python3 -c "p=(${S1H:-0}+${S2H:-0})/500;f=int(p*30);print('█'*f+'░'*(30-f))")
echo -e "${B}TOTAL: ${G}${TOTAL}h${N}/500h [${G}${BAR}${N}] ${PCT}%"
echo -e "${D}S1:${S1H:-0}h S2:${S2H:-0}h${N}"
