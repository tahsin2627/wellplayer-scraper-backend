import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

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
    'Referer': 'https://sflix.to/'
}

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TMDB data from {url}: {e}")
        return None

def parse_query_for_language(query):
    language_keywords = ['hindi', 'tamil', 'telugu', 'malayalam', 'kannada', 'bengali', 'dubbed', 'dual audio']
    base_query_parts = [part for part in query.split() if part.lower() not in language_keywords]
    base_query = " ".join(base_query_parts)
    return base_query if base_query else query, query

# --- Scraper Functions ---

## --- NEW PRIMARY ADVANCED SCRAPER: SFlix --- ##
def scrape_sflix(tmdb_id, media_type, season=None, episode=None):
    found_links = []
    try:
        base_url = "https://sflix.to"
        
        # Step 1: Get the "Episode ID" from the first API call
        episodes_api_url = f"{base_url}/ajax/movie/episodes/{tmdb_id}"
        episodes_response = requests.get(episodes_api_url, headers=HEADERS, timeout=10)
        episodes_soup = BeautifulSoup(episodes_response.json()['html'], 'lxml')
        
        episode_id = None
        if media_type == 'movie':
            episode_item = episodes_soup.select_one('.ep-item')
            if episode_item:
                episode_id = episode_item.get('data-id')
        else: # tv
            for ep_item in episodes_soup.select('.ep-item'):
                if ep_item.get('data-season') == str(season) and ep_item.get('data-episode') == str(episode):
                    episode_id = ep_item.get('data-id')
                    break
        
        if not episode_id:
            print("SFlix: Could not find episode ID.")
            return []

        # Step 2: Get the Server List from the second API call
        servers_api_url = f"{base_url}/ajax/episode/servers/{episode_id}"
        servers_response = requests.get(servers_api_url, headers=HEADERS, timeout=10)
        servers_soup = BeautifulSoup(servers_response.json()['html'], 'lxml')

        # Step 3: Get the Final Embed Link from the third API call for each server
        for server_item in servers_soup.select('.server-item'):
            server_id = server_item.get('data-id')
            server_name = server_item.text.strip()
            
            final_link_api_url = f"{base_url}/ajax/server/{server_id}"
            final_link_response = requests.get(final_link_api_url, headers=HEADERS, timeout=10)
            
            final_link_json = final_link_response.json()
            if final_link_json.get('status') and final_link_json.get('result'):
                embed_url = "https:" + final_link_json['result']['url']
                lang = "Dubbed" if "dub" in server_name.lower() else "Original"
                found_links.append({"url": embed_url, "source": f"SFlix - {server_name}", "lang": lang})
                
    except Exception as e:
        print(f"Error scraping SFlix: {e}")
        
    return found_links

## --- SECONDARY ROBUST SCRAPER --- ##
def scrape_vidsrc_to_sources(tmdb_id, media_type, season=None, episode=None):
    # This function remains as a backup
    found_links = []
    # ... (rest of the vidsrc.to scraper code is unchanged) ...
    try:
        base_url = "https://vidsrc.to/"
        embed_url = f"{base_url}embed/{media_type}/{tmdb_id}"
        if media_type == 'tv':
            embed_url += f"/{season}/{episode}"

        response = requests.get(embed_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'lxml')
        
        server_divs = soup.find('div', class_='servers')
        if not server_divs: return []
        
        for server_link in server_divs.find_all('li'):
            server_name = server_link.text.strip()
            data_id = server_link.get('data-id')
            if not data_id: continue
            
            source_url = f"{base_url}ajax/embed/source/{data_id}"
            source_response = requests.get(source_url, headers={'Referer': embed_url, 'User-Agent': USER_AGENT}, timeout=10)
            
            if source_response.status_code == 200:
                source_data = source_response.json()
                iframe_src = source_data.get('result', {}).get('url')
                if iframe_src:
                    final_url = urljoin("https:", iframe_src)
                    lang = "Dubbed" if "dub" in server_name.lower() or "hindi" in server_name.lower() else "Original"
                    found_links.append({"url": final_url, "source": f"VidSrc - {server_name}", "lang": lang})
    except Exception as e:
        print(f"Error scraping VidSrc.to sources: {e}")
    return found_links

