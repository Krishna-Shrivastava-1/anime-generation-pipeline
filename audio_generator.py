
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

#     # 2. Presence EQ: boost 3.2kHz - 5.5kHz for crisp vocal definition
#     sos_presence = butter(2, [3200, 5500], btype="bandpass", fs=sample_rate, output="sos")
#     presence = sosfilt(sos_presence, samples)
#     samples = samples + 0.28 * presence

#     # 3. Soft clipping tanh curve
#     samples = np.tanh(samples * 1.35)

#     # 4. Normalize to -1 dB peak
#     peak = np.max(np.abs(samples)) + 1e-9
#     samples = (samples / peak) * 0.92

#     return samples.astype(np.float32)


# def add_narrative_pauses(text: str) -> str:
#     """
#     Inserts micro-pauses at Hindi punctuation so the TTS breathes naturally.
#     """
#     # Remove troublesome curly or stray quotes that confuse phonemizers
#     text = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "").replace("'", "").replace('"', "")
#     text = text.replace("...", " ... ")
#     text = re.sub(r"([।!?])", r"\1 ", text)
#     text = re.sub(r"\s+", " ", text).strip()
#     return text


# def split_sentences(text: str):
#     parts = re.split(r"(?<=[।.!?])\s+", text.strip())
#     # Only keep chunks that contain actual words/letters (not just punctuation)
#     valid_parts = []
#     for p in parts:
#         cleaned = p.strip()
#         # Check if chunk contains at least one word character (letters/digits in Hindi or English)
#         if re.search(r"[\w\u0900-\u097F]", cleaned):
#             valid_parts.append(cleaned)
#     return valid_parts


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

#     STORY_SPEED = 1.08
#     VOICE_ID = "hf_beta"

#     for scene in story.get("scenes", []):
#         for beat in scene.get("beats", []):
#             beat_id = beat["beat_id"]
#             raw_text = beat["narration_text"].strip()
#             out_file = AUDIO_DIR / f"{beat_id}.wav"

#             formatted_text = add_narrative_pauses(raw_text)
#             sentences = split_sentences(formatted_text)

#             # Fallback if sentence splitting stripped everything
#             if not sentences:
#                 sentences = [formatted_text] if formatted_text else []

#             chunks = []
#             sr = 24000
#             for s in sentences:
#                 # Double check to prevent Kokoro empty phoneme error
#                 if not re.search(r"[\w\u0900-\u097F]", s):
#                     continue
#                 try:
#                     smpls, sr = kokoro.create(text=s, voice=VOICE_ID, speed=STORY_SPEED, lang="hi")
#                     chunks.append(smpls)
#                 except Exception as e:
#                     print(f"[Warning] Skipped unpronounceable fragment '{s}': {e}")

#             if not chunks:
#                 print(f"[Warning] No audio generated for beat: {beat_id}")
#                 continue

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
import random
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt
from kokoro_onnx import Kokoro
from pathlib import Path

MODEL_PATH = "models/kokoro-v1.0.onnx"
VOICES_PATH = "models/voices-v1.0.bin"

AUDIO_DIR = Path("build/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# =====================================================================
# 1. CLEAN STUDIO MASTERING (Zero Comb-Filtering, Zero Echo)
# =====================================================================

def biquad_peak_sos(fs, f0, gain_db, q=1.0):
    """Clean biquad peak filter coefficients."""
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2 * q)

    b0 = 1 + alpha * a
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * a
    a0 = 1 + alpha / a
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / a

    b = np.array([b0, b1, b2]) / a0
    a_coeffs = np.array([a0, a1, a2]) / a0
    return np.array([[b[0], b[1], b[2], 1.0, a_coeffs[1], a_coeffs[2]]])


