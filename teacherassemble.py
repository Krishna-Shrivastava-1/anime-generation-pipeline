# Force 9:16 vertical Shorts/Reels with soft background music
# python teacherassemble.py teachingscript.json -a 9:16 -b bgm.mp3 -o final_video.mp4
# git pull
# python teacherassemble.py teachingscript.json

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

VOICE = "hf_alpha"        # Kokoro Hindi female: "hf_alpha" or "hf_beta"
TTS_LANG = "hi"
TTS_SPEED = 1.10
VOICE_VOLUME = 0.95

MAX_INTERNAL_SILENCE_MS = 220
KEEP_INTERNAL_SILENCE_MS = 120
BEAT_PAD_START_MS = 20
BEAT_PAD_END_MS = 45

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
# TRANSLATION (HINDI -> ENGLISH)
# ============================================================

def translate_hi_to_en(text):
    global _TRANSLATION_CACHE
    text = " ".join(text.strip().split())
    if not text or all(ord(ch) < 128 for ch in text):
        return text

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

    if text in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[text]

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
    _TRANSLATION_CACHE[text] = translated
    TRANSLATION_CACHE_FILE.write_text(
        json.dumps(_TRANSLATION_CACHE, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return translated


# ============================================================
# KOKORO ONNX TTS
# ============================================================

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
    return _KOKORO_INSTANCE


def trim_edge_silence(samples, sr, threshold=0.0025, pad_start_ms=BEAT_PAD_START_MS, pad_end_ms=BEAT_PAD_END_MS):
    samples = np.asarray(samples, dtype=np.float32)
    active = np.where(np.abs(samples) > threshold)[0]
    if active.size == 0:
        return samples
    start_idx = max(0, int(active[0]) - int(sr * pad_start_ms / 1000))
    end_idx = min(samples.size, int(active[-1]) + int(sr * pad_end_ms / 1000))
    return samples[start_idx:end_idx]


def compress_internal_silences(samples, sr, threshold=0.003):
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return samples

    max_samples = int(sr * MAX_INTERNAL_SILENCE_MS / 1000)
    keep_samples = int(sr * KEEP_INTERNAL_SILENCE_MS / 1000)
    padded = np.concatenate(([False], np.abs(samples) < threshold, [False]))
    starts = np.where(~padded[:-1] & padded[1:])[0]
    ends = np.where(padded[:-1] & ~padded[1:])[0]

    chunks = []
    cursor = 0
    for s, e in zip(starts, ends):
        if s == 0 or e == samples.size:
            continue
        if (e - s) > max_samples:
            half_keep = max(1, keep_samples // 2)
            chunks.append(samples[cursor:s + half_keep])
            cursor = e - half_keep

    chunks.append(samples[cursor:])
    return np.concatenate(chunks) if len(chunks) > 1 else samples


def split_long_text(text, max_chars=320):
    if len(text) <= max_chars:
        return [text]
    sentences, current = [], []
    for ch in text:
        current.append(ch)
        if ch in "।.!?":
            part = "".join(current).strip()
            if part:
                sentences.append(part)
            current = []
    remainder = "".join(current).strip()
    if remainder:
        sentences.append(remainder)
    return sentences or [text]


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


def create_tts(text):
    text = " ".join(text.strip().split())
    if not text:
        raise ValueError("Empty narration text.")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.md5(
        f"{text}|{VOICE}|{TTS_LANG}|{TTS_SPEED}|{MAX_INTERNAL_SILENCE_MS}|{KEEP_INTERNAL_SILENCE_MS}|v3".encode("utf-8")
    ).hexdigest()
    output_path = CACHE_DIR / f"{cache_key}.wav"

    if not output_path.exists() or output_path.stat().st_size == 0:
        print(f"      Generating TTS: {text[:75]}...")
        kokoro = get_kokoro()
        parts = split_long_text(text)
        chunks, sample_rate = [], None

        for idx, part in enumerate(parts):
            samples, sr = kokoro.create(part, voice=VOICE, speed=TTS_SPEED, lang=TTS_LANG)
            sample_rate = sr
            samples = trim_edge_silence(
                samples, sr,
                pad_start_ms=40 if idx > 0 else BEAT_PAD_START_MS,
                pad_end_ms=70 if idx < len(parts) - 1 else BEAT_PAD_END_MS
            )
            samples = compress_internal_silences(samples, sr)
            if samples.size > 0:
                chunks.append(samples)

        if not chunks or sample_rate is None:
            raise RuntimeError(f"Kokoro returned empty audio for: {text}")

        full_samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        save_wav(output_path, full_samples, sample_rate)

    duration = get_duration(output_path)
    if duration <= 0:
        raise RuntimeError(f"Invalid TTS duration: {output_path}")
    return output_path, duration


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
# IMAGE-TO-VIDEO PROCESSING
# ============================================================

def render_image_clip_bg(image_path, target_duration, output_path, profile, motion_index=0):
    """
    Converts a still image into an animated video clip of exact `target_duration`
    using cover-scaling (no black bars) and alternating subtle camera pan.
    """
    width = profile["width"]
    height = profile["height"]
    zoom = max(1.0, float(VIDEO_ZOOM))
    zoom_w = ((int(round(width * zoom)) + 1) // 2) * 2
    zoom_h = ((int(round(height * zoom)) + 1) // 2) * 2
    dur = max(0.05, float(target_duration))

    # Alternate motion direction across clips so visual cuts stay engaging
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
        f"setsar=1,fps={FPS},trim=duration={dur:.6f},setpts=PTS-STARTPTS"
    )

    command = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(image_path),
        "-an",
        "-vf", vf,
        "-t", f"{dur:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    run_cmd(command)
    return output_path


def combine_beat_video_and_tts(beat_video_path, tts_path, target_duration, timed_cues, beat_dir, beat_id, output_path, profile):
    command = ["ffmpeg", "-y", "-stream_loop", "1", "-i", str(beat_video_path), "-i", str(tts_path)]
    filter_parts = [f"[0:v]fps={FPS},setpts=PTS-STARTPTS,trim=duration={target_duration:.6f},setpts=PTS-STARTPTS[v0]"]
    last_v = "v0"

    if timed_cues and Image is not None:
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
                f"[{last_v}][{idx + 2}:v]overlay=(W-w)/2:H-h-{profile['sub_bottom_margin']}:"
                f"enable='{cond}'[{next_v}]"
            )
            last_v = next_v
    elif timed_cues:
        ass_path = write_fallback_ass(timed_cues, beat_dir / f"{beat_id}_sub.ass", profile=profile)
        escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        filter_parts.append(f"[{last_v}]ass='{escaped}'[v_sub]")
        last_v = "v_sub"

    filter_parts.append(
        "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
        "asetpts=PTS-STARTPTS,apad,"
        f"atrim=duration={target_duration:.6f},asetpts=PTS-STARTPTS,"
        f"volume={VOICE_VOLUME}[a]"
    )

    command.extend([
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{last_v}]", "-map", "[a]",
        "-t", f"{target_duration:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
        str(output_path)
    ])
    run_cmd(command)
    return output_path


def concatenate_segments(segment_files, output_file, temp_dir, video_only=False, bgm_path=None):
    output_file = Path(output_file)
    concat_file = Path(temp_dir) / f"{output_file.stem}.concat.txt"

    with open(concat_file, "w", encoding="utf-8") as f:
        for seg in segment_files:
            safe = str(seg.resolve()).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    if video_only:
        # All clip_bg files share identical size, fps, pix_fmt, and codec
        run_cmd([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c:v", "copy", "-an", str(output_file)
        ])
        return output_file

    is_mp4 = output_file.suffix.lower() == ".mp4"
    command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]

    if bgm_path is not None and Path(bgm_path).exists():
        command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        command.extend([
            "-filter_complex",
            "[0:a]aresample=44100:async=1:first_pts=0,asetpts=PTS-STARTPTS[v_a];"
            f"[1:a]aresample=44100,volume={BGM_VOLUME}[bgm];"
            "[v_a][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]",
            "-map", "0:v:0", "-map", "[aout]"
        ])
    else:
        command.extend([
            "-af", "aresample=44100:async=1:first_pts=0,asetpts=PTS-STARTPTS"
        ])

    command.extend([
        "-vf", f"fps={FPS},setpts=PTS-STARTPTS",
        "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20" if is_mp4 else "18", "-pix_fmt", "yuv420p",
    ])

    if is_mp4:
        command.extend([
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart",
        ])
    else:
        command.extend([
            "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
        ])

    command.append(str(output_file))
    run_cmd(command)
    return output_file


# ============================================================
# BEAT & ASSEMBLY PIPELINE
# ============================================================

def compute_clip_target_durations(clips, total_beat_duration):
    weights = []
    for clip in clips:
        txt = clip.get("spoken_text", "").strip()
        if txt:
            chars = sum(1 for c in txt if not c.isspace() and c not in "।,.!?")
            pauses = sum(2.5 if c in "।.!?" else 1.2 for c in txt if c in "।,.!?")
            weights.append(max(float(chars) + pauses, 1.0))
        elif clip.get("estimated_spoken_duration"):
            weights.append(max(float(clip["estimated_spoken_duration"]), 0.5))
        elif "start" in clip and "end" in clip:
            weights.append(max(float(clip["end"]) - float(clip["start"]), 0.5))
        else:
            weights.append(1.0)

    total_w = sum(weights)
    durations, elapsed = [], 0.0
    for idx, w in enumerate(weights):
        if idx == len(weights) - 1:
            durations.append(max(0.1, total_beat_duration - elapsed))
        else:
            dur = max(0.1, total_beat_duration * (w / total_w))
            elapsed += dur
            durations.append(dur)
    return durations


def render_beat(beat, beat_index, frames_dir, temp_dir, profile, motion_counter):
    beat_id = beat.get("beat_id", f"B{beat_index:04d}")
    clips = beat.get("clips") or [{"clip_id": f"{beat_id}_C0001", "spoken_text": beat.get("narration", "")}]

    narration = (
        beat.get("narration", "").strip()
        or beat.get("narration_text", "").strip()
        or " ".join(c.get("spoken_text", "").strip() for c in clips if c.get("spoken_text", "").strip())
    )
    if not narration:
        raise ValueError(f"{beat_id}: missing narration.")

    print(f"\n[{beat_id}] {narration}")
    beat_dir = temp_dir / beat_id
    beat_dir.mkdir(parents=True, exist_ok=True)

    beat_tts_path, beat_tts_duration = create_tts(narration)
    english_sub = translate_hi_to_en(narration)
    timed_cues = build_timed_subtitle_cues(
        english_sub, beat_tts_duration, max_chars_cue=profile["sub_max_chars_cue"]
    )
    clip_durations = compute_clip_target_durations(clips, beat_tts_duration)

    print(f"      TTS: {beat_tts_duration:.2f}s | Clips: {len(clips)} | Sub: {english_sub[:70]}...")

    clip_segments = []
    for idx, (clip, target_dur) in enumerate(zip(clips, clip_durations), start=1):
        clip_id = clip.get("clip_id", f"{beat_id}_C{idx:04d}")
        img_path = resolve_clip_image(clip, beat_id, clip_id, frames_dir)
        bg_path = beat_dir / f"{clip_id}_bg.mkv"
        render_image_clip_bg(
            img_path, target_dur, bg_path,
            profile=profile,
            motion_index=motion_counter + idx - 1
        )
        clip_segments.append(bg_path)

    beat_video = beat_dir / f"{beat_id}_video.mkv"
    concatenate_segments(clip_segments, beat_video, temp_dir=beat_dir, video_only=True)

    beat_output = beat_dir / f"{beat_id}_final.mkv"
    combine_beat_video_and_tts(
        beat_video, beat_tts_path, beat_tts_duration,
        timed_cues, beat_dir, beat_id, beat_output, profile=profile
    )
    return beat_output, beat_tts_duration, motion_counter + len(clips)


def run_assembly(json_path, frames_dir=None, output_path=None, aspect_ratio="auto", bgm_path=None):
    check_dependencies()
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

    # Resolve aspect ratio: CLI -> JSON -> first image dimensions
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

    print(
        f"Title: {title} | Beats: {len(beats)} | Aspect: {aspect_ratio} "
        f"({profile['width']}x{profile['height']}) | Frames: {frames_dir} | Output: {final_output.name}"
    )
    if Image is None:
        print("[Note] Install Pillow (`pip install pillow`) for RDR2-style sketchy subtitles.")

    try:
        get_kokoro()
        beat_outputs, expected_total, motion_counter = [], 0.0, 0
        for idx, beat in enumerate(beats, start=1):
            out, dur, motion_counter = render_beat(
                beat, idx, frames_dir, temp_dir, profile, motion_counter
            )
            beat_outputs.append(out)
            expected_total += dur

        print("\nAssembling final video...")
        concatenate_segments(
            beat_outputs, final_output, temp_dir=temp_dir, video_only=False, bgm_path=bgm_path
        )
        actual_total = get_duration(final_output)
        print(f"Done: {final_output} ({actual_total:.2f}s / {actual_total / 60:.2f} min)")
        return str(final_output)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assemble explainer video from generated images + beat/clip JSON with Kokoro TTS and RDR2 subtitles."
    )
    parser.add_argument("json_path", help="Path to story JSON (with beats[] and clips[])")
    parser.add_argument("-f", "--frames-dir", default=None, help="Directory with generated images (default: build/frames)")
    parser.add_argument("-o", "--output", default=None, help="Optional output MP4 path")
    parser.add_argument("-a", "--aspect-ratio", choices=["auto", "9:16", "16:9"], default="auto", help="Target aspect ratio")
    parser.add_argument("-b", "--bgm", default=None, help="Optional background music audio file (looped softly)")
    args = parser.parse_args()
    run_assembly(
        args.json_path,
        frames_dir=args.frames_dir,
        output_path=args.output,
        aspect_ratio=args.aspect_ratio,
        bgm_path=args.bgm,
    )