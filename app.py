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
# This public API aggregates links from multiple providers below
# NEW: Added 'dramacool' which is excellent for Asian and Indian content.
API_PROVIDERS = ['flixhq', 'goku', 'dramacool']

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

# --- NEW API-based Link Fetcher ---
def get_stream_links_from_api(tmdb_id, media_type, season=None, episode=None):
    all_links = []
    # For TV shows, the API needs the specific TMDB ID. For movies, it can be movie/tmdb_id
    media_id_str = f"tv/{tmdb_id}" if media_type == 'tv' else f"movie/{tmdb_id}"

    for provider in API_PROVIDERS:
        try:
            print(f"Trying provider: {provider}")
            # Step A: Get info which contains the all-important internal ID
            info_url = f"{STREAMING_API_URL}/movies/{provider}/info?id={media_id_str}"
            info_res = requests.get(info_url, timeout=20)
            if info_res.status_code != 200: continue
            info_data = info_res.json()

            episode_id = None
            if media_type == 'movie':
                # The episodeId for a movie is often its own TMDB ID or a specific ID from the provider
                episode_id = info_data.get('id')
            else: # tv
                target_season = next((s for s in info_data.get('episodes', []) if str(s.get('season')) == str(season)), None)
                if target_season:
                    target_episode = next((e for e in target_season.get('episodes', []) if str(e.get('number')) == str(episode)), None)
                    if target_episode:
                        episode_id = target_episode.get('id')
            
            if not episode_id: continue

            # Step B: Get the actual streaming sources using the episode ID
            watch_url = f"{STREAMING_API_URL}/movies/{provider}/watch?episodeId={episode_id}&mediaId={media_id_str}"
            watch_res = requests.get(watch_url, timeout=20)
            if watch_res.status_code != 200: continue
            watch_data = watch_res.json()
            
            # Step C: Format the links for the frontend
            for source in watch_data.get('sources', []):
                quality = source.get('quality', 'auto')
                # Add the provider name to the source for clarity
                all_links.append({
                    "url": source['url'],
                    "source": f"{provider.title()} - {quality}",
                    "lang": "Original"
                })
            
            # If we found links from the first provider, we can stop and return them for speed.
            if all_links:
                print(f"Found links from provider: {provider}")
                break
        except Exception as e:
            print(f"Error with provider {provider}: {e}")
            continue # Try the next provider
            
    return all_links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (Stable API + Indian Content) is running!"

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
    all_links = get_stream_links_from_api(tmdb_id, 'movie')
    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
    return jsonify({"links": list({link['url']: link for link in all_links}.values())})

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    try:
        details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
        details_data = get_tmdb_data(details_url)
        if not details_data: return jsonify({"error": "TV show not found."}), 404
        
        seasons = [
            {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")}
            for s in details_data.get('seasons', []) if s.get('season_number', 0) > 0
        ]
        return jsonify({"title": details_data.get("name"), "seasons": seasons})
    except Exception as e:
        print(f"Error fetching TV details: {e}")
        return jsonify({"error": "Failed to fetch TV show details."}), 500

@app.route('/episodes')
def get_episodes():
    tmdb_id, season_num = request.args.get('tmdb_id'), request.args.get('season')
    if not tmdb_id or not season_num: return jsonify({"error": "tmdb_id and season are required."}), 400

    season_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    season_data = get_tmdb_data(season_details_url)
    if not season_data or not season_data.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
        
    episode_links_list = []
    for episode in season_data.get('episodes', []):
        ep_num = episode.get('episode_number')
        all_links_for_ep = get_stream_links_from_api(tmdb_id, 'tv', season_num, ep_num)
        
        episode_links_list.append({
            "episode": ep_num,
            "title": episode.get('name', f"Episode {ep_num}"),
            "links": list({link['url']: link for link in all_links_for_ep}.values())
        })

    return jsonify({"season": season_num, "episodes": episode_links_list})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

