import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# Initialize the Flask App
app = Flask(__name__)
CORS(app) # Allows your frontend to talk to this backend

# --- Scraper Functions ---
def get_vidsrc_links(imdb_id, media_type, season=None, episode=None):
    """Constructs streaming URLs for vidsrc.to and similar sites."""
    links = []
    if media_type == 'movie':
        links.append(f"https://vidsrc.to/embed/movie/{imdb_id}")
        links.append(f"https://vidsrc.me/embed/movie?imdb={imdb_id}")
    elif media_type == 'series':
        # Default to season 1, episode 1 if not specified
        s = season or '1'
        e = episode or '1'
        links.append(f"https://vidsrc.to/embed/tv/{imdb_id}/{s}-{e}")
        links.append(f"https://vidsrc.me/embed/tv?imdb={imdb_id}&season={s}&episode={e}")
    return links

def get_2embed_link(imdb_id, media_type):
    """Constructs the streaming URL for 2embed.cc."""
    # 2embed is another popular source with a simple URL structure
    if media_type == 'movie':
        return f"https://2embed.cc/embed/{imdb_id}"
    elif media_type == 'series':
        # For series, it usually requires season/episode, but the base link often works for S1E1
        return f"https://2embed.cc/embed/{imdb_id}"
    return None

# --- The API Endpoint for Your Frontend ---
@app.route('/search')
def search():
    """
    This is the endpoint your WellPlayer website will call.
    It takes a title, finds its IMDb ID, then scrapes all sources for links.
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400

    try:
        # --- Step 1: Find the IMDb ID and media type for the title ---
        # Using a public, free-to-use key for the OMDb API.
        omdb_api_key = "bf168b9"
        find_id_url = f"http://www.omdbapi.com/?t={query}&apikey={omdb_api_key}"
        id_response = requests.get(find_id_url)
        id_data = id_response.json()

        if id_data.get("Response") == "False" or "imdbID" not in id_data:
            return jsonify({"error": f"Could not find '{query}'."}), 404
            
        imdb_id = id_data.get("imdbID")
        title = id_data.get("Title")
        media_type = id_data.get("Type") # This will be 'movie' or 'series'

        # --- Step 2: Scrape all sources ---
        all_links = []
        all_links.extend(get_vidsrc_links(imdb_id, media_type))
        
        link_2embed = get_2embed_link(imdb_id, media_type)
        if link_2embed:
            all_links.append(link_2embed)

        if not all_links:
            return jsonify({"error": "Could not find any streaming links for this title."}), 404
            
        # Return all found links
        return jsonify({
            "title": title,
            "links": all_links
        })
        
    except Exception as e:
        print(f"An error occurred in /search: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/')
def index():
    """A simple health-check page."""
    return "WellPlayer Scraper Backend is running!"

# This part is needed for Render to run the app
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
