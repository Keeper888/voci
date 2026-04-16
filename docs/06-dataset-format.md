# Dataset Format Specification

## Overview

The Voci dataset is distributed as a collection of JSON files (one per episode) paired with audio references. This document defines the schema for the final merged output.

## File Structure

```
voci-dataset/
├── metadata.json               # Dataset-level metadata
├── splits/
│   ├── train.json              # Episode IDs for training
│   ├── validation.json         # Episode IDs for validation
│   └── test.json               # Episode IDs for testing
├── episodes/
│   ├── {episode_id}.json       # Transcript + annotations
│   └── ...
└── audio/                      # Optional: audio references or segments
    ├── {episode_id}/
    │   ├── full.wav            # Full episode audio (16kHz mono)
    │   └── segments/           # Pre-cut speaker segments
    │       ├── seg_001.wav
    │       └── ...
    └── ...
```

## Dataset Metadata (`metadata.json`)

```json
{
  "name": "voci",
  "version": "1.0.0",
  "description": "5,000 hours of Italian conversational speech with rich paralinguistic annotation",
  "language": "it",
  "license": "Apache-2.0",
  "total_hours": 5000.0,
  "total_episodes": 25000,
  "total_segments": 15000000,
  "unique_speakers_estimate": 8000,
  "creation_date": "2026-XX-XX",
  "pipeline_version": "1.0.0",
  "models_used": {
    "asr": "faster-whisper large-v3-turbo",
    "diarization": "pyannote 3.1",
    "alignment": "whisperx",
    "paralinguistics": "wavlm-it-conv-finetuned",
    "emotion": "emotion2vec"
  },
  "annotation": {
    "manual_hours": 100,
    "annotators": "N",
    "inter_annotator_kappa": 0.78
  },
  "splits": {
    "train": {"hours": 4500, "episodes": 22500},
    "validation": {"hours": 250, "episodes": 1250},
    "test": {"hours": 250, "episodes": 1250}
  }
}
```

## Episode Schema (`episodes/{episode_id}.json`)

