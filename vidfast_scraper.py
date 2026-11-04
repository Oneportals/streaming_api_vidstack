import sys
if sys.platform == "win32":
    import asyncio
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
import os
import time
import base64
import struct
import sys
import re
import urllib.parse
import subprocess
import hashlib
import concurrent.futures
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
try:
    import nacl.secret
except ImportError:
    nacl = None

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as curl_requests
    HAS_CURL_CFFI = False

def safe_curl_get(url, **kwargs):
    if not HAS_CURL_CFFI:
        kwargs.pop("impersonate", None)
        return requests.get(url, **kwargs)
    try:
        return curl_requests.get(url, **kwargs)
    except TypeError:
        kwargs.pop("impersonate", None)
        return requests.get(url, **kwargs)

import requests
import uvicorn

app = FastAPI(title="VidFast & VidLink Universal Backend", docs_url=None, redoc_url=None)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto")
    if not proto:
        proto = request.headers.get("x-forwarded-scheme")
    if not proto and request.headers.get("x-forwarded-ssl") == "on":
        proto = "https"
    if not proto and request.headers.get("cf-visitor") and '"scheme":"https"' in request.headers.get("cf-visitor", ""):
        proto = "https"
    if not proto:
        proto = request.url.scheme or "http"
    proto = proto.split(",")[0].strip()

    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        host = host.split(",")[0].strip()
    else:
        host = request.url.netloc

    return f"{proto}://{host}".rstrip("/")


KEY_HEX = "c75136c5668bbfe65a7ecad431a745db68b5f381555b38d8f6c699449cf11fcd"
KEY = bytes.fromhex(KEY_HEX)
BOX = nacl.secret.SecretBox(KEY) if nacl else None
NONCE = bytes(24)

VIDLINK_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
    'Origin': 'https://vidlink.pro',
    'Referer': 'https://vidlink.pro/'
}

SUB_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sub_cache")
os.makedirs(SUB_CACHE_DIR, exist_ok=True)

DURATION_CACHE = {}

INDIAN_LANGUAGES = [
    {"code": "hi", "name": "Hindi", "native": "हिन्दी"},
    {"code": "ta", "name": "Tamil", "native": "தமிழ்"},
    {"code": "te", "name": "Telugu", "native": "తెలుగు"},
    {"code": "ml", "name": "Malayalam", "native": "മലയാളം"},
    {"code": "kn", "name": "Kannada", "native": "ಕನ್ನಡ"},
    {"code": "mr", "name": "Marathi", "native": "मराठी"},
    {"code": "bn", "name": "Bengali", "native": "বাংলা"},
    {"code": "pa", "name": "Punjabi", "native": "ਪੰਜਾਬੀ"},
    {"code": "gu", "name": "Gujarati", "native": "ગુજરાતી"},
    {"code": "ur", "name": "Urdu", "native": "اُردُو"},
]

session = requests.Session()

def encrypt_token(media_id: str) -> str:
    if not BOX:
        return ""
    timestamp = int(time.time() + 480)
    message = str(media_id).encode("utf-8") + struct.pack(">Q", timestamp)
    encrypted = BOX.encrypt(message, NONCE)
    full_payload = NONCE + encrypted.ciphertext
    return base64.urlsafe_b64encode(full_payload).decode("utf-8").rstrip("=")

def get_upstream_headers(target_url: str, referer: str = None, origin: str = None) -> dict:
    headers = {}
    if "zenoak" in target_url or "laserlamp" in target_url or "vidfast" in (referer or ""):
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        headers["Referer"] = "https://vidfast.pro/"
        headers["Origin"] = "https://vidfast.pro"
    elif "freecdn" in target_url or "imgcdn" in target_url or "net52" in (referer or "") or "netmirror" in target_url:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        headers["Referer"] = referer or "https://net52.cc/"
        headers["Origin"] = origin or "https://net52.cc"
    elif "novahd" in (referer or "") or "novahd" in target_url or "edgemaster.site" in target_url:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        headers["Referer"] = referer or "https://novahd.cc/"
        headers["Origin"] = origin or "https://novahd.cc"
    elif "totu.me" in target_url or "hubcloud" in target_url:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        if referer:
            headers["Referer"] = referer
        if origin:
            headers["Origin"] = origin
    elif "filmboom" in (referer or "") or "bcdnxw" in target_url:
        headers["Referer"] = referer or "https://filmboom.top/"
        headers["Origin"] = origin or "https://filmboom.top"
    elif "workers.dev" in target_url or "finalsignal" in target_url:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        headers["Referer"] = referer or "https://vidsrc.pm/"
        headers["Origin"] = origin or "https://vidsrc.pm"
        if "data=" in target_url:
            try:
                raw_data = urllib.parse.parse_qs(urllib.parse.urlparse(target_url).query).get("data", [""])[0]
                if raw_data:
                    decoded_data = base64.b64decode(raw_data).decode("utf-8", errors="ignore")
                    for part in decoded_data.split("|"):
                        if part.startswith("Origin="):
                            headers["Origin"] = part.split("=", 1)[1]
                        elif part.startswith("Referer="):
                            headers["Referer"] = part.split("=", 1)[1]
            except Exception:
                pass
    elif referer:
        headers["Referer"] = referer
        if origin:
            headers["Origin"] = origin
    elif "hakunaymatata" in target_url or "bcdn" in target_url:
        headers["Origin"] = "https://vidlink.pro"
    return headers

def srt_to_vtt(srt_text: str) -> str:
    srt_text = srt_text.replace('\r\n', '\n').replace('\r', '\n')
    vtt_text = re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})', r'\1.\2', srt_text)
    return "WEBVTT\n\n" + vtt_text.strip() + "\n"

