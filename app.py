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
    # ... (code for this function is unchanged)
    return links

def get_2embed_link(imdb_id, media_type, season=None, episode=None):
    """Source 3: 2embed.cc"""
    # ... (code for this function is unchanged)
    return None

def scrape_sflix(query):
    """Source 4: sflix.to"""
    # ... (code for this function is unchanged)
    return None

def get_fmoviesz_link(tmdb_id, media_type, season=None, episode=None):
    """Source 5: fmoviesz.to"""
    # ... (code for this function is unchanged)
    return None

# --- NEW SCRAPER FOR KATMOVIEHD ---
def scrape_katmoviehd(query):
    """Source 6: katmoviehd.lat"""
    try:
        search_url = f"https://katmoviehd.lat/?s={quote_plus(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        search_response = requests.get(search_url, headers=headers)
        search_soup = BeautifulSoup(search_response.text, 'lxml')

        # Find the first search result link in the article titles
        first_result = search_soup.find('h2', class_='title').find('a')
        if not first_result or not first_result.has_attr('href'):
            return None

        # This link is the direct embed link
        return first_result['href']
    except Exception as e:
        print(f"Error scraping KatMovieHD: {e}")
        return None

# --- NEW SCRAPER FOR BOLLYFLIX ---
def scrape_bollyflix(query):
    """Source 7: bollyflix.autos"""
    try:
        search_url = f"https://bollyflix.autos/?s={quote_plus(query)}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        search_response = requests.get(search_url, headers=headers)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        
        # Find the first result link
        first_result = search_soup.find('a', class_='post-thumb')
        if not first_result or not first_result.has_attr('href'):
            return None

        # Go to the movie's page
        movie_page_url = first_result['href']
        movie_response = requests.get(movie_page_url, headers=headers)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')

        # Find an iframe that is likely the player
        iframe = movie_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            return iframe['src']
            
        return None
    except Exception as e:
        print(f"Error scraping Bollyflix: {e}")
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
        
        # Run the new scrapers first as they are more specific
        katmovie_link = scrape_katmoviehd(query)
        if katmovie_link:
            all_links.append(katmovie_link)

        bollyflix_link = scrape_bollyflix(query)
        if bollyflix_link:
            all_links.append(bollyflix_link)
            
        sflix_link = scrape_sflix(query)
        if sflix_link:
            all_links.append(sflix_link)

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
                if link_2embed:
                    all_links.append(link_2embed)
            
            if tmdb_id:
                fmoviesz_link = get_fmoviesz_link(tmdb_id, media_type)
                if fmoviesz_link:
                    all_links.append(fmoviesz_link)

        if not all_links:
            return jsonify({"error": "Could not find any streaming links from any source."}), 404
            
        # Use set to remove any duplicate links found from different sources
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
