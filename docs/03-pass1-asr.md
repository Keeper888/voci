# Pass 1 — ASR + Diarization

## Goal

Convert raw podcast audio into text transcripts with speaker labels and word-level timestamps. This is the "clean" transcription pass — high accuracy on what was said, but no paralinguistic detail.

## Stack

| Component | Library | Version | Purpose |
|-----------|---------|---------|---------|
| ASR | faster-whisper | latest | Speech-to-text (CTranslate2 optimized) |
| Model | Whisper large-v3-turbo | — | Best Italian accuracy / speed tradeoff |
| Diarization | pyannote.audio | 3.1+ | Speaker identification |
| Alignment | WhisperX | latest | Word-level timestamp alignment |
| Audio decode | FFmpeg | 6+ | Format conversion to 16kHz mono WAV |

## Pipeline Detail

### Step 1: Audio Preprocessing

```python
# Convert any format to 16kHz mono WAV (WhisperX input requirement)
ffmpeg -i input.mp3 -ar 16000 -ac 1 -f wav output.wav
```

- Normalize audio level (peak normalization to -3dB)
- No noise reduction at this stage (preserves paralinguistic signals for Pass 2)

### Step 2: Speaker Diarization (pyannote 3.1)

```python
from pyannote.audio import Pipeline

pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
diarization = pipeline(audio_file)

# Output: [(start, end, speaker_label), ...]
# e.g., [(0.5, 12.3, "SPEAKER_00"), (12.5, 25.1, "SPEAKER_01"), ...]
```

- Runs first to establish speaker segments
- pyannote 3.1 handles overlapping speech detection
- Speaker labels are per-episode (SPEAKER_00, SPEAKER_01, etc.)

### Step 3: ASR per Speaker Segment

```python
from faster_whisper import WhisperModel

model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")

for segment in diarization:
    audio_chunk = extract_audio(audio_file, segment.start, segment.end)
    result = model.transcribe(audio_chunk, language="it", beam_size=5)
```

- Transcribe each speaker segment independently
- Language forced to Italian (`language="it"`) — no auto-detect overhead
- Beam size 5 for quality (tradeoff: slower but more accurate)

### Step 4: Word-Level Alignment (WhisperX)

```python
import whisperx

# Align transcription to get word-level timestamps
alignment_model, metadata = whisperx.load_align_model(language_code="it", device="cuda")
aligned = whisperx.align(transcript, alignment_model, metadata, audio, device="cuda")
```

- Maps each word to precise start/end timestamps
- Critical for Pass 2 alignment later (paralinguistic events need to map to specific words)

### Step 5: Output Assembly

Combine diarization + ASR + alignment into structured output:

```json
{
  "episode_id": "ep_abc123",
  "audio_file": "shows/xyz/episodes/ep_abc123.mp3",
  "duration_seconds": 3600,
  "speakers_detected": 3,
  "segments": [
    {
      "id": "seg_001",
      "start": 0.500,
      "end": 12.300,
      "speaker": "SPEAKER_00",
      "text": "Buongiorno a tutti benvenuti in questa nuova puntata",
      "words": [
        {"word": "Buongiorno", "start": 0.520, "end": 1.100},
        {"word": "a", "start": 1.120, "end": 1.200},
        {"word": "tutti", "start": 1.220, "end": 1.580},
        ...
      ],
      "confidence": 0.96
    }
  ]
}
```

## GPU Configuration (DGX Spark)

### Memory Allocation (128GB unified)
- Whisper large-v3-turbo: ~6GB
- pyannote 3.1: ~2GB
- WhisperX alignment model: ~2GB
- Audio buffers + batch: ~10GB
- **Free for batching**: ~108GB

With 108GB free, we can process **multiple files simultaneously** on a single GPU.

### Batch Processing Strategy

```python
# Process N files concurrently on each GPU
# N depends on average episode length and memory
CONCURRENT_FILES = 8  # Conservative, tune up based on monitoring

# Queue: filesystem-based (simple) or Redis (distributed)
# Each GPU worker pulls from the queue
```

### Throughput Estimate

| Config | Speed | 5,000h Completion |
|--------|-------|-------------------|
| 1x DGX Spark, serial | ~15x real-time | ~14 days |
| 1x DGX Spark, 8x batch | ~80-100x real-time | ~2-3 days |
| 2x DGX Spark, 8x batch each | ~160-200x real-time | ~1-2 days |

## Error Handling

- **Audio decode failure**: Log, skip, continue (don't block queue)
- **OOM**: Reduce batch size, retry with single-file processing
- **Diarization failure**: Fall back to single-speaker mode (still useful for ASR)
- **Low confidence segments**: Keep them but flag (quality filter handles downstream)

## Checkpointing

- Per-episode state tracked in SQLite: `pending → processing → pass1_complete → failed`
- Intermediate outputs written per-episode (crash-safe)
- Resume: query for episodes in `pending` or `processing` state (processing = possibly interrupted)
