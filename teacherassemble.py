
# # Run interactively (prompts for Language, Accent, Gender, and Voice):
# #   python teacherassemble.py teachingscript.json
# #   python teacherassemble.py teachingscript.json -a 9:16 -b bgm.mp3 -o final_video.mp4
# #
# # Or pass flags directly + -y to skip prompts:
# #   python teacherassemble.py teachingscript.json --lang en --accent us --gender male -y

# import argparse
# import hashlib
# import json
# import math
# import random
# import re
# import shutil
# import subprocess
# import sys
# import urllib.parse
# import urllib.request
# import wave
# from pathlib import Path

# import numpy as np
# from kokoro_onnx import Kokoro

# try:
#     import soundfile as sf
# except ImportError:
#     sf = None

# try:
#     from PIL import Image, ImageDraw, ImageFont
# except ImportError:
#     Image = ImageDraw = ImageFont = None

# try:
#     from deep_translator import GoogleTranslator
# except ImportError:
#     GoogleTranslator = None


# # ============================================================
# # CONFIGURATION
# # ============================================================

# DEFAULT_LANG = "en"       # "en" or "hi" (auto-detected from script if omitted)
# DEFAULT_GENDER = "female" # "female" or "male"
# DEFAULT_ACCENT = "us"     # "us", "hindi", or "uk"
# TTS_SPEED = 1.02          # Natural conversational pace
# VOICE_VOLUME = 0.96

# # Grouping & natural phrasing controls
# MAX_GROUP_CHARS = 360     # Keep within Kokoro's optimal prosody window
# MAX_BEATS_PER_GROUP = 4   # Speak up to 4 connected beats in one continuous pass
# INTER_GROUP_PAUSE_MS = 140
# BRIDGE_EXTRA_PAUSE_MS = 220

# FPS = 30
# VIDEO_ZOOM = 1.08         # Subtle zoom + smooth alternating pan across each image
# BGM_VOLUME = 0.12         # Used only if --bgm is passed

# IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

# BASE_DIR = Path(__file__).resolve().parent
# MODELS_DIR = BASE_DIR / "models"
# CACHE_DIR = BASE_DIR / "tts_cache"
# DEFAULT_FRAMES_DIR = BASE_DIR / "build" / "frames"
# TRANSLATION_CACHE_FILE = BASE_DIR / "translation_cache.json"

# _KOKORO_INSTANCE = None
# _TRANSLATION_CACHE = None
# _PHONEMIZER_PATCHED = False

# VOICE_PRESETS = {
#     "us": {
#         "female": ["af_heart", "af_bella", "af_sarah", "af_nicole"],
#         "male": ["am_michael", "am_adam", "am_fenrir", "am_onyx"],
#     },
#     "hindi": {
#         "female": ["hf_alpha", "hf_beta"],
#         "male": ["hm_omega", "hm_psi"],
#     },
#     "uk": {
#         "female": ["bf_emma", "bf_isabella", "bf_alice"],
#         "male": ["bm_george", "bm_lewis", "bm_daniel"],
#     },
# }

# ACRONYM_MAP = {
#     "AI": "A I",
#     "ML": "M L",
#     "LLM": "L L M",
#     "LLMs": "L L Ms",
#     "NLP": "N L P",
#     "PDF": "P D F",
#     "PDFs": "P D Fs",
#     "GPU": "G P U",
#     "GPUs": "G P Us",
#     "API": "A P I",
#     "APIs": "A P Is",
#     "URL": "U R L",
#     "URLs": "U R Ls",
#     "URI": "U R I",
#     "SQL": "S Q L",
#     "NoSQL": "No S Q L",
#     "DTO": "D T O",
#     "DTOs": "D T Os",
#     "ORM": "O R M",
#     "JWT": "J W T",
#     "HTML": "H T M L",
#     "CSS": "C S S",
#     "DOM": "D O M",
#     "CLI": "C L I",
#     "IDE": "I D E",
#     "SDK": "S D K",
#     "JDK": "J D K",
#     "JVM": "J V M",
#     "HTTP": "H T T P",
#     "HTTPS": "H T T P S",
#     "UI": "U I",
#     "UX": "U X",
#     "DB": "D B",
#     "ID": "I D",
#     "IDs": "I Ds",
#     "CPU": "C P U",
#     "RAM": "R A M",
#     "MVC": "M V C",
#     "DI": "D I",
#     "IoC": "I o C",
#     "OOP": "O O P",
#     "NPM": "N P M",
#     "npm": "N P M",
#     "JPA": "J P A",
#     "DAO": "D A O",
#     "POJO": "po jo",
# }


# # ============================================================
# # HELPERS
# # ============================================================

# def run_cmd(command):
#     result = subprocess.run(
#         command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
#     )
#     if result.returncode != 0:
#         raise RuntimeError(
#             "\nFFmpeg command failed:\n"
#             + " ".join(map(str, command))
#             + "\n\n"
#             + result.stderr[-4000:]
#         )
#     return result


# def get_duration(path):
#     result = run_cmd([
#         "ffprobe", "-v", "error",
#         "-show_entries", "format=duration",
#         "-of", "default=noprint_wrappers=1:nokey=1",
#         str(path)
#     ])
#     return float(result.stdout.strip())


# def check_dependencies():
#     for tool in ("ffmpeg", "ffprobe"):
#         if shutil.which(tool) is None:
#             raise RuntimeError(f"{tool} was not found in PATH.")
#     find_kokoro_models()


# def sanitize_filename(name):
#     cleaned = re.sub(r'[<>:"/\\|?*]+', "", name.strip())
#     return re.sub(r"\s+", "_", cleaned).strip("_") or "story"


# def has_devanagari(text):
#     return any("\u0900" <= ch <= "\u097f" for ch in text)


# def load_story_json(json_path):
#     raw_text = json_path.read_text(encoding="utf-8-sig")
#     try:
#         return json.loads(raw_text, strict=False)
#     except json.JSONDecodeError:
#         cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw_text)
#         return json.loads(cleaned, strict=False)


# def extract_beats(story_data):
#     """Supports flat `beats[]` (movie-recap/explainer schema) and `scenes[].beats[]`."""
#     if story_data.get("beats"):
#         return story_data["beats"]
#     beats = []
#     for sc in story_data.get("scenes", []):
#         for bt in sc.get("beats", []):
#             beats.append(bt)
#     return beats


# def get_beat_raw_narration(beat):
#     clips = beat.get("clips") or []
#     return (
#         beat.get("narration", "").strip()
#         or beat.get("narration_text", "").strip()
#         or " ".join(c.get("spoken_text", "").strip() for c in clips if c.get("spoken_text", "").strip())
#     )


# def detect_script_language(beats):
#     sample_text = " ".join(get_beat_raw_narration(bt) for bt in beats[:5])
#     return "hi" if has_devanagari(sample_text) else "en"


# def get_render_profile(aspect_ratio):
#     if aspect_ratio == "9:16":
#         return {
#             "width": 1080,
#             "height": 1920,
#             "sub_font_size": 34,
#             "sub_max_chars_cue": 52,
#             "sub_max_chars_line": 28,
#             "sub_bottom_margin": 140,
#         }
#     return {
#         "width": 1920,
#         "height": 1080,
#         "sub_font_size": 32,
#         "sub_max_chars_cue": 74,
#         "sub_max_chars_line": 48,
#         "sub_bottom_margin": 54,
#     }


# def detect_aspect_ratio_from_image(img_path):
#     if Image is None or not img_path or not Path(img_path).exists():
#         return "9:16"
#     with Image.open(img_path) as im:
#         w, h = im.size
#     return "9:16" if h > w else "16:9"


# def resolve_clip_image(clip, beat_id, clip_id, frames_dir):
#     """
#     Finds the generated image in `frames_dir`:
#       1. Explicit `image` / `image_path` / `frame` key on clip
#       2. {frames_dir}/{beat_id}_{clip_id}.{ext}
#       3. {frames_dir}/{clip_id}.{ext}
#       4. {frames_dir}/{beat_id}.{ext}
#     """
#     for key in ("image", "image_path", "frame"):
#         val = clip.get(key)
#         if val:
#             p = Path(val)
#             if not p.is_absolute():
#                 p = BASE_DIR / p
#             if p.exists():
#                 return p

#     for stem in (f"{beat_id}_{clip_id}", clip_id, beat_id):
#         for ext in IMAGE_EXTENSIONS:
#             candidate = frames_dir / f"{stem}{ext}"
#             if candidate.exists():
#                 return candidate

#     raise FileNotFoundError(
#         f"Image not found for beat={beat_id}, clip={clip_id} in {frames_dir}. "
#         f"Tried {beat_id}_{clip_id}.png, {clip_id}.png, and {beat_id}.png"
#     )


# # ============================================================
# # TRANSLATION (ONLY WHEN SCRIPT CONTAINS HINDI)
# # ============================================================

# def _get_translation_cache():
#     global _TRANSLATION_CACHE
#     if _TRANSLATION_CACHE is None:
#         if TRANSLATION_CACHE_FILE.exists():
#             try:
#                 _TRANSLATION_CACHE = json.loads(
#                     TRANSLATION_CACHE_FILE.read_text(encoding="utf-8")
#                 )
#             except Exception:
#                 _TRANSLATION_CACHE = {}
#         else:
#             _TRANSLATION_CACHE = {}
#     return _TRANSLATION_CACHE


# def ensure_english_text(text):
#     """Returns text directly if already English; translates only if Devanagari Hindi is present."""
#     text = " ".join(text.strip().split())
#     if not text or not has_devanagari(text):
#         return text

#     cache = _get_translation_cache()
#     if text in cache:
#         return cache[text]

#     translated = None
#     if GoogleTranslator is not None:
#         try:
#             translated = GoogleTranslator(source="hi", target="en").translate(text)
#         except Exception:
#             translated = None

#     if not translated:
#         try:
#             url = (
#                 "https://translate.googleapis.com/translate_a/single"
#                 "?client=gtx&sl=hi&tl=en&dt=t&q=" + urllib.parse.quote(text)
#             )
#             req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
#             with urllib.request.urlopen(req, timeout=15) as resp:
#                 data = json.loads(resp.read().decode("utf-8"))
#                 translated = "".join(part[0] for part in data[0] if part and part[0])
#         except Exception as exc:
#             print(f"      [Warning] Translation failed ({exc}); using original text.")
#             translated = text

#     translated = " ".join(translated.strip().split())
#     cache[text] = translated
#     TRANSLATION_CACHE_FILE.write_text(
#         json.dumps(cache, ensure_ascii=False, indent=2),
#         encoding="utf-8"
#     )
#     return translated


# # ============================================================
# # TEXT NORMALIZATION FOR NATURAL TTS
# # ============================================================

# def normalize_text_for_tts(text, lang="en"):
#     """
#     Cleans Hindi/English + code/tech tokens so Kokoro doesn't insert fake breaks
#     on 'Node.js', stumble on '@RestController', or mumble CamelCase & acronyms.
#     """
#     orig = " ".join(text.strip().split())
#     if not orig:
#         return orig

#     s = orig
#     # Normalize curly quotes & typographic punctuation
#     s = s.replace("\u2019", "'").replace("\u2018", "'")
#     s = s.replace("\u201c", "").replace("\u201d", "").replace('"', "")
#     s = s.replace("`", "").replace("*", "").replace("()", "")

#     # '&' -> spoken word
#     s = re.sub(r"\s*&\s*", " aur " if lang == "hi" else " and ", s)

#     # Arrows / dashes / parens -> brief natural comma pauses
#     s = s.replace("->", ", ").replace("=>", ", ")
#     s = re.sub(r"[—–]+", ", ", s)
#     s = re.sub(r"\s+-\s+", ", ", s)
#     s = re.sub(r"\(([^)]+)\)", r", \1, ", s)

#     # Annotations like @RestController -> at RestController
#     s = re.sub(r"@([A-Za-z_]\w*)", r"at \1", s)

#     # Underscore identifiers like user_id -> user id
#     s = re.sub(r"([A-Za-z0-9])_([A-Za-z0-9])", r"\1 \2", s)

#     # File/framework extensions: Node.js -> Node JS, package.json -> package JSON
#     s = re.sub(
#         r"\b([A-Za-z][A-Za-z0-9-]*)\.(js|ts|jsx|tsx|json|html|css|xml|yml|yaml|sql|py|java|md)\b",
#         lambda m: f"{m.group(1)} {m.group(2).upper()}",
#         s,
#         flags=re.IGNORECASE,
#     )

#     # Code dot notation: app.get / req.params.id -> app dot get / req dot params dot id
#     while re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", s):
#         s = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", r"\1 dot \2", s)

#     # Slashes between words: GET/POST -> GET, POST
#     s = re.sub(r"([A-Za-z0-9]+)/([A-Za-z0-9]+)", r"\1, \2", s)

#     # Split CamelCase / PascalCase so Kokoro pronounces words fluidly
#     s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
#     s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)

#     # Expand uppercase technical acronyms cleanly
#     s = re.sub(r"\b[A-Za-z]{2,6}\b", lambda m: ACRONYM_MAP.get(m.group(0), m.group(0)), s)

#     # Replace Devanagari Danda with ASCII period for cleaner espeak sentence pauses
#     if lang == "hi":
#         s = s.replace("॥", ".").replace("।", ".")

#     # Clean repeated commas/spaces
#     s = re.sub(r"\s*,\s*(,\s*)+", ", ", s)
#     s = re.sub(r"\s+([,।.!?])", r"\1", s)
#     s = " ".join(s.split()).strip(" ,")

#     if not s:
#         return orig

#     if s[-1] not in "।.!?":
#         s += "."

#     return s


# def estimate_spoken_weight(text):
#     """Estimates relative speaking duration for Hindi/English + punctuation."""
#     w = 0.0
#     for ch in text:
#         if ch.isspace():
#             continue
#         if "\u0904" <= ch <= "\u0939" or "\u0958" <= ch <= "\u0961":
#             w += 1.25
#         elif "\u0900" <= ch <= "\u097f":
#             w += 0.35
#         elif ch.isalnum():
#             w += 0.90
#         elif ch in ",;:":
#             w += 3.2
#         elif ch in "।.!?":
#             w += 6.0
#     return max(w, 1.0)


# # ============================================================
# # KOKORO ONNX TTS + PHONEMIZER FIX + FLUENT SYNTHESIS
# # ============================================================

# def _strip_lang_flags(phonemes):
#     """
#     Removes espeak-ng language-switch markers like (hi), (en), (en-us).
#     Without this, kokoro-onnx drops '(' and ')' and literally speaks 'hi' as 'hee'.
#     """
#     if isinstance(phonemes, str):
#         cleaned = re.sub(r"\([A-Za-z0-9_-]{1,14}\)", " ", phonemes)
#         return re.sub(r"\s+", " ", cleaned).strip()
#     if isinstance(phonemes, list):
#         return [_strip_lang_flags(p) for p in phonemes]
#     return phonemes


# def patch_kokoro_phonemizer(kokoro):
#     """
#     Patches phonemizer / EspeakBackend / tokenizer.phonemize so (hi) and (en)
#     language switch markers never leak into Kokoro's phoneme tokens as 'hee'.
#     """
#     global _PHONEMIZER_PATCHED
#     if _PHONEMIZER_PATCHED:
#         return
#     _PHONEMIZER_PATCHED = True

#     try:
#         import phonemizer
#         if hasattr(phonemizer, "phonemize"):
#             orig_ph = phonemizer.phonemize

#             def patched_phonemize(*args, **kwargs):
#                 kwargs.setdefault("language_switch", "remove-flags")
#                 return _strip_lang_flags(orig_ph(*args, **kwargs))

#             phonemizer.phonemize = patched_phonemize

#         from phonemizer.backend import EspeakBackend
#         if hasattr(EspeakBackend, "phonemize"):
#             orig_backend_ph = EspeakBackend.phonemize

#             def patched_backend_ph(self, *args, **kwargs):
#                 return _strip_lang_flags(orig_backend_ph(self, *args, **kwargs))

#             EspeakBackend.phonemize = patched_backend_ph
#     except Exception:
#         pass

#     tok = getattr(kokoro, "tokenizer", None)
#     if tok is not None:
#         if hasattr(tok, "phonemize"):
#             orig_tok_ph = tok.phonemize

#             def patched_tok_ph(*args, **kwargs):
#                 return _strip_lang_flags(orig_tok_ph(*args, **kwargs))

#             tok.phonemize = patched_tok_ph

#         inner_backend = getattr(tok, "phonemizer", None)
#         if inner_backend is not None and hasattr(inner_backend, "phonemize"):
#             orig_inner = inner_backend.phonemize

#             def patched_inner(*args, **kwargs):
#                 return _strip_lang_flags(orig_inner(*args, **kwargs))

#             inner_backend.phonemize = patched_inner


# def find_kokoro_models():
#     if not MODELS_DIR.exists():
#         raise FileNotFoundError(f"Models folder not found: {MODELS_DIR}")

#     model_path = next(
#         (p for p in [MODELS_DIR / "kokoro-v1.0.onnx", MODELS_DIR / "kokoro-v0_19.onnx"] if p.exists()),
#         None
#     ) or next(iter(sorted(MODELS_DIR.glob("*.onnx"))), None)
#     if model_path is None:
#         raise FileNotFoundError(f"No .onnx model file found in {MODELS_DIR}")

#     voices_path = next(
#         (p for p in [MODELS_DIR / "voices-v1.0.bin", MODELS_DIR / "voices.bin", MODELS_DIR / "voices.json"] if p.exists()),
#         None
#     ) or next(
#         iter(sorted(list(MODELS_DIR.glob("*.bin")) + list(MODELS_DIR.glob("*voices*.json")))),
#         None
#     )
#     if voices_path is None:
#         raise FileNotFoundError(f"No voices file found in {MODELS_DIR}")

#     return model_path, voices_path


# def get_kokoro():
#     global _KOKORO_INSTANCE
#     if _KOKORO_INSTANCE is None:
#         model_path, voices_path = find_kokoro_models()
#         print(f"Loading Kokoro: {model_path.name} | Voices: {voices_path.name}")
#         _KOKORO_INSTANCE = Kokoro(str(model_path), str(voices_path))
#         patch_kokoro_phonemizer(_KOKORO_INSTANCE)
#     return _KOKORO_INSTANCE


# def get_available_voices(kokoro):
#     if hasattr(kokoro, "get_voices"):
#         try:
#             return set(kokoro.get_voices())
#         except Exception:
#             pass
#     voices_obj = getattr(kokoro, "voices", None)
#     if isinstance(voices_obj, dict):
#         return set(voices_obj.keys())
#     if hasattr(voices_obj, "files"):
#         return set(voices_obj.files)
#     return set()


# def get_voices_for_profile(accent, gender):
#     kokoro = get_kokoro()
#     available = get_available_voices(kokoro)
#     candidates = list(VOICE_PRESETS[accent][gender])

#     if not available:
#         return candidates

#     filtered = [v for v in candidates if v in available]
#     prefix = f"{'h' if accent == 'hindi' else ('b' if accent == 'uk' else 'a')}{'f' if gender == 'female' else 'm'}_"
#     extra = sorted(v for v in available if v.startswith(prefix) and v not in filtered)
#     combined = filtered + extra
#     if combined:
#         return combined

#     any_gender = sorted(v for v in available if len(v) > 2 and v[1] == ("f" if gender == "female" else "m"))
#     return any_gender or sorted(available)


