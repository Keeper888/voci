# Voci

**Italian conversational speech dataset pipeline — from podcast scraping to training-ready stereo audio.**

Voci (Italian for "voices") scrapes Italian podcasts, strips background music, diarizes speakers, transcribes with Whisper, and outputs stereo WAV + JSON transcripts in [moshi-finetune](https://github.com/kyutai-labs/moshi-finetune) format. Built for training [Project Ara](https://github.com/Keeper888/project-ara) — a real-time Italian voice agent based on NVIDIA PersonaPlex.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         VOCI PIPELINE                                   │
│                                                                         │
│  PHASE 1 — DISCOVERY & DOWNLOAD                                        │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────────┐         │
│  │ Spreaker API  │    │ Podcast Index │    │  Apple Charts    │         │
│  │ (primary)     │    │ (lang=it)     │    │  (top Italian)   │         │
│  └──────┬───────┘    └───────┬───────┘    └────────┬─────────┘         │
│         └────────────────────┼─────────────────────┘                    │
│                              ▼                                          │
│                   ┌──────────────────┐                                  │
│                   │  SQLite Index DB  │  5,064 shows / 466k episodes   │
│                   │  (index.db)       │  174,955h cataloged            │
│                   └────────┬─────────┘                                  │
│                            ▼                                            │
│                   ┌──────────────────┐                                  │
│                   │ Diverse Downloader│  Max 5 eps/show for speaker    │
│                   │ (diverse_download)│  diversity, skip monologues    │
│                   └────────┬─────────┘                                  │
│                            │                                            │
│  PHASE 2 — CONVERSION (runs on 2x DGX Spark Blackwell GPUs)           │
│                            ▼                                            │
│              ┌─────────────────────────┐                               │
│         Step 1│  FFmpeg Resample        │  MP3 → 24kHz mono WAV       │
│              └────────────┬────────────┘                               │
│                           ▼                                             │
│              ┌─────────────────────────┐                               │
│         Step 2│  Demucs (htdemucs)      │  Strip background music,    │
│              │  Meta's source separator │  keep only vocals            │
│              │  60s chunks, GPU         │  Load → process → unload    │
│              └────────────┬────────────┘                               │
│                           ▼                                             │
│              ┌─────────────────────────┐                               │
│         Step 3│  Trim intro/outro       │  Remove first/last 30s      │
│              │  (jingles)              │  (catches what Demucs misses)│
│              └────────────┬────────────┘                               │
│                           ▼                                             │
│              ┌─────────────────────────┐                               │
│         Step 4│  pyannote 3.1           │  Speaker diarization         │
│              │  (GPU)                  │  Who speaks when             │
│              │                         │  Filter: >92% = monologue   │
│              └────────────┬────────────┘                               │
│                           ▼                                             │
│              ┌─────────────────────────┐                               │
│         Step 5│  OpenAI Whisper turbo   │  Transcribe each speaker    │
│              │  (GPU, Italian)         │  segment individually        │
│              │  beam_size=5            │  Word-level timestamps       │
│              └────────────┬────────────┘                               │
│                           ▼                                             │
│              ┌─────────────────────────┐                               │
│         Step 6│  Stereo Split           │  Speaker A → left channel   │
│              │                         │  Speaker B → right channel   │
│              └────────────┬────────────┘                               │
│                           ▼                                             │
│              ┌─────────────────────────┐                               │
│         Step 7│  Segment (30-120s)      │  Split at speaker turns     │
│              │  + Filter               │  Drop single-speaker chunks  │
│              └────────────┬────────────┘                               │
│                           ▼                                             │
│              ┌─────────────────────────┐                               │
│              │  moshi-finetune output  │  Stereo WAV (24kHz 16-bit)  │
│              │                         │  + JSON transcript           │
│              │                         │  + JSONL manifest            │
│              └─────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────┘
```

## Output Format

```json
{
  "audio_file": "data/moshi/train/episode_0001.wav",
  "duration": 47.3,
  "source_episode": "abc123",
  "transcript": [
    {
      "start": 0.0,
      "end": 3.2,
      "speaker": "user",
      "text": "Ciao, come stai oggi?"
    },
    {
      "start": 3.5,
      "end": 8.1,
      "speaker": "agent",
      "text": "Bene grazie! Oggi parliamo di qualcosa di interessante."
    }
  ]
}
```

Audio: stereo WAV, 24kHz, 16-bit PCM. Left channel = agent (Speaker A), right channel = user (Speaker B).

## Hardware

| Machine | Role | Specs |
|---------|------|-------|
| DGX Spark 1 (spark-9000) | Pipeline + downloads | NVIDIA GB10 Blackwell, 128GB RAM, 3.7TB NVMe |
| DGX Spark 2 (spark-f5af) | Pipeline (via Ethernet to Spark 1) | Same specs |

Both GPUs run at ~80-95% utilization. Pipeline produces ~2h of clean training data per hour per Spark.

## Scripts

| Script | Purpose |
|--------|---------|
| `src/scraper/cli.py` | Podcast discovery (Spreaker, Apple Charts, Podcast Index) |
| `scripts/diverse_download.py` | Download max N episodes per show for speaker diversity |
| `scripts/convert_single_model.py` | Main conversion pipeline (Demucs + diarize + transcribe + stereo) |
| `scripts/reprocess_demucs.py` | Batch reprocess existing WAVs through Demucs |
| `scripts/mimi_test.py` | Test Mimi codec quality on Italian audio |
| `scripts/parallel_download.py` | Multi-threaded bulk downloader |
| `scripts/start_workers.sh` | Launch conversion workers on a Spark |
| `scripts/start_spark2.sh` | Launch pipeline on Spark 2 |
| `scripts/status.sh` | Quick pipeline status check |
| `scripts/monitor_fast.sh` | Live monitor (run on Spark 1) |
| `scripts/live_monitor.sh` | Live monitor (run from Windows) |

## Quick Start

```bash
# 1. Discover Italian podcasts
python -m src.scraper.cli discover

# 2. Fetch episode lists
python -m src.scraper.cli episodes

# 3. Download diverse episodes (max 5 per show)
python scripts/diverse_download.py

# 4. Run conversion pipeline
python scripts/convert_single_model.py \
  --data-dir ./data/prod \
  --output-dir ./data/moshi/output \
  --episode-list data/prod/slice_0.txt \
  --hf-token YOUR_HF_TOKEN

# 5. Check status
bash scripts/status.sh
```

## Quality Controls

- **Demucs**: Strips background music/jingles, keeps only vocals
- **Monologue filter**: Skip episodes where one speaker >92% of talk time
- **Segment filter**: Drop segments with only one speaker present
- **Intro/outro trim**: Remove first/last 30 seconds (jingles)
- **Duration filter**: Only process episodes 10-120 minutes long

## Stats (live)

| Metric | Value |
|--------|-------|
| Shows discovered | 5,064 |
| Episodes cataloged | 466,036 |
| Total audio cataloged | 174,955h |
| Yield rate | ~60% of processed episodes produce output |
| Output rate | ~2h clean data per hour per GPU |

## License

Apache 2.0