def studio_vocal_master(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Clean broadcast chain using zero-phase filtering (`sosfiltfilt`):
      - 80Hz rumble cut
      - 300Hz gentle cut (clears boxy mud)
      - 3.5kHz clarity boost (crisp voice projection)
      - Dynamic transparent leveling
    """
    samples = samples.astype(np.float32)

    # 1. 80Hz High-pass filter (cuts sub-bass rumble)
    sos_hp = butter(2, 80, btype="highpass", fs=sample_rate, output="sos")
    samples = sosfiltfilt(sos_hp, samples)

    # 2. De-box: cut 300Hz by 1.5dB to eliminate dull nasal resonance
    sos_box = biquad_peak_sos(sample_rate, f0=300, gain_db=-1.5, q=1.0)
    samples = sosfiltfilt(sos_box, samples)

    # 3. Presence EQ: clean +2.5dB boost at 3500Hz for crisp articulation
    sos_presence = biquad_peak_sos(sample_rate, f0=3500, gain_db=2.5, q=1.2)
    samples = sosfiltfilt(sos_presence, samples)

    # 4. Soft-Knee Leveling (Prevents harsh digital peaks without tanh distortion)
    threshold = 0.60
    ratio = 2.5
    abs_samples = np.abs(samples)
    mask = abs_samples > threshold
    samples[mask] = np.sign(samples[mask]) * (threshold + (abs_samples[mask] - threshold) / ratio)

    # 5. Peak Normalization to -0.5 dB
    peak = np.max(np.abs(samples)) + 1e-9
    samples = (samples / peak) * 0.94

    return samples.astype(np.float32)


# =====================================================================
# 2. NATURAL SENTENCE PROSODY & TEXT FORMATTING
# =====================================================================

def clean_and_split_sentences(raw_text: str):
    """
    Keep commas inside the sentence so Kokoro speaks naturally with its own pauses.
    Only split at terminal punctuation (।, ., ?, !).
    """
    # Clean quotes and unnecessary punctuation
    clean = re.sub(r'["“”‘’\']', '', raw_text)
    clean = clean.replace("...", "…")
    clean = re.sub(r'\s+', ' ', clean).strip()

    # Split on sentence boundaries: Hindi purnavirama (।), period, question, or exclamation
    parts = re.split(r'(?<=[।?!.])\s+', clean)
    sentences = []

    for p in parts:
        p_clean = p.strip()
        # Must contain at least one valid Hindi or alphanumeric character
        if re.search(r"[\w\u0900-\u097F]", p_clean):
            sentences.append(p_clean)

    return sentences


def get_sentence_cadence(sentence: str, base_speed: float):
    """
    Dynamically adjusts Kokoro's native reading speed and pause length:
    - Questions and exclamations naturally run slightly faster
    - Base speed has slight micro-variation to sound human
    """
    # Slight micro-jitter (+/- 0.02) so sentences don't sound robotic
    speed = base_speed + random.uniform(-0.02, 0.03)
    pause_ms = 140

    if sentence.endswith("?"):
        speed += 0.03
        pause_ms = 180
    elif sentence.endswith("!"):
        speed += 0.04
        pause_ms = 160
    elif sentence.endswith("…"):
        pause_ms = 220
    else:
        pause_ms = 140

    return round(speed, 2), pause_ms


def apply_micro_fade(audio: np.ndarray, fade_samples: int = 48) -> np.ndarray:
    """Soft 2ms cosine fade at borders to prevent clicks between sentences."""
    if len(audio) <= fade_samples * 2:
        return audio
    fade_in = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fade_samples)))
    fade_out = 0.5 * (1 + np.cos(np.linspace(0, np.pi, fade_samples)))
    audio[:fade_samples] *= fade_in
    audio[-fade_samples:] *= fade_out
    return audio


# =====================================================================
# 3. MAIN RUNTIME
# =====================================================================

def main():
    if not os.path.exists(MODEL_PATH) or not os.path.exists(VOICES_PATH):
        print(f"[Error] Missing models! Check {MODEL_PATH} and {VOICES_PATH}")
        return

    with open("story_pipeline.json", "r", encoding="utf-8") as f:
        story = json.load(f)

    print("🎙️ Initializing Crystal-Clear Kokoro Engine...")
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    manifest = []
    total_dur = 0.0

    # 1.14x speed provides punchy, fast, human-paced storytelling
    BASE_SPEED = 1.14
    VOICE_ID = "hf_beta"

    for scene in story.get("scenes", []):
        for beat in scene.get("beats", []):
            beat_id = beat["beat_id"]
            raw_text = beat["narration_text"].strip()
            out_file = AUDIO_DIR / f"{beat_id}.wav"

            sentences = clean_and_split_sentences(raw_text)
            if not sentences:
                sentences = [raw_text]

            assembled_chunks = []
            sr = 24000

            for s in sentences:
                speed, pause_ms = get_sentence_cadence(s, BASE_SPEED)
                try:
                    # Let Kokoro handle native pitch, intonation, and Hindi accents
                    audio, sr = kokoro.create(text=s, voice=VOICE_ID, speed=speed, lang="hi")
                    audio = apply_micro_fade(audio)

                    pause = np.zeros(int(sr * (pause_ms / 1000.0)), dtype=np.float32)

                    assembled_chunks.append(audio)
                    assembled_chunks.append(pause)
                except Exception as e:
                    print(f"[Warning] Failed to pronounce '{s}': {e}")

            if not assembled_chunks:
                continue

            # Remove trailing pause from the last sentence
            assembled_chunks.pop()

            full_wave = np.concatenate(assembled_chunks)
            mastered = studio_vocal_master(full_wave, sr)

            sf.write(str(out_file), mastered, sr)
            dur = len(mastered) / sr
            print(f"[Synthesized] {beat_id} -> {dur:.2f}s | '{raw_text[:35]}...'")

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

    print(f"\n✅ Generation Complete! Crisp Vocal Track Duration: {total_dur:.2f}s")


if __name__ == "__main__":
    main()