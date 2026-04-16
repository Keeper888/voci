# Quality Control

## Overview

With 5,000 hours of automatically processed audio, quality control is critical. Not every segment will be usable. This document defines the filtering pipeline that ensures the final dataset meets quality standards.

## Quality Dimensions

### 1. ASR Confidence

**What**: How confident Whisper was in its transcription.
**Threshold**: Segment mean confidence >= 0.80
**Action**: Below threshold → flagged for review or excluded

```python
# Per-segment filtering
if segment.asr_confidence < 0.80:
    segment.quality_flag = "low_asr_confidence"
    
# Per-word filtering within segments
segment.words = [w for w in segment.words if w.confidence >= 0.50]
```

### 2. Audio Quality

**What**: Signal-to-noise ratio, clipping, distortion, music contamination.
**Detection**: Audio quality classifier (simple CNN on mel spectrograms)
**Categories**:
- `studio` — Clean, professional recording
- `good` — Minor background noise, acceptable
- `fair` — Noticeable noise but speech is clear
- `poor` — Significant noise, speech partially obscured
- `unusable` — Music, heavy distortion, or inaudible

**Threshold**: Exclude `unusable`, flag `poor`

### 3. Language Purity

**What**: Proportion of the episode that is actually Italian.
**Detection**: Language ID on segments (faster-whisper provides this)
**Threshold**: Episode must be >= 90% Italian
**Exception**: Code-switching segments (Italian + English/dialect) are kept and labeled

### 4. Speaker Diarization Quality

**What**: Whether pyannote correctly identified speakers.
**Signals of bad diarization**:
- Too many speakers detected (>10 for a 2-person podcast)
- Speaker segments too short (<0.3s average)
- Single speaker dominates >95% (probably failed to split)

**Action**: Flag for review, exclude worst cases

### 5. Segment Duration

| Duration | Action |
|----------|--------|
| < 0.3s | Exclude (too short for meaningful content) |
| 0.3s - 0.5s | Keep if backchannel/filler, otherwise exclude |
| 0.5s - 120s | Keep (normal range) |
| > 120s | Split or exclude (diarization likely failed) |

### 6. Paralinguistic Detection Confidence

**What**: How confident Pass 2 was in detected events.
**Threshold**: Event confidence >= 0.70
**Action**: Below threshold → remove the paralinguistic label (keep the segment text)

## Filtering Pipeline

```
Raw Pass 1 + Pass 2 output (all segments)
    ↓
┌─────────────────────────────────┐
│ Stage 1: Hard filters           │
│ - Remove segments < 0.3s       │
│ - Remove unusable audio quality │
│ - Remove non-Italian episodes   │
│ - Remove episodes with >10      │
│   detected speakers             │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ Stage 2: Confidence filters     │
│ - Flag segments with ASR < 0.80│
│ - Remove para events < 0.70    │
│ - Flag poor audio quality      │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ Stage 3: Deduplication          │
│ - Audio fingerprint matching    │
│ - Remove duplicate episodes     │
│ - Remove reposted content       │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ Stage 4: Statistical validation │
│ - Check distribution of labels  │
│ - Flag episodes that are        │
│   statistical outliers          │
│ - Verify speaker balance        │
└──────────────┬──────────────────┘
               ↓
┌─────────────────────────────────┐
│ Stage 5: Human spot check       │
│ - Random 1% sample              │
│ - Manual verification           │
│ - Adjust thresholds if needed   │
└──────────────┬──────────────────┘
               ↓
Final dataset (quality-assured)
```

## Expected Loss Rates

| Filter | Estimated data loss |
|--------|-------------------|
| Audio quality (unusable) | ~5% |
| Language purity | ~2% |
| ASR confidence | ~8% |
| Diarization failures | ~3% |
| Duration filters | ~2% |
| Deduplication | ~5% |
| **Total loss** | **~20-25%** |

This means we should scrape **~6,500h** to end up with **~5,000h** usable.

## Monitoring Dashboard

Track quality metrics across the full corpus:

- ASR confidence distribution (histogram)
- Paralinguistic event frequency by type
- Emotion distribution
- Speaker count distribution per episode
- Audio quality category distribution
- Processing failures by stage
- Cumulative hours processed over time
