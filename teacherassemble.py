# # Force 9:16 vertical Shorts/Reels with soft background music
# # python teacherassemble.py teachingscript.json -a 9:16 -b bgm.mp3 -o final_video.mp4
# # git pull
# # python teacherassemble.py teachingscript.json

# import argparse
# import hashlib
# import json
# import math
# import random
# import re
# import shutil
# import subprocess
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

# VOICE = "hf_alpha"        # Kokoro Hindi female: "hf_alpha" or "hf_beta"
# TTS_LANG = "hi"
# TTS_SPEED = 1.10
# VOICE_VOLUME = 0.95

# MAX_INTERNAL_SILENCE_MS = 220
# KEEP_INTERNAL_SILENCE_MS = 120
# BEAT_PAD_START_MS = 20
# BEAT_PAD_END_MS = 45

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
#     Finds the generated image in `frames_dir` (e.g. after `git pull`):
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
# # TRANSLATION (HINDI -> ENGLISH)
# # ============================================================

# def translate_hi_to_en(text):
#     global _TRANSLATION_CACHE
#     text = " ".join(text.strip().split())
#     if not text or all(ord(ch) < 128 for ch in text):
#         return text

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

#     if text in _TRANSLATION_CACHE:
#         return _TRANSLATION_CACHE[text]

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
#     _TRANSLATION_CACHE[text] = translated
#     TRANSLATION_CACHE_FILE.write_text(
#         json.dumps(_TRANSLATION_CACHE, ensure_ascii=False, indent=2),
#         encoding="utf-8"
#     )
#     return translated


# # ============================================================
# # KOKORO ONNX TTS
# # ============================================================

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
#     return _KOKORO_INSTANCE


# def trim_edge_silence(samples, sr, threshold=0.0025, pad_start_ms=BEAT_PAD_START_MS, pad_end_ms=BEAT_PAD_END_MS):
#     samples = np.asarray(samples, dtype=np.float32)
#     active = np.where(np.abs(samples) > threshold)[0]
#     if active.size == 0:
#         return samples
#     start_idx = max(0, int(active[0]) - int(sr * pad_start_ms / 1000))
#     end_idx = min(samples.size, int(active[-1]) + int(sr * pad_end_ms / 1000))
#     return samples[start_idx:end_idx]


# def compress_internal_silences(samples, sr, threshold=0.003):
#     samples = np.asarray(samples, dtype=np.float32)
#     if samples.size == 0:
#         return samples

#     max_samples = int(sr * MAX_INTERNAL_SILENCE_MS / 1000)
#     keep_samples = int(sr * KEEP_INTERNAL_SILENCE_MS / 1000)
#     padded = np.concatenate(([False], np.abs(samples) < threshold, [False]))
#     starts = np.where(~padded[:-1] & padded[1:])[0]
#     ends = np.where(padded[:-1] & ~padded[1:])[0]

#     chunks = []
#     cursor = 0
#     for s, e in zip(starts, ends):
#         if s == 0 or e == samples.size:
#             continue
#         if (e - s) > max_samples:
#             half_keep = max(1, keep_samples // 2)
#             chunks.append(samples[cursor:s + half_keep])
#             cursor = e - half_keep

#     chunks.append(samples[cursor:])
#     return np.concatenate(chunks) if len(chunks) > 1 else samples


# def split_long_text(text, max_chars=320):
#     if len(text) <= max_chars:
#         return [text]
#     sentences, current = [], []
#     for ch in text:
#         current.append(ch)
#         if ch in "।.!?":
#             part = "".join(current).strip()
#             if part:
#                 sentences.append(part)
#             current = []
#     remainder = "".join(current).strip()
#     if remainder:
#         sentences.append(remainder)
#     return sentences or [text]


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


# def create_tts(text):
#     text = " ".join(text.strip().split())
#     if not text:
#         raise ValueError("Empty narration text.")

#     CACHE_DIR.mkdir(parents=True, exist_ok=True)
#     cache_key = hashlib.md5(
#         f"{text}|{VOICE}|{TTS_LANG}|{TTS_SPEED}|{MAX_INTERNAL_SILENCE_MS}|{KEEP_INTERNAL_SILENCE_MS}|v3".encode("utf-8")
#     ).hexdigest()
#     output_path = CACHE_DIR / f"{cache_key}.wav"

#     if not output_path.exists() or output_path.stat().st_size == 0:
#         print(f"      Generating TTS: {text[:75]}...")
#         kokoro = get_kokoro()
#         parts = split_long_text(text)
#         chunks, sample_rate = [], None