def get_media_duration(target_url: str, media_id: str) -> float:
    if media_id in DURATION_CACHE:
        return DURATION_CACHE[media_id]
    try:
        ffmpeg_bin = r"C:\ffmpeg\bin\ffprobe.exe" if os.path.exists(r"C:\ffmpeg\bin\ffprobe.exe") else "ffprobe"
        cmd = [ffmpeg_bin, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", target_url]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        dur = float(res.stdout.strip())
        if dur > 0:
            DURATION_CACHE[media_id] = dur
            return dur
    except Exception:
        pass
    return 7200.0

# ==========================================
# Translation Engine for Indian Languages
# ==========================================
def translate_text_chunk(texts: list, target_lang: str) -> list:
    if not texts:
        return []
    delimiter = " <br> "
    joined = delimiter.join(texts)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl={target_lang}&dt=t&q={urllib.parse.quote(joined)}"
    try:
        r = session.get(url, timeout=12)
        if r.status_code == 200:
            res = r.json()
            translated_full = "".join([item[0] for item in res[0]])
            parts = re.split(r"\s*<br>\s*|\s*<BR>\s*", translated_full)
            if len(parts) == len(texts):
                return parts
    except Exception as e:
        print(f"[WARN] Translation chunk failed: {e}")
    return texts

def translate_vtt_or_srt(content_text: str, target_lang: str, out_format: str = "vtt") -> str:
    lines = content_text.splitlines()
    text_indices = []
    texts_to_translate = []

    timestamp_re = re.compile(r'^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}')

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.isdigit() or stripped.startswith("WEBVTT") or stripped.startswith("NOTE") or timestamp_re.match(stripped):
            continue
        text_indices.append(idx)
        texts_to_translate.append(stripped)

    if not texts_to_translate:
        return srt_to_vtt(content_text) if out_format == "vtt" else content_text

    chunk_size = 40
    chunks = [texts_to_translate[i:i + chunk_size] for i in range(0, len(texts_to_translate), chunk_size)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        translated_chunks = list(executor.map(lambda c: translate_text_chunk(c, target_lang), chunks))

    translated_flat = [item for sublist in translated_chunks for item in sublist]

    if len(translated_flat) == len(text_indices):
        for i, idx in enumerate(text_indices):
            lines[idx] = translated_flat[i]

    result_text = "\n".join(lines)
    if out_format == "vtt":
        return srt_to_vtt(result_text) if not result_text.startswith("WEBVTT") else result_text
    else:
        srt_clean = re.sub(r'WEBVTT(\n|\r\n)+', '', result_text)
        srt_clean = re.sub(r'(\d{2}:\d{2}:\d{2})\.(\d{3})', r'\1,\2', srt_clean)
        return srt_clean.strip() + "\n"

# ==========================================
# 1. Upstream Metadata Fetchers
# ==========================================
@app.get("/movie/{movie_id}")
async def get_movie(movie_id: str):
    token = encrypt_token(movie_id)
    url = f"https://vidlink.pro/api/b/movie/{token}?multiLang=1"
    try:
        response = safe_curl_get(url, headers=VIDLINK_HEADERS, impersonate="chrome110", timeout=10)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Host server connection rejected.")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tv/{tv_id}/{season}/{episode}")
async def get_tv(tv_id: str, season: int, episode: int):
    token = encrypt_token(tv_id)
    url = f"https://vidlink.pro/api/b/tv/{token}/{season}/{episode}?multiLang=1"
    try:
        response = safe_curl_get(url, headers=VIDLINK_HEADERS, impersonate="chrome110", timeout=10)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Host segment server rejected connection.")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 2. Subtitle Extraction & Translation Endpoints
# ==========================================
def build_all_subtitles(captions: list, base_server: str) -> list:
    subtitles = []
    seen_langs = set()
    base_en_url = None

    if captions:
        for cap in captions:
            lang = cap.get("language") or "English"
            enc_url = urllib.parse.quote(cap["url"])
            enc_lang = urllib.parse.quote(lang)
            srclang = lang[:2].lower()
            is_default = (lang.lower() == "english")
            seen_langs.add(srclang)
            seen_langs.add(lang.lower())

            if is_default and not base_en_url:
                base_en_url = cap["url"]

            subtitles.append({
                "id": cap.get("id"),
                "language": lang,
                "srclang": srclang,
                "vtt_url": f"{base_server}/proxy/subtitle?url={enc_url}&format=vtt",
                "srt_url": f"{base_server}/proxy/subtitle?url={enc_url}&format=srt",
                "download_url": f"{base_server}/proxy/subtitle?url={enc_url}&format=srt&download=1&lang={enc_lang}",
                "default": is_default,
                "is_translated": False
            })

    if not base_en_url and captions:
        base_en_url = captions[0]["url"]

    if base_en_url:
        enc_base_en = urllib.parse.quote(base_en_url)
        for ind in INDIAN_LANGUAGES:
            code = ind["code"]
            name = ind["name"]
            native = ind["native"]
            if code not in seen_langs and name.lower() not in seen_langs:
                display_label = f"🇮🇳 {name} ({native})"
                enc_name = urllib.parse.quote(name)
                subtitles.append({
                    "id": f"trans_{code}",
                    "language": display_label,
                    "srclang": code,
                    "vtt_url": f"{base_server}/proxy/subtitle/translate?url={enc_base_en}&target={code}&format=vtt",
                    "srt_url": f"{base_server}/proxy/subtitle/translate?url={enc_base_en}&target={code}&format=srt",
                    "download_url": f"{base_server}/proxy/subtitle/translate?url={enc_base_en}&target={code}&format=srt&download=1&lang={enc_name}",
                    "default": False,
                    "is_translated": True
                })

    return subtitles

@app.get("/api/subtitles/{movie_id}")
async def get_movie_subtitles(request: Request, movie_id: str):
    base_server = get_base_url(request)
    try:
        data = await get_movie(movie_id)
        stream = data.get("stream") if data else None
        captions = stream.get("captions", []) if stream else []
        subtitles = build_all_subtitles(captions, base_server)
        return {
            "status": "success",
            "movie_id": movie_id,
            "total": len(subtitles),
            "subtitles": subtitles
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/subtitles/tv/{tv_id}/{season}/{episode}")
async def get_tv_subtitles(request: Request, tv_id: str, season: int, episode: int):
    base_server = get_base_url(request)
    try:
        data = await get_tv(tv_id, season, episode)
        stream = data.get("stream") if data else None
        captions = stream.get("captions", []) if stream else []
        subtitles = build_all_subtitles(captions, base_server)
        return {
            "status": "success",
            "tv_id": tv_id,
            "season": season,
            "episode": episode,
            "total": len(subtitles),
            "subtitles": subtitles
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.api_route("/proxy/subtitle", methods=["GET", "HEAD"])
async def proxy_subtitle(request: Request, url: str, format: str = "vtt", download: str = None, lang: str = "subtitle"):
    try:
        sub_url = urllib.parse.unquote(url)
        headers = get_upstream_headers(sub_url)

        if request.method == "HEAD":
            media_type = "text/vtt; charset=utf-8" if format == "vtt" else "application/x-subrip; charset=utf-8"
            return Response(
                status_code=200,
                media_type=media_type,
                headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            )

        resp = session.get(sub_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Subtitle download failed from upstream")

        content_text = resp.text
        if format.lower() == "vtt":
            body = srt_to_vtt(content_text).encode("utf-8")
            media_type = "text/vtt; charset=utf-8"
            ext = "vtt"
        else:
            body = content_text.encode("utf-8")
            media_type = "application/x-subrip; charset=utf-8"
            ext = "srt"

        res_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Content-Length": str(len(body)),
        }
        if download in ["1", "true", "yes"]:
            clean_lang = re.sub(r'[^a-zA-Z0-9_\-]', '', lang) or "subtitle"
            res_headers["Content-Disposition"] = f'attachment; filename="{clean_lang}.{ext}"'
        else:
            res_headers["Content-Disposition"] = "inline"

        return Response(content=body, media_type=media_type, headers=res_headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Subtitle proxy error: {e}")

@app.api_route("/proxy/subtitle/translate", methods=["GET", "HEAD"])
async def proxy_subtitle_translate(request: Request, url: str, target: str = "hi", format: str = "vtt", download: str = None, lang: str = "subtitle"):
    try:
        sub_url = urllib.parse.unquote(url)
        target_lang = target.strip().lower()
        out_fmt = format.strip().lower()

        if request.method == "HEAD":
            media_type = "text/vtt; charset=utf-8" if out_fmt == "vtt" else "application/x-subrip; charset=utf-8"
            return Response(
                status_code=200,
                media_type=media_type,
                headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            )

        cache_key = hashlib.md5(f"{sub_url}_{target_lang}_{out_fmt}".encode("utf-8")).hexdigest()
        cache_file = os.path.join(SUB_CACHE_DIR, f"{cache_key}.{out_fmt}")

        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            headers = get_upstream_headers(sub_url)
            resp = session.get(sub_url, headers=headers, timeout=12)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Base subtitle fetch failed")

            raw_text = resp.text
            content = translate_vtt_or_srt(raw_text, target_lang=target_lang, out_format=out_fmt)
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                print(f"[WARN] Failed to write sub cache: {e}")

        body = content.encode("utf-8")
        media_type = "text/vtt; charset=utf-8" if out_fmt == "vtt" else "application/x-subrip; charset=utf-8"

        res_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Content-Length": str(len(body)),
        }
        if download in ["1", "true", "yes"]:
            clean_lang = re.sub(r'[^a-zA-Z0-9_\-]', '', lang) or target_lang
            res_headers["Content-Disposition"] = f'attachment; filename="{clean_lang}.{out_fmt}"'
        else:
            res_headers["Content-Disposition"] = "inline"

        return Response(content=body, media_type=media_type, headers=res_headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Subtitle translation error: {e}")

# ==========================================
# 3. Source Extraction (Movies & TV Shows)
# ==========================================

# ==========================================
# Direct Mirror Scraper & Hunter Decoder (100% Native - NO IFRAMES)
# ==========================================
class MultiembedHunterDecoder:
    @staticmethod
    def hunter(h: str, u: int, n: str, t: int, e: int, r: int) -> str:
        def hunter_def(d, e_val, f_val) -> int:
            charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
            source_base = charset[0:e_val]
            target_base = charset[0:f_val]
            reversed_input = list(d)[::-1]
            result = 0
            for power, digit in enumerate(reversed_input):
                if digit in source_base:
                    result += source_base.index(digit) * (e_val ** power)
            converted_result = ""
            while result > 0:
                converted_result = target_base[result % f_val] + converted_result
                result = (result - (result % f_val)) // f_val
            return int(converted_result) or 0

        i = 0
        result_str = ""
        while i < len(h):
            j = 0
            s = ""
            while i < len(h) and h[i] != n[e]:
                s += h[i]
                i += 1
            while j < len(n):
                s = s.replace(n[j], str(j))
                j += 1
            if s:
                try:
                    result_str += chr(hunter_def(s, e, 10) - t)
                except Exception:
                    pass
            i += 1
        return result_str

    @classmethod
    def unpack(cls, packed_text: str) -> list:
        hunter_match = re.search(r'eval\(function\(h,u,n,t,e,r\).*?\((.*?)\)\)', packed_text)
        if not hunter_match:
            return []
        args_str = hunter_match.group(1)
        m = re.search(r'^\"(.*?)\",(.*?),(?:\"(.*?)\"|(\[.*?\])),(.*?),(.*?),(.*?)$', args_str)
        if not m:
            return []
        try:
            h = str(m.group(1))
            u = int(m.group(2))
            n = str(m.group(3) or m.group(4))
            t = int(m.group(5))
            e = int(m.group(6))
            r = int(m.group(7))
            unpacked = cls.hunter(h, u, n, t, e, r)
            return re.findall(r'file:\"([^\"]*)\"', unpacked)
        except Exception:
            return []


TMDB_KEYS = [
    "439c478a771f35c05022f9feabcca01c",
    "1865f43a0549ca50d341dd9ab8b29f49",
    "8265bd1679663a7ea12ac168da84d2e8",
    "e49339e830e014e414c2b9a71b2d4f82"
]

NEWTV_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Requested-With": "NetmirrorNewTV v1.0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0 /OS.GatuNewTV v1.0",
    "Accept": "application/json, text/plain, */*"
}

DISCOVERY_DOMAINS = [
    "https://mobiledetects.com",
    "https://mobiledetect.app",
    "https://mobidetect.art",
    "https://mobidetect.cc",
    "https://mobidetect.vip",
    "https://mobidetect.xyz"
]

_NETMIRROR_API_BASE = "https://tv.imgcdn.kim"
_NETMIRROR_RESOLVE_TIME = 0

def resolve_netmirror_api_base() -> str:
    global _NETMIRROR_API_BASE, _NETMIRROR_RESOLVE_TIME
    now = time.time()
    if _NETMIRROR_API_BASE and (now - _NETMIRROR_RESOLVE_TIME < 3600):
        return _NETMIRROR_API_BASE
    for d in DISCOVERY_DOMAINS:
        try:
            r = safe_curl_get(f"{d}/checknewtv.php", headers=NEWTV_HEADERS, impersonate="chrome120", timeout=3)
            if r.status_code == 200:
                data = r.json()
                if "token_hash" in data:
                    decoded = base64.b64decode(data["token_hash"]).decode("utf-8").strip()
                    if decoded.startswith("http"):
                        _NETMIRROR_API_BASE = decoded
                        _NETMIRROR_RESOLVE_TIME = now
                        return _NETMIRROR_API_BASE
        except Exception:
            pass
    return _NETMIRROR_API_BASE or "https://tv.imgcdn.kim"

def get_tmdb_metadata(media_id: str, is_tv: bool = False) -> tuple:
    endpoint = "tv" if is_tv else "movie"
    for key in TMDB_KEYS:
        try:
            url = f"https://api.tmdb.org/3/{endpoint}/{media_id}?api_key={key}"
            r = safe_curl_get(url, impersonate="chrome120", timeout=4)
            if r.status_code == 200:
                data = r.json()
                title = data.get("title") or data.get("name") or data.get("original_title") or ""
                release_date = data.get("release_date") or data.get("first_air_date") or ""
                year = release_date.split("-")[0] if release_date else ""
                if title:
                    return title, year
        except Exception:
            pass
    return "", ""

def get_netmirror_direct_stream(media_id: str, is_tv: bool = False, season: int = 1, episode: int = 1) -> dict:
    try:
        title, year = get_tmdb_metadata(media_id, is_tv)
        if not title:
            title = str(media_id)
        api_base = resolve_netmirror_api_base()
        clean_target = re.sub(r'[^a-zA-Z0-9]+', '', title).lower()
        
        ott_list = ["nf", "pv", "hs"]
        for ott in ott_list:
            try:
                search_url = f"{api_base}/newtv/search.php?s={urllib.parse.quote(title)}&t={int(time.time()*1000)}"
                h = dict(NEWTV_HEADERS)
                h["Ott"] = ott
                sr = safe_curl_get(search_url, headers=h, impersonate="chrome120", timeout=4)
                if sr.status_code != 200:
                    continue
                sdata = sr.json()
                results = sdata.get("searchResult", [])
                if not results or not isinstance(results, list):
                    continue
                
                match_item = None
                for r in results:
                    t_norm = re.sub(r'[^a-zA-Z0-9]+', '', r.get("t", "")).lower()
                    if t_norm == clean_target or clean_target in t_norm:
                        match_item = r
                        break
                if not match_item and len(results) == 1:
                    match_item = results[0]
                if not match_item or not match_item.get("id"):
                    continue
                
                item_id = match_item["id"]
                if not is_tv:
                    player_url = f"{api_base}/newtv/player.php?id={item_id}"
                    pr = safe_curl_get(player_url, headers=h, impersonate="chrome120", timeout=5)
                    if pr.status_code == 200:
                        pdata = pr.json()
                        vlink = pdata.get("video_link")
                        if vlink and ".m3u8" in vlink:
                            return {
                                "status": "success",
                                "stream_url": vlink,
                                "referer": pdata.get("referer", "https://net52.cc"),
                                "origin": "https://net52.cc",
                                "provider": f"NetMirror Multi-Audio ({ott.upper()})"
                            }
                else:
                    post_url = f"{api_base}/newtv/post.php?id={item_id}"
                    post_r = safe_curl_get(post_url, headers=h, impersonate="chrome120", timeout=5)
                    if post_r.status_code == 200:
                        post_data = post_r.json()
                        seasons = post_data.get("season") or []
                        target_season = None
                        for s in seasons:
                            s_str = str(s.get("s", "")).lower()
                            if f"season {season}" in s_str or f"s{season}" in s_str or s_str == str(season):
                                target_season = s
                                break
                        if not target_season and season <= len(seasons):
                            target_season = seasons[season - 1]
                        
                        if target_season:
                            ep_url = f"{api_base}/newtv/episodes.php?id={target_season.get('id')}"
                            ep_r = safe_curl_get(ep_url, headers=h, impersonate="chrome120", timeout=5)
                            if ep_r.status_code == 200:
                                ep_data = ep_r.json()
                                episodes_list = ep_data.get("episodes") or []
                                match_ep = None
                                for e in episodes_list:
                                    if str(e.get("ep")) == str(episode):
                                        match_ep = e
                                        break
                                if not match_ep and episode <= len(episodes_list):
                                    match_ep = episodes_list[episode - 1]
                                if match_ep and match_ep.get("id"):
                                    ep_player_url = f"{api_base}/newtv/player.php?id={match_ep.get('id')}"
                                    epr = safe_curl_get(ep_player_url, headers=h, impersonate="chrome120", timeout=5)
                                    if epr.status_code == 200:
                                        ep_pdata = epr.json()
                                        vlink = ep_pdata.get("video_link")
                                        if vlink and ".m3u8" in vlink:
                                            return {
                                                "status": "success",
                                                "stream_url": vlink,
                                                "referer": ep_pdata.get("referer", "https://net52.cc"),
                                                "origin": "https://net52.cc",
                                                "provider": f"NetMirror Multi-Audio ({ott.upper()})"
                                            }
            except Exception as ott_e:
                continue
    except Exception as e:
        print(f"[WARN] NetMirror stream scrape error: {e}")
    return {}

def get_novahd_direct_stream(media_id: str, is_tv: bool = False, season: int = 1, episode: int = 1) -> dict:
    url = f"https://novahd.cc/watch/tv/{media_id}/{season}/{episode}" if is_tv else f"https://novahd.cc/watch/m/{media_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://novahd.cc/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }
    try:
        r = safe_curl_get(url, headers=headers, impersonate="chrome120", timeout=8)
        if r.status_code == 200:
            html = r.text
            next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if next_data_match:
                try:
                    import json
                    data = json.loads(next_data_match.group(1))
                    page_props = data.get("props", {}).get("pageProps", {})
                    for key in ["stream", "sources", "playlist", "source", "videoUrl"]:
                        val = page_props.get(key)
                        if isinstance(val, str) and (".m3u8" in val or ".mp4" in val):
                            return {"status": "success", "stream_url": val, "referer": "https://novahd.cc/", "origin": "https://novahd.cc"}
                        elif isinstance(val, list) and len(val) > 0:
                            first = val[0]
                            if isinstance(first, dict) and first.get("url"):
                                return {"status": "success", "stream_url": first["url"], "referer": "https://novahd.cc/", "origin": "https://novahd.cc"}
                            elif isinstance(first, str):
                                return {"status": "success", "stream_url": first, "referer": "https://novahd.cc/", "origin": "https://novahd.cc"}
                except Exception:
                    pass
            m3u8_matches = re.findall(r'https?://[a-zA-Z0-9._:/?=&%+#]+\.m3u8[a-zA-Z0-9._:/?=&%+#]*', html)
            if m3u8_matches:
                return {
                    "status": "success",
                    "stream_url": m3u8_matches[0],
                    "referer": "https://novahd.cc/",
                    "origin": "https://novahd.cc"
                }
    except Exception as e:
        print(f"[WARN] NovaHD scrape notice: {e}")
    return {}

def get_screenscape_direct_stream(media_id: str, is_tv: bool = False, season: int = 1, episode: int = 1) -> dict:
    api_url = f"https://totu.me/api/hubcloud?tmdb={media_id}" if not is_tv else f"https://totu.me/api/hubcloud?tmdb={media_id}&s={season}&e={episode}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    try:
        r = safe_curl_get(api_url, headers=headers, impersonate="chrome120", timeout=6)
        if r.status_code == 200:
            data = r.json()
            stream_url = data.get("stream_url") or data.get("url") or (data.get("sources", [{}])[0].get("url") if data.get("sources") else None)
            if stream_url:
                return {
                    "status": "success",
                    "stream_url": stream_url,
                    "referer": "https://totu.me/",
                    "origin": "https://totu.me"
                }
    except Exception as e:
        print(f"[WARN] ScreenScape scrape notice: {e}")
    return {}

def get_multiaudio_hindi_stream(media_id: str, is_tv: bool = False, season: int = 1, episode: int = 1) -> dict:
    # 1. Primary: NetMirror Multi-Audio Engine (Native Hindi + Dual/Multi-Audio tracks)
    data = get_netmirror_direct_stream(media_id, is_tv, season, episode)
    if data and data.get("stream_url"):
        return data
    # 2. Secondary: NovaHD Direct Provider
    data = get_novahd_direct_stream(media_id, is_tv, season, episode)
    if data and data.get("stream_url"):
        return data
    # 3. Tertiary: ScreenScape HubCloud
    data = get_screenscape_direct_stream(media_id, is_tv, season, episode)
    if data and data.get("stream_url"):
        return data
    return {}

def get_vidsrc_direct_stream(media_id: str, is_tv: bool = False, season: int = 1, episode: int = 1) -> dict:
    session_obj = curl_requests.Session()
    embed_url = f"https://vidsrc.pm/embed/tv/{media_id}/{season}-{episode}" if is_tv else f"https://vidsrc.pm/embed/movie/{media_id}"
    api_url = f"https://vidsrc.pm/api/vidora/v1/tv/{media_id}/{season}/{episode}?source=scrapify" if is_tv else f"https://vidsrc.pm/api/vidora/v1/movie/{media_id}?source=scrapify"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": embed_url,
        "Origin": "https://vidsrc.pm",
        "x-player-key": "f3b72e73c80c9a996574379798703796a1936efa3516a7105cb0e43048b46b5a"
    }
    try:
        extra_kwargs = {"impersonate": "chrome120"} if HAS_CURL_CFFI else {}
        session_obj.get(embed_url, headers=headers, timeout=8, **extra_kwargs)
        r = session_obj.get(api_url, headers=headers, timeout=8, **extra_kwargs)
        if r.status_code == 200:
            data = r.json()
            if data.get("result") and data.get("sources"):
                src = data["sources"][0]
                return {
                    "status": "success",
                    "stream_url": src.get("url"),
                    "tracks": src.get("tracks", []),
                    "qualities": src.get("qualities", [])
                }
    except Exception as e:
        print(f"[WARN] Vidsrc direct extractor error: {e}")
    return {}

def build_sources_tracks_servers(stream: dict, base_server: str, media_type: str, media_id: str, season: int = 1, episode: int = 1):
    sources = []
    tracks = []
    servers = []
    total_dur = 7200.0

    # 1. Native Direct Streams (100% Native HTML5 Video - Zero Iframes)
    servers = [
        {"id": "1", "name": "⚡ Server 1: Ultra HD Direct (MP4 / Fast Proxy)", "type": "native"},
        {"id": "2", "name": "🌐 Server 2: Mirror HLS Direct (Scraped Stream)", "type": "native"},
        {"id": "3", "name": "🎧 Server 3: Multi-Audio / Hindi Dubbed (Nova & ScreenScape)", "type": "native"}
    ]
    if not stream:
        # Allow fallback Server 2 and Server 3 even if Server 1 had no stream
        pass

    # 2. Subtitles with Indian Languages
    captions = stream.get("captions", [])
    sub_objs = build_all_subtitles(captions, base_server)
    for s in sub_objs:
        tracks.append({
            "kind": "subtitles",
            "src": s["vtt_url"],
            "download_src": s["download_url"],
            "srclang": s["srclang"],
            "label": s["language"],
            "default": s["default"]
        })

    # 3. HLS Playlist
    if stream.get("type") == "hls" or stream.get("playlist"):
        playlist_url = stream.get("playlist") or stream.get("qualities", {}).get("auto", {}).get("url")
        hdrs = stream.get("headers") or {}
        enc_play = urllib.parse.quote(playlist_url)
        proxy_m3u8 = f"{base_server}/proxy/m3u8?url={enc_play}"
        if hdrs.get("referer"):
            proxy_m3u8 += f"&referer={urllib.parse.quote(hdrs['referer'])}"
        if hdrs.get("origin"):
            proxy_m3u8 += f"&origin={urllib.parse.quote(hdrs['origin'])}"
        sources.append({
            "src": proxy_m3u8,
            "type": "application/x-mpegURL",
            "label": "Auto HLS",
            "codec": "h264"
        })

    # 4. Direct MP4 Qualities
    elif stream.get("qualities"):
        quals = stream["qualities"]
        sorted_keys = sorted(quals.keys(), key=lambda x: int(x) if x.isdigit() else 0, reverse=True)
        top_raw_url = quals[sorted_keys[0]]["url"]
        
        # Probe exact duration once
        total_dur = get_media_duration(f"{base_server}/proxy/segment?url={urllib.parse.quote(top_raw_url)}", media_id)

        for q in sorted_keys:
            q_obj = quals[q]
            raw_url = q_obj["url"]
            codec_name = q_obj.get("codecName", "unknown").lower()
            hdrs = q_obj.get("headers") or {}
            ref = hdrs.get("referer") or hdrs.get("Referer") or ""
            orig = hdrs.get("origin") or hdrs.get("Origin") or ""

            enc_url = urllib.parse.quote(raw_url)
            proxy_url = f"{base_server}/proxy/segment?url={enc_url}"
            if ref:
                proxy_url += f"&referer={urllib.parse.quote(ref)}"
            if orig:
                proxy_url += f"&origin={urllib.parse.quote(orig)}"

            label_extra = f" ({codec_name.upper()})" if codec_name in ["hevc", "h265"] else ""
            sources.append({
                "src": proxy_url,
                "type": "video/mp4",
                "label": f"{q}p HD{label_extra}",
                "res": int(q) if q.isdigit() else 720,
                "codec": codec_name
            })

            # If 1080p and HEVC, provide Universal H.264
            if q == sorted_keys[0] and codec_name in ["hevc", "h265"]:
                h264_url = f"{base_server}/proxy/h264?url={enc_url}"
                if ref:
                    h264_url += f"&referer={urllib.parse.quote(ref)}"
                if orig:
                    h264_url += f"&origin={urllib.parse.quote(orig)}"
                sources.append({
                    "src": h264_url,
                    "type": "video/mp4",
                    "label": f"{q}p (Universal H.264 - Fast Scrubbing)",
                    "res": int(q) if q.isdigit() else 720,
                    "codec": "h264",
                    "isTranscode": True
                })

    
        # 5. Attach Scraped Direct Mirror Stream (Zero Iframes)
    try:
        m_data = get_vidsrc_direct_stream(media_id, is_tv=(media_type == "tv"), season=season, episode=episode)
        if m_data and m_data.get("stream_url"):
            m_url = m_data["stream_url"]
            enc_m = urllib.parse.quote(m_url)
            p_mirror = f"{base_server}/proxy/m3u8?url={enc_m}&referer=https%3A%2F%2Fvidsrc.pm%2F&origin=https%3A%2F%2Fvidsrc.pm"
            sources.append({
                "src": p_mirror,
                "type": "application/x-mpegURL",
                "label": "Mirror HLS (Direct Scraped Stream)",
                "codec": "h264",
                "isMirror": True
            })
    except Exception as e:
        print(f"[WARN] Mirror stream scrape notice: {e}")

    # 6. Attach Server 3: Multi-Audio / Hindi Dubbed (Nova & ScreenScape)
    try:
        multi_data = get_multiaudio_hindi_stream(media_id, is_tv=(media_type == "tv"), season=season, episode=episode)
        if multi_data and multi_data.get("stream_url"):
            s_url = multi_data["stream_url"]
            enc_s = urllib.parse.quote(s_url)
            ref_param = urllib.parse.quote(multi_data.get("referer", "https://novahd.cc/"))
            orig_param = urllib.parse.quote(multi_data.get("origin", "https://novahd.cc"))
            p_multiaudio = f"{base_server}/proxy/m3u8?url={enc_s}&referer={ref_param}&origin={orig_param}"
            sources.append({
                "src": p_multiaudio,
                "type": "application/x-mpegURL",
                "label": "🎧 Multi-Audio HLS (Hindi / Dual Audio)",
                "codec": "h264",
                "isMultiAudio": True,
                "server": "3"
            })
    except Exception as e:
        print(f"[WARN] Multi-Audio Server 3 scrape notice: {e}")

    return sources, tracks, servers, total_dur

@app.get("/api/debug/{movie_id}")
async def api_debug(movie_id: str):
    res = {
        "has_nacl": nacl is not None,
        "has_curl_cffi": HAS_CURL_CFFI,
    }
    try:
        res["tmdb_meta"] = get_tmdb_metadata(movie_id)
    except Exception as e:
        res["tmdb_meta_error"] = str(e)
    try:
        res["netmirror_base"] = resolve_netmirror_api_base()
    except Exception as e:
        res["netmirror_base_error"] = str(e)
    try:
        res["netmirror"] = get_netmirror_direct_stream(movie_id)
    except Exception as e:
        res["netmirror_error"] = str(e)
    try:
        res["vidsrc"] = get_vidsrc_direct_stream(movie_id)
    except Exception as e:
        res["vidsrc_error"] = str(e)
    try:
        res["vidlink"] = await get_movie(movie_id)
    except Exception as e:
        res["vidlink_error"] = str(e)
    return res

@app.get("/api/source/{movie_id}")
async def api_source_for_videojs(request: Request, movie_id: str):
    base_server = get_base_url(request)
    stream = {}
    try:
        data = await get_movie(movie_id)
        if data and isinstance(data, dict):
            stream = data.get("stream") or {}
    except Exception as e:
        print(f"[WARN] Primary stream get_movie notice: {e}")
        stream = {}

    try:
        sources, tracks, servers, duration = build_sources_tracks_servers(stream, base_server, "movie", movie_id)
        if not sources:
            return JSONResponse({"status": "error", "message": "No stream found for this movie ID across any servers"}, status_code=404)

        return {
            "status": "success",
            "type": "movie",
            "movie_id": movie_id,
            "duration": duration,
            "servers": servers,
            "sources": sources,
            "tracks": tracks
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/source/tv/{tv_id}/{season}/{episode}")
async def api_source_for_tv(request: Request, tv_id: str, season: int, episode: int):
    base_server = get_base_url(request)
    stream = {}
    try:
        data = await get_tv(tv_id, season, episode)
        if data and isinstance(data, dict):
            stream = data.get("stream") or {}
    except Exception as e:
        print(f"[WARN] Primary stream get_tv notice: {e}")
        stream = {}

    try:
        sources, tracks, servers, duration = build_sources_tracks_servers(stream, base_server, "tv", tv_id, season, episode)
        if not sources:
            return JSONResponse({"status": "error", "message": "No stream found for this TV episode across any servers"}, status_code=404)

        return {
            "status": "success",
            "type": "tv",
            "tv_id": tv_id,
            "season": season,
            "episode": episode,
            "duration": duration,
            "servers": servers,
            "sources": sources,
            "tracks": tracks
        }
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ==========================================
# 4. Direct Playable Stream Endpoints
# ==========================================
def pick_playable_stream(sources: list, codec: str = None, transcode: str = None) -> str:
    if not sources:
        return None
    if codec == "h264" or transcode in ["1", "true", "yes"]:
        for s in sources:
            if s.get("codec") == "h264" or s.get("isTranscode"):
                return s["src"]
    if codec in ["raw", "hevc", "h265"]:
        for s in sources:
            if not s.get("isTranscode"):
                return s["src"]
        return sources[0]["src"]
    # For direct streams (/stream/{id}), prefer the seekable direct MP4 proxy with Range support
    for s in sources:
        if not s.get("isTranscode"):
            return s["src"]
    return sources[0]["src"]

@app.api_route("/stream/{movie_id}/{lang}", methods=["GET", "HEAD"])
@app.api_route("/stream/{movie_id}", methods=["GET", "HEAD"])
@app.api_route("/stream/movie/{movie_id}/{lang}", methods=["GET", "HEAD"])
@app.api_route("/stream/movie/{movie_id}", methods=["GET", "HEAD"])
async def direct_stream_redirect(request: Request, movie_id: str, lang: str = None, codec: str = None, transcode: str = None, raw: str = None):
    try:
        if movie_id == "movie" and lang:
            actual_id = lang
            target_lang = request.query_params.get("lang")
        else:
            actual_id = movie_id
            target_lang = lang or request.query_params.get("lang")
        accept_hdr = request.headers.get("accept", "").lower()
        ua = request.headers.get("user-agent", "").lower()

        # 1. If JSON requested or query param ?json=1: return direct API JSON
        if "application/json" in accept_hdr or request.query_params.get("json"):
            source_data = await api_source_for_videojs(request, actual_id)
            if isinstance(source_data, dict) and source_data.get("sources"):
                stream_url = pick_playable_stream(source_data["sources"], codec, transcode)
                base = get_base_url(request)
                return JSONResponse({
                    "status": "success",
                    "media_id": actual_id,
                    "language": target_lang or "english",
                    "direct_stream_url": stream_url,
                    "stream_embed_url": f"{base}/stream/{actual_id}" + (f"/{target_lang}" if target_lang else ""),
                    "player_url": f"{base}/watch/{actual_id}" + (f"?lang={target_lang}" if target_lang else ""),
                    "sources": source_data["sources"],
                    "subtitles": source_data.get("tracks", [])
                })
            raise HTTPException(status_code=404, detail="No stream available for this movie ID")

        # 2. If opened in browser tab or embed player (HTML):
        # Serve our 100% Native Custom Cinema Player with pre-selected language and ZERO IFRAMES!
        if "text/html" in accept_hdr and not raw:
            lang_param = f"&lang={urllib.parse.quote(target_lang)}" if target_lang else ""
            return RedirectResponse(url=f"/embed/movie/{actual_id}?autoplay=1{lang_param}", status_code=307)

        # 3. If requested directly as video stream (e.g. <video src="...">, VLC, ffmpeg, or raw=1):
        source_data = await api_source_for_videojs(request, actual_id)
        if isinstance(source_data, dict) and source_data.get("sources"):
            is_firefox = "firefox" in ua
            if is_firefox and not codec:
                codec = "h264"
            stream_url = pick_playable_stream(source_data["sources"], codec, transcode)
            if stream_url:
                return RedirectResponse(url=stream_url, status_code=307)
        raise HTTPException(status_code=404, detail="No stream available for this movie ID")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/stream/tv/{tv_id}/{season}/{episode}/{lang}", methods=["GET", "HEAD"])
@app.api_route("/stream/tv/{tv_id}/{season}/{episode}", methods=["GET", "HEAD"])
async def direct_stream_tv_redirect(request: Request, tv_id: str, season: int, episode: int, lang: str = None, codec: str = None, transcode: str = None, raw: str = None):
    try:
        accept_hdr = request.headers.get("accept", "").lower()
        ua = request.headers.get("user-agent", "").lower()
        target_lang = lang or request.query_params.get("lang")

        if "application/json" in accept_hdr or request.query_params.get("json"):
            source_data = await api_source_for_tv(request, tv_id, season, episode)
            if isinstance(source_data, dict) and source_data.get("sources"):
                stream_url = pick_playable_stream(source_data["sources"], codec, transcode)
                base = get_base_url(request)
                return JSONResponse({
                    "status": "success",
                    "type": "tv",
                    "tv_id": tv_id,
                    "season": season,
                    "episode": episode,
                    "language": target_lang or "english",
                    "direct_stream_url": stream_url,
                    "stream_embed_url": f"{base}/stream/tv/{tv_id}/{season}/{episode}" + (f"/{target_lang}" if target_lang else ""),
                    "player_url": f"{base}/watch/tv/{tv_id}/{season}/{episode}" + (f"?lang={target_lang}" if target_lang else ""),
                    "sources": source_data["sources"],
                    "subtitles": source_data.get("tracks", [])
                })
            raise HTTPException(status_code=404, detail="No stream available for this TV episode")

        if "text/html" in accept_hdr and not raw:
            lang_param = f"&lang={urllib.parse.quote(target_lang)}" if target_lang else ""
            return RedirectResponse(url=f"/embed/tv/{tv_id}/{season}/{episode}?autoplay=1{lang_param}", status_code=307)

        source_data = await api_source_for_tv(request, tv_id, season, episode)
        if isinstance(source_data, dict) and source_data.get("sources"):
            is_firefox = "firefox" in ua
            if is_firefox and not codec:
                codec = "h264"
            stream_url = pick_playable_stream(source_data["sources"], codec, transcode)
            if stream_url:
                return RedirectResponse(url=stream_url, status_code=307)
        raise HTTPException(status_code=404, detail="No stream available for this TV episode")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stream/{movie_id}/{lang}")
@app.get("/api/stream/{movie_id}")
async def api_direct_stream_json(request: Request, movie_id: str, lang: str = None):
    actual_id = movie_id
    target_lang = lang or request.query_params.get("lang")
    source_data = await api_source_for_videojs(request, actual_id)
    if isinstance(source_data, dict) and source_data.get("sources"):
        stream_url = pick_playable_stream(source_data["sources"])
        base = get_base_url(request)
        matching_sub = next((t for t in source_data.get("tracks", []) if target_lang and (target_lang.lower() in t.get("label", "").lower() or target_lang.lower() == t.get("srclang", "").lower())), None)
        return {
            "status": "success",
            "type": "movie",
            "media_id": actual_id,
            "language": target_lang or "english",
            "direct_stream_url": stream_url,
            "stream_embed_url": f"{base}/stream/{actual_id}" + (f"/{target_lang}" if target_lang else ""),
            "player_url": f"{base}/watch/{actual_id}" + (f"?lang={target_lang}" if target_lang else ""),
            "active_subtitle": matching_sub,
            "all_sources": source_data["sources"],
            "all_subtitles": source_data.get("tracks", [])
        }
    raise HTTPException(status_code=404, detail="Stream not found")



# ==========================================
# 5. HLS & Video Proxy Endpoints (With Instant Seek Support)
# ==========================================
@app.api_route("/proxy/m3u8", methods=["GET", "HEAD"])
async def proxy_m3u8(request: Request, url: str, referer: str = None, origin: str = None):
    try:
        if request.method == "HEAD":
            return Response(
                status_code=200,
                media_type="application/vnd.apple.mpegurl",
                headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            )

        stream_url = urllib.parse.unquote(url) if "%" in url else url
        ref = urllib.parse.unquote(referer) if (referer and "%" in referer) else referer
        orig = urllib.parse.unquote(origin) if (origin and "%" in origin) else origin
        headers = get_upstream_headers(stream_url, ref, orig)
        
        try:
            resp = safe_curl_get(stream_url, headers=headers, impersonate="chrome120", timeout=12)
        except Exception as ce:
            resp = session.get(stream_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Upstream playlist error")
            
        content = resp.text
        base_url = stream_url.rsplit("/", 1)[0] + "/"
        enc_ref = urllib.parse.quote(headers.get("Referer", ""))
        enc_orig = urllib.parse.quote(headers.get("Origin", ""))
        extra_params = f"&referer={enc_ref}" if enc_ref else ""
        if enc_orig:
            extra_params += f"&origin={enc_orig}"

        rewritten_lines = []
        tag_uri_regex = re.compile(r'URI="([^"]+)"')

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                rewritten_lines.append(line)
                continue

            if stripped.startswith("#EXT-X-MAP") or stripped.startswith("#EXT-X-KEY"):
                def replace_tag_uri(match):
                    target = urllib.parse.urljoin(base_url, match.group(1))
                    enc_target = urllib.parse.quote(target)
                    return f'URI="/proxy/segment?url={enc_target}{extra_params}"'
                rewritten_lines.append(tag_uri_regex.sub(replace_tag_uri, stripped))
            elif stripped.startswith("#EXT-X-MEDIA"):
                def replace_media_uri(match):
                    target = urllib.parse.urljoin(base_url, match.group(1))
                    enc_target = urllib.parse.quote(target)
                    if ".m3u8" in target:
                        return f'URI="/proxy/m3u8?url={enc_target}{extra_params}"'
                    return f'URI="/proxy/segment?url={enc_target}{extra_params}"'
                rewritten_lines.append(tag_uri_regex.sub(replace_media_uri, stripped))
            elif not stripped.startswith("#"):
                target_url = urllib.parse.urljoin(base_url, stripped)
                enc_target = urllib.parse.quote(target_url)
                if ".m3u8" in target_url:
                    rewritten_lines.append(f"/proxy/m3u8?url={enc_target}{extra_params}")
                else:
                    rewritten_lines.append(f"/proxy/segment?url={enc_target}{extra_params}")
            else:
                rewritten_lines.append(line)

        manifest_data = "\n".join(rewritten_lines)
        return Response(
            content=manifest_data,
            media_type="application/vnd.apple.mpegurl",
            headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Proxy m3u8 error: {e}")

@app.api_route("/proxy/segment", methods=["GET", "HEAD"])
async def proxy_segment(request: Request, url: str, referer: str = None, origin: str = None):
    try:
        segment_url = urllib.parse.unquote(url) if "%" in url else url
        ref = urllib.parse.unquote(referer) if (referer and "%" in referer) else referer
        orig = urllib.parse.unquote(origin) if (origin and "%" in origin) else origin
        headers = get_upstream_headers(segment_url, ref, orig)
        
        client_range = request.headers.get("Range")
        if client_range:
            headers["Range"] = client_range

        if request.method == "HEAD":
            upstream_resp = session.head(segment_url, headers=headers, timeout=10)
            res_headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Content-Disposition": "inline",
                "Accept-Ranges": "bytes",
            }
            for k in ["Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"]:
                if k in upstream_resp.headers:
                    res_headers[k] = upstream_resp.headers[k]
            return Response(
                status_code=upstream_resp.status_code if upstream_resp.status_code in [200, 206] else 200,
                headers=res_headers,
                media_type=upstream_resp.headers.get("Content-Type", "video/mp4")
            )

        upstream_resp = session.get(segment_url, headers=headers, stream=True, timeout=25)
        
        response_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes",
        }
        for k in ["Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"]:
            if k in upstream_resp.headers:
                response_headers[k] = upstream_resp.headers[k]

        def iter_chunks():
            try:
                for chunk in upstream_resp.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        yield chunk
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            finally:
                upstream_resp.close()

        seg_type = "video/mp2t" if (("freecdn" in segment_url and segment_url.endswith(".js")) or segment_url.endswith(".ts")) else upstream_resp.headers.get("Content-Type", "video/mp4")
        response_headers["Content-Type"] = seg_type
        return StreamingResponse(
            iter_chunks(),
            status_code=upstream_resp.status_code,
            headers=response_headers,
            media_type=seg_type
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Segment error: {e}")

# Universal H.264 Transcoding Endpoint with Fast Instant Seek (-ss parameter)
@app.api_route("/proxy/h264", methods=["GET", "HEAD"])
async def proxy_h264(request: Request, url: str, referer: str = None, origin: str = None, ss: float = 0.0):
    try:
        segment_url = urllib.parse.unquote(url) if "%" in url else url
        ref = urllib.parse.unquote(referer) if (referer and "%" in referer) else referer
        orig = urllib.parse.unquote(origin) if (origin and "%" in origin) else origin

        if request.method == "HEAD":
            return Response(
                status_code=200,
                headers={
                    "Content-Type": "video/mp4",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "*",
                    "Accept-Ranges": "none",
                }
            )

        port = os.getenv("PORT", "8000")
        enc_target = urllib.parse.quote(segment_url)
        local_segment_url = f"http://127.0.0.1:{port}/proxy/segment?url={enc_target}"
        if ref:
            local_segment_url += f"&referer={urllib.parse.quote(ref)}"
        if orig:
            local_segment_url += f"&origin={urllib.parse.quote(orig)}"

        ffmpeg_bin = r"C:\ffmpeg\bin\ffmpeg.exe" if os.path.exists(r"C:\ffmpeg\bin\ffmpeg.exe") else "ffmpeg"
        
        if sys.platform == "win32":
            encoder_args = ["-c:v", "h264_mf", "-b:v", "3000k"]
        else:
            encoder_args = ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-b:v", "3000k"]

        cmd = [ffmpeg_bin]
        # Fast input seek before -i allows instant scrubbing to any second!
        if ss and float(ss) > 0:
            cmd += ["-ss", str(float(ss))]

        cmd += [
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", local_segment_url,
        ] + encoder_args + [
            "-c:a", "copy",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "-f", "mp4",
            "pipe:1"
        ]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def iter_h264():
            try:
                while True:
                    data = proc.stdout.read(64 * 1024)
                    if not data:
                        break
                    yield data
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            finally:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except Exception:
                    proc.kill()

        return StreamingResponse(
            iter_h264(),
            media_type="video/mp4",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Content-Disposition": "inline"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"H264 transcode error: {e}")

# ==========================================
# 6. Standalone Embeddable Player (With Controllable Scrubber & Indian Languages)
# ==========================================

# ==========================================
# 6. Built-in Embed Player (Zero Iframes)
# ==========================================

# ==========================================
# 6. Built-in Embed Player (Zero Iframes)
# ==========================================
EMBED_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Universal Stream Embed</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      width: 100%; height: 100%;
      background: #000;
      overflow: hidden;
      font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
    }
    .video-container {
      position: relative;
      width: 100vw; height: 100vh;
      display: flex; align-items: center; justify-content: center;
      background: #000;
    }
    video {
      width: 100%; height: 100%;
      object-fit: contain;
      outline: none;
      background: #000;
      cursor: pointer;
    }
    video::cue {
      background: rgba(0, 0, 0, 0.85);
      color: #ffffff;
      font-size: 1.15rem;
      font-family: 'Plus Jakarta Sans', sans-serif;
      text-shadow: 0 2px 4px rgba(0,0,0,0.9);
      border-radius: 4px;
      padding: 3px 8px;
    }
    iframe
    /* Centered Buffering Spinner */
    .buffering-spinner {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      display: none;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      z-index: 35;
      pointer-events: none;
    }
    .spinner-ring {
      width: 52px; height: 52px;
      border: 4px solid rgba(255, 255, 255, 0.15);
      border-top-color: #06b6d4;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      box-shadow: 0 0 16px rgba(6, 182, 212, 0.5);
    }
    .spinner-text {
      font-size: 0.85rem;
      font-weight: 600;
      color: #e2e8f0;
      text-shadow: 0 2px 4px rgba(0,0,0,0.8);
      letter-spacing: 0.5px;
    }
    @keyframes spin { 100% { transform: rotate(360deg); } }

    /* Center Big Play Button */
    .center-play-btn {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      width: 72px; height: 72px;
      background: rgba(15, 23, 42, 0.75);
      backdrop-filter: blur(8px);
      border: 2px solid rgba(255, 255, 255, 0.25);
      border-radius: 50%;
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer;
      z-index: 30;
      transition: all 0.2s ease;
      box-shadow: 0 4px 20px rgba(0,0,0,0.6);
    }
    .center-play-btn:hover {
      transform: translate(-50%, -50%) scale(1.1);
      background: rgba(99, 102, 241, 0.9);
      border-color: #6366f1;
    }

    /* Floating Controls Bar */
    .custom-controls {
      position: absolute;
      bottom: 0; left: 0; right: 0;
      background: linear-gradient(to top, rgba(10, 15, 30, 0.95) 0%, rgba(10, 15, 30, 0.7) 60%, transparent 100%);
      padding: 18px 22px 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      z-index: 40;
      opacity: 1;
      transition: opacity 0.3s ease;
    }
    .video-container.hide-controls .custom-controls,
    .video-container.hide-controls .center-play-btn {
      opacity: 0;
      pointer-events: none;
    }

    /* Scrubber Track */
    .scrub-container {
      position: relative;
      width: 100%;
      padding: 8px 0;
      cursor: pointer;
    }
    .scrubber-track {
      position: relative;
      width: 100%;
      height: 6px;
      background: rgba(255, 255, 255, 0.22);
      border-radius: 6px;
      transition: height 0.15s ease;
    }
    .scrub-container:hover .scrubber-track,
    .scrub-container.is-dragging .scrubber-track {
      height: 10px;
    }
    .scrubber-buffer {
      position: absolute;
      top: 0; left: 0; height: 100%;
      background: rgba(255, 255, 255, 0.38);
      border-radius: 6px;
      width: 0%;
      pointer-events: none;
    }
    .scrubber-played {
      position: absolute;
      top: 0; left: 0; height: 100%;
      background: linear-gradient(90deg, #6366f1, #06b6d4);
      border-radius: 6px;
      width: 0%;
      pointer-events: none;
    }
    .scrubber-thumb {
      position: absolute;
      top: 50%;
      width: 16px; height: 16px;
      background: #ffffff;
      border-radius: 50%;
      transform: translate(-50%, -50%) scale(0);
      box-shadow: 0 0 10px rgba(6, 182, 212, 0.9), 0 2px 4px rgba(0,0,0,0.6);
      pointer-events: none;
      left: 0%;
      transition: transform 0.15s ease;
    }
    .scrub-container:hover .scrubber-thumb,
    .scrub-container.is-dragging .scrubber-thumb {
      transform: translate(-50%, -50%) scale(1);
    }
    .scrub-tooltip {
      position: absolute;
      bottom: 24px;
      transform: translateX(-50%);
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #38bdf8;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 6px;
      pointer-events: none;
      display: none;
      white-space: nowrap;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
      z-index: 50;
    }

    /* Controls Row */
    .ctrl-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .ctrl-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .ctrl-btn {
      background: none;
      border: none;
      color: #f1f5f9;
      cursor: pointer;
      padding: 6px 8px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
    }
    .ctrl-btn:hover {
      background: rgba(255, 255, 255, 0.15);
      color: #38bdf8;
    }
    .time-label {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.82rem;
      color: #cbd5e1;
      margin-left: 4px;
      white-space: nowrap;
    }
    .vol-control {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .vol-slider {
      width: 70px;
      height: 4px;
      accent-color: #06b6d4;
      cursor: pointer;
      opacity: 0.85;
      transition: opacity 0.2s;
    }
    .vol-slider:hover { opacity: 1; }

    /* Dropdowns */
    .player-select {
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #f8fafc;
      padding: 5px 8px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 500;
      cursor: pointer;
      outline: none;
      max-width: 180px;
      transition: border-color 0.2s;
    }
    .player-select:focus, .player-select:hover {
      border-color: #6366f1;
    }
    .error-msg {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      background: rgba(239, 68, 68, 0.9);
      color: white;
      padding: 14px 20px;
      border-radius: 10px;
      font-size: 0.9rem;
      text-align: center;
      max-width: 80%;
      display: none;
      z-index: 100;
    }
  </style>
</head>
<body>
  <div class="video-container" id="videoContainer">
    <video id="player" playsinline crossorigin="anonymous" preload="metadata" onclick="togglePlay()"></video>
    

    <!-- Center Buffering Spinner -->
    <div id="bufferingSpinner" class="buffering-spinner">
      <div class="spinner-ring"></div>
      <span class="spinner-text">Buffering...</span>
    </div>

    <!-- Center Big Play Button -->
    <button id="centerPlayBtn" class="center-play-btn" onclick="togglePlay()" title="Play/Pause">
      <svg id="centerPlayIcon" width="36" height="36" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>
    </button>

    <!-- Custom Controls Bar -->
    <div id="customControls" class="custom-controls">
      <!-- Full-Width Interactive Scrubber -->
      <div id="scrubContainer" class="scrub-container">
        <div id="scrubTooltip" class="scrub-tooltip">00:00</div>
        <div id="scrubberTrack" class="scrubber-track">
          <div id="scrubberBuffer" class="scrubber-buffer"></div>
          <div id="scrubberPlayed" class="scrubber-played"></div>
          <div id="scrubberThumb" class="scrubber-thumb"></div>
        </div>
      </div>

      <!-- Controls Row -->
      <div class="ctrl-row">
        <!-- Left: Play/Pause, -10s, +10s, Volume, Time -->
        <div class="ctrl-group">
          <button id="playPauseBtn" class="ctrl-btn" title="Play/Pause (Space)" onclick="togglePlay()">
            <svg id="playIcon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            <svg id="pauseIcon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor" style="display:none;"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
          </button>

          <button class="ctrl-btn" title="Rewind 10s (Left Arrow)" onclick="seekRelative(-10)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 17l-5-5 5-5M18 17l-5-5 5-5"/></svg>
            <span style="font-size:0.65rem; font-weight:700; margin-left:-2px;">10</span>
          </button>

          <button class="ctrl-btn" title="Forward 10s (Right Arrow)" onclick="seekRelative(10)">
            <span style="font-size:0.65rem; font-weight:700; margin-right:-2px;">10</span>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>
          </button>

          <div class="vol-control">
            <button id="muteBtn" class="ctrl-btn" title="Mute/Unmute (M)" onclick="toggleMute()">
              <svg id="volHighIcon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
              <svg id="volMuteIcon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:none;"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>
            </button>
            <input type="range" id="volumeSlider" class="vol-slider" min="0" max="1" step="0.05" value="1" oninput="setVolume(this.value)">
          </div>

          <span id="timeLabel" class="time-label">0:00 / 0:00</span>
        </div>

        <!-- Right: Server, Quality, Captions, Fullscreen -->
        <div class="ctrl-group">
          <!-- Server Switcher (Native HD vs Hindi Dubbed) -->
          <select id="serverSelect" class="player-select" onchange="switchServer(this.value)" title="Stream Source">
            <option value="1">⚡ Server 1: Ultra HD Direct (MP4 / Fast Proxy)</option>
            <option value="2">🌐 Server 2: Mirror HLS Direct (Scraped Stream)</option>
            <option value="3">🎧 Server 3: Multi-Audio / Hindi Dubbed (Nova & ScreenScape)</option>
          </select>
          <select id="audioSelect" class="player-select" onchange="onAudioChange(this.value)" title="Audio Track" style="display: none;"></select>
          <select id="qualitySelect" class="player-select" onchange="onQualityChange(this.value)" title="Quality">
            <option value="">Stream Quality</option>
          </select>
          <select id="captionSelect" class="player-select" onchange="onCaptionChange(this.value)" title="Subtitles">
            <option value="-1">Subtitles: Off</option>
          </select>
          <button class="ctrl-btn" title="Fullscreen (F)" onclick="toggleFullscreen()">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
          </button>
        </div>
      </div>
    </div>

    <div id="errorBox" class="error-msg"></div>
  </div>

  <script>
    const MEDIA_TYPE = "__MEDIA_TYPE__";
    const TARGET_LANG = "__TARGET_LANG__";
    const MEDIA_ID = "__MEDIA_ID__";
    const SEASON = "__SEASON__";
    const EPISODE = "__EPISODE__";

    let currentSources = [];
    let currentTracks = [];
    let currentServers = [];
    let currentSourceIdx = 0;
    let totalDuration = 7200;
    let baseOffset = 0;
    let hlsInstance = null;
    let isDragging = false;
    let hideControlsTimeout = null;

    const video = document.getElementById('player');
    const iframe = document.getElementById('embedFrame');
    const qualitySelect = document.getElementById('qualitySelect');
    const captionSelect = document.getElementById('captionSelect');
    const serverSelect = document.getElementById('serverSelect');
    const customControls = document.getElementById('customControls');
    const videoContainer = document.getElementById('videoContainer');
    const errorBox = document.getElementById('errorBox');
    const timeLabel = document.getElementById('timeLabel');
    const playPauseBtn = document.getElementById('playPauseBtn');
    const playIcon = document.getElementById('playIcon');
    const pauseIcon = document.getElementById('pauseIcon');
    const centerPlayBtn = document.getElementById('centerPlayBtn');
    const bufferingSpinner = document.getElementById('bufferingSpinner');
    const volumeSlider = document.getElementById('volumeSlider');
    const volHighIcon = document.getElementById('volHighIcon');
    const volMuteIcon = document.getElementById('volMuteIcon');
    const scrubContainer = document.getElementById('scrubContainer');
    const scrubberTrack = document.getElementById('scrubberTrack');
    const scrubberBuffer = document.getElementById('scrubberBuffer');
    const scrubberPlayed = document.getElementById('scrubberPlayed');
    const scrubberThumb = document.getElementById('scrubberThumb');
    const scrubTooltip = document.getElementById('scrubTooltip');

    function formatTime(sec) {
      if (isNaN(sec) || !isFinite(sec) || sec < 0) sec = 0;
      sec = Math.floor(sec);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      if (h > 0) {
        return `${h}:${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
      }
      return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    function showBuffering(show) {
      bufferingSpinner.style.display = show ? 'flex' : 'none';
    }

    function updatePlayPauseUI(playing) {
      if (playing) {
        playIcon.style.display = 'none';
        pauseIcon.style.display = 'block';
        centerPlayBtn.style.display = 'none';
      } else {
        playIcon.style.display = 'block';
        pauseIcon.style.display = 'none';
        centerPlayBtn.style.display = 'flex';
      }
    }

    function togglePlay() {
      if (video.paused) {
        video.play().catch(() => {});
      } else {
        video.pause();
      }
    }

    function toggleMute() {
      video.muted = !video.muted;
      if (video.muted || video.volume === 0) {
        volHighIcon.style.display = 'none';
        volMuteIcon.style.display = 'block';
      } else {
        volHighIcon.style.display = 'block';
        volMuteIcon.style.display = 'none';
      }
    }

    function setVolume(val) {
      video.volume = parseFloat(val);
      video.muted = (video.volume === 0);
      toggleMute();
      video.muted = (video.volume === 0);
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        videoContainer.requestFullscreen().catch(err => {
          alert(`Error attempting to enable fullscreen: ${err.message}`);
        });
      } else {
        document.exitFullscreen();
      }
    }

    // Auto-hide controls during playback
    function resetHideControlsTimer() {
      videoContainer.classList.remove('hide-controls');
      clearTimeout(hideControlsTimeout);
      if (!video.paused) {
        hideControlsTimeout = setTimeout(() => {
          if (!video.paused && !isDragging) {
            videoContainer.classList.add('hide-controls');
          }
        }, 3000);
      }
    }
    videoContainer.addEventListener('mousemove', resetHideControlsTimer);
    videoContainer.addEventListener('click', resetHideControlsTimer);

    // Scrubber Logic
    function getScrubFraction(e) {
      const rect = scrubberTrack.getBoundingClientRect();
      const clientX = e.touches && e.touches.length > 0 ? e.touches[0].clientX : e.clientX;
      return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    }

    function updateScrubVisuals(fraction, updateTooltipOnly) {
      const time = fraction * totalDuration;
      const pct = fraction * 100;

      const rect = scrubberTrack.getBoundingClientRect();
      scrubTooltip.style.display = 'block';
      const tooltipX = fraction * rect.width;
      scrubTooltip.style.left = tooltipX + 'px';
      scrubTooltip.textContent = formatTime(time);

      if (!updateTooltipOnly) {
        scrubberPlayed.style.width = pct + '%';
        scrubberThumb.style.left = pct + '%';
        timeLabel.textContent = `${formatTime(time)} / ${formatTime(totalDuration)}`;
      }
    }

    scrubContainer.addEventListener('pointerdown', (e) => {
      isDragging = true;
      scrubContainer.classList.add('is-dragging');
      scrubContainer.setPointerCapture(e.pointerId);
      const frac = getScrubFraction(e);
      updateScrubVisuals(frac, false);
    });

    scrubContainer.addEventListener('pointermove', (e) => {
      const frac = getScrubFraction(e);
      if (isDragging) {
        updateScrubVisuals(frac, false);
      } else {
        updateScrubVisuals(frac, true);
      }
    });

    scrubContainer.addEventListener('pointerup', (e) => {
      if (isDragging) {
        const frac = getScrubFraction(e);
        const target = frac * totalDuration;
        seekTo(target);
        isDragging = false;
        scrubContainer.classList.remove('is-dragging');
      }
    });

    scrubContainer.addEventListener('pointercancel', () => {
      isDragging = false;
      scrubContainer.classList.remove('is-dragging');
      scrubTooltip.style.display = 'none';
    });

    scrubContainer.addEventListener('mouseleave', () => {
      if (!isDragging) {
        scrubTooltip.style.display = 'none';
      }
    });

    function seekTo(targetTime) {
      targetTime = Math.max(0, Math.min(totalDuration, targetTime));
      showBuffering(true);
      const srcObj = currentSources[currentSourceIdx];
      if (srcObj && srcObj.isTranscode) {
        baseOffset = targetTime;
        const cleanUrl = srcObj.src.replace(/&ss=[0-9.]+/, '');
        video.src = `${cleanUrl}&ss=${Math.floor(targetTime)}`;
        video.load();
        video.play().catch(() => {});
      } else {
        baseOffset = 0;
        video.currentTime = targetTime;
      }
      updateScrubUI(targetTime);
    }

    function seekRelative(delta) {
      const cur = baseOffset + video.currentTime;
      seekTo(cur + delta);
    }

    function updateScrubUI(time) {
      if (isDragging || totalDuration <= 0) return;
      const pct = Math.max(0, Math.min(100, (time / totalDuration) * 100));
      scrubberPlayed.style.width = pct + '%';
      scrubberThumb.style.left = pct + '%';
      timeLabel.textContent = `${formatTime(time)} / ${formatTime(totalDuration)}`;
    }

    video.addEventListener('loadedmetadata', function() {
      if (isFinite(video.duration) && video.duration > 0) {
        totalDuration = video.duration;
      }
      updateScrubUI(baseOffset + video.currentTime);
    });

    video.addEventListener('timeupdate', function() {
      if (isDragging) return;
      const cur = baseOffset + video.currentTime;
      if (!totalDuration && isFinite(video.duration) && video.duration > 0) {
        totalDuration = video.duration;
      }
      updateScrubUI(cur);
    });

    video.addEventListener('progress', function() {
      if (totalDuration > 0 && video.buffered.length > 0) {
        const end = baseOffset + video.buffered.end(video.buffered.length - 1);
        const pct = Math.min(100, Math.max(0, (end / totalDuration) * 100));
        scrubberBuffer.style.width = pct + '%';
      }
    });

    video.addEventListener('waiting', () => showBuffering(true));
    video.addEventListener('seeking', () => showBuffering(true));
    video.addEventListener('stalled', () => showBuffering(true));
    video.addEventListener('canplay', () => showBuffering(false));
    video.addEventListener('playing', () => {
      showBuffering(false);
      updatePlayPauseUI(true);
      resetHideControlsTimer();
    });
    video.addEventListener('pause', () => {
      updatePlayPauseUI(false);
      videoContainer.classList.remove('hide-controls');
    });
    video.addEventListener('seeked', () => showBuffering(false));

    // Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
      if (e.code === 'Space' || e.key === 'k') {
        e.preventDefault();
        togglePlay();
      } else if (e.code === 'ArrowLeft' || e.key === 'j') {
        e.preventDefault();
        seekRelative(-10);
      } else if (e.code === 'ArrowRight' || e.key === 'l') {
        e.preventDefault();
        seekRelative(10);
      } else if (e.code === 'ArrowUp') {
        e.preventDefault();
        setVolume(Math.min(1, video.volume + 0.1));
      } else if (e.code === 'ArrowDown') {
        e.preventDefault();
        setVolume(Math.max(0, video.volume - 0.1));
      } else if (e.key === 'm') {
        toggleMute();
      } else if (e.key === 'f') {
        toggleFullscreen();
      }
    });

    async function loadEmbed() {
      try {
        const apiUrl = (MEDIA_TYPE === 'tv') 
          ? `/api/source/tv/${MEDIA_ID}/${SEASON}/${EPISODE}`
          : `/api/source/${MEDIA_ID}`;
        
        const res = await fetch(apiUrl);
        const data = await res.json();
        if (data.status !== 'success' || !data.sources || data.sources.length === 0) {
          showError("No video streams available for this title.");
          return;
        }

        currentSources = data.sources;
        currentTracks = data.tracks || [];
        currentServers = data.servers || [];

        // Mixed-content prevention: upgrade http to https when on https origin
        if (window.location.protocol === "https:") {
          currentSources.forEach(s => {
            if (s.src && s.src.startsWith("http://")) {
              s.src = s.src.replace(/^http:\/\//i, "https://");
            }
          });
          currentTracks.forEach(t => {
            if (t.src && t.src.startsWith("http://")) {
              t.src = t.src.replace(/^http:\/\//i, "https://");
            }
            if (t.download_src && t.download_src.startsWith("http://")) {
              t.download_src = t.download_src.replace(/^http:\/\//i, "https://");
            }
          });
        }
        if (data.duration && data.duration > 0) totalDuration = data.duration;

        qualitySelect.innerHTML = '';
        currentSources.forEach((s, idx) => {
          const opt = document.createElement('option');
          opt.value = idx;
          opt.textContent = s.label || ('Source ' + (idx + 1));
          qualitySelect.appendChild(opt);
        });

        captionSelect.innerHTML = '<option value="-1">Subtitles: Off</option>';
        Array.from(video.querySelectorAll('track')).forEach(t => t.remove());

        let defaultIdx = -1;
        currentTracks.forEach((t, idx) => {
          const opt = document.createElement('option');
          opt.value = idx;
          opt.textContent = t.label + (t.default ? ' (Default)' : '');
          const targetLang = (new URLSearchParams(window.location.search).get('lang') || (typeof TARGET_LANG !== 'undefined' ? TARGET_LANG : '')).toLowerCase();
          const isTargetLang = targetLang && (
            (t.label && t.label.toLowerCase().includes(targetLang)) ||
            (t.srclang && t.srclang.toLowerCase() === targetLang) ||
            (targetLang === 'hindi' && ((t.label && t.label.includes('Hindi')) || t.srclang === 'hi')) ||
            (targetLang === 'tamil' && ((t.label && t.label.includes('Tamil')) || t.srclang === 'ta')) ||
            (targetLang === 'telugu' && ((t.label && t.label.includes('Telugu')) || t.srclang === 'te')) ||
            (targetLang === 'english' && ((t.label && t.label.includes('English')) || t.srclang === 'en'))
          );
          if (isTargetLang && defaultIdx === -1) {
            defaultIdx = idx;
            trackEl.default = true;
          } else if (t.default && defaultIdx === -1) {
            defaultIdx = idx;
            trackEl.default = true;
          }
          captionSelect.appendChild(opt);

          const trackEl = document.createElement('track');
          trackEl.kind = 'subtitles';
          trackEl.label = t.label;
          trackEl.srclang = t.srclang || 'en';
          trackEl.src = t.src;
          if (t.default) trackEl.default = true;
          video.appendChild(trackEl);
        });

        if (defaultIdx !== -1) {
          captionSelect.value = defaultIdx;
          setTimeout(() => setTrackMode(defaultIdx), 400);
        }

        playSource(0);
      } catch (err) {
        showError("Failed to initialize embed player: " + err.message);
      }
    }

        function switchServer(serverNum) {
      if (serverNum === "3") {
        const multiIdx = currentSources.findIndex(s => s.server === "3" || s.isMultiAudio || (s.label && s.label.includes("Multi-Audio")));
        if (multiIdx !== -1) {
          playSource(multiIdx);
        } else {
          showError("Multi-Audio / Hindi stream is not available for this specific title.");
        }
      } else if (serverNum === "2") {
        const mirrorIdx = currentSources.findIndex(s => s.isMirror || (s.label && s.label.includes("Mirror")));
        if (mirrorIdx !== -1) {
          playSource(mirrorIdx);
        } else if (currentSources.length > 1) {
          playSource(1);
        }
      } else {
        const primIdx = currentSources.findIndex(s => !s.isMirror && !s.isMultiAudio && s.server !== "3");
        if (primIdx !== -1) {
          playSource(primIdx);
        } else {
          playSource(0);
        }
      }
    }

    function setupAudioTrackSelector(tracks) {
      const selectors = [document.getElementById('audioSelect'), document.getElementById('audioSelect2')].filter(Boolean);
      const audioGroup = document.getElementById('audioGroup');
      if (!tracks || tracks.length <= 1) {
        selectors.forEach(sel => sel.style.display = 'none');
        if (audioGroup) audioGroup.style.display = 'none';
        return;
      }
      selectors.forEach(sel => {
        sel.innerHTML = '';
        tracks.forEach((t, idx) => {
          const opt = document.createElement('option');
          opt.value = idx;
          const name = t.name || t.lang || `Track ${idx + 1}`;
          opt.textContent = `🔊 ${name}`;
          sel.appendChild(opt);
        });
        sel.style.display = 'inline-block';
        if (hlsInstance) sel.value = hlsInstance.audioTrack;
      });
      if (audioGroup) audioGroup.style.display = 'flex';

      // Auto-select Hindi if requested or if Server 3 (Multi-Audio) is active
      const targetLang = (new URLSearchParams(window.location.search).get('lang') || '').toLowerCase();
      const curServer = (typeof serverSelect !== 'undefined' && serverSelect ? serverSelect.value : '') || (typeof serverSelect2 !== 'undefined' && serverSelect2 ? serverSelect2.value : '');
      if (targetLang === 'hindi' || targetLang === 'hi' || curServer === '3') {
        const hindiIdx = tracks.findIndex(t => (t.name && t.name.toLowerCase().includes('hindi')) || (t.lang && (t.lang.toLowerCase() === 'hi' || t.lang.toLowerCase() === 'hin')));
        if (hindiIdx !== -1 && hlsInstance) {
          hlsInstance.audioTrack = hindiIdx;
          selectors.forEach(sel => sel.value = hindiIdx);
        }
      }
    }

    function onAudioChange(val) {
      if (hlsInstance) {
        hlsInstance.audioTrack = parseInt(val, 10);
        const selectors = [document.getElementById('audioSelect'), document.getElementById('audioSelect2')].filter(Boolean);
        selectors.forEach(sel => sel.value = val);
      }
    }

    function playSource(index) {
      currentSourceIdx = index;
      const source = currentSources[index];
      if (!source) return;
      qualitySelect.value = index;
      baseOffset = 0;

      if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
      }

      showBuffering(true);
      if (source.type === 'application/x-mpegURL' && Hls.isSupported()) {
        hlsInstance = new Hls({ debug: false, enableWorker: true });
        hlsInstance.loadSource(source.src);
        hlsInstance.attachMedia(video);
        hlsInstance.on(Hls.Events.AUDIO_TRACKS_UPDATED, function(event, data) {
          setupAudioTrackSelector(data.audioTracks);
        });
        hlsInstance.on(Hls.Events.MANIFEST_PARSED, function() {
          if (hlsInstance.audioTracks && hlsInstance.audioTracks.length > 1) {
            setupAudioTrackSelector(hlsInstance.audioTracks);
          }
          video.play().catch(() => {});
        });
        hlsInstance.on(Hls.Events.ERROR, function(event, data) {
          if (data && data.fatal) {
            console.warn("HLS fatal error on source", currentSourceIdx, data);
            if (currentSources.length > 1 && currentSourceIdx + 1 < currentSources.length) {
              const nextIdx = currentSourceIdx + 1;
              console.log("Failing over automatically to source:", nextIdx);
              playSource(nextIdx);
            } else {
              showError("Stream connection interrupted. Try switching servers from the dropdown.");
            }
          }
        });
      } else {
        video.src = source.src;
        video.load();
        video.play().catch(() => {});
      }
    }

    function onQualityChange(val) {
      const idx = parseInt(val, 10);
      if (!isNaN(idx)) playSource(idx);
    }

    function onCaptionChange(val) {
      const idx = parseInt(val, 10);
      setTrackMode(idx);
    }

    function setTrackMode(activeIdx) {
      const textTracks = video.textTracks;
      for (let i = 0; i < textTracks.length; i++) {
        textTracks[i].mode = (i === activeIdx) ? 'showing' : 'disabled';
      }
    }

    function showError(msg) {
      errorBox.textContent = msg;
      errorBox.style.display = 'block';
      showBuffering(false);
    }

    window.addEventListener('DOMContentLoaded', loadEmbed);
  </script>
</body>
</html>
"""

@app.get("/embed/movie/{movie_id}", response_class=HTMLResponse)
@app.get("/embed/movie/{movie_id}/{lang}", response_class=HTMLResponse)
@app.get("/embed/{movie_id}", response_class=HTMLResponse)
@app.get("/embed/{movie_id}/{lang}", response_class=HTMLResponse)
async def embed_movie(request: Request, movie_id: str, lang: str = None):
    if movie_id == "movie" and lang:
        actual_id = lang
        target_lang = request.query_params.get("lang") or ""
    else:
        actual_id = movie_id
        target_lang = lang or request.query_params.get("lang") or ""
    html = EMBED_HTML_TEMPLATE.replace("__MEDIA_TYPE__", "movie")\
                               .replace("__MEDIA_ID__", actual_id)\
                               .replace("__SEASON__", "1")\
                               .replace("__EPISODE__", "1")\
                               .replace("__TARGET_LANG__", target_lang)
    return HTMLResponse(content=html)

@app.get("/embed/tv/{tv_id}/{season}/{episode}", response_class=HTMLResponse)
@app.get("/embed/tv/{tv_id}/{season}/{episode}/{lang}", response_class=HTMLResponse)
async def embed_tv(request: Request, tv_id: str, season: int, episode: int, lang: str = None):
    target_lang = lang or request.query_params.get("lang") or ""
    html = EMBED_HTML_TEMPLATE.replace("__MEDIA_TYPE__", "tv")\
                               .replace("__MEDIA_ID__", tv_id)\
                               .replace("__SEASON__", str(season))\
                               .replace("__EPISODE__", str(episode))\
                               .replace("__TARGET_LANG__", target_lang)
    return HTMLResponse(content=html)

# ==========================================
# 7. Built-in Web Player UI (Zero Iframes)
# ==========================================
PLAYER_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Universal Stream Player & Subtitle Extractor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(17, 24, 39, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --primary: #6366f1;
      --primary-hover: #4f46e5;
      --accent: #06b6d4;
      --text: #f8fafc;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      background-image: 
        radial-gradient(circle at 15% 20%, rgba(99, 102, 241, 0.12) 0%, transparent 40%),
        radial-gradient(circle at 85% 80%, rgba(6, 182, 212, 0.12) 0%, transparent 40%);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px 20px;
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    /* Header & Navigation */
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      padding: 16px 22px;
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--card-border);
      border-radius: 16px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 800;
      font-size: 1.25rem;
      letter-spacing: -0.02em;
    }
    .mode-toggle {
      display: flex;
      background: rgba(0, 0, 0, 0.4);
      padding: 4px;
      border-radius: 12px;
      border: 1px solid var(--card-border);
      gap: 4px;
    }
    .mode-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }
    .mode-btn.active {
      background: var(--primary);
      color: #fff;
    }
    .search-box { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .search-input {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 0.95rem;
      font-family: inherit;
    }
    .search-input:focus { outline: none; border-color: var(--primary); }
    .btn {
      background: var(--primary);
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 10px;
      font-weight: 600;
      font-size: 0.95rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn:hover { background: var(--primary-hover); transform: translateY(-1px); }
    .btn-secondary { background: rgba(255, 255, 255, 0.08); border: 1px solid var(--card-border); }
    .btn-secondary:hover { background: rgba(255, 255, 255, 0.15); }
    .btn-success { background: #10b981; }
    .btn-success:hover { background: #059669; }
    .btn-sm { padding: 4px 10px; font-size: 0.8rem; }

    /* Video Player Card */
    .player-card {
      background: #000;
      border-radius: 16px;
      overflow: hidden;
      border: 1px solid var(--card-border);
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7);
    }
    .video-wrapper {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #000;
      overflow: hidden;
    }
    video {
      width: 100%; height: 100%;
      object-fit: contain;
      background: #000;
      cursor: pointer;
    }
    video::cue {
      background: rgba(0, 0, 0, 0.85);
      color: #ffffff;
      font-size: 1.15rem;
      font-family: 'Plus Jakarta Sans', sans-serif;
      text-shadow: 0 2px 4px rgba(0,0,0,0.9);
      border-radius: 4px;
      padding: 3px 8px;
    }
    iframe
    /* Centered Buffering Spinner */
    .buffering-spinner {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      display: none;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      z-index: 35;
      pointer-events: none;
    }
    .spinner-ring {
      width: 54px; height: 54px;
      border: 4px solid rgba(255, 255, 255, 0.15);
      border-top-color: #06b6d4;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      box-shadow: 0 0 16px rgba(6, 182, 212, 0.5);
    }
    .spinner-text {
      font-size: 0.88rem;
      font-weight: 600;
      color: #e2e8f0;
      text-shadow: 0 2px 4px rgba(0,0,0,0.8);
      letter-spacing: 0.5px;
    }
    @keyframes spin { 100% { transform: rotate(360deg); } }

    /* Center Big Play Button */
    .center-play-btn {
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      width: 76px; height: 76px;
      background: rgba(15, 23, 42, 0.75);
      backdrop-filter: blur(8px);
      border: 2px solid rgba(255, 255, 255, 0.25);
      border-radius: 50%;
      color: #fff;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer;
      z-index: 30;
      transition: all 0.2s ease;
      box-shadow: 0 4px 25px rgba(0,0,0,0.6);
    }
    .center-play-btn:hover {
      transform: translate(-50%, -50%) scale(1.1);
      background: rgba(99, 102, 241, 0.9);
      border-color: #6366f1;
    }

    /* Floating Player Controls Bar */
    .custom-controls {
      position: absolute;
      bottom: 0; left: 0; right: 0;
      background: linear-gradient(to top, rgba(10, 15, 30, 0.95) 0%, rgba(10, 15, 30, 0.7) 60%, transparent 100%);
      padding: 18px 22px 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      z-index: 40;
      opacity: 1;
      transition: opacity 0.3s ease;
    }
    .video-wrapper.hide-controls .custom-controls,
    .video-wrapper.hide-controls .center-play-btn {
      opacity: 0;
      pointer-events: none;
    }

    /* Scrubber Track */
    .scrub-container {
      position: relative;
      width: 100%;
      padding: 8px 0;
      cursor: pointer;
    }
    .scrubber-track {
      position: relative;
      width: 100%;
      height: 6px;
      background: rgba(255, 255, 255, 0.22);
      border-radius: 6px;
      transition: height 0.15s ease;
    }
    .scrub-container:hover .scrubber-track,
    .scrub-container.is-dragging .scrubber-track {
      height: 10px;
    }
    .scrubber-buffer {
      position: absolute;
      top: 0; left: 0; height: 100%;
      background: rgba(255, 255, 255, 0.38);
      border-radius: 6px;
      width: 0%;
      pointer-events: none;
    }
    .scrubber-played {
      position: absolute;
      top: 0; left: 0; height: 100%;
      background: linear-gradient(90deg, #6366f1, #06b6d4);
      border-radius: 6px;
      width: 0%;
      pointer-events: none;
    }
    .scrubber-thumb {
      position: absolute;
      top: 50%;
      width: 16px; height: 16px;
      background: #ffffff;
      border-radius: 50%;
      transform: translate(-50%, -50%) scale(0);
      box-shadow: 0 0 10px rgba(6, 182, 212, 0.9), 0 2px 4px rgba(0,0,0,0.6);
      pointer-events: none;
      left: 0%;
      transition: transform 0.15s ease;
    }
    .scrub-container:hover .scrubber-thumb,
    .scrub-container.is-dragging .scrubber-thumb {
      transform: translate(-50%, -50%) scale(1);
    }
    .scrub-tooltip {
      position: absolute;
      bottom: 24px;
      transform: translateX(-50%);
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #38bdf8;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 6px;
      pointer-events: none;
      display: none;
      white-space: nowrap;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
      z-index: 50;
    }

    /* Controls Row */
    .ctrl-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .ctrl-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .ctrl-btn {
      background: none;
      border: none;
      color: #f1f5f9;
      cursor: pointer;
      padding: 6px 8px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
    }
    .ctrl-btn:hover {
      background: rgba(255, 255, 255, 0.15);
      color: #38bdf8;
    }
    .time-label {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.82rem;
      color: #cbd5e1;
      margin-left: 4px;
      white-space: nowrap;
    }
    .vol-control {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .vol-slider {
      width: 70px;
      height: 4px;
      accent-color: #06b6d4;
      cursor: pointer;
      opacity: 0.85;
      transition: opacity 0.2s;
    }
    .vol-slider:hover { opacity: 1; }

    .player-select {
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #f8fafc;
      padding: 5px 8px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 500;
      cursor: pointer;
      outline: none;
      max-width: 180px;
      transition: border-color 0.2s;
    }
    .player-select:focus, .player-select:hover {
      border-color: #6366f1;
    }

    /* Below Player Secondary Bar */
    .controls-bar {
      padding: 16px 20px;
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }
    .select-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .quality-select {
      background: rgba(0, 0, 0, 0.5);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 0.9rem;
      font-family: inherit;
      cursor: pointer;
    }
    .quality-select:focus { outline: none; border-color: var(--primary); }

    /* Sections */
    .section-card {
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .section-title {
      font-size: 1.05rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
    }
    .url-input {
      width: 100%;
      background: rgba(0, 0, 0, 0.5);
      border: 1px solid var(--card-border);
      color: var(--accent);
      padding: 10px 14px;
      border-radius: 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.88rem;
    }
    .url-input:focus { outline: none; border-color: var(--accent); }

    .subtitle-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .sub-chip {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--card-border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 500;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .sub-chip:hover {
      background: var(--primary);
      color: #fff;
      transform: translateY(-1px);
    }
    .sub-chip.indian-lang {
      border-color: rgba(6, 182, 212, 0.4);
      background: rgba(6, 182, 212, 0.1);
    }
    .sub-chip.indian-lang:hover {
      background: var(--accent);
      color: #000;
    }

    .code-box {
      background: #000;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 14px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.85rem;
      color: #cbd5e1;
      overflow-x: auto;
      white-space: pre;
    }
    .alert {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #fca5a5;
      padding: 12px 16px;
      border-radius: 12px;
      font-size: 0.9rem;
      display: none;
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="brand">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Universal Stream Hub
      </div>

      <!-- Mode Toggle -->
      <div class="mode-toggle">
        <button id="modeMovie" class="mode-btn active" onclick="setMode('movie')">🎬 Movie</button>
        <button id="modeTv" class="mode-btn" onclick="setMode('tv')">📺 TV Show</button>
      </div>

      <!-- Search Box -->
      <div class="search-box">
        <input type="text" id="mediaIdInput" class="search-input" style="width: 130px;" placeholder="TMDB ID..." />
        <div id="tvInputs" style="display: none; gap: 6px; align-items: center;">
          <input type="number" id="seasonInput" class="search-input" style="width: 65px;" placeholder="S#" min="1" value="1" />
          <input type="number" id="episodeInput" class="search-input" style="width: 65px;" placeholder="E#" min="1" value="1" />
        </div>
        <button class="btn" onclick="applySearch()">Load Stream</button>
      </div>
    </div>

    <div id="error-box" class="alert"></div>

    <!-- Video Player Card -->
    <div class="player-card">
      <div class="video-wrapper" id="videoWrapper">
        <video id="player" playsinline crossorigin="anonymous" preload="metadata" onclick="togglePlay()"></video>
        

        <!-- Center Buffering Spinner -->
        <div id="bufferingSpinner" class="buffering-spinner">
          <div class="spinner-ring"></div>
          <span class="spinner-text">Buffering...</span>
        </div>

        <!-- Center Big Play Button -->
        <button id="centerPlayBtn" class="center-play-btn" onclick="togglePlay()" title="Play/Pause">
          <svg id="centerPlayIcon" width="38" height="38" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>
        </button>

        <!-- Custom Controls Bar -->
        <div id="customControls" class="custom-controls">
          <!-- Full-Width Interactive Scrubber -->
          <div id="scrubContainer" class="scrub-container">
            <div id="scrubTooltip" class="scrub-tooltip">00:00</div>
            <div id="scrubberTrack" class="scrubber-track">
              <div id="scrubberBuffer" class="scrubber-buffer"></div>
              <div id="scrubberPlayed" class="scrubber-played"></div>
              <div id="scrubberThumb" class="scrubber-thumb"></div>
            </div>
          </div>

          <!-- Controls Row -->
          <div class="ctrl-row">
            <!-- Left: Play/Pause, -10s, +10s, Volume, Time -->
            <div class="ctrl-group">
              <button id="playPauseBtn" class="ctrl-btn" title="Play/Pause (Space)" onclick="togglePlay()">
                <svg id="playIcon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                <svg id="pauseIcon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor" style="display:none;"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
              </button>

              <button class="ctrl-btn" title="Rewind 10s (Left Arrow)" onclick="seekRelative(-10)">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 17l-5-5 5-5M18 17l-5-5 5-5"/></svg>
                <span style="font-size:0.65rem; font-weight:700; margin-left:-2px;">10</span>
              </button>

              <button class="ctrl-btn" title="Forward 10s (Right Arrow)" onclick="seekRelative(10)">
                <span style="font-size:0.65rem; font-weight:700; margin-right:-2px;">10</span>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>
              </button>

              <div class="vol-control">
                <button id="muteBtn" class="ctrl-btn" title="Mute/Unmute (M)" onclick="toggleMute()">
                  <svg id="volHighIcon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
                  <svg id="volMuteIcon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:none;"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>
                </button>
                <input type="range" id="volumeSlider" class="vol-slider" min="0" max="1" step="0.05" value="1" oninput="setVolume(this.value)">
              </div>

              <span id="timeLabel" class="time-label">0:00 / 0:00</span>
            </div>

            <!-- Right: Server, Quality, Captions, Fullscreen -->
            <div class="ctrl-group">
              <select id="serverSelect" class="player-select" onchange="switchServer(this.value)" title="Stream Source">
            <option value="1">⚡ Server 1: Ultra HD Direct (MP4 / Fast Proxy)</option>
            <option value="2">🌐 Server 2: Mirror HLS Direct (Scraped Stream)</option>
            <option value="3">🎧 Server 3: Multi-Audio / Hindi Dubbed (Nova & ScreenScape)</option>
          </select>
          <select id="audioSelect" class="player-select" onchange="onAudioChange(this.value)" title="Audio Track" style="display: none;"></select>
              <select id="qualitySelect" class="player-select" onchange="onQualityChange(this.value)" title="Quality">
                <option value="">Stream Quality</option>
              </select>
              <select id="captionSelect" class="player-select" onchange="onCaptionChange(this.value)" title="Subtitles">
                <option value="-1">Subtitles: Off</option>
              </select>
              <button class="ctrl-btn" title="Fullscreen (F)" onclick="toggleFullscreen()">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Below-Player Secondary Controls Bar -->
    <div id="nativeControlsBar" class="controls-bar">
      <!-- Server Switcher -->
      <div class="select-group">
        <span style="font-size: 0.88rem; color: var(--text-muted); font-weight: 600;">Server / Audio:</span>
        <select id="serverSelect2" class="quality-select" onchange="switchServer(this.value)">
          <option value="1">⚡ Server 1: Ultra HD Direct (MP4 / Fast Proxy)</option>
          <option value="2">🌐 Server 2: Mirror HLS Direct (Scraped Stream)</option>
          <option value="3">🎧 Server 3: Multi-Audio / Hindi Dubbed (Nova & ScreenScape)</option>
        </select>
      </div>

      <!-- Multi-Audio Track Selector -->
      <div id="audioGroup" class="select-group" style="display: none;">
        <span style="font-size: 0.88rem; color: var(--text-muted); font-weight: 600;">Audio Language:</span>
        <select id="audioSelect2" class="quality-select" onchange="onAudioChange(this.value)">
          <option value="0">Audio: Default</option>
        </select>
      </div>

      <!-- Quality Selector -->
      <div class="select-group">
        <span style="font-size: 0.88rem; color: var(--text-muted); font-weight: 600;">Stream Quality:</span>
        <select id="qualitySelect2" class="quality-select" onchange="onQualityChange(this.value)">
          <option value="">Loading streams...</option>
        </select>
      </div>

      <!-- Subtitle Selector -->
      <div class="select-group">
        <span style="font-size: 0.88rem; color: var(--text-muted); font-weight: 600;">Subtitles:</span>
        <select id="captionSelect2" class="quality-select" onchange="onCaptionChange(this.value)">
          <option value="-1">Off (No Subtitles)</option>
        </select>
      </div>

      <!-- Action Buttons -->
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button id="downloadSubBtn" class="btn btn-success" onclick="downloadActiveSubtitle()">
          📥 Extract Subtitle (.SRT)
        </button>
        <button class="btn btn-secondary" onclick="openInVlc()">🚀 Open in VLC</button>
      </div>
    </div>

    <!-- Direct Stream & Embed URLs Section -->
    <div class="section-card">
      <div class="section-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        Direct Stream URL & Embed Codes (For Any Website / Player)
      </div>

      <div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <span style="font-size: 0.85rem; font-weight: 600; color: var(--accent);">Direct Stream URL (Playable in Browser, VLC, Mobile & &lt;video src="..."&gt;):</span>
          <button class="btn btn-secondary btn-sm" onclick="copyDirectStreamUrl()">📋 Copy Stream URL</button>
        </div>
        <input type="text" id="directStreamUrlInput" readonly class="url-input" />
      </div>

      <div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <span style="font-size: 0.85rem; font-weight: 600; color: var(--accent);">Iframe Embed Code (Drop into Any Website):</span>
          <button class="btn btn-secondary btn-sm" onclick="copyIframeCode()">📋 Copy Iframe Code</button>
        </div>
        <input type="text" id="iframeCodeInput" readonly class="url-input" />
      </div>
    </div>

    <!-- Subtitle Extraction Section (With Indian Languages) -->
    <div class="section-card">
      <div class="section-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        All Available Subtitles & Indian Translations (One-Click Download / Extraction):
      </div>
      <div id="subtitleList" class="subtitle-chips">
        <span style="font-size: 0.85rem; color: var(--text-muted);">Fetching subtitle tracks...</span>
      </div>
    </div>

    <!-- Video.js Integration Code Section -->
    <div class="section-card">
      <div class="section-title">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
        Embed in your External Website (Video.js Player Code with Subtitles):
      </div>
      <div class="code-box" id="embedCode">Loading embed code...</div>
    </div>
  </div>

  <script>
    let currentMode = "__MEDIA_TYPE__";
    let currentMediaId = "__TARGET_ID__";
    let currentSeason = parseInt("__TARGET_SEASON__", 10) || 1;
    let currentEpisode = parseInt("__TARGET_EPISODE__", 10) || 1;
    let currentTargetLang = "__TARGET_LANG__";

    let currentSources = [];
    let currentTracks = [];
    let currentServers = [];
    let currentSourceIdx = 0;
    let totalDuration = 7200;
    let baseOffset = 0;
    let hlsInstance = null;
    let isDragging = false;
    let hideControlsTimeout = null;

    const video = document.getElementById('player');
    const videoWrapper = document.getElementById('videoWrapper');
    const qualitySelect = document.getElementById('qualitySelect');
    const qualitySelect2 = document.getElementById('qualitySelect2');
    const captionSelect = document.getElementById('captionSelect');
    const captionSelect2 = document.getElementById('captionSelect2');
    const serverSelect = document.getElementById('serverSelect');
    const serverSelect2 = document.getElementById('serverSelect2');
    const customControls = document.getElementById('customControls');
    const timeLabel = document.getElementById('timeLabel');
    const playPauseBtn = document.getElementById('playPauseBtn');
    const playIcon = document.getElementById('playIcon');
    const pauseIcon = document.getElementById('pauseIcon');
    const centerPlayBtn = document.getElementById('centerPlayBtn');
    const bufferingSpinner = document.getElementById('bufferingSpinner');
    const volumeSlider = document.getElementById('volumeSlider');
    const volHighIcon = document.getElementById('volHighIcon');
    const volMuteIcon = document.getElementById('volMuteIcon');
    const scrubContainer = document.getElementById('scrubContainer');
    const scrubberTrack = document.getElementById('scrubberTrack');
    const scrubberBuffer = document.getElementById('scrubberBuffer');
    const scrubberPlayed = document.getElementById('scrubberPlayed');
    const scrubberThumb = document.getElementById('scrubberThumb');
    const scrubTooltip = document.getElementById('scrubTooltip');
    const errorBox = document.getElementById('error-box');

    function formatTime(sec) {
      if (isNaN(sec) || !isFinite(sec) || sec < 0) sec = 0;
      sec = Math.floor(sec);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      if (h > 0) {
        return `${h}:${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
      }
      return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    function showBuffering(show) {
      bufferingSpinner.style.display = show ? 'flex' : 'none';
    }

    function updatePlayPauseUI(playing) {
      if (playing) {
        playIcon.style.display = 'none';
        pauseIcon.style.display = 'block';
        centerPlayBtn.style.display = 'none';
      } else {
        playIcon.style.display = 'block';
        pauseIcon.style.display = 'none';
        centerPlayBtn.style.display = 'flex';
      }
    }

    function togglePlay() {
      if (video.paused) {
        video.play().catch(() => {});
      } else {
        video.pause();
      }
    }

    function toggleMute() {
      video.muted = !video.muted;
      if (video.muted || video.volume === 0) {
        volHighIcon.style.display = 'none';
        volMuteIcon.style.display = 'block';
      } else {
        volHighIcon.style.display = 'block';
        volMuteIcon.style.display = 'none';
      }
    }

    function setVolume(val) {
      video.volume = parseFloat(val);
      video.muted = (video.volume === 0);
      toggleMute();
      video.muted = (video.volume === 0);
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        videoWrapper.requestFullscreen().catch(err => {
          alert(`Error attempting to enable fullscreen: ${err.message}`);
        });
      } else {
        document.exitFullscreen();
      }
    }

    // Auto-hide controls
    function resetHideControlsTimer() {
      videoWrapper.classList.remove('hide-controls');
      clearTimeout(hideControlsTimeout);
      if (!video.paused) {
        hideControlsTimeout = setTimeout(() => {
          if (!video.paused && !isDragging) {
            videoWrapper.classList.add('hide-controls');
          }
        }, 3000);
      }
    }
    videoWrapper.addEventListener('mousemove', resetHideControlsTimer);
    videoWrapper.addEventListener('click', resetHideControlsTimer);

    // Scrubber Logic
    function getScrubFraction(e) {
      const rect = scrubberTrack.getBoundingClientRect();
      const clientX = e.touches && e.touches.length > 0 ? e.touches[0].clientX : e.clientX;
      return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    }

    function updateScrubVisuals(fraction, updateTooltipOnly) {
      const time = fraction * totalDuration;
      const pct = fraction * 100;

      const rect = scrubberTrack.getBoundingClientRect();
      scrubTooltip.style.display = 'block';
      const tooltipX = fraction * rect.width;
      scrubTooltip.style.left = tooltipX + 'px';
      scrubTooltip.textContent = formatTime(time);

      if (!updateTooltipOnly) {
        scrubberPlayed.style.width = pct + '%';
        scrubberThumb.style.left = pct + '%';
        timeLabel.textContent = `${formatTime(time)} / ${formatTime(totalDuration)}`;
      }
    }

    scrubContainer.addEventListener('pointerdown', (e) => {
      isDragging = true;
      scrubContainer.classList.add('is-dragging');
      scrubContainer.setPointerCapture(e.pointerId);
      const frac = getScrubFraction(e);
      updateScrubVisuals(frac, false);
    });

    scrubContainer.addEventListener('pointermove', (e) => {
      const frac = getScrubFraction(e);
      if (isDragging) {
        updateScrubVisuals(frac, false);
      } else {
        updateScrubVisuals(frac, true);
      }
    });

    scrubContainer.addEventListener('pointerup', (e) => {
      if (isDragging) {
        const frac = getScrubFraction(e);
        const target = frac * totalDuration;
        seekTo(target);
        isDragging = false;
        scrubContainer.classList.remove('is-dragging');
      }
    });

    scrubContainer.addEventListener('pointercancel', () => {
      isDragging = false;
      scrubContainer.classList.remove('is-dragging');
      scrubTooltip.style.display = 'none';
    });

    scrubContainer.addEventListener('mouseleave', () => {
      if (!isDragging) {
        scrubTooltip.style.display = 'none';
      }
    });

    function seekTo(targetTime) {
      targetTime = Math.max(0, Math.min(totalDuration, targetTime));
      showBuffering(true);
      const srcObj = currentSources[currentSourceIdx];
      if (srcObj && srcObj.isTranscode) {
        baseOffset = targetTime;
        const cleanUrl = srcObj.src.replace(/&ss=[0-9.]+/, '');
        video.src = `${cleanUrl}&ss=${Math.floor(targetTime)}`;
        video.load();
        video.play().catch(() => {});
      } else {
        baseOffset = 0;
        video.currentTime = targetTime;
      }
      updateScrubUI(targetTime);
    }

    function seekRelative(delta) {
      const cur = baseOffset + video.currentTime;
      seekTo(cur + delta);
    }

    function updateScrubUI(time) {
      if (isDragging || totalDuration <= 0) return;
      const pct = Math.max(0, Math.min(100, (time / totalDuration) * 100));
      scrubberPlayed.style.width = pct + '%';
      scrubberThumb.style.left = pct + '%';
      timeLabel.textContent = `${formatTime(time)} / ${formatTime(totalDuration)}`;
    }

    video.addEventListener('loadedmetadata', function() {
      if (isFinite(video.duration) && video.duration > 0) {
        totalDuration = video.duration;
      }
      updateScrubUI(baseOffset + video.currentTime);
    });

    video.addEventListener('timeupdate', function() {
      if (isDragging) return;
      const cur = baseOffset + video.currentTime;
      if (!totalDuration && isFinite(video.duration) && video.duration > 0) {
        totalDuration = video.duration;
      }
      updateScrubUI(cur);
    });

    video.addEventListener('progress', function() {
      if (totalDuration > 0 && video.buffered.length > 0) {
        const end = baseOffset + video.buffered.end(video.buffered.length - 1);
        const pct = Math.min(100, Math.max(0, (end / totalDuration) * 100));
        scrubberBuffer.style.width = pct + '%';
      }
    });

    video.addEventListener('waiting', () => showBuffering(true));
    video.addEventListener('seeking', () => showBuffering(true));
    video.addEventListener('stalled', () => showBuffering(true));
    video.addEventListener('canplay', () => showBuffering(false));
    video.addEventListener('playing', () => {
      showBuffering(false);
      updatePlayPauseUI(true);
      resetHideControlsTimer();
    });
    video.addEventListener('pause', () => {
      updatePlayPauseUI(false);
      videoWrapper.classList.remove('hide-controls');
    });
    video.addEventListener('seeked', () => showBuffering(false));

    // Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
      if (e.code === 'Space' || e.key === 'k') {
        e.preventDefault();
        togglePlay();
      } else if (e.code === 'ArrowLeft' || e.key === 'j') {
        e.preventDefault();
        seekRelative(-10);
      } else if (e.code === 'ArrowRight' || e.key === 'l') {
        e.preventDefault();
        seekRelative(10);
      } else if (e.code === 'ArrowUp') {
        e.preventDefault();
        setVolume(Math.min(1, video.volume + 0.1));
      } else if (e.code === 'ArrowDown') {
        e.preventDefault();
        setVolume(Math.max(0, video.volume - 0.1));
      } else if (e.key === 'm') {
        toggleMute();
      } else if (e.key === 'f') {
        toggleFullscreen();
      }
    });

    // UI Handlers
    function setMode(mode) {
      currentMode = mode;
      document.getElementById('modeMovie').classList.toggle('active', mode === 'movie');
      document.getElementById('modeTv').classList.toggle('active', mode === 'tv');
      document.getElementById('tvInputs').style.display = (mode === 'tv') ? 'flex' : 'none';
      if (mode === 'movie') {
        document.getElementById('mediaIdInput').value = '1148365';
      } else {
        document.getElementById('mediaIdInput').value = '1399';
        document.getElementById('seasonInput').value = '1';
        document.getElementById('episodeInput').value = '1';
      }
    }

    function applySearch() {
      const idVal = document.getElementById('mediaIdInput').value.trim();
      if (!idVal) return;
      currentMediaId = idVal;
      if (currentMode === 'tv') {
        currentSeason = parseInt(document.getElementById('seasonInput').value, 10) || 1;
        currentEpisode = parseInt(document.getElementById('episodeInput').value, 10) || 1;
        window.history.pushState({}, '', `/watch/tv/${currentMediaId}/${currentSeason}/${currentEpisode}`);
      } else {
        window.history.pushState({}, '', `/watch/${currentMediaId}`);
      }
      loadStreams();
    }

    async function loadStreams() {
      try {
        errorBox.style.display = 'none';
        const apiUrl = (currentMode === 'tv')
          ? `/api/source/tv/${currentMediaId}/${currentSeason}/${currentEpisode}`
          : `/api/source/${currentMediaId}`;

        const res = await fetch(apiUrl);
        const data = await res.json();
        if (data.status !== 'success' || !data.sources || data.sources.length === 0) {
          showError(`No video streams found for ${currentMode.toUpperCase()} ID: ${currentMediaId}`);
          return;
        }

        currentSources = data.sources;
        currentTracks = data.tracks || [];
        currentServers = data.servers || [];

        // Mixed-content prevention: upgrade http to https when on https origin
        if (window.location.protocol === "https:") {
          currentSources.forEach(s => {
            if (s.src && s.src.startsWith("http://")) {
              s.src = s.src.replace(/^http:\/\//i, "https://");
            }
          });
          currentTracks.forEach(t => {
            if (t.src && t.src.startsWith("http://")) {
              t.src = t.src.replace(/^http:\/\//i, "https://");
            }
            if (t.download_src && t.download_src.startsWith("http://")) {
              t.download_src = t.download_src.replace(/^http:\/\//i, "https://");
            }
          });
        }
        if (data.duration && data.duration > 0) totalDuration = data.duration;

        // Quality Selectors (both on-player and below-player)
        [qualitySelect, qualitySelect2].forEach(sel => {
          sel.innerHTML = '';
          currentSources.forEach((s, idx) => {
            const opt = document.createElement('option');
            opt.value = idx;
            opt.textContent = s.label || ('Source ' + (idx + 1));
            sel.appendChild(opt);
          });
        });

        // Server Selectors
        [serverSelect, serverSelect2].forEach(sel => {
          sel.value = "1";
        });

        // Subtitles
        populateSubtitles(currentTracks);

        // Update URLs
        updateLinkInputs();
        updateEmbedSnippet(currentSources[0].src, currentTracks);

        // Start playback
        playSource(0);
      } catch (err) {
        showError("Failed to fetch stream data: " + err.message);
      }
    }

    function populateSubtitles(tracks) {
      [captionSelect, captionSelect2].forEach(sel => {
        sel.innerHTML = '<option value="-1">Subtitles: Off</option>';
      });
      const chipList = document.getElementById('subtitleList');
      chipList.innerHTML = '';

      Array.from(video.querySelectorAll('track')).forEach(t => t.remove());

      let defaultIdx = -1;
      tracks.forEach((t, idx) => {
        [captionSelect, captionSelect2].forEach(sel => {
          const opt = document.createElement('option');
          opt.value = idx;
          opt.textContent = t.label + (t.default ? ' (Default)' : '');
          sel.appendChild(opt);
        });

        const trackEl = document.createElement('track');
        trackEl.kind = 'subtitles';
        trackEl.label = t.label;
        trackEl.srclang = t.srclang || 'en';
        trackEl.src = t.src;
        const targetLang = (new URLSearchParams(window.location.search).get('lang') || (typeof currentTargetLang !== 'undefined' ? currentTargetLang : '')).toLowerCase();
        const isTargetLang = targetLang && (
          (t.label && t.label.toLowerCase().includes(targetLang)) ||
          (t.srclang && t.srclang.toLowerCase() === targetLang) ||
          (targetLang === 'hindi' && ((t.label && t.label.includes('Hindi')) || t.srclang === 'hi')) ||
          (targetLang === 'tamil' && ((t.label && t.label.includes('Tamil')) || t.srclang === 'ta')) ||
          (targetLang === 'telugu' && ((t.label && t.label.includes('Telugu')) || t.srclang === 'te')) ||
          (targetLang === 'english' && ((t.label && t.label.includes('English')) || t.srclang === 'en'))
        );
        if (isTargetLang && defaultIdx === -1) {
          trackEl.default = true;
          defaultIdx = idx;
        } else if (t.default && defaultIdx === -1) {
          trackEl.default = true;
          defaultIdx = idx;
        }
        video.appendChild(trackEl);

        // Download Chip
        const chip = document.createElement('a');
        chip.href = t.download_src || t.src;
        chip.className = 'sub-chip';
        const isIndian = ['hi', 'ta', 'te', 'ml', 'kn', 'mr', 'bn', 'pa', 'gu', 'ur'].includes(t.srclang);
        if (isIndian) chip.classList.add('indian-lang');
        chip.textContent = `${t.label} (.SRT)`;
        chipList.appendChild(chip);
      });

      if (defaultIdx !== -1) {
        captionSelect.value = defaultIdx;
        captionSelect2.value = defaultIdx;
        setTimeout(() => setTrackMode(defaultIdx), 400);
      }
    }

    function playSource(index) {
      currentSourceIdx = index;
      const source = currentSources[index];
      if (!source) return;

      qualitySelect.value = index;
      if (typeof qualitySelect2 !== 'undefined' && qualitySelect2) qualitySelect2.value = index;
      baseOffset = 0;
      if (typeof serverSelect !== 'undefined' && serverSelect) {
        if (source.server === '3' || source.isMultiAudio || (source.label && source.label.includes('Multi-Audio'))) {
          serverSelect.value = '3';
          if (typeof serverSelect2 !== 'undefined' && serverSelect2) serverSelect2.value = '3';
        } else if (source.isMirror || (source.label && source.label.includes('Mirror'))) {
          serverSelect.value = '2';
          if (typeof serverSelect2 !== 'undefined' && serverSelect2) serverSelect2.value = '2';
        } else {
          serverSelect.value = '1';
          if (typeof serverSelect2 !== 'undefined' && serverSelect2) serverSelect2.value = '1';
        }
      }

      if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
      }

      showBuffering(true);
      if (source.type === 'application/x-mpegURL' && Hls.isSupported()) {
        hlsInstance = new Hls({ debug: false, enableWorker: true });
        hlsInstance.loadSource(source.src);
        hlsInstance.attachMedia(video);
        hlsInstance.on(Hls.Events.AUDIO_TRACKS_UPDATED, function(event, data) {
          setupAudioTrackSelector(data.audioTracks);
        });
        hlsInstance.on(Hls.Events.MANIFEST_PARSED, function() {
          if (hlsInstance.audioTracks && hlsInstance.audioTracks.length > 1) {
            setupAudioTrackSelector(hlsInstance.audioTracks);
          }
          video.play().catch(() => {});
        });
        hlsInstance.on(Hls.Events.ERROR, function(event, data) {
          if (data && data.fatal) {
            console.warn("HLS fatal error on source", currentSourceIdx, data);
            if (currentSources.length > 1 && currentSourceIdx + 1 < currentSources.length) {
              const nextIdx = currentSourceIdx + 1;
              console.log("Failing over automatically to source:", nextIdx);
              playSource(nextIdx);
            } else {
              showError("Stream connection interrupted. Try switching servers from the dropdown.");
            }
          }
        });
      } else {
        video.src = source.src;
        video.load();
        video.play().catch(() => {});
      }
    }

        function switchServer(serverNum) {
      if (serverNum === "3") {
        const multiIdx = currentSources.findIndex(s => s.server === "3" || s.isMultiAudio || (s.label && s.label.includes("Multi-Audio")));
        if (multiIdx !== -1) {
          playSource(multiIdx);
        } else {
          showError("Multi-Audio / Hindi stream is not available for this specific title.");
        }
      } else if (serverNum === "2") {
        const mirrorIdx = currentSources.findIndex(s => s.isMirror || (s.label && s.label.includes("Mirror")));
        if (mirrorIdx !== -1) {
          playSource(mirrorIdx);
        } else if (currentSources.length > 1) {
          playSource(1);
        }
      } else {
        const primIdx = currentSources.findIndex(s => !s.isMirror && !s.isMultiAudio && s.server !== "3");
        if (primIdx !== -1) {
          playSource(primIdx);
        } else {
          playSource(0);
        }
      }
    }

    function setupAudioTrackSelector(tracks) {
      const selectors = [document.getElementById('audioSelect'), document.getElementById('audioSelect2')].filter(Boolean);
      const audioGroup = document.getElementById('audioGroup');
      if (!tracks || tracks.length <= 1) {
        selectors.forEach(sel => sel.style.display = 'none');
        if (audioGroup) audioGroup.style.display = 'none';
        return;
      }
      selectors.forEach(sel => {
        sel.innerHTML = '';
        tracks.forEach((t, idx) => {
          const opt = document.createElement('option');
          opt.value = idx;
          const name = t.name || t.lang || `Track ${idx + 1}`;
          opt.textContent = `🔊 ${name}`;
          sel.appendChild(opt);
        });
        sel.style.display = 'inline-block';
        if (hlsInstance) sel.value = hlsInstance.audioTrack;
      });
      if (audioGroup) audioGroup.style.display = 'flex';

      // Auto-select Hindi if requested or if Server 3 (Multi-Audio) is active
      const targetLang = (new URLSearchParams(window.location.search).get('lang') || '').toLowerCase();
      const curServer = (typeof serverSelect !== 'undefined' && serverSelect ? serverSelect.value : '') || (typeof serverSelect2 !== 'undefined' && serverSelect2 ? serverSelect2.value : '');
      if (targetLang === 'hindi' || targetLang === 'hi' || curServer === '3') {
        const hindiIdx = tracks.findIndex(t => (t.name && t.name.toLowerCase().includes('hindi')) || (t.lang && (t.lang.toLowerCase() === 'hi' || t.lang.toLowerCase() === 'hin')));
        if (hindiIdx !== -1 && hlsInstance) {
          hlsInstance.audioTrack = hindiIdx;
          selectors.forEach(sel => sel.value = hindiIdx);
        }
      }
    }

    function onAudioChange(val) {
      if (hlsInstance) {
        hlsInstance.audioTrack = parseInt(val, 10);
        const selectors = [document.getElementById('audioSelect'), document.getElementById('audioSelect2')].filter(Boolean);
        selectors.forEach(sel => sel.value = val);
      }
    }

    function onQualityChange(val) {
      const idx = parseInt(val, 10);
      if (!isNaN(idx)) playSource(idx);
    }

    function onCaptionChange(val) {
      const idx = parseInt(val, 10);
      captionSelect.value = idx;
      captionSelect2.value = idx;
      setTrackMode(idx);
    }

    function setTrackMode(activeIdx) {
      const textTracks = video.textTracks;
      for (let i = 0; i < textTracks.length; i++) {
        textTracks[i].mode = (i === activeIdx) ? 'showing' : 'disabled';
      }
    }

    function downloadActiveSubtitle() {
      const idx = parseInt(captionSelect.value, 10);
      if (idx === -1 || !currentTracks[idx]) {
        alert("Please select a subtitle track from the dropdown first.");
        return;
      }
      const sub = currentTracks[idx];
      window.location.href = sub.download_src || sub.src;
    }

    function openInVlc() {
      const srcObj = currentSources[currentSourceIdx] || currentSources[0];
      if (!srcObj) return;
      window.location.href = `vlc://${srcObj.src}`;
    }

    function updateLinkInputs() {
      const host = window.location.origin;
      const directUrl = (currentMode === 'tv')
        ? `${host}/stream/tv/${currentMediaId}/${currentSeason}/${currentEpisode}`
        : `${host}/stream/${currentMediaId}`;
      const embedUrl = (currentMode === 'tv')
        ? `${host}/embed/tv/${currentMediaId}/${currentSeason}/${currentEpisode}`
        : `${host}/embed/movie/${currentMediaId}`;
      const iframeCode = `<iframe src="${embedUrl}" width="100%" height="100%" frameborder="0" allowfullscreen allow="autoplay; encrypted-media; fullscreen; picture-in-picture"></iframe>`;

      document.getElementById('directStreamUrlInput').value = directUrl;
      document.getElementById('iframeCodeInput').value = iframeCode;
    }

    function copyDirectStreamUrl() {
      const el = document.getElementById('directStreamUrlInput');
      el.select();
      navigator.clipboard.writeText(el.value).then(() => alert("Direct Stream URL copied!"));
    }

    function copyIframeCode() {
      const el = document.getElementById('iframeCodeInput');
      el.select();
      navigator.clipboard.writeText(el.value).then(() => alert("Iframe embed code copied!"));
    }

    function updateEmbedSnippet(videoSrc, tracks) {
      let snippet = `<video id="my-video" class="video-js vjs-big-play-centered" controls preload="auto" width="640" height="360" crossorigin="anonymous">\n`;
      snippet += `  <source src="${videoSrc}" type="video/mp4" />\n`;
      tracks.forEach(t => {
        snippet += `  <track kind="subtitles" src="${t.src}" srclang="${t.srclang}" label="${t.label}" ${t.default ? 'default' : ''} />\n`;
      });
      snippet += `</video>\n<script src="https://vjs.zencdn.net/8.10.0/video.min.js"><\/script>`;
      document.getElementById('embedCode').textContent = snippet;
    }

    function showError(msg) {
      errorBox.textContent = msg;
      errorBox.style.display = 'block';
      showBuffering(false);
    }

    window.addEventListener('DOMContentLoaded', () => {
      document.getElementById('mediaIdInput').value = currentMediaId;
      if (currentMode === 'tv') {
        document.getElementById('seasonInput').value = currentSeason;
        document.getElementById('episodeInput').value = currentEpisode;
        setMode('tv');
      } else {
        setMode('movie');
      }
      loadStreams();
    });
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.get("/watch", response_class=HTMLResponse)
@app.get("/watch/{movie_id}", response_class=HTMLResponse)
@app.get("/watch/{movie_id}/{lang}", response_class=HTMLResponse)
@app.get("/watch/movie/{movie_id}", response_class=HTMLResponse)
@app.get("/watch/movie/{movie_id}/{lang}", response_class=HTMLResponse)
@app.get("/player", response_class=HTMLResponse)
@app.get("/player/{movie_id}", response_class=HTMLResponse)
@app.get("/player/{movie_id}/{lang}", response_class=HTMLResponse)
async def watch_movie_player(request: Request, movie_id: str = None, id: str = None, lang: str = None):
    if movie_id == "movie" and lang:
        target_id = lang
        target_lang = request.query_params.get("lang") or ""
    else:
        target_id = movie_id or id or request.query_params.get("id") or "1148365"
        target_lang = lang or request.query_params.get("lang") or ""
    html = PLAYER_HTML_TEMPLATE.replace("__MEDIA_TYPE__", "movie")\
                               .replace("__TARGET_ID__", target_id)\
                               .replace("__TARGET_SEASON__", "1")\
                               .replace("__TARGET_EPISODE__", "1")\
                               .replace("__TARGET_LANG__", target_lang)
    return HTMLResponse(content=html)

@app.get("/watch/tv/{tv_id}/{season}/{episode}", response_class=HTMLResponse)
@app.get("/watch/tv/{tv_id}/{season}/{episode}/{lang}", response_class=HTMLResponse)
@app.get("/player/tv/{tv_id}/{season}/{episode}", response_class=HTMLResponse)
@app.get("/player/tv/{tv_id}/{season}/{episode}/{lang}", response_class=HTMLResponse)
async def watch_tv_player(request: Request, tv_id: str, season: int, episode: int, lang: str = None):
    target_lang = lang or request.query_params.get("lang") or ""
    html = PLAYER_HTML_TEMPLATE.replace("__MEDIA_TYPE__", "tv")\
                               .replace("__TARGET_ID__", tv_id)\
                               .replace("__TARGET_SEASON__", str(season))\
                               .replace("__TARGET_EPISODE__", str(episode))                               .replace("__TARGET_LANG__", target_lang)
    return HTMLResponse(content=html)

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"[SERVER START] Running on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, proxy_headers=True, forwarded_allow_ips="*")
