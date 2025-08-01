import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin
from functools import lru_cache
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

# --- Configuration & Global Variables ---
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_API_BASE = "https://api.themoviedb.org/3"
STREAMING_API_URL = "https://consumet-api-movies-nine.vercel.app"
API_PROVIDERS = ['flixhq', 'goku', 'dramacool']

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

# --- Source Functions ---

## --- LAYER 1: STABLE API SOURCES --- ##
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
                all_links.append({"url": source['url'], "source": f"{provider.title()} - {quality}", "lang": "Original"})
            
            if all_links:
                print(f"Found links from API provider: {provider}")
                break
        except Exception as e:
            print(f"Error with API provider {provider}: {e}")
            continue
    return all_links

## --- LAYER 2: TRUSTED ID-BASED SOURCES --- ##
def get_vidsrc_link(imdb_id):
    try:
        return [{"url": f"https://vidsrc.to/embed/movie/{imdb_id}", "source": "VidSrc.to", "lang": "Original"}]
    except: return []

def get_2embed_link(imdb_id):
    try:
        return [{"url": f"https://www.2embed.cc/embed/{imdb_id}", "source": "2Embed", "lang": "Original"}]
    except: return []

def scrape_streamblasters(tmdb_id):
    found_links = []
    try:
        url = f"https://www.streamblasters.city/embed/movie/{tmdb_id}"
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200: return []
        soup = BeautifulSoup(response.text, 'lxml')
        for link in soup.select('ul.servers > li'):
            server_name = link.text.strip()
            iframe_src = link.get('data-embed')
            if iframe_src:
                lang = "Dubbed" if "dub" in server_name.lower() or "hindi" in server_name.lower() else "Original"
                found_links.append({"url": iframe_src, "source": f"StreamBlasters - {server_name}", "lang": lang})
    except Exception as e:
        print(f"Error scraping StreamBlasters: {e}")
    return found_links

## --- LAYER 3: TEXT-BASED FALLBACK --- ##
def scrape_dongobd(query):
    found_links = []
    try:
        base_url = "https://dongobd.com/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        search_response = requests.get(search_url, headers=HEADERS, timeout=15)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        movie_link_element = search_soup.find('a', class_='lnk-blk')
        if not movie_link_element: return []
        movie_page_url = movie_link_element['href']
        post_title = movie_link_element.get('title', '').lower()
        movie_response = requests.get(movie_page_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        iframe = movie_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            lang = "Hindi" if "hindi" in post_title or "dubbed" in post_title else "Original"
            found_links.append({"url": urljoin(base_url, iframe['src']), "source": "DongoBD", "lang": lang})
    except Exception as e:
        print(f"Error scraping Dongobd: {e}")
    return found_links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (Final Stable Hybrid) is running!"

@app.route('/search')
def search():
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
    
    ids_data = get_tmdb_data(f"{TMDB_API_BASE}/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
    imdb_id = ids_data.get("imdb_id") if ids_data else None

    # Layer 1: Stable Multi-Provider API
    all_links.extend(get_stream_links_from_api(tmdb_id, 'movie'))
    
    # Run Layer 2 and 3 sources in parallel for speed
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit ID-based scrapers
        future_streamblasters = executor.submit(scrape_streamblasters, tmdb_id)
        future_vidsrc = executor.submit(get_vidsrc_link, imdb_id) if imdb_id else None
        future_2embed = executor.submit(get_2embed_link, imdb_id) if imdb_id else None
        
        # Submit text-based scrapers
        future_dongobd = executor.submit(scrape_dongobd, original_query) if original_query else None

        # Collect results as they complete
        if future_vidsrc: all_links.extend(future_vidsrc.result())
        if future_2embed: all_links.extend(future_2embed.result())
        all_links.extend(future_streamblasters.result())
        if future_dongobd: all_links.extend(future_dongobd.result())
        
    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
            
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

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

    ids_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
    imdb_id = ids_data.get("imdb_id") if ids_data else None

    season_details = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}")
    if not season_details or not season_details.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
        
    episode_links_list = []
    for episode in season_details.get('episodes', []):
        ep_num = episode.get('episode_number')
        all_links_for_ep = []
        
        # For episodes, we prioritize the most reliable sources
        all_links_for_ep.extend(get_stream_links_from_api(tmdb_id, 'tv', season_num, ep_num))
        if imdb_id:
            # We can simplify these calls for TV episodes as they are less critical than the API one
            try:
                all_links_for_ep.append({"url": f"https://vidsrc.to/embed/tv/{imdb_id}/{season_num}/{ep_num}", "source": "VidSrc.to", "lang": "Original"})
            except: pass
        
        episode_links_list.append({
            "episode": ep_num,
            "title": episode.get('name', f"Episode {ep_num}"),
            "links": list({link['url']: link for link in all_links_for_ep}.values())
        })

    return jsonify({"season": season_num, "episodes": episode_links_list})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
