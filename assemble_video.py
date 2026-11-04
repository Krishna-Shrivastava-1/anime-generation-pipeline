# import os
# import json
# from pathlib import Path
# import numpy as np
# import PIL.Image

# if not hasattr(PIL.Image, 'ANTIALIAS'):
#     PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

# from moviepy import (
#     ImageClip, 
#     AudioFileClip, 
#     CompositeAudioClip, 
#     concatenate_videoclips
# )
# import moviepy.audio.fx as afx

# BUILD_DIR = Path("build")
# FRAMES_DIR = BUILD_DIR / "frames"
# AUDIO_DIR = BUILD_DIR / "audio"
# MANIFEST_FILE = BUILD_DIR / "audio_manifest.json"
# OUTPUT_VIDEO = BUILD_DIR / "final_story_video.mp4"
# BGM_FILE = Path("bgm.mp3")  # Optional background music file


# def crop_and_fit_image(img_path: Path, target_w: int, target_h: int) -> np.ndarray:
#     img = PIL.Image.open(img_path).convert("RGB")
#     src_w, src_h = img.size
#     scale = max(target_w / src_w, target_h / src_h)
#     new_w, new_h = int(src_w * scale), int(src_h * scale)
#     resized = img.resize((new_w, new_h), PIL.Image.Resampling.LANCZOS)
#     left = (new_w - target_w) // 2
#     top = (new_h - target_h) // 2
#     return np.array(resized.crop((left, top, left + target_w, top + target_h)))


# def assemble_story_video(aspect_ratio="9:16"):
#     with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
#         manifest = json.load(f)

#     target_size = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
#     clips = []
#     print(f"\n🎬 Assembling Story Video [{aspect_ratio}]...")

#     for item in manifest.get("beats", []):
#         beat_id = item["beat_id"]
#         audio_path = Path(item["audio_file"])
#         frame_path = FRAMES_DIR / f"{beat_id}.png"

#         if not frame_path.exists() or not audio_path.exists():
#             continue

#         audio_clip = AudioFileClip(str(audio_path))
#         duration = audio_clip.duration

#         frame_arr = crop_and_fit_image(frame_path, target_size[0], target_size[1])
#         clip = ImageClip(frame_arr).with_duration(duration).with_audio(audio_clip)
#         clips.append(clip)
#         print(f" -> Attached {beat_id} ({duration:.2f}s)")

#     final_video = concatenate_videoclips(clips, method="compose")

#     # If background music is present, mix it cleanly underneath the voice
#     if BGM_FILE.exists():
#         print("🎵 Mixing ambient background music (ducked to 12% volume)...")
#         bgm = AudioFileClip(str(BGM_FILE))
#         # Loop BGM to match video length and lower volume
#         bgm = afx.audio_loop(bgm, duration=final_video.duration).volumex(0.12)
#         # Combine voice track and music track
#         mixed_audio = CompositeAudioClip([final_video.audio, bgm])
#         final_video = final_video.with_audio(mixed_audio)

#     print("\nRendering final MP4...")
#     final_video.write_videofile(
#         str(OUTPUT_VIDEO),
#         fps=30,
#         codec="libx264",
#         audio_codec="aac",
#         threads=4,
#         preset="medium"
#     )
#     print(f"\n🎉 VIDEO READY: {OUTPUT_VIDEO}")


# if __name__ == "__main__":
#     assemble_story_video()













import os
import re
import json
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Tuple

import numpy as np
import soundfile as sf
import requests
import PIL.Image

if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

from moviepy import (
    ImageClip, 
    AudioFileClip, 
    CompositeAudioClip, 
    concatenate_videoclips
)
import moviepy.audio.fx as afx
from groq import Groq

# ================= Configuration & API Keys =================
BUILD_DIR = Path("build")
AUDIO_DIR = BUILD_DIR / "audio"
FRAMES_DIR = BUILD_DIR / "frames"
SFX_DIR = BUILD_DIR / "sfx"
PROCESSED_SFX_DIR = BUILD_DIR / "processed_sfx"
TIMESTAMPS_DIR = BUILD_DIR / "word_timestamps"

for p in [SFX_DIR, PROCESSED_SFX_DIR, TIMESTAMPS_DIR]:
    p.mkdir(parents=True, exist_ok=True)