## --- TERTIARY TEXT-BASED SCRAPERS --- ##
# ... (All your other scrapers like hdhub4u, cinefreak, etc. remain here unchanged) ...
def scrape_hdhub4u(query):
    found_links = []
    try:
        base_url = "https://hdhub4u.build/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        search_response = requests.get(search_url, headers=HEADERS, timeout=15)
        if search_response.status_code != 200: return []
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        first_result = search_soup.select_one('article.post .entry-title a')
        if not first_result: return []
        movie_page_url = first_result['href']
        post_title = first_result.text.lower()
        movie_page_response = requests.get(movie_page_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_page_response.text, 'lxml')
        watch_online_link = movie_soup.find('a', class_=["aio-red", "dl-button"], string=re.compile(r'Watch Online', re.IGNORECASE))
        if not watch_online_link: return []
        stream_page_url = watch_online_link['href']
        stream_page_response = requests.get(stream_page_url, headers=HEADERS, timeout=15)
        stream_soup = BeautifulSoup(stream_page_response.text, 'lxml')
        iframe = stream_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            lang = "Hindi" if "hindi" in post_title or "dubbed" in post_title else "Original"
            found_links.append({"url": iframe['src'], "source": "HDHub4u", "lang": lang})
    except Exception as e:
        print(f"Error scraping HDHub4u: {e}")
    return found_links

# ... other text-based scrapers (cinefreak, skymovieshd, dongobd, etc.) go here ...

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend v18 (SFlix Integration) is running!"

@app.route('/search')
def search():
    # This endpoint is unchanged
    query = request.args.get('query')
    if not query: return jsonify({"error": "A 'query' parameter is required."}), 400
    if not TMDB_API_KEY: return jsonify({"error": "TMDB_API_KEY is not configured."}), 500
    base_query, _ = parse_query_for_language(query)
    search_url = f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(base_query)}"
    data = get_tmdb_data(search_url)
    if not data or not data.get("results"): return jsonify({"error": f"Could not find '{query}'."}), 404
    results = [
        {"id": item.get("id"), "type": item.get("media_type"), "title": item.get("title") or item.get("name"), "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4], "poster_path": item.get("poster_path")}
        for item in data["results"] if item.get("media_type") in ["movie", "tv"]
    ]
    return jsonify(results)

@app.route('/movie/<int:tmdb_id>')
def get_movie_details(tmdb_id):
    original_query = request.args.get('query')
    all_links = []
    
    # --- UPDATED LOGIC ---
    # 1. Primary Scraper: SFlix
    all_links.extend(scrape_sflix(tmdb_id, 'movie'))
    
    # 2. If SFlix fails, try the next robust scraper
    if not all_links:
        print("SFlix failed, trying VidSrc.to...")
        all_links.extend(scrape_vidsrc_to_sources(tmdb_id, 'movie'))

    # 3. Finally, run all text-based scrapers as a last resort (in parallel for speed)
    if original_query:
        text_scrapers = [
            scrape_hdhub4u,
            # Add your other text-based scrapers (cinefreak, etc.) here
        ]
        with ThreadPoolExecutor(max_workers=len(text_scrapers)) as executor:
            results = executor.map(lambda f: f(original_query), text_scrapers)
            for result in results:
                all_links.extend(result)

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
            
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

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
    tmdb_id, season_num, ep_num = request.args.get('tmdb_id'), request.args.get('season'), request.args.get('episode')
    if not all([tmdb_id, season_num, ep_num]): 
        return jsonify({"error": "tmdb_id, season, and episode are required."}), 400

    all_links = []
    
    # Prioritize SFlix for episodes as well
    all_links.extend(scrape_sflix(tmdb_id, 'tv', season_num, ep_num))
    
    # Fallback to VidSrc.to if SFlix fails
    if not all_links:
        all_links.extend(scrape_vidsrc_to_sources(tmdb_id, 'tv', season_num, ep_num))
        
    # Get episode title from TMDB
    episode_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}/episode/{ep_num}?api_key={TMDB_API_KEY}"
    episode_data = get_tmdb_data(episode_details_url)
    episode_title = episode_data.get('name', f"Episode {ep_num}")

    return jsonify({
        "episode": ep_num,
        "title": episode_title,
        "links": list({link['url']: link for link in all_links}.values())
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
