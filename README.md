# Voci

**5,000 hours of Italian conversational speech with rich paralinguistic transcription.**

Voci (Italian for "voices") is an open-source pipeline that builds a large-scale Italian conversational speech dataset from publicly available podcasts. Unlike existing datasets that produce sanitized text, Voci preserves the full texture of real conversation — hesitations, laughter, sarcasm, fillers, false starts, and emotional tone.

## Why

Current Italian speech datasets are either too small, too clean, or based on read speech (audiobooks, parliament). None of them capture how Italians actually talk. Conversational AI trained on clean transcripts sounds robotic because it never learned the "shade" — the paralinguistic layer that makes human conversation human.

Voci solves this with a two-pass pipeline:

1. **Pass 1 — ASR + Diarization**: WhisperX (faster-whisper + pyannote) produces high-accuracy transcripts with speaker labels and timestamps
2. **Pass 2 — Paralinguistic Detection**: Self-supervised models (HuBERT/WavLM) pre-trained on the full unlabeled corpus, then fine-tuned on a small manually annotated subset, detect and label non-verbal events that Whisper ignores

The result is a dataset where every utterance includes not just *what* was said, but *how* — with speaker identity, emotional cues, and conversational dynamics.

## Output Format

```json
{
  "episode_id": "ep_abc123",
  "source": "podcast_name",
  "language": "it",
  "segments": [
    {
      "start": 12.340,
      "end": 15.780,
      "speaker": "Speaker_A",
      "text": "Allooora no aspetta— cioè volevo dire che...",
      "raw_text": "allora no aspetta cioè volevo dire che",
      "paralinguistics": [
        {"type": "elongation", "token": "Allooora", "start": 12.340, "end": 12.980},
        {"type": "false_start", "token": "no aspetta—", "start": 13.100, "end": 13.650},
        {"type": "filler", "token": "cioè", "start": 13.700, "end": 13.950}
      ],
      "emotion": "hesitant",
      "confidence": 0.94
    },
    {
      "start": 15.200,
      "end": 15.600,
      "speaker": "Speaker_B",
      "text": "[mhm]",
      "paralinguistics": [
        {"type": "backchannel", "token": "mhm", "start": 15.200, "end": 15.600}
      ],
      "emotion": "neutral",
      "confidence": 0.91
    }
  ]
}
```

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        VOCI PIPELINE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────┐    ┌──────────┐    ┌──────────┐                 │
│  │  Podcast   │───▶│ Download │───▶│  Audio   │                │
│  │  Scraper   │    │ Manager  │    │  Store   │                │
│  └───────────┘    └──────────┘    └─────┬────┘                 │
│                                         │                       │
│                          ┌──────────────┼──────────────┐        │
│                          ▼              ▼              ▼        │
│                   ┌────────────┐ ┌────────────┐ ┌──────────┐   │
│         Pass 1:   │  faster-   │ │  pyannote  │ │  Word    │   │
│                   │  whisper   │ │  3.1       │ │  Align   │   │
│                   │  (ASR)     │ │  (diariz.) │ │          │   │
│                   └─────┬──────┘ └─────┬──────┘ └────┬─────┘   │
│                         └──────────────┼─────────────┘          │
│                                        ▼                        │
│                              ┌──────────────────┐               │
│                              │  Base Transcript  │              │
│                              │  + Speakers       │              │
│                              │  + Timestamps     │              │
│                              └────────┬─────────┘               │
│                                       │                         │
│                          ┌────────────┼────────────┐            │
│                          ▼            ▼            ▼            │
│                   ┌───────────┐ ┌──────────┐ ┌──────────────┐  │
│         Pass 2:   │  HuBERT/  │ │ emotion  │ │ Paralinguist │  │
│                   │  WavLM    │ │ 2vec     │ │ ic Detector  │  │
│                   │  (SSL)    │ │          │ │              │  │
│                   └─────┬─────┘ └────┬─────┘ └──────┬───────┘  │
│                         └────────────┼──────────────┘           │
│                                      ▼                          │
│                            ┌──────────────────┐                 │
│                            │   Rich Merged    │                 │
│                            │   Transcript     │                 │
│                            └────────┬─────────┘                 │
│                                     ▼                           │
│                          ┌──────────────────┐                   │
│                          │  Quality Filter  │                   │
│                          │  + Validation    │                   │
│                          └────────┬─────────┘                   │
│                                   ▼                             │
│                          ┌──────────────────┐                   │
│                          │  Final Dataset   │                   │
│                          │  (JSON + Audio)  │                   │
│                          └──────────────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Paralinguistic Taxonomy

