# Architecture

## Overview

Voci is a two-pass pipeline that transforms raw podcast audio into richly annotated conversational transcripts. The design separates concerns cleanly: Pass 1 handles what standard ASR does well (speech-to-text, speakers, timing), while Pass 2 handles what ASR deliberately ignores (paralinguistics, emotion, conversational dynamics).

## Design Principles

1. **Modular passes** — Each pass can run independently. Pass 1 output is useful on its own; Pass 2 enriches it
2. **GPU-first** — Every compute-heavy step is designed for GPU acceleration. CPU fallbacks exist but are not the target
3. **Resumable** — Every stage writes checkpoints. A crash at hour 3,000 doesn't lose hours 1–2,999
4. **Deterministic** — Same input + same config = same output. No randomness in production runs
5. **Storage-aware** — 5,000 hours of audio is ~5–10TB. The pipeline streams where possible and manages disk lifecycle

## System Components

### 1. Podcast Scraper (`src/scraper/`)

Discovers and downloads Italian podcast episodes from public RSS feeds.

- **Discovery**: Crawls podcast directories (Apple Podcasts, Spotify catalog, Podchaser) for Italian-language shows
- **Filtering**: Excludes music-heavy shows, solo readings, news bulletins (too scripted)
- **Targeting**: Prioritizes multi-speaker conversational formats — interviews, panel discussions, debates, casual chat
- **Download Manager**: Parallel downloads with rate limiting, retry logic, and deduplication
- **Metadata Store**: SQLite database tracking every episode — source, duration, download state, processing state

### 2. Pass 1 — ASR + Diarization (`src/pass1/`)

Converts raw audio to text with speaker labels and word-level timestamps.

**Stack:**
- **faster-whisper** (CTranslate2) — Whisper large-v3-turbo, optimized inference
- **pyannote 3.1** — Speaker diarization (who speaks when)
- **WhisperX alignment** — Word-level timestamp alignment

**Process:**
```
Audio file (MP3/M4A/WAV)
    → FFmpeg decode to 16kHz mono WAV
    → pyannote: speaker segments [(start, end, speaker_id), ...]
    → faster-whisper: transcribe each speaker segment
    → WhisperX: word-level alignment
    → Output: transcript with speaker labels + word timestamps
```

**GPU Scheduling:**
- Each DGX Spark processes files from a shared queue (Redis or filesystem-based)
- Batch size tuned per GPU memory (128GB allows large batches)
- Progress tracked in SQLite — resumable after interruption

### 3. Pass 2 — Paralinguistic Detection (`src/pass2/`)

Detects and labels non-verbal events that Whisper strips out.

**Phase A — Self-Supervised Pre-training (unsupervised):**
```
All 5,000h raw audio (no labels needed)
    → HuBERT or WavLM base model
    → Continue pre-training on Italian conversational speech
    → Output: Italian conversational speech encoder
```

This teaches the model the acoustic patterns of Italian conversation — laughter sounds, hesitation patterns, filler intonation, emotional prosody — without any labels.

**Phase B — Fine-tuning (supervised, small scale):**
```
~100h manually annotated audio
    → Fine-tune the pre-trained encoder
    → Token classification: label each audio frame with paralinguistic tags
    → Output: paralinguistic detector model
```

**Phase C — Inference:**
```
All 5,000h audio + Pass 1 timestamps
    → Run paralinguistic detector
    → Align detected events with transcript words
    → Output: paralinguistic annotations per segment
```

### 4. Merge Engine (`src/merge/`)

Combines Pass 1 (text + speakers + timing) with Pass 2 (paralinguistics + emotion) into the final dataset format.

- Aligns paralinguistic events to transcript words using timestamps
- Resolves conflicts (e.g., Whisper transcribed "allora" but Pass 2 detected elongation → "allooora")
- Enriches raw text with paralinguistic markers
- Produces final JSON output per episode

### 5. Quality Control (`src/quality/`)

Filters the merged output to ensure dataset quality.

- **Confidence filtering**: Drop segments where ASR confidence < threshold
- **Duration filtering**: Drop segments shorter than 0.5s or longer than 60s
- **Speaker consistency**: Flag episodes where diarization produced too many/few speakers
- **Language check**: Verify Italian (reject episodes that are mostly other languages)
- **Audio quality**: Reject segments with excessive noise, music, or distortion
- **Deduplication**: Detect and remove duplicate episodes across sources

## Data Flow

```
                    ┌─────────────────┐
                    │  Podcast Index  │
                    │  (SQLite DB)    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   Raw Audio     │
                    │   /data/raw/    │
                    └───┬────────┬────┘
                        │        │
              ┌─────────▼──┐  ┌──▼──────────┐
              │  Pass 1    │  │  Pass 2a    │
              │  WhisperX  │  │  SSL Pretrain│
              └─────┬──────┘  └──────┬──────┘
                    │                │
                    │         ┌──────▼──────┐
                    │         │  Pass 2b    │
                    │         │  Fine-tune  │
                    │         └──────┬──────┘
                    │                │
                    │         ┌──────▼──────┐
                    │         │  Pass 2c    │
                    │         │  Inference  │
                    │         └──────┬──────┘
                    │                │
              ┌─────▼────────────────▼─────┐
              │        Merge Engine        │
              └─────────────┬──────────────┘
                            │
              ┌─────────────▼──────────────┐
              │      Quality Control       │
              └─────────────┬──────────────┘
                            │
              ┌─────────────▼──────────────┐
              │      Final Dataset         │
              │      /data/final/          │
              └────────────────────────────┘
```

## Multi-GPU Strategy

With 2x DGX Spark (128GB unified memory each):

| Task | GPU Allocation | Estimated Time |
|------|---------------|----------------|
| Pass 1 (WhisperX) | Both GPUs, parallel queue | ~4-5 days |
| Pass 2a (SSL pre-train) | Both GPUs, distributed training | ~7-14 days |
| Pass 2b (Fine-tune) | Single GPU | ~4-8 hours |
| Pass 2c (Inference) | Both GPUs, parallel queue | ~3-4 days |
| **Total** | | **~15-24 days** |

Pass 1 and Pass 2a can run concurrently if storage permits (both read from raw audio).