#         for idx, part in enumerate(parts):
#             samples, sr = kokoro.create(part, voice=VOICE, speed=TTS_SPEED, lang=TTS_LANG)
#             sample_rate = sr
#             samples = trim_edge_silence(
#                 samples, sr,
#                 pad_start_ms=40 if idx > 0 else BEAT_PAD_START_MS,
#                 pad_end_ms=70 if idx < len(parts) - 1 else BEAT_PAD_END_MS
#             )
#             samples = compress_internal_silences(samples, sr)
#             if samples.size > 0:
#                 chunks.append(samples)

#         if not chunks or sample_rate is None:
#             raise RuntimeError(f"Kokoro returned empty audio for: {text}")

#         full_samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
#         save_wav(output_path, full_samples, sample_rate)

#     duration = get_duration(output_path)
#     if duration <= 0:
#         raise RuntimeError(f"Invalid TTS duration: {output_path}")
#     return output_path, duration


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
# # IMAGE-TO-VIDEO PROCESSING
# # ============================================================

# def render_image_clip_bg(image_path, target_duration, output_path, profile, motion_index=0):
#     """
#     Converts a still image into an animated video clip of exact `target_duration`
#     using cover-scaling (no black bars) and alternating subtle camera pan.
#     """
#     width = profile["width"]
#     height = profile["height"]
#     zoom = max(1.0, float(VIDEO_ZOOM))
#     zoom_w = ((int(round(width * zoom)) + 1) // 2) * 2
#     zoom_h = ((int(round(height * zoom)) + 1) // 2) * 2
#     dur = max(0.05, float(target_duration))

#     # Alternate motion direction across clips so visual cuts stay engaging
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
#         f"setsar=1,fps={FPS},trim=duration={dur:.6f},setpts=PTS-STARTPTS"
#     )

#     command = [
#         "ffmpeg", "-y",
#         "-loop", "1",
#         "-framerate", str(FPS),
#         "-i", str(image_path),
#         "-an",
#         "-vf", vf,
#         "-t", f"{dur:.6f}",
#         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
#         str(output_path)
#     ]
#     run_cmd(command)
#     return output_path


# def combine_beat_video_and_tts(beat_video_path, tts_path, target_duration, timed_cues, beat_dir, beat_id, output_path, profile):
#     command = ["ffmpeg", "-y", "-stream_loop", "1", "-i", str(beat_video_path), "-i", str(tts_path)]
#     filter_parts = [f"[0:v]fps={FPS},setpts=PTS-STARTPTS,trim=duration={target_duration:.6f},setpts=PTS-STARTPTS[v0]"]
#     last_v = "v0"

#     if timed_cues and Image is not None:
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
#                 f"[{last_v}][{idx + 2}:v]overlay=(W-w)/2:H-h-{profile['sub_bottom_margin']}:"
#                 f"enable='{cond}'[{next_v}]"
#             )
#             last_v = next_v
#     elif timed_cues:
#         ass_path = write_fallback_ass(timed_cues, beat_dir / f"{beat_id}_sub.ass", profile=profile)
#         escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
#         filter_parts.append(f"[{last_v}]ass='{escaped}'[v_sub]")
#         last_v = "v_sub"

#     filter_parts.append(
#         "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
#         "asetpts=PTS-STARTPTS,apad,"
#         f"atrim=duration={target_duration:.6f},asetpts=PTS-STARTPTS,"
#         f"volume={VOICE_VOLUME}[a]"
#     )

#     command.extend([
#         "-filter_complex", ";".join(filter_parts),
#         "-map", f"[{last_v}]", "-map", "[a]",
#         "-t", f"{target_duration:.6f}",
#         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
#         "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
#         str(output_path)
#     ])
#     run_cmd(command)
#     return output_path


# def concatenate_segments(segment_files, output_file, temp_dir, video_only=False, bgm_path=None):
#     output_file = Path(output_file)
#     concat_file = Path(temp_dir) / f"{output_file.stem}.concat.txt"

#     with open(concat_file, "w", encoding="utf-8") as f:
#         for seg in segment_files:
#             safe = str(seg.resolve()).replace("\\", "/").replace("'", "'\\''")
#             f.write(f"file '{safe}'\n")

#     if video_only:
#         # All clip_bg files share identical size, fps, pix_fmt, and codec
#         run_cmd([
#             "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
#             "-c:v", "copy", "-an", str(output_file)
#         ])
#         return output_file

#     is_mp4 = output_file.suffix.lower() == ".mp4"
#     command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]

