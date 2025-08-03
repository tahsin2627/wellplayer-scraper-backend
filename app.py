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
HEADERS = { 'User-Agent': USER_AGENT, 'Referer': 'https://www.google.com/' }

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching TMDB data: {e}")
        return None

# --- NEW SCRAPER FUNCTIONS ---

def scrape_filmcave(query):
    found_links = []
    try:
        base_url = "https://filmcave.net/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        
        result_link = soup.select_one('.movies-list .ml-item a')
        if not result_link: return []
        
        movie_url = result_link['href']
        movie_res = requests.get(movie_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_res.text, 'lxml')
        
        iframe_src = movie_soup.select_one('#playeriframe')['src']
        if iframe_src:
            lang = "Dubbed" if "hindi" in query.lower() or "dubbed" in query.lower() else "Original"
            found_links.append({"url": iframe_src, "source": "FilmCave", "lang": lang})
    except Exception as e:
        print(f"Error scraping FilmCave: {e}")
    return found_links

def scrape_moviemaze(query):
    found_links = []
    try:
        base_url = "https://moviemaze.cc/"
        search_url = f"{base_url}search/?q={quote_plus(query)}"
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        
        result_link = soup.select_one('.movie-item a')
        if not result_link: return []

        movie_url = urljoin(base_url, result_link['href'])
        movie_res = requests.get(movie_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_res.text, 'lxml')
        
        iframe_src = movie_soup.select_one('.iframe-container iframe')['src']
        if iframe_src:
            lang = "Dubbed" if "hindi" in query.lower() or "dubbed" in query.lower() else "Original"
            found_links.append({"url": iframe_src, "source": "MovieMaze", "lang": lang})
    except Exception as e:
        print(f"Error scraping MovieMaze: {e}")
    return found_links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (New Sources Edition) is running!"

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
    original_query = request.args.get('query')
    if not original_query:
        return jsonify({"error": "A query parameter is required to fetch movie links."}), 400
        
    all_links = []
    
    # Run the new scrapers in parallel for maximum speed
    scrapers = [scrape_filmcave, scrape_moviemaze]
    with ThreadPoolExecutor(max_workers=len(scrapers)) as executor:
        results = executor.map(lambda f: f(original_query), scrapers)
        for result in results:
            all_links.extend(result)

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
        
    return jsonify({"links": list({link['url']: link for link in all_links}.values())})

# For TV shows, we return an empty list as these new sites are not reliable for episodes
@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    return jsonify({"error": "TV series are not supported by these sources."}), 404

@app.route('/episodes')
def get_episodes():
    return jsonify({"error": "TV series are not supported by these sources."}), 404

@app.route('/episode-links')
def get_episode_links():
    return jsonify({"error": "TV series are not supported by these sources."}), 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
