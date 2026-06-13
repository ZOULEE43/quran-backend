#!/usr/bin/env python3
"""
Quran Reels Video Generator - Video Background Version
Matches reference video style:
  - Full-frame nature video backgrounds (looping)
  - Large Arabic Quran text (bottom-center) with tashkeel
  - English translation below
  - Fade in/out per ayah
"""

import os, sys, json, uuid, shutil, threading, subprocess, tempfile, random
import zipfile, urllib.request, math, time
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import requests as req
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np

app = Flask(__name__)
CORS(app)

BASE_DIR          = Path(__file__).parent.resolve()
AUDIO_DIR         = BASE_DIR / "audio"
OUTPUTS_DIR       = BASE_DIR / "outputs"
FONTS_DIR         = BASE_DIR / "fonts"
FFMPEG_DIR        = BASE_DIR / "ffmpeg_bin"
NATURE_VIDEOS_DIR = BASE_DIR / "nature_videos"

for d in [AUDIO_DIR, OUTPUTS_DIR, FONTS_DIR, FFMPEG_DIR, NATURE_VIDEOS_DIR]:
    d.mkdir(exist_ok=True)

QURAN_API = "https://api.alquran.cloud/v1"
jobs: dict = {}

W, H   = 1080, 1920
WR, HR = 540, 960  # Working resolution (half for faster processing)
FPS    = 25

# ─── Video themes ─────────────────────────────────────────────────────────────
# Dark/Moody aesthetic themes for cinematic Quran videos
# Videos will be automatically converted to 1080x1920 (9:16 portrait)
SAMPLE_VIDEO_URLS = {
    "city_night": [
        # Urban nightscapes - city lights, bridges, traffic at night
        "https://videos.pexels.com/video-files/25401841/11901201_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/35795012/15175692_360_640_30fps.mp4",
    ],
    "stars": [
        # Starry skies
        "https://videos.pexels.com/video-files/27638338/12191399_360_640_25fps.mp4",
        "https://videos.pexels.com/video-files/14374617/14374617-sd_360_640_30fps.mp4",
    ],
    "foggy_forest": [
        # Foggy forests
        "https://videos.pexels.com/video-files/27733274/12214514_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/28462206/12391042_360_640_60fps.mp4",
    ],
    "ocean": [
        # Ocean waves at night
        "https://videos.pexels.com/video-files/9807229/9807229-sd_360_640_25fps.mp4",
        "https://videos.pexels.com/video-files/35072027/14856538_360_640_30fps.mp4",
    ],
    "clouds": [
        # Surreal clouds / view from above
        "https://videos.pexels.com/video-files/33638648/14295167_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/33637604/14294522_360_640_30fps.mp4",
    ],
    "space": [
        # Earth from space
        "https://videos.pexels.com/video-files/36991202/15670190_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/36964023/15660037_360_640_30fps.mp4",
    ],
    "cabin": [
        # Solitary cabin on cliffside
        "https://videos.pexels.com/video-files/33848483/14364927_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/29868624/12823722_360_640_30fps.mp4",
    ],
    "autumn_path": [
        # Warm garden path in autumn
        "https://videos.pexels.com/video-files/36629135/15529516_360_640_60fps.mp4",
        "https://videos.pexels.com/video-files/18753492/18753492-sd_360_640_25fps.mp4",
    ],
    "mystical": [
        # Glowing spirits / mystical forest
        "https://videos.pexels.com/video-files/35447137/15017806_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/15659127/15659127-sd_360_640_30fps.mp4",
    ],
    "rain": [
        # Rain / moody atmosphere
        "https://videos.pexels.com/video-files/29507693/12702052_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/32457244/13842736_360_640_30fps.mp4",
    ],
}

# Theme list includes "auto" for automatic assignment
NATURE_THEMES = ["auto"] + list(SAMPLE_VIDEO_URLS.keys())


# ─── FFmpeg ────────────────────────────────────────────────────────────────────
def _find_exe(name):
    for ext in ("", ".exe"):
        p = FFMPEG_DIR / (name + ext)
        if p.exists(): return str(p)
    found = shutil.which(name)
    if found: return found
    # Windows paths
    for d in [Path("C:/ffmpeg/bin"), Path("C:/Program Files/ffmpeg/bin"),
              Path(os.environ.get("LOCALAPPDATA","")) / "ffmpeg/bin",
              Path(os.environ.get("USERPROFILE",""))  / "ffmpeg/bin"]:
        p = d / (name + ".exe")
        if p.exists(): return str(p)
    # Linux/Docker paths
    for d in [Path("/usr/bin"), Path("/usr/local/bin"), Path("/bin")]:
        p = d / name
        if p.exists(): return str(p)
    return None

def _dl_ffmpeg_win():
    url = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/"
           "latest/ffmpeg-master-latest-win64-gpl.zip")
    zp = FFMPEG_DIR / "ff.zip"
    print("Downloading FFmpeg...")
    urllib.request.urlretrieve(url, zp)
    with zipfile.ZipFile(zp) as z:
        for m in z.namelist():
            fn = Path(m).name
            if fn in ("ffmpeg.exe","ffprobe.exe"):
                (FFMPEG_DIR / fn).write_bytes(z.read(m))
    zp.unlink(missing_ok=True)

