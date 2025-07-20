ort=port)
import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus

app = Flask(__name__)
CORS(app)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

# --- Scraper Functions for Each Source ---

def get_vidsrc_links(imdb_id, media_type, season=None, episode=None):
    """Source 1 & 2: vidsrc.to and vidsrc.me"""
    links = []
    # ... (This function is already stable and remains unchanged) ...
    return links

def get_2embed_link(imdb_id, media_type, season=None, episode=None):
    """Source 3: 2embed.cc"""
    # ... (This function is already stable and remains unchanged) ...
    return None

def scrape_sflix(query):
    """Source 4: sflix.to"""
    # ... (This function is already stable and remains unchanged) ...
    return None

def get_fmoviesz_link(tmdb_id, media_type, season=None, episode=None):
    """Source 5: fmoviesz.to"""
    # ... (This function is already stable and remains unchanged) ...
    return None

# --- UPGRADED ROBUST SCRAPER ---
def scrape_katmoviehd(query):
    """Source 6: katmoviehd.lat (Now more robust)"""
    try:
        search_url = f"https://katmoviehd.lat/?s={quote_plus(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        search_response = requests.get(search_url, headers=headers, timeout=10)
        search_soup = BeautifulSoup(search_response.text, 'lxml')

        # Find the container for the first search result
        first_result_container = search_soup.find('h2', class_='title')
        # This is the key fix: Check if the container was found before trying to find the link
        if first_result_container:
            first_result_link = first_result_container.find('a')
            if first_result_link and first_result_link.has_attr('href'):
                return first_result_link['href']
        
        return None # Return None if anything is not found, preventing crashes
    except Exception as e:
        print(f"Error scraping KatMovieHD: {e}")
        return None

# --- NEW RELIABLE SCRAPER ---
def scrape_extramovies(query):
    """Source 7: extramovies.lat"""
    try:
        search_url = f"https://extramovies.lat/?s={quote_plus(query)}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        search_response = requests.get(search_url, headers=headers, timeout=10)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        
        # Find the first result link in the main content area
        content_area = search_soup.find('div', id='content_box')
        if content_area:
            first_result = content_area.find('a')
            if first_result and first_result.has_attr('href'):
                # This site often provides direct embed links in search results
                return first_result['href']

        return None
    except Exception as e:
        print(f"Error scraping ExtraMovies: {e}")
        return None


# --- Main API Endpoint ---
@app.route('/search')
def search():
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured on the server."}), 500

    try:
        all_links = []
        
        # --- Run all scrapers ---
        
        # Run the new, more direct scrapers first
        katmovie_link = scrape_katmoviehd(query)
        if katmovie_link: all_links.append(katmovie_link)

        extramovies_link = scrape_extramovies(query)
        if extramovies_link: all_links.append(extramovies_link)
            
        sflix_link = scrape_sflix(query)
        if sflix_link: all_links.append(sflix_link)

        # Use TMDB to get IDs for the other scrapers
        tmdb_search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
        tmdb_response = requests.get(tmdb_search_url)
        tmdb_data = tmdb_response.json()

        title = query # Default title
        if tmdb_data.get("results"):
            first_result = tmdb_data["results"][0]
            tmdb_id = first_result.get("id")
            media_type = first_result.get("media_type")
            title = first_result.get("name") or first_result.get("title")
            
            details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
            details_response = requests.get(details_url)
            details_data = details_response.json()
            imdb_id = details_data.get("imdb_id")

            if imdb_id:
                all_links.extend(get_vidsrc_links(imdb_id, media_type))
                link_2embed = get_2embed_link(imdb_id, media_type)
                if link_2embed: all_links.append(link_2embed)
            
            if tmdb_id:
                fmoviesz_link = get_fmoviesz_link(tmdb_id, media_type)
                if fmoviesz_link: all_links.append(fmoviesz_link)

        if not all_links:
            return jsonify({"error": "Could not find any streaming links from any source."}), 404
            
        unique_links = list(set(all_links))
        return jsonify({ "title": title, "links": unique_links })
        
    except Exception as e:
        print(f"An error occurred in /search: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/')
def index():
    return "WellPlayer Scraper Backend is running!"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
