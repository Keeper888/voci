#!/bin/bash
pkill -f convert 2>/dev/null
sleep 2
cd ~/voci
source ~/ara-env2/bin/activate
PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRITON_CACHE_DIR=/tmp/triton_cache nohup python3 scripts/convert_single_model.py \
  --data-dir ./data/prod \
  --output-dir ./data/moshi/spark2 \
  --episode-list data/prod/slice_3.txt data/prod/slice_4.txt data/prod/slice_5.txt \
  --hf-token $HF_TOKEN \
  > ~/voci-single.log 2>&1 &
echo "PID: $!"
