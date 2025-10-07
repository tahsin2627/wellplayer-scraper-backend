import os
import re
import time
from functools import lru_cache
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ------------------------------
# Configuration & Global Variables
# ------------------------------
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_API_BASE = "https://api.themoviedb.org/3"

# Optional third-party API fallback (kept from your original)
STREAMING_API_URL = "https://consumet-api-movies-nine.vercel.app"
API_PROVIDERS = ['flixhq', 'goku', 'dramacool']

# Provider registry and order
PROVIDER_ORDER = ["hdhub4u", "cinefreak", "dongobd", "netmirror"]

PROVIDERS = {
    "hdhub4u": {
        "label": "HDHub4u",
        "bases": ["https://hdhub4u.cologne"],
    },
    "cinefreak": {
        "label": "CineFreak",
        "bases": ["https://www.cinefreak.net", "https://cinefreak.net"],
    },
    "dongobd": {
        "label": "DongoBD",
        "bases": ["https://dongobd.com"],
    },
    "netmirror": {
        "label": "NetMirror",
        "bases": ["https://netmirror.bio"],
    },
}

# Only collect embeds/links from these hostnames (expand as partners approve)
ALLOWED_EMBED_HOSTS = {
    "hdstream4u.com",
    "neodrive.xyz",
    "netmirror.bio",
    "p2pplay.pro",
    "ottbangla.p2pplay.pro",
}

# Mirror cache: {provider: (url, expires_at)}
MIRROR_CACHE = {}

# Request defaults
REQ_TIMEOUT = 12
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WellPlayerFetcher/1.0; +https://example.com)"
}

# Languages day-1
LANG_CODES = ["hi", "en", "bn", "ta", "te", "ml", "kn", "mr", "ur"]
LANG_LABELS = {
    "hi": "Hindi",
    "en": "English",
    "bn": "Bangla",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "kn": "Kannada",
    "mr": "Marathi",
    "ur": "Urdu",
}

# ------------------------------
# TMDB helpers
# ------------------------------
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    try:
        response = requests.get(url, timeout=REQ_TIMEOUT, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TMDB data from {url}: {e}")
        return None

def get_tmdb_title_year(tmdb_id, media_type):
    if not TMDB_API_KEY:
        return None, None
    if media_type == "movie":
        data = get_tmdb_data(f"{TMDB_API_BASE}/movie/{tmdb_id}?api_key={TMDB_API_KEY}&language=en-US")
        if not data:
            return None, None
        title = data.get("title") or data.get("original_title") or ""
        year = (data.get("release_date") or "")[:4]
        return title.strip(), year.strip()
    else:
        data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}&language=en-US")
        if not data:
            return None, None
        title = data.get("name") or data.get("original_name") or ""
        year = (data.get("first_air_date") or "")[:4]
        return title.strip(), year.strip()

# ------------------------------
# Normalization & heuristics
# ------------------------------
STOP_WORDS = {
    "full", "movie", "watch", "online", "download", "webrip", "web-dl", "webdl", "hdrip",
    "bluray", "brrip", "hdtc", "hdcam", "cam", "predvd", "prehd", "uncut", "extended",
    "esub", "gdrive", "x264", "x265", "hevc", "720p", "1080p", "480p", "2160p", "uhd",
    "4k", "multiaudio", "multi", "dual", "audio", "org", "official", "rip", "print"
}

RELEASE_TYPES = [
    "HDCAM", "CAM", "HDTC", "TS", "TC", "PreDVD", "PreHD", "WEBRip", "WEB-DL", "HDRip", "BluRay", "DVDRip", "BRRip"
]

