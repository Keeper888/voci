"""
Convert downloaded podcast MP3s to moshi-finetune format.

For each episode:
1. Resample to 24kHz mono WAV
2. Diarize speakers (pyannote 3.1)
3. Transcribe (faster-whisper large-v3-turbo)
4. Split to stereo WAV (Speaker A → left, Speaker B → right)
5. Segment into 30-120s chunks
6. Output: stereo WAV + JSON transcript + manifest entry

Usage:
    python scripts/convert_pipeline.py --data-dir ./data/prod --output-dir ./data/moshi
"""
import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

TARGET_SR = 24000
MIN_SEGMENT = 30   # seconds
MAX_SEGMENT = 120  # seconds
MIN_SPEAKERS = 2


def resample_to_wav(mp3_path: Path, wav_path: Path) -> bool:
    """Convert MP3 to 24kHz mono WAV via FFmpeg."""
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(mp3_path),
        "-ar", str(TARGET_SR), "-ac", "1", "-f", "wav",
        str(wav_path)
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    return result.returncode == 0


def diarize(wav_path: Path, pipeline) -> list[dict]:
    """Run pyannote diarization. Returns list of {start, end, speaker}."""
    result = pipeline(str(wav_path))
    diarization = result.speaker_diarization if hasattr(result, 'speaker_diarization') else result
    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "start": round(turn.start, 3),
            "end": round(turn.end, 3),
            "speaker": speaker,
        })
    return segments


def transcribe(wav_path: Path, model, segments: list[dict]) -> list[dict]:
    """Transcribe each diarized segment with openai-whisper."""
    import whisper
    audio, sr = sf.read(str(wav_path))

    results = []
    for seg in segments:
        start_sample = int(seg["start"] * sr)
        end_sample = int(seg["end"] * sr)
        chunk = audio[start_sample:end_sample]

        if len(chunk) < sr * 0.3:  # skip < 0.3s
            continue

        # Write temp chunk for whisper
        tmp_path = Path("/tmp/whisper_chunk.wav")
        sf.write(str(tmp_path), chunk, sr)

        result = model.transcribe(
            str(tmp_path), language="it", beam_size=5,
            word_timestamps=True
        )

        text_parts = []
        words = []
        for ws in result.get("segments", []):
            text_parts.append(ws["text"].strip())
            for w in ws.get("words", []):
                words.append({
                    "word": w["word"].strip(),
                    "start": round(seg["start"] + w["start"], 3),
                    "end": round(seg["start"] + w["end"], 3),
                })

        text = " ".join(text_parts).strip()
        if text:
            results.append({
                "start": seg["start"],
                "end": seg["end"],
                "speaker": seg["speaker"],
                "text": text,
                "words": words,
            })

    return results


def make_stereo(mono_audio: np.ndarray, sr: int, transcript: list[dict],
                speaker_a: str, speaker_b: str) -> np.ndarray:
    """Split mono audio into stereo: speaker_a → left, speaker_b → right."""
    n_samples = len(mono_audio)
    stereo = np.zeros((n_samples, 2), dtype=np.float32)

    for seg in transcript:
        start = int(seg["start"] * sr)
        end = min(int(seg["end"] * sr), n_samples)
        if seg["speaker"] == speaker_a:
            stereo[start:end, 0] = mono_audio[start:end]  # left
        elif seg["speaker"] == speaker_b:
            stereo[start:end, 1] = mono_audio[start:end]  # right

    return stereo


def segment_audio(stereo: np.ndarray, sr: int, transcript: list[dict],
                  min_dur: float, max_dur: float) -> list[tuple]:
    """Split into segments of min_dur to max_dur seconds at speaker boundaries.
    Returns list of (start_sample, end_sample, segment_transcript)."""
    if not transcript:
        return []

    segments = []
    current_start = 0
    current_transcript = []

    for i, turn in enumerate(transcript):
        turn_end_sample = int(turn["end"] * sr)
        current_transcript.append(turn)
        current_duration = (turn_end_sample - current_start) / sr

        # Check if we should cut here
        is_last = i == len(transcript) - 1
        next_speaker_change = (not is_last and
                               transcript[i + 1]["speaker"] != turn["speaker"])

        if current_duration >= min_dur and (next_speaker_change or
                                            current_duration >= max_dur or
                                            is_last):
            segments.append((current_start, turn_end_sample, current_transcript))
            current_start = turn_end_sample
            current_transcript = []

    # Handle leftover
    if current_transcript:
        turn_end_sample = int(current_transcript[-1]["end"] * sr)
        if (turn_end_sample - current_start) / sr >= 10:  # at least 10s
            segments.append((current_start, turn_end_sample, current_transcript))

    return segments