def get_ffmpeg():
    e = _find_exe("ffmpeg")
    if not e:
        if sys.platform == "win32": _dl_ffmpeg_win(); e = _find_exe("ffmpeg")
        if not e:
            raise RuntimeError(
                "FFmpeg not found! "
                "On Linux/Docker run: apt-get install -y ffmpeg  "
                "On Windows: copy ffmpeg.exe to ffmpeg_bin/"
            )
    return e

def get_ffprobe():
    e = _find_exe("ffprobe")
    if not e:
        ff = _find_exe("ffmpeg")
        if ff:
            ext = ".exe" if sys.platform == "win32" else ""
            c = str(Path(ff).parent / f"ffprobe{ext}")
            if os.path.exists(c): return c
    return e or get_ffmpeg().replace("ffmpeg","ffprobe")

def run_ff(args, progress_cb=None, pct_start=87, pct_end=98, total_frames=0):
    resolved = [get_ffmpeg() if a=="ffmpeg" else
                get_ffprobe() if a=="ffprobe" else a for a in args]
    
    # Add -nostdin to prevent stdin blocking and -loglevel for cleaner output
    if resolved[0].endswith("ffmpeg") or resolved[0].endswith("ffmpeg.exe"):
        resolved = [resolved[0], "-nostdin"] + resolved[1:]

    # Use PIPE only for stderr, stdout not needed for FFmpeg
    proc = subprocess.Popen(
        resolved,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=1,  # Line buffered
    )

    stderr_lines = []
    last_frame   = [0]
    done_event = threading.Event()

    def drain_stderr():
        try:
            while not done_event.is_set():
                try:
                    raw = proc.stderr.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if not line:
                        continue
                    stderr_lines.append(line)
                    if progress_cb and total_frames > 0 and "frame=" in line:
                        try:
                            part = line.split("frame=")[1].split()[0].strip()
                            f = int(part)
                            if f > last_frame[0]:
                                last_frame[0] = f
                                pct = pct_start + int((f / total_frames) * (pct_end - pct_start))
                                fps_str = ""
                                if "fps=" in line:
                                    fps_parts = line.split("fps=")[1].split()
                                    if fps_parts:
                                        fps_str = " | " + fps_parts[0] + " fps"
                                progress_cb(min(pct, pct_end),
                                            f"ترميز: {f}/{total_frames} إطار{fps_str}")
                        except Exception:
                            pass
                except Exception:
                    break
        except Exception:
            pass

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()

    try:
        proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        done_event.set()
        t.join(timeout=5)
        raise RuntimeError("FFmpeg تجاوز وقت الانتظار (10 دقائق)")
    
    done_event.set()
    t.join(timeout=10)

    if proc.returncode != 0:
        err = "\n".join(stderr_lines[-30:])
        raise RuntimeError(f"FFmpeg exit {proc.returncode}:\n{err}")

    return proc


# ─── Fonts ─────────────────────────────────────────────────────────────────────
FONT_URLS = {
    "ScheherazadeNew-Regular.ttf": [
        "https://github.com/silnrsi/font-scheherazade/releases/download/v3.300/ScheherazadeNew-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/scheherazadenew/ScheherazadeNew-Regular.ttf",
    ],
    "AmiriQuran.ttf": [
        "https://github.com/alif-type/amiri/releases/download/v0.110/AmiriQuran.ttf",
        "https://github.com/google/fonts/raw/main/ofl/amiriquran/AmiriQuran.ttf",
    ],
    "Amiri-Regular.ttf": [
        "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf",
        "https://github.com/alif-type/amiri/releases/download/v0.110/Amiri-Regular.ttf",
    ],
}

def _try_dl(url, dst):
    try:
        import urllib3; urllib3.disable_warnings()
    except: pass
    for verify in (True, False):
        try:
            r = req.get(url, timeout=30, verify=verify,
                        headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) > 50000:
                dst.write_bytes(r.content); return True
        except: pass
    try:
        import ssl; ctx = ssl.create_default_context()
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, context=ctx, timeout=30) as resp:
            data = resp.read()
        if len(data) > 50000: dst.write_bytes(data); return True
    except: pass
    return False

def ensure_fonts():
    for fn, urls in FONT_URLS.items():
        dst = FONTS_DIR / fn
        if dst.exists() and dst.stat().st_size > 50000: continue
        print(f"  Downloading {fn}...")
        for url in urls:
            if _try_dl(url, dst):
                print(f"  OK: {fn}"); break
        else:
            print(f"  WARN: {fn} not downloaded")

def get_arabic_font(size):
    ensure_fonts()
    priority = ["AmiriQuran.ttf", "Amiri-Regular.ttf", "Amiri-Quran.ttf",
                "NotoNaskhArabic-Regular.ttf", "ScheherazadeNew-Regular.ttf"]
    for fn in priority:
        p = FONTS_DIR / fn
        if p.exists() and p.stat().st_size > 50000:
            try: return ImageFont.truetype(str(p), size)
            except: pass
    return ImageFont.load_default()

