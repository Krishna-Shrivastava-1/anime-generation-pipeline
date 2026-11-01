# import os
# import re
# import json
# import numpy as np
# import soundfile as sf
# from scipy.signal import butter, sosfilt
# from kokoro_onnx import Kokoro
# from pathlib import Path

# MODEL_PATH = "models/kokoro-v1.0.onnx"
# VOICES_PATH = "models/voices-v1.0.bin"

# AUDIO_DIR = Path("build/audio")
# AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# def broadcast_voice_master(samples: np.ndarray, sample_rate: int) -> np.ndarray:
#     """
#     Studio Vocal Chain:
#       1. High-Pass Filter (Rumble cut below 80Hz)
#       2. Presence / Clarity Boost (3.5kHz band) so it cuts through crisply
#       3. Soft Compression / Normalization for radio punch
#     """
#     samples = samples.astype(np.float32)

#     # 1. High-pass filter at 80Hz to remove muddy mic rumble
#     sos_hp = butter(2, 80, btype="highpass", fs=sample_rate, output="sos")
#     samples = sosfilt(sos_hp, samples)

#     # 2. Presence EQ: boost 3.2kHz - 5.5kHz for crisp, engaging vocal definition
#     sos_presence = butter(2, [3200, 5500], btype="bandpass", fs=sample_rate, output="sos")
#     presence = sosfilt(sos_presence, samples)
#     samples = samples + 0.28 * presence

#     # 3. Fast soft-knee limiter / compressor (levels out quiet & loud syllables)
#     # Apply soft clipping tanh curve
#     samples = np.tanh(samples * 1.35)

#     # 4. Normalize to -1 dB peak (0.89)
#     peak = np.max(np.abs(samples)) + 1e-9
#     samples = (samples / peak) * 0.92

#     return samples.astype(np.float32)


# def add_narrative_pauses(text: str) -> str:
#     """
#     Inserts micro-pauses at Hindi punctuation so the TTS breathes naturally.
#     """
#     # Normalize danda and ellipsis to give dramatic suspense
#     text = text.replace("...", " ... ")
#     text = re.sub(r"([।!?])", r"\1 ", text)
#     text = re.sub(r"\s+", " ", text).strip()
#     return text


# def split_sentences(text: str):
#     parts = re.split(r"(?<=[।.!?])\s+", text.strip())
#     return [p for p in parts if p.strip()]


# def crossfade_concat(chunks, sample_rate, pause_ms=120):
#     """
#     Concatenate chunks with an intentional natural spoken pause.
#     """
#     if not chunks:
#         return np.array([], dtype=np.float32)

#     pause_samples = np.zeros(int(sample_rate * (pause_ms / 1000.0)), dtype=np.float32)
#     result = chunks[0].astype(np.float32)

#     for nxt in chunks[1:]:
#         result = np.concatenate([result, pause_samples, nxt.astype(np.float32)])
#     return result


# def main():
#     if not os.path.exists(MODEL_PATH) or not os.path.exists(VOICES_PATH):
#         print(f"[Error] Missing models! Check {MODEL_PATH} and {VOICES_PATH}")
#         return

#     with open("story_pipeline.json", "r", encoding="utf-8") as f:
#         story = json.load(f)

#     print("🎙️ Initializing High-Definition Kokoro Engine...")
#     kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
#     manifest = []
#     total_dur = 0.0

#     # 1.08x speed feels far more energetic and human in Hindi
#     STORY_SPEED = 1.08
#     VOICE_ID = "hf_beta"

#     for scene in story.get("scenes", []):
#         for beat in scene.get("beats", []):
#             beat_id = beat["beat_id"]
#             raw_text = beat["narration_text"].strip()
#             out_file = AUDIO_DIR / f"{beat_id}.wav"

#             formatted_text = add_narrative_pauses(raw_text)
#             sentences = split_sentences(formatted_text)
            
#             chunks = []
#             sr = 24000
#             for s in sentences:
#                 smpls, sr = kokoro.create(text=s, voice=VOICE_ID, speed=STORY_SPEED, lang="hi")
#                 chunks.append(smpls)

#             combined = crossfade_concat(chunks, sr, pause_ms=100)
#             mastered = broadcast_voice_master(combined, sr)

#             sf.write(str(out_file), mastered, sr)
#             dur = len(mastered) / sr
#             print(f"[Synthesized] {beat_id} -> {dur:.2f}s | '{raw_text[:30]}...'")

#             manifest.append({
#                 "beat_id": beat_id,
#                 "audio_file": str(out_file).replace("\\", "/"),
#                 "duration_seconds": round(dur, 3),
#                 "subtitle": beat.get("subtitle_text", raw_text)
#             })
#             total_dur += dur

#     manifest_path = Path("build/audio_manifest.json")
#     with open(manifest_path, "w", encoding="utf-8") as f:
#         json.dump({"total_duration": round(total_dur, 3), "beats": manifest}, f, indent=2, ensure_ascii=False)

#     print(f"\n✅ Mastering Complete! New Audio Duration: {total_dur:.2f}s")


