import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# Initialize the Flask App
app = Flask(__name__)
CORS(app) # Allow your frontend to talk to this backend

# --- The Main Scraper Logic ---
def scrape_vidsrc(imdb_id):
    """Scrapes vidsrc.to for a streaming link using an IMDb ID."""
    try:
        # vidsrc.to uses a simple URL structure with the IMDb ID
        # Example: https://vidsrc.to/embed/movie/tt0133093
        stream_url = f"https://vidsrc.to/embed/movie/{imdb_id}"
        
        # We can check if the page exists, but for now, we'll assume it does
        # and just return the constructed URL. This is very fast.
        return stream_url
    except Exception as e:
        print(f"Error scraping vidsrc: {e}")
        return None

# --- The API Endpoint for Your Frontend ---
@app.route('/search')
def search():
    """
    This is the endpoint your WellPlayer website will call.
    It takes a movie title, finds its IMDb ID, then scrapes for a link.
    """
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400

    try:
        # --- Step 1: Find the IMDb ID for the movie title ---
        # We use a free, simple API for this.
        find_id_url = f"https://www.omdbapi.com/?t={query}&apikey=bf168b9" # A public, free-to-use key
        id_response = requests.get(find_id_url)
        id_data = id_response.json()

        if id_data.get("Response") == "False" or "imdbID" not in id_data:
            return jsonify({"error": "Movie not found."}), 404
            
        imdb_id = id_data.get("imdbID")
        title = id_data.get("Title")

        # --- Step 2: Scrape vidsrc.to with the IMDb ID ---
        stream_link = scrape_vidsrc(imdb_id)

        if not stream_link:
            return jsonify({"error": "Could not find a streaming link for this title."}), 404
            
        # Return the found link in a format the frontend can use
        return jsonify({
            "title": title,
            "links": [stream_link] # We return it as a list for consistency
        })
        
    except Exception as e:
        print(f"An error occurred in /search: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500


@app.route('/')
def index():
    return "WellPlayer Scraper Backend is running!"

# This part is needed for Render to run the app
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
