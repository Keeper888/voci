"""Reprocess existing WAV files through Demucs to strip music.
Runs as a separate process, yields GPU between files so the main pipeline isn't blocked."""
import glob
import logging
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

TARGET_SR = 24000


def strip_music_from_wav(wav_path: Path, model, device="cuda"):
    """Run Demucs on a stereo WAV, keep only vocals, overwrite in place."""
    import torchaudio
    from demucs.apply import apply_model

    audio, sr = sf.read(str(wav_path))
    # audio is (samples, 2) for stereo

    # Mix to mono for Demucs, then make stereo (Demucs expects stereo input)
    if len(audio.shape) == 2:
        mono = audio.mean(axis=1)
    else:
        mono = audio
    waveform = torch.tensor(mono, dtype=torch.float32)
    waveform = waveform.unsqueeze(0).repeat(2, 1)  # fake stereo for Demucs

    if sr != model.samplerate:
        waveform = torchaudio.transforms.Resample(sr, model.samplerate)(waveform)

    # Process in 60s chunks
    chunk_size = 60 * model.samplerate
    total_samples = waveform.shape[1]
    vocals_chunks = []

    for start in range(0, total_samples, chunk_size):
        end = min(start + chunk_size, total_samples)
        chunk = waveform[:, start:end]
        with torch.no_grad():
            sources = apply_model(model, chunk.unsqueeze(0).to(device))
        vocals = sources[0, 3].mean(dim=0).cpu()
        vocals_chunks.append(vocals)
        del sources

    vocals_full = torch.cat(vocals_chunks).numpy()

    if model.samplerate != sr:
        import torchaudio
        vocals_full = torchaudio.transforms.Resample(model.samplerate, sr)(
            torch.tensor(vocals_full).unsqueeze(0)
        ).squeeze(0).numpy()

    # Reconstruct stereo using original channel energy ratios
    if len(audio.shape) == 2:
        left_energy = np.sqrt(np.mean(audio[:, 0] ** 2)) + 1e-10
        right_energy = np.sqrt(np.mean(audio[:, 1] ** 2)) + 1e-10
        total_energy = left_energy + right_energy
        left_ratio = left_energy / total_energy
        right_ratio = right_energy / total_energy

        # Trim to match lengths
        min_len = min(len(vocals_full), len(audio))
        stereo_out = np.zeros((min_len, 2), dtype=np.float32)

        # Apply original channel mask: where original had audio, put vocals
        for ch, ratio in [(0, left_ratio), (1, right_ratio)]:
            orig_ch = np.abs(audio[:min_len, ch])
            orig_mono = np.abs(mono[:min_len]) + 1e-10
            mask = orig_ch / orig_mono
            mask = np.clip(mask, 0, 1)
            stereo_out[:, ch] = vocals_full[:min_len] * mask

        sf.write(str(wav_path), stereo_out, sr, subtype="PCM_16")
    else:
        sf.write(str(wav_path), vocals_full, sr, subtype="PCM_16")


def main():
    input_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/moshi/spark2/train")

    wav_files = sorted(glob.glob(str(input_dir / "*.wav")))
    log.info(f"Reprocessing {len(wav_files)} WAV files through Demucs")

    from demucs.pretrained import get_model
    model = get_model("htdemucs").to("cuda")
    model.eval()

    done = 0
    for i, wav_path in enumerate(wav_files):
        wav_path = Path(wav_path)
        log.info(f"[{i+1}/{len(wav_files)}] {wav_path.name}")
        try:
            strip_music_from_wav(wav_path, model)
            done += 1
        except Exception as e:
            log.warning(f"  Failed: {e}")

        # Free GPU memory between files so pipeline can use it
        torch.cuda.empty_cache()

    del model
    torch.cuda.empty_cache()
    log.info(f"Done. {done}/{len(wav_files)} reprocessed.")


if __name__ == "__main__":
    main()
