"""
Single-model conversion pipeline — one Whisper + one pyannote instance,
processes episodes from a queue. More efficient than multiple workers
each loading their own model copies.

Usage:
    python scripts/convert_single_model.py --data-dir ./data/prod --output-dir ./data/moshi --episode-list slices.txt
"""
import argparse
import json
import logging
import subprocess
import sqlite3
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

TARGET_SR = 24000
MIN_SEGMENT = 30
MAX_SEGMENT = 120


def resample_to_wav(mp3_path: Path, wav_path: Path) -> bool:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", str(TARGET_SR), "-ac", "1", "-f", "wav", str(wav_path)],
        capture_output=True, timeout=120
    )
    return result.returncode == 0


_demucs_model = None

def strip_music(wav_path: Path, device: str = "cuda") -> bool:
    """Remove background music using Demucs, keep only vocals.
    Loads model, processes in chunks, then UNLOADS to free GPU for Whisper/pyannote."""
    import torchaudio
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    # Load Demucs on GPU
    model = get_model("htdemucs").to(device)
    model.eval()

    waveform, sr = torchaudio.load(str(wav_path))
    if waveform.shape[0] == 1:
        waveform = waveform.repeat(2, 1)
    if sr != model.samplerate:
        waveform = torchaudio.transforms.Resample(sr, model.samplerate)(waveform)

    # Process in 60-second chunks
    chunk_size = 60 * model.samplerate
    overlap = int(0.5 * model.samplerate)
    total_samples = waveform.shape[1]
    vocals_chunks = []

    for start in range(0, total_samples, chunk_size - overlap):
        end = min(start + chunk_size, total_samples)
        chunk = waveform[:, start:end]

        with torch.no_grad():
            sources = apply_model(model, chunk.unsqueeze(0).to(device))
        vocals = sources[0, 3].mean(dim=0).cpu()

        if start > 0 and len(vocals) > overlap:
            vocals = vocals[overlap:]
        vocals_chunks.append(vocals)
        del sources

    vocals_full = torch.cat(vocals_chunks)

    if model.samplerate != TARGET_SR:
        vocals_full = torchaudio.transforms.Resample(model.samplerate, TARGET_SR)(vocals_full.unsqueeze(0)).squeeze(0)

    sf.write(str(wav_path), vocals_full.numpy(), TARGET_SR)

    # CRITICAL: Unload Demucs from GPU so Whisper/pyannote get full memory
    del model
    torch.cuda.empty_cache()

    return True


def diarize(wav_path: Path, pipeline):
    # Monkey-patch pyannote's TF32 disable — it kills Blackwell performance
    import pyannote.audio.utils.reproducibility as _repr
    _repr.handle_reproducibility = lambda x: None  # no-op

    result = pipeline(str(wav_path))

    # Re-enable TF32 in case pyannote disabled it elsewhere
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    diarization = result.speaker_diarization if hasattr(result, 'speaker_diarization') else result
    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({"start": round(turn.start, 3), "end": round(turn.end, 3), "speaker": speaker})
    return segments


def transcribe_segment(model, audio_chunk, sr, seg_start):
    """Transcribe a single audio chunk."""
    tmp_path = Path(f"/tmp/whisper_{id(audio_chunk)}.wav")
    sf.write(str(tmp_path), audio_chunk, sr)
    result = model.transcribe(str(tmp_path), language="it", beam_size=5, word_timestamps=True)
    tmp_path.unlink(missing_ok=True)

    text_parts = []
    words = []
    for ws in result.get("segments", []):
        text_parts.append(ws["text"].strip())
        for w in ws.get("words", []):
            words.append({"word": w["word"].strip(), "start": round(seg_start + w["start"], 3), "end": round(seg_start + w["end"], 3)})

    return " ".join(text_parts).strip(), words


def make_stereo(mono_audio, sr, transcript, speaker_a, speaker_b):
    n = len(mono_audio)
    stereo = np.zeros((n, 2), dtype=np.float32)
    for seg in transcript:
        start = int(seg["start"] * sr)
        end = min(int(seg["end"] * sr), n)
        if seg["speaker"] == speaker_a:
            stereo[start:end, 0] = mono_audio[start:end]
        elif seg["speaker"] == speaker_b:
            stereo[start:end, 1] = mono_audio[start:end]
    return stereo