LANG_PATTERNS = {
    "hi": r"(hindi|हिंदी|हिन्दी|\bhin\b)",
    "en": r"(english|\beng\b)",
    "bn": r"(bangla|bengali|বাংলা|\bbn\b)",
    "ta": r"(tamil|தமிழ்|\btam\b)",
    "te": r"(telugu|తెలుగు|\btel\b)",
    "ml": r"(malayalam|മലയാളം|\bmal\b)",
    "kn": r"(kannada|ಕನ್ನಡ|\bkan\b)",
    "mr": r"(marathi|मराठी|\bmar\b)",
    "ur": r"(urdu|اردو|\burd\b)",
}
DUAL_PATTERNS = r"(dual\s*audio|hin\s*[-+\/]\s*eng|hi\s*[-+\/]\s*en|en\s*[-+\/]\s*hi)"
MULTI_PATTERNS = r"(multi\s*audio|multiaudio|multi\b)"

def normalize_text(s: str) -> str:
    s = s.lower()
    # Replace punctuation with space, keep letters/numbers/underscore + whitespace
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize_title(s: str):
    s = normalize_text(s)
    tokens = [t for t in s.split() if t not in STOP_WORDS and len(t) > 1]
    return set(tokens)

def score_title(candidate_text: str, wanted_title: str, year: str = "", lang_codes=None):
    if lang_codes is None:
        lang_codes = []
    cand_tokens = tokenize_title(candidate_text)
    want_tokens = tokenize_title(wanted_title)
    if not cand_tokens or not want_tokens:
        return 0.0
    jaccard = len(cand_tokens & want_tokens) / max(1, len(cand_tokens | want_tokens))
    score = jaccard

    # Year boost/penalty
    cand_lower = candidate_text.lower()
    if year and year in cand_lower:
        score += 0.2
    elif year and re.search(r"\b\d{4}\b", cand_lower):
        score += 0.05

    # Language boost
    for code in lang_codes:
        pat = LANG_PATTERNS.get(code)
        if pat and re.search(pat, cand_lower):
            score += 0.25
    if re.search(DUAL_PATTERNS, cand_lower):
        score += 0.2
    if re.search(MULTI_PATTERNS, cand_lower):
        score += 0.15

    return min(score, 1.0)

def detect_release_type(text: str):
    t = text.upper()
    for rt in RELEASE_TYPES:
        if rt in t:
            return rt
    return None

def detect_quality(text: str):
    t = text.lower()
    if "2160p" in t or "4k" in t or "uhd" in t:
        return "2160p"
    if "1080p" in t:
        return "1080p"
    if "720p" in t:
        return "720p"
    if "480p" in t:
        return "480p"
    return "auto"

def detect_audio_lang(text: str):
    t = text.lower()
    if re.search(DUAL_PATTERNS, t):
        return "dual", "Dual (Hi+En)"
    if re.search(MULTI_PATTERNS, t):
        return "multi", "Multi Audio"
    for code, pat in LANG_PATTERNS.items():
        if re.search(pat, t):
            return code, f"{LANG_LABELS.get(code, code)}"
    return "original", "Original"

def domain_of(url: str):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def is_allowed_embed(url: str):
    host = domain_of(url)
    return any(host == h or host.endswith("." + h) for h in ALLOWED_EMBED_HOSTS)

# ------------------------------
# Mirror resolution and HTTP helpers
# ------------------------------
def resolve_mirror(provider: str):
    now = time.time()
    cached = MIRROR_CACHE.get(provider)
    if cached and cached[1] > now:
        return cached[0]

    bases = PROVIDERS.get(provider, {}).get("bases", [])
    for base in bases:
        try:
            r = requests.get(base, timeout=REQ_TIMEOUT, headers=DEFAULT_HEADERS, allow_redirects=True)
            if r.status_code in (200, 301, 302):
                MIRROR_CACHE[provider] = (base.rstrip("/"), now + 1800)  # 30 min
                return base.rstrip("/")
        except Exception:
            continue
    if bases:
        MIRROR_CACHE[provider] = (bases[0].rstrip("/"), now + 600)
        return bases[0].rstrip("/")
    return None

def http_get(url: str):
    try:
        r = requests.get(url, timeout=REQ_TIMEOUT, headers=DEFAULT_HEADERS)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"GET error {url}: {e}")
    return None

