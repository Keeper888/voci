#!/bin/bash
# Start 3 conversion workers on this machine
# Usage: bash start_workers.sh <start_slice> <end_slice>
# Spark 1: bash start_workers.sh 0 2
# Spark 2: bash start_workers.sh 3 5

START=${1:-0}
END=${2:-2}

pkill -f convert_pipeline 2>/dev/null
sleep 2

cd ~/voci
source ~/ara-env2/bin/activate

for i in $(seq $START $END); do
    mkdir -p data/moshi/worker_$i/train
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TRITON_CACHE_DIR=/tmp/triton_cache_$i \
    nohup python3 scripts/convert_pipeline.py \
      --data-dir ./data/prod \
      --output-dir ./data/moshi/worker_$i \
      --episode-list ./data/prod/slice_$i.txt \
      --hf-token $HF_TOKEN \
      > ~/voci-convert-w$i.log 2>&1 &
    echo "Worker $i: PID $!"
done

echo "All workers started"