# def resolve_voice_and_tts_lang(narration_lang, gender, accent, explicit_voice=None):
#     kokoro = get_kokoro()
#     available = get_available_voices(kokoro)

#     if narration_lang == "hi":
#         tts_lang = "hi"
#     else:
#         tts_lang = "en-gb" if accent == "uk" else "en-us"

#     if explicit_voice:
#         if available and explicit_voice not in available:
#             raise ValueError(
#                 f"Voice '{explicit_voice}' not found in loaded voices file. "
#                 f"Available sample: {sorted(available)[:20]}"
#             )
#         return explicit_voice, tts_lang

#     candidates = get_voices_for_profile(accent, gender)
#     return candidates[0], tts_lang


# def save_wav(path, samples, sample_rate):
#     samples = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
#     if sf is not None:
#         sf.write(str(path), samples, int(sample_rate), subtype="PCM_16")
#         return
#     pcm16 = (samples * 32767.0).astype(np.int16)
#     with wave.open(str(path), "wb") as wf:
#         wf.setnchannels(1)
#         wf.setsampwidth(2)
#         wf.setframerate(int(sample_rate))
#         wf.writeframes(pcm16.tobytes())


# def load_wav(path):
#     if sf is not None:
#         samples, sr = sf.read(str(path), dtype="float32")
#         if samples.ndim > 1:
#             samples = np.mean(samples, axis=1)
#         return samples.astype(np.float32), int(sr)
#     with wave.open(str(path), "rb") as wf:
#         sr = wf.getframerate()
#         nch = wf.getnchannels()
#         frames = wf.readframes(wf.getnframes())
#     pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
#     if nch > 1:
#         pcm = pcm.reshape(-1, nch).mean(axis=1)
#     return pcm, int(sr)


# def apply_cosine_fades(samples, sr, fade_in_ms=8, fade_out_ms=12):
#     samples = np.asarray(samples, dtype=np.float32).copy()
#     n = samples.size
#     if n == 0:
#         return samples
#     fi = min(int(sr * fade_in_ms / 1000), n // 3)
#     fo = min(int(sr * fade_out_ms / 1000), n // 3)
#     if fi > 1:
#         ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, fi, dtype=np.float32)))
#         samples[:fi] *= ramp
#     if fo > 1:
#         ramp = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, fo, dtype=np.float32)))
#         samples[-fo:] *= ramp
#     return samples


# def gentle_trim_silence(samples, sr, threshold=0.0012, pad_start_ms=45, pad_end_ms=75):
#     samples = np.asarray(samples, dtype=np.float32)
#     active = np.where(np.abs(samples) > threshold)[0]
#     if active.size == 0:
#         return samples
#     start_idx = max(0, int(active[0]) - int(sr * pad_start_ms / 1000))
#     end_idx = min(samples.size, int(active[-1]) + int(sr * pad_end_ms / 1000))
#     return samples[start_idx:end_idx]


# def normalize_voice_dynamics(samples, target_rms=0.115):
#     samples = np.asarray(samples, dtype=np.float32)
#     if samples.size == 0:
#         return samples
#     active = samples[np.abs(samples) > 0.004]
#     if active.size < 64:
#         return samples
#     rms = float(np.sqrt(np.mean(active * active)))
#     if rms <= 1e-5:
#         return samples
#     gain = np.clip(target_rms / rms, 0.65, 1.85)
#     scaled = samples * gain
#     peak = float(np.max(np.abs(scaled)))
#     if peak > 0.92:
#         scaled = np.tanh(scaled * 0.95) / np.tanh(0.95) * 0.92
#     return scaled.astype(np.float32)


# def split_long_sentences(text, max_chars=340):
#     if len(text) <= max_chars:
#         return [text]
#     parts = re.split(r"(?<!\d)(?<=[।!?\.])\s+", text)
#     chunks, curr = [], ""
#     for part in parts:
#         part = part.strip()
#         if not part:
#             continue
#         if curr and len(curr) + 1 + len(part) > max_chars:
#             chunks.append(curr)
#             curr = part
#         else:
#             curr = f"{curr} {part}".strip() if curr else part
#     if curr:
#         chunks.append(curr)
#     return chunks or [text]


# def synthesize_text_raw(text, voice, tts_lang, speed=TTS_SPEED):
#     kokoro = get_kokoro()
#     parts = split_long_sentences(text, max_chars=340)
#     chunks, sample_rate = [], None

#     for idx, part in enumerate(parts):
#         samples, sr = kokoro.create(part, voice=voice, speed=speed, lang=tts_lang)
#         sample_rate = int(sr)
#         samples = gentle_trim_silence(
#             samples, sample_rate,
#             pad_start_ms=45 if idx == 0 else 55,
#             pad_end_ms=75 if idx == len(parts) - 1 else 65,
#         )
#         samples = normalize_voice_dynamics(samples)
#         samples = apply_cosine_fades(samples, sample_rate, fade_in_ms=8, fade_out_ms=12)
#         if samples.size > 0:
#             chunks.append(samples)

#     if not chunks or sample_rate is None:
#         raise RuntimeError(f"Kokoro returned empty audio for: {text}")

#     if len(chunks) == 1:
#         return chunks[0], sample_rate

#     breath_gap = np.zeros(int(sample_rate * 0.16), dtype=np.float32)
#     joined = []
#     for i, ch in enumerate(chunks):
#         if i > 0:
#             joined.append(breath_gap)
#         joined.append(ch)
#     return np.concatenate(joined), sample_rate


# def find_quiet_pauses(samples, sr, min_pause_s=0.055):
#     """Detects quiet pause midpoints inside a waveform."""
#     n = samples.size
#     win = max(1, int(0.020 * sr))
#     hop = max(1, int(0.005 * sr))
#     if n < win * 4:
#         return [], 0, n

#     sq = samples.astype(np.float64) ** 2
#     csum = np.concatenate(([0.0], np.cumsum(sq)))
#     starts = np.arange(0, n - win + 1, hop)
#     rms = np.sqrt(np.maximum(0.0, (csum[starts + win] - csum[starts]) / win))

#     active_rms = rms[rms > 0.003]
#     if active_rms.size == 0:
#         return [], 0, n
#     med_rms = float(np.median(active_rms))
#     quiet_thresh = min(0.015, max(0.0025, 0.065 * med_rms))

#     active_frames = np.where(rms > quiet_thresh)[0]
#     if active_frames.size == 0:
#         return [], 0, n
#     speech_start = int(starts[active_frames[0]])
#     speech_end = int(starts[active_frames[-1]] + win)

#     is_quiet = rms < quiet_thresh
#     padded = np.concatenate(([False], is_quiet, [False]))
#     q_starts = np.where(~padded[:-1] & padded[1:])[0]
#     q_ends = np.where(padded[:-1] & ~padded[1:])[0]

#     candidates = []
#     for qs, qe in zip(q_starts, q_ends):
#         s_samp = int(starts[qs])
#         e_samp = int(starts[min(qe, len(starts) - 1)] + win)
#         if e_samp <= speech_start + int(0.20 * sr) or s_samp >= speech_end - int(0.20 * sr):
#             continue
#         dur_s = (e_samp - s_samp) / sr
#         if dur_s >= min_pause_s:
#             candidates.append(((s_samp + e_samp) // 2, dur_s))

#     return candidates, speech_start, speech_end


# def find_natural_split_points(samples, sr, norm_texts):
#     k = len(norm_texts)
#     if k <= 1:
#         return []

#     candidates, speech_start, speech_end = find_quiet_pauses(samples, sr, min_pause_s=0.065)
#     speech_span = max(1, speech_end - speech_start)
#     if len(candidates) < k - 1:
#         return None

#     weights = [estimate_spoken_weight(t) for t in norm_texts]
#     total_w = sum(weights)
#     cum_w = 0.0
#     exp_samples = []
#     for w in weights[:-1]:
#         cum_w += w
#         exp_samples.append(speech_start + int(speech_span * (cum_w / total_w)))

#     max_dev = max(int(1.4 * sr), int(0.28 * speech_span))
#     min_seg_samples = int(0.35 * sr)

#     best_cost = float("inf")
#     best_splits = None

#     def backtrack(b_idx, c_start_idx, prev_split, chosen):
#         nonlocal best_cost, best_splits
#         if b_idx == k - 1:
#             if speech_end - prev_split < min_seg_samples:
#                 return
#             cost = 0.0
#             for j, (mid_s, dur_s) in enumerate(chosen):
#                 cost += abs(mid_s - exp_samples[j]) / sr - 0.75 * min(dur_s, 0.55)
#             if cost < best_cost:
#                 best_cost = cost
#                 best_splits = [m for m, _ in chosen]
#             return

#         exp_s = exp_samples[b_idx]
#         for ci in range(c_start_idx, len(candidates)):
#             mid_s, dur_s = candidates[ci]
#             if mid_s - prev_split < min_seg_samples:
#                 continue
#             if abs(mid_s - exp_s) > max_dev:
#                 if mid_s > exp_s + max_dev:
#                     break
#                 continue
#             chosen.append((mid_s, dur_s))
#             backtrack(b_idx + 1, ci + 1, mid_s, chosen)
#             chosen.pop()

#     backtrack(0, 0, speech_start, [])
#     return best_splits


# def group_beats_for_tts(beats, narration_lang="en"):
#     groups = []
#     current_group = []
#     current_chars = 0

#     for idx, beat in enumerate(beats):
#         raw_narration = get_beat_raw_narration(beat)
#         if not raw_narration:
#             beat_id = beat.get("beat_id", f"B{idx + 1:04d}")
#             raise ValueError(f"{beat_id}: missing narration.")

#         # Subtitle / English text uses script narration directly if already English
#         subtitle_text = ensure_english_text(raw_narration)

#         # Spoken narration comes directly from the script (only translates Hindi->English if Hindi script + EN audio)
#         if narration_lang == "en":
#             spoken_source = subtitle_text
#         else:
#             spoken_source = raw_narration

#         norm_text = normalize_text_for_tts(spoken_source, lang=narration_lang)
#         added_len = len(norm_text) + (1 if current_group else 0)

#         if current_group and (
#             len(current_group) >= MAX_BEATS_PER_GROUP
#             or current_chars + added_len > MAX_GROUP_CHARS
#         ):
#             groups.append(current_group)
#             current_group = []
#             current_chars = 0

#         current_group.append({
#             "beat_index": idx + 1,
#             "beat": beat,
#             "raw_narration": raw_narration,
#             "subtitle_text": subtitle_text,
#             "norm_text": norm_text,
#             "is_bridge": bool(beat.get("is_scene_bridge", False)),
#         })
#         current_chars += len(norm_text) + (1 if len(current_group) > 1 else 0)

#         if beat.get("is_scene_bridge", False):
#             groups.append(current_group)
#             current_group = []
#             current_chars = 0

#     if current_group:
#         groups.append(current_group)

#     return groups


# def synthesize_group_and_cache(group, voice, tts_lang, speed=TTS_SPEED, use_cache=True):
#     CACHE_DIR.mkdir(parents=True, exist_ok=True)
#     sig_payload = json.dumps(
#         {
#             "v": "v6_fluent",
#             "voice": voice,
#             "lang": tts_lang,
#             "speed": speed,
#             "texts": [item["norm_text"] for item in group],
#         },
#         ensure_ascii=False,
#     )
#     group_key = hashlib.md5(sig_payload.encode("utf-8")).hexdigest()
#     cached_paths = [CACHE_DIR / f"{group_key}_{i:02d}.wav" for i in range(len(group))]

#     all_cached = use_cache and all(p.exists() and p.stat().st_size > 0 for p in cached_paths)
#     if not all_cached:
#         norm_texts = [item["norm_text"] for item in group]
#         beat_samples_list = None
#         sr = None

#         if len(group) > 1:
#             joined = " ".join(norm_texts)
#             print(f"      Generating fluent TTS group ({len(group)} beats): {joined[:78]}...")
#             full_samples, sr = synthesize_text_raw(joined, voice=voice, tts_lang=tts_lang, speed=speed)
#             split_pts = find_natural_split_points(full_samples, sr, norm_texts)

#             if split_pts is not None:
#                 bounds = [0] + split_pts + [full_samples.size]
#                 beat_samples_list = []
#                 for i in range(len(group)):
#                     seg = full_samples[bounds[i]:bounds[i + 1]]
#                     fi = 4 if i > 0 else 8
#                     fo = 4 if i < len(group) - 1 else 12
#                     seg = apply_cosine_fades(seg, sr, fade_in_ms=fi, fade_out_ms=fo)
#                     beat_samples_list.append(seg)
#             else:
#                 print("      [Note] Pause alignment uncertain for group; falling back to per-beat with natural pauses.")

#         if beat_samples_list is None:
#             beat_samples_list = []
#             for item in group:
#                 print(f"      Generating TTS: {item['norm_text'][:78]}...")
#                 seg, sr = synthesize_text_raw(item["norm_text"], voice=voice, tts_lang=tts_lang, speed=speed)
#                 beat_samples_list.append(seg)

#         for path, seg in zip(cached_paths, beat_samples_list):
#             save_wav(path, seg, sr)

#     results = []
#     for idx, (item, path) in enumerate(zip(group, cached_paths)):
#         dur = get_duration(path)
#         if dur <= 0:
#             raise RuntimeError(f"Invalid TTS duration: {path}")

#         if idx < len(group) - 1:
#             pause_after_s = 0.0
#         else:
#             pause_after_s = (INTER_GROUP_PAUSE_MS + (BRIDGE_EXTRA_PAUSE_MS if item["is_bridge"] else 0)) / 1000.0

#         results.append((path, dur, pause_after_s))

#     return results


# def prepare_all_beats_audio(beats, temp_dir, narration_lang, voice, tts_lang, speed=TTS_SPEED, use_cache=True):
#     groups = group_beats_for_tts(beats, narration_lang=narration_lang)
#     print(f"Synthesizing fluent narration ({narration_lang.upper()} | {voice} | {tts_lang}) across {len(beats)} beats in {len(groups)} groups...")

#     beat_audio_plans = []
#     master_chunks = []
#     master_sr = None

#     for group in groups:
#         group_results = synthesize_group_and_cache(
#             group, voice=voice, tts_lang=tts_lang, speed=speed, use_cache=use_cache
#         )
#         for item, (wav_path, raw_dur, pause_after_s) in zip(group, group_results):
#             samples, sr = load_wav(wav_path)
#             if master_sr is None:
#                 master_sr = sr
#             elif sr != master_sr:
#                 old_x = np.linspace(0.0, 1.0, samples.size)
#                 new_len = int(round(samples.size * master_sr / sr))
#                 new_x = np.linspace(0.0, 1.0, new_len)
#                 samples = np.interp(new_x, old_x, samples).astype(np.float32)

#             exact_speech_dur = samples.size / master_sr
#             total_target_dur = exact_speech_dur + pause_after_s
#             num_frames = max(3, int(round(total_target_dur * FPS)))
#             frame_aligned_dur = num_frames / FPS
#             target_samples = int(round(frame_aligned_dur * master_sr))

#             if target_samples > samples.size:
#                 padded = np.concatenate([
#                     samples,
#                     np.zeros(target_samples - samples.size, dtype=np.float32)
#                 ])
#             else:
#                 padded = apply_cosine_fades(samples[:target_samples], master_sr, fade_in_ms=0, fade_out_ms=6)

#             master_chunks.append(padded)
#             beat_audio_plans.append({
#                 "beat_index": item["beat_index"],
#                 "beat": item["beat"],
#                 "raw_narration": item["raw_narration"],
#                 "subtitle_text": item["subtitle_text"],
#                 "speech_samples": samples,
#                 "sample_rate": master_sr,
#                 "speech_dur": exact_speech_dur,
#                 "num_frames": num_frames,
#                 "frame_dur": frame_aligned_dur,
#             })

#     master_samples = np.concatenate(master_chunks)
#     master_wav_path = Path(temp_dir) / "master_narration.wav"
#     save_wav(master_wav_path, master_samples, master_sr)

#     return beat_audio_plans, master_wav_path


# # ============================================================
# # RDR2-STYLE ENGLISH SUBTITLES
# # ============================================================

# def split_english_into_cues(text, max_chars=74):
#     text = " ".join(text.strip().split())
#     if not text:
#         return []

#     cues = []
#     for sentence in re.split(r"(?<=[.!?])\s+", text):
#         current, current_len = [], 0
#         for word in sentence.split():
#             added = len(word) + (1 if current else 0)
#             if current and current_len + added > max_chars:
#                 cues.append(" ".join(current))
#                 current, current_len = [word], len(word)
#             else:
#                 current.append(word)
#                 current_len += added

#             if word.endswith(",") and current_len >= max_chars * 0.55:
#                 cues.append(" ".join(current))
#                 current, current_len = [], 0
#         if current:
#             cues.append(" ".join(current))
#     return cues


# def build_timed_subtitle_cues(english_text, total_duration, max_chars_cue=74):
#     chunks = split_english_into_cues(english_text, max_chars=max_chars_cue)
#     if not chunks:
#         return []

#     weights = [
#         max(
#             sum(1 for c in ch if not c.isspace() and c not in ".,!?;:")
#             + sum(2.5 if c in ".!?" else 1.2 for c in ch if c in ".,!?;:"),
#             1.0
#         )
#         for ch in chunks
#     ]
#     total_w = sum(weights)
#     timed, cursor = [], 0.0

#     for idx, (chunk, w) in enumerate(zip(chunks, weights)):
#         end_t = total_duration if idx == len(chunks) - 1 else min(total_duration, cursor + total_duration * (w / total_w))
#         timed.append((cursor, end_t, chunk))
#         cursor = end_t
#     return timed


# def wrap_subtitle_lines(text, max_line_chars=48):
#     lines, current, current_len = [], [], 0
#     for word in text.split():
#         added = len(word) + (1 if current else 0)
#         if current and current_len + added > max_line_chars:
#             lines.append(" ".join(current))
#             current, current_len = [word], len(word)
#         else:
#             current.append(word)
#             current_len += added
#     if current:
#         lines.append(" ".join(current))

#     if len(lines) == 2 and len(lines[1]) < len(lines[0]) * 0.35:
#         words = text.split()
#         mid = len(words) // 2
#         lines = [" ".join(words[:mid]), " ".join(words[mid:])]
#     return lines[:3]


# def find_subtitle_font(size):
#     for path in [
#         "C:/Windows/Fonts/georgia.ttf",
#         "C:/Windows/Fonts/times.ttf",
#         "C:/Windows/Fonts/segoeui.ttf",
#         "C:/Windows/Fonts/arial.ttf",
#         "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
#         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
#         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
#     ]:
#         if Path(path).exists():
#             try:
#                 return ImageFont.truetype(path, size)
#             except Exception:
#                 pass
#     return ImageFont.load_default()


# def render_rdr2_subtitle_png(text, output_path, profile, seed_value=0):
#     font_size = profile["sub_font_size"]
#     font = find_subtitle_font(font_size)
#     lines = wrap_subtitle_lines(text, max_line_chars=profile["sub_max_chars_line"])

#     probe = ImageDraw.Draw(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
#     line_sizes = [(b[2] - b[0], b[3] - b[1]) for b in (probe.textbbox((0, 0), ln, font=font) for ln in lines)]

#     text_w = max(w for w, _ in line_sizes)
#     line_h = max(h for _, h in line_sizes)
#     line_gap = max(6, int(font_size * 0.28))
#     text_h = line_h * len(lines) + line_gap * max(0, len(lines) - 1)