# ------------------------------
# Generic search/extract helpers
# ------------------------------
def build_query_variants(title: str, year: str, lang_codes, want_dubbed: bool):
    q = []
    base = f"{title} {year}".strip()
    q.append(base)
    q.append(title)
    if want_dubbed and lang_codes:
        for code in lang_codes:
            lname = LANG_LABELS.get(code, code)
            q.append(f"{title} {lname} Dubbed")
            q.append(f"{title} {year} {lname} Dubbed")
        q.append(f"{title} Dual Audio")
        q.append(f"{title} Multi Audio")
    else:
        q.append(f"{title} Dual Audio")
        q.append(f"{title} Multi Audio")
    seen = set()
    res = []
    for s in q:
        s2 = " ".join(s.split())
        if s2 not in seen:
            seen.add(s2)
            res.append(s2)
    return res

def parse_search_results(html: str, base: str):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    selectors = [
        "article h2 a", "h2.entry-title a", "h3.entry-title a",
        ".post-title a", ".entry-title a", ".post h2 a", ".grid-item a",
        "a[href]"
    ]
    seen = set()
    for sel in selectors:
        for a in soup.select(sel):
            href = a.get("href")
            text = (a.get_text(" ", strip=True) or "").strip()
            if not href or not text:
                continue
            if href in seen:
                continue
            seen.add(href)
            candidates.append({"title": text, "url": href})
        if candidates:
            break
    uniq = []
    seenu = set()
    for c in candidates:
        if c["url"] not in seenu:
            uniq.append(c)
            seenu.add(c["url"])
    return uniq[:20]

def extract_embeds_from_page(page_url: str, provider_label: str):
    html = http_get(page_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    page_text_for_detect = " ".join([
        soup.title.get_text(" ", strip=True) if soup.title else "",
        soup.get_text(" ", strip=True)[:5000],
    ])
    release_type = detect_release_type(page_text_for_detect)
    quality = detect_quality(page_text_for_detect)
    audio_code, audio_label = detect_audio_lang(page_text_for_detect)

    links = []

    # iframes
    for iframe in soup.select("iframe[src]"):
        src = iframe.get("src", "").strip()
        if not src:
            continue
        url_abs = urljoin(page_url, src)
        if is_allowed_embed(url_abs):
            host = domain_of(url_abs).split(":")[0]
            links.append({
                "url": url_abs,
                "source": f"{provider_label} ({host})",
                "type": "embed",
                "quality": quality,
                "release_type": release_type,
                "audio_lang": audio_code,
                "audio_label": audio_label,
                "subtitles": [],
                "headers": {},
                "openInNewTab": False,
                "note": None,
                "lang": audio_label or "Original",
            })

    # anchors (buttons/links) pointing to allowed hosts
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if not href:
            continue
        url_abs = urljoin(page_url, href)
        if is_allowed_embed(url_abs):
            host = domain_of(url_abs).split(":")[0]
            q2 = detect_quality(a.get_text(" ", strip=True) or "")
            q_use = q2 if q2 != "auto" else quality
            links.append({
                "url": url_abs,
                "source": f"{provider_label} ({host})",
                "type": "embed",
                "quality": q_use,
                "release_type": release_type,
                "audio_lang": audio_code,
                "audio_label": audio_label,
                "subtitles": [],
                "headers": {},
                "openInNewTab": False,
                "note": None,
                "lang": audio_label or "Original",
            })

    # de-dup
    uniq = []
    seen = set()
    for l in links:
        if l["url"] not in seen:
            uniq.append(l)
            seen.add(l["url"])
    return uniq

# ------------------------------
# Provider-specific fetch
# ------------------------------
def provider_search_and_extract(provider: str, tmdb_id: int, title: str, year: str, media_type: str,
                                season=None, episode=None, lang_codes=None, want_dubbed=False):
    if lang_codes is None:
        lang_codes = []

    base = resolve_mirror(provider)
    if not base:
        return []
    provider_label = PROVIDERS[provider]["label"]

    # Special case: NetMirror supports a direct embed URL for many titles
    if provider == "netmirror":
        path_type = "movie" if media_type == "movie" else "tv"
        embed_url = f"{base}/{path_type}/{tmdb_id}/?embed=1"
        html = http_get(embed_url)
        if html:
            links = extract_embeds_from_page(embed_url, provider_label)
            if links:
                return links
            # fallback: return the embed page itself
            return [{
                "url": embed_url,
                "source": f"{provider_label} (embed)",
                "type": "embed",
                "quality": "auto",
                "release_type": None,
                "audio_lang": "original",
                "audio_label": "Original",
                "subtitles": [],
                "headers": {},
                "openInNewTab": False,
                "note": None,
                "lang": "Original",
            }]

    # Generic flow for others: search → best match → extract
    queries = build_query_variants(title, year, lang_codes, want_dubbed)
    best = None
    best_score = 0.0

    for q in queries:
        search_url = f"{base}/?s={quote_plus(q)}"
        html = http_get(search_url)
        if not html:
            continue
        candidates = parse_search_results(html, base)
        for c in candidates:
            cand_text = f"{c['title']} {c['url']}"
            sc = score_title(cand_text, title, year, lang_codes)
            if sc > best_score:
                best_score = sc
                best = c
        if best and best_score >= 0.75:
            break

    if not best:
        return []

    # If NetMirror via search, try its embed variant too
    if provider == "netmirror" and best.get("url"):
        try_embed = best["url"]
        if "/movie/" in try_embed or "/tv/" in try_embed:
            if "?" in try_embed:
                try_embed = try_embed + "&embed=1"
            else:
                try_embed = try_embed + "?embed=1"
            links = extract_embeds_from_page(try_embed, provider_label)
            if links:
                return links
            page_links = extract_embeds_from_page(best["url"], provider_label)
            if page_links:
                return page_links

    # For others (HDHub4u, CineFreak, DongoBD), extract from page
    links = extract_embeds_from_page(best["url"], provider_label)
    return links

def fetch_links_from_providers(tmdb_id: int, media_type: str, season=None, episode=None,
                               lang_codes=None, want_dubbed=False, strict=False):
    if lang_codes is None:
        lang_codes = []

    title, year = get_tmdb_title_year(tmdb_id, media_type)
    if not title:
        return []

    all_links = []
    for prov in PROVIDER_ORDER:
        try:
            links = provider_search_and_extract(
                prov, tmdb_id, title, year, media_type,
                season=season, episode=episode,
                lang_codes=lang_codes, want_dubbed=want_dubbed
            )
            if strict and lang_codes:
                links = [l for l in links if (l.get("audio_lang") in lang_codes) or
                         (l.get("audio_lang") in ("dual", "multi") and any(code in LANG_CODES for code in lang_codes))]
            all_links.extend(links)
        except Exception as e:
            print(f"Provider {prov} error: {e}")
            continue

    # Soft fallback note if dubbed requested but nothing matched
    if want_dubbed and lang_codes:
        has_requested_lang = any(
            (l.get("audio_lang") in lang_codes) or (l.get("audio_lang") in ("dual", "multi"))
            for l in all_links
        )
        if not has_requested_lang and not strict:
            for l in all_links:
                if l.get("audio_lang") == "original":
                    wanted = ", ".join([LANG_LABELS.get(c, c) for c in lang_codes])
                    l["note"] = f"No {wanted} dub found — playing Original."
                    break

    # Rank: non-CAM first, then higher quality, then provider order
    def rank_key(l):
        cam_penalty = 1 if (l.get("release_type") in ("CAM", "HDCAM", "HDTC", "TS", "TC")) else 0
        q_order = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1, "auto": 0}.get(l.get("quality") or "auto", 0)
        src = l.get("source", "")
        prov_name = src.split(" (")[0] if " (" in src else src
        prov_rank = PROVIDER_ORDER.index(prov_name) if prov_name in PROVIDER_ORDER else 99
        return (cam_penalty, -q_order, prov_rank)

    all_links = sorted(all_links, key=rank_key)
    return all_links[:8]

# ------------------------------
# Existing third-party API fallback (kept)
# ------------------------------
def get_stream_links_from_api(tmdb_id, media_type, season=None, episode=None):
    all_links = []
    media_id_str = f"tv/{tmdb_id}" if media_type == 'tv' else f"movie/{tmdb_id}"
    for provider in API_PROVIDERS:
        try:
            print(f"Trying API provider: {provider}")
            info_url = f"{STREAMING_API_URL}/movies/{provider}/info?id={media_id_str}"
            info_res = requests.get(info_url, timeout=20, headers=DEFAULT_HEADERS)
            if info_res.status_code != 200:
                continue
            info_data = info_res.json()

            episode_id = None
            if media_type == 'movie':
                episode_id = info_data.get('id')
            else:
                target_season = next((s for s in info_data.get('episodes', []) if str(s.get('season')) == str(season)), None)
                if target_season:
                    target_episode = next((e for e in target_season.get('episodes', []) if str(e.get('number')) == str(episode)), None)
                    if target_episode:
                        episode_id = target_episode.get('id')

            if not episode_id:
                continue

            watch_url = f"{STREAMING_API_URL}/movies/{provider}/watch?episodeId={episode_id}&mediaId={media_id_str}"
            watch_res = requests.get(watch_url, timeout=20, headers=DEFAULT_HEADERS)
            if watch_res.status_code != 200:
                continue
            watch_data = watch_res.json()

            for source in watch_data.get('sources', []):
                quality = source.get('quality', 'auto')
                all_links.append({
                    "url": source['url'],
                    "source": f"{provider.title()} ({quality})",
                    "lang": "Original",
                    "type": "stream",
                    "quality": quality,
                    "release_type": None,
                    "audio_lang": "original",
                    "audio_label": "Original",
                    "subtitles": [],
                    "headers": {},
                    "openInNewTab": False,
                    "note": None,
                })

            if all_links:
                print(f"Found links from API provider: {provider}")
                break
        except Exception as e:
            print(f"Error with API provider {provider}: {e}")
            continue
    return all_links

# ------------------------------
# FALLBACK SOURCES (kept)
# ------------------------------
def get_fallback_links(id_value, id_type, media_type, season=None, episode=None):
    links = []
    try:
        if id_type == 'imdb':
            url = f"https://vidsrc.to/embed/{media_type}/{id_value}"
            if media_type == 'tv':
                url += f"/{season}/{episode}"
            links.append({
                "url": url, "source": "VidSrc.to", "lang": "Backup",
                "type": "embed", "quality": "auto", "release_type": None,
                "audio_lang": "original", "audio_label": "Original",
                "subtitles": [], "headers": {}, "openInNewTab": True, "note": None
            })
    except Exception as e:
        print(f"Error with VidSrc.to fallback: {e}")
    try:
        if id_type == 'imdb':
            url = f"https://www.2embed.cc/embed/{media_type}/{id_value}"
            if media_type == 'tv':
                url += f"&s={season}&e={episode}"
            links.append({
                "url": url, "source": "2Embed", "lang": "Backup",
                "type": "embed", "quality": "auto", "release_type": None,
                "audio_lang": "original", "audio_label": "Original",
                "subtitles": [], "headers": {}, "openInNewTab": True, "note": None
            })
    except Exception as e:
        print(f"Error with 2Embed fallback: {e}")
    return links

# ------------------------------
# API Endpoints
# ------------------------------
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (AI Fetcher + API + Fallbacks) is running!"

@app.route('/favicon.ico')
def favicon():
    # Avoid noisy 500s for favicon fetches
    return ("", 204)

@app.route('/search')
def search():
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured."}), 500
    search_url = f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(query)}"
    data = get_tmdb_data(search_url)
    if not data or not data.get("results"):
        return jsonify({"error": f"Could not find '{query}'."}), 404
    results = [
        {
            "id": item.get("id"),
            "type": item.get("media_type"),
            "title": item.get("title") or item.get("name"),
            "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4],
            "poster_path": item.get("poster_path")
        }
        for item in data["results"] if item.get("media_type") in ["movie", "tv"]
    ]
    return jsonify(results)