MANIFEST_FILE = BUILD_DIR / "audio_manifest.json"
STORY_SCRIPT_FILE = Path("story_pipeline.json")
OUTPUT_VIDEO = BUILD_DIR / "final_story_video.mp4"
BGM_FILE = Path("bgm.mp3")

# Freesound API Configuration
FREESOUND_API_KEY = "Bs9vTK3Anfb9CPgXomEI3RTWCTRmlS34cOb1NIox"
SFX_MIN_DUR = 0.2
SFX_MAX_DUR = 6.0

# Groq API Configuration
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")

if not GROQ_API_KEY:
    print("\n" + "="*70)
    print("❌ ERROR: GROQ_API_KEY is not set!")
    print("="*70 + "\n")
    exit(1)

GROQ_MODEL = "openai/gpt-oss-120b"
groq_client = Groq(api_key=GROQ_API_KEY)


# =====================================================================
# 1. GROUND-TRUTH ACOUSTIC SCRIPT ALIGNER
# =====================================================================

def calculate_hindi_word_weight(word: str) -> float:
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
        elif '\u0900' <= ch <= '\u097F':
            weight += 1.0
        else:
            weight += 0.5
    return max(0.6, weight)


def align_ground_truth_to_audio(audio_path: Path, ground_truth_text: str, output_json: Path) -> List[Dict]:
    data, sr = sf.read(str(audio_path), dtype="float32")
    if data.ndim > 1:
        data = np.mean(data, axis=1)

    total_duration_sec = len(data) / sr

    clean_text = re.sub(r'["“”‘’\']', '', ground_truth_text)
    clean_text = clean_text.replace("...", "…")
    raw_words = [w.strip() for w in re.split(r'\s+', clean_text) if w.strip()]

    if not raw_words:
        return []

    frame_len = int(sr * 0.02)
    hop_len = int(sr * 0.01)
    frames = [data[i:i + frame_len] for i in range(0, len(data) - frame_len, hop_len)]
    rms = np.array([np.sqrt(np.mean(f**2)) for f in frames])

    threshold = np.max(rms) * 0.05
    active_indices = np.where(rms > threshold)[0]

    if len(active_indices) > 0:
        speech_start_sec = max(0.0, (active_indices[0] * hop_len) / sr - 0.04)
        speech_end_sec = min(total_duration_sec, (active_indices[-1] * hop_len) / sr + 0.06)
    else:
        speech_start_sec = 0.0
        speech_end_sec = total_duration_sec

    usable_duration = speech_end_sec - speech_start_sec
    weights = [calculate_hindi_word_weight(w) for w in raw_words]
    total_weight = sum(weights)

    words_timeline = []
    current_time = speech_start_sec

    for word, weight in zip(raw_words, weights):
        word_dur = (weight / total_weight) * usable_duration
        start_ms = int(current_time * 1000)
        end_ms = int((current_time + word_dur) * 1000)
        
        words_timeline.append({
            "word": word,
            "start_ms": start_ms,
            "end_ms": end_ms
        })
        current_time += word_dur

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(words_timeline, f, ensure_ascii=False, indent=2)

    return words_timeline


# =====================================================================
# 2. FREESOUND API (Clean Foley Filtering + Relevance Search)
# =====================================================================

