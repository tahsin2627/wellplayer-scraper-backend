import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Get your TMDB API Key from environment variables
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

# --- Scraper Functions for Each Source ---

def get_vidsrc_links(imdb_id, media_type, season=None, episode=None):
    """Source 1 & 2: vidsrc.to and vidsrc.me"""
    links = []
    try:
        if media_type == 'movie':
            links.append(f"https://vidsrc.to/embed/movie/{imdb_id}")
            links.append(f"https://vidsrc.me/embed/movie?imdb={imdb_id}")
        elif media_type == 'tv':
            s = season or '1'
            e = episode or '1'
            links.append(f"https://vidsrc.to/embed/tv/{imdb_id}/{s}-{e}")
            links.append(f"https://vidsrc.me/embed/tv?imdb={imdb_id}&season={s}&episode={e}")
    except Exception as e:
        print(f"Error getting vidsrc links: {e}")
    return links

def get_2embed_link(imdb_id, media_type, season=None, episode=None):
    """Source 3: 2embed.cc"""
    try:
        if media_type == 'movie':
            return f"https://2embed.cc/embed/{imdb_id}"
        elif media_type == 'tv':
            s = season or '1'
            e = episode or '1'
            return f"https://2embed.cc/embed/tv?imdb={imdb_id}&s={s}&e={e}"
    except Exception as e:
        print(f"Error getting 2embed link: {e}")
    return None

def get_fmoviesz_link(tmdb_id, media_type, season=None, episode=None):
    """Source 4: fmoviesz.to (uses TMDB ID)"""
    try:
        if media_type == 'movie':
            return f"https://fmoviesz.to/movie/{tmdb_id}"
        elif media_type == 'tv':
            s = season or '1'
            e = episode or '1'
            return f"https://fmoviesz.to/tv/{tmdb_id}-{s}-{e}"
    except Exception as e:
        print(f"Error getting fmoviesz link: {e}")
    return None
    
# --- Main API Endpoint ---

@app.route('/search')
def search():
    """
    Searches for a title using the TMDB API, then finds streaming links from all sources.
    """
    query = request.args.get('query')
    season = request.args.get('s')
    episode = request.args.get('e')

    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured on the server."}), 500

    try:
        # --- Step 1: Search TMDB to get IDs and info ---
        tmdb_search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
        tmdb_response = requests.get(tmdb_search_url)
        tmdb_data = tmdb_response.json()

        if not tmdb_data.get("results"):
            return jsonify({"error": f"Could not find '{query}'."}), 404
        
        first_result = tmdb_data["results"][0]
        tmdb_id = first_result.get("id")
        media_type = first_result.get("media_type")
        
        # --- Step 2: Get the IMDb ID for sources that need it ---
        details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
        details_response = requests.get(details_url)
        details_data = details_response.json()
        
        imdb_id = details_data.get("imdb_id")
        title = first_result.get("name") or first_result.get("title")

        if not imdb_id:
            return jsonify({"error": "Could not find IMDb ID for this title."}), 404

        # --- Step 3: Scrape all sources and collect the links ---
        all_links = []
        all_links.extend(get_vidsrc_links(imdb_id, media_type, season, episode))
        
        link_2embed = get_2embed_link(imdb_id, media_type, season, episode)
        if link_2embed:
            all_links.append(link_2embed)
            
        link_fmoviesz = get_fmoviesz_link(tmdb_id, media_type, season, episode)
        if link_fmoviesz:
            all_links.append(link_fmoviesz)

        if not all_links:
            return jsonify({"error": "Could not find any streaming links from any source."}), 404
            
        return jsonify({ "title": title, "links": all_links })
        
    except Exception as e:
        print(f"An error occurred in /search: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/')
def index():
    """A simple health-check page."""
    return "WellPlayer Scraper Backend is running!"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