#     pad_x, pad_y, sketch_margin = 40, 14, 22
#     box_w, box_h = text_w + pad_x * 2, text_h + pad_y * 2
#     img_w, img_h = box_w + sketch_margin * 2, box_h + 12

#     img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
#     draw = ImageDraw.Draw(img)
#     rng = random.Random(seed_value)

#     x0, x1 = sketch_margin, sketch_margin + box_w
#     y0, y1 = 6, 6 + box_h

#     pts = []
#     for x in range(x0, x1, 18):
#         pts.append((x, y0 + rng.randint(-1, 1)))
#     pts.append((x1, y0 + rng.randint(-1, 1)))

#     for y in range(y0 + 3, y1, 3):
#         taper = math.sin(((y - y0) / max(1, y1 - y0)) * math.pi)
#         pts.append((int(x1 + rng.randint(-6, 12) * (0.45 + 0.55 * taper)), y))

#     for x in range(x1, x0, -18):
#         pts.append((x, y1 + rng.randint(-1, 1)))
#     pts.append((x0, y1 + rng.randint(-1, 1)))

#     for y in range(y1 - 3, y0, -3):
#         taper = math.sin(((y - y0) / max(1, y1 - y0)) * math.pi)
#         pts.append((int(x0 + rng.randint(-12, 6) * (0.45 + 0.55 * taper)), y))

#     draw.polygon(pts, fill=(8, 8, 8, 218))

#     for _ in range(10):
#         sy_l = rng.randint(y0 + 3, y1 - 3)
#         draw.line(
#             [(x0 + rng.randint(-18, 4), sy_l), (x0 + rng.randint(8, 26), sy_l + rng.randint(-1, 1))],
#             fill=(8, 8, 8, rng.randint(110, 195)), width=rng.randint(1, 3)
#         )
#         sy_r = rng.randint(y0 + 3, y1 - 3)
#         draw.line(
#             [(x1 - rng.randint(8, 26), sy_r), (x1 + rng.randint(-4, 18), sy_r + rng.randint(-1, 1))],
#             fill=(8, 8, 8, rng.randint(110, 195)), width=rng.randint(1, 3)
#         )

#     curr_y = y0 + pad_y - 2
#     for line, (lw, _) in zip(lines, line_sizes):
#         lx = (img_w - lw) // 2
#         draw.text((lx + 1, curr_y + 2), line, font=font, fill=(0, 0, 0, 235))
#         draw.text((lx, curr_y), line, font=font, fill=(246, 245, 240, 255))
#         curr_y += line_h + line_gap

#     max_allowed_w = profile["width"] - 32
#     if img.width > max_allowed_w:
#         scale = max_allowed_w / img.width
#         img = img.resize((max_allowed_w, max(1, int(img.height * scale))), Image.Resampling.LANCZOS)

#     img.save(str(output_path), "PNG")
#     return output_path


# def write_fallback_ass(timed_cues, ass_path, profile):
#     def fmt(sec):
#         cs = max(0, int(round(sec * 100)))
#         s, cs = divmod(cs, 100)
#         m, s = divmod(s, 60)
#         h, m = divmod(m, 60)
#         return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

#     lines = [
#         "[Script Info]\nScriptType: v4.00+\n"
#         f"PlayResX: {profile['width']}\nPlayResY: {profile['height']}\n\n"
#         "[V4+ Styles]\n"
#         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
#         "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
#         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
#         f"Style: Default,Georgia,{profile['sub_font_size']},&H00F5F5F5,&H000000FF,&H26080808,"
#         f"&H26080808,0,0,0,0,100,100,0,0,3,14,0,2,60,60,{profile['sub_bottom_margin']},1\n\n"
#         "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
#     ]
#     for st, et, txt in timed_cues:
#         wrapped = "\\N".join(wrap_subtitle_lines(txt, max_line_chars=profile["sub_max_chars_line"]))
#         lines.append(f"Dialogue: 0,{fmt(st)},{fmt(et)},Default,,0,0,0,,{wrapped}\n")
#     ass_path.write_text("".join(lines), encoding="utf-8")
#     return ass_path


# # ============================================================
# # IMAGE-TO-VIDEO PROCESSING (FRAME-EXACT)
# # ============================================================

# def render_image_clip_bg(image_path, num_frames, output_path, profile, motion_index=0):
#     width = profile["width"]
#     height = profile["height"]
#     zoom = max(1.0, float(VIDEO_ZOOM))
#     zoom_w = ((int(round(width * zoom)) + 1) // 2) * 2
#     zoom_h = ((int(round(height * zoom)) + 1) // 2) * 2
#     dur = max(1 / FPS, num_frames / FPS)

#     mode = motion_index % 4
#     if mode == 0:
#         x_expr = f"(iw-ow)*t/{dur:.6f}"
#         y_expr = "(ih-oh)/2"
#     elif mode == 1:
#         x_expr = f"(iw-ow)*(1-t/{dur:.6f})"
#         y_expr = "(ih-oh)/2"
#     elif mode == 2:
#         x_expr = "(iw-ow)/2"
#         y_expr = f"(ih-oh)*t/{dur:.6f}"
#     else:
#         x_expr = "(iw-ow)/2"
#         y_expr = f"(ih-oh)*(1-t/{dur:.6f})"

#     vf = (
#         f"scale={zoom_w}:{zoom_h}:force_original_aspect_ratio=increase:flags=bicubic,"
#         f"crop={width}:{height}:x='{x_expr}':y='{y_expr}',"
#         f"setsar=1,fps={FPS},setpts=PTS-STARTPTS"
#     )

#     command = [
#         "ffmpeg", "-y",
#         "-loop", "1",
#         "-framerate", str(FPS),
#         "-i", str(image_path),
#         "-an",
#         "-vf", vf,
#         "-frames:v", str(num_frames),
#         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
#         str(output_path)
#     ]
#     run_cmd(command)
#     return output_path


# def overlay_beat_subtitles(beat_video_path, num_frames, timed_cues, beat_dir, beat_id, output_path, profile):
#     if not timed_cues:
#         shutil.copy2(beat_video_path, output_path)
#         return output_path

#     command = ["ffmpeg", "-y", "-i", str(beat_video_path)]
#     filter_parts = [f"[0:v]fps={FPS},setpts=PTS-STARTPTS[v0]"]
#     last_v = "v0"

#     if Image is not None:
#         for idx, (st, et, txt) in enumerate(timed_cues):
#             png_path = beat_dir / f"{beat_id}_sub_{idx:03d}.png"
#             seed = int(hashlib.md5(f"{beat_id}_{idx}_{txt}".encode("utf-8")).hexdigest()[:8], 16)
#             render_rdr2_subtitle_png(txt, png_path, profile=profile, seed_value=seed)
#             command.extend(["-i", str(png_path)])
#             next_v = f"v{idx + 1}"
#             cond = (
#                 f"between(t,{st:.3f},{et:.3f})"
#                 if idx == len(timed_cues) - 1
#                 else f"gte(t,{st:.3f})*lt(t,{et:.3f})"
#             )
#             filter_parts.append(
#                 f"[{last_v}][{idx + 1}:v]overlay=(W-w)/2:H-h-{profile['sub_bottom_margin']}:"
#                 f"enable='{cond}'[{next_v}]"
#             )
#             last_v = next_v
#     else:
#         ass_path = write_fallback_ass(timed_cues, beat_dir / f"{beat_id}_sub.ass", profile=profile)
#         escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
#         filter_parts.append(f"[{last_v}]ass='{escaped}'[v_sub]")
#         last_v = "v_sub"

#     command.extend([
#         "-filter_complex", ";".join(filter_parts),
#         "-map", f"[{last_v}]",
#         "-an",
#         "-frames:v", str(num_frames),
#         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
#         str(output_path)
#     ])
#     run_cmd(command)
#     return output_path


# def concat_video_only(segment_files, output_file, temp_dir):
#     output_file = Path(output_file)
#     concat_file = Path(temp_dir) / f"{output_file.stem}.concat.txt"
#     with open(concat_file, "w", encoding="utf-8") as f:
#         for seg in segment_files:
#             safe = str(seg.resolve()).replace("\\", "/").replace("'", "'\\''")
#             f.write(f"file '{safe}'\n")

#     run_cmd([
#         "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
#         "-c:v", "copy", "-an", str(output_file)
#     ])
#     return output_file


# def mux_final_video(master_video_path, master_audio_path, output_file, bgm_path=None):
#     output_file = Path(output_file)
#     command = [
#         "ffmpeg", "-y",
#         "-i", str(master_video_path),
#         "-i", str(master_audio_path),
#     ]

#     voice_chain = (
#         "[1:a]aresample=44100,"
#         "highpass=f=75,"
#         "acompressor=threshold=-18dB:ratio=2.0:attack=15:release=180:makeup=1.4,"
#         f"volume={VOICE_VOLUME}"
#     )

#     if bgm_path is not None and Path(bgm_path).exists():
#         command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
#         filter_complex = (
#             f"{voice_chain}[v_pre];"
#             "[v_pre]asplit=2[v_mix][v_sc];"
#             f"[2:a]aresample=44100,volume={BGM_VOLUME}[bgm_raw];"
#             "[bgm_raw][v_sc]sidechaincompress=threshold=0.02:ratio=2.8:attack=90:release=480[bgm];"
#             "[v_mix][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
#             "alimiter=limit=0.95[aout]"
#         )
#     else:
#         filter_complex = f"{voice_chain},alimiter=limit=0.95[aout]"

#     command.extend([
#         "-filter_complex", filter_complex,
#         "-map", "0:v:0", "-map", "[aout]",
#         "-c:v", "copy",
#         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
#         "-shortest",
#         "-movflags", "+faststart",
#         str(output_file),
#     ])
#     run_cmd(command)
#     return output_file


# # ============================================================
# # BEAT & CLIP-SEGMENT ASSEMBLY PIPELINE
# # ============================================================

# def compute_clip_target_frames(
#     clips, speech_samples, sr, speech_dur, total_beat_frames, narration_lang="en"
# ):
#     """
#     Allocates integer frames across clips so image segments track the spoken clauses:
#       1. Weights each clip by its spoken text (directly from clip if already English,
#          or translated if clip spoken_text is Hindi and --lang en).
#       2. Snaps internal clip cut timestamps to nearby natural pause/comma valleys
#          in the beat's actual audio waveform so images change cleanly between clauses.
#     """
#     speech_frames = max(len(clips), min(total_beat_frames, int(round(speech_dur * FPS))))
#     pause_frames = max(0, total_beat_frames - speech_frames)
#     if len(clips) == 1:
#         return [total_beat_frames]

#     weights = []
#     for clip in clips:
#         if narration_lang == "en":
#             en_txt = (clip.get("spoken_text_en") or clip.get("english_text") or "").strip()
#             if not en_txt and clip.get("spoken_text", "").strip():
#                 en_txt = ensure_english_text(clip["spoken_text"].strip())
#             if en_txt:
#                 weights.append(estimate_spoken_weight(en_txt))
#                 continue

#         txt = clip.get("spoken_text", "").strip()
#         if txt:
#             weights.append(estimate_spoken_weight(txt))
#         elif clip.get("estimated_spoken_duration"):
#             weights.append(max(float(clip["estimated_spoken_duration"]), 0.5))
#         elif "start" in clip and "end" in clip:
#             weights.append(max(float(clip["end"]) - float(clip["start"]), 0.5))
#         else:
#             weights.append(1.0)

#     total_w = sum(weights)
#     expected_cuts_s = []
#     cum_w = 0.0
#     for w in weights[:-1]:
#         cum_w += w
#         expected_cuts_s.append(speech_dur * (cum_w / total_w))

#     pauses, _, _ = find_quiet_pauses(speech_samples, sr, min_pause_s=0.045)
#     pause_times = [mid / sr for mid, _ in pauses]

#     snapped_cuts_s = []
#     prev_t = 0.0
#     for idx, exp_t in enumerate(expected_cuts_s):
#         remaining = len(expected_cuts_s) - idx
#         min_t = prev_t + 0.30
#         max_t = speech_dur - remaining * 0.30
#         best_t = min(max(exp_t, min_t), max_t)

#         nearby = [pt for pt in pause_times if min_t <= pt <= max_t and abs(pt - exp_t) <= 0.45]
#         if nearby:
#             best_t = min(nearby, key=lambda pt: abs(pt - exp_t))

#         snapped_cuts_s.append(best_t)
#         prev_t = best_t

#     cut_frames = [int(round(t * FPS)) for t in snapped_cuts_s]
#     frames_list = []
#     prev_f = 0
#     for idx, cf in enumerate(cut_frames):
#         remaining = len(clips) - idx - 1
#         cf = max(prev_f + 3, min(cf, speech_frames - remaining * 3))
#         frames_list.append(cf - prev_f)
#         prev_f = cf
#     frames_list.append(max(1, speech_frames - prev_f) + pause_frames)

#     diff = total_beat_frames - sum(frames_list)
#     frames_list[-1] = max(1, frames_list[-1] + diff)
#     return frames_list


# def render_beat_video(plan, frames_dir, temp_dir, profile, motion_counter, narration_lang):
#     beat_index = plan["beat_index"]
#     beat = plan["beat"]
#     raw_narration = plan["raw_narration"]
#     subtitle_text = plan["subtitle_text"]
#     speech_dur = plan["speech_dur"]
#     total_frames = plan["num_frames"]

#     beat_id = beat.get("beat_id", f"B{beat_index:04d}")
#     clips = beat.get("clips") or [{"clip_id": f"{beat_id}_C0001", "spoken_text": raw_narration}]

#     preview_txt = subtitle_text if narration_lang == "en" else raw_narration
#     print(f"\n[{beat_id}] ({speech_dur:.2f}s speech / {total_frames / FPS:.2f}s total) {preview_txt}")
#     beat_dir = temp_dir / beat_id
#     beat_dir.mkdir(parents=True, exist_ok=True)

#     timed_cues = build_timed_subtitle_cues(
#         subtitle_text, speech_dur, max_chars_cue=profile["sub_max_chars_cue"]
#     )
#     clip_frames_list = compute_clip_target_frames(
#         clips,
#         plan["speech_samples"],
#         plan["sample_rate"],
#         speech_dur,
#         total_frames,
#         narration_lang=narration_lang,
#     )

#     print(f"      Clips: {len(clips)} | Sub: {subtitle_text[:70]}...")

#     clip_segments = []
#     for idx, (clip, n_frames) in enumerate(zip(clips, clip_frames_list), start=1):
#         clip_id = clip.get("clip_id", f"{beat_id}_C{idx:04d}")
#         img_path = resolve_clip_image(clip, beat_id, clip_id, frames_dir)
#         bg_path = beat_dir / f"{clip_id}_bg.mp4"
#         render_image_clip_bg(
#             img_path, n_frames, bg_path,
#             profile=profile,
#             motion_index=motion_counter + idx - 1
#         )
#         clip_segments.append(bg_path)

#     beat_video = beat_dir / f"{beat_id}_video.mp4"
#     concat_video_only(clip_segments, beat_video, temp_dir=beat_dir)

#     beat_output = beat_dir / f"{beat_id}_sub.mp4"
#     overlay_beat_subtitles(
#         beat_video, total_frames, timed_cues, beat_dir, beat_id, beat_output, profile=profile
#     )
#     return beat_output, motion_counter + len(clips)


# def normalize_lang_arg(val):
#     v = val.strip().lower()
#     if v in ("hi", "hindi"):
#         return "hi"
#     if v in ("en", "eng", "english"):
#         return "en"
#     raise ValueError(f"Unsupported language '{val}'. Choose 'hi' or 'en'.")


# def _ask_choice(prompt_text, mapping, default_val):
#     while True:
#         raw = input(prompt_text).strip().lower()
#         if not raw:
#             return default_val
#         if raw in mapping:
#             return mapping[raw]
#         print(f"   Invalid choice '{raw}'. Valid options: {', '.join(sorted(mapping.keys()))}")


# def resolve_interactive_options(args, detected_script_lang):
#     """
#     Prompts interactively for Language, Accent (US / Hindi / UK), Gender, and Voice
#     so every combination (e.g. English + US, English + Hindi accent, Hindi + US accent,
#     Hindi + Hindi accent) is cleanly selectable without memorizing CLI flags.
#     """
#     can_prompt = sys.stdin.isatty() and not args.yes

#     lang = normalize_lang_arg(args.lang) if args.lang is not None else None
#     accent = args.accent
#     gender = args.gender
#     voice = args.voice

#     default_lang = detected_script_lang
#     default_accent = "hindi" if default_lang == "hi" else "us"

#     if can_prompt and (lang is None or (voice is None and (accent is None or gender is None))):
#         detected_label = "Hindi" if detected_script_lang == "hi" else "English"
#         print("\n=== Audio & Voice Setup ===")
#         print(f"Detected script narration: {detected_label}")

#     if lang is None:
#         if can_prompt:
#             def_num = "1" if default_lang == "en" else "2"
#             print("\n1) Audio Language (Script reading / TTS mode):")
#             print("   [1] English")
#             print("   [2] Hindi")
#             lang = _ask_choice(
#                 f"   Choose language [1/2, default={def_num}]: ",
#                 {"1": "en", "en": "en", "eng": "en", "english": "en", "2": "hi", "hi": "hi", "hindi": "hi"},
#                 default_lang,
#             )
#         else:
#             lang = default_lang

#     if accent is None:
#         if can_prompt and voice is None:
#             def_acc = "2" if lang == "hi" else "1"
#             print("\n2) Voice Accent:")
#             print("   [1] US Accent (American)")
#             print("   [2] Hindi / Indian Accent")
#             print("   [3] UK Accent (British)")
#             accent = _ask_choice(
#                 f"   Choose accent [1/2/3, default={def_acc}]: ",
#                 {
#                     "1": "us", "us": "us", "american": "us",
#                     "2": "hindi", "hi": "hindi", "hindi": "hindi", "indian": "hindi",
#                     "3": "uk", "uk": "uk", "british": "uk",
#                 },
#                 "hindi" if lang == "hi" else "us",
#             )
#         else:
#             accent = "hindi" if lang == "hi" else default_accent

#     if gender is None:
#         if can_prompt and voice is None:
#             print("\n3) Narrator Gender:")
#             print("   [1] Female")
#             print("   [2] Male")
#             gender = _ask_choice(
#                 "   Choose gender [1/2, default=1]: ",
#                 {"1": "female", "f": "female", "female": "female", "2": "male", "m": "male", "male": "male"},
#                 DEFAULT_GENDER,
#             )
#         else:
#             gender = DEFAULT_GENDER

#     if voice is None and can_prompt:
#         voice_choices = get_voices_for_profile(accent, gender)
#         if len(voice_choices) > 1:
#             print(f"\n4) Voice ({accent.upper()} / {gender.capitalize()}):")
#             mapping = {}
#             for i, v in enumerate(voice_choices[:6], start=1):
#                 tag = " (default)" if i == 1 else ""
#                 print(f"   [{i}] {v}{tag}")
#                 mapping[str(i)] = v
#                 mapping[v.lower()] = v
#             voice = _ask_choice(
#                 f"   Choose voice [1-{min(6, len(voice_choices))}, default=1]: ",
#                 mapping,
#                 voice_choices[0],
#             )
#         elif voice_choices:
#             voice = voice_choices[0]

#     return lang, gender, accent, voice


