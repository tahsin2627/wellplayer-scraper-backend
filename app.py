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
# Common headers for making requests look more like a real browser
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

# --- ADVANCED "DEEP" SCRAPER ---
def scrape_vidsrc_pro(tmdb_id, media_type, season=None, episode=None):
    """
    An advanced scraper for sources like VidSrc.Pro.
    It finds the server list and extracts direct iframe links.
    """
    found_links = []
    try:
        # Step 1: Construct the embed URL
        base_url = "https://vidsrc.pro/embed"
        if media_type == 'movie':
            embed_url = f"{base_url}/movie/{tmdb_id}"
        elif media_type == 'tv':
            embed_url = f"{base_url}/tv/{tmdb_id}/{season}-{episode}"
        else:
            return []

        # Step 2: Get the embed page content
        response = requests.get(embed_url, headers=HEADERS)
        if response.status_code != 200: return []
        
        soup = BeautifulSoup(response.text, 'lxml')

        # Step 3: Find all server tabs
        server_tabs = soup.find_all('div', class_='server')
        for tab in server_tabs:
            server_name = tab.text.strip()
            data_hash = tab.get('data-hash')

            if not data_hash: continue

            # Step 4: Call the hidden API to get the source URL
            # The referer header is crucial for this API call to work
            api_url = f"https://vidsrc.pro/rcp/{data_hash}"
            api_headers = HEADERS.copy()
            api_headers['Referer'] = embed_url
            
            source_response = requests.get(api_url, headers=api_headers)
            if source_response.status_code != 200: continue
            
            source_data = source_response.json()
            iframe_url = source_data.get('result', {}).get('url')

            if iframe_url:
                # The final URL is often URL-encoded, so we clean it up
                final_url = urljoin("https:", iframe_url)
                
                lang = "Unknown"
                if "hindi" in server_name.lower(): lang = "Hindi"
                elif "dub" in server_name.lower(): lang = "Dubbed"
                elif server_name in ["VidSrc", "2Embed"]: lang = "Original"

                found_links.append({"url": final_url, "source": server_name, "lang": lang})

    except Exception as e:
        print(f"Error in scrape_vidsrc_pro: {e}")

    return found_links


# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend v6 is running!"

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
    """Step 2 (Movies): Get streaming links using the advanced scraper."""
    # The original_query is no longer needed here as the TMDB ID is more reliable
    all_links = scrape_vidsrc_pro(tmdb_id, 'movie')

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
            
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    """Step 2 (TV): Get season info for a specific TV show."""
    details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
    details_data = get_tmdb_data(details_url)
    
    if not details_data:
        return jsonify({"error": "TV show not found."}), 404
    
    seasons = details_data.get('seasons', [])
    season_list = [
        {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")} 
        for s in seasons if s.get('season_number', 0) > 0
    ]
    return jsonify({"title": details_data.get("name"), "seasons": season_list})

@app.route('/episodes')
def get_episodes():
    """Step 3 (TV): Get episode links for a specific season."""
    tmdb_id = request.args.get('tmdb_id')
    season_num = request.args.get('season')

    if not tmdb_id or not season_num:
        return jsonify({"error": "tmdb_id and season are required."}), 400

    # Use the new advanced scraper for episodes as well
    all_links = scrape_vidsrc_pro(tmdb_id, 'tv', season_num, '1') # Scrape for first episode to get general links
    
    # We will assume for now all episodes are on the same servers.
    # A full implementation would scrape for each episode individually.
    
    season_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    season_data = get_tmdb_data(season_details_url)
    if not season_data or not season_data.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
        
    episode_links_list = []
    for episode in season_data.get('episodes', []):
        ep_num = episode.get('episode_number')
        
        # We re-use the scraped server links for each episode, just changing the episode number in the URL
        current_episode_links = []
        for server_link in all_links:
            new_link = server_link.copy()
            # Replace the episode number in the URL (e.g., .../s1-e1 -> .../s1-e2)
            new_link['url'] = re.sub(r'e(\d+)$', f'e{ep_num}', new_link['url'])
            new_link['url'] = re.sub(r'episode=(\d+)$', f'episode={ep_num}', new_link['url'])
            current_episode_links.append(new_link)

        episode_links_list.append({
            "episode": ep_num,
            "title": episode.get('name', f"Episode {ep_num}"),
            "links": current_episode_links
        })

    return jsonify({"season": season_num, "episodes": episode_links_list})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

