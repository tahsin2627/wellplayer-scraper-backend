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
STREAMING_API_URL = "https://consumet-api-movies-nine.vercel.app"
API_PROVIDERS = ['flixhq', 'goku', 'dramacool']

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
HEADERS = { 'User-Agent': USER_AGENT, 'Referer': 'https://www.google.com/' }

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e: print(f"Error fetching TMDB data: {e}"); return None

# --- Source Functions ---

## --- NEW IMDB TITLE SCRAPER --- ##
def scrape_imdb_search(query):
    results = []
    try:
        # IMDb's search URL for titles
        url = f"https://www.imdb.com/find/?q={quote_plus(query)}&s=tt&ttype=ft&ref_=fn_ft"
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Find all search result items
        for item in soup.select('.ipc-metadata-list-summary-item__c'):
            title_tag = item.select_one('a.ipc-mdem')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            imdb_id = title_tag['href'].split('/title/')[1].split('/')[0]
            
            year_tag = item.select_one('.ipc-metadata-list-summary-item__li')
            year = year_tag.text.strip() if year_tag else "N/A"

            # We create a result that looks like a TMDB result
            results.append({
                "id": imdb_id, # Use IMDb ID
                "type": "movie", # Assume movie for simplicity
                "title": f"{title} (IMDb)", # Add indicator
                "year": year,
                "poster_path": None # IMDb doesn't give easy poster links
            })
    except Exception as e:
        print(f"Error scraping IMDb search: {e}")
    return results

def get_stream_links_from_api(tmdb_id, media_type, s=None, e=None):
    # ... (function is unchanged)
    return []

def get_fallback_links(imdb_id, media_type, s=None, e=None):
    # ... (function is unchanged)
    return []

def scrape_hdhub4u(query):
    # ... (function is unchanged)
    return []

def scrape_cinefreak(query):
    # ... (function is unchanged)
    return []

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (IMDb Title Search Edition) is running!"

@app.route('/search')
def search():
    query = request.args.get('query')
    if not query: return jsonify({"error": "A 'query' parameter is required."}), 400
    
    all_results = []
    
    # Run TMDB and IMDb searches in parallel for maximum speed
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_tmdb = executor.submit(requests.get, f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(query)}", headers=HEADERS)
        future_imdb = executor.submit(scrape_imdb_search, query)
        
        # Process TMDB results
        tmdb_response = future_tmdb.result()
        if tmdb_response.status_code == 200:
            tmdb_data = tmdb_response.json()
            tmdb_results = [
                {"id": item.get("id"), "type": item.get("media_type"), "title": item.get("title") or item.get("name"), "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4], "poster_path": item.get("poster_path")}
                for item in tmdb_data.get("results", []) if item.get("media_type") in ["movie", "tv"]
            ]
            all_results.extend(tmdb_results)

        # Process IMDb results
        imdb_results = future_imdb.result()
        all_results.extend(imdb_results)

    if not all_results:
        return jsonify({"error": f"Could not find '{query}'."}), 404
    
    # De-duplicate results
    final_results = {str(res.get('id')): res for res in all_results}
    return jsonify(list(final_results.values()))

@app.route('/movie/<string:media_id>')
def get_movie_details(media_id):
    original_query = request.args.get('query')
    all_links = []
    
    tmdb_id, imdb_id = (None, media_id) if media_id.startswith('tt') else (int(media_id), None)
    
    # If we have a TMDB ID but no IMDb ID, fetch it
    if tmdb_id and not imdb_id:
        ids_data = get_tmdb_data(f"{TMDB_API_BASE}/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
        imdb_id = ids_data.get("imdb_id") if ids_data else None

    # --- "FETCH ALL" STRATEGY ---
    
    # 1. Start all ID-based sources in parallel
    id_based_scrapers = []
    if tmdb_id:
        id_based_scrapers.append(lambda: get_stream_links_from_api(tmdb_id, 'movie'))
    if imdb_id:
        id_based_scrapers.append(lambda: get_fallback_links(imdb_id, 'imdb', 'movie'))

    with ThreadPoolExecutor(max_workers=len(id_based_scrapers) or 1) as executor:
        id_results = executor.map(lambda f: f(), id_based_scrapers)
        for result in id_results:
            all_links.extend(result)

    # 2. Start all text-based "Dubbed Hunter" scrapers in parallel
    if original_query:
        text_scrapers = [scrape_hdhub4u, scrape_cinefreak]
        with ThreadPoolExecutor(max_workers=len(text_scrapers)) as executor:
            text_results = executor.map(lambda f: f(original_query), text_scrapers)
            for result in text_results:
                all_links.extend(result)

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
        
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

# ... TV Endpoints remain the same ...
@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    # ...
    return jsonify({})
@app.route('/episodes')
def get_episodes():
    # ...
    return jsonify({})
@app.route('/episode-links')
def get_episode_links():
    # ...
    return jsonify({})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