# def run_assembly(
#     json_path,
#     frames_dir=None,
#     output_path=None,
#     aspect_ratio="auto",
#     bgm_path=None,
#     lang=None,
#     gender=None,
#     accent=None,
#     voice=None,
#     speed=TTS_SPEED,
#     yes=False,
#     no_cache=False,
# ):
#     check_dependencies()

#     json_path = Path(json_path).resolve()
#     if not json_path.exists():
#         raise FileNotFoundError(f"Story JSON not found: {json_path}")

#     frames_dir = Path(frames_dir).resolve() if frames_dir else DEFAULT_FRAMES_DIR
#     if not frames_dir.exists():
#         raise FileNotFoundError(f"Frames folder not found: {frames_dir}")

#     story_data = load_story_json(json_path)
#     beats = extract_beats(story_data)
#     if not beats:
#         raise ValueError("No beats found in story JSON.")

#     detected_script_lang = detect_script_language(beats)

#     # Load Kokoro upfront so voice selection menu reflects voices actually in voices-*.bin
#     get_kokoro()

#     # Resolve options interactively when running from terminal unless passed via CLI
#     dummy_args = argparse.Namespace(lang=lang, gender=gender, accent=accent, voice=voice, yes=yes)
#     narration_lang, chosen_gender, chosen_accent, chosen_voice = resolve_interactive_options(
#         dummy_args, detected_script_lang=detected_script_lang
#     )

#     if aspect_ratio == "auto":
#         meta_ar = story_data.get("aspect_ratio") or story_data.get("project_meta", {}).get("aspect_ratio")
#         if meta_ar in ("9:16", "16:9"):
#             aspect_ratio = meta_ar
#         else:
#             first_beat = beats[0]
#             first_bid = first_beat.get("beat_id", "B0001")
#             first_clips = first_beat.get("clips") or [{"clip_id": f"{first_bid}_C0001"}]
#             first_cid = first_clips[0].get("clip_id", f"{first_bid}_C0001")
#             first_img = resolve_clip_image(first_clips[0], first_bid, first_cid, frames_dir)
#             aspect_ratio = detect_aspect_ratio_from_image(first_img)

#     profile = get_render_profile(aspect_ratio)

#     title = (
#         story_data.get("movie_title")
#         or story_data.get("title")
#         or story_data.get("project_meta", {}).get("title")
#         or json_path.stem
#     )
#     safe_title = sanitize_filename(title)
#     final_output = Path(output_path).resolve() if output_path else BASE_DIR / f"{safe_title}_explained.mp4"
#     final_output.parent.mkdir(parents=True, exist_ok=True)

#     temp_dir = BASE_DIR / f".assembly_temp_{safe_title}"
#     if temp_dir.exists():
#         shutil.rmtree(temp_dir)
#     temp_dir.mkdir(parents=True, exist_ok=True)

#     try:
#         selected_voice, tts_lang = resolve_voice_and_tts_lang(
#             narration_lang=narration_lang,
#             gender=chosen_gender,
#             accent=chosen_accent,
#             explicit_voice=chosen_voice,
#         )

#         print(
#             f"\nTitle: {title} | Beats: {len(beats)} | Aspect: {aspect_ratio} ({profile['width']}x{profile['height']}) "
#             f"| Audio: {narration_lang.upper()} ({chosen_gender}, {chosen_accent} accent -> {selected_voice}, {tts_lang}) @ {speed}x "
#             f"| Output: {final_output.name}"
#         )
#         if Image is None:
#             print("[Note] Install Pillow (`pip install pillow`) for RDR2-style sketchy subtitles.")

#         beat_audio_plans, master_wav_path = prepare_all_beats_audio(
#             beats,
#             temp_dir=temp_dir,
#             narration_lang=narration_lang,
#             voice=selected_voice,
#             tts_lang=tts_lang,
#             speed=speed,
#             use_cache=not no_cache,
#         )

#         beat_video_outputs, motion_counter = [], 0
#         for plan in beat_audio_plans:
#             out_vid, motion_counter = render_beat_video(
#                 plan, frames_dir, temp_dir, profile, motion_counter, narration_lang=narration_lang
#             )
#             beat_video_outputs.append(out_vid)

#         print("\nAssembling master video + continuous audio...")
#         master_video_path = temp_dir / "master_video.mp4"
#         concat_video_only(beat_video_outputs, master_video_path, temp_dir=temp_dir)
#         mux_final_video(master_video_path, master_wav_path, final_output, bgm_path=bgm_path)

#         actual_total = get_duration(final_output)
#         print(f"Done: {final_output} ({actual_total:.2f}s / {actual_total / 60:.2f} min)")
#         return str(final_output)
#     finally:
#         if temp_dir.exists():
#             shutil.rmtree(temp_dir, ignore_errors=True)


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(
#         description="Assemble explainer video from generated images + beat/clip JSON with fluent Kokoro TTS and RDR2 subtitles."
#     )
#     parser.add_argument("json_path", help="Path to story JSON (with beats[] and clips[])")
#     parser.add_argument("-f", "--frames-dir", default=None, help="Directory with generated images (default: build/frames)")
#     parser.add_argument("-o", "--output", default=None, help="Optional output MP4 path")
#     parser.add_argument("-a", "--aspect-ratio", choices=["auto", "9:16", "16:9"], default="auto", help="Target aspect ratio")
#     parser.add_argument("-b", "--bgm", default=None, help="Optional background music audio file (looped softly)")
#     parser.add_argument("-l", "--lang", choices=["hi", "en", "hindi", "english"], default=None, help="Audio language (prompted if omitted)")
#     parser.add_argument("-g", "--gender", choices=["female", "male"], default=None, help="Narrator gender (prompted if omitted)")
#     parser.add_argument("--accent", choices=["us", "hindi", "uk"], default=None, help="Voice accent: 'us', 'hindi', or 'uk' (prompted if omitted)")
#     parser.add_argument("--voice", default=None, help="Optional explicit Kokoro voice ID override (e.g. af_heart, am_michael, hf_alpha)")
#     parser.add_argument("--speed", type=float, default=TTS_SPEED, help=f"TTS speed (default: {TTS_SPEED})")
#     parser.add_argument("-y", "--yes", action="store_true", help="Skip interactive prompts and use defaults for omitted options")
#     parser.add_argument("--no-cache", action="store_true", help="Force fresh TTS generation instead of reusing tts_cache")
#     args = parser.parse_args()

#     run_assembly(
#         args.json_path,
#         frames_dir=args.frames_dir,
#         output_path=args.output,
#         aspect_ratio=args.aspect_ratio,
#         bgm_path=args.bgm,
#         lang=args.lang,
#         gender=args.gender,
#         accent=args.accent,
#         voice=args.voice,
#         speed=args.speed,
#         yes=args.yes,
#         no_cache=args.no_cache,
#     )













# Run interactively (prompts for Language, Accent, Gender, Voice, Subtitles, and SFX):
#   python teacherassemble.py teachingscript.json
#   python teacherassemble.py teachingscript.json -a 9:16 -b bgm.mp3 -o final_video.mp4
#
# Or pass flags directly + -y to skip prompts:
#   python teacherassemble.py teachingscript.json --lang en --accent us --gender male --subtitle en --sfx -y
#   python teacherassemble.py teachingscript.json --lang hi --accent hindi --gender female --subtitle none --no-sfx -y

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    from PIL import Image, ImageDraw, ImageFont, features as pil_features
except ImportError:
    Image = ImageDraw = ImageFont = pil_features = None

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import requests
except ImportError:
    requests = None

try:
    from groq import Groq
except ImportError:
    Groq = None


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_LANG = "en"       # "en" or "hi" (auto-detected from script if omitted)
DEFAULT_GENDER = "female" # "female" or "male"
DEFAULT_ACCENT = "us"     # "us", "hindi", or "uk"
TTS_SPEED = 1.02          # Natural conversational pace
VOICE_VOLUME = 0.96

# Grouping & natural phrasing controls
MAX_GROUP_CHARS = 360     # Keep within Kokoro's optimal prosody window
MAX_BEATS_PER_GROUP = 4   # Speak up to 4 connected beats in one continuous pass
INTER_GROUP_PAUSE_MS = 140
BRIDGE_EXTRA_PAUSE_MS = 220

FPS = 30
VIDEO_ZOOM = 1.08         # Subtle zoom + smooth alternating pan across each image
BGM_VOLUME = 0.12         # Used only if --bgm is passed

# Groq + Freesound SFX controls
SFX_MIN_DUR = 0.2
SFX_MAX_DUR = 6.0
SFX_MASTER_VOLUME = 0.72
GROQ_MODEL_DEFAULT = "openai/gpt-oss-120b"

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
CACHE_DIR = BASE_DIR / "tts_cache"
BUILD_DIR = BASE_DIR / "build"
DEFAULT_FRAMES_DIR = BUILD_DIR / "frames"
SFX_DIR = BUILD_DIR / "sfx"
PROCESSED_SFX_DIR = BUILD_DIR / "processed_sfx"
TIMESTAMPS_DIR = BUILD_DIR / "word_timestamps"
TRANSLATION_CACHE_FILE = BASE_DIR / "translation_cache.json"

_KOKORO_INSTANCE = None
_TRANSLATION_CACHE = None
_PHONEMIZER_PATCHED = False
_TRANSLATION_COOLDOWN_UNTIL = 0.0

VOICE_PRESETS = {
    "us": {
        "female": ["af_heart", "af_bella", "af_sarah", "af_nicole"],
        "male": ["am_michael", "am_adam", "am_fenrir", "am_onyx"],
    },
    "hindi": {
        "female": ["hf_alpha", "hf_beta"],
        "male": ["hm_omega", "hm_psi"],
    },
    "uk": {
        "female": ["bf_emma", "bf_isabella", "bf_alice"],
        "male": ["bm_george", "bm_lewis", "bm_daniel"],
    },
}

ACRONYM_MAP = {
    "AI": "A I",
    "ML": "M L",
    "LLM": "L L M",
    "LLMs": "L L Ms",
    "NLP": "N L P",
    "PDF": "P D F",
    "PDFs": "P D Fs",
    "GPU": "G P U",
    "GPUs": "G P Us",
    "API": "A P I",
    "APIs": "A P Is",
    "URL": "U R L",
    "URLs": "U R Ls",
    "URI": "U R I",
    "SQL": "S Q L",
    "NoSQL": "No S Q L",
    "DTO": "D T O",
    "DTOs": "D T Os",
    "ORM": "O R M",
    "JWT": "J W T",
    "HTML": "H T M L",
    "CSS": "C S S",
    "DOM": "D O M",
    "CLI": "C L I",
    "IDE": "I D E",
    "SDK": "S D K",
    "JDK": "J D K",
    "JVM": "J V M",
    "HTTP": "H T T P",
    "HTTPS": "H T T P S",
    "UI": "U I",
    "UX": "U X",
    "DB": "D B",
    "ID": "I D",
    "IDs": "I Ds",
    "CPU": "C P U",
    "RAM": "R A M",
    "MVC": "M V C",
    "DI": "D I",
    "IoC": "I o C",
    "OOP": "O O P",
    "NPM": "N P M",
    "npm": "N P M",
    "JPA": "J P A",
    "DAO": "D A O",
    "POJO": "po jo",
}


# ============================================================
# HELPERS & ENV LOADER
# ============================================================

def load_env_vars():
    if load_dotenv is not None:
        load_dotenv()
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def run_cmd(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            "\nFFmpeg command failed:\n"
            + " ".join(map(str, command))
            + "\n\n"
            + (result.stderr or "")[-4000:]
        )
    return result


def get_duration(path):
    result = run_cmd([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ])
    return float(result.stdout.strip())


def check_dependencies():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} was not found in PATH.")
    find_kokoro_models()


def sanitize_filename(name):
    cleaned = re.sub(r'[<>:"/\\|?*]+', "", name.strip())
    return re.sub(r"\s+", "_", cleaned).strip("_") or "story"


def has_devanagari(text):
    return any("\u0900" <= ch <= "\u097f" for ch in text)


def load_story_json(json_path):
    raw_text = json_path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(raw_text, strict=False)
    except json.JSONDecodeError:
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw_text)
        return json.loads(cleaned, strict=False)


def extract_beats(story_data):
    """Supports flat `beats[]` (movie-recap/explainer schema) and `scenes[].beats[]`."""
    if story_data.get("beats"):
        return story_data["beats"]
    beats = []
    for sc in story_data.get("scenes", []):
        for bt in sc.get("beats", []):
            beats.append(bt)
    return beats


def get_beat_raw_narration(beat):
    clips = beat.get("clips") or []
    return (
        beat.get("narration", "").strip()
        or beat.get("narration_text", "").strip()
        or " ".join(c.get("spoken_text", "").strip() for c in clips if c.get("spoken_text", "").strip())
    )


def get_beat_visual_context(beat):
    parts = []
    for key in ("prompt_action", "scene_context", "visual_context"):
        val = beat.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    for clip in beat.get("clips") or []:
        sc = (clip.get("scene_context") or clip.get("prompt_action") or "").strip()
        if sc:
            parts.append(sc)
    return " | ".join(dict.fromkeys(parts))


def detect_script_language(beats):
    sample_text = " ".join(get_beat_raw_narration(bt) for bt in beats[:5])
    return "hi" if has_devanagari(sample_text) else "en"


def get_render_profile(aspect_ratio):
    if aspect_ratio == "9:16":
        return {
            "width": 1080,
            "height": 1920,
            "sub_font_size": 34,
            "sub_max_chars_cue": 52,
            "sub_max_chars_line": 28,
            "sub_bottom_margin": 140,
        }
    return {
        "width": 1920,
        "height": 1080,
        "sub_font_size": 32,
        "sub_max_chars_cue": 74,
        "sub_max_chars_line": 48,
        "sub_bottom_margin": 54,
    }


def detect_aspect_ratio_from_image(img_path):
    if Image is None or not img_path or not Path(img_path).exists():
        return "9:16"
    with Image.open(img_path) as im:
        w, h = im.size
    return "9:16" if h > w else "16:9"


def resolve_clip_image(clip, beat_id, clip_id, frames_dir):
    for key in ("image", "image_path", "frame"):
        val = clip.get(key)
        if val:
            p = Path(val)
            if not p.is_absolute():
                p = BASE_DIR / p
            if p.exists():
                return p

    for stem in (f"{beat_id}_{clip_id}", clip_id, beat_id):
        for ext in IMAGE_EXTENSIONS:
            candidate = frames_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate

    raise FileNotFoundError(
        f"Image not found for beat={beat_id}, clip={clip_id} in {frames_dir}. "
        f"Tried {beat_id}_{clip_id}.png, {clip_id}.png, and {beat_id}.png"
    )


# ============================================================
# TRANSLATION WITH 429 RATE-LIMIT HANDLING & HINDI FALLBACK
# ============================================================

def _get_translation_cache():
    global _TRANSLATION_CACHE
    if _TRANSLATION_CACHE is None:
        if TRANSLATION_CACHE_FILE.exists():
            try:
                _TRANSLATION_CACHE = json.loads(
                    TRANSLATION_CACHE_FILE.read_text(encoding="utf-8")
                )
            except Exception:
                _TRANSLATION_CACHE = {}
        else:
            _TRANSLATION_CACHE = {}
    return _TRANSLATION_CACHE


def _save_translation_cache(cache):
    TRANSLATION_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def translate_text(text, src, tgt, allow_network=True):
    global _TRANSLATION_COOLDOWN_UNTIL

    text = " ".join(text.strip().split())
    if not text or src == tgt:
        return text
    if src == "hi" and tgt == "en" and not has_devanagari(text):
        return text

    cache = _get_translation_cache()
    cache_key = text if (src == "hi" and tgt == "en") else f"{src}->{tgt}::{text}"

    if cache_key in cache:
        cached_val = cache[cache_key]
        if not (src == "hi" and tgt == "en" and has_devanagari(cached_val)):
            return cached_val

    if not allow_network or time.time() < _TRANSLATION_COOLDOWN_UNTIL:
        return text

    translated = None
    last_err = None

    for attempt in range(2):
        if GoogleTranslator is not None:
            try:
                res = GoogleTranslator(source=src, target=tgt).translate(text)
                if res and res.strip():
                    translated = res
                    break
            except Exception as exc:
                last_err = exc
                if "429" in str(exc) or "too many" in str(exc).lower():
                    time.sleep(1.5 * (attempt + 1))
                    continue

        if not translated:
            try:
                url = (
                    "https://translate.googleapis.com/translate_a/single"
                    f"?client=gtx&sl={src}&tl={tgt}&dt=t&q=" + urllib.parse.quote(text)
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    res = "".join(part[0] for part in data[0] if part and part[0])
                    if res and res.strip():
                        translated = res
                        break
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                last_err = exc
                break

    if not translated:
        if last_err and ("429" in str(last_err) or "too many" in str(last_err).lower()):
            _TRANSLATION_COOLDOWN_UNTIL = time.time() + 60.0
            print("      [Warning] Google Translate rate-limited (429); falling back to original text for remaining lines.")
        elif last_err:
            print(f"      [Warning] Translation failed ({last_err}); falling back to original text.")
        return text

    translated = " ".join(translated.strip().split())
    cache[cache_key] = translated
    _save_translation_cache(cache)
    time.sleep(0.20)
    return translated


def ensure_english_text(text, allow_network=True):
    return translate_text(text, src="hi", tgt="en", allow_network=allow_network)


def resolve_subtitle_text(raw_narration, subtitle_mode):
    if subtitle_mode == "none":
        return ""
    if subtitle_mode == "hi":
        if has_devanagari(raw_narration):
            return raw_narration
        return translate_text(raw_narration, src="en", tgt="hi")
    if not has_devanagari(raw_narration):
        return raw_narration
    return translate_text(raw_narration, src="hi", tgt="en")


# ============================================================
# TEXT NORMALIZATION FOR NATURAL TTS
# ============================================================

def normalize_text_for_tts(text, lang="en"):
    orig = " ".join(text.strip().split())
    if not orig:
        return orig

    s = orig
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", "").replace("\u201d", "").replace('"', "")
    s = s.replace("`", "").replace("*", "").replace("()", "")

    s = re.sub(r"\s*&\s*", " aur " if lang == "hi" else " and ", s)

    s = s.replace("->", ", ").replace("=>", ", ")
    s = re.sub(r"[—–]+", ", ", s)
    s = re.sub(r"\s+-\s+", ", ", s)
    s = re.sub(r"\(([^)]+)\)", r", \1, ", s)

    s = re.sub(r"@([A-Za-z_]\w*)", r"at \1", s)
    s = re.sub(r"([A-Za-z0-9])_([A-Za-z0-9])", r"\1 \2", s)

    s = re.sub(
        r"\b([A-Za-z][A-Za-z0-9-]*)\.(js|ts|jsx|tsx|json|html|css|xml|yml|yaml|sql|py|java|md)\b",
        lambda m: f"{m.group(1)} {m.group(2).upper()}",
        s,
        flags=re.IGNORECASE,
    )

    while re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", s):
        s = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", r"\1 dot \2", s)

    s = re.sub(r"([A-Za-z0-9]+)/([A-Za-z0-9]+)", r"\1, \2", s)

    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)

    s = re.sub(r"\b[A-Za-z]{2,6}\b", lambda m: ACRONYM_MAP.get(m.group(0), m.group(0)), s)

    if lang == "hi":
        s = s.replace("॥", ".").replace("।", ".")

    s = re.sub(r"\s*,\s*(,\s*)+", ", ", s)
    s = re.sub(r"\s+([,।.!?])", r"\1", s)
    s = " ".join(s.split()).strip(" ,")

    if not s:
        return orig

    if s[-1] not in "।.!?":
        s += "."

    return s