# if __name__ == "__main__":
#     main()







import os
import re
import json
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt
from kokoro_onnx import Kokoro
from pathlib import Path

MODEL_PATH = "models/kokoro-v1.0.onnx"
VOICES_PATH = "models/voices-v1.0.bin"

AUDIO_DIR = Path("build/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def broadcast_voice_master(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Studio Vocal Chain:
      1. High-Pass Filter (Rumble cut below 80Hz)
      2. Presence / Clarity Boost (3.5kHz band) so it cuts through crisply
      3. Soft Compression / Normalization for radio punch
    """
    samples = samples.astype(np.float32)

    # 1. High-pass filter at 80Hz to remove muddy mic rumble
    sos_hp = butter(2, 80, btype="highpass", fs=sample_rate, output="sos")
    samples = sosfilt(sos_hp, samples)

    # 2. Presence EQ: boost 3.2kHz - 5.5kHz for crisp vocal definition
    sos_presence = butter(2, [3200, 5500], btype="bandpass", fs=sample_rate, output="sos")
    presence = sosfilt(sos_presence, samples)
    samples = samples + 0.28 * presence

    # 3. Soft clipping tanh curve
    samples = np.tanh(samples * 1.35)

    # 4. Normalize to -1 dB peak
    peak = np.max(np.abs(samples)) + 1e-9
    samples = (samples / peak) * 0.92

    return samples.astype(np.float32)


def add_narrative_pauses(text: str) -> str:
    """
    Inserts micro-pauses at Hindi punctuation so the TTS breathes naturally.
    """
    # Remove troublesome curly or stray quotes that confuse phonemizers
    text = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "").replace("'", "").replace('"', "")
    text = text.replace("...", " ... ")
    text = re.sub(r"([।!?])", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str):
    parts = re.split(r"(?<=[।.!?])\s+", text.strip())
    # Only keep chunks that contain actual words/letters (not just punctuation)
    valid_parts = []
    for p in parts:
        cleaned = p.strip()
        # Check if chunk contains at least one word character (letters/digits in Hindi or English)
        if re.search(r"[\w\u0900-\u097F]", cleaned):
            valid_parts.append(cleaned)
    return valid_parts


def crossfade_concat(chunks, sample_rate, pause_ms=120):
    """
    Concatenate chunks with an intentional natural spoken pause.
    """
    if not chunks:
        return np.array([], dtype=np.float32)

    pause_samples = np.zeros(int(sample_rate * (pause_ms / 1000.0)), dtype=np.float32)
    result = chunks[0].astype(np.float32)

    for nxt in chunks[1:]:
        result = np.concatenate([result, pause_samples, nxt.astype(np.float32)])
    return result


def main():
    if not os.path.exists(MODEL_PATH) or not os.path.exists(VOICES_PATH):
        print(f"[Error] Missing models! Check {MODEL_PATH} and {VOICES_PATH}")
        return

    with open("story_pipeline.json", "r", encoding="utf-8") as f:
        story = json.load(f)

    print("🎙️ Initializing High-Definition Kokoro Engine...")
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    manifest = []
    total_dur = 0.0

    STORY_SPEED = 1.08
    VOICE_ID = "hf_beta"

    for scene in story.get("scenes", []):
        for beat in scene.get("beats", []):
            beat_id = beat["beat_id"]
            raw_text = beat["narration_text"].strip()
            out_file = AUDIO_DIR / f"{beat_id}.wav"

            formatted_text = add_narrative_pauses(raw_text)
            sentences = split_sentences(formatted_text)

            # Fallback if sentence splitting stripped everything
            if not sentences:
                sentences = [formatted_text] if formatted_text else []

            chunks = []
            sr = 24000
            for s in sentences:
                # Double check to prevent Kokoro empty phoneme error
                if not re.search(r"[\w\u0900-\u097F]", s):
                    continue
                try:
                    smpls, sr = kokoro.create(text=s, voice=VOICE_ID, speed=STORY_SPEED, lang="hi")
                    chunks.append(smpls)
                except Exception as e:
                    print(f"[Warning] Skipped unpronounceable fragment '{s}': {e}")

            if not chunks:
                print(f"[Warning] No audio generated for beat: {beat_id}")
                continue

            combined = crossfade_concat(chunks, sr, pause_ms=100)
            mastered = broadcast_voice_master(combined, sr)

            sf.write(str(out_file), mastered, sr)
            dur = len(mastered) / sr
            print(f"[Synthesized] {beat_id} -> {dur:.2f}s | '{raw_text[:30]}...'")

            manifest.append({
                "beat_id": beat_id,
                "audio_file": str(out_file).replace("\\", "/"),
                "duration_seconds": round(dur, 3),
                "subtitle": beat.get("subtitle_text", raw_text)
            })
            total_dur += dur

    manifest_path = Path("build/audio_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"total_duration": round(total_dur, 3), "beats": manifest}, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Mastering Complete! New Audio Duration: {total_dur:.2f}s")


if __name__ == "__main__":
    main()