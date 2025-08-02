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
MANUAL_SOURCE_API = "https://wellplayer-admin.vercel.app/api/get" # This remains the same

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

def get_manual_links_from_db(tmdb_id=None, imdb_id=None, query=None):
    if not MANUAL_SOURCE_API: return []
    try:
        params = {}
        if tmdb_id:
            params['tmdb_id'] = tmdb_id
        elif imdb_id:
            params['imdb_id'] = imdb_id
        elif query:
            params['query'] = query
        else:
            return []
            
        response = requests.get(MANUAL_SOURCE_API, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"Found {len(data.get('results', []))} manual items.")
            return data.get('results', [])
    except Exception as e:
        print(f"Error fetching from manual DB: {e}")
    return []

# --- All other source functions (API, Fallbacks) are unchanged ---
def get_stream_links_from_api(tmdb_id, media_type, season=None, episode=None):
    # ... (This function is unchanged)
    all_links = []
    # ...
    return all_links

def get_fallback_links(id_value, id_type, media_type, season=None, episode=None):
    # ... (This function is unchanged)
    links = []
    # ...
    return links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (Final Integrated Search) is running!"

@app.route('/search')
def search():
    query = request.args.get('query')
    if not query: return jsonify({"error": "A 'query' parameter is required."}), 400
    if not TMDB_API_KEY: return jsonify({"error": "TMDB_API_KEY is not configured."}), 500
    
    # --- UPGRADED SEARCH LOGIC ---
    all_results = []
    
    # 1. Search TMDB
    tmdb_search_url = f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(query)}"
    tmdb_data = get_tmdb_data(tmdb_search_url)
    if tmdb_data and tmdb_data.get("results"):
        tmdb_results = [
            {"id": item.get("id"), "type": item.get("media_type"), "title": item.get("title") or item.get("name"), "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4], "poster_path": item.get("poster_path")}
            for item in tmdb_data["results"] if item.get("media_type") in ["movie", "tv"]
        ]
        all_results.extend(tmdb_results)

    # 2. Search your personal database
    manual_results = get_manual_links_from_db(query=query)
    if manual_results:
        # Format the manual results to match the TMDB structure
        formatted_manual_results = [
            {"id": item.get("tmdb_id") or item.get("imdb_id"), "type": "movie", "title": item.get("title"), "year": item.get("title", "")[-5:-1], "poster_path": None}
            for item in manual_results
        ]
        all_results.extend(formatted_manual_results)

    if not all_results:
        return jsonify({"error": f"Could not find '{query}'."}), 404
    
    # De-duplicate results, giving preference to TMDB results if IDs match
    final_results = {str(res.get('id')): res for res in all_results}

    return jsonify(list(final_results.values()))

@app.route('/movie/<string:media_id>') # Changed to string to accept both tmdb and imdb IDs
def get_movie_details(media_id):
    all_links = []
    
    # Determine if the ID is for TMDB or IMDb
    if media_id.startswith('tt'):
        imdb_id = media_id
        tmdb_id = None # We don't have the TMDB ID for IMDb-only entries
    else:
        tmdb_id = int(media_id)
        ids_data = get_tmdb_data(f"{TMDB_API_BASE}/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
        imdb_id = ids_data.get("imdb_id") if ids_data else None

    # Layer 1: Your Personal Manual Database (Highest Priority)
    all_links.extend(get_manual_links_from_db(tmdb_id=tmdb_id, imdb_id=imdb_id))
    
    # If no manual links, try automated sources (only works if we have a tmdb_id)
    if not all_links and tmdb_id:
        print("No manual links found, proceeding to automated sources...")
        all_links.extend(get_stream_links_from_api(tmdb_id, 'movie'))
        if not all_links:
            print("API failed for movie, trying fallbacks...")
            if imdb_id:
                all_links.extend(get_fallback_links(imdb_id, 'imdb', 'movie'))

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
    return jsonify({"links": list({link['url']: link for link in all_links}.values())})

# ... All other endpoints (/tv, /episodes, /episode-links) are unchanged ...

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    # This endpoint is unchanged
    details_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}")
    if not details_data: return jsonify({"error": "TV show not found."}), 404
    seasons = [
        {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")}
        for s in details_data.get('seasons', []) if s.get('season_number', 0) > 0
    ]
    return jsonify({"title": details_data.get("name"), "seasons": seasons})

@app.route('/episodes')
def get_episodes():
    # This endpoint is unchanged
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
    # This endpoint is unchanged
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
