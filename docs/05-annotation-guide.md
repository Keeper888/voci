# Annotation Guide

## Purpose

This guide defines the protocol for manually annotating ~50-100 hours of Italian conversational audio with paralinguistic events. These annotations are used to fine-tune the self-supervised model (Phase B of Pass 2).

**Quality over quantity.** 50 hours of carefully annotated data is worth more than 200 hours of sloppy labels. Every annotation should be defensible.

## Annotator Requirements

- Native Italian speaker (any regional variety)
- Familiar with conversational Italian across registers (formal, informal, dialect-influenced)
- Trained on this guide + passed qualification test

## Tooling

We'll build a web-based annotation UI (`annotation/` directory) that provides:

- Audio waveform visualization
- Playback with speed control (0.5x to 2x)
- Pre-loaded Pass 1 transcript (annotators see the text, correct if needed, and add paralinguistic labels)
- Click-and-drag region selection for labeling
- Keyboard shortcuts for common labels
- Inter-annotator agreement tracking

## Label Taxonomy

### Frame-Level Labels (applied to audio regions)

| Label | Code | Description | Examples |
|-------|------|-------------|----------|
| **Filler** | `FIL` | Vocalized pause, thinking sound | ehm, mhm, ah, uh, boh, mah, eh |
| **Backchannel** | `BCH` | Listener feedback signal | sì sì, esatto, certo, no?, già, eh già, ok ok |
| **Laughter** | `LAU` | Standalone laughter | [ha ha], [risata], chuckle |
| **Laugh-speech** | `LAS` | Speaking while laughing | words spoken through laughter |
| **Hesitation** | `HES` | Stutters, restarts, blocks | "è— è—", "il— la—", repeated syllables |
| **False start** | `FST` | Abandoned utterance, restart | "volevo— no, intendevo dire..." |
| **Elongation** | `ELO` | Stretched sounds | "allooora", "nooo", "seeenti" |
| **Breath** | `BRE` | Audible breath intake | [inhale] between phrases |
| **Sigh** | `SIG` | Expressive exhale | [sospiro], expressing frustration/relief |
| **Overlap** | `OVL` | Two speakers simultaneously | mark both speaker regions |
| **Repair** | `REP` | Self-correction | "a Roma— a Milano volevo dire" |
| **Code-switch** | `CSW` | Language/dialect switch | English words, dialectal expressions |
| **Discourse marker** | `DIS` | Conversational structuring | "allora", "comunque", "tipo", "praticamente", "diciamo" |

### Segment-Level Labels (applied to full speaker turns)

| Label | Code | Description |
|-------|------|-------------|
| **Neutral** | `EMO_NEU` | Default emotional state |
| **Amused** | `EMO_AMU` | Light humor, smiling tone |
| **Sarcastic** | `EMO_SAR` | Ironic/sarcastic delivery |
| **Excited** | `EMO_EXC` | High energy, enthusiasm |
| **Annoyed** | `EMO_ANN` | Irritation, impatience |
| **Hesitant** | `EMO_HES` | Uncertainty, reluctance |
| **Angry** | `EMO_ANG` | Clear anger or frustration |
| **Sad** | `EMO_SAD` | Sadness, disappointment |
| **Surprised** | `EMO_SUR` | Surprise, disbelief |
| **Affectionate** | `EMO_AFF` | Warmth, tenderness |

## Annotation Rules

### General Principles

1. **Label what you hear, not what you infer.** If you can hear the elongation, label it. If you're guessing based on context, don't.
2. **When in doubt, don't label.** False negatives are better than false positives for training.
3. **Multiple labels can overlap.** A person can produce laugh-speech (LAS) while also elongating (ELO) a word.
4. **Context matters for discourse markers.** "Allora" at the start of a turn is `DIS`. "Allora" meaning "then/so" in a narrative is just speech.

### Specific Guidelines

**Fillers (FIL):**
- Must be a vocalized sound, not a word being used meaningfully
- "Mhm" as active listening = `BCH`, not `FIL`
- "Mhm" while thinking of what to say = `FIL`
- "Eh" as surprise = `EMO_SUR` context, not `FIL`

**Backchannels (BCH):**
- Must occur while another speaker is talking (or in direct response)
- Short confirmations: "sì", "ok", "esatto", "certo"
- Must NOT be the start of a new turn — that's just agreement

**Elongation (ELO):**
- Sound must be audibly stretched beyond normal duration
- Common on: "allora", "no", "sì", "ma", "eh", "vabbè"
- Don't label normal Italian vowel length as elongation

**False Starts (FST):**
- Speaker must audibly abandon the utterance and restart
- There should be a break or shift in delivery
- Don't confuse with repairs (REP) — repairs complete the thought, false starts abandon it

**Sarcasm (EMO_SAR):**
- Only label when prosodic cues are clear (exaggerated intonation, timing)
- If sarcasm is only detectable from text context (not audio), don't label it
- Italian sarcasm often uses elongation + flat affect — label both

## Data Selection for Annotation

### Diversity Requirements

The 50-100h annotation set must cover:

- **Speaker diversity**: At least 200 unique speakers, balanced M/F
- **Age range**: Young adults to elderly
- **Regional variety**: Northern, Central, Southern Italian + at least 3 dialect-heavy shows
- **Register range**: Casual chat, professional interview, heated debate, comedy
- **Topic range**: Politics, culture, sports, daily life, technology, relationships
- **Audio quality range**: Studio quality to phone calls

### Sampling Strategy

```
Total: 100h annotated

Studio quality interviews:     25h (clean, easy for model)
Casual multi-speaker chat:     25h (natural conversation, core use case)
Debate/heated discussion:      15h (emotional range, overlap)
Comedy/banter:                 15h (laughter, sarcasm, rapid-fire)
Phone-in segments:             10h (lower quality audio, real spontaneous speech)
Regional/dialect-heavy:        10h (code-switching, diverse accents)
```

## Quality Assurance

### Inter-Annotator Agreement

- Every 10th episode annotated by 2 annotators independently
- Measure Cohen's kappa per label category
- Target: kappa > 0.75 for frame-level, > 0.65 for emotion
- Disagreements resolved by third annotator (adjudicator)

### Annotator Calibration

- Weekly calibration sessions: all annotators label the same 5-minute clip
- Discuss disagreements, update guidelines if needed
- Monitor for annotator drift over time

### Qualification Test

Before starting, each annotator must:
1. Read this guide completely
2. Annotate a 30-minute calibration clip
3. Achieve >80% agreement with gold standard on frame labels
4. Achieve >70% agreement with gold standard on emotion labels