def get_latin_font(size):
    candidates = [
        # Windows
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/serif.ttf",
        # Linux / Docker
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()


# ─── Arabic shaping ─────────────────────────────────────────────────────────────
def _install_arabic_libs():
    try:
        import arabic_reshaper; from bidi.algorithm import get_display; return True
    except ImportError: pass
    try:
        r = subprocess.run([sys.executable,"-m","pip","install",
                            "arabic-reshaper","python-bidi","-q"],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except: return False

def shape_arabic(text):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaper = arabic_reshaper.ArabicReshaper(
            configuration={"delete_harakat": False, "support_ligatures": True})
        return get_display(reshaper.reshape(text))
    except Exception:
        pass
    try:
        from bidi.algorithm import get_display
        return get_display(text)
    except Exception:
        pass

    TASHKEEL = set("ًٌٍَؘُؙِؚّْٰٕٖۣ۪ۭٓٔٗ٘ؐؑؒؓؔؕؖؗۖۗۘۙۚۛۜ۟۠ۡۢۤۧۨ۫۬")
    LAM_ALEF = {
        ("ل", "آ"): ("ﻵ", "ﻶ"), ("ل", "أ"): ("ﻷ", "ﻸ"),
        ("ل", "إ"): ("ﻹ", "ﻺ"), ("ل", "ا"): ("ﻻ", "ﻼ"),
    }
    FORMS = {
        "آ": ("آ", "آ", "آ", "ﺂ"), "أ": ("أ", "أ", "أ", "ﺄ"),
        "ؤ": ("ؤ", "ؤ", "ؤ", "ﺆ"), "إ": ("إ", "إ", "إ", "ﺈ"),
        "ئ": ("ﺉ", "ﺋ", "ﺌ", "ﺊ"), "ا": ("ا", "ا", "ا", "ﺎ"),
        "ب": ("ﺏ", "ﺑ", "ﺒ", "ﺐ"), "ة": ("ﺓ", "ﺓ", "ﺓ", "ﺔ"),
        "ت": ("ﺕ", "ﺗ", "ﺘ", "ﺖ"), "ث": ("ﺙ", "ﺛ", "ﺜ", "ﺚ"),
        "ج": ("ﺝ", "ﺟ", "ﺠ", "ﺞ"), "ح": ("ﺡ", "ﺣ", "ﺤ", "ﺢ"),
        "خ": ("ﺥ", "ﺧ", "ﺨ", "ﺦ"), "د": ("ﺩ", "ﺩ", "ﺩ", "ﺪ"),
        "ذ": ("ﺫ", "ﺫ", "ﺫ", "ﺬ"), "ر": ("ﺭ", "ﺭ", "ﺭ", "ﺮ"),
        "ز": ("ﺯ", "ﺯ", "ﺯ", "ﺰ"), "س": ("ﺱ", "ﺳ", "ﺴ", "ﺲ"),
        "ش": ("ﺵ", "ﺷ", "ﺸ", "ﺶ"), "ص": ("ﺹ", "ﺻ", "ﺼ", "ﺺ"),
        "ض": ("ﺽ", "ﺿ", "ﻀ", "ﺾ"), "ط": ("ﻁ", "ﻃ", "ﻄ", "ﻂ"),
        "ظ": ("ﻅ", "ﻇ", "ﻈ", "ﻆ"), "ع": ("ﻉ", "ﻋ", "ﻌ", "ﻊ"),
        "غ": ("ﻍ", "ﻏ", "ﻐ", "ﻎ"), "ف": ("ﻑ", "ﻓ", "ﻔ", "ﻒ"),
        "ق": ("ﻕ", "ﻗ", "ﻘ", "ﻖ"), "ك": ("ﻙ", "ﻛ", "ﻜ", "ﻚ"),
        "ل": ("ﻝ", "ﻟ", "ﻠ", "ﻞ"), "م": ("ﻡ", "ﻣ", "ﻤ", "ﻢ"),
        "ن": ("ﻥ", "ﻧ", "ﻨ", "ﻦ"), "ه": ("ﻩ", "ﻫ", "ﻬ", "ﻪ"),
        "و": ("ﻭ", "ﻭ", "ﻭ", "ﻮ"), "ى": ("ﻯ", "ﻱ", "ﻲ", "ﻰ"),
        "ي": ("ﻱ", "ﻳ", "ﻴ", "ﻲ"),
    }
    NO_NEXT = {"ء","آ","أ","ؤ","إ","ا","ة","د","ذ","ر","ز","و"}
    def _is_ar(c): return "؀" <= c <= "ۿ"

    clean = "".join(c for c in text if c not in TASHKEEL)
    result = []
    for word in clean.split(" "):
        chars = list(word); n = len(chars); out = []; i = 0
        while i < n:
            c = chars[i]
            if i < n-1 and (c, chars[i+1]) in LAM_ALEF:
                prev_ok = (i > 0 and chars[i-1] in FORMS
                           and chars[i-1] not in NO_NEXT and _is_ar(chars[i-1]))
                iso_f, fin_f = LAM_ALEF[(c, chars[i+1])]
                out.append(fin_f if prev_ok else iso_f)
                i += 2; continue
            if c not in FORMS: out.append(c); i += 1; continue
            prev_ok = (i > 0 and chars[i-1] in FORMS
                       and chars[i-1] not in NO_NEXT and _is_ar(chars[i-1]))
            next_ok = (i < n-1 and chars[i+1] in FORMS
                       and c not in NO_NEXT and _is_ar(chars[i+1]))
            iso, ini, med, fin = FORMS[c]
            if prev_ok and next_ok: out.append(med)
            elif prev_ok:           out.append(fin)
            elif next_ok:           out.append(ini)
            else:                   out.append(iso)
            i += 1
        result.append("".join(reversed(out)))
    return " ".join(reversed(result))


# ─── Video download ─────────────────────────────────────────────────────────────
def download_video(theme, index, progress_cb=None):
    if theme == "auto":
        return None  # Let get_auto_videos handle this
    
    if theme not in SAMPLE_VIDEO_URLS:
        return None
    
    urls = SAMPLE_VIDEO_URLS.get(theme, [])
    if not urls:
        return None
    
    url = urls[index % len(urls)]
    
    # Skip placeholder URLs
    if "example.com" in url or url.startswith("https://example.com"):
        print(f"  Skipping placeholder URL for {theme}_{index}")
        return None
        
    dst = NATURE_VIDEOS_DIR / f"{theme}_{index}.mp4"
    dst = NATURE_VIDEOS_DIR / f"{theme}_{index}.mp4"
    
    if dst.exists() and dst.stat().st_size > 500000:
        return str(dst)
    
    if progress_cb:
        progress_cb(2, f"تحميل فيديو {theme}...")
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = req.get(url, headers=headers, timeout=120, stream=True)
        if r.status_code == 200:
            with open(dst, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if dst.stat().st_size > 500000:
                print(f"  Video OK: {theme}_{index}.mp4 ({dst.stat().st_size // 1024}KB)")
                return str(dst)
    except Exception as e:
        print(f"  Video download failed for {theme}_{index}: {e}")
    
    return None

def get_videos(theme, count, progress_cb=None):
    """Get videos for a theme. If theme=auto or local videos exist, use them."""
    # Always prefer local videos regardless of theme
    local = get_local_videos()
    if local:
        if progress_cb:
            progress_cb(6, f"استخدام {len(local)} فيديو محلي...")
        return [local[i % len(local)] for i in range(count)]

    # Download by theme
    videos = []
    themes_to_try = [theme] + [t for t in NATURE_THEMES if t != theme and t != "auto"]
    for i in range(count):
        for try_theme in themes_to_try:
            v = download_video(try_theme, i % 3,
                               progress_cb if (i == 0 and try_theme == theme) else None)
            if v:
                videos.append(v)
                break
        if len(videos) <= i:
            if videos:
                videos.append(videos[-1])
            else:
                videos.append("fallback")
    return videos

def get_local_videos():
    """Scan nature_videos/ folder for user-uploaded mp4/mov files."""
    exts = {".mp4", ".mov", ".MP4", ".MOV"}
    vids = sorted([
        str(p) for p in NATURE_VIDEOS_DIR.iterdir()
        if p.suffix in exts and p.stat().st_size > 100_000
    ])
    return vids

def get_auto_videos(count, progress_cb=None):
    """
    Priority:
    1. Use videos from nature_videos/ folder (user-uploaded)
    2. Fall back to downloading from Pexels if folder is empty
    Each ayah gets a different video cycling through the pool.
    """
    # ── Try local videos first ──────────────────────────────────────────────────
    local = get_local_videos()
    if local:
        if progress_cb:
            progress_cb(6, f"تم العثور على {len(local)} فيديو محلي...")
        videos = [local[i % len(local)] for i in range(count)]
        return videos

    # ── Fallback: download from internet ────────────────────────────────────────
    if progress_cb:
        progress_cb(6, "لا توجد فيديوهات محلية، جارٍ التحميل من الإنترنت...")
    videos = []
    all_themes = [t for t in NATURE_THEMES if t != "auto"]
    for i in range(count):
        theme = all_themes[i % len(all_themes)]
        video_idx = (i // len(all_themes)) % 3
        v = download_video(theme, video_idx, progress_cb if i == 0 else None)
        if v:
            videos.append(v)
        else:
            for fallback_theme in all_themes:
                for fallback_idx in range(3):
                    v = download_video(fallback_theme, fallback_idx)
                    if v:
                        videos.append(v)
                        break
                if len(videos) > i:
                    break
        if len(videos) <= i and videos:
            videos.append(videos[-1])
    return videos


# ─── Frame rendering ────────────────────────────────────────────────────────────
def wrap_line(text, font, max_w, max_lines=4):
    """Wrap text to fit within max_w pixels. Limits to max_lines lines."""
    words = text.split()
    if not words:
        return [text]
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        try:
            bb = font.getbbox(test)
            tw = bb[2] - bb[0]
        except Exception:
            tw = len(test) * (font.size // 2)
        if tw <= max_w:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            if len(lines) >= max_lines - 1:
                # Pack remaining words into last line
                cur = [w]
                remaining_idx = words.index(w)
                lines.append(" ".join(words[remaining_idx:]))
                cur = []
                break
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines if lines else [text]


def split_ayah_if_long(ar_text, en_text, ar_font, en_font, max_w, max_lines=4):
    """
    If an ayah produces more than max_lines Arabic lines,
    split it into two halves so each displays clearly.
    Returns a list of (ar_text, en_text) tuples — either 1 or 2 items.
    """
    shaped = shape_arabic(ar_text)
    lines = wrap_line(shaped, ar_font, max_w, max_lines=50)  # no limit first
    if len(lines) <= max_lines:
        return [(ar_text, en_text)]

    # Split words roughly in half
    words = ar_text.split()
    mid = len(words) // 2
    part1 = " ".join(words[:mid])
    part2 = " ".join(words[mid:])

    # Split English translation roughly in half too
    en_words = en_text.split() if en_text else []
    en_mid = len(en_words) // 2
    en1 = " ".join(en_words[:en_mid]) if en_words else ""
    en2 = " ".join(en_words[en_mid:]) if en_words else ""

    return [(part1, en1), (part2, en2)]

def draw_text_block(img, arabic_lines, english_lines, ar_font, en_font, alpha):
    """
    Draw Arabic text + English translation — matches the cinematic style:
    - Arabic text centered horizontally, positioned at 42% from top
    - Subtle dark gradient strip behind text (not a box)
    - Soft text shadow (2px offset, no hard outline)
    - English italic-style below, smaller, centered
    """
    from PIL import ImageDraw, ImageFilter
    import numpy as np

    img = img.copy().convert("RGBA")
    iw, ih = img.size
    overlay = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    a = int(alpha * 255)

    line_h_ar = int(ar_font.size * 1.6)
    line_h_en = int(en_font.size * 1.4)
    gap = int(en_font.size * 0.6)   # gap between Arabic and English

    total_ar_h = len(arabic_lines) * line_h_ar
    total_en_h = len(english_lines) * line_h_en
    total_h = total_ar_h + (gap + total_en_h if english_lines else 0)

    # Center vertically — true center of frame
    center_y = int(ih * 0.50)
    base_y = center_y - total_h // 2

    # ── Gradient strip behind text ──────────────────────────────────────────────
    strip_h = total_h + 80
    strip_y1 = max(0, base_y - 40)
    strip_y2 = min(ih, strip_y1 + strip_h)
    strip_img = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(strip_img)
    # Gradient: transparent → dark → transparent (top to bottom)
    max_strip_alpha = int(165 * alpha)
    for row in range(strip_y1, strip_y2):
        rel = (row - strip_y1) / max(strip_h, 1)
        # Bell-curve alpha: peaks in the middle
        bell = 4 * rel * (1 - rel)
        row_a = int(max_strip_alpha * bell)
        s_draw.line([(0, row), (iw, row)], fill=(0, 0, 0, row_a))
    # Blur to soften the gradient edges
    strip_img = strip_img.filter(ImageFilter.GaussianBlur(radius=18))
    overlay = Image.alpha_composite(overlay, strip_img)
    draw = ImageDraw.Draw(overlay)

    # ── Draw Arabic lines ───────────────────────────────────────────────────────
    y = base_y
    for ln in arabic_lines:
        bb = ar_font.getbbox(ln)
        tw = bb[2] - bb[0]
        cx = (iw - tw) // 2

        # Soft shadow (no hard stroke) — 2px offset, semi-transparent black
        shadow_a = int(a * 0.55)
        for sx, sy in ((2, 2), (3, 3), (1, 2), (2, 1)):
            draw.text((cx + sx, y + sy), ln, font=ar_font,
                      fill=(0, 0, 0, shadow_a))

        draw.text((cx, y), ln, font=ar_font,
                  fill=(255, 255, 255, a))
        y += line_h_ar

    # ── Draw English lines ──────────────────────────────────────────────────────
    if english_lines:
        y += gap
        en_color_a = int(a * 0.88)   # slightly dimmer than Arabic
        for ln in english_lines:
            bb = en_font.getbbox(ln)
            tw = bb[2] - bb[0]
            cx = (iw - tw) // 2
            # Lighter shadow for English
            for sx, sy in ((1, 1), (2, 2)):
                draw.text((cx + sx, y + sy), ln, font=en_font,
                          fill=(0, 0, 0, int(a * 0.45)))
            draw.text((cx, y), ln, font=en_font,
                      fill=(220, 220, 220, en_color_a))
            y += line_h_en

    return Image.alpha_composite(img, overlay).convert("RGB")


def extract_video_frames(video_path, duration, output_dir, work_w=WR, work_h=HR):
    """Extract frames from a video at specified resolution."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"scale={work_w}:{work_h}:force_original_aspect_ratio=decrease,pad={work_w}:{work_h}:(ow-iw)/2:(oh-ih)/2:black",
        "-t", str(duration),
        "-r", str(FPS),
        "-pix_fmt", "rgb24",
        str(output_dir / "frame_%06d.jpg")
    ]
    run_ff(cmd)

def get_video_frame_at_time(video_path, t, duration, work_w=WR, work_h=HR):
    """Extract a single frame from video at given time using looping."""
    if video_path == "fallback":
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (work_w, work_h), (20, 20, 30))
        draw = ImageDraw.Draw(img)
        for _ in range(30):
            x = random.randint(0, work_w)
            y = random.randint(0, work_h)
            draw.ellipse([x-2, y-2, x+2, y+2], fill=(200, 200, 220, 50))
        return img
    
    ffprobe = get_ffprobe()
    if ffprobe:
        probe = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", video_path],
            capture_output=True, text=True
        )
        if probe.stdout:
            try:
                info = json.loads(probe.stdout)
                video_duration = float(info['format']['duration'])
                t_looped = t % video_duration
            except:
                t_looped = t
        else:
            t_looped = t
    else:
        t_looped = t
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(t_looped),
        "-i", video_path,
        "-vf", f"scale={work_w}:{work_h}:force_original_aspect_ratio=decrease,pad={work_w}:{work_h}:(ow-iw)/2:(oh-ih)/2:black",
        "-vframes", "1",
        "-pix_fmt", "rgb24",
        "-f", "image2pipe",
        "-"
    ]
    
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and result.stdout:
        from PIL import Image
        import io
        return Image.open(io.BytesIO(result.stdout))
    return None


# ─── Core generation ─────────────────────────────────────────────────────────────
def generate_video(texts, translations, audio_path, audio_duration, ayah_durations,
                   bg_theme, text_color, output_path, progress_cb):
    n = len(texts)
    total_frames = int(math.ceil(audio_duration * FPS))

    if ayah_durations and len(ayah_durations) == n:
        ayah_starts = []
        t_cursor = 0.0
        for d in ayah_durations:
            ayah_starts.append(t_cursor)
            t_cursor += d
        ayah_ends = ayah_starts[1:] + [audio_duration]
    else:
        slot = audio_duration / max(n, 1)
        ayah_starts = [i * slot for i in range(n)]
        ayah_ends = [(i+1) * slot for i in range(n)]

    ar_font = get_arabic_font(52)  # Sized for 540px working width
    en_font = get_latin_font(19)

    # Build ayah_data — long ayahs get split into 2 visual segments
    # Each entry: (ar_lines, en_lines, orig_ayah_index, split_fraction)
    # split_fraction: how much of the ayah's audio duration this segment takes
    ayah_data = []
    ayah_segment_map = []   # maps segment index → (orig ayah index, t_start_frac, t_end_frac)

    for i, (ar_text, en_text) in enumerate(zip(texts, translations or [""] * n)):
        parts = split_ayah_if_long(ar_text, en_text, ar_font, en_font, WR - 50, max_lines=4)
        n_parts = len(parts)
        for p_idx, (part_ar, part_en) in enumerate(parts):
            ar_shaped = shape_arabic(part_ar)
            ar_lines = wrap_line(ar_shaped, ar_font, WR - 50)
            ar_lines = ar_lines[::-1]
            en_lines = wrap_line(part_en, en_font, WR - 60) if part_en else []
            ayah_data.append((ar_lines, en_lines))
            # fraction of original ayah's duration for this segment
            t_start_frac = p_idx / n_parts
            t_end_frac   = (p_idx + 1) / n_parts
            ayah_segment_map.append((i, t_start_frac, t_end_frac))

    total_segments = len(ayah_data)

    # Build per-segment absolute time boundaries
    seg_starts = []
    seg_ends   = []
    for (orig_i, t_sf, t_ef) in ayah_segment_map:
        ayah_start = ayah_starts[orig_i]
        ayah_dur   = ayah_ends[orig_i] - ayah_starts[orig_i]
        seg_starts.append(ayah_start + t_sf * ayah_dur)
        seg_ends.append(  ayah_start + t_ef * ayah_dur)

    progress_cb(5, f"تحميل فيديوهات {bg_theme}...")
    if bg_theme == "auto":
        bg_videos = get_auto_videos(n, progress_cb)
    else:
        bg_videos = get_videos(bg_theme, n, progress_cb)
    
    if not bg_videos:
        raise RuntimeError("فشل تحميل الفيديوهات")

    progress_cb(30, "إعداد الفيديو...")
    
    frames_dir = Path(tempfile.mkdtemp(prefix="qr_frames_"))
    try:
        for fi in range(total_frames):
            t = fi / FPS

            # Find which segment (split ayah) we are in
            si = total_segments - 1
            for k in range(total_segments):
                if t < seg_ends[k]:
                    si = k
                    break

            seg_start = seg_starts[si]
            seg_end   = seg_ends[si]
            seg_dur   = max(seg_end - seg_start, 0.001)
            local_t   = t - seg_start

            orig_i = ayah_segment_map[si][0]
            local_dur = ayah_durations[orig_i] if orig_i < len(ayah_durations) else seg_dur

            # Loop the video within the segment
            ayah_local_t = local_t % max(local_dur, 0.001)

            # Fade duration per segment
            fd_in  = min(0.5, seg_dur * 0.15)
            fd_out = min(0.5, seg_dur * 0.15)
            if local_t < fd_in:
                a = local_t / fd_in
            elif local_t > seg_dur - fd_out:
                a = max(0.0, (seg_dur - local_t) / fd_out)
            else:
                a = 1.0
            # Ease in/out with smoothstep
            a = a * a * (3 - 2 * a)

            # Global fade at very start/end of video
            if t < 0.8:
                a *= t / 0.8
            if t > audio_duration - 0.8:
                a *= max(0.0, (audio_duration - t) / 0.8)

            # Get frame from video — use original ayah index for video selection
            bg_video = bg_videos[orig_i % len(bg_videos)]
            bg = get_video_frame_at_time(bg_video, ayah_local_t, local_dur)
            
            if bg is None:
                bg = Image.new("RGB", (WR, HR), (15, 20, 30))

            # Slightly darken the background for better text contrast
            bg_arr = np.array(bg, dtype=np.float32)
            bg_arr = bg_arr * 0.82  # 18% darker
            bg = Image.fromarray(bg_arr.clip(0, 255).astype(np.uint8))

            ar_lines, en_lines = ayah_data[si]
            frame = draw_text_block(bg, ar_lines, en_lines, ar_font, en_font, a)
            frame.save(frames_dir / f"f{fi:06d}.jpg", quality=95)

            if fi % 50 == 0:
                pct = 30 + int(fi/total_frames*55)
                progress_cb(pct, f"إطار {fi}/{total_frames}...")
            
            # Flush every 100 frames to reduce memory usage
            if fi % 100 == 99:
                import gc
                gc.collect()

        progress_cb(87, "ترميز الفيديو النهائي...")
        
        # Use optimized encoding for mobile (target: <72MB for Android, <287MB for iOS)
        # 1080x1920 @ 25fps = ~2.4GB/minute raw, targeting ~50MB/min with good quality
        run_ff([
            "ffmpeg", "-y",
            "-thread_queue_size", "512",
            "-framerate", str(FPS),
            "-i", str(frames_dir/"f%06d.jpg"),
            "-thread_queue_size", "512",
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            # Scale to 1080x1920 with high-quality Lanczos
            "-vf", f"scale={W}:{H}:flags=lanczos,format=yuv420p",
            # H.264 CRF 22 = excellent quality, ~30-60% smaller than CRF 18
            # slow preset = better compression (same quality, smaller file)
            "-vcodec", "libx264", "-preset", "slow", "-crf", "22",
            "-profile:v", "high", "-level", "4.1",
            # Tune for still-image-heavy content (text on video)
            "-tune", "stillimage",
            # AAC audio at 128k (transparent quality for voice)
            "-acodec", "aac", "-b:a", "128k", "-ar", "44100",
            "-t", f"{audio_duration:.3f}",
            # faststart = metadata at front for streaming
            "-movflags", "+faststart",
            "-max_muxing_queue_size", "2048",
            # Cap bitrate to keep file small on long videos
            "-maxrate", "2M", "-bufsize", "4M",
            output_path,
        ], progress_cb=progress_cb, pct_start=87, pct_end=98,
           total_frames=total_frames)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


# ─── Job runner ───────────────────────────────────────────────────────────────────
def upd(jid, status, pct, msg, **kw):
    jobs[jid].update({"status":status,"progress":pct,"message":msg,**kw})

def run_job(jid, data):
    try:
        reciter    = data.get("reciter","ar.alafasy")
        surah_num  = int(data.get("surah",1))
        ayah_from  = int(data.get("ayahFrom",1))
        ayah_to    = int(data.get("ayahTo",1))
        bg_theme   = data.get("bgTheme","sky")
        text_color = data.get("textColor","auto")

        upd(jid,"running",3,"التحقق من FFmpeg...")
        get_ffmpeg()

        upd(jid,"running",6,"جلب الآيات...")
        texts, translations, audio_urls = [], [], []
        total = ayah_to - ayah_from + 1
        for idx, anum in enumerate(range(ayah_from, ayah_to+1)):
            upd(jid,"running", 6+int(idx/total*14), f"جلب الآية {anum}...")
            r = req.get(
                f"{QURAN_API}/ayah/{surah_num}:{anum}"
                f"/editions/quran-uthmani,{reciter},en.sahih",
                timeout=20)
            eds = r.json().get("data",[])
            if len(eds) >= 2:
                texts.append(eds[0]["text"])
                audio_urls.append(eds[1].get("audio",""))
                if len(eds) >= 3:
                    translations.append(eds[2].get("text",""))
                else:
                    translations.append("")

        if not texts: raise ValueError("لا توجد آيات")

        upd(jid,"running",22,"تحميل الصوت...")
        audio_files = []
        for i, url in enumerate(audio_urls):
            if not url: continue
            af = AUDIO_DIR / f"{jid}_{i}.mp3"
            r2 = req.get(url, timeout=90)
            if r2.status_code == 200:
                af.write_bytes(r2.content)
                audio_files.append(str(af))

        if not audio_files: raise ValueError("لا توجد ملفات صوتية")

        upd(jid,"running",38,"تحليل مدة كل آية...")

        def probe_duration(path):
            r = subprocess.run(
                [get_ffprobe(),"-v","quiet","-print_format","json",
                 "-show_format", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            return float(json.loads(r.stdout)["format"]["duration"])

        ayah_durations = []
        for i, af in enumerate(audio_files):
            d = probe_duration(af)
            ayah_durations.append(d)
            upd(jid,"running", 38+int(i/len(audio_files)*6),
                f"مدة الآية {ayah_from+i}: {d:.1f}s")

        combined = str(AUDIO_DIR / f"{jid}_combined.mp3")
        if len(audio_files) == 1:
            combined = audio_files[0]
        else:
            lst = AUDIO_DIR / f"{jid}_list.txt"
            lst.write_text("\n".join(f"file '{p.replace(chr(92),'/')}'"
                                      for p in audio_files), encoding="utf-8")
            run_ff(["ffmpeg","-y","-f","concat","-safe","0",
                    "-i",str(lst),"-c","copy",combined])

        dur = sum(ayah_durations)
        upd(jid,"running",46, f"المدة الإجمالية: {dur:.1f}s")

        output_path = str(OUTPUTS_DIR / f"{jid}_output.mp4")

        def pcb(pct, msg): upd(jid,"running",pct,msg)
        generate_video(texts, translations, combined, dur, ayah_durations,
                       bg_theme, text_color, output_path, pcb)

        upd(jid,"done",100,f"✅ اكتمل! {dur:.1f} ثانية",
            output_path=output_path, duration=round(dur,1))

        for af in audio_files:
            try: Path(af).unlink(missing_ok=True)
            except: pass

    except Exception as e:
        upd(jid,"error",0,f"❌ {e}")
        print(f"[{jid}] ERR: {e}", flush=True)


# ─── Flask routes ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "frontend.html")

@app.route("/api/check")
def check():
    info = {}
    try:
        ff = get_ffmpeg()
        r = subprocess.run([ff,"-version"],capture_output=True,text=True)
        info["ffmpeg"] = {"ok":True,"path":ff,"version":r.stdout.split("\n")[0]}
    except Exception as e:
        info["ffmpeg"] = {"ok":False,"error":str(e)}
    ensure_fonts()
    fp = next((str(FONTS_DIR/fn) for fn in FONT_URLS
               if (FONTS_DIR/fn).exists() and (FONTS_DIR/fn).stat().st_size>50000), None)
    info["font"] = {"ok":bool(fp),"path":fp}
    try:
        import arabic_reshaper; from bidi.algorithm import get_display
        info["arabic"] = {"ok":True}
    except:
        info["arabic"] = {"ok":False}
    return jsonify(info)

@app.route("/api/install-arabic", methods=["POST"])
def install_arabic():
    ok = _install_arabic_libs()
    if ok:
        try:
            import arabic_reshaper; from bidi.algorithm import get_display
            return jsonify({"ok":True,"msg":"تم تثبيت مكتبات العربية!"})
        except Exception as e:
            return jsonify({"ok":False,"msg":f"تم التثبيت - أعد تشغيل الخادم: {e}"})
    return jsonify({"ok":False,"msg":"فشل - شغّل: pip install arabic-reshaper python-bidi"})

@app.route("/api/reciters")
def reciters():
    try:
        r = req.get(f"{QURAN_API}/edition?format=audio&language=ar", timeout=10)
        out, seen = [], set()
        for ed in r.json().get("data",[]):
            k = ed.get("identifier",""); n = ed.get("englishName","") or ed.get("name","")
            if k and n and k not in seen:
                seen.add(k)
                out.append({"identifier":k,"name":ed.get("name",n),"englishName":n})
        return jsonify({"reciters":out})
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/surahs")
def surahs():
    try:
        r = req.get(f"{QURAN_API}/surah", timeout=10)
        out = [{"number":s["number"],"name":s["name"],
                "englishName":s["englishName"],"numberOfAyahs":s["numberOfAyahs"]}
               for s in r.json().get("data",[])]
        return jsonify({"surahs":out})
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/surah/<int:n>")
def surah(n):
    try:
        r = req.get(f"{QURAN_API}/surah/{n}/quran-uthmani", timeout=10)
        d = r.json()["data"]
        return jsonify({"name":d["name"],
                        "ayahs":[{"numberInSurah":a["numberInSurah"],"text":a["text"]}
                                  for a in d["ayahs"]]})
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.json
    jid = str(uuid.uuid4())[:8]
    jobs[jid] = {"status":"queued","progress":0,"message":"في الانتظار..."}
    threading.Thread(target=run_job, args=(jid,data), daemon=True).start()
    return jsonify({"job_id":jid})

@app.route("/api/status/<jid>")
def status(jid):
    return jsonify(jobs.get(jid,{"error":"not found"}))

@app.route("/api/download/<jid>")
def download(jid):
    job = jobs.get(jid)
    if not job: return jsonify({"error": "not found"}), 404
    if job.get("status") != "done": return jsonify({"error": "not ready"}), 400
    op = job.get("output_path")
    if not op or not os.path.exists(op): return jsonify({"error": "file missing"}), 404
    return send_file(
        op,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=f"quran_reels_{jid}.mp4",
        conditional=False,
    )

@app.route("/api/cleanup/<jid>", methods=["DELETE"])
def cleanup(jid):
    """Delete a finished job's output file from disk. Call this after n8n downloads the video."""
    job = jobs.get(jid)
    if not job: return jsonify({"error": "not found"}), 404
    op = job.get("output_path")
    deleted = False
    if op:
        try:
            Path(op).unlink(missing_ok=True)
            deleted = True
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    jobs.pop(jid, None)
    return jsonify({"deleted": deleted, "job_id": jid})


# ─── Startup ─────────────────────────────────────────────────────────────────────
def startup():
    print("\n" + "="*55)
    print("  Quran Reels Generator - Video Backgrounds Edition")
    print("="*55)
    try:
        ff = get_ffmpeg()
        r = subprocess.run([ff,"-version"],capture_output=True,text=True)
        print(f"  [OK] FFmpeg : {r.stdout.split(chr(10))[0][:55]}")
    except Exception as e:
        print(f"  [!!] FFmpeg: {e}")
    ensure_fonts()
    fp = next((fn for fn in FONT_URLS if (FONTS_DIR/fn).exists() and
               (FONTS_DIR/fn).stat().st_size>50000), None)
    print(f"  [{'OK' if fp else '!!'}] Font   : {fp or 'NOT FOUND'}")
    print("  Checking Arabic shaping libs...")
    if _install_arabic_libs():
        print("  [OK] arabic-reshaper + python-bidi ready")
    else:
        print("  [!!] Run: pip install arabic-reshaper python-bidi")
    print(f"  [OK] Pillow: {Image.__version__}")
    port = int(os.environ.get("PORT", 3000))
    print("="*55)
    print(f"  Running on : http://0.0.0.0:{port}")
    print("="*55 + "\n")

if __name__ == "__main__":
    startup()
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False,
            threaded=True, use_reloader=False)
