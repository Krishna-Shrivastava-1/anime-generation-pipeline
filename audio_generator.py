import os
import re
import json
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, butter, sosfilt
from kokoro_onnx import Kokoro
from fractions import Fraction
from pathlib import Path

# Paths to your local model files
MODEL_PATH = "models/kokoro-v1.0.onnx"
VOICES_PATH = "models/voices-v1.0.bin"

AUDIO_DIR = Path("build/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def change_pitch(samples: np.ndarray, sample_rate: int, pitch_factor: float) -> np.ndarray:
    if pitch_factor == 1.0 or len(samples) == 0:
        return samples
    target_len = len(samples)
    frac = Fraction(pitch_factor).limit_denominator(1000)
    stretched = resample_poly(samples, frac.numerator, frac.denominator)
    if len(stretched) != target_len:
        from scipy.signal import resample
        pitched = resample(stretched, target_len)
    else:
        pitched = stretched
    return pitched.astype(np.float32)


def polish_voice(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    samples = samples.astype(np.float32)
    sos_low = butter(2, 9000, btype="low", fs=sample_rate, output="sos")
    samples = 0.7 * samples + 0.3 * sosfilt(sos_low, samples)
    sos_band = butter(2, [150, 400], btype="band", fs=sample_rate, output="sos")
    samples = samples + 0.15 * sosfilt(sos_band, samples)
    peak = np.max(np.abs(samples)) + 1e-9
    if peak > 0.97:
        samples = samples / peak * 0.97
    return samples.astype(np.float32)


def split_sentences(text: str):
    parts = re.split(r"(?<=[।.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def crossfade_concat(chunks, sample_rate, fade_ms=25):
    if not chunks:
        return np.array([], dtype=np.float32)
    fade_len = int(sample_rate * fade_ms / 1000)
    result = chunks[0].astype(np.float32)
    for nxt in chunks[1:]:
        nxt = nxt.astype(np.float32)
        if fade_len > 0 and len(result) >= fade_len and len(nxt) >= fade_len:
            fade_out = np.linspace(1.0, 0.0, fade_len)
            fade_in = np.linspace(0.0, 1.0, fade_len)
            overlap = result[-fade_len:] * fade_out + nxt[:fade_len] * fade_in
            result = np.concatenate([result[:-fade_len], overlap, nxt[fade_len:]])
        else:
            result = np.concatenate([result, nxt])
    return result


def main():
    if not os.path.exists(MODEL_PATH) or not os.path.exists(VOICES_PATH):
        print(f"[Error] Missing models! Place them in {MODEL_PATH} and {VOICES_PATH}")
        return

    with open("story_pipeline.json", "r", encoding="utf-8") as f:
        story = json.load(f)

    print("Initializing Kokoro TTS...")
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    manifest = []
    total_dur = 0.0

    for scene in story.get("scenes", []):
        for beat in scene.get("beats", []):
            beat_id = beat["beat_id"]
            text = beat["narration_text"].strip()
            out_file = AUDIO_DIR / f"{beat_id}.wav"

            if out_file.exists():
                data, sr = sf.read(str(out_file))
                dur = len(data) / sr
                print(f"[Skipping] {beat_id} already exists ({dur:.2f}s)")
            else:
                sentences = split_sentences(text)
                chunks = []
                sr = 24000
                for s in sentences:
                    smpls, sr = kokoro.create(text=s, voice="hf_beta", speed=1.0, lang="hi")
                    chunks.append(smpls)
                audio = crossfade_concat(chunks, sr)
                audio = change_pitch(audio, sr, 0.92)
                audio = polish_voice(audio, sr)
                sf.write(str(out_file), audio, sr)
                dur = len(audio) / sr
                print(f"[Generated] {beat_id} -> {dur:.2f}s")

            manifest.append({
                "beat_id": beat_id,
                "audio_file": str(out_file).replace("\\", "/"),
                "duration_seconds": round(dur, 3),
                "subtitle": beat.get("subtitle_text", text)
            })
            total_dur += dur

    manifest_path = Path("build/audio_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"total_duration": round(total_dur, 3), "beats": manifest}, f, indent=2, ensure_ascii=False)

    print(f"\n✅ All audio generated locally! Total duration: {total_dur:.2f}s")
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    main()