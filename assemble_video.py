import os
import json
from pathlib import Path
import numpy as np
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

BUILD_DIR = Path("build")
FRAMES_DIR = BUILD_DIR / "frames"
AUDIO_DIR = BUILD_DIR / "audio"
MANIFEST_FILE = BUILD_DIR / "audio_manifest.json"
OUTPUT_VIDEO = BUILD_DIR / "final_story_video.mp4"
BGM_FILE = Path("bgm.mp3")  # Optional background music file


def crop_and_fit_image(img_path: Path, target_w: int, target_h: int) -> np.ndarray:
    img = PIL.Image.open(img_path).convert("RGB")
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    resized = img.resize((new_w, new_h), PIL.Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return np.array(resized.crop((left, top, left + target_w, top + target_h)))


def assemble_story_video(aspect_ratio="9:16"):
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    target_size = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    clips = []
    print(f"\n🎬 Assembling Story Video [{aspect_ratio}]...")

    for item in manifest.get("beats", []):
        beat_id = item["beat_id"]
        audio_path = Path(item["audio_file"])
        frame_path = FRAMES_DIR / f"{beat_id}.png"

        if not frame_path.exists() or not audio_path.exists():
            continue

        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        frame_arr = crop_and_fit_image(frame_path, target_size[0], target_size[1])
        clip = ImageClip(frame_arr).with_duration(duration).with_audio(audio_clip)
        clips.append(clip)
        print(f" -> Attached {beat_id} ({duration:.2f}s)")

    final_video = concatenate_videoclips(clips, method="compose")

    # If background music is present, mix it cleanly underneath the voice
    if BGM_FILE.exists():
        print("🎵 Mixing ambient background music (ducked to 12% volume)...")
        bgm = AudioFileClip(str(BGM_FILE))
        # Loop BGM to match video length and lower volume
        bgm = afx.audio_loop(bgm, duration=final_video.duration).volumex(0.12)
        # Combine voice track and music track
        mixed_audio = CompositeAudioClip([final_video.audio, bgm])
        final_video = final_video.with_audio(mixed_audio)

    print("\nRendering final MP4...")
    final_video.write_videofile(
        str(OUTPUT_VIDEO),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="medium"
    )
    print(f"\n🎉 VIDEO READY: {OUTPUT_VIDEO}")


if __name__ == "__main__":
    assemble_story_video()