class FreesoundAudioAPI:
    BASE_URL = "https://freesound.org/apiv2/search/text/"
    HEADERS = {
        "Authorization": f"Token {FREESOUND_API_KEY}",
        "User-Agent": "AudioStoryFoleyBot/3.0"
    }

    # Blacklist irrelevant tags that ruin clean Foley (music, synths, loops, cars/crashes unless asked)
    NEGATIVE_TAG_FILTER = "-tag:music -tag:beat -tag:loop -tag:song -tag:synth -tag:electronic"

    @classmethod
    def clean_query_term(cls, term: str) -> str:
        """Sanitizes text queries for Freesound API."""
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', term)
        return " ".join(cleaned.split())

    @classmethod
    def search_and_download(cls, query: str, fallback_query: str = "") -> Path | None:
        q_clean = cls.clean_query_term(query)
        fb_clean = cls.clean_query_term(fallback_query)

        slug = re.sub(r'[^a-zA-Z0-9_-]', '_', q_clean.strip().lower())
        cached_files = list(SFX_DIR.glob(f"{slug}_*.mp3"))
        if cached_files and cached_files[0].stat().st_size > 1024:
            return cached_files[0]

        # Prioritize search attempts:
        # 1. Exact query with negative filter and duration constraint
        # 2. Fallback query with negative filter
        # 3. First two material words (e.g. 'glass bottle') instead of the last verb (e.g. 'break')
        queries_to_try = [q_clean]
        if fb_clean and fb_clean != q_clean:
            queries_to_try.append(fb_clean)

        words = q_clean.split()
        if len(words) >= 2:
            # Fallback to the object/material itself (e.g., 'glass bottle', 'door wood')
            queries_to_try.append(f"{words[0]} {words[1]}")

        for attempt_query in queries_to_try:
            if not attempt_query.strip():
                continue

            # Sort by "score" (relevance) instead of downloads_desc to prevent generic high-download car crashes
            params = {
                "query": attempt_query,
                "filter": f"duration:[{SFX_MIN_DUR} TO {SFX_MAX_DUR}] {cls.NEGATIVE_TAG_FILTER}",
                "sort": "score",
                "fields": "id,name,previews,duration,num_downloads,rating_avg",
                "page_size": 5
            }

            try:
                resp = requests.get(cls.BASE_URL, headers=cls.HEADERS, params=params, timeout=10)
                if resp.status_code != 200:
                    continue

                results = resp.json().get("results", [])
                
                # If strict negative filter returns nothing, loosen filter slightly
                if not results:
                    params["filter"] = f"duration:[{SFX_MIN_DUR} TO {SFX_MAX_DUR}]"
                    params["sort"] = "rating_desc"
                    resp = requests.get(cls.BASE_URL, headers=cls.HEADERS, params=params, timeout=10)
                    results = resp.json().get("results", []) if resp.status_code == 200 else []

                if results:
                    # Pick the top rated/relevant match
                    chosen = results[0]
                    sound_id = chosen["id"]
                    previews = chosen.get("previews", {})
                    download_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")

                    if not download_url:
                        continue

                    target_file = SFX_DIR / f"{slug}_{sound_id}.mp3"
                    print(f"      🔗 Downloading Freesound #{sound_id} ('{chosen.get('name')[:35]}') for '{attempt_query}'...")

                    audio_resp = requests.get(download_url, headers=cls.HEADERS, timeout=15)
                    if audio_resp.status_code == 200 and len(audio_resp.content) > 1024:
                        with open(target_file, "wb") as f:
                            f.write(audio_resp.content)
                        print(f"      ✅ Saved SFX: {target_file.name}")
                        return target_file

            except Exception as e:
                print(f"      ⚠️ Freesound lookup failed for '{attempt_query}': {e}")

        print(f"      ❌ Freesound: No reasonable sounds found for queries: {queries_to_try}")
        return None


# =====================================================================
# 3. TRANSIENT ONSET DETECTOR
# =====================================================================

def detect_audio_transient_onset(data: np.ndarray, sr: int) -> float:
    if len(data) == 0:
        return 0.0

    peak = np.max(np.abs(data)) + 1e-9
    norm_data = np.abs(data) / peak

    win = max(1, int(sr * 0.01))
    energy = np.convolve(norm_data**2, np.ones(win) / win, mode='same')
    max_e = np.max(energy)

    if max_e < 1e-4:
        return 0.0

    threshold = max_e * 0.08
    indices = np.where(energy >= threshold)[0]
    if len(indices) == 0:
        return 0.0

    onset_sec = indices[0] / float(sr)
    return min(onset_sec, 1.2)


def process_sfx_audio(raw_sfx_path: Path, sound_type: str, max_duration_sec: float, output_path: Path) -> float:
    data, sr = sf.read(str(raw_sfx_path), dtype="float32")
    if data.ndim > 1:
        data = np.mean(data, axis=1)

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

    sf.write(str(output_path), data.astype(np.float32), sr)
    return onset_sec


# =====================================================================
# 4. GROQ SOUND DIRECTOR (Grounded Foley Context)
# =====================================================================

