import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- NEW: Get your TMDB API Key from environment variables ---
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

def get_vidsrc_links(imdb_id, media_type, season=None, episode=None):
    """Constructs streaming URLs for vidsrc.to and similar sites."""
    links = []
    if media_type == 'movie':
        links.append(f"https://vidsrc.to/embed/movie/{imdb_id}")
        links.append(f"https://vidsrc.me/embed/movie?imdb={imdb_id}")
    elif media_type == 'tv': # TMDB uses 'tv' for series
        s = season or '1'
        e = episode or '1'
        links.append(f"https://vidsrc.to/embed/tv/{imdb_id}/{s}-{e}")
        links.append(f"https://vidsrc.me/embed/tv?imdb={imdb_id}&season={s}&episode={e}")
    return links

@app.route('/search')
def search():
    """
    Searches for a title using the TMDB API, then finds streaming links.
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured on the server."}), 500

    try:
        # --- Step 1: Search TMDB for the movie/series to get its ID ---
        tmdb_search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
        tmdb_response = requests.get(tmdb_search_url)
        tmdb_data = tmdb_response.json()

        if not tmdb_data.get("results"):
            return jsonify({"error": f"Could not find '{query}'."}), 404
        
        # Get the first and most relevant result
        first_result = tmdb_data["results"][0]
        media_id = first_result.get("id")
        media_type = first_result.get("media_type") # Will be 'movie' or 'tv'
        
        # --- Step 2: Use the TMDB ID to find the IMDb ID ---
        details_url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/external_ids?api_key={TMDB_API_KEY}"
        details_response = requests.get(details_url)
        details_data = details_response.json()
        
        imdb_id = details_data.get("imdb_id")
        title = first_result.get("name") or first_result.get("title")

        if not imdb_id:
            return jsonify({"error": "Could not find IMDb ID for this title."}), 404

        # --- Step 3: Get streaming links using the IMDb ID ---
        all_links = get_vidsrc_links(imdb_id, media_type)

        if not all_links:
            return jsonify({"error": "Could not find any streaming links."}), 404
            
        return jsonify({ "title": title, "links": all_links })
        
    except Exception as e:
        print(f"An error occurred in /search: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/')
def index():
    return "WellPlayer Scraper Backend is running!"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