Voci defines a rich set of non-verbal and paraverbal events:

| Category | Tags | Examples |
|----------|------|----------|
| **Fillers** | `filler` | ehm, mhm, ah, eh, boh, mah |
| **Backchannels** | `backchannel` | sì sì, eh già, no?, certo, esatto |
| **Laughter** | `laugh`, `laugh_speech` | [risata], speaking while laughing |
| **Hesitations** | `hesitation`, `false_start` | "volevo— no cioè", "è— è—" |
| **Elongations** | `elongation` | "allooora", "nooo", "vabbè" |
| **Breath/Sighs** | `breath`, `sigh` | [sospiro], [respiro] |
| **Emotions** | `emotion` | hesitant, sarcastic, excited, annoyed, amused |
| **Overlap** | `overlap_start`, `overlap_end` | simultaneous speech markers |
| **Repairs** | `repair` | "a Roma— a Milano volevo dire" |
| **Code-switching** | `code_switch` | dialect/English insertions |
| **Discourse markers** | `discourse` | "allora", "comunque", "tipo", "praticamente" |

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | RTX 3090 (24GB) | DGX Spark (128GB) or A100 |
| RAM | 32GB | 64GB+ |
| Storage | 10TB (audio + dataset) | 20TB |
| Network | 100 Mbps | 1 Gbps |

## Project Structure

```
voci/
├── README.md
├── docs/                        # Detailed documentation (wiki)
│   ├── 01-architecture.md       # System architecture deep dive
│   ├── 02-podcast-scraper.md    # Scraper design and source list
│   ├── 03-pass1-asr.md          # WhisperX pipeline details
│   ├── 04-pass2-paralinguistics.md  # Self-supervised + fine-tune
│   ├── 05-annotation-guide.md   # Manual annotation protocol
│   ├── 06-dataset-format.md     # Output schema specification
│   ├── 07-quality-control.md    # Filtering and validation
│   └── 08-hardware-setup.md     # DGX Spark / GPU setup guide
├── src/
│   ├── scraper/                 # Podcast discovery and download
│   ├── pass1/                   # ASR + diarization pipeline
│   ├── pass2/                   # Paralinguistic detection
│   ├── merge/                   # Transcript merger
│   ├── quality/                 # Quality filtering
│   └── utils/                   # Shared utilities
├── configs/                     # Pipeline configuration files
├── scripts/                     # CLI entry points
├── tests/                       # Test suite
├── annotation/                  # Annotation tools and guidelines
└── pyproject.toml
```

## Quick Start

```bash
# Clone
git clone https://github.com/AntonioGison/voci.git
cd voci

# Install
pip install -e ".[dev]"

# Configure
cp configs/default.yaml configs/local.yaml
# Edit local.yaml with your paths and GPU settings

# Step 1: Scrape Italian podcasts
voci scrape --language it --output ./data/raw

# Step 2: Run ASR + diarization (Pass 1)
voci transcribe --input ./data/raw --output ./data/pass1 --model large-v3-turbo

# Step 3: Pre-train paralinguistic model (Pass 2 - self-supervised)
voci pretrain --input ./data/raw --output ./models/hubert-it --hours 5000

# Step 4: Fine-tune on annotated subset
voci finetune --model ./models/hubert-it --annotations ./data/annotated --output ./models/para-it

# Step 5: Run paralinguistic detection
voci detect --input ./data/raw --transcript ./data/pass1 --model ./models/para-it --output ./data/pass2

# Step 6: Merge and filter
voci merge --pass1 ./data/pass1 --pass2 ./data/pass2 --output ./data/final --min-confidence 0.85
```

## Roadmap

- [ ] **Phase 1 — Infrastructure**: Podcast scraper, download manager, storage
- [ ] **Phase 2 — Pass 1 Pipeline**: WhisperX integration, batch processing, GPU scheduling
- [ ] **Phase 3 — Self-Supervised Pre-training**: HuBERT/WavLM training on full corpus
- [ ] **Phase 4 — Annotation Tooling**: Web UI for paralinguistic annotation
- [ ] **Phase 5 — Pass 2 Pipeline**: Fine-tuned paralinguistic detector
- [ ] **Phase 6 — Merge + Quality**: Transcript merger, confidence filtering, validation
- [ ] **Phase 7 — Dataset Release**: Packaging, documentation, HuggingFace upload

## License

Apache 2.0

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
