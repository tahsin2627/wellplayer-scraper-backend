import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin
from functools import lru_cache

app = Flask(__name__)
CORS(app)

# --- Configuration & Global Variables ---
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_API_BASE = "https://api.themoviedb.org/3"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/'
}

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    """A cached function to fetch data from TMDB."""
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TMDB data from {url}: {e}")
        return None

def parse_query_for_language(query):
    """Parses a query to find a base title."""
    language_keywords = ['hindi', 'tamil', 'telugu', 'malayalam', 'kannada', 'bengali', 'dubbed', 'dual audio']
    
    base_query_parts = [part for part in query.split() if part.lower() not in language_keywords]
    base_query = " ".join(base_query_parts)

    if not base_query:
        base_query = query
        
    return base_query, query

# --- Link Provider & Scraper Functions ---
def get_vidsrc_links(imdb_id, media_type, season=None, episode=None):
    """Source 1 & 2: vidsrc.to and vidsrc.me (Original Language)"""
    links = []
    try:
        if media_type == 'movie':
            links.append({"url": f"https://vidsrc.to/embed/movie/{imdb_id}", "source": "VidSrc.to", "lang": "Original"})
            links.append({"url": f"https://vidsrc.me/embed/movie?imdb={imdb_id}", "source": "VidSrc.me", "lang": "Original"})
        elif media_type == 'tv':
            s = season or '1'
            e = episode or '1'
            links.append({"url": f"https://vidsrc.to/embed/tv/{imdb_id}/{s}-{e}", "source": "VidSrc.to", "lang": "Original"})
            links.append({"url": f"https://vidsrc.me/embed/tv?imdb={imdb_id}&season={s}&episode={e}", "source": "VidSrc.me", "lang": "Original"})
    except Exception as e:
        print(f"Error getting vidsrc links: {e}")
    return links

def get_2embed_link(imdb_id, media_type, season=None, episode=None):
    """Source 3: 2embed.cc (Original Language)"""
    links = []
    try:
        url = None
        if media_type == 'movie':
            url = f"https://2embed.cc/embed/{imdb_id}"
        elif media_type == 'tv':
            s = season or '1'
            e = episode or '1'
            url = f"https://2embed.cc/embed/tv?imdb={imdb_id}&s={s}&e={e}"
        if url:
            links.append({"url": url, "source": "2Embed", "lang": "Original"})
    except Exception as e:
        print(f"Error getting 2embed link: {e}")
    return links

def scrape_vidsrc_pro(tmdb_id, media_type, season=None, episode=None):
    """Advanced scraper for sources like VidSrc.Pro."""
    found_links = []
    try:
        base_url = "https://vidsrc.pro/embed"
        if media_type == 'movie':
            embed_url = f"{base_url}/movie/{tmdb_id}"
        elif media_type == 'tv':
            embed_url = f"{base_url}/tv/{tmdb_id}/{season}-{episode}"
        else:
            return []

        response = requests.get(embed_url, headers=HEADERS)
        if response.status_code != 200: return []
        
        soup = BeautifulSoup(response.text, 'lxml')
        server_tabs = soup.find_all('div', class_='server')
        for tab in server_tabs:
            server_name = tab.text.strip()
            data_hash = tab.get('data-hash')
            if not data_hash: continue

            api_url = f"https://vidsrc.pro/rcp/{data_hash}"
            api_headers = HEADERS.copy()
            api_headers['Referer'] = embed_url
            
            source_response = requests.get(api_url, headers=api_headers)
            if source_response.status_code != 200: continue
            
            source_data = source_response.json()
            iframe_url = source_data.get('result', {}).get('url')

            if iframe_url:
                final_url = urljoin("https:", iframe_url)
                lang = "Dubbed" if "dub" in server_name.lower() or "hindi" in server_name.lower() else "Original"
                found_links.append({"url": final_url, "source": server_name, "lang": lang})
    except Exception as e:
        print(f"Error in scrape_vidsrc_pro: {e}")
    return found_links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend v7 (Robust) is running!"

@app.route('/search')
def search():
    """Step 1: Search for media. Returns a list of potential matches."""
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured."}), 500

    base_query, _ = parse_query_for_language(query)
    search_url = f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(base_query)}"
    data = get_tmdb_data(search_url)
    
    if not data or not data.get("results"):
        return jsonify({"error": f"Could not find '{query}'."}), 404
        
    results = []
    for item in data["results"]:
        media_type = item.get("media_type")
        if media_type in ["movie", "tv"]:
            results.append({
                "id": item.get("id"),
                "type": media_type,
                "title": item.get("title") or item.get("name"),
                "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4],
                "poster_path": item.get("poster_path")
            })
    return jsonify(results)

@app.route('/movie/<int:tmdb_id>')
def get_movie_details(tmdb_id):
    """Step 2 (Movies): Gets links from ALL available sources."""
    all_links = []
    
    # Get IMDb ID for the simple scrapers
    details_url = f"{TMDB_API_BASE}/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
    ids_data = get_tmdb_data(details_url)
    imdb_id = ids_data.get("imdb_id") if ids_data else None

    # --- Run all sources ---
    if imdb_id:
        all_links.extend(get_vidsrc_links(imdb_id, 'movie'))
        all_links.extend(get_2embed_link(imdb_id, 'movie'))
    
    # Also run the advanced scraper
    all_links.extend(scrape_vidsrc_pro(tmdb_id, 'movie'))

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
            
    # De-duplicate results
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    """Step 2 (TV): Get season info for a specific TV show."""
    details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
    details_data = get_tmdb_data(details_url)
    
    if not details_data: return jsonify({"error": "TV show not found."}), 404
    
    seasons = details_data.get('seasons', [])
    season_list = [
        {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")} 
        for s in seasons if s.get('season_number', 0) > 0
    ]
    return jsonify({"title": details_data.get("name"), "seasons": season_list})

@app.route('/episodes')
def get_episodes():
    """Step 3 (TV): Get episode links for a specific season from all sources."""
    tmdb_id = request.args.get('tmdb_id')
    season_num = request.args.get('season')

    if not tmdb_id or not season_num:
        return jsonify({"error": "tmdb_id and season are required."}), 400

    # Get IMDb ID for simple scrapers
    external_ids_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
    ids_data = get_tmdb_data(external_ids_url)
    imdb_id = ids_data.get("imdb_id") if ids_data else None

    # Get episode list from TMDB
    season_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    season_data = get_tmdb_data(season_details_url)
    if not season_data or not season_data.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
        
    episode_links_list = []
    for episode in season_data.get('episodes', []):
        ep_num = episode.get('episode_number')
        all_links_for_ep = []

        # Get links from all sources for this specific episode
        if imdb_id:
            all_links_for_ep.extend(get_vidsrc_links(imdb_id, 'tv', season_num, ep_num))
            all_links_for_ep.extend(get_2embed_link(imdb_id, 'tv', season_num, ep_num))
        
        all_links_for_ep.extend(scrape_vidsrc_pro(tmdb_id, 'tv', season_num, ep_num))
        
        episode_links_list.append({
            "episode": ep_num,
            "title": episode.get('name', f"Episode {ep_num}"),
            "links": list({link['url']: link for link in all_links_for_ep}.values()) # De-duplicate
        })

    return jsonify({"season": season_num, "episodes": episode_links_list})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
