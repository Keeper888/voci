"""
Mimi Codec Test for Italian Audio

Tests whether NVIDIA's Mimi audio codec (used by PersonaPlex/Moshi)
preserves Italian speech quality after encode/decode roundtrip.

Usage:
    python scripts/mimi_test.py --input test.mp3 --output test_roundtrip.wav
    python scripts/mimi_test.py --download-test  # downloads a sample Italian clip
"""
import argparse
import subprocess
import sys
from pathlib import Path

import torch
import torchaudio


def download_test_clip(output_path: Path):
    """Download a short Italian speech sample for testing."""
    # Use a Spreaker episode as test audio
    import requests
    url = "https://api.spreaker.com/v2/episodes/68578235/download.mp3"
    print(f"Downloading test clip from Spreaker...")
    resp = requests.get(url, allow_redirects=True, timeout=60,
                        headers={"User-Agent": "VociCollector/1.0"})
    resp.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(resp.content)
    print(f"Saved to {output_path} ({len(resp.content) / 1024 / 1024:.1f} MB)")


def load_audio(path: Path, target_sr: int = 24000) -> torch.Tensor:
    """Load audio file and resample to target sample rate."""
    waveform, sr = torchaudio.load(str(path))
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(sr, target_sr)
        waveform = resampler(waveform)
    # Mono
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    return waveform


def run_mimi_test(input_path: Path, output_path: Path):
    """Encode audio through Mimi codec and decode back, then compare."""
    print(f"Loading audio: {input_path}")
    waveform = load_audio(input_path)
    duration = waveform.shape[1] / 24000
    print(f"Duration: {duration:.1f}s, Shape: {waveform.shape}")

    # Load Mimi codec
    print("Loading Mimi codec from HuggingFace...")
    try:
        from huggingface_hub import hf_hub_download
        mimi_path = hf_hub_download("kyutai/moshiko-pytorch-bf16", "tokenizer-e351c8d8-checkpoint125.safetensors")
        print(f"Mimi weights: {mimi_path}")
    except Exception as e:
        print(f"Failed to download Mimi weights: {e}")
        print("Trying alternative: loading from moshi package...")

    try:
        from moshi.models import loaders
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Device: {device}")

        # Load the Mimi codec
        mimi = loaders.get_mimi(mimi_path, device=device)
        mimi.eval()

        # Encode
        print("Encoding Italian audio through Mimi...")
        with torch.no_grad():
            waveform_gpu = waveform.unsqueeze(0).to(device)  # [1, 1, samples]
            codes = mimi.encode(waveform_gpu)
            print(f"Encoded to {codes.shape} tokens")

            # Decode
            print("Decoding back to audio...")
            reconstructed = mimi.decode(codes)
            print(f"Reconstructed shape: {reconstructed.shape}")

        # Save reconstructed audio
        reconstructed_cpu = reconstructed.squeeze(0).cpu()
        torchaudio.save(str(output_path), reconstructed_cpu, 24000)
        print(f"Saved roundtrip audio to: {output_path}")

        # Compare quality metrics
        original = waveform[:, :reconstructed_cpu.shape[1]]
        reconstructed_compare = reconstructed_cpu[:, :original.shape[1]]

        # SNR
        noise = original - reconstructed_compare
        signal_power = (original ** 2).mean()
        noise_power = (noise ** 2).mean()
        snr = 10 * torch.log10(signal_power / (noise_power + 1e-10))
        print(f"\n=== QUALITY METRICS ===")
        print(f"SNR: {snr.item():.1f} dB")
        print(f"  > 20 dB = excellent (no audible difference)")
        print(f"  > 15 dB = good (minor artifacts)")
        print(f"  > 10 dB = acceptable (some quality loss)")
        print(f"  < 10 dB = PROBLEM (Italian phonemes likely distorted)")

        # Correlation
        corr = torch.corrcoef(torch.stack([original.flatten(), reconstructed_compare.flatten()]))[0, 1]
        print(f"Correlation: {corr.item():.4f}")
        print(f"  > 0.95 = excellent")
        print(f"  > 0.90 = good")
        print(f"  < 0.90 = PROBLEM")

        print(f"\n=== VERDICT ===")
        if snr > 15 and corr > 0.90:
            print("PASS — Mimi handles Italian audio well. Proceed with training.")
        elif snr > 10 and corr > 0.85:
            print("MARGINAL — Some quality loss. Listen to the output to judge.")
        else:
            print("FAIL — Mimi significantly distorts Italian. Consider alternatives.")

        print(f"\nListen to both files to compare:")
        print(f"  Original:      {input_path}")
        print(f"  Mimi roundtrip: {output_path}")

    except Exception as e:
        print(f"Error during Mimi test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Test Mimi codec on Italian audio")
    parser.add_argument("--input", type=Path, help="Input audio file")
    parser.add_argument("--output", type=Path, default=Path("mimi_roundtrip.wav"), help="Output file")
    parser.add_argument("--download-test", action="store_true", help="Download a test Italian clip")
    args = parser.parse_args()

    if args.download_test:
        test_input = Path("/tmp/italian_test.mp3")
        download_test_clip(test_input)
        args.input = test_input

    if not args.input:
        print("Usage: python mimi_test.py --input file.mp3")
        print("   or: python mimi_test.py --download-test")
        sys.exit(1)

    run_mimi_test(args.input, args.output)


if __name__ == "__main__":
    main()