def query_groq_sound_director(beat_id: str, prompt_action: str, narration_text: str, words_timeline: List[Dict]) -> List[Dict]:
    system_instruction = (
        "You are a realistic Foley Sound Editor. Your job is to select physical sound effects "
        "that accurately match the LITERAL objects and actions happening in the Hindi narration.\n\n"
        "STRICT REALISM & MATCHING RULES:\n"
        "1. GROUND TO PHYSICAL OBJECTS: If the scene mentions a bottle, glass, water, cup, book, or door, choose "
        "sounds specifically containing those physical materials (e.g. 'glass clink', 'bottle set on table', 'liquid pouring').\n"
        "2. ABSOLUTELY NO UNPROMPTED DRAMATIC SFX: NEVER output 'car crash', 'explosion', 'gunshot', or 'cinematic hit' "
        "unless a vehicle crash or weapon is explicitly mentioned in the text.\n"
        "3. QUERY FORMAT FOR FREESOUND:\n"
        "   - Use 2-3 precise natural English words describing the exact material and action.\n"
        "   - Good: 'glass bottle clink', 'bottle cork pop', 'pouring water', 'footsteps wood', 'paper turn', 'door creak'\n"
        "   - Bad: 'smash' (too vague), 'break' (causes car crashes), 'dramatic_impact_cinematic_boom'\n"
        "4. DENSITY: Output between 0 and 2 precise cues. If there is no distinct physical interaction, return an empty list [].\n\n"
        "Return strictly a JSON object with this schema:\n"
        "{\n"
        '  "scene_analysis": "One sentence explaining physical objects present",\n'
        '  "sfx_cues": [\n'
        '    {\n'
        '      "freesound_tag": "glass bottle clink",\n'
        '      "fallback_tag": "glass impact",\n'
        '      "sound_type": "transient",\n'
        '      "trigger_word": "Hindi word from the timeline",\n'
        '      "target_ms": integer_start_ms,\n'
        '      "duration_sec": 1.5,\n'
        '      "volume": 0.55\n'
        '    }\n'
        '  ]\n'
        "}"
    )

    user_content = f"""
Beat ID: {beat_id}
Visual Prompt Context: {prompt_action if prompt_action else 'Story scene'}
Spoken Hindi Narration: {narration_text}

Word-by-word Timestamps (ms):
{json.dumps(words_timeline, ensure_ascii=False)}

Identify literal physical materials and objects in the narration and select 0 to 2 matching Foley sound cues.
"""

    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,  # Lower temperature for grounded factual choices
            max_tokens=600
        )
        data = json.loads(completion.choices[0].message.content)
        analysis = data.get("scene_analysis", "")
        if analysis:
            print(f"   🔎 Scene Foley Context: {analysis}")
        return data.get("sfx_cues", [])
    except Exception as e:
        print(f"   ⚠️ Groq Sound Director error on {beat_id}: {e}")
        return []


# =====================================================================
# 5. FINAL AUDIO-VISUAL ASSEMBLY
# =====================================================================