def estimate_spoken_weight(text):
    w = 0.0
    for ch in text:
        if ch.isspace():
            continue
        if "\u0904" <= ch <= "\u0939" or "\u0958" <= ch <= "\u0961":
            w += 1.25
        elif "\u0900" <= ch <= "\u097f":
            w += 0.35
        elif ch.isalnum():
            w += 0.90
        elif ch in ",;:":
            w += 3.2
        elif ch in "।.!?":
            w += 6.0
    return max(w, 1.0)


# ============================================================
# KOKORO ONNX TTS + PHONEMIZER FIX + FLUENT SYNTHESIS
# ============================================================

def _strip_lang_flags(phonemes):
    if isinstance(phonemes, str):
        cleaned = re.sub(r"\([A-Za-z0-9_-]{1,14}\)", " ", phonemes)
        return re.sub(r"\s+", " ", cleaned).strip()
    if isinstance(phonemes, list):
        return [_strip_lang_flags(p) for p in phonemes]
    return phonemes


def patch_kokoro_phonemizer(kokoro):
    global _PHONEMIZER_PATCHED
    if _PHONEMIZER_PATCHED:
        return
    _PHONEMIZER_PATCHED = True

    try:
        import phonemizer
        if hasattr(phonemizer, "phonemize"):
            orig_ph = phonemizer.phonemize

            def patched_phonemize(*args, **kwargs):
                kwargs.setdefault("language_switch", "remove-flags")
                return _strip_lang_flags(orig_ph(*args, **kwargs))

            phonemizer.phonemize = patched_phonemize

        from phonemizer.backend import EspeakBackend
        if hasattr(EspeakBackend, "phonemize"):
            orig_backend_ph = EspeakBackend.phonemize

            def patched_backend_ph(self, *args, **kwargs):
                return _strip_lang_flags(orig_backend_ph(self, *args, **kwargs))

            EspeakBackend.phonemize = patched_backend_ph
    except Exception:
        pass

    tok = getattr(kokoro, "tokenizer", None)
    if tok is not None:
        if hasattr(tok, "phonemize"):
            orig_tok_ph = tok.phonemize

            def patched_tok_ph(*args, **kwargs):
                return _strip_lang_flags(orig_tok_ph(*args, **kwargs))

            tok.phonemize = patched_tok_ph

        inner_backend = getattr(tok, "phonemizer", None)
        if inner_backend is not None and hasattr(inner_backend, "phonemize"):
            orig_inner = inner_backend.phonemize

            def patched_inner(*args, **kwargs):
                return _strip_lang_flags(orig_inner(*args, **kwargs))

            inner_backend.phonemize = patched_inner


def find_kokoro_models():
    if not MODELS_DIR.exists():
        raise FileNotFoundError(f"Models folder not found: {MODELS_DIR}")

    model_path = next(
        (p for p in [MODELS_DIR / "kokoro-v1.0.onnx", MODELS_DIR / "kokoro-v0_19.onnx"] if p.exists()),
        None
    ) or next(iter(sorted(MODELS_DIR.glob("*.onnx"))), None)
    if model_path is None:
        raise FileNotFoundError(f"No .onnx model file found in {MODELS_DIR}")

    voices_path = next(
        (p for p in [MODELS_DIR / "voices-v1.0.bin", MODELS_DIR / "voices.bin", MODELS_DIR / "voices.json"] if p.exists()),
        None
    ) or next(
        iter(sorted(list(MODELS_DIR.glob("*.bin")) + list(MODELS_DIR.glob("*voices*.json")))),
        None
    )
    if voices_path is None:
        raise FileNotFoundError(f"No voices file found in {MODELS_DIR}")

    return model_path, voices_path


def get_kokoro():
    global _KOKORO_INSTANCE
    if _KOKORO_INSTANCE is None:
        model_path, voices_path = find_kokoro_models()
        print(f"Loading Kokoro: {model_path.name} | Voices: {voices_path.name}")
        _KOKORO_INSTANCE = Kokoro(str(model_path), str(voices_path))
        patch_kokoro_phonemizer(_KOKORO_INSTANCE)
    return _KOKORO_INSTANCE


def get_available_voices(kokoro):
    if hasattr(kokoro, "get_voices"):
        try:
            return set(kokoro.get_voices())
        except Exception:
            pass
    voices_obj = getattr(kokoro, "voices", None)
    if isinstance(voices_obj, dict):
        return set(voices_obj.keys())
    if hasattr(voices_obj, "files"):
        return set(voices_obj.files)
    return set()


def get_voices_for_profile(accent, gender):
    kokoro = get_kokoro()
    available = get_available_voices(kokoro)
    candidates = list(VOICE_PRESETS[accent][gender])

    if not available:
        return candidates

    filtered = [v for v in candidates if v in available]
    prefix = f"{'h' if accent == 'hindi' else ('b' if accent == 'uk' else 'a')}{'f' if gender == 'female' else 'm'}_"
    extra = sorted(v for v in available if v.startswith(prefix) and v not in filtered)
    combined = filtered + extra
    if combined:
        return combined

    any_gender = sorted(v for v in available if len(v) > 2 and v[1] == ("f" if gender == "female" else "m"))
    return any_gender or sorted(available)


def resolve_voice_and_tts_lang(narration_lang, gender, accent, explicit_voice=None):
    kokoro = get_kokoro()
    available = get_available_voices(kokoro)

    if narration_lang == "hi":
        tts_lang = "hi"
    else:
        tts_lang = "en-gb" if accent == "uk" else "en-us"

    if explicit_voice:
        if available and explicit_voice not in available:
            raise ValueError(
                f"Voice '{explicit_voice}' not found in loaded voices file. "
                f"Available sample: {sorted(available)[:20]}"
            )
        return explicit_voice, tts_lang

    candidates = get_voices_for_profile(accent, gender)
    return candidates[0], tts_lang


def save_wav(path, samples, sample_rate):
    samples = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    if sf is not None:
        sf.write(str(path), samples, int(sample_rate), subtype="PCM_16")
        return
    pcm16 = (samples * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm16.tobytes())


def load_audio_mono(path, target_sr=None, temp_dir=None):
    """Loads WAV/MP3/FLAC/OGG as mono float32; falls back to FFmpeg if soundfile cannot decode MP3."""
    path = Path(path)
    samples = None
    sr = None

    if sf is not None:
        try:
            data, file_sr = sf.read(str(path), dtype="float32")
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            samples, sr = data.astype(np.float32), int(file_sr)
        except Exception:
            samples = None

    if samples is None and path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wf:
            sr = wf.getframerate()
            nch = wf.getnchannels()
            frames = wf.readframes(wf.getnframes())
        pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if nch > 1:
            pcm = pcm.reshape(-1, nch).mean(axis=1)
        samples = pcm

    if samples is None:
        tmp_wav = (Path(temp_dir) if temp_dir else path.parent) / f".dec_{path.stem}.wav"
        dec_sr = int(target_sr or 24000)
        run_cmd([
            "ffmpeg", "-y", "-i", str(path),
            "-vn", "-ac", "1", "-ar", str(dec_sr), "-c:a", "pcm_s16le",
            str(tmp_wav)
        ])
        try:
            return load_audio_mono(tmp_wav, target_sr=target_sr)
        finally:
            if tmp_wav.exists():
                tmp_wav.unlink(missing_ok=True)

    if target_sr is not None and sr != target_sr and samples.size > 0:
        old_x = np.linspace(0.0, 1.0, samples.size)
        new_len = max(1, int(round(samples.size * target_sr / sr)))
        new_x = np.linspace(0.0, 1.0, new_len)
        samples = np.interp(new_x, old_x, samples).astype(np.float32)
        sr = int(target_sr)

    return samples, int(sr)


def apply_cosine_fades(samples, sr, fade_in_ms=8, fade_out_ms=12):
    samples = np.asarray(samples, dtype=np.float32).copy()
    n = samples.size
    if n == 0:
        return samples
    fi = min(int(sr * fade_in_ms / 1000), n // 3)
    fo = min(int(sr * fade_out_ms / 1000), n // 3)
    if fi > 1:
        ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, fi, dtype=np.float32)))
        samples[:fi] *= ramp
    if fo > 1:
        ramp = 0.5 * (1.0 + np.cos(np.linspace(0.0, np.pi, fo, dtype=np.float32)))
        samples[-fo:] *= ramp
    return samples


def gentle_trim_silence(samples, sr, threshold=0.0012, pad_start_ms=45, pad_end_ms=75):
    samples = np.asarray(samples, dtype=np.float32)
    active = np.where(np.abs(samples) > threshold)[0]
    if active.size == 0:
        return samples
    start_idx = max(0, int(active[0]) - int(sr * pad_start_ms / 1000))
    end_idx = min(samples.size, int(active[-1]) + int(sr * pad_end_ms / 1000))
    return samples[start_idx:end_idx]


def normalize_voice_dynamics(samples, target_rms=0.115):
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return samples
    active = samples[np.abs(samples) > 0.004]
    if active.size < 64:
        return samples
    rms = float(np.sqrt(np.mean(active * active)))
    if rms <= 1e-5:
        return samples
    gain = np.clip(target_rms / rms, 0.65, 1.85)
    scaled = samples * gain
    peak = float(np.max(np.abs(scaled)))
    if peak > 0.92:
        scaled = np.tanh(scaled * 0.95) / np.tanh(0.95) * 0.92
    return scaled.astype(np.float32)


def split_long_sentences(text, max_chars=340):
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<!\d)(?<=[।!?\.])\s+", text)
    chunks, curr = [], ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if curr and len(curr) + 1 + len(part) > max_chars:
            chunks.append(curr)
            curr = part
        else:
            curr = f"{curr} {part}".strip() if curr else part
    if curr:
        chunks.append(curr)
    return chunks or [text]


def synthesize_text_raw(text, voice, tts_lang, speed=TTS_SPEED):
    kokoro = get_kokoro()
    parts = split_long_sentences(text, max_chars=340)
    chunks, sample_rate = [], None

    for idx, part in enumerate(parts):
        samples, sr = kokoro.create(part, voice=voice, speed=speed, lang=tts_lang)
        sample_rate = int(sr)
        samples = gentle_trim_silence(
            samples, sample_rate,
            pad_start_ms=45 if idx == 0 else 55,
            pad_end_ms=75 if idx == len(parts) - 1 else 65,
        )
        samples = normalize_voice_dynamics(samples)
        samples = apply_cosine_fades(samples, sample_rate, fade_in_ms=8, fade_out_ms=12)
        if samples.size > 0:
            chunks.append(samples)

    if not chunks or sample_rate is None:
        raise RuntimeError(f"Kokoro returned empty audio for: {text}")

    if len(chunks) == 1:
        return chunks[0], sample_rate

    breath_gap = np.zeros(int(sample_rate * 0.16), dtype=np.float32)
    joined = []
    for i, ch in enumerate(chunks):
        if i > 0:
            joined.append(breath_gap)
        joined.append(ch)
    return np.concatenate(joined), sample_rate


