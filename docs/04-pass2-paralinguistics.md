# Pass 2 — Paralinguistic Detection

## Goal

Detect and label the non-verbal and paraverbal events that standard ASR (Whisper) deliberately strips out. This is what makes Voci unique — capturing the full texture of Italian conversation.

## What Whisper Misses

Whisper is trained to produce clean, readable text. It actively removes or normalizes:

| Real Speech | Whisper Output | What's Lost |
|------------|---------------|-------------|
| "Allooora..." | "Allora" | Elongation (signals thinking/stalling) |
| "Volevo— no cioè..." | "Volevo no cioè" | False start marker (—) |
| [laughing] "dai smettila" | "dai smettila" | Laughter during speech |
| "mhm" | (often omitted) | Backchannel (active listening signal) |
| [sigh] "vabbè" | "vabbè" | Emotional cue (resignation) |
| "ehm... tipo..." | "tipo" | Fillers stripped |

These are not noise. They carry conversational meaning. A conversational AI that never produces "mhm" or laughs or hesitates sounds fundamentally inhuman.

## Approach: Self-Supervised Learning + Fine-Tuning

### Why Self-Supervised?

Labeling 5,000 hours of paralinguistic events manually is impossible. But:

1. **Self-supervised pre-training** learns audio representations from **unlabeled** data — just raw audio, no transcripts needed
2. The model learns acoustic patterns: what laughter sounds like, what hesitation sounds like, what emotional shifts sound like
3. Then we **fine-tune on a small labeled set** (~50-100h) to teach it our specific label taxonomy
4. The fine-tuned model generalizes across the full 5,000h

This is the same approach Meta used for HuBERT and Microsoft used for WavLM — proven at scale.

### Model Selection

| Model | Strengths | Our Use |
|-------|-----------|---------|
| **HuBERT** (Meta) | Best for speech structure, phonetic patterns | Primary candidate for paralinguistic detection |
| **WavLM** (Microsoft) | Trained with denoising — better for non-speech events | Strong alternative, especially for laughter/breath |
| **emotion2vec** | Pre-trained specifically for emotion recognition | Emotion layer (complement to HuBERT/WavLM) |

**Recommended**: WavLM as the paralinguistic backbone (its denoising pretext task makes it naturally attentive to non-speech sounds) + emotion2vec as a specialized emotion classifier.

## Three Phases

### Phase A: Self-Supervised Pre-Training

**Input**: All 5,000h of raw Italian podcast audio (no labels)
**Output**: An Italian conversational speech encoder

```
Pre-trained WavLM (English-heavy)
    ↓
Continue pre-training on 5,000h Italian conversational audio
    ↓
WavLM-IT-Conv (Italian conversational speech encoder)
```

**What it learns** (unsupervised):
- Italian phonetic patterns and prosody
- Conversational rhythm (turn-taking timing)
- Non-speech sound patterns (laughter, sighs, fillers)
- Speaker variation in Italian accents/dialects
- Emotional prosody patterns

**Training config:**
```yaml
model: wavlm-base-plus  # or wavlm-large
training:
  epochs: 3-5
  learning_rate: 5e-5
  batch_size: 32  # 128GB allows large batches
  max_audio_length: 30  # seconds per sample
  masking:
    prob: 0.065
    length: 10
  optimizer: adam
  scheduler: linear_warmup
  warmup_steps: 32000
  fp16: true
```

**Compute estimate:**
- 2x DGX Spark: ~7-14 days for full pre-training
- Checkpoint every epoch

### Phase B: Fine-Tuning on Annotated Data

**Input**: ~50-100h of manually annotated audio (see Annotation Guide)
**Output**: Paralinguistic classifier

```
WavLM-IT-Conv (from Phase A)
    ↓
Add classification head (per-frame labels)
    ↓
Fine-tune on annotated data
    ↓
Voci-Para (paralinguistic detector)
```

**Label scheme** (frame-level classification):

Each 20ms audio frame gets one or more labels:
```
speech          — normal speech (default)
filler          — ehm, mhm, ah, boh, mah
backchannel     — sì sì, esatto, certo, no?
laugh           — laughter (standalone)
laugh_speech    — laughing while speaking
hesitation      — stutters, restarts, "è— è—"
elongation      — stretched vowels "nooo", "allooora"
breath          — audible breath
sigh            — sigh
overlap         — two speakers simultaneously
silence         — pause (contextually meaningful)
noise           — background noise, music
```

**Emotion layer** (segment-level, via emotion2vec):
```
neutral, amused, sarcastic, excited, annoyed,
hesitant, angry, sad, surprised, affectionate
```

**Training config:**
```yaml
model: wavlm-it-conv  # Our pre-trained model
head: token_classification
num_labels: 12  # paralinguistic categories
training:
  epochs: 20-30
  learning_rate: 1e-4
  batch_size: 16
  max_audio_length: 30
  optimizer: adam
  scheduler: cosine
  fp16: true
  class_weights: true  # Handle class imbalance (speech >> filler)
```

**Compute estimate:** 4-8 hours on single DGX Spark

### Phase C: Full-Corpus Inference

**Input**: All 5,000h audio + Pass 1 timestamps
**Output**: Paralinguistic annotations aligned to transcript

```python
# For each episode:
audio = load_audio(episode_path)
pass1 = load_pass1_transcript(episode_id)

# Run paralinguistic detector (per-frame)
frames = model.predict(audio)  # [speech, filler, laugh, ...]

# Run emotion classifier (per-segment)
for segment in pass1.segments:
    segment_audio = extract(audio, segment.start, segment.end)
    emotion = emotion_model.predict(segment_audio)

# Align frame-level detections to word-level timestamps
paralinguistics = align_to_words(frames, pass1.word_timestamps)
```

**Compute estimate:** 2x DGX Spark, ~3-4 days

## Handling Edge Cases

### Overlapping Speech
- pyannote detects overlap regions
- Pass 2 confirms and labels them
- Transcript shows both speakers with `[overlap]` markers

### Dialect and Code-Switching
- Italian podcasts frequently mix standard Italian with dialect and English
- WavLM-IT-Conv learns these patterns during pre-training
- Code-switching detector labels segments where language shifts

### Music and Jingles
- Podcast intros/outros often have music
- Classify as `noise` and exclude from transcript
- Use simple audio classifier: speech vs music vs silence

### Sarcasm and Irony
- The hardest category — prosodic cues are subtle
- emotion2vec provides baseline
- Fine-tuning on Italian-specific examples improves detection
- Expect lower accuracy here (~70%) vs other categories (~90%+)
