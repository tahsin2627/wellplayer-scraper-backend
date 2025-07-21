import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin

app = Flask(__name__)
CORS(app)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

# --- Helper function for making requests ---
def get_soup(url):
    """A helper function to get a BeautifulSoup object from a URL, handling errors."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()  # Will raise an error for bad responses (4xx or 5xx)
    return BeautifulSoup(response.text, 'lxml')

# --- Scraper Functions for Each Source ---

def get_vidsrc_links(imdb_id, media_type, season=None, episode=None):
    """Source 1 & 2: vidsrc.to and vidsrc.me (Stable)"""
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
    """Source 3: 2embed.cc (Stable)"""
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

# --- UPGRADED, LANGUAGE-AWARE SCRAPERS ---

def scrape_sflix(query):
    """Source 4: sflix.to (Upgraded language-aware scraper)"""
    try:
        search_soup = get_soup(f"https://sflix.to/search/{query.replace(' ', '-')}")
        results = search_soup.find_all('a', class_='flw-item-tip')
        if not results: return None

        best_match_url = None
        query_lower = query.lower()
        # Intelligently find the best match based on the query
        for result in results:
            title = result.get('title', '').lower()
            if all(word in title for word in query_lower.split()):
                best_match_url = "https://sflix.to" + result['href']
                break # Found a good match
        
        if not best_match_url:
            # Fallback to the first result if no perfect match is found
            best_match_url = "https://sflix.to" + results[0]['href']

        movie_page_soup = get_soup(best_match_url)
        watch_button = movie_page_soup.find('a', class_='btn-play')
        if not watch_button or not watch_button.has_attr('href'): return None
            
        embed_path = watch_button['href'].replace('/watch-', '/embed-')
        return "https://sflix.to" + embed_path
    except Exception as e:
        print(f"Error scraping sflix: {e}")
        return None


def scrape_katmoviehd(query):
    """Source 5: katmoviehd.lat (Upgraded language-aware scraper)"""
    try:
        search_soup = get_soup(f"https://katmoviehd.lat/?s={quote_plus(query)}")
        results = search_soup.find_all('h2', class_='title')
        if not results: return None

        best_match_url = None
        query_lower = query.lower()
        for result in results:
            link_element = result.find('a')
            if link_element:
                title = link_element.text.lower()
                if all(word in title for word in query_lower.split()):
                    best_match_url = link_element['href']
                    break
        
        if not best_match_url:
            first_link = results[0].find('a')
            if first_link and first_link.has_attr('href'):
                best_match_url = first_link['href']
            else:
                return None

        # This site often requires navigating to the page to find the real link
        movie_page_soup = get_soup(best_match_url)
        # Look for an iframe, a common embed method
        iframe = movie_page_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            return iframe['src']
        
        return best_match_url # Fallback to the page link
    except Exception as e:
        print(f"Error scraping KatMovieHD: {e}")
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
        
        # Run our powerful direct scrapers first
        sflix_link = scrape_sflix(query)
        if sflix_link: all_links.append(sflix_link)
        
        katmovie_link = scrape_katmoviehd(query)
        if katmovie_link: all_links.append(katmovie_link)

        # Use TMDB to get IDs for the other, simpler scrapers
        cleaned_query = query.lower().replace('hindi', '').replace('dubbed', '').strip()
        tmdb_search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={cleaned_query}"
        tmdb_response = requests.get(tmdb_search_url)
        tmdb_data = tmdb_response.json()

        title = query
        if tmdb_data.get("results"):
            first_result = tmdb_data["results"][0]
            media_type = first_result.get("media_type")
            title = first_result.get("name") or first_result.get("title")
            
            details_url = f"https://api.themoviedb.org/3/{media_type}/{first_result.get('id')}/external_ids?api_key={TMDB_API_KEY}"
            details_response = requests.get(details_url)
            details_data = details_response.json()
            imdb_id = details_data.get("imdb_id")

            if imdb_id:
                all_links.extend(get_vidsrc_links(imdb_id, media_type))
                link_2embed = get_2embed_link(imdb_id, media_type)
                if link_2embed: all_links.append(link_2embed)

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