def find_quiet_pauses(samples, sr, min_pause_s=0.055):
    n = samples.size
    win = max(1, int(0.020 * sr))
    hop = max(1, int(0.005 * sr))
    if n < win * 4:
        return [], 0, n

    sq = samples.astype(np.float64) ** 2
    csum = np.concatenate(([0.0], np.cumsum(sq)))
    starts = np.arange(0, n - win + 1, hop)
    rms = np.sqrt(np.maximum(0.0, (csum[starts + win] - csum[starts]) / win))

    active_rms = rms[rms > 0.003]
    if active_rms.size == 0:
        return [], 0, n
    med_rms = float(np.median(active_rms))
    quiet_thresh = min(0.015, max(0.0025, 0.065 * med_rms))

    active_frames = np.where(rms > quiet_thresh)[0]
    if active_frames.size == 0:
        return [], 0, n
    speech_start = int(starts[active_frames[0]])
    speech_end = int(starts[active_frames[-1]] + win)

    is_quiet = rms < quiet_thresh
    padded = np.concatenate(([False], is_quiet, [False]))
    q_starts = np.where(~padded[:-1] & padded[1:])[0]
    q_ends = np.where(padded[:-1] & ~padded[1:])[0]

    candidates = []
    for qs, qe in zip(q_starts, q_ends):
        s_samp = int(starts[qs])
        e_samp = int(starts[min(qe, len(starts) - 1)] + win)
        if e_samp <= speech_start + int(0.20 * sr) or s_samp >= speech_end - int(0.20 * sr):
            continue
        dur_s = (e_samp - s_samp) / sr
        if dur_s >= min_pause_s:
            candidates.append(((s_samp + e_samp) // 2, dur_s))

    return candidates, speech_start, speech_end


def find_natural_split_points(samples, sr, norm_texts):
    k = len(norm_texts)
    if k <= 1:
        return []

    candidates, speech_start, speech_end = find_quiet_pauses(samples, sr, min_pause_s=0.065)
    speech_span = max(1, speech_end - speech_start)
    if len(candidates) < k - 1:
        return None

    weights = [estimate_spoken_weight(t) for t in norm_texts]
    total_w = sum(weights)
    cum_w = 0.0
    exp_samples = []
    for w in weights[:-1]:
        cum_w += w
        exp_samples.append(speech_start + int(speech_span * (cum_w / total_w)))

    max_dev = max(int(1.4 * sr), int(0.28 * speech_span))
    min_seg_samples = int(0.35 * sr)

    best_cost = float("inf")
    best_splits = None

    def backtrack(b_idx, c_start_idx, prev_split, chosen):
        nonlocal best_cost, best_splits
        if b_idx == k - 1:
            if speech_end - prev_split < min_seg_samples:
                return
            cost = 0.0
            for j, (mid_s, dur_s) in enumerate(chosen):
                cost += abs(mid_s - exp_samples[j]) / sr - 0.75 * min(dur_s, 0.55)
            if cost < best_cost:
                best_cost = cost
                best_splits = [m for m, _ in chosen]
            return

        exp_s = exp_samples[b_idx]
        for ci in range(c_start_idx, len(candidates)):
            mid_s, dur_s = candidates[ci]
            if mid_s - prev_split < min_seg_samples:
                continue
            if abs(mid_s - exp_s) > max_dev:
                if mid_s > exp_s + max_dev:
                    break
                continue
            chosen.append((mid_s, dur_s))
            backtrack(b_idx + 1, ci + 1, mid_s, chosen)
            chosen.pop()

    backtrack(0, 0, speech_start, [])
    return best_splits


def group_beats_for_tts(beats, narration_lang="en", subtitle_mode="en"):
    groups = []
    current_group = []
    current_chars = 0

    for idx, beat in enumerate(beats):
        raw_narration = get_beat_raw_narration(beat)
        if not raw_narration:
            beat_id = beat.get("beat_id", f"B{idx + 1:04d}")
            raise ValueError(f"{beat_id}: missing narration.")

        if narration_lang == "en":
            spoken_source = ensure_english_text(raw_narration)
        else:
            spoken_source = raw_narration

        subtitle_text = resolve_subtitle_text(raw_narration, subtitle_mode=subtitle_mode)
        norm_text = normalize_text_for_tts(spoken_source, lang=narration_lang)
        added_len = len(norm_text) + (1 if current_group else 0)

        if current_group and (
            len(current_group) >= MAX_BEATS_PER_GROUP
            or current_chars + added_len > MAX_GROUP_CHARS
        ):
            groups.append(current_group)
            current_group = []
            current_chars = 0

        current_group.append({
            "beat_index": idx + 1,
            "beat": beat,
            "raw_narration": raw_narration,
            "spoken_source": spoken_source,
            "subtitle_text": subtitle_text,
            "norm_text": norm_text,
            "is_bridge": bool(beat.get("is_scene_bridge", False)),
        })
        current_chars += len(norm_text) + (1 if len(current_group) > 1 else 0)

        if beat.get("is_scene_bridge", False):
            groups.append(current_group)
            current_group = []
            current_chars = 0

    if current_group:
        groups.append(current_group)

    return groups


def synthesize_group_and_cache(group, voice, tts_lang, speed=TTS_SPEED, use_cache=True):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sig_payload = json.dumps(
        {
            "v": "v6_fluent",
            "voice": voice,
            "lang": tts_lang,
            "speed": speed,
            "texts": [item["norm_text"] for item in group],
        },
        ensure_ascii=False,
    )
    group_key = hashlib.md5(sig_payload.encode("utf-8")).hexdigest()
    cached_paths = [CACHE_DIR / f"{group_key}_{i:02d}.wav" for i in range(len(group))]

    all_cached = use_cache and all(p.exists() and p.stat().st_size > 0 for p in cached_paths)
    if not all_cached:
        norm_texts = [item["norm_text"] for item in group]
        beat_samples_list = None
        sr = None

        if len(group) > 1:
            joined = " ".join(norm_texts)
            print(f"      Generating fluent TTS group ({len(group)} beats): {joined[:78]}...")
            full_samples, sr = synthesize_text_raw(joined, voice=voice, tts_lang=tts_lang, speed=speed)
            split_pts = find_natural_split_points(full_samples, sr, norm_texts)

            if split_pts is not None:
                bounds = [0] + split_pts + [full_samples.size]
                beat_samples_list = []
                for i in range(len(group)):
                    seg = full_samples[bounds[i]:bounds[i + 1]]
                    fi = 4 if i > 0 else 8
                    fo = 4 if i < len(group) - 1 else 12
                    seg = apply_cosine_fades(seg, sr, fade_in_ms=fi, fade_out_ms=fo)
                    beat_samples_list.append(seg)
            else:
                print("      [Note] Pause alignment uncertain for group; falling back to per-beat with natural pauses.")

        if beat_samples_list is None:
            beat_samples_list = []
            for item in group:
                print(f"      Generating TTS: {item['norm_text'][:78]}...")
                seg, sr = synthesize_text_raw(item["norm_text"], voice=voice, tts_lang=tts_lang, speed=speed)
                beat_samples_list.append(seg)

        for path, seg in zip(cached_paths, beat_samples_list):
            save_wav(path, seg, sr)

    results = []
    for idx, (item, path) in enumerate(zip(group, cached_paths)):
        dur = get_duration(path)
        if dur <= 0:
            raise RuntimeError(f"Invalid TTS duration: {path}")

        if idx < len(group) - 1:
            pause_after_s = 0.0
        else:
            pause_after_s = (INTER_GROUP_PAUSE_MS + (BRIDGE_EXTRA_PAUSE_MS if item["is_bridge"] else 0)) / 1000.0

        results.append((path, dur, pause_after_s))

    return results


def prepare_all_beats_audio(beats, temp_dir, narration_lang, subtitle_mode, voice, tts_lang, speed=TTS_SPEED, use_cache=True):
    groups = group_beats_for_tts(beats, narration_lang=narration_lang, subtitle_mode=subtitle_mode)
    print(
        f"Synthesizing fluent narration ({narration_lang.upper()} | {voice} | {tts_lang} | sub={subtitle_mode.upper()}) "
        f"across {len(beats)} beats in {len(groups)} groups..."
    )

    beat_audio_plans = []
    master_chunks = []
    master_sr = None
    timeline_cursor_s = 0.0

    for group in groups:
        group_results = synthesize_group_and_cache(
            group, voice=voice, tts_lang=tts_lang, speed=speed, use_cache=use_cache
        )
        for item, (wav_path, raw_dur, pause_after_s) in zip(group, group_results):
            samples, sr = load_audio_mono(wav_path)
            if master_sr is None:
                master_sr = sr
            elif sr != master_sr:
                samples, _ = load_audio_mono(wav_path, target_sr=master_sr)

            exact_speech_dur = samples.size / master_sr
            total_target_dur = exact_speech_dur + pause_after_s
            num_frames = max(3, int(round(total_target_dur * FPS)))
            frame_aligned_dur = num_frames / FPS
            target_samples = int(round(frame_aligned_dur * master_sr))

            if target_samples > samples.size:
                padded = np.concatenate([
                    samples,
                    np.zeros(target_samples - samples.size, dtype=np.float32)
                ])
            else:
                padded = apply_cosine_fades(samples[:target_samples], master_sr, fade_in_ms=0, fade_out_ms=6)

            master_chunks.append(padded)
            beat_audio_plans.append({
                "beat_index": item["beat_index"],
                "beat": item["beat"],
                "raw_narration": item["raw_narration"],
                "spoken_source": item["spoken_source"],
                "subtitle_text": item["subtitle_text"],
                "speech_samples": samples,
                "sample_rate": master_sr,
                "speech_dur": exact_speech_dur,
                "beat_start_s": timeline_cursor_s,
                "num_frames": num_frames,
                "frame_dur": frame_aligned_dur,
            })
            timeline_cursor_s += frame_aligned_dur

    master_samples = np.concatenate(master_chunks)
    master_wav_path = Path(temp_dir) / "master_narration.wav"
    save_wav(master_wav_path, master_samples, master_sr)

    return beat_audio_plans, master_wav_path, master_samples.size, master_sr


# ============================================================
# GROQ SOUND DIRECTOR + FREESOUND FOLEY SFX PIPELINE
# ============================================================

def calculate_word_weight(word):
    matras = set("ाीूेैोौौंः")
    short_vowels = set("िु")
    virama = "्"

    weight = 0.0
    for ch in word:
        if ch in matras:
            weight += 1.4
        elif ch in short_vowels:
            weight += 0.8
        elif ch == virama:
            weight -= 0.3
        elif "\u0900" <= ch <= "\u097F":
            weight += 1.0
        elif ch.isalnum():
            weight += 0.65
        else:
            weight += 0.25
    return max(0.6, weight)


def align_ground_truth_to_samples(data, sr, ground_truth_text, output_json=None):
    data = np.asarray(data, dtype=np.float32)
    if data.size == 0:
        return []

    total_duration_sec = len(data) / float(sr)
    clean_text = re.sub(r'["“”‘’\']', "", ground_truth_text)
    clean_text = clean_text.replace("...", "…")
    raw_words = [w.strip() for w in re.split(r"\s+", clean_text) if w.strip()]
    if not raw_words:
        return []

    frame_len = max(1, int(sr * 0.02))
    hop_len = max(1, int(sr * 0.01))
    if len(data) > frame_len:
        frames = [data[i:i + frame_len] for i in range(0, len(data) - frame_len, hop_len)]
        rms = np.array([np.sqrt(np.mean(f ** 2)) for f in frames])
        threshold = np.max(rms) * 0.05
        active_indices = np.where(rms > threshold)[0]
    else:
        active_indices = np.array([], dtype=np.int64)

    if len(active_indices) > 0:
        speech_start_sec = max(0.0, (active_indices[0] * hop_len) / sr - 0.04)
        speech_end_sec = min(total_duration_sec, (active_indices[-1] * hop_len) / sr + 0.06)
    else:
        speech_start_sec = 0.0
        speech_end_sec = total_duration_sec

    usable_duration = max(0.05, speech_end_sec - speech_start_sec)
    weights = [calculate_word_weight(w) for w in raw_words]
    total_weight = sum(weights)

    words_timeline = []
    current_time = speech_start_sec
    for word, weight in zip(raw_words, weights):
        word_dur = (weight / total_weight) * usable_duration
        words_timeline.append({
            "word": word,
            "start_ms": int(current_time * 1000),
            "end_ms": int((current_time + word_dur) * 1000),
        })
        current_time += word_dur

    if output_json is not None:
        Path(output_json).write_text(
            json.dumps(words_timeline, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    return words_timeline


class FreesoundAudioAPI:
    BASE_URL = "https://freesound.org/apiv2/search/text/"
    NEGATIVE_TAG_FILTER = "-tag:music -tag:beat -tag:loop -tag:song -tag:synth -tag:electronic"

    @classmethod
    def clean_query_term(cls, term):
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", str(term or ""))
        return " ".join(cleaned.split())

    @classmethod
    def search_and_download(cls, query, fallback_query="", api_key=None):
        if requests is None:
            raise RuntimeError("`requests` is required for Freesound SFX. Install with: pip install requests")
        api_key = api_key or os.getenv("FREESOUND_API_KEY")
        if not api_key:
            raise RuntimeError("FREESOUND_API_KEY is not set.")

        headers = {
            "Authorization": f"Token {api_key}",
            "User-Agent": "TeacherAssembleFoleyBot/4.0",
        }
        SFX_DIR.mkdir(parents=True, exist_ok=True)

        q_clean = cls.clean_query_term(query)
        fb_clean = cls.clean_query_term(fallback_query)
        if not q_clean and not fb_clean:
            return None

        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", (q_clean or fb_clean).strip().lower())
        cached_files = list(SFX_DIR.glob(f"{slug}_*.mp3"))
        if cached_files and cached_files[0].stat().st_size > 1024:
            return cached_files[0]

        queries_to_try = [q_clean]
        if fb_clean and fb_clean != q_clean:
            queries_to_try.append(fb_clean)
        words = q_clean.split()
        if len(words) >= 2:
            queries_to_try.append(f"{words[0]} {words[1]}")

        for attempt_query in queries_to_try:
            if not attempt_query.strip():
                continue

            params = {
                "query": attempt_query,
                "filter": f"duration:[{SFX_MIN_DUR} TO {SFX_MAX_DUR}] {cls.NEGATIVE_TAG_FILTER}",
                "sort": "score",
                "fields": "id,name,previews,duration,num_downloads,rating_avg",
                "page_size": 5,
            }

            try:
                resp = requests.get(cls.BASE_URL, headers=headers, params=params, timeout=10)
                if resp.status_code != 200:
                    continue

                results = resp.json().get("results", [])
                if not results:
                    params["filter"] = f"duration:[{SFX_MIN_DUR} TO {SFX_MAX_DUR}]"
                    params["sort"] = "rating_desc"
                    resp = requests.get(cls.BASE_URL, headers=headers, params=params, timeout=10)
                    results = resp.json().get("results", []) if resp.status_code == 200 else []

                if results:
                    chosen = results[0]
                    sound_id = chosen["id"]
                    previews = chosen.get("previews", {})
                    download_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
                    if not download_url:
                        continue

                    target_file = SFX_DIR / f"{slug}_{sound_id}.mp3"
                    print(f"      Downloading Freesound #{sound_id} ('{chosen.get('name', '')[:35]}') for '{attempt_query}'...")
                    audio_resp = requests.get(download_url, headers=headers, timeout=15)
                    if audio_resp.status_code == 200 and len(audio_resp.content) > 1024:
                        target_file.write_bytes(audio_resp.content)
                        print(f"      Saved SFX: {target_file.name}")
                        return target_file
            except Exception as e:
                print(f"      [Warning] Freesound lookup failed for '{attempt_query}': {e}")

        print(f"      [Warning] Freesound: No sounds found for queries: {queries_to_try}")
        return None


def detect_audio_transient_onset(data, sr):
    if len(data) == 0:
        return 0.0
    peak = np.max(np.abs(data)) + 1e-9
    norm_data = np.abs(data) / peak
    win = max(1, int(sr * 0.01))
    energy = np.convolve(norm_data ** 2, np.ones(win) / win, mode="same")
    max_e = np.max(energy)
    if max_e < 1e-4:
        return 0.0
    threshold = max_e * 0.08
    indices = np.where(energy >= threshold)[0]
    if len(indices) == 0:
        return 0.0
    return min(indices[0] / float(sr), 1.2)


def process_sfx_audio(raw_sfx_path, sound_type, max_duration_sec, output_path, target_sr, temp_dir=None):
    data, sr = load_audio_mono(raw_sfx_path, target_sr=target_sr, temp_dir=temp_dir)
    if data.size == 0:
        return np.zeros(0, dtype=np.float32), 0.0

    duration_sec = len(data) / float(sr)
    onset_sec = detect_audio_transient_onset(data, sr)

    if sound_type == "transient":
        if duration_sec > max_duration_sec + 0.8:
            target_samples = int((max_duration_sec + 0.6) * sr)
            data = data[:target_samples]
            fade = min(int(sr * 0.1), len(data) // 4)
            if fade > 0:
                data[-fade:] *= 0.5 * (1 + np.cos(np.linspace(0, np.pi, fade)))
    else:
        target_samples = int(max_duration_sec * sr)
        if len(data) > target_samples:
            data = data[:target_samples]
            fade = min(int(sr * 0.15), len(data) // 4)
            if fade > 0:
                data[-fade:] *= 0.5 * (1 + np.cos(np.linspace(0, np.pi, fade)))

    data = apply_cosine_fades(data, sr, fade_in_ms=5, fade_out_ms=25)
    save_wav(output_path, data, sr)
    return data, onset_sec


# def query_groq_sound_director(groq_client, groq_model, beat_id, visual_context, narration_text, words_timeline):
#     cache_sig = hashlib.md5(
#         json.dumps(
#             {
#                 "v": "groq_sfx_v1",
#                 "model": groq_model,
#                 "visual": visual_context,
#                 "text": narration_text,
#                 "words": len(words_timeline),
#                 "dur_ms": words_timeline[-1]["end_ms"] if words_timeline else 0,
#             },
#             ensure_ascii=False,
#         ).encode("utf-8")
#     ).hexdigest()
#     SFX_DIR.mkdir(parents=True, exist_ok=True)
#     cache_file = SFX_DIR / f"groq_{beat_id}_{cache_sig[:12]}.json"
#     if cache_file.exists():
#         try:
#             cached = json.loads(cache_file.read_text(encoding="utf-8"))
#             if cached.get("scene_analysis"):
#                 print(f"   Scene Foley Context (cached): {cached['scene_analysis']}")
#             return cached.get("sfx_cues", [])
#         except Exception:
#             pass

#     system_instruction = (
#         "You are a realistic Foley & Explainer Sound Editor. Your job is to select subtle, grounded sound effects "
#         "that accurately match the LITERAL objects, actions, or UI/whiteboard interactions happening in the narration.\n\n"
#         "STRICT REALISM & MATCHING RULES:\n"
#         "1. GROUND TO LITERAL OBJECTS/ACTIONS: If the scene mentions a bottle, glass, water, cup, book, door, keyboard, "
#         "whiteboard drawing, click, notification, or data transfer, choose sounds specifically matching those actions.\n"
#         "2. ABSOLUTELY NO UNPROMPTED DRAMATIC SFX: NEVER output 'car crash', 'explosion', 'gunshot', or 'cinematic hit' "
#         "unless a vehicle crash or weapon is explicitly mentioned in the text.\n"
#         "3. QUERY FORMAT FOR FREESOUND:\n"
#         "   - Use 2-3 precise natural English words describing the exact material/object and action.\n"
#         "   - Good story Foley: 'glass bottle clink', 'pouring water', 'footsteps wood', 'paper turn', 'door creak'\n"
#         "   - Good explainer/tech Foley: 'marker whiteboard draw', 'keyboard typing', 'mouse click', 'subtle UI pop', 'server hum'\n"
#         "   - Bad: 'smash', 'break', 'dramatic_impact_cinematic_boom'\n"
#         "4. DENSITY: Output between 0 and 2 tasteful cues. Keep volume subtle (0.25 to 0.55) so voiceover stays crystal clear. "
#         "If no distinct sound cue fits naturally, return an empty list [].\n\n"
#         "Return strictly a JSON object with this schema:\n"
#         "{\n"
#         '  "scene_analysis": "One sentence explaining physical/visual objects present",\n'
#         '  "sfx_cues": [\n'
#         "    {\n"
#         '      "freesound_tag": "glass bottle clink",\n'
#         '      "fallback_tag": "glass impact",\n'
#         '      "sound_type": "transient",\n'
#         '      "trigger_word": "word from the timeline",\n'
#         '      "target_ms": 1200,\n'
#         '      "duration_sec": 1.5,\n'
#         '      "volume": 0.45\n'
#         "    }\n"
#         "  ]\n"
#         "}"
#     )

#     user_content = f"""
# Beat ID: {beat_id}
# Visual Context: {visual_context if visual_context else 'Explainer / story scene'}
# Spoken Narration: {narration_text}

# Word-by-word Timestamps (ms):
# {json.dumps(words_timeline, ensure_ascii=False)}

# Identify literal physical materials, actions, or UI/whiteboard cues and select 0 to 2 matching sound cues.
# """

#     try:
#         completion = groq_client.chat.completions.create(
#             model=groq_model,
#             messages=[
#                 {"role": "system", "content": system_instruction},
#                 {"role": "user", "content": user_content},
#             ],
#             response_format={"type": "json_object"},
#             temperature=0.1,
#             max_tokens=600,
#         )
#         data = json.loads(completion.choices[0].message.content)
#         analysis = data.get("scene_analysis", "")
#         if analysis:
#             print(f"   Scene Foley Context: {analysis}")
#         cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
#         return data.get("sfx_cues", [])
#     except Exception as e:
#         print(f"   [Warning] Groq Sound Director error on {beat_id}: {e}")
#         return []
def _extract_json_object(raw_text):
    if not raw_text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def query_groq_sound_director(groq_client, groq_model, beat_id, visual_context, narration_text, words_timeline):
    cache_sig = hashlib.md5(
        json.dumps(
            {
                "v": "groq_sfx_v1",
                "model": groq_model,
                "visual": visual_context,
                "text": narration_text,
                "words": len(words_timeline),
                "dur_ms": words_timeline[-1]["end_ms"] if words_timeline else 0,
            },
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = SFX_DIR / f"groq_{beat_id}_{cache_sig[:12]}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("scene_analysis"):
                print(f"   Scene Foley Context (cached): {cached['scene_analysis']}")
            return cached.get("sfx_cues") or []
        except Exception:
            pass

    system_instruction = (
        "You are a realistic Foley & Explainer Sound Editor. Your job is to select subtle, grounded sound effects "
        "that accurately match the LITERAL objects, actions, or UI/whiteboard interactions happening in the narration.\n\n"
        "STRICT REALISM & MATCHING RULES:\n"
        "1. GROUND TO LITERAL OBJECTS/ACTIONS: If the scene mentions a bottle, glass, water, cup, book, door, keyboard, "
        "whiteboard drawing, click, notification, or data transfer, choose sounds specifically matching those actions.\n"
        "2. ABSOLUTELY NO UNPROMPTED DRAMATIC SFX: NEVER output 'car crash', 'explosion', 'gunshot', or 'cinematic hit' "
        "unless a vehicle crash or weapon is explicitly mentioned in the text.\n"
        "3. QUERY FORMAT FOR FREESOUND:\n"
        "   - Use 2-3 precise natural English words describing the exact material/object and action.\n"
        "   - Good story Foley: 'glass bottle clink', 'pouring water', 'footsteps wood', 'paper turn', 'door creak'\n"
        "   - Good explainer/tech Foley: 'marker whiteboard draw', 'keyboard typing', 'mouse click', 'subtle UI pop', 'server hum'\n"
        "   - Bad: 'smash', 'break', 'dramatic_impact_cinematic_boom'\n"
        "4. DENSITY: Output between 0 and 2 tasteful cues. Keep volume subtle (0.25 to 0.55) so voiceover stays crystal clear. "
        "If no distinct sound cue fits naturally, return an empty list [].\n\n"
        "Return strictly a valid JSON object (no markdown fences, no extra text) with this schema:\n"
        "{\n"
        '  "scene_analysis": "One sentence explaining physical/visual objects present",\n'
        '  "sfx_cues": [\n'
        "    {\n"
        '      "freesound_tag": "glass bottle clink",\n'
        '      "fallback_tag": "glass impact",\n'
        '      "sound_type": "transient",\n'
        '      "trigger_word": "word from the timeline",\n'
        '      "target_ms": 1200,\n'
        '      "duration_sec": 1.5,\n'
        '      "volume": 0.45\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_content = f"""
Beat ID: {beat_id}
Visual Context: {visual_context if visual_context else 'Explainer / story scene'}
Spoken Narration: {narration_text}

Word-by-word Timestamps (ms):
{json.dumps(words_timeline, ensure_ascii=False)}

Identify literal physical materials, actions, or UI/whiteboard cues and select 0 to 2 matching sound cues.
"""

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_content},
    ]

    extra_kwargs = {}
    if "gpt-oss" in groq_model.lower():
        extra_kwargs["reasoning_effort"] = "low"

    data = None
    last_err = None

    # Attempt 1: structured json_object mode with adequate token budget
    # Attempt 2: plain completion + local JSON extraction if Groq's JSON validator rejects
    for use_json_mode in (True, False):
        req_kwargs = {
            "model": groq_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2048,
            **extra_kwargs,
        }
        if use_json_mode:
            req_kwargs["response_format"] = {"type": "json_object"}

        try:
            completion = groq_client.chat.completions.create(**req_kwargs)
            raw_content = completion.choices[0].message.content or ""
            data = _extract_json_object(raw_content)
            if isinstance(data, dict):
                break
        except Exception as e:
            last_err = e
            # If reasoning_effort caused an unsupported-param 400 on a custom model, drop it for retry
            if "reasoning_effort" in str(e):
                extra_kwargs.pop("reasoning_effort", None)
            continue

    if not isinstance(data, dict):
        print(f"   [Warning] Groq Sound Director error on {beat_id}: {last_err}")
        return []

    analysis = data.get("scene_analysis", "")
    if analysis:
        print(f"   Scene Foley Context: {analysis}")
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return [c for c in (data.get("sfx_cues") or []) if isinstance(c, dict)]

def validate_sfx_dependencies():
    load_env_vars()
    missing_pkgs = []
    if Groq is None:
        missing_pkgs.append("groq")
    if requests is None:
        missing_pkgs.append("requests")
    if missing_pkgs:
        raise RuntimeError(
            f"Missing packages for SFX mode: {', '.join(missing_pkgs)}. "
            f"Install with: pip install {' '.join(missing_pkgs)} python-dotenv"
        )

    groq_key = os.getenv("GROQ_API_KEY")
    freesound_key = os.getenv("FREESOUND_API_KEY")
    if not groq_key:
        raise RuntimeError("GROQ_API_KEY is not set! Add it to .env or environment variables.")
    if not freesound_key:
        raise RuntimeError("FREESOUND_API_KEY is not set! Add it to .env or environment variables.")

    return Groq(api_key=groq_key), freesound_key, os.getenv("GROQ_MODEL", GROQ_MODEL_DEFAULT)


# def build_master_sfx_track(beat_audio_plans, total_samples, sample_rate, temp_dir):
#     groq_client, freesound_key, groq_model = validate_sfx_dependencies()
#     SFX_DIR.mkdir(parents=True, exist_ok=True)
#     PROCESSED_SFX_DIR.mkdir(parents=True, exist_ok=True)
#     TIMESTAMPS_DIR.mkdir(parents=True, exist_ok=True)

#     master_sfx = np.zeros(total_samples, dtype=np.float32)
#     total_attached = 0

#     print(f"\nDirecting Grounded Foley SFX (Groq: {groq_model} + Freesound API)...")
#     for plan in beat_audio_plans:
#         beat = plan["beat"]
#         beat_id = beat.get("beat_id", f"B{plan['beat_index']:04d}")
#         visual_context = get_beat_visual_context(beat)
#         spoken_text = plan["spoken_source"]

#         ts_file = TIMESTAMPS_DIR / f"{beat_id}_words.json"
#         words_timeline = align_ground_truth_to_samples(
#             data=plan["speech_samples"],
#             sr=plan["sample_rate"],
#             ground_truth_text=spoken_text,
#             output_json=ts_file,
#         )

#         sfx_cues = query_groq_sound_director(
#             groq_client=groq_client,
#             groq_model=groq_model,
#             beat_id=beat_id,
#             visual_context=visual_context,
#             narration_text=spoken_text,
#             words_timeline=words_timeline,
#         )
#         if not sfx_cues:
#             continue

#         print(f"   [{beat_id}] Foley cues chosen: {len(sfx_cues)}")
#         for sfx_idx, cue in enumerate(sfx_cues):
#             tag = cue.get("freesound_tag", "")
#             fallback = cue.get("fallback_tag", "")
#             sound_type = cue.get("sound_type", "transient")
#             target_ms = float(cue.get("target_ms", 0))
#             duration_sec = min(SFX_MAX_DUR, max(SFX_MIN_DUR, float(cue.get("duration_sec", 2.0))))
#             volume = float(np.clip(float(cue.get("volume", 0.45)), 0.05, 0.85))

#             raw_sfx = FreesoundAudioAPI.search_and_download(tag, fallback, api_key=freesound_key)
#             if not raw_sfx:
#                 continue

#             processed_sfx_path = PROCESSED_SFX_DIR / f"{beat_id}_sfx_{sfx_idx}.wav"
#             sfx_samples, onset_sec = process_sfx_audio(
#                 raw_sfx_path=raw_sfx,
#                 sound_type=sound_type,
#                 max_duration_sec=duration_sec,
#                 output_path=processed_sfx_path,
#                 target_sr=sample_rate,
#                 temp_dir=temp_dir,
#             )
#             if sfx_samples.size == 0:
#                 continue

#             target_impact_time = plan["beat_start_s"] + (target_ms / 1000.0)
#             sfx_start_time = max(0.0, target_impact_time - onset_sec)
#             start_idx = int(round(sfx_start_time * sample_rate))
#             if start_idx >= total_samples:
#                 continue

#             end_idx = min(total_samples, start_idx + sfx_samples.size)
#             copy_len = end_idx - start_idx
#             if copy_len > 0:
#                 master_sfx[start_idx:end_idx] += sfx_samples[:copy_len] * volume
#                 total_attached += 1
#                 print(
#                     f"      Attached '{tag}' @ {sfx_start_time:.2f}s "
#                     f"(onset: -{onset_sec * 1000:.0f}ms, vol={volume:.2f})"
#                 )

#     if total_attached == 0:
#         print("No SFX attached; continuing with voiceover only.")
#         return None

#     # Soft-limit any overlapping SFX peaks before final FFmpeg mux
#     peak = float(np.max(np.abs(master_sfx)))
#     if peak > 0.92:
#         master_sfx = (np.tanh(master_sfx * 0.95) / np.tanh(0.95) * 0.92).astype(np.float32)

#     master_sfx_path = Path(temp_dir) / "master_sfx.wav"
#     save_wav(master_sfx_path, master_sfx, sample_rate)
#     print(f"Mixed {total_attached} SFX cues into {master_sfx_path.name}.")
#     return master_sfx_path

def build_master_sfx_track(beat_audio_plans, total_samples, sample_rate, temp_dir):
    groq_client, freesound_key, groq_model = validate_sfx_dependencies()
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_SFX_DIR.mkdir(parents=True, exist_ok=True)
    TIMESTAMPS_DIR.mkdir(parents=True, exist_ok=True)

    master_sfx = np.zeros(total_samples, dtype=np.float32)
    total_attached = 0

    def _safe_float(val, default):
        if val is None or val == "":
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    print(f"\nDirecting Grounded Foley SFX (Groq: {groq_model} + Freesound API)...")
    for plan in beat_audio_plans:
        beat = plan["beat"]
        beat_id = beat.get("beat_id", f"B{plan['beat_index']:04d}")
        visual_context = get_beat_visual_context(beat)
        spoken_text = plan["spoken_source"]

        ts_file = TIMESTAMPS_DIR / f"{beat_id}_words.json"
        words_timeline = align_ground_truth_to_samples(
            data=plan["speech_samples"],
            sr=plan["sample_rate"],
            ground_truth_text=spoken_text,
            output_json=ts_file,
        )

        sfx_cues = query_groq_sound_director(
            groq_client=groq_client,
            groq_model=groq_model,
            beat_id=beat_id,
            visual_context=visual_context,
            narration_text=spoken_text,
            words_timeline=words_timeline,
        )
        if not sfx_cues:
            continue

        print(f"   [{beat_id}] Foley cues chosen: {len(sfx_cues)}")
        max_beat_ms = plan["frame_dur"] * 1000.0

        for sfx_idx, cue in enumerate(sfx_cues):
            if not isinstance(cue, dict):
                continue

            tag = str(cue.get("freesound_tag") or "").strip()
            fallback = str(cue.get("fallback_tag") or "").strip()
            if not tag and not fallback:
                continue

            sound_type = str(cue.get("sound_type") or "transient").strip().lower()
            if sound_type not in ("transient", "ambient", "continuous"):
                sound_type = "transient"

            target_ms = min(max_beat_ms, max(0.0, _safe_float(cue.get("target_ms"), 0.0)))
            duration_sec = min(SFX_MAX_DUR, max(SFX_MIN_DUR, _safe_float(cue.get("duration_sec"), 2.0)))
            volume = float(np.clip(_safe_float(cue.get("volume"), 0.45), 0.05, 0.85))

            raw_sfx = FreesoundAudioAPI.search_and_download(tag, fallback, api_key=freesound_key)
            if not raw_sfx:
                continue

            processed_sfx_path = PROCESSED_SFX_DIR / f"{beat_id}_sfx_{sfx_idx}.wav"
            sfx_samples, onset_sec = process_sfx_audio(
                raw_sfx_path=raw_sfx,
                sound_type=sound_type,
                max_duration_sec=duration_sec,
                output_path=processed_sfx_path,
                target_sr=sample_rate,
                temp_dir=temp_dir,
            )
            if sfx_samples.size == 0:
                continue

            target_impact_time = plan["beat_start_s"] + (target_ms / 1000.0)
            sfx_start_time = max(0.0, target_impact_time - onset_sec)
            start_idx = int(round(sfx_start_time * sample_rate))
            if start_idx >= total_samples:
                continue

            end_idx = min(total_samples, start_idx + sfx_samples.size)
            copy_len = end_idx - start_idx
            if copy_len > 0:
                master_sfx[start_idx:end_idx] += sfx_samples[:copy_len] * volume
                total_attached += 1
                print(
                    f"      Attached '{tag or fallback}' @ {sfx_start_time:.2f}s "
                    f"(onset: -{onset_sec * 1000:.0f}ms, vol={volume:.2f})"
                )

    if total_attached == 0:
        print("No SFX attached; continuing with voiceover only.")
        return None

    # Soft-limit any overlapping SFX peaks before final FFmpeg mux
    peak = float(np.max(np.abs(master_sfx)))
    if peak > 0.92:
        master_sfx = (np.tanh(master_sfx * 0.95) / np.tanh(0.95) * 0.92).astype(np.float32)

    master_sfx_path = Path(temp_dir) / "master_sfx.wav"
    save_wav(master_sfx_path, master_sfx, sample_rate)
    print(f"Mixed {total_attached} SFX cues into {master_sfx_path.name}.")
    return master_sfx_path


# ============================================================
# RDR2-STYLE SUBTITLES (ENGLISH & HINDI DEVANAGARI SUPPORT)
# ============================================================

def split_text_into_cues(text, max_chars=74):
    text = " ".join(text.strip().split())
    if not text:
        return []

    cues = []
    for sentence in re.split(r"(?<=[।.!?])\s+", text):
        current, current_len = [], 0
        for word in sentence.split():
            added = len(word) + (1 if current else 0)
            if current and current_len + added > max_chars:
                cues.append(" ".join(current))
                current, current_len = [word], len(word)
            else:
                current.append(word)
                current_len += added

            if word.endswith(",") and current_len >= max_chars * 0.55:
                cues.append(" ".join(current))
                current, current_len = [], 0
        if current:
            cues.append(" ".join(current))
    return cues


def build_timed_subtitle_cues(sub_text, total_duration, max_chars_cue=74):
    chunks = split_text_into_cues(sub_text, max_chars=max_chars_cue)
    if not chunks:
        return []

    weights = [
        max(
            sum(1 for c in ch if not c.isspace() and c not in "।.,!?;:")
            + sum(2.5 if c in "।.!?" else 1.2 for c in ch if c in "।.,!?;:"),
            1.0
        )
        for ch in chunks
    ]
    total_w = sum(weights)
    timed, cursor = [], 0.0

    for idx, (chunk, w) in enumerate(zip(chunks, weights)):
        end_t = total_duration if idx == len(chunks) - 1 else min(total_duration, cursor + total_duration * (w / total_w))
        timed.append((cursor, end_t, chunk))
        cursor = end_t
    return timed


def wrap_subtitle_lines(text, max_line_chars=48):
    lines, current, current_len = [], [], 0
    for word in text.split():
        added = len(word) + (1 if current else 0)
        if current and current_len + added > max_line_chars:
            lines.append(" ".join(current))
            current, current_len = [word], len(word)
        else:
            current.append(word)
            current_len += added
    if current:
        lines.append(" ".join(current))

    if len(lines) == 2 and len(lines[1]) < len(lines[0]) * 0.35:
        words = text.split()
        mid = len(words) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    return lines[:3]


def find_subtitle_font(size, prefer_devanagari=False):
    if prefer_devanagari:
        font_paths = [
            "C:/Windows/Fonts/Nirmala.ttc",
            "C:/Windows/Fonts/NirmalaS.ttf",
            "C:/Windows/Fonts/mangal.ttf",
            "C:/Windows/Fonts/aparaj.ttf",
            "C:/Windows/Fonts/kokila.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Regular.ttf",
            "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/System/Library/Fonts/Kohinoor.ttc",
            "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
        ]
    else:
        font_paths = [
            "C:/Windows/Fonts/georgia.ttf",
            "C:/Windows/Fonts/times.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    for path in font_paths:
        if Path(path).exists():
            try:
                if prefer_devanagari and pil_features is not None and pil_features.check("raqm"):
                    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def can_pillow_shape_text(text):
    if Image is None:
        return False
    if has_devanagari(text):
        return bool(pil_features is not None and pil_features.check("raqm"))
    return True


def render_rdr2_subtitle_png(text, output_path, profile, seed_value=0):
    font_size = profile["sub_font_size"]
    font = find_subtitle_font(font_size, prefer_devanagari=has_devanagari(text))
    lines = wrap_subtitle_lines(text, max_line_chars=profile["sub_max_chars_line"])

    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
    line_sizes = [(b[2] - b[0], b[3] - b[1]) for b in (probe.textbbox((0, 0), ln, font=font) for ln in lines)]

    text_w = max(w for w, _ in line_sizes)
    line_h = max(h for _, h in line_sizes)
    line_gap = max(6, int(font_size * 0.28))
    text_h = line_h * len(lines) + line_gap * max(0, len(lines) - 1)

    pad_x, pad_y, sketch_margin = 40, 14, 22
    box_w, box_h = text_w + pad_x * 2, text_h + pad_y * 2
    img_w, img_h = box_w + sketch_margin * 2, box_h + 12

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rng = random.Random(seed_value)

    x0, x1 = sketch_margin, sketch_margin + box_w
    y0, y1 = 6, 6 + box_h

    pts = []
    for x in range(x0, x1, 18):
        pts.append((x, y0 + rng.randint(-1, 1)))
    pts.append((x1, y0 + rng.randint(-1, 1)))

    for y in range(y0 + 3, y1, 3):
        taper = math.sin(((y - y0) / max(1, y1 - y0)) * math.pi)
        pts.append((int(x1 + rng.randint(-6, 12) * (0.45 + 0.55 * taper)), y))

    for x in range(x1, x0, -18):
        pts.append((x, y1 + rng.randint(-1, 1)))
    pts.append((x0, y1 + rng.randint(-1, 1)))

    for y in range(y1 - 3, y0, -3):
        taper = math.sin(((y - y0) / max(1, y1 - y0)) * math.pi)
        pts.append((int(x0 + rng.randint(-12, 6) * (0.45 + 0.55 * taper)), y))

    draw.polygon(pts, fill=(8, 8, 8, 218))

    for _ in range(10):
        sy_l = rng.randint(y0 + 3, y1 - 3)
        draw.line(
            [(x0 + rng.randint(-18, 4), sy_l), (x0 + rng.randint(8, 26), sy_l + rng.randint(-1, 1))],
            fill=(8, 8, 8, rng.randint(110, 195)), width=rng.randint(1, 3)
        )
        sy_r = rng.randint(y0 + 3, y1 - 3)
        draw.line(
            [(x1 - rng.randint(8, 26), sy_r), (x1 + rng.randint(-4, 18), sy_r + rng.randint(-1, 1))],
            fill=(8, 8, 8, rng.randint(110, 195)), width=rng.randint(1, 3)
        )

    curr_y = y0 + pad_y - 2
    for line, (lw, _) in zip(lines, line_sizes):
        lx = (img_w - lw) // 2
        draw.text((lx + 1, curr_y + 2), line, font=font, fill=(0, 0, 0, 235))
        draw.text((lx, curr_y), line, font=font, fill=(246, 245, 240, 255))
        curr_y += line_h + line_gap

    max_allowed_w = profile["width"] - 32
    if img.width > max_allowed_w:
        scale = max_allowed_w / img.width
        img = img.resize((max_allowed_w, max(1, int(img.height * scale))), Image.Resampling.LANCZOS)

    img.save(str(output_path), "PNG")
    return output_path


def write_fallback_ass(timed_cues, ass_path, profile, is_hindi=False):
    def fmt(sec):
        cs = max(0, int(round(sec * 100)))
        s, cs = divmod(cs, 100)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    font_name = "Nirmala UI" if is_hindi else "Georgia"
    lines = [
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {profile['width']}\nPlayResY: {profile['height']}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{profile['sub_font_size']},&H00F5F5F5,&H000000FF,&H26080808,"
        f"&H26080808,0,0,0,0,100,100,0,0,3,14,0,2,60,60,{profile['sub_bottom_margin']},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    ]
    for st, et, txt in timed_cues:
        wrapped = "\\N".join(wrap_subtitle_lines(txt, max_line_chars=profile["sub_max_chars_line"]))
        lines.append(f"Dialogue: 0,{fmt(st)},{fmt(et)},Default,,0,0,0,,{wrapped}\n")
    ass_path.write_text("".join(lines), encoding="utf-8")
    return ass_path


# ============================================================
# IMAGE-TO-VIDEO PROCESSING (FRAME-EXACT)
# ============================================================

def render_image_clip_bg(image_path, num_frames, output_path, profile, motion_index=0):
    width = profile["width"]
    height = profile["height"]
    zoom = max(1.0, float(VIDEO_ZOOM))
    zoom_w = ((int(round(width * zoom)) + 1) // 2) * 2
    zoom_h = ((int(round(height * zoom)) + 1) // 2) * 2
    dur = max(1 / FPS, num_frames / FPS)

    mode = motion_index % 4
    if mode == 0:
        x_expr = f"(iw-ow)*t/{dur:.6f}"
        y_expr = "(ih-oh)/2"
    elif mode == 1:
        x_expr = f"(iw-ow)*(1-t/{dur:.6f})"
        y_expr = "(ih-oh)/2"
    elif mode == 2:
        x_expr = "(iw-ow)/2"
        y_expr = f"(ih-oh)*t/{dur:.6f}"
    else:
        x_expr = "(iw-ow)/2"
        y_expr = f"(ih-oh)*(1-t/{dur:.6f})"

    vf = (
        f"scale={zoom_w}:{zoom_h}:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop={width}:{height}:x='{x_expr}':y='{y_expr}',"
        f"setsar=1,fps={FPS},setpts=PTS-STARTPTS"
    )

    command = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(image_path),
        "-an",
        "-vf", vf,
        "-frames:v", str(num_frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    run_cmd(command)
    return output_path


def overlay_beat_subtitles(beat_video_path, num_frames, timed_cues, beat_dir, beat_id, output_path, profile):
    if not timed_cues:
        shutil.copy2(beat_video_path, output_path)
        return output_path

    command = ["ffmpeg", "-y", "-i", str(beat_video_path)]
    filter_parts = [f"[0:v]fps={FPS},setpts=PTS-STARTPTS[v0]"]
    last_v = "v0"

    joined_sub = " ".join(txt for _, _, txt in timed_cues)
    if can_pillow_shape_text(joined_sub):
        for idx, (st, et, txt) in enumerate(timed_cues):
            png_path = beat_dir / f"{beat_id}_sub_{idx:03d}.png"
            seed = int(hashlib.md5(f"{beat_id}_{idx}_{txt}".encode("utf-8")).hexdigest()[:8], 16)
            render_rdr2_subtitle_png(txt, png_path, profile=profile, seed_value=seed)
            command.extend(["-i", str(png_path)])
            next_v = f"v{idx + 1}"
            cond = (
                f"between(t,{st:.3f},{et:.3f})"
                if idx == len(timed_cues) - 1
                else f"gte(t,{st:.3f})*lt(t,{et:.3f})"
            )
            filter_parts.append(
                f"[{last_v}][{idx + 1}:v]overlay=(W-w)/2:H-h-{profile['sub_bottom_margin']}:"
                f"enable='{cond}'[{next_v}]"
            )
            last_v = next_v
    else:
        ass_path = write_fallback_ass(
            timed_cues, beat_dir / f"{beat_id}_sub.ass", profile=profile, is_hindi=has_devanagari(joined_sub)
        )
        escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        filter_parts.append(f"[{last_v}]ass='{escaped}'[v_sub]")
        last_v = "v_sub"

    command.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{last_v}]",
        "-an",
        "-frames:v", str(num_frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        str(output_path)
    ])
    run_cmd(command)
    return output_path


def concat_video_only(segment_files, output_file, temp_dir):
    output_file = Path(output_file)
    concat_file = Path(temp_dir) / f"{output_file.stem}.concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for seg in segment_files:
            safe = str(seg.resolve()).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    run_cmd([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:v", "copy", "-an", str(output_file)
    ])
    return output_file


def mux_final_video(master_video_path, master_audio_path, output_file, sfx_audio_path=None, bgm_path=None):
    output_file = Path(output_file)
    command = [
        "ffmpeg", "-y",
        "-i", str(master_video_path),
        "-i", str(master_audio_path),
    ]

    next_idx = 2
    filter_parts = [
        "[1:a]aresample=44100,"
        "highpass=f=75,"
        "acompressor=threshold=-18dB:ratio=2.0:attack=15:release=180:makeup=1.4,"
        f"volume={VOICE_VOLUME}[v_pre]"
    ]

    has_sfx = sfx_audio_path is not None and Path(sfx_audio_path).exists()
    has_bgm = bgm_path is not None and Path(bgm_path).exists()

    if has_bgm:
        filter_parts.append("[v_pre]asplit=2[v_mix][v_sc]")
        voice_label = "[v_mix]"
    else:
        voice_label = "[v_pre]"

    mix_inputs = [voice_label]

    if has_sfx:
        command.extend(["-i", str(sfx_audio_path)])
        filter_parts.append(f"[{next_idx}:a]aresample=44100,volume={SFX_MASTER_VOLUME}[sfx]")
        mix_inputs.append("[sfx]")
        next_idx += 1

    if has_bgm:
        command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        filter_parts.append(f"[{next_idx}:a]aresample=44100,volume={BGM_VOLUME}[bgm_raw]")
        filter_parts.append("[bgm_raw][v_sc]sidechaincompress=threshold=0.02:ratio=2.8:attack=90:release=480[bgm]")
        mix_inputs.append("[bgm]")
        next_idx += 1

    if len(mix_inputs) == 1:
        filter_parts.append(f"{voice_label}alimiter=limit=0.95[aout]")
    else:
        filter_parts.append(
            f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2:normalize=0,"
            "alimiter=limit=0.95[aout]"
        )

    command.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        str(output_file),
    ])
    run_cmd(command)
    return output_file


# ============================================================
# BEAT & CLIP-SEGMENT ASSEMBLY PIPELINE
# ============================================================

def compute_clip_target_frames(
    clips, speech_samples, sr, speech_dur, total_beat_frames, narration_lang="en"
):
    speech_frames = max(len(clips), min(total_beat_frames, int(round(speech_dur * FPS))))
    pause_frames = max(0, total_beat_frames - speech_frames)
    if len(clips) == 1:
        return [total_beat_frames]

    weights = []
    for clip in clips:
        if narration_lang == "en":
            en_txt = (clip.get("spoken_text_en") or clip.get("english_text") or "").strip()
            if not en_txt and clip.get("spoken_text", "").strip():
                en_txt = ensure_english_text(clip["spoken_text"].strip())
            if en_txt:
                weights.append(estimate_spoken_weight(en_txt))
                continue

        txt = clip.get("spoken_text", "").strip()
        if txt:
            weights.append(estimate_spoken_weight(txt))
        elif clip.get("estimated_spoken_duration"):
            weights.append(max(float(clip["estimated_spoken_duration"]), 0.5))
        elif "start" in clip and "end" in clip:
            weights.append(max(float(clip["end"]) - float(clip["start"]), 0.5))
        else:
            weights.append(1.0)

    total_w = sum(weights)
    expected_cuts_s = []
    cum_w = 0.0
    for w in weights[:-1]:
        cum_w += w
        expected_cuts_s.append(speech_dur * (cum_w / total_w))

    pauses, _, _ = find_quiet_pauses(speech_samples, sr, min_pause_s=0.045)
    pause_times = [mid / sr for mid, _ in pauses]

    snapped_cuts_s = []
    prev_t = 0.0
    for idx, exp_t in enumerate(expected_cuts_s):
        remaining = len(expected_cuts_s) - idx
        min_t = prev_t + 0.30
        max_t = speech_dur - remaining * 0.30
        best_t = min(max(exp_t, min_t), max_t)

        nearby = [pt for pt in pause_times if min_t <= pt <= max_t and abs(pt - exp_t) <= 0.45]
        if nearby:
            best_t = min(nearby, key=lambda pt: abs(pt - exp_t))

        snapped_cuts_s.append(best_t)
        prev_t = best_t

    cut_frames = [int(round(t * FPS)) for t in snapped_cuts_s]
    frames_list = []
    prev_f = 0
    for idx, cf in enumerate(cut_frames):
        remaining = len(clips) - idx - 1
        cf = max(prev_f + 3, min(cf, speech_frames - remaining * 3))
        frames_list.append(cf - prev_f)
        prev_f = cf
    frames_list.append(max(1, speech_frames - prev_f) + pause_frames)

    diff = total_beat_frames - sum(frames_list)
    frames_list[-1] = max(1, frames_list[-1] + diff)
    return frames_list


def render_beat_video(plan, frames_dir, temp_dir, profile, motion_counter, narration_lang, subtitle_mode):
    beat_index = plan["beat_index"]
    beat = plan["beat"]
    raw_narration = plan["raw_narration"]
    subtitle_text = plan["subtitle_text"]
    speech_dur = plan["speech_dur"]
    total_frames = plan["num_frames"]

    beat_id = beat.get("beat_id", f"B{beat_index:04d}")
    clips = beat.get("clips") or [{"clip_id": f"{beat_id}_C0001", "spoken_text": raw_narration}]

    preview_txt = raw_narration if narration_lang == "hi" else (subtitle_text or raw_narration)
    print(f"\n[{beat_id}] ({speech_dur:.2f}s speech / {total_frames / FPS:.2f}s total) {preview_txt}")
    beat_dir = temp_dir / beat_id
    beat_dir.mkdir(parents=True, exist_ok=True)

    if subtitle_mode == "none" or not subtitle_text:
        timed_cues = []
        print(f"      Clips: {len(clips)} | Sub: (none)")
    else:
        timed_cues = build_timed_subtitle_cues(
            subtitle_text, speech_dur, max_chars_cue=profile["sub_max_chars_cue"]
        )
        print(f"      Clips: {len(clips)} | Sub ({subtitle_mode}): {subtitle_text[:70]}...")

    clip_frames_list = compute_clip_target_frames(
        clips,
        plan["speech_samples"],
        plan["sample_rate"],
        speech_dur,
        total_frames,
        narration_lang=narration_lang,
    )

    clip_segments = []
    for idx, (clip, n_frames) in enumerate(zip(clips, clip_frames_list), start=1):
        clip_id = clip.get("clip_id", f"{beat_id}_C{idx:04d}")
        img_path = resolve_clip_image(clip, beat_id, clip_id, frames_dir)
        bg_path = beat_dir / f"{clip_id}_bg.mp4"
        render_image_clip_bg(
            img_path, n_frames, bg_path,
            profile=profile,
            motion_index=motion_counter + idx - 1
        )
        clip_segments.append(bg_path)

    beat_video = beat_dir / f"{beat_id}_video.mp4"
    concat_video_only(clip_segments, beat_video, temp_dir=beat_dir)

    beat_output = beat_dir / f"{beat_id}_sub.mp4"
    overlay_beat_subtitles(
        beat_video, total_frames, timed_cues, beat_dir, beat_id, beat_output, profile=profile
    )
    return beat_output, motion_counter + len(clips)


def normalize_lang_arg(val):
    v = val.strip().lower()
    if v in ("hi", "hindi"):
        return "hi"
    if v in ("en", "eng", "english"):
        return "en"
    raise ValueError(f"Unsupported language '{val}'. Choose 'hi' or 'en'.")


def normalize_subtitle_arg(val):
    v = val.strip().lower()
    if v in ("en", "eng", "english"):
        return "en"
    if v in ("hi", "hindi"):
        return "hi"
    if v in ("none", "no", "off", "false", "0"):
        return "none"
    raise ValueError(f"Unsupported subtitle option '{val}'. Choose 'en', 'hi', or 'none'.")


def _ask_choice(prompt_text, mapping, default_val):
    while True:
        raw = input(prompt_text).strip().lower()
        if not raw:
            return default_val
        if raw in mapping:
            return mapping[raw]
        print(f"   Invalid choice '{raw}'. Valid options: {', '.join(sorted(mapping.keys()))}")


def resolve_interactive_options(args, detected_script_lang):
    can_prompt = sys.stdin.isatty() and not args.yes

    lang = normalize_lang_arg(args.lang) if args.lang is not None else None
    accent = args.accent
    gender = args.gender
    voice = args.voice
    subtitle_mode = normalize_subtitle_arg(args.subtitle) if args.subtitle is not None else None
    use_sfx = args.sfx

    default_lang = detected_script_lang
    default_accent = "hindi" if default_lang == "hi" else "us"

    if can_prompt and (
        lang is None or subtitle_mode is None or use_sfx is None
        or (voice is None and (accent is None or gender is None))
    ):
        detected_label = "Hindi" if detected_script_lang == "hi" else "English"
        print("\n=== Audio, Subtitle & SFX Setup ===")
        print(f"Detected script narration: {detected_label}")

    if lang is None:
        if can_prompt:
            def_num = "1" if default_lang == "en" else "2"
            print("\n1) Audio Language (Script reading / TTS mode):")
            print("   [1] English")
            print("   [2] Hindi")
            lang = _ask_choice(
                f"   Choose language [1/2, default={def_num}]: ",
                {"1": "en", "en": "en", "eng": "en", "english": "en", "2": "hi", "hi": "hi", "hindi": "hi"},
                default_lang,
            )
        else:
            lang = default_lang

    if accent is None:
        if can_prompt and voice is None:
            def_acc = "2" if lang == "hi" else "1"
            print("\n2) Voice Accent:")
            print("   [1] US Accent (American)")
            print("   [2] Hindi / Indian Accent")
            print("   [3] UK Accent (British)")
            accent = _ask_choice(
                f"   Choose accent [1/2/3, default={def_acc}]: ",
                {
                    "1": "us", "us": "us", "american": "us",
                    "2": "hindi", "hi": "hindi", "hindi": "hindi", "indian": "hindi",
                    "3": "uk", "uk": "uk", "british": "uk",
                },
                "hindi" if lang == "hi" else "us",
            )
        else:
            accent = "hindi" if lang == "hi" else default_accent

    if gender is None:
        if can_prompt and voice is None:
            print("\n3) Narrator Gender:")
            print("   [1] Female")
            print("   [2] Male")
            gender = _ask_choice(
                "   Choose gender [1/2, default=1]: ",
                {"1": "female", "f": "female", "female": "female", "2": "male", "m": "male", "male": "male"},
                DEFAULT_GENDER,
            )
        else:
            gender = DEFAULT_GENDER

    if voice is None and can_prompt:
        voice_choices = get_voices_for_profile(accent, gender)
        if len(voice_choices) > 1:
            print(f"\n4) Voice ({accent.upper()} / {gender.capitalize()}):")
            mapping = {}
            for i, v in enumerate(voice_choices[:6], start=1):
                tag = " (default)" if i == 1 else ""
                print(f"   [{i}] {v}{tag}")
                mapping[str(i)] = v
                mapping[v.lower()] = v
            voice = _ask_choice(
                f"   Choose voice [1-{min(6, len(voice_choices))}, default=1]: ",
                mapping,
                voice_choices[0],
            )
        elif voice_choices:
            voice = voice_choices[0]

    if subtitle_mode is None:
        if can_prompt:
            def_sub = "1" if detected_script_lang == "en" else "2"
            print("\n5) Subtitles:")
            print("   [1] English (if Hindi script & translation fails, falls back to Hindi)")
            print("   [2] Hindi")
            print("   [3] None (No subtitles)")
            subtitle_mode = _ask_choice(
                f"   Choose subtitles [1/2/3, default={def_sub}]: ",
                {
                    "1": "en", "en": "en", "eng": "en", "english": "en",
                    "2": "hi", "hi": "hi", "hindi": "hi",
                    "3": "none", "none": "none", "no": "none", "off": "none",
                },
                detected_script_lang,
            )
        else:
            subtitle_mode = detected_script_lang

    if use_sfx is None:
        if can_prompt:
            print("\n6) Sound Effects (Groq AI Director + Freesound API):")
            print("   [1] No (Voice + optional BGM only)")
            print("   [2] Yes (Add grounded Foley/SFX via Groq + Freesound)")
            use_sfx = _ask_choice(
                "   Add sound effects? [1/2, default=1]: ",
                {"1": False, "n": False, "no": False, "false": False, "2": True, "y": True, "yes": True, "true": True},
                False,
            )
        else:
            use_sfx = False

    return lang, gender, accent, voice, subtitle_mode, use_sfx


def run_assembly(
    json_path,
    frames_dir=None,
    output_path=None,
    aspect_ratio="auto",
    bgm_path=None,
    lang=None,
    gender=None,
    accent=None,
    voice=None,
    subtitle=None,
    sfx=None,
    speed=TTS_SPEED,
    yes=False,
    no_cache=False,
):
    check_dependencies()
    load_env_vars()

    json_path = Path(json_path).resolve()
    if not json_path.exists():
        raise FileNotFoundError(f"Story JSON not found: {json_path}")

    frames_dir = Path(frames_dir).resolve() if frames_dir else DEFAULT_FRAMES_DIR
    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames folder not found: {frames_dir}")

    story_data = load_story_json(json_path)
    beats = extract_beats(story_data)
    if not beats:
        raise ValueError("No beats found in story JSON.")

    detected_script_lang = detect_script_language(beats)
    get_kokoro()

    dummy_args = argparse.Namespace(
        lang=lang, gender=gender, accent=accent, voice=voice, subtitle=subtitle, sfx=sfx, yes=yes
    )
    narration_lang, chosen_gender, chosen_accent, chosen_voice, subtitle_mode, use_sfx = resolve_interactive_options(
        dummy_args, detected_script_lang=detected_script_lang
    )

    if use_sfx:
        validate_sfx_dependencies()

    if aspect_ratio == "auto":
        meta_ar = story_data.get("aspect_ratio") or story_data.get("project_meta", {}).get("aspect_ratio")
        if meta_ar in ("9:16", "16:9"):
            aspect_ratio = meta_ar
        else:
            first_beat = beats[0]
            first_bid = first_beat.get("beat_id", "B0001")
            first_clips = first_beat.get("clips") or [{"clip_id": f"{first_bid}_C0001"}]
            first_cid = first_clips[0].get("clip_id", f"{first_bid}_C0001")
            first_img = resolve_clip_image(first_clips[0], first_bid, first_cid, frames_dir)
            aspect_ratio = detect_aspect_ratio_from_image(first_img)

    profile = get_render_profile(aspect_ratio)

    title = (
        story_data.get("movie_title")
        or story_data.get("title")
        or story_data.get("project_meta", {}).get("title")
        or json_path.stem
    )
    safe_title = sanitize_filename(title)
    final_output = Path(output_path).resolve() if output_path else BASE_DIR / f"{safe_title}_explained.mp4"
    final_output.parent.mkdir(parents=True, exist_ok=True)

    temp_dir = BASE_DIR / f".assembly_temp_{safe_title}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        selected_voice, tts_lang = resolve_voice_and_tts_lang(
            narration_lang=narration_lang,
            gender=chosen_gender,
            accent=chosen_accent,
            explicit_voice=chosen_voice,
        )

        print(
            f"\nTitle: {title} | Beats: {len(beats)} | Aspect: {aspect_ratio} ({profile['width']}x{profile['height']}) "
            f"| Audio: {narration_lang.upper()} ({chosen_gender}, {chosen_accent} accent -> {selected_voice}, {tts_lang}) @ {speed}x "
            f"| Subtitles: {subtitle_mode.upper()} | SFX: {'Groq+Freesound' if use_sfx else 'OFF'} "
            f"| Output: {final_output.name}"
        )
        if subtitle_mode != "none" and Image is None:
            print("[Note] Install Pillow (`pip install pillow`) for RDR2-style sketchy subtitles.")

        beat_audio_plans, master_wav_path, total_samples, master_sr = prepare_all_beats_audio(
            beats,
            temp_dir=temp_dir,
            narration_lang=narration_lang,
            subtitle_mode=subtitle_mode,
            voice=selected_voice,
            tts_lang=tts_lang,
            speed=speed,
            use_cache=not no_cache,
        )

        sfx_wav_path = None
        if use_sfx:
            sfx_wav_path = build_master_sfx_track(
                beat_audio_plans,
                total_samples=total_samples,
                sample_rate=master_sr,
                temp_dir=temp_dir,
            )

        beat_video_outputs, motion_counter = [], 0
        for plan in beat_audio_plans:
            out_vid, motion_counter = render_beat_video(
                plan,
                frames_dir,
                temp_dir,
                profile,
                motion_counter,
                narration_lang=narration_lang,
                subtitle_mode=subtitle_mode,
            )
            beat_video_outputs.append(out_vid)

        print("\nAssembling master video + continuous audio...")
        master_video_path = temp_dir / "master_video.mp4"
        concat_video_only(beat_video_outputs, master_video_path, temp_dir=temp_dir)
        mux_final_video(
            master_video_path,
            master_wav_path,
            final_output,
            sfx_audio_path=sfx_wav_path,
            bgm_path=bgm_path,
        )

        actual_total = get_duration(final_output)
        print(f"Done: {final_output} ({actual_total:.2f}s / {actual_total / 60:.2f} min)")
        return str(final_output)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assemble explainer video from generated images + beat/clip JSON with fluent Kokoro TTS, subtitles, and optional Groq+Freesound SFX."
    )
    parser.add_argument("json_path", help="Path to story JSON (with beats[] and clips[])")
    parser.add_argument("-f", "--frames-dir", default=None, help="Directory with generated images (default: build/frames)")
    parser.add_argument("-o", "--output", default=None, help="Optional output MP4 path")
    parser.add_argument("-a", "--aspect-ratio", choices=["auto", "9:16", "16:9"], default="auto", help="Target aspect ratio")
    parser.add_argument("-b", "--bgm", default=None, help="Optional background music audio file (looped softly)")
    parser.add_argument("-l", "--lang", choices=["hi", "en", "hindi", "english"], default=None, help="Audio language (prompted if omitted)")
    parser.add_argument("-g", "--gender", choices=["female", "male"], default=None, help="Narrator gender (prompted if omitted)")
    parser.add_argument("--accent", choices=["us", "hindi", "uk"], default=None, help="Voice accent: 'us', 'hindi', or 'uk' (prompted if omitted)")
    parser.add_argument("--voice", default=None, help="Optional explicit Kokoro voice ID override (e.g. af_heart, am_michael, hf_alpha)")
    parser.add_argument("-s", "--subtitle", choices=["en", "hi", "english", "hindi", "none", "off"], default=None, help="Subtitle language: 'en', 'hi', or 'none' (prompted if omitted)")
    sfx_group = parser.add_mutually_exclusive_group()
    sfx_group.add_argument("--sfx", dest="sfx", action="store_true", default=None, help="Enable Groq + Freesound SFX")
    sfx_group.add_argument("--no-sfx", dest="sfx", action="store_false", help="Disable SFX")
    parser.add_argument("--speed", type=float, default=TTS_SPEED, help=f"TTS speed (default: {TTS_SPEED})")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip interactive prompts and use defaults for omitted options")
    parser.add_argument("--no-cache", action="store_true", help="Force fresh TTS generation instead of reusing tts_cache")
    args = parser.parse_args()

    run_assembly(
        args.json_path,
        frames_dir=args.frames_dir,
        output_path=args.output,
        aspect_ratio=args.aspect_ratio,
        bgm_path=args.bgm,
        lang=args.lang,
        gender=args.gender,
        accent=args.accent,
        voice=args.voice,
        subtitle=args.subtitle,
        sfx=args.sfx,
        speed=args.speed,
        yes=args.yes,
        no_cache=args.no_cache,
    )