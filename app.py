import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus
from functools import lru_cache

app = Flask(__name__)
CORS(app)

# --- Configuration & Global Variables ---
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_API_BASE = "https://api.themoviedb.org/3"
STREAMING_API_URL = "https://consumet-api-movies-nine.vercel.app"
API_PROVIDERS = ['flixhq', 'goku', 'dramacool']
MANUAL_SOURCE_API = "https://wellplayer-admin.vercel.app/api/get"

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TMDB data from {url}: {e}")
        return None

# --- Source Functions ---

## --- YOUR PERSONAL DATABASE (HIGHEST PRIORITY) --- ##
def get_manual_links_from_db(tmdb_id=None, imdb_id=None):
    if not MANUAL_SOURCE_API: return []
    try:
        # Build the query based on which ID is available
        if tmdb_id:
            api_url = f"{MANUAL_SOURCE_API}?tmdb_id={tmdb_id}"
        elif imdb_id:
            api_url = f"{MANUAL_SOURCE_API}?imdb_id={imdb_id}"
        else:
            return [] # No ID to search with
            
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data.get('links', []))} manual links.")
            return data.get('links', [])
    except Exception as e:
        print(f"Error fetching from manual DB: {e}")
    return []

def get_stream_links_from_api(tmdb_id, media_type, season=None, episode=None):
    all_links = []
    media_id_str = f"tv/{tmdb_id}" if media_type == 'tv' else f"movie/{tmdb_id}"
    for provider in API_PROVIDERS:
        try:
            print(f"Trying API provider: {provider}")
            info_url = f"{STREAMING_API_URL}/movies/{provider}/info?id={media_id_str}"
            info_res = requests.get(info_url, timeout=20)
            if info_res.status_code != 200: continue
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
            if not episode_id: continue
            watch_url = f"{STREAMING_API_URL}/movies/{provider}/watch?episodeId={episode_id}&mediaId={media_id_str}"
            watch_res = requests.get(watch_url, timeout=20)
            if watch_res.status_code != 200: continue
            watch_data = watch_res.json()
            for source in watch_data.get('sources', []):
                quality = source.get('quality', 'auto')
                all_links.append({"url": source['url'], "source": f"{provider.title()} ({quality})", "lang": "Original"})
            if all_links:
                print(f"Found links from API provider: {provider}")
                break
        except Exception as e:
            print(f"Error with API provider {provider}: {e}")
            continue
    return all_links

def get_fallback_links(id_value, id_type, media_type, season=None, episode=None):
    links = []
    try:
        if id_type == 'imdb':
            url = f"https://vidsrc.to/embed/{media_type}/{id_value}"
            if media_type == 'tv': url += f"/{season}/{episode}"
            links.append({"url": url, "source": "VidSrc.to", "lang": "Backup"})
    except Exception as e:
        print(f"Error with VidSrc.to fallback: {e}")
    try:
        if id_type == 'imdb':
            url = f"https://www.2embed.cc/embed/{media_type}/{id_value}"
            if media_type == 'tv': url += f"&s={season}&e={episode}"
            links.append({"url": url, "source": "2Embed", "lang": "Backup"})
    except Exception as e:
        print(f"Error with 2Embed fallback: {e}")
    return links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (Definitive Final) is running!"

@app.route('/search')
def search():
    query = request.args.get('query')
    if not query: return jsonify({"error": "A 'query' parameter is required."}), 400
    if not TMDB_API_KEY: return jsonify({"error": "TMDB_API_KEY is not configured."}), 500
    search_url = f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(query)}"
    data = get_tmdb_data(search_url)
    if not data or not data.get("results"): return jsonify({"error": f"Could not find '{query}'."}), 404
    results = [
        {"id": item.get("id"), "type": item.get("media_type"), "title": item.get("title") or item.get("name"), "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4], "poster_path": item.get("poster_path")}
        for item in data["results"] if item.get("media_type") in ["movie", "tv"]
    ]
    return jsonify(results)

@app.route('/movie/<int:tmdb_id>')
def get_movie_details(tmdb_id):
    all_links = []
    ids_data = get_tmdb_data(f"{TMDB_API_BASE}/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
    imdb_id = ids_data.get("imdb_id") if ids_data else None

    # Layer 1: Your Personal Manual Database
    all_links.extend(get_manual_links_from_db(tmdb_id=tmdb_id, imdb_id=imdb_id))
    
    # If no manual links, try automated sources
    if not all_links:
        print("No manual links found, proceeding to automated sources...")
        all_links.extend(get_stream_links_from_api(tmdb_id, 'movie'))
        if not all_links:
            print("API failed for movie, trying fallbacks...")
            if imdb_id:
                all_links.extend(get_fallback_links(imdb_id, 'imdb', 'movie'))

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
    return jsonify({"links": list({link['url']: link for link in all_links}.values())})

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    details_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}")
    if not details_data: return jsonify({"error": "TV show not found."}), 404
    seasons = [
        {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")}
        for s in details_data.get('seasons', []) if s.get('season_number', 0) > 0
    ]
    return jsonify({"title": details_data.get("name"), "seasons": seasons})

@app.route('/episodes')
def get_episodes():
    tmdb_id, season_num = request.args.get('tmdb_id'), request.args.get('season')
    if not tmdb_id or not season_num: return jsonify({"error": "tmdb_id and season are required."}), 400
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
    
    all_links = get_stream_links_from_api(tmdb_id, 'tv', season_num, ep_num)
    
    if not all_links:
        print(f"API failed for S{season_num}E{ep_num}, trying fallbacks...")
        ids_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
        imdb_id = ids_data.get("imdb_id") if ids_data else None
        if imdb_id:
            all_links.extend(get_fallback_links(imdb_id, 'imdb', 'tv', season_num, ep_num))

    if not all_links:
        return jsonify({"error": f"No sources found for Episode {ep_num}."}), 404
    
    return jsonify({"links": list({link['url']: link for link in all_links}.values())})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