@app.route('/movie/<int:tmdb_id>')
def get_movie_details(tmdb_id):
    # Dub-aware params
    lang_param = (request.args.get("lang") or "").strip()
    lang_codes = [x.strip() for x in lang_param.split(",") if x.strip() in LANG_CODES]
    want_dubbed = request.args.get("dubbed", "0").lower() in ("1", "true", "yes")
    strict = request.args.get("strict", "0").lower() in ("1", "true", "yes")

    # Try providers first (embeds)
    provider_links = fetch_links_from_providers(
        tmdb_id, "movie",
        lang_codes=lang_codes, want_dubbed=want_dubbed, strict=strict
    )
    all_links = list(provider_links)

    # If none, try existing API providers
    if not all_links:
        print("AI Fetcher found nothing for movie; trying API providers...")
        all_links.extend(get_stream_links_from_api(tmdb_id, 'movie'))

    # If still none, try fallbacks using IMDb id
    if not all_links:
        print("API failed for movie, trying fallbacks...")
        ids_data = get_tmdb_data(f"{TMDB_API_BASE}/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
        imdb_id = ids_data.get("imdb_id") if ids_data else None
        if imdb_id:
            all_links.extend(get_fallback_links(imdb_id, 'imdb', 'movie'))

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404

    dedup = list({l["url"]: l for l in all_links}.values())
    return jsonify({"links": dedup})

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    details_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}")
    if not details_data:
        return jsonify({"error": "TV show not found."}), 404
    seasons = [
        {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")}
        for s in details_data.get('seasons', []) if s.get('season_number', 0) > 0
    ]
    return jsonify({"title": details_data.get("name"), "seasons": seasons})

@app.route('/episodes')
def get_episodes():
    tmdb_id, season_num = request.args.get('tmdb_id'), request.args.get('season')
    if not tmdb_id or not season_num:
        return jsonify({"error": "tmdb_id and season are required."}), 400
    season_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    season_data = get_tmdb_data(season_details_url)
    if not season_data or not season_data.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
    episodes_list = [{"episode": ep.get('episode_number'), "title": ep.get('name')} for ep in season_data.get('episodes', [])]
    return jsonify({"season": season_num, "episodes": episodes_list})

@app.route('/episode-links')
def get_episode_links():
    tmdb_id, season_num, ep_num = request.args.get('tmdb_id'), request.args.get('season'), request.args.get('episode')
    if not all([tmdb_id, season_num, ep_num]):
        return jsonify({"error": "tmdb_id, season, and episode are required."}), 400

    # Dub-aware params
    lang_param = (request.args.get("lang") or "").strip()
    lang_codes = [x.strip() for x in lang_param.split(",") if x.strip() in LANG_CODES]
    want_dubbed = request.args.get("dubbed", "0").lower() in ("1", "true", "yes")
    strict = request.args.get("strict", "0").lower() in ("1", "true", "yes")

    provider_links = fetch_links_from_providers(
        int(tmdb_id), "tv",
        season=season_num, episode=ep_num,
        lang_codes=lang_codes, want_dubbed=want_dubbed, strict=strict
    )
    all_links = list(provider_links)

    if not all_links:
        print(f"AI Fetcher found nothing for S{season_num}E{ep_num}; trying API providers...")
        all_links.extend(get_stream_links_from_api(tmdb_id, 'tv', season_num, ep_num))

    if not all_links:
        print(f"API failed for S{season_num}E{ep_num}, trying fallbacks...")
        ids_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
        imdb_id = ids_data.get("imdb_id") if ids_data else None
        if imdb_id:
            all_links.extend(get_fallback_links(imdb_id, 'imdb', 'tv', season_num, ep_num))

    if not all_links:
        return jsonify({"error": f"No sources found for Episode {ep_num}."}), 404

    dedup = list({l["url"]: l for l in all_links}.values())
    return jsonify({"links": dedup})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