def segment_audio(stereo, sr, transcript, min_dur, max_dur):
    if not transcript:
        return []
    segments = []
    current_start = 0
    current_transcript = []
    for i, turn in enumerate(transcript):
        turn_end = int(turn["end"] * sr)
        current_transcript.append(turn)
        dur = (turn_end - current_start) / sr
        is_last = i == len(transcript) - 1
        speaker_change = not is_last and transcript[i + 1]["speaker"] != turn["speaker"]
        if dur >= min_dur and (speaker_change or dur >= max_dur or is_last):
            segments.append((current_start, turn_end, current_transcript))
            current_start = turn_end
            current_transcript = []
    if current_transcript:
        turn_end = int(current_transcript[-1]["end"] * sr)
        if (turn_end - current_start) / sr >= 10:
            segments.append((current_start, turn_end, current_transcript))
    return segments


def process_episode(mp3_path, output_dir, episode_id, diarize_pipeline, whisper_model, manifest_file):
    wav_path = Path(f"/tmp/voci_{episode_id}.wav")

    # 1. Resample
    if not resample_to_wav(mp3_path, wav_path):
        log.warning(f"  FFmpeg failed")
        return False

    # 1b. Strip background music with Demucs (vocals only)
    log.info(f"  Stripping music (Demucs)...")
    try:
        strip_music(wav_path)
        log.info(f"  Music stripped")
    except Exception as e:
        log.warning(f"  Demucs failed: {e} — continuing with original")

    # Also trim first/last 30s (jingles that survive Demucs)
    try:
        audio_data, sr_check = sf.read(str(wav_path))
        total_dur = len(audio_data) / sr_check
        if total_dur > 120:
            trim_s = int(30 * sr_check)
            audio_data = audio_data[trim_s:-trim_s]
            sf.write(str(wav_path), audio_data, sr_check)
    except Exception:
        pass

    # 2. Diarize
    log.info(f"  Diarizing...")
    try:
        diar_segments = diarize(wav_path, diarize_pipeline)
    except Exception as e:
        log.warning(f"  Diarization failed: {e}")
        wav_path.unlink(missing_ok=True)
        return False

    # Speaker balance check
    speaker_dur = {}
    for s in diar_segments:
        speaker_dur[s["speaker"]] = speaker_dur.get(s["speaker"], 0) + (s["end"] - s["start"])

    if len(speaker_dur) < 2:
        log.info(f"  Skipping — {len(speaker_dur)} speaker(s)")
        wav_path.unlink(missing_ok=True)
        return False

    total_speech = sum(speaker_dur.values())
    top_speakers = sorted(speaker_dur, key=speaker_dur.get, reverse=True)
    dominant = speaker_dur[top_speakers[0]] / total_speech if total_speech > 0 else 1.0

    if dominant > 0.92:
        log.info(f"  Skipping — dominant {dominant:.0%} (monologue)")
        wav_path.unlink(missing_ok=True)
        return False

    speaker_a, speaker_b = top_speakers[0], top_speakers[1]
    log.info(f"  Balance: {speaker_dur[speaker_a]/total_speech:.0%}/{speaker_dur[speaker_b]/total_speech:.0%}")

    diar_segments = [s for s in diar_segments if s["speaker"] in (speaker_a, speaker_b)]

    # 3. Transcribe
    log.info(f"  Transcribing {len(diar_segments)} segments...")
    mono_audio, sr = sf.read(str(wav_path))
    transcript = []
    for seg in diar_segments:
        start_s = int(seg["start"] * sr)
        end_s = int(seg["end"] * sr)
        chunk = mono_audio[start_s:end_s]
        if len(chunk) < sr * 0.3:
            continue
        text, words = transcribe_segment(whisper_model, chunk, sr, seg["start"])
        if text:
            transcript.append({"start": seg["start"], "end": seg["end"], "speaker": seg["speaker"], "text": text, "words": words})
            # Live transcription output
            spk = "A" if seg["speaker"] == diar_segments[0]["speaker"] else "B"
            log.info(f"    [{spk}] {seg['start']:6.1f}s: {text[:80]}")

    if not transcript:
        wav_path.unlink(missing_ok=True)
        return False

    # 4. Stereo + segment
    stereo = make_stereo(mono_audio, sr, transcript, speaker_a, speaker_b)
    chunks = segment_audio(stereo, sr, transcript, MIN_SEGMENT, MAX_SEGMENT)

    # 5. Write (filter: both speakers must appear)
    written = 0
    for idx, (start, end, seg_t) in enumerate(chunks):
        seg_id = f"{episode_id}_{idx:04d}"
        seg_audio = stereo[start:end]
        seg_dur = len(seg_audio) / sr
        seg_start = start / sr

        adj = [{"start": round(t["start"] - seg_start, 3), "end": round(t["end"] - seg_start, 3),
                "speaker": "agent" if t["speaker"] == speaker_a else "user", "text": t["text"]} for t in seg_t]

        if len(set(t["speaker"] for t in adj)) < 2:
            continue
        if len(" ".join(t["text"] for t in adj)) < 20:
            continue

        written += 1
        audio_path = output_dir / f"{seg_id}.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(audio_path), seg_audio, sr, subtype="PCM_16")

        json_path = output_dir / f"{seg_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"audio_file": str(audio_path), "duration": round(seg_dur, 2),
                        "source_episode": episode_id, "transcript": adj}, f, ensure_ascii=False, indent=2)

        manifest_file.write(json.dumps({"audio": str(audio_path), "duration": round(seg_dur, 2)}) + "\n")
        manifest_file.flush()

    log.info(f"  Kept {written}/{len(chunks)} segments")
    wav_path.unlink(missing_ok=True)
    return written > 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("./data/prod"))
    parser.add_argument("--output-dir", type=Path, default=Path("./data/moshi/combined"))
    parser.add_argument("--episode-list", type=Path, nargs="+", help="One or more slice files")
    parser.add_argument("--hf-token", type=str, default=None)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Enable TF32 for Blackwell GPU performance
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    log.info("TF32 enabled for GPU acceleration")

    # Load models ONCE
    log.info("Loading Whisper turbo...")
    import whisper
    whisper_model = whisper.load_model("turbo", device="cuda")
    log.info("Whisper loaded")

    log.info("Loading pyannote...")
    from pyannote.audio import Pipeline
    diarize_kwargs = {"token": args.hf_token} if args.hf_token else {}
    diarize_pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", **diarize_kwargs).to(torch.device("cuda"))
    log.info("pyannote loaded")

    # Re-enable TF32 AFTER pyannote (it disables it)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    log.info("TF32 re-enabled after pyannote load")

    # Collect episode IDs from all slice files
    episode_filter = set()
    if args.episode_list:
        for f in args.episode_list:
            if f.exists():
                episode_filter.update(f.read_text().strip().split("\n"))
        log.info(f"Processing {len(episode_filter)} episodes from {len(args.episode_list)} slice files")

    # Open DB and manifest
    db = sqlite3.connect(str(args.data_dir / "index.db"))
    db.row_factory = sqlite3.Row
    manifest_file = open(args.output_dir / "manifest.jsonl", "a", encoding="utf-8")

    processed_file = args.output_dir / "processed.txt"
    processed = set()
    if processed_file.exists():
        processed = set(processed_file.read_text().strip().split("\n"))

    rows = db.execute("SELECT episode_id, file_path FROM episodes WHERE download_state = 'completed' AND file_path IS NOT NULL ORDER BY downloaded_at").fetchall()

    total = 0
    success = 0
    for row in rows:
        eid = row["episode_id"]
        if eid in processed:
            continue
        if episode_filter and eid not in episode_filter:
            continue

        fp = Path(row["file_path"])
        if not fp.is_absolute():
            fp = args.data_dir / fp
        if not fp.exists():
            continue

        total += 1
        # Get show name for logging
        show = db.execute("SELECT s.name FROM episodes e JOIN shows s ON e.show_id=s.show_id WHERE e.episode_id=?", (eid,)).fetchone()
        show_name = show["name"][:40] if show else "?"
        log.info(f"[{total}] {show_name} — {eid}")

        ok = process_episode(fp, args.output_dir / "train", eid, diarize_pipeline, whisper_model, manifest_file)
        if ok:
            success += 1
        with open(processed_file, "a") as f:
            f.write(eid + "\n")

        log.info(f"  {'OK' if ok else 'SKIP'} | {success}/{total} ({success/total*100:.0f}% yield)")

    manifest_file.close()
    db.close()
    log.info(f"Done. {success}/{total} episodes → output in {args.output_dir}")


if __name__ == "__main__":
    main()