```json
{
  "episode_id": "ep_a1b2c3d4",
  "source": {
    "show_name": "Il Podcast Esempio",
    "show_id": "show_xyz789",
    "episode_title": "Puntata 42 — Parliamo di tutto",
    "published_date": "2025-06-15",
    "feed_url": "https://example.com/feed.xml",
    "original_url": "https://example.com/ep42.mp3"
  },
  "audio": {
    "duration_seconds": 3612.5,
    "sample_rate": 16000,
    "channels": 1,
    "format": "wav",
    "file": "audio/ep_a1b2c3d4/full.wav"
  },
  "speakers": {
    "count": 3,
    "labels": ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"],
    "durations": {
      "SPEAKER_00": 1450.2,
      "SPEAKER_01": 1320.8,
      "SPEAKER_02": 680.5
    }
  },
  "quality": {
    "asr_confidence_mean": 0.94,
    "asr_confidence_min": 0.62,
    "diarization_quality": "good",
    "audio_quality": "studio",
    "language_purity": 0.98
  },
  "segments": [
    {
      "id": "seg_001",
      "start": 0.500,
      "end": 8.340,
      "speaker": "SPEAKER_00",
      "text": "Buongiorno a tutti benvenuti in questa nuova puntata",
      "text_enriched": "Buongiorno a tutti benvenuti in questa nuova puntata",
      "words": [
        {"word": "Buongiorno", "start": 0.520, "end": 1.100, "confidence": 0.98},
        {"word": "a", "start": 1.120, "end": 1.200, "confidence": 0.99},
        {"word": "tutti", "start": 1.220, "end": 1.580, "confidence": 0.97},
        {"word": "benvenuti", "start": 1.640, "end": 2.200, "confidence": 0.96},
        {"word": "in", "start": 2.240, "end": 2.350, "confidence": 0.99},
        {"word": "questa", "start": 2.380, "end": 2.680, "confidence": 0.98},
        {"word": "nuova", "start": 2.720, "end": 3.050, "confidence": 0.97},
        {"word": "puntata", "start": 3.100, "end": 3.600, "confidence": 0.98}
      ],
      "paralinguistics": [],
      "emotion": "neutral",
      "emotion_confidence": 0.88,
      "asr_confidence": 0.97
    },
    {
      "id": "seg_042",
      "start": 245.100,
      "end": 252.800,
      "speaker": "SPEAKER_01",
      "text": "Allooora no aspetta— cioè volevo dire che secondo me...",
      "text_enriched": "Allooora [hesitation] no aspetta— cioè volevo dire che secondo me...",
      "words": [
        {"word": "Allooora", "start": 245.100, "end": 245.900, "confidence": 0.91},
        {"word": "no", "start": 246.200, "end": 246.400, "confidence": 0.95},
        {"word": "aspetta", "start": 246.450, "end": 246.900, "confidence": 0.94},
        {"word": "cioè", "start": 247.100, "end": 247.400, "confidence": 0.96},
        {"word": "volevo", "start": 247.500, "end": 247.850, "confidence": 0.95},
        {"word": "dire", "start": 247.900, "end": 248.150, "confidence": 0.97},
        {"word": "che", "start": 248.200, "end": 248.350, "confidence": 0.98},
        {"word": "secondo", "start": 248.400, "end": 248.800, "confidence": 0.96},
        {"word": "me", "start": 248.850, "end": 249.050, "confidence": 0.98}
      ],
      "paralinguistics": [
        {
          "type": "elongation",
          "code": "ELO",
          "start": 245.100,
          "end": 245.900,
          "token": "Allooora",
          "confidence": 0.89
        },
        {
          "type": "false_start",
          "code": "FST",
          "start": 246.200,
          "end": 246.900,
          "token": "no aspetta—",
          "confidence": 0.85
        },
        {
          "type": "filler",
          "code": "FIL",
          "start": 247.100,
          "end": 247.400,
          "token": "cioè",
          "confidence": 0.92
        }
      ],
      "emotion": "hesitant",
      "emotion_confidence": 0.81,
      "asr_confidence": 0.93
    },
    {
      "id": "seg_043",
      "start": 248.500,
      "end": 249.100,
      "speaker": "SPEAKER_00",
      "text": "[mhm]",
      "text_enriched": "[mhm]",
      "words": [
        {"word": "mhm", "start": 248.500, "end": 249.100, "confidence": 0.78}
      ],
      "paralinguistics": [
        {
          "type": "backchannel",
          "code": "BCH",
          "start": 248.500,
          "end": 249.100,
          "token": "mhm",
          "confidence": 0.90
        }
      ],
      "emotion": "neutral",
      "emotion_confidence": 0.92,
      "asr_confidence": 0.78,
      "overlap_with": "seg_042"
    }
  ],
  "statistics": {
    "total_segments": 892,
    "total_words": 18450,
    "paralinguistic_events": {
      "filler": 245,
      "backchannel": 189,
      "laugh": 67,
      "laugh_speech": 23,
      "hesitation": 112,
      "false_start": 45,
      "elongation": 98,
      "breath": 156,
      "sigh": 12,
      "overlap": 78,
      "repair": 34,
      "code_switch": 8,
      "discourse": 203
    },
    "emotion_distribution": {
      "neutral": 0.52,
      "amused": 0.15,
      "excited": 0.12,
      "hesitant": 0.08,
      "annoyed": 0.05,
      "sarcastic": 0.04,
      "surprised": 0.02,
      "affectionate": 0.01,
      "angry": 0.005,
      "sad": 0.005
    }
  }
}
```

## Field Definitions

### Segment Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique segment identifier within episode |
| `start` | float | yes | Start time in seconds |
| `end` | float | yes | End time in seconds |
| `speaker` | string | yes | Speaker label |
| `text` | string | yes | Enriched text (with paralinguistic spelling) |
| `text_enriched` | string | yes | Text with inline paralinguistic markers |
| `words` | array | yes | Word-level details with timestamps |
| `paralinguistics` | array | yes | Detected paralinguistic events (can be empty) |
| `emotion` | string | yes | Dominant emotion label |
| `emotion_confidence` | float | yes | Emotion classification confidence |
| `asr_confidence` | float | yes | Mean ASR confidence for this segment |
| `overlap_with` | string | no | ID of overlapping segment (if any) |

### Paralinguistic Event Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Event type (see taxonomy) |
| `code` | string | Short code |
| `start` | float | Event start time |
| `end` | float | Event end time |
| `token` | string | The text/sound associated with the event |
| `confidence` | float | Detection confidence |

## HuggingFace Distribution

The dataset will be published to HuggingFace Hub with:

- Streaming support (no need to download all 5,000h)
- Train/validation/test splits
- Dataset card with full documentation
- Loading script for common frameworks (PyTorch, TensorFlow)

```python
from datasets import load_dataset

# Load just transcripts (fast)
ds = load_dataset("AntonioGison/voci", streaming=True)

# Load with audio
ds = load_dataset("AntonioGison/voci", "with_audio", streaming=True)
```