#     if bgm_path is not None and Path(bgm_path).exists():
#         command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
#         command.extend([
#             "-filter_complex",
#             "[0:a]aresample=44100:async=1:first_pts=0,asetpts=PTS-STARTPTS[v_a];"
#             f"[1:a]aresample=44100,volume={BGM_VOLUME}[bgm];"
#             "[v_a][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]",
#             "-map", "0:v:0", "-map", "[aout]"
#         ])
#     else:
#         command.extend([
#             "-af", "aresample=44100:async=1:first_pts=0,asetpts=PTS-STARTPTS"
#         ])

#     command.extend([
#         "-vf", f"fps={FPS},setpts=PTS-STARTPTS",
#         "-c:v", "libx264", "-preset", "veryfast",
#         "-crf", "20" if is_mp4 else "18", "-pix_fmt", "yuv420p",
#     ])

#     if is_mp4:
#         command.extend([
#             "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart",
#         ])
#     else:
#         command.extend([
#             "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
#         ])

#     command.append(str(output_file))
#     run_cmd(command)
#     return output_file


# # ============================================================
# # BEAT & ASSEMBLY PIPELINE
# # ============================================================

# def compute_clip_target_durations(clips, total_beat_duration):
#     weights = []
#     for clip in clips:
#         txt = clip.get("spoken_text", "").strip()
#         if txt:
#             chars = sum(1 for c in txt if not c.isspace() and c not in "।,.!?")
#             pauses = sum(2.5 if c in "।.!?" else 1.2 for c in txt if c in "।,.!?")
#             weights.append(max(float(chars) + pauses, 1.0))
#         elif clip.get("estimated_spoken_duration"):
#             weights.append(max(float(clip["estimated_spoken_duration"]), 0.5))
#         elif "start" in clip and "end" in clip:
#             weights.append(max(float(clip["end"]) - float(clip["start"]), 0.5))
#         else:
#             weights.append(1.0)

#     total_w = sum(weights)
#     durations, elapsed = [], 0.0
#     for idx, w in enumerate(weights):
#         if idx == len(weights) - 1:
#             durations.append(max(0.1, total_beat_duration - elapsed))
#         else:
#             dur = max(0.1, total_beat_duration * (w / total_w))
#             elapsed += dur
#             durations.append(dur)
#     return durations


# def render_beat(beat, beat_index, frames_dir, temp_dir, profile, motion_counter):
#     beat_id = beat.get("beat_id", f"B{beat_index:04d}")
#     clips = beat.get("clips") or [{"clip_id": f"{beat_id}_C0001", "spoken_text": beat.get("narration", "")}]

#     narration = (
#         beat.get("narration", "").strip()
#         or beat.get("narration_text", "").strip()
#         or " ".join(c.get("spoken_text", "").strip() for c in clips if c.get("spoken_text", "").strip())
#     )
#     if not narration:
#         raise ValueError(f"{beat_id}: missing narration.")

#     print(f"\n[{beat_id}] {narration}")
#     beat_dir = temp_dir / beat_id
#     beat_dir.mkdir(parents=True, exist_ok=True)

#     beat_tts_path, beat_tts_duration = create_tts(narration)
#     english_sub = translate_hi_to_en(narration)
#     timed_cues = build_timed_subtitle_cues(
#         english_sub, beat_tts_duration, max_chars_cue=profile["sub_max_chars_cue"]
#     )
#     clip_durations = compute_clip_target_durations(clips, beat_tts_duration)

#     print(f"      TTS: {beat_tts_duration:.2f}s | Clips: {len(clips)} | Sub: {english_sub[:70]}...")

#     clip_segments = []
#     for idx, (clip, target_dur) in enumerate(zip(clips, clip_durations), start=1):
#         clip_id = clip.get("clip_id", f"{beat_id}_C{idx:04d}")
#         img_path = resolve_clip_image(clip, beat_id, clip_id, frames_dir)
#         bg_path = beat_dir / f"{clip_id}_bg.mkv"
#         render_image_clip_bg(
#             img_path, target_dur, bg_path,
#             profile=profile,
#             motion_index=motion_counter + idx - 1
#         )
#         clip_segments.append(bg_path)

#     beat_video = beat_dir / f"{beat_id}_video.mkv"
#     concatenate_segments(clip_segments, beat_video, temp_dir=beat_dir, video_only=True)

#     beat_output = beat_dir / f"{beat_id}_final.mkv"
#     combine_beat_video_and_tts(
#         beat_video, beat_tts_path, beat_tts_duration,
#         timed_cues, beat_dir, beat_id, beat_output, profile=profile
#     )
#     return beat_output, beat_tts_duration, motion_counter + len(clips)