def process_episode(mp3_path: Path, output_dir: Path, episode_id: str,
                    diarize_pipeline, whisper_model, manifest_file) -> bool:
    """Full pipeline for one episode."""
    wav_path = Path(f"/tmp/voci_{episode_id}.wav")

    # 1. Resample
    log.info(f"  Resampling {mp3_path.name}...")
    if not resample_to_wav(mp3_path, wav_path):
        log.warning(f"  FFmpeg failed for {mp3_path}")
        return False

    # 2. Diarize
    log.info(f"  Diarizing...")
    try:
        diar_segments = diarize(wav_path, diarize_pipeline)
    except Exception as e:
        log.warning(f"  Diarization failed: {e}")
        wav_path.unlink(missing_ok=True)
        return False

    # Count unique speakers and check balance
    speaker_dur = {}
    for s in diar_segments:
        speaker_dur[s["speaker"]] = speaker_dur.get(s["speaker"], 0) + (s["end"] - s["start"])

    if len(speaker_dur) < MIN_SPEAKERS:
        log.info(f"  Skipping — only {len(speaker_dur)} speaker(s)")
        wav_path.unlink(missing_ok=True)
        return False

    # Check if dominant speaker has >70% — monologue, skip entirely
    total_speech = sum(speaker_dur.values())
    top_speakers = sorted(speaker_dur, key=speaker_dur.get, reverse=True)
    dominant_ratio = speaker_dur[top_speakers[0]] / total_speech if total_speech > 0 else 1.0

    if dominant_ratio > 0.92:
        log.info(f"  Skipping — dominant speaker {dominant_ratio:.0%} (true monologue)")
        wav_path.unlink(missing_ok=True)
        return False

    speaker_a, speaker_b = top_speakers[0], top_speakers[1]
    log.info(f"  Speaker balance: {speaker_dur[speaker_a]/total_speech:.0%} / {speaker_dur[speaker_b]/total_speech:.0%}")

    # Filter to only top 2 speakers
    diar_segments = [s for s in diar_segments if s["speaker"] in (speaker_a, speaker_b)]

    # 3. Transcribe (only runs if we passed the balance check — saves GPU time)
    log.info(f"  Transcribing ({len(diar_segments)} segments)...")
    try:
        transcript = transcribe(wav_path, whisper_model, diar_segments)
    except Exception as e:
        log.warning(f"  Transcription failed: {e}")
        wav_path.unlink(missing_ok=True)
        return False

    if not transcript:
        log.info(f"  Skipping — empty transcript")
        wav_path.unlink(missing_ok=True)
        return False

    # 4. Make stereo
    log.info(f"  Creating stereo...")
    mono_audio, sr = sf.read(str(wav_path))
    stereo = make_stereo(mono_audio, sr, transcript, speaker_a, speaker_b)

    # 5. Segment
    chunks = segment_audio(stereo, sr, transcript, MIN_SEGMENT, MAX_SEGMENT)
    log.info(f"  Split into {len(chunks)} segments")

    # 6. Write output (with quality filters)
    written = 0
    for idx, (start, end, seg_transcript) in enumerate(chunks):
        seg_id = f"{episode_id}_{idx:04d}"
        seg_audio = stereo[start:end]
        seg_duration = len(seg_audio) / sr

        # Adjust transcript timestamps relative to segment start
        seg_start_sec = start / sr
        adjusted_transcript = []
        for turn in seg_transcript:
            adjusted_transcript.append({
                "start": round(turn["start"] - seg_start_sec, 3),
                "end": round(turn["end"] - seg_start_sec, 3),
                "speaker": "agent" if turn["speaker"] == speaker_a else "user",
                "text": turn["text"],
            })

        # FILTER: Skip segments with literally zero from second speaker
        seg_speakers = set(t["speaker"] for t in adjusted_transcript)
        if len(seg_speakers) < 2:
            continue

        # FILTER: Skip segments where transcript looks like garbage (Whisper hallucination)
        all_text = " ".join(t["text"] for t in adjusted_transcript)
        if len(all_text) < 20:
            continue

        written += 1

        # Write stereo WAV
        audio_path = output_dir / f"{seg_id}.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(audio_path), seg_audio, sr, subtype="PCM_16")

        # Write JSON transcript
        json_path = output_dir / f"{seg_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "audio_file": str(audio_path),
                "duration": round(seg_duration, 2),
                "source_episode": episode_id,
                "transcript": adjusted_transcript,
            }, f, ensure_ascii=False, indent=2)

        # Append to manifest
        manifest_file.write(json.dumps({
            "audio": str(audio_path),
            "duration": round(seg_duration, 2),
        }) + "\n")
        manifest_file.flush()

    log.info(f"  Kept {written}/{len(chunks)} segments (filtered {len(chunks)-written} single-speaker/unbalanced)")

    # Cleanup
    wav_path.unlink(missing_ok=True)
    return written > 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("./data/prod"))
    parser.add_argument("--output-dir", type=Path, default=Path("./data/moshi"))
    parser.add_argument("--whisper-model", default="large-v3-turbo")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--hf-token", type=str, default=None, help="HuggingFace token for pyannote")
    parser.add_argument("--episode-list", type=Path, default=None, help="File with episode IDs to process (one per line)")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Load models
    log.info("Loading openai-whisper model...")
    import whisper
    whisper_model = whisper.load_model("turbo", device="cuda")
    log.info("Whisper turbo loaded on CUDA")

    log.info("Loading pyannote diarization pipeline...")
    from pyannote.audio import Pipeline
    diarize_kwargs = {}
    if args.hf_token:
        diarize_kwargs["token"] = args.hf_token
    diarize_pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", **diarize_kwargs
    ).to(torch.device("cuda"))

    # Open manifest
    manifest_path = args.output_dir / "manifest.jsonl"
    manifest_file = open(manifest_path, "a", encoding="utf-8")

    # Find downloaded episodes
    import sqlite3
    db = sqlite3.connect(str(args.data_dir / "index.db"))
    db.row_factory = sqlite3.Row

    # Track what we've already processed
    processed_file = args.output_dir / "processed.txt"
    processed = set()
    if processed_file.exists():
        processed = set(processed_file.read_text().strip().split("\n"))

    # Load episode filter if provided
    episode_filter = None
    if args.episode_list and args.episode_list.exists():
        episode_filter = set(args.episode_list.read_text().strip().split("\n"))
        log.info(f"Filtering to {len(episode_filter)} episodes from {args.episode_list}")

    rows = db.execute(
        "SELECT episode_id, file_path FROM episodes "
        "WHERE download_state = 'completed' AND file_path IS NOT NULL "
        "ORDER BY downloaded_at"
    ).fetchall()

    total = 0
    success = 0
    for row in rows:
        episode_id = row["episode_id"]
        if episode_id in processed:
            continue
        if episode_filter and episode_id not in episode_filter:
            continue

        file_path = Path(row["file_path"])
        if not file_path.is_absolute():
            file_path = args.data_dir / file_path

        if not file_path.exists():
            continue

        total += 1
        log.info(f"[{total}] Processing {episode_id}...")
        ok = process_episode(file_path, args.output_dir / "train", episode_id,
                             diarize_pipeline, whisper_model, manifest_file)
        if ok:
            success += 1
            with open(processed_file, "a") as f:
                f.write(episode_id + "\n")

        log.info(f"  {'OK' if ok else 'SKIP'} | {success}/{total} processed")

    manifest_file.close()
    db.close()
    log.info(f"Done. {success}/{total} episodes converted to moshi format.")


if __name__ == "__main__":
    main()