def crop_and_fit_image(img_path: Path, target_w: int, target_h: int) -> np.ndarray:
    img = PIL.Image.open(img_path).convert("RGB")
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    resized = img.resize((new_w, new_h), PIL.Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return np.array(resized.crop((left, top, left + target_w, top + target_h)))


def assemble_story_video_with_dynamic_sfx(aspect_ratio="9:16"):
    if not MANIFEST_FILE.exists():
        print(f"❌ Manifest {MANIFEST_FILE} not found!")
        return

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    script_beats = {}
    if STORY_SCRIPT_FILE.exists():
        with open(STORY_SCRIPT_FILE, "r", encoding="utf-8") as f:
            script_data = json.load(f)
            for sc in script_data.get("scenes", []):
                for bt in sc.get("beats", []):
                    script_beats[bt["beat_id"]] = bt

    target_size = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    video_clips = []
    all_audio_tracks = []
    
    current_timeline_time = 0.0
    beats_list = manifest.get("beats", [])
    print(f"\n🎬 Assembling {len(beats_list)} beats with Grounded Foley...\n")

    for idx, item in enumerate(beats_list):
        beat_id = item["beat_id"]
        narration_file = Path(item["audio_file"])
        frame_file = FRAMES_DIR / f"{beat_id}.png"

        print(f"▶️ Processing Beat [{idx+1}/{len(beats_list)}]: {beat_id}")

        if not frame_file.exists() or not narration_file.exists():
            print(f"   ⚠️ Missing assets for {beat_id}, skipping.")
            continue

        narration_clip = AudioFileClip(str(narration_file))
        beat_dur = narration_clip.duration
        narration_clip = narration_clip.with_start(current_timeline_time)
        all_audio_tracks.append(narration_clip)

        frame_arr = crop_and_fit_image(frame_file, target_size[0], target_size[1])
        v_clip = ImageClip(frame_arr).with_duration(beat_dur)
        video_clips.append(v_clip)

        # 1. Word alignment
        beat_script = script_beats.get(beat_id, {})
        prompt_action = beat_script.get("prompt_action", "")
        narration_text = item.get("subtitle", beat_script.get("narration_text", ""))

        ts_file = TIMESTAMPS_DIR / f"{beat_id}_words.json"
        words_timeline = align_ground_truth_to_audio(
            audio_path=narration_file,
            ground_truth_text=narration_text,
            output_json=ts_file
        )

        # 2. Sound Director Decisions
        sfx_cues = query_groq_sound_director(
            beat_id=beat_id,
            prompt_action=prompt_action,
            narration_text=narration_text,
            words_timeline=words_timeline
        )

        print(f"   🎯 Foley cues chosen: {len(sfx_cues)}")

        # 3. Download & Process Correct SFX
        for sfx_idx, cue in enumerate(sfx_cues):
            tag = cue.get("freesound_tag", "")
            fallback = cue.get("fallback_tag", "")
            sound_type = cue.get("sound_type", "transient")
            target_ms = cue.get("target_ms", 0)
            duration_sec = float(cue.get("duration_sec", 2.0))
            volume = float(cue.get("volume", 0.50))

            print(f"      [{sfx_idx+1}] Searching: '{tag}' (Alt: '{fallback}') | Target: {target_ms}ms")

            raw_sfx = FreesoundAudioAPI.search_and_download(tag, fallback)
            if not raw_sfx:
                continue

            processed_sfx_path = PROCESSED_SFX_DIR / f"{beat_id}_sfx_{sfx_idx}.wav"
            onset_sec = process_sfx_audio(
                raw_sfx_path=raw_sfx,
                sound_type=sound_type,
                max_duration_sec=duration_sec,
                output_path=processed_sfx_path
            )

            target_impact_time = current_timeline_time + (target_ms / 1000.0)
            sfx_start_time = max(0.0, target_impact_time - onset_sec)

            sfx_clip = AudioFileClip(str(processed_sfx_path))
            sfx_clip = sfx_clip.with_volume_scaled(volume).with_start(sfx_start_time)
            all_audio_tracks.append(sfx_clip)

            print(f"         ⚡ Attached @ {sfx_start_time:.2f}s (Attack onset: -{onset_sec*1000:.0f}ms)")

        current_timeline_time += beat_dur
        print(f"   ⏱️ Beat complete. Timeline: {current_timeline_time:.2f}s\n")

    if not video_clips:
        print("❌ No video clips found.")
        return

    final_video = concatenate_videoclips(video_clips, method="compose")

    # 4. Optional BGM bed
    if BGM_FILE.exists():
        print("🎵 Layering Ambient BGM Bed (ducked to 10%)...")
        bgm = AudioFileClip(str(BGM_FILE))
        bgm = afx.audio_loop(bgm, duration=final_video.duration).with_volume_scaled(0.10)
        all_audio_tracks.append(bgm)

    # 5. Render
    print(f"🎛️ Mixing {len(all_audio_tracks)} audio tracks...")
    final_audio = CompositeAudioClip(all_audio_tracks)
    final_video = final_video.with_audio(final_audio)

    print(f"\n🚀 Rendering Final MP4: {OUTPUT_VIDEO}...")
    final_video.write_videofile(
        str(OUTPUT_VIDEO),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="medium"
    )
    print(f"\n🎉 Render complete: {OUTPUT_VIDEO}")


if __name__ == "__main__":
    assemble_story_video_with_dynamic_sfx()