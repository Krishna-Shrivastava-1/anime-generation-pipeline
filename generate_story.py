import os, re, sys, json, subprocess, time, math
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
    print("[ERROR] GROQ_API_KEY secret is required in repository settings!", flush=True)
    sys.exit(1)

groq_client = Groq(api_key=GROQ_API_KEY)
GROQ_MODEL = "llama-3.3-70b-versatile"

DEBUG_DIR = Path("debug"); DEBUG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = Path("build/pipeline_state.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
RUN_LOG = DEBUG_DIR / "run.log"

# Only proxy if explicitly requested via USE_TOR
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

# ==================== PLAYWRIGHT DUCK.AI CONTROLLER ====================

def get_prompt_box(page):
    return page.locator("textarea[name='user-prompt'], textarea[placeholder*='ask' i], textarea").first

def click_ask_button(page):
    try:
        ask_btn = page.locator("button[aria-label*='ask' i], button:has-text('Ask'), button[type='submit']").first
        if ask_btn.count() > 0 and ask_btn.is_visible() and ask_btn.is_enabled():
            ask_btn.click(timeout=1500)
            return True
    except Exception:
        pass

    try:
        return page.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const ask = buttons.find(b => !b.disabled && (
                (b.innerText || '').trim().toLowerCase() === 'ask' ||
                (b.getAttribute('aria-label') || '').toLowerCase().includes('ask') ||
                (b.getAttribute('aria-label') || '').toLowerCase().includes('send')
            ));
            if (ask) { ask.click(); return true; }
            return false;
        }""")
    except Exception:
        return False

def submit_prompt(page, box, text, context):
    box.click()
    page.wait_for_timeout(200)

    page.evaluate("""(val) => {
        const textarea = document.querySelector('textarea');
        if (textarea) {
            textarea.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
            nativeSetter.call(textarea, val);
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }""", text)
    page.wait_for_timeout(300)

    cur_val = page.evaluate("() => document.querySelector('textarea')?.value || ''")
    if not cur_val:
        try: box.fill(text)
        except Exception: pass

    page.wait_for_timeout(300)
    if not click_ask_button(page):
        box.focus()
        box.press("Enter")
    page.wait_for_timeout(500)

def parse_sse_text(raw_sse: str) -> str:
    chunks = []
    for line in raw_sse.splitlines():
        line = line.strip()
        if not line.startswith("data:"): continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]": continue
        try:
            d = json.loads(payload)
            c = d.get("message", "")
            if c: chunks.append(c)
        except Exception: pass
    return "".join(chunks)

def wait_for_duck_response(page, state, max_wait=TEXT_WAIT):
    start = time.time()
    last_text, stable_ticks = "", 0
    page.wait_for_timeout(5000)

    while time.time() - start < max_wait:
        # Graceful handling of HTTP 418
        if state.get("rate_limited"):
            log("[WARN] Duck.ai returned HTTP 418 (Rate limited / Tor IP blocked).")
            return None

        try: page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        except Exception: pass

        if state.get("chat_done") and state.get("raw_stream"):
            parsed_sse = parse_sse_text("".join(state["raw_stream"]))
            if '"beats"' in parsed_sse or '"characters"' in parsed_sse:
                return deep_repair(parsed_sse)

        stop_btn = page.locator("button:has-text('Stop generating'), button:has-text('Stop')")
        is_generating = (stop_btn.count() > 0 and stop_btn.first.is_visible())

        try:
            cur_text = page.evaluate("""() => {
                const blocks = Array.from(document.querySelectorAll('pre code, pre, code'));
                for (let i = blocks.length - 1; i >= 0; i--) {
                    const t = (blocks[i].innerText || '').trim();
                    if (t.includes('{') && t.includes('}')) return t;
                }
                const msgs = Array.from(document.querySelectorAll('article, [class*="message"], main div'));
                for (let i = msgs.length - 1; i >= 0; i--) {
                    const t = (msgs[i].innerText || '').trim();
                    if (t.includes('{') && t.includes('}') && !t.includes('Hindi YouTube movie-recap narrator')) return t;
                }
                return '';
            }""")
            if cur_text and cur_text == last_text and not is_generating:
                stable_ticks += 1
            else:
                stable_ticks = 0
            last_text = cur_text

            if stable_ticks >= 3 and len(last_text) > 40 and ('"beats"' in last_text or '"characters"' in last_text):
                return deep_repair(last_text)
        except Exception: pass

        page.wait_for_timeout(2500)

    if state.get("raw_stream"):
        return deep_repair(parse_sse_text("".join(state["raw_stream"])))
    return deep_repair(last_text)

def start_fresh_browser(p_runner):
    launch_kwargs = {
        "headless": not HEADED,
        "args": ["--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
    }
    if BROWSER_PROXY:
        log(f"Using browser proxy: {BROWSER_PROXY}")
        launch_kwargs["proxy"] = {"server": BROWSER_PROXY}
    else:
        log("Connecting directly (No Tor proxy) to ensure clean access.")

    b = p_runner.chromium.launch(**launch_kwargs)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36")
    pg = ctx.new_page()
    return b, ctx, pg

def duck_ask_json(page, context, prompt):
    state = {"raw_stream": [], "chat_done": False, "rate_limited": False}

    def on_response(resp):
        if "/duckchat/v1/chat" in resp.url and resp.request.method == "POST":
            if resp.status == 418: state["rate_limited"] = True
            try: state["raw_stream"].append(resp.body().decode("utf-8", errors="replace"))
            except Exception: pass
    page.on("response", on_response)

    def on_request_finished(req):
        if req.method == "POST" and "/duckchat/v1/chat" in req.url:
            state["chat_done"] = True
    page.on("requestfinished", on_request_finished)

    box = get_prompt_box(page)
    box.wait_for(state="visible", timeout=40000)
    submit_prompt(page, box, prompt, context)

    for _ in range(10):
        page.wait_for_timeout(1000)
        if "chatID=" in page.url or len(state["raw_stream"]) > 0: break
        click_ask_button(page)
        box.press("Enter")

    raw_resp = wait_for_duck_response(page, state, max_wait=TEXT_WAIT)
    return parse_balanced_json(raw_resp)

# ==================== GROQ ENGINES (SUPERVISOR & FALLBACK) ====================

def groq_discover_context(full_transcript):
    """Fallback context discoverer using Groq if Duck.ai is ever rate-limited."""
    log("Groq Engine: Discovering show title & characters directly from transcript...")
    segments = full_transcript.get("segments", [])
    sample = "\n".join([f"[{s['start']:.1f}s] {s.get('text', '')}" for s in segments[:50]])

    prompt = f"""Identify the movie or TV show title and characters from these dialogues:
{sample}

TASK:
1. Identify the exact show/movie title.
2. List characters with their English name, pure Devanagari Hindi name, and role.

Output STRICT JSON:
{{
  "identified_title": "detected title",
  "characters": [
    {{"name": "Lucifer Morningstar", "hindi_name": "लूसिफ़र", "role": "क्लब मालिक"}},
    {{"name": "Chloe Decker", "hindi_name": "डिटेक्टिव क्लो", "role": "जांच अधिकारी"}},
    {{"name": "Dan Espinoza", "hindi_name": "डिटेक्टिव डैन", "role": "साथी जासूस"}},
    {{"name": "Jimmy Barnes", "hindi_name": "जिमी बार्न्स", "role": "संगीत निर्माता"}},
    {{"name": "2Vile", "hindi_name": "रैपर टू-वाइल", "role": "रैपर"}},
    {{"name": "Trixie", "hindi_name": "ट्रिक्सी", "role": "क्लो की बेटी"}}
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
    """Fallback generator using Groq when Duck.ai is rate-limited."""
    log("Groq Generator: Generating scene beats...")
    prompt = f"""You are a professional Hindi YouTube movie-recap narrator.
Movie/Show: {movie_title}
CHARACTERS: {json.dumps(character_directory, ensure_ascii=False)}

PREVIOUS STORY CONTEXT:
{prev_continuity_str}

SCENE TRANSCRIPT:
{chunk_text}

TASK:
Generate sequential story recap beats for this scene in Hindi Devanagari.
RULES:
1. WORD COUNT: Exactly 8 to 12 words per beat (MAX 13 words).
2. USE REAL NAMES: Use characters' real names (e.g. क्लो, लूसिफ़र, जिमी, टू-वाइल, ट्रिक्सी). Never use 'एक व्यक्ति' or 'कोई'.
3. NATURAL CONTINUITY: Connect scene shifts smoothly.
4. TIMESTAMPS: Extract start_sec and end_sec matching the dialogue timestamps.

Output STRICT JSON:
{{
  "beats": [
    {{
      "narration": "डैन क्लो को बताता है कि हत्या का मुख्य गवाह लूसिफ़र है।",
      "start_sec": 61.15,
      "end_sec": 65.15
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
        return data.get("beats", [])
    except Exception as e:
        log(f"Groq generator failed: {e}")
        return []

def groq_supervise_and_edit_beats(raw_beats, character_directory, scene_title):
    log(f"Groq Editor: Reviewing and trimming beats for '{scene_title}'...")

    prompt = f"""You are the Lead Quality Editor for a high-retention Hindi YouTube recap channel.
Refine these draft beats created from the transcript.

OFFICIAL CHARACTER DIRECTORY:
{json.dumps(character_directory, ensure_ascii=False)}

DRAFT BEATS TO VERIFY:
{json.dumps(raw_beats, ensure_ascii=False, indent=2)}

STRICT EDITORIAL RULES:
1. WORD COUNT LIMIT: Every single beat MUST be between 8 and 12 Hindi words (ABSOLUTE MAXIMUM: 13 words). If a beat is longer, trim unnecessary words without losing the key plot point.
2. NO VAGUE PRONOUNS: Never let characters be called 'एक व्यक्ति' (a person) or 'कोई' (someone). Use their real name from the Character Directory (e.g. 'रैपर टू-वाइल', 'निर्माता जिमी', 'ट्रिक्सी').
3. DEDUPLICATION: If two beats say almost the same thing or have overlapping timestamps, remove the redundant one.
4. DRAMATIC FLOW: Use engaging, high-retention storytelling Hindi.
5. KEEP TIMESTAMPS: Preserve start_sec and end_sec as numbers.

Output STRICT JSON:
{{
  "beats": [
    {{
      "narration": "डैन क्लो को बताता है कि कत्ल का गवाह लूसिफ़र नाम का क्लब मालिक है।",
      "start_sec": 61.15,
      "end_sec": 65.15
    }}
  ]
}}"""
    try:
        res = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        data = json.loads(res.choices[0].message.content)
        return data.get("beats", raw_beats)
    except Exception as e:
        log(f"Groq editor pass skipped: {e}")
        return raw_beats

# ==================== MAIN PIPELINE ====================

with open("transcript.json", "r", encoding="utf-8") as f:
    full_transcript = json.load(f)

with sync_playwright() as p:
    browser, context, page = start_fresh_browser(p)

    if RUN_MODE == "probe":
        log("Testing Duck.ai connection...")
        page.goto("https://duck.ai/chat", wait_until="domcontentloaded", timeout=75000)
        box = get_prompt_box(page); box.wait_for(state="visible", timeout=40000)
        submit_prompt(page, box, 'Reply with: {"ok": true}', context)
        page.wait_for_timeout(5000)
        log("Probe passed.")
        sys.exit(0)

    # PHASE 1: Discovery (Duck.ai live with Groq fallback)
    log("\n[PHASE 1] Live Context & Character Discovery...")
    page.goto("https://duck.ai/chat", wait_until="domcontentloaded", timeout=75000)
    page.wait_for_timeout(3000)

    segments = full_transcript.get("segments", [])
    sample_dialogues = "\n".join([f"[{s['start']:.1f}s] {s.get('text', '')}" for s in segments[:35]])

    discovery_prompt = f"""Identify this movie / TV episode from these dialogue lines:
{sample_dialogues}

TASK:
1. Identify the exact show/movie title.
2. List characters with their English name, pure Devanagari Hindi name, and role (e.g. Chloe Decker -> क्लो, Lucifer Morningstar -> लूसिफ़र, Jimmy Barnes -> जिमी बार्न्स, 2Vile -> टू-वाइल, Beatrice/Trixie -> ट्रिक्सी, Delilah -> डेलाइला).

Return STRICT JSON:
```json
{{
  "identified_title": "detected title",
  "characters": [
    {{"name": "Lucifer Morningstar", "hindi_name": "लूसिफ़र", "role": "क्लब मालिक और मुख्य गवाह"}},
    {{"name": "Chloe Decker", "hindi_name": "डिटेक्टिव क्लो", "role": "मर्डर केस की मुख्य जांच अधिकारी"}},
    {{"name": "Dan Espinoza", "hindi_name": "डिटेक्टिव डैन", "role": "क्लो का पूर्व पति और साथी जासूस"}},
    {{"name": "Jimmy Barnes", "hindi_name": "जिमी बार्न्स", "role": "संगीत निर्माता"}},
    {{"name": "2Vile", "hindi_name": "रैपर टू-वाइल", "role": "नशे का कारोबारी रैपर"}},
    {{"name": "Trixie", "hindi_name": "ट्रिक्सी", "role": "क्लो की नटखट बेटी"}}
  ]
}}
```"""
    discovery_result = duck_ask_json(page, context, discovery_prompt)
    if not discovery_result or "characters" not in discovery_result:
        log("Duck.ai was rate-limited or blocked. Using Groq for Phase 1...")
        discovery_result = groq_discover_context(full_transcript)

    character_directory = discovery_result.get("characters", [])
    movie_title = discovery_result.get("identified_title", full_transcript.get("movie_title", "Movie Recap"))
    log(f"Identified movie: '{movie_title}' with {len(character_directory)} characters.")

    # PHASE 2: Group into natural scenes
    lines = []
    for s in segments:
        s_id = f"S{int(s['id']):04d}"
        lines.append(f"[{s_id} | {float(s['start']):.2f}s - {float(s['end']):.2f}s] {str(s.get('text', '')).strip()}")

    chunks, cur, cur_len = [], [], 0
    for line in lines:
        line_len = len(line) + 1
        if cur_len + line_len > 3000 and cur:
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

    # PHASE 3: Scene Generation (Duck.ai with automatic Groq Fallback)
    for c_idx, chunk_lines in enumerate(chunks):
        chunk_id = f"chunk_{c_idx+1}"
        if chunk_id in pipeline_state.get("completed_chunks", []):
            log(f"Skipping already completed {chunk_id}.")
            continue

        log(f"\n==================== PROCESSING: {chunk_id} ({c_idx+1}/{len(chunks)}) ====================")

        prev_context_lines = []
        if all_beats:
            for b in all_beats[-2:]:
                prev_context_lines.append(f"- {b['narration']} (timestamp: {b['target_window']['start']}s)")
        prev_continuity_str = "\n".join(prev_context_lines) if prev_context_lines else "None (Opening scene)"

        chunk_text = "\n".join(chunk_lines)

        writer_prompt = (
            f"You are a professional Hindi YouTube movie-recap writer.\n"
            f"Movie/Show: {movie_title}\n"
            f"OFFICIAL CHARACTERS: {json.dumps(character_directory, ensure_ascii=False)}\n\n"
            f"PREVIOUS STORY BEATS (CONNECT NATURALLY FROM THIS):\n{prev_continuity_str}\n\n"
            f"CURRENT SCENE TRANSCRIPT:\n{chunk_text}\n\n"
            "WRITING RULES:\n"
            "1. ACCURATE NAMES: Always use the exact Hindi character names from the roster (e.g. क्लो, लूसिफ़र, जिमी, टू-वाइल, ट्रिक्सी). NEVER use vague terms like 'एक व्यक्ति' or 'कोई'.\n"
            "2. CONNECT SCENE JUMPS: If the scene shifts, explain the movement (e.g. 'यह सुनकर क्लो सीधे लूसिफ़र से पूछताछ करने मौका-ए-वारदात पर पहुँचती है...').\n"
            "3. NATURAL PACING: Generate a beat every 15-30 seconds of meaningful plot progression.\n"
            "4. OUTPUT STRICT JSON ONLY:\n"
            "```json\n"
            "{\n"
            '  "beats": [\n'
            '    {"narration": "डैन क्लो को बताता है कि हत्या का गवाह लूसिफ़र मॉर्निंगस्टार नाम का क्लब मालिक है।", "start_sec": 61.15, "end_sec": 65.15}\n'
            '  ]\n'
            "}\n"
            "```"
        )

        raw_chunk_json = duck_ask_json(page, context, writer_prompt)
        raw_beats = raw_chunk_json.get("beats", []) if raw_chunk_json else []

        # If Duck.ai returned 418 or empty, seamlessly use Groq generator
        if not raw_beats:
            log(f"Duck.ai unavailable for {chunk_id}. Activating Groq Generator...")
            raw_beats = groq_generate_scene_beats(chunk_text, movie_title, character_directory, prev_continuity_str)

        # Groq Supervisor: Trims words to 8-12 and removes duplicate beats
        polished_beats = groq_supervise_and_edit_beats(raw_beats, character_directory, f"Act {c_idx+1}")

        for b in polished_beats:
            st_s = round(float(b.get("start_sec", 0.0)), 2)
            en_s = round(float(b.get("end_sec", st_s + 4.0)), 2)
            if en_s <= st_s or (en_s - st_s) < 2.0: en_s = round(st_s + 3.8, 2)
            elif (en_s - st_s) > 5.0: en_s = round(st_s + 4.2, 2)

            narr = deep_repair(b.get("narration", "")).strip()
            words = narr.split()

            if all_beats and st_s <= all_beats[-1]["target_window"]["start"]:
                continue

            beat_obj = {
                "beat_id": f"B{len(all_beats)+1:04d}",
                "narration": narr,
                "target_window": {"start": st_s, "end": en_s},
                "portion": {"start": st_s, "end": en_s},
                "duration": round(en_s - st_s, 2),
                "word_count": len(words)
            }
            all_beats.append(beat_obj)

        pipeline_state.setdefault("completed_chunks", []).append(chunk_id)
        pipeline_state["beats"] = all_beats

        with open(STATE_FILE, "w", encoding="utf-8") as sf:
            json.dump(pipeline_state, sf, indent=2, ensure_ascii=False)

        log(f"SUCCESS: {chunk_id} completed. Total beats so far: {len(all_beats)}")
        page.wait_for_timeout(1000)

    final_output = {
        "movie_title": movie_title,
        "characters": character_directory,
        "total_beats": len(all_beats),
        "total_words": sum(b["word_count"] for b in all_beats),
        "average_words_per_beat": round(sum(b["word_count"] for b in all_beats) / max(1, len(all_beats)), 1),
        "beats": all_beats
    }

    Path("story_beats.json").write_text(json.dumps(final_output, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"COMPLETE: story_beats.json written with {len(all_beats)} beats (~{final_output['total_words']} words).")
    if browser: browser.close()
