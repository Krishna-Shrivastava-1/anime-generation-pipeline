import os, re, sys, json, time
from pathlib import Path
from playwright.sync_api import sync_playwright
import ftfy
from groq import Groq

if sys.platform != "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

HEADED = os.environ.get("HEADED") == "true"
USE_TOR = os.environ.get("USE_TOR", "false").strip().lower() == "true"
RUN_MODE = os.environ.get("RUN_MODE", "full").strip().lower()
RESET_STATE = os.environ.get("RESET_STATE", "false").strip().lower() == "true"
TEXT_WAIT = int(os.environ.get("TEXT_WAIT_SECONDS", "180"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

if not GROQ_API_KEY:
    print("[ERROR] GROQ_API_KEY secret is required!", flush=True)
    sys.exit(1)

groq_client = Groq(api_key=GROQ_API_KEY)
GROQ_MODEL = "openai/gpt-oss-120b"

DEBUG_DIR = Path("debug"); DEBUG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = Path("build/pipeline_state.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
RUN_LOG = DEBUG_DIR / "run.log"

BROWSER_PROXY = "socks5://127.0.0.1:9050" if USE_TOR else None

if RESET_STATE and STATE_FILE.exists():
    STATE_FILE.unlink()
    print("[INIT] Cache cleared for fresh regeneration.", flush=True)

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def fix_mojibake(s):
    if not isinstance(s, str) or not s: return s
    try: s = ftfy.fix_text(s)
    except Exception: pass
    if any(m in s for m in ["à¤", "à¥", "â€™", "â€”", "Ã", "Â"]):
        try: return s.encode("cp1252").decode("utf-8")
        except Exception: pass
    return s

def deep_repair(val):
    if isinstance(val, str): return fix_mojibake(val)
    if isinstance(val, list): return [deep_repair(i) for i in val]
    if isinstance(val, dict): return {k: deep_repair(v) for k, v in val.items()}
    return val

def clean_json_text(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    return re.sub(r"\s*```$", "", text.strip())

def parse_balanced_json(text: str):
    if not text: return None
    cleaned = clean_json_text(text)
    try: return deep_repair(json.loads(cleaned))
    except Exception: pass
    start = cleaned.find("{")
    if start == -1: return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(cleaned)):
        c = cleaned[i]
        if esc: esc = False; continue
        if c == "\\": esc = True; continue
        if c == '"': in_str = not in_str; continue
        if not in_str:
            if c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try: return deep_repair(json.loads(cleaned[start:i+1]))
                    except Exception: break
    return None

# ==================== GROQ STORYTELLING RECAP ENGINES ====================

def groq_discover_context(full_transcript):
    log("Groq Engine: Discovering show title & characters directly from transcript...")
    segments = full_transcript.get("segments", [])
    sample = "\n".join([f"[{s['start']:.1f}s] {s.get('text', '')}" for s in segments[:50]])

    prompt = f"""Identify the movie or TV show title and characters from these dialogues:
{sample}

TASK:
1. Identify the exact show/movie title.
2. List characters with their English name, pure Devanagari Hindi name, and dramatic role.

Output STRICT JSON:
{{
  "identified_title": "detected title",
  "characters": [
    {{"name": "Lucifer Morningstar", "hindi_name": "लूसिफ़र", "role": "क्लब का रहस्यमयी मालिक"}},
    {{"name": "Chloe Decker", "hindi_name": "डिटेक्टिव क्लो", "role": "केस की मुख्य जांच अधिकारी"}},
    {{"name": "Dan Espinoza", "hindi_name": "डिटेक्टिव डैन", "role": "क्लो का पूर्व पति और साथी जासूस"}}
  ]
}}"""
    try:
        res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        log(f"Groq context discovery failed: {e}")
        return {"identified_title": "Lucifer Pilot", "characters": []}

def groq_generate_scene_beats(chunk_text, movie_title, character_directory, prev_continuity_str):
    """Generates engaging, high-retention Hindi YouTube recap beats."""
    log("Groq Generator: Writing professional YouTube recap narration...")
    prompt = f"""You are India's top Hindi YouTube Movie Recap voiceover writer (like 'Mystery Recapped' / 'Haunting Tube').
Movie/Show: {movie_title}
CHARACTERS: {json.dumps(character_directory, ensure_ascii=False)}

PREVIOUS STORY CONTEXT:
{prev_continuity_str}

SCENE TRANSCRIPT WITH TIMESTAMPS:
{chunk_text}

MANDATORY RULES FOR YOUTUBE RECAP QUALITY:
1. NATURAL SPOKEN HINDI: Write fluid, dramatic, grammatically complete sentences.
   - BAD (Robotic): "डैन चेतावनी देता, क्लो गवाह लूसिफ़र का नाम सुनती।"
   - GOOD (Engaging): "डैन की चेतावनियों को नजरअंदाज करते हुए, क्लो को पता चलता है कि इस मर्डर का इकलौता गवाह लूसिफ़र है।"
2. GRAMMAR & VERBS: NEVER drop auxiliary verbs like 'है', 'था', 'रहा है', 'होता है', or postpositions like 'ने', 'को', 'की'.
3. LENGTH: Each beat must be between 14 and 20 Hindi words (approx. 4 to 6 seconds spoken).
4. CONTINUITY: Connect events smoothly using cinematic hooks (e.g. "इसके बाद", "तभी अचानक", "क्लो को शक होता है कि").
5. ACCURACY: Use real names (लूसिफ़र, क्लो, डैन, जैला). Never use vague terms like 'एक आदमी' or 'कोई'.

Output STRICT JSON:
{{
  "beats": [
    {{
      "narration": "कहानी के इस मोड़ पर क्लो मर्डर सीन पर पहुंचती है, जहां डैन उसे केस जल्दी बंद करने की सलाह देता है।",
      "start_sec": 0.72,
      "end_sec": 5.80
    }}
  ]
}}"""
    try:
        res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        data = json.loads(res.choices[0].message.content)
        return data.get("beats", [])
    except Exception as e:
        log(f"Groq generator failed: {e}")
        return []

def groq_supervise_and_edit_beats(raw_beats, character_directory, scene_title):
    """Polishes script for flow, grammar, and viewer engagement."""
    log(f"Groq Editor: Verifying storytelling tone & Hindi grammar for '{scene_title}'...")

    prompt = f"""You are the Lead Script Editor for a major Hindi YouTube Recap Channel.
Review and polish these narration beats.

CHARACTERS:
{json.dumps(character_directory, ensure_ascii=False)}

DRAFT BEATS:
{json.dumps(raw_beats, ensure_ascii=False, indent=2)}

EDITORIAL CRITERIA:
1. FIX BROKEN GRAMMAR: If a beat sounds robotic or telegram-style, rewrite it into smooth, natural, spoken Hindi.
2. COMPLETE SENTENCES: Every beat MUST end with a valid verb phrase (जैसे: 'करता है', 'हो जाती है', 'निकल पड़ता है').
3. LENGTH: Keep sentences between 13 and 20 words. Do NOT chop off words if it hurts sentence meaning.
4. HIGH RETENTION: Make it sound suspenseful and engaging for YouTube viewers.
5. KEEP TIMESTAMPS: Keep original start_sec and calculate a realistic end_sec based on speech pacing.

Output STRICT JSON:
{{
  "beats": [
    {{
      "narration": "डैन की चेतावनियों के बावजूद, क्लो इस मर्डर केस की तह तक जाने के लिए क्लब के मालिक लूसिफ़र से मिलती है।",
      "start_sec": 45.75,
      "end_sec": 51.50
    }}
  ]
}}"""
    try:
        res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.25
        )
        data = json.loads(res.choices[0].message.content)
        return data.get("beats", raw_beats)
    except Exception as e:
        log(f"Groq editor pass skipped: {e}")
        return raw_beats

# ==================== MAIN PIPELINE ====================

with open("transcript.json", "r", encoding="utf-8") as f:
    full_transcript = json.load(f)

# Discovery Pass
discovery_result = groq_discover_context(full_transcript)
character_directory = discovery_result.get("characters", [])
movie_title = discovery_result.get("identified_title", full_transcript.get("movie_title", "Movie Recap"))
log(f"Identified Title: '{movie_title}' with {len(character_directory)} characters.")

segments = full_transcript.get("segments", [])
lines = []
for s in segments:
    s_id = f"S{int(s['id']):04d}"
    lines.append(f"[{s_id} | {float(s['start']):.2f}s - {float(s['end']):.2f}s] {str(s.get('text', '')).strip()}")

chunks, cur, cur_len = [], [], 0
for line in lines:
    line_len = len(line) + 1
    if cur_len + line_len > 3500 and cur:
        chunks.append(list(cur))
        cur = list(cur[-3:]) if len(cur) >= 3 else list(cur)
        cur_len = sum(len(l) + 1 for l in cur)
    cur.append(line)
    cur_len += line_len
if cur: chunks.append(cur)

pipeline_state = {"completed_chunks": [], "beats": [], "characters": character_directory}
if STATE_FILE.exists():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as sf:
            pipeline_state = deep_repair(json.load(sf))
    except Exception: pass

all_beats = pipeline_state.get("beats", [])

for c_idx, chunk_lines in enumerate(chunks):
    chunk_id = f"chunk_{c_idx+1}"
    if chunk_id in pipeline_state.get("completed_chunks", []):
        log(f"Skipping completed {chunk_id}.")
        continue

    log(f"\n==================== PROCESSING: {chunk_id} ({c_idx+1}/{len(chunks)}) ====================")

    prev_context_lines = []
    if all_beats:
        for b in all_beats[-2:]:
            prev_context_lines.append(f"- {b['narration']}")
    prev_continuity_str = "\n".join(prev_context_lines) if prev_context_lines else "None (Opening scene)"

    chunk_text = "\n".join(chunk_lines)

    # Generate dramatic, connected recap beats
    raw_beats = groq_generate_scene_beats(chunk_text, movie_title, character_directory, prev_continuity_str)
    polished_beats = groq_supervise_and_edit_beats(raw_beats, character_directory, f"Scene {c_idx+1}")

    for b in polished_beats:
        narr = deep_repair(b.get("narration", "")).strip()
        words = narr.split()
        word_count = len(words)

        st_s = round(float(b.get("start_sec", 0.0)), 2)
        
        # Realistic voiceover pacing: ~3.0 Hindi words per second (min 3.5s, max 7.5s)
        estimated_duration = max(3.5, min(7.5, round(word_count / 3.0, 2)))
        en_s = round(st_s + estimated_duration, 2)

        if all_beats and st_s <= all_beats[-1]["target_window"]["start"]:
            st_s = round(all_beats[-1]["target_window"]["end"] + 0.5, 2)
            en_s = round(st_s + estimated_duration, 2)

        beat_obj = {
            "beat_id": f"B{len(all_beats)+1:04d}",
            "narration": narr,
            "target_window": {"start": st_s, "end": en_s},
            "portion": {"start": st_s, "end": en_s},
            "duration": round(en_s - st_s, 2),
            "word_count": word_count
        }
        all_beats.append(beat_obj)

    pipeline_state.setdefault("completed_chunks", []).append(chunk_id)
    pipeline_state["beats"] = all_beats

    with open(STATE_FILE, "w", encoding="utf-8") as sf:
        json.dump(pipeline_state, sf, indent=2, ensure_ascii=False)

    log(f"SUCCESS: {chunk_id} processed. Beats added: {len(polished_beats)}")

final_output = {
    "movie_title": movie_title,
    "characters": character_directory,
    "total_beats": len(all_beats),
    "total_words": sum(b["word_count"] for b in all_beats),
    "average_words_per_beat": round(sum(b["word_count"] for b in all_beats) / max(1, len(all_beats)), 1),
    "beats": all_beats
}

Path("story_beats.json").write_text(json.dumps(final_output, ensure_ascii=False, indent=2), encoding="utf-8")
log(f"\n[DONE] High-quality recap exported to story_beats.json ({len(all_beats)} beats). Ready for voiceover!")
