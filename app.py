import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin
from functools import lru_cache

app = Flask(__name__)
CORS(app)

# --- Configuration & Global Variables ---
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_API_BASE = "https://api.themoviedb.org/3"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    """A cached function to fetch data from TMDB."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TMDB data from {url}: {e}")
        return None

# --- Link Provider & Scraper Functions ---
def get_vidsrc_links(imdb_id, media_type, season=None, episode=None):
    """Source 1 & 2: vidsrc.to and vidsrc.me (Original Language)"""
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
    """Source 3: 2embed.cc (Original Language)"""
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

def scrape_skymovieshd_for_dubs(query):
    """Source 4: skymovieshd.land - Upgraded to search for dubbed content."""
    base_url = "https://skymovieshd.land/"
    found_links = []
    try:
        search_url = f"{base_url}?s={quote_plus(query)}"
        headers = {'User-Agent': USER_AGENT}
        search_response = requests.get(search_url, headers=headers, timeout=10)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        
        post = search_soup.find('div', class_='post-content')
        if not post: return []

        post_title = post.find('h2').text.lower() if post.find('h2') else ''
        title_link_element = post.find('a')
        if not title_link_element or not title_link_element.has_attr('href'): return []
        
        movie_page_url = title_link_element['href']
        movie_response = requests.get(movie_page_url, headers=headers, timeout=10)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        
        for link in movie_soup.find_all('a'):
            link_text = link.text.lower()
            
            if 'stream' in link_text or 'watch' in link_text or 'download' in link_text:
                lang = "Unknown"
                if 'hindi' in post_title or 'hindi' in link_text:
                    lang = "Hindi"
                elif 'dual audio' in post_title or 'dual audio' in link_text:
                    lang = "Dual Audio"
                
                full_url = urljoin(base_url, link.get('href', ''))
                if full_url and ('stream' in full_url or 'vcloud' in full_url):
                     found_links.append({"url": full_url, "source": "SkyMoviesHD", "lang": lang})

    except Exception as e:
        print(f"Error scraping SkymoviesHD for dubs: {e}")
    
    return found_links[:1]

def scrape_cinefreak_for_dubs(query):
    """Source 5: cinefreak.net - Upgraded for dubbed content."""
    base_url = "https://cinefreak.net/"
    found_links = []
    try:
        search_url = f"{base_url}?s={quote_plus(query)}"
        headers = {'User-Agent': USER_AGENT}
        search_response = requests.get(search_url, headers=headers, timeout=15)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        
        movie_link_element = search_soup.find('a', class_='post-image-container')
        if not movie_link_element or not movie_link_element.has_attr('href'):
            return []
            
        movie_page_url = movie_link_element['href']
        post_title = movie_link_element.get('title', '').lower()

        movie_response = requests.get(movie_page_url, headers=headers, timeout=15)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        
        iframe = movie_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            lang = "Unknown"
            if 'hindi' in post_title:
                lang = "Hindi"
            elif 'dubbed' in post_title:
                lang = "Dubbed"
            
            full_url = urljoin(base_url, iframe['src'])
            found_links.append({"url": full_url, "source": "Cinefreak", "lang": lang})

    except Exception as e:
        print(f"Error scraping Cinefreak: {e}")
        
    return found_links

def run_all_scrapers(query):
    """Runs all text-based scrapers and collects the results."""
    all_scraped_links = []
    
    all_scraped_links.extend(scrape_skymovieshd_for_dubs(query))
    all_scraped_links.extend(scrape_cinefreak_for_dubs(query))
    
    return all_scraped_links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend v4 is running!"

@app.route('/search')
def search():
    """Step 1: Search for media. Returns a list of potential matches."""
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured."}), 500

    search_url = f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(query)}"
    data = get_tmdb_data(search_url)
    
    if not data or not data.get("results"):
        return jsonify({"error": f"Could not find '{query}'."}), 404
        
    results = []
    for item in data["results"]:
        media_type = item.get("media_type")
        if media_type in ["movie", "tv"]:
            results.append({
                "id": item.get("id"),
                "type": media_type,
                "title": item.get("title") or item.get("name"),
                "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4],
                "poster_path": item.get("poster_path")
            })
    return jsonify(results)

@app.route('/movie/<int:tmdb_id>')
def get_movie_details(tmdb_id):
    """Step 2 (Movies): Get streaming links with improved fallback logic."""
    original_query = request.args.get('query')
    all_links = []

    # --- Phase 1: Try the fast and reliable IMDb-based sources first ---
    details_url = f"{TMDB_API_BASE}/movie/{tmdb_id}?api_key={TMDB_API_KEY}&append_to_response=external_ids"
    movie_data = get_tmdb_data(details_url)

    if not movie_data:
        return jsonify({"error": "Movie not found with that ID."}), 404

    imdb_id = movie_data.get("external_ids", {}).get("imdb_id")
    movie_title = movie_data.get("title")

    if imdb_id:
        vidsrc_links = get_vidsrc_links(imdb_id, 'movie')
        for link in vidsrc_links:
            all_links.append({"url": link, "source": "VidSrc", "lang": "Original"})

        link_2embed = get_2embed_link(imdb_id, 'movie')
        if link_2embed:
            all_links.append({"url": link_2embed, "source": "2Embed", "lang": "Original"})
            
    # --- Phase 2: Use Text-Based Scrapers for Dubbed Content or as a Fallback ---
    scrape_query = original_query or movie_title
    
    if scrape_query:
        scraped_links = run_all_scrapers(scrape_query)
        all_links.extend(scraped_links)

    # --- Final Step: Return results ---
    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
            
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    """Step 2 (TV): Get season info for a specific TV show."""
    details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
    details_data = get_tmdb_data(details_url)
    
    if not details_data:
        return jsonify({"error": "TV show not found."}), 404
    
    seasons = details_data.get('seasons', [])
    season_list = [
        {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")} 
        for s in seasons if s.get('season_number', 0) > 0
    ]
    return jsonify({"title": details_data.get("name"), "seasons": season_list})

@app.route('/episodes')
def get_episodes():
    """Step 3 (TV): Get episode links for a specific season."""
    tmdb_id = request.args.get('tmdb_id')
    season_num = request.args.get('season')
    original_query = request.args.get('query')

    if not tmdb_id or not season_num:
        return jsonify({"error": "tmdb_id and season are required."}), 400

    external_ids_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
    ids_data = get_tmdb_data(external_ids_url)
    if not ids_data or not ids_data.get("imdb_id"):
        return jsonify({"error": "Could not find IMDb ID for this series."}), 404
    imdb_id = ids_data.get("imdb_id")

    season_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    season_data = get_tmdb_data(season_details_url)
    if not season_data or not season_data.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
        
    episode_links_list = []
    for episode in season_data.get('episodes', []):
        ep_num = episode.get('episode_number')
        if ep_num:
            links = []
            vidsrc_links = get_vidsrc_links(imdb_id, 'tv', season_num, ep_num)
            for link in vidsrc_links:
                links.append({"url": link, "source": "VidSrc", "lang": "Original"})

            link_2embed = get_2embed_link(imdb_id, 'tv', season_num, ep_num)
            if link_2embed:
                links.append({"url": link_2embed, "source": "2Embed", "lang": "Original"})
            
            episode_links_list.append({
                "episode": ep_num,
                "title": episode.get('name', f"Episode {ep_num}"),
                "links": list({link['url']: link for link in links}.values())
            })

    return jsonify({"season": season_num, "episodes": episode_links_list})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
