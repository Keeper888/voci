# Hardware Setup — DGX Spark

## Hardware Specs

**NVIDIA DGX Spark** (x2):
- GPU: NVIDIA Blackwell (GB-series), 128GB unified memory
- CPU: ARM Grace
- Connectivity: 10GbE+

These are compact AI workstations designed for local training and inference. The 128GB unified memory is the key advantage — it eliminates the memory bottleneck that limits batch sizes on consumer GPUs.

## Network Setup

### Current Status
Both DGX Sparks are on a subnet that's currently unreachable from the main network. They need to be connected to the Mercury switch on Subnet 1 (192.168.10.0/24).

### Required Steps
1. Physically connect DGX Sparks to Mercury switch (Subnet 1)
2. Assign static IPs (e.g., 192.168.10.20, 192.168.10.21)
3. Verify SSH access via jump host: `ssh -J ubnt@192.168.20.1 antonio@192.168.10.{20,21}`
4. Configure WireGuard if remote access needed
5. Set up shared storage (NFS) for the audio corpus

### Network Topology
```
Internet
    ↓
Asus RT-AX82U (192.168.50.1)
    ↓
Zeus (192.168.60.1) — firewall/gateway
    ↓
EdgeRouter X (192.168.60.141)
    ↓
Mercury Switch — Subnet 1 (192.168.10.0/24)
    ├── LattePanda Delta (192.168.10.11)
    ├── Delta2 (192.168.10.12)
    ├── DGX Spark 1 (192.168.10.20)  ← NEW
    └── DGX Spark 2 (192.168.10.21)  ← NEW
```

## Software Stack

### OS Setup
```bash
# Both machines should run Ubuntu 22.04+ or Debian 12+
# NVIDIA drivers should come pre-installed on DGX

# Verify GPU
nvidia-smi

# Should show Blackwell GPU with 128GB memory
```

### Python Environment
```bash
# Install miniconda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh
bash Miniconda3-latest-Linux-aarch64.sh

# Create voci environment
conda create -n voci python=3.11
conda activate voci

# Install PyTorch (ARM + CUDA)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# Install pipeline dependencies
pip install faster-whisper whisperx pyannote.audio transformers datasets
pip install emotion2vec soundfile librosa

# Install training dependencies
pip install accelerate deepspeed wandb
```

### Storage Planning

| Data | Size Estimate | Location |
|------|--------------|----------|
| Raw audio (5,000h MP3) | ~2.5 TB | Shared NFS |
| Decoded WAV (16kHz mono) | ~5.5 TB | Local SSD (faster I/O) |
| Pass 1 transcripts (JSON) | ~50 GB | Shared NFS |
| Pass 2 model checkpoints | ~20 GB | Local SSD |
| Pass 2 annotations | ~50 GB | Shared NFS |
| Final dataset | ~100 GB (JSON only) | Shared NFS |
| **Total** | **~8-9 TB** | |

**Recommendation**: 
- 10TB+ NFS share for corpus and outputs
- Local NVMe SSDs on each Spark for active processing (WAV decode cache, model weights)

## GPU Task Distribution

### Strategy: Task-Level Parallelism

Don't split individual files across GPUs. Instead, each GPU pulls from a shared queue:

```
┌──────────────────┐
│   Task Queue     │
│   (filesystem)   │
└───────┬──────────┘
        │
   ┌────┴────┐
   ▼         ▼
┌──────┐  ┌──────┐
│Spark1│  │Spark2│
│Worker│  │Worker│
└──────┘  └──────┘
```

### Configuration per Task

**Pass 1 (WhisperX):**
```yaml
# Each Spark runs independently
worker:
  gpu_id: 0
  concurrent_files: 8
  model: large-v3-turbo
  compute_type: float16
  batch_size: 16
  queue_dir: /shared/voci/queue/pass1/
  output_dir: /shared/voci/output/pass1/
```

**Pass 2a (SSL Pre-training):**
```yaml
# Distributed training across both Sparks
distributed:
  world_size: 2
  backend: nccl
  master_addr: 192.168.10.20
  master_port: 29500
training:
  model: wavlm-base-plus
  batch_size: 64  # Per GPU, 128GB allows this
  gradient_accumulation: 4
  effective_batch: 512
  fp16: true
```

**Pass 2c (Inference):**
```yaml
# Each Spark runs independently (same as Pass 1)
worker:
  gpu_id: 0
  concurrent_files: 12  # Lighter model than Whisper
  model: /shared/voci/models/voci-para-v1/
  queue_dir: /shared/voci/queue/pass2/
  output_dir: /shared/voci/output/pass2/
```

## Monitoring

```bash
# GPU utilization (should be >90% during processing)
watch -n 1 nvidia-smi

# Pipeline progress
python scripts/status.py --queue-dir /shared/voci/queue/

# Estimated completion
python scripts/eta.py --task pass1
```

## Power and Cooling

DGX Spark draws ~300-400W under load. Two units:
- Ensure adequate power supply (~1kW total)
- Room ventilation — they generate significant heat under sustained load
- Consider running overnight / during cooler hours for multi-day training runs