# def run_assembly(json_path, frames_dir=None, output_path=None, aspect_ratio="auto", bgm_path=None):
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

#     # Resolve aspect ratio: CLI -> JSON -> first image dimensions
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

#     print(
#         f"Title: {title} | Beats: {len(beats)} | Aspect: {aspect_ratio} "
#         f"({profile['width']}x{profile['height']}) | Frames: {frames_dir} | Output: {final_output.name}"
#     )
#     if Image is None:
#         print("[Note] Install Pillow (`pip install pillow`) for RDR2-style sketchy subtitles.")

#     try:
#         get_kokoro()
#         beat_outputs, expected_total, motion_counter = [], 0.0, 0
#         for idx, beat in enumerate(beats, start=1):
#             out, dur, motion_counter = render_beat(
#                 beat, idx, frames_dir, temp_dir, profile, motion_counter
#             )
#             beat_outputs.append(out)
#             expected_total += dur

#         print("\nAssembling final video...")
#         concatenate_segments(
#             beat_outputs, final_output, temp_dir=temp_dir, video_only=False, bgm_path=bgm_path
#         )
#         actual_total = get_duration(final_output)
#         print(f"Done: {final_output} ({actual_total:.2f}s / {actual_total / 60:.2f} min)")
#         return str(final_output)
#     finally:
#         if temp_dir.exists():
#             shutil.rmtree(temp_dir, ignore_errors=True)


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(
#         description="Assemble explainer video from generated images + beat/clip JSON with Kokoro TTS and RDR2 subtitles."
#     )
#     parser.add_argument("json_path", help="Path to story JSON (with beats[] and clips[])")
#     parser.add_argument("-f", "--frames-dir", default=None, help="Directory with generated images (default: build/frames)")
#     parser.add_argument("-o", "--output", default=None, help="Optional output MP4 path")
#     parser.add_argument("-a", "--aspect-ratio", choices=["auto", "9:16", "16:9"], default="auto", help="Target aspect ratio")
#     parser.add_argument("-b", "--bgm", default=None, help="Optional background music audio file (looped softly)")
#     args = parser.parse_args()
#     run_assembly(
#         args.json_path,
#         frames_dir=args.frames_dir,
#         output_path=args.output,
#         aspect_ratio=args.aspect_ratio,
#         bgm_path=args.bgm,
#     )








# Examples:
#   Hindi female (default):
#     python teacherassemble.py teachingscript.json
#   English in the SAME Hindi accent (male) using translation_cache.json:
#     python teacherassemble.py teachingscript.json --lang en --gender male --accent hindi
#   English in the SAME Hindi accent (female) + 9:16 + BGM:
#     python teacherassemble.py teachingscript.json --lang en --gender female -a 9:16 -b bgm.mp3 -o final_video.mp4
#   Hindi male:
#     python teacherassemble.py teachingscript.json --lang hi --gender male

import argparse
import hashlib
import json
import math
import random
import re
import shutil
import subprocess
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
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_LANG = "hi"       # "hi" or "en"
DEFAULT_GENDER = "female" # "female" or "male"
DEFAULT_ACCENT = "hindi"  # "hindi" (keeps Indian/Hindi accent even in English), "us", or "uk"
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

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
CACHE_DIR = BASE_DIR / "tts_cache"
DEFAULT_FRAMES_DIR = BASE_DIR / "build" / "frames"
TRANSLATION_CACHE_FILE = BASE_DIR / "translation_cache.json"

_KOKORO_INSTANCE = None
_TRANSLATION_CACHE = None
_PHONEMIZER_PATCHED = False

VOICE_PRESETS = {
    "hindi": {
        "female": ["hf_alpha", "hf_beta"],
        "male": ["hm_omega", "hm_psi"],
    },
    "us": {
        "female": ["af_heart", "af_bella", "af_sarah", "af_nicole"],
        "male": ["am_michael", "am_adam", "am_fenrir", "am_onyx"],
    },
    "uk": {
        "female": ["bf_emma", "bf_isabella", "bf_alice"],
        "male": ["bm_george", "bm_lewis", "bm_daniel"],
    },
}

ACRONYM_MAP = {
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
# HELPERS
# ============================================================

def run_cmd(command):
    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            "\nFFmpeg command failed:\n"
            + " ".join(map(str, command))
            + "\n\n"
            + result.stderr[-4000:]
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
    """
    Finds the generated image in `frames_dir` (e.g. after `git pull`):
      1. Explicit `image` / `image_path` / `frame` key on clip
      2. {frames_dir}/{beat_id}_{clip_id}.{ext}
      3. {frames_dir}/{clip_id}.{ext}
      4. {frames_dir}/{beat_id}.{ext}
    """
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
# TRANSLATION (HINDI -> ENGLISH via translation_cache.json)
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


def translate_hi_to_en(text):
    text = " ".join(text.strip().split())
    if not text or all(ord(ch) < 128 for ch in text):
        return text

    cache = _get_translation_cache()
    if text in cache:
        return cache[text]

    translated = None
    if GoogleTranslator is not None:
        try:
            translated = GoogleTranslator(source="hi", target="en").translate(text)
        except Exception:
            translated = None

    if not translated:
        try:
            url = (
                "https://translate.googleapis.com/translate_a/single"
                "?client=gtx&sl=hi&tl=en&dt=t&q=" + urllib.parse.quote(text)
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = "".join(part[0] for part in data[0] if part and part[0])
        except Exception as exc:
            print(f"      [Warning] Translation failed ({exc}); using original text.")
            translated = text

    translated = " ".join(translated.strip().split())
    cache[text] = translated
    TRANSLATION_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return translated


# ============================================================
# HINGLISH & TECH TEXT NORMALIZATION FOR NATURAL TTS
# ============================================================

def normalize_text_for_tts(text, lang="hi"):
    """
    Cleans Hindi/English + code/tech tokens so Kokoro doesn't insert fake breaks
    on 'Node.js', stumble on '@RestController', or mumble CamelCase & acronyms.
    """
    orig = " ".join(text.strip().split())
    if not orig:
        return orig

    s = orig
    # Strip backticks / markdown emphasis and empty call parens
    s = s.replace("`", "").replace("*", "").replace("()", "")

    # Arrows / dashes / parens -> brief natural comma pauses
    s = s.replace("->", ", ").replace("=>", ", ")
    s = re.sub(r"[—–]+", ", ", s)
    s = re.sub(r"\s+-\s+", ", ", s)
    s = re.sub(r"\(([^)]+)\)", r", \1, ", s)

    # Annotations like @RestController -> at RestController
    s = re.sub(r"@([A-Za-z_]\w*)", r"at \1", s)

    # Underscore identifiers like user_id -> user id
    s = re.sub(r"([A-Za-z0-9])_([A-Za-z0-9])", r"\1 \2", s)

    # File/framework extensions: Node.js -> Node JS, package.json -> package JSON
    s = re.sub(
        r"\b([A-Za-z][A-Za-z0-9-]*)\.(js|ts|jsx|tsx|json|html|css|xml|yml|yaml|sql|py|java|md)\b",
        lambda m: f"{m.group(1)} {m.group(2).upper()}",
        s,
        flags=re.IGNORECASE,
    )

    # Code dot notation: app.get / req.params.id -> app dot get / req dot params dot id
    while re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", s):
        s = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", r"\1 dot \2", s)

    # Slashes between words: GET/POST -> GET, POST
    s = re.sub(r"([A-Za-z0-9]+)/([A-Za-z0-9]+)", r"\1, \2", s)

    # Split CamelCase / PascalCase so Kokoro pronounces words fluidly
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)

    # Expand uppercase technical acronyms cleanly
    s = re.sub(r"\b[A-Za-z]{2,6}\b", lambda m: ACRONYM_MAP.get(m.group(0), m.group(0)), s)

    # Replace Devanagari Danda with ASCII period for cleaner espeak sentence pauses
    if lang == "hi":
        s = s.replace("॥", ".").replace("।", ".")

    # Clean repeated commas/spaces
    s = re.sub(r"\s*,\s*(,\s*)+", ", ", s)
    s = re.sub(r"\s+([,।.!?])", r"\1", s)
    s = " ".join(s.split()).strip(" ,")

    if not s:
        return orig

    if s[-1] not in "।.!?":
        s += "."

    return s


def estimate_spoken_weight(text):
    """Estimates relative speaking duration for Hindi/English + punctuation."""
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
    """
    Removes espeak-ng language-switch markers like (hi), (en), (en-us).
    Without this, kokoro-onnx drops '(' and ')' and literally speaks 'hi' as 'hee'.
    """
    if isinstance(phonemes, str):
        cleaned = re.sub(r"\([A-Za-z0-9_-]{1,14}\)", " ", phonemes)
        return re.sub(r"\s+", " ", cleaned).strip()
    if isinstance(phonemes, list):
        return [_strip_lang_flags(p) for p in phonemes]
    return phonemes


def patch_kokoro_phonemizer(kokoro):
    """
    Patches phonemizer / EspeakBackend / tokenizer.phonemize so (hi) and (en)
    language switch markers never leak into Kokoro's phoneme tokens as 'hee'.
    """
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

    candidates = VOICE_PRESETS[accent][gender]
    if available:
        for v in candidates:
            if v in available:
                return v, tts_lang
        # Fallback within same gender prefix if custom voices file
        prefix = f"{'h' if accent == 'hindi' else ('b' if accent == 'uk' else 'a')}{'f' if gender == 'female' else 'm'}_"
        matched = sorted(v for v in available if v.startswith(prefix))
        if matched:
            return matched[0], tts_lang
        any_gender = sorted(v for v in available if len(v) > 2 and v[1] == ("f" if gender == "female" else "m"))
        if any_gender:
            return any_gender[0], tts_lang

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


def load_wav(path):
    if sf is not None:
        samples, sr = sf.read(str(path), dtype="float32")
        if samples.ndim > 1:
            samples = np.mean(samples, axis=1)
        return samples.astype(np.float32), int(sr)
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
    pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        pcm = pcm.reshape(-1, nch).mean(axis=1)
    return pcm, int(sr)


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
    """Detects quiet pause midpoints inside a waveform."""
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


def group_beats_for_tts(beats, narration_lang="hi"):
    groups = []
    current_group = []
    current_chars = 0

    for idx, beat in enumerate(beats):
        clips = beat.get("clips") or []
        raw_narration_hi = (
            beat.get("narration", "").strip()
            or beat.get("narration_text", "").strip()
            or " ".join(c.get("spoken_text", "").strip() for c in clips if c.get("spoken_text", "").strip())
        )
        if not raw_narration_hi:
            beat_id = beat.get("beat_id", f"B{idx + 1:04d}")
            raise ValueError(f"{beat_id}: missing narration.")

        english_narration = translate_hi_to_en(raw_narration_hi)
        spoken_source = english_narration if narration_lang == "en" else raw_narration_hi
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
            "raw_narration_hi": raw_narration_hi,
            "english_narration": english_narration,
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


def synthesize_group_and_cache(group, voice, tts_lang, speed=TTS_SPEED):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sig_payload = json.dumps(
        {
            "v": "v5_fluent",
            "voice": voice,
            "lang": tts_lang,
            "speed": speed,
            "texts": [item["norm_text"] for item in group],
        },
        ensure_ascii=False,
    )
    group_key = hashlib.md5(sig_payload.encode("utf-8")).hexdigest()
    cached_paths = [CACHE_DIR / f"{group_key}_{i:02d}.wav" for i in range(len(group))]

    all_cached = all(p.exists() and p.stat().st_size > 0 for p in cached_paths)
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


def prepare_all_beats_audio(beats, temp_dir, narration_lang, voice, tts_lang, speed=TTS_SPEED):
    groups = group_beats_for_tts(beats, narration_lang=narration_lang)
    print(f"Synthesizing fluent narration ({narration_lang.upper()} | {voice} | {tts_lang}) across {len(beats)} beats in {len(groups)} groups...")

    beat_audio_plans = []
    master_chunks = []
    master_sr = None

    for group in groups:
        group_results = synthesize_group_and_cache(group, voice=voice, tts_lang=tts_lang, speed=speed)
        for item, (wav_path, raw_dur, pause_after_s) in zip(group, group_results):
            samples, sr = load_wav(wav_path)
            if master_sr is None:
                master_sr = sr
            elif sr != master_sr:
                old_x = np.linspace(0.0, 1.0, samples.size)
                new_len = int(round(samples.size * master_sr / sr))
                new_x = np.linspace(0.0, 1.0, new_len)
                samples = np.interp(new_x, old_x, samples).astype(np.float32)

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
                "raw_narration_hi": item["raw_narration_hi"],
                "english_narration": item["english_narration"],
                "speech_samples": samples,
                "sample_rate": master_sr,
                "speech_dur": exact_speech_dur,
                "num_frames": num_frames,
                "frame_dur": frame_aligned_dur,
            })

    master_samples = np.concatenate(master_chunks)
    master_wav_path = Path(temp_dir) / "master_narration.wav"
    save_wav(master_wav_path, master_samples, master_sr)

    return beat_audio_plans, master_wav_path


# ============================================================
# RDR2-STYLE ENGLISH SUBTITLES
# ============================================================

def split_english_into_cues(text, max_chars=74):
    text = " ".join(text.strip().split())
    if not text:
        return []

    cues = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
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


def build_timed_subtitle_cues(english_text, total_duration, max_chars_cue=74):
    chunks = split_english_into_cues(english_text, max_chars=max_chars_cue)
    if not chunks:
        return []

    weights = [
        max(
            sum(1 for c in ch if not c.isspace() and c not in ".,!?;:")
            + sum(2.5 if c in ".!?" else 1.2 for c in ch if c in ".,!?;:"),
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


def find_subtitle_font(size):
    for path in [
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_rdr2_subtitle_png(text, output_path, profile, seed_value=0):
    font_size = profile["sub_font_size"]
    font = find_subtitle_font(font_size)
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


def write_fallback_ass(timed_cues, ass_path, profile):
    def fmt(sec):
        cs = max(0, int(round(sec * 100)))
        s, cs = divmod(cs, 100)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    lines = [
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {profile['width']}\nPlayResY: {profile['height']}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Georgia,{profile['sub_font_size']},&H00F5F5F5,&H000000FF,&H26080808,"
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

    if Image is not None:
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
        ass_path = write_fallback_ass(timed_cues, beat_dir / f"{beat_id}_sub.ass", profile=profile)
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


def mux_final_video(master_video_path, master_audio_path, output_file, bgm_path=None):
    output_file = Path(output_file)
    command = [
        "ffmpeg", "-y",
        "-i", str(master_video_path),
        "-i", str(master_audio_path),
    ]

    voice_chain = (
        "[1:a]aresample=44100,"
        "highpass=f=75,"
        "acompressor=threshold=-18dB:ratio=2.0:attack=15:release=180:makeup=1.4,"
        f"volume={VOICE_VOLUME}"
    )

    if bgm_path is not None and Path(bgm_path).exists():
        command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        filter_complex = (
            f"{voice_chain}[v_pre];"
            "[v_pre]asplit=2[v_mix][v_sc];"
            f"[2:a]aresample=44100,volume={BGM_VOLUME}[bgm_raw];"
            "[bgm_raw][v_sc]sidechaincompress=threshold=0.02:ratio=2.8:attack=90:release=480[bgm];"
            "[v_mix][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
            "alimiter=limit=0.95[aout]"
        )
    else:
        filter_complex = f"{voice_chain},alimiter=limit=0.95[aout]"

    command.extend([
        "-filter_complex", filter_complex,
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
    clips, speech_samples, sr, speech_dur, total_beat_frames, narration_lang="hi"
):
    """
    Allocates integer frames across clips so image segments track the spoken clauses:
      1. Weights each clip by its English translation (when --lang en) or Hindi spoken_text.
      2. Snaps internal clip cut timestamps to nearby natural pause/comma valleys
         in the beat's actual audio waveform so images change cleanly between clauses.
    """
    speech_frames = max(len(clips), min(total_beat_frames, int(round(speech_dur * FPS))))
    pause_frames = max(0, total_beat_frames - speech_frames)
    if len(clips) == 1:
        return [total_beat_frames]

    weights = []
    for clip in clips:
        if narration_lang == "en":
            en_txt = (clip.get("spoken_text_en") or clip.get("english_text") or "").strip()
            if not en_txt and clip.get("spoken_text", "").strip():
                en_txt = translate_hi_to_en(clip["spoken_text"].strip())
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

    # Snap cut points to natural micro-pauses (commas/clause breaks) if present nearby
    pauses, _, _ = find_quiet_pauses(speech_samples, sr, min_pause_s=0.045)
    pause_times = [mid / sr for mid, _ in pauses]

    snapped_cuts_s = []
    prev_t = 0.0
    for idx, exp_t in enumerate(expected_cuts_s):
        remaining = len(expected_cuts_s) - idx
        min_t = prev_t + 0.30
        max_t = speech_dur - remaining * 0.30
        best_t = min(max(exp_t, min_t), max_t)

        # Look for closest quiet pause within +/- 0.45s of expected clause boundary
        nearby = [pt for pt in pause_times if min_t <= pt <= max_t and abs(pt - exp_t) <= 0.45]
        if nearby:
            best_t = min(nearby, key=lambda pt: abs(pt - exp_t))

        snapped_cuts_s.append(best_t)
        prev_t = best_t

    # Convert snapped timestamps to integer frames summing to total_beat_frames
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


def render_beat_video(plan, frames_dir, temp_dir, profile, motion_counter, narration_lang):
    beat_index = plan["beat_index"]
    beat = plan["beat"]
    raw_narration_hi = plan["raw_narration_hi"]
    english_narration = plan["english_narration"]
    speech_dur = plan["speech_dur"]
    total_frames = plan["num_frames"]

    beat_id = beat.get("beat_id", f"B{beat_index:04d}")
    clips = beat.get("clips") or [{"clip_id": f"{beat_id}_C0001", "spoken_text": raw_narration_hi}]

    preview_txt = english_narration if narration_lang == "en" else raw_narration_hi
    print(f"\n[{beat_id}] ({speech_dur:.2f}s speech / {total_frames / FPS:.2f}s total) {preview_txt}")
    beat_dir = temp_dir / beat_id
    beat_dir.mkdir(parents=True, exist_ok=True)

    timed_cues = build_timed_subtitle_cues(
        english_narration, speech_dur, max_chars_cue=profile["sub_max_chars_cue"]
    )
    clip_frames_list = compute_clip_target_frames(
        clips,
        plan["speech_samples"],
        plan["sample_rate"],
        speech_dur,
        total_frames,
        narration_lang=narration_lang,
    )

    print(f"      Clips: {len(clips)} | Sub: {english_narration[:70]}...")

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


def run_assembly(
    json_path,
    frames_dir=None,
    output_path=None,
    aspect_ratio="auto",
    bgm_path=None,
    lang=DEFAULT_LANG,
    gender=DEFAULT_GENDER,
    accent=DEFAULT_ACCENT,
    voice=None,
    speed=TTS_SPEED,
):
    check_dependencies()
    narration_lang = normalize_lang_arg(lang)

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
        get_kokoro()
        selected_voice, tts_lang = resolve_voice_and_tts_lang(
            narration_lang=narration_lang,
            gender=gender,
            accent=accent,
            explicit_voice=voice,
        )

        print(
            f"Title: {title} | Beats: {len(beats)} | Aspect: {aspect_ratio} ({profile['width']}x{profile['height']}) "
            f"| Audio: {narration_lang.upper()} ({gender}, {accent} accent -> {selected_voice}, {tts_lang}) @ {speed}x "
            f"| Output: {final_output.name}"
        )
        if Image is None:
            print("[Note] Install Pillow (`pip install pillow`) for RDR2-style sketchy subtitles.")

        beat_audio_plans, master_wav_path = prepare_all_beats_audio(
            beats,
            temp_dir=temp_dir,
            narration_lang=narration_lang,
            voice=selected_voice,
            tts_lang=tts_lang,
            speed=speed,
        )

        beat_video_outputs, motion_counter = [], 0
        for plan in beat_audio_plans:
            out_vid, motion_counter = render_beat_video(
                plan, frames_dir, temp_dir, profile, motion_counter, narration_lang=narration_lang
            )
            beat_video_outputs.append(out_vid)

        print("\nAssembling master video + continuous audio...")
        master_video_path = temp_dir / "master_video.mp4"
        concat_video_only(beat_video_outputs, master_video_path, temp_dir=temp_dir)
        mux_final_video(master_video_path, master_wav_path, final_output, bgm_path=bgm_path)

        actual_total = get_duration(final_output)
        print(f"Done: {final_output} ({actual_total:.2f}s / {actual_total / 60:.2f} min)")
        return str(final_output)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assemble explainer video from generated images + beat/clip JSON with fluent Kokoro TTS and RDR2 subtitles."
    )
    parser.add_argument("json_path", help="Path to story JSON (with beats[] and clips[])")
    parser.add_argument("-f", "--frames-dir", default=None, help="Directory with generated images (default: build/frames)")
    parser.add_argument("-o", "--output", default=None, help="Optional output MP4 path")
    parser.add_argument("-a", "--aspect-ratio", choices=["auto", "9:16", "16:9"], default="auto", help="Target aspect ratio")
    parser.add_argument("-b", "--bgm", default=None, help="Optional background music audio file (looped softly)")
    parser.add_argument("-l", "--lang", choices=["hi", "en", "hindi", "english"], default=DEFAULT_LANG, help="Narration audio language: Hindi ('hi') or English from translation_cache ('en')")
    parser.add_argument("-g", "--gender", choices=["female", "male"], default=DEFAULT_GENDER, help="Narrator voice gender (default: female)")
    parser.add_argument("--accent", choices=["hindi", "us", "uk"], default=DEFAULT_ACCENT, help="Speaker accent: 'hindi' keeps Indian/Hindi accent even for English audio (default: hindi)")
    parser.add_argument("--voice", default=None, help="Optional explicit Kokoro voice ID override (e.g. hf_alpha, hf_beta, hm_omega, hm_psi)")
    parser.add_argument("--speed", type=float, default=TTS_SPEED, help=f"TTS speed (default: {TTS_SPEED})")
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
        speed=args.speed,
    )