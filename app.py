import os
import re
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
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/'
}

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    """A cached function to fetch data from TMDB."""
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TMDB data from {url}: {e}")
        return None

def parse_query_for_language(query):
    """Parses a query to find a base title."""
    language_keywords = ['hindi', 'tamil', 'telugu', 'malayalam', 'kannada', 'bengali', 'dubbed', 'dual audio']
    
    base_query_parts = [part for part in query.split() if part.lower() not in language_keywords]
    base_query = " ".join(base_query_parts)

    if not base_query:
        base_query = query
        
    return base_query, query

# --- Link Provider & Scraper Functions ---

## --- PRIMARY ROBUST SCRAPER --- ##
def scrape_vidsrc_to_sources(tmdb_id, media_type, season=None, episode=None):
    """Scrapes vidsrc.to to get multiple embed links from its servers."""
    found_links = []
    try:
        base_url = "https://vidsrc.to/"
        if media_type == 'movie':
            embed_url = f"{base_url}embed/movie/{tmdb_id}"
        else: # tv
            embed_url = f"{base_url}embed/tv/{tmdb_id}/{season}/{episode}"

        response = requests.get(embed_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'lxml')
        
        server_divs = soup.find('div', class_='servers')
        if not server_divs: return []
        
        for server_link in server_divs.find_all('li'):
            server_name = server_link.text.strip()
            data_id = server_link.get('data-id')
            if not data_id: continue
            
            source_url = f"{base_url}ajax/embed/source/{data_id}"
            source_response = requests.get(source_url, headers={'Referer': embed_url, 'User-Agent': USER_AGENT}, timeout=10)
            
            if source_response.status_code == 200:
                source_data = source_response.json()
                iframe_src = source_data.get('result', {}).get('url')
                if iframe_src:
                    final_url = urljoin("https:", iframe_src)
                    lang = "Dubbed" if "dub" in server_name.lower() or "hindi" in server_name.lower() else "Original"
                    found_links.append({"url": final_url, "source": f"VidSrc - {server_name}", "lang": lang})
    except Exception as e:
        print(f"Error scraping VidSrc.to sources: {e}")
    return found_links

## --- SECONDARY SCRAPER: HDHub4u (Re-added) --- ##
def scrape_hdhub4u(query):
    """Text-based scraper for hdhub4u.build."""
    found_links = []
    try:
        base_url = "https://hdhub4u.build/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        search_response = requests.get(search_url, headers=HEADERS, timeout=15)
        if search_response.status_code != 200: return []
        
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        first_result = search_soup.select_one('article.post .entry-title a')
        if not first_result: return []

        movie_page_url = first_result['href']
        post_title = first_result.text.lower()
        
        movie_page_response = requests.get(movie_page_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_page_response.text, 'lxml')
        
        watch_online_link = movie_soup.find('a', class_=["aio-red", "dl-button"], string=re.compile(r'Watch Online', re.IGNORECASE))
        if not watch_online_link: return []

        stream_page_url = watch_online_link['href']
        stream_page_response = requests.get(stream_page_url, headers=HEADERS, timeout=15)
        stream_soup = BeautifulSoup(stream_page_response.text, 'lxml')
        
        iframe = stream_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            lang = "Hindi" if "hindi" in post_title or "dubbed" in post_title else "Original"
            found_links.append({"url": iframe['src'], "source": "HDHub4u", "lang": lang})
    except Exception as e:
        print(f"Error scraping HDHub4u: {e}")
    return found_links

## --- SECONDARY SCRAPER: Cinefreak (Re-added) --- ##
def scrape_cinefreak(query):
    """Text-based scraper for cinefreak.net."""
    found_links = []
    try:
        base_url = "https://cinefreak.net/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        search_response = requests.get(search_url, headers=HEADERS, timeout=15)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        
        movie_link_element = search_soup.find('a', class_='post-image-container')
        if not movie_link_element or not movie_link_element.has_attr('href'): return []
            
        movie_page_url = movie_link_element['href']
        post_title = movie_link_element.get('title', '').lower()

        movie_response = requests.get(movie_page_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        
        iframe = movie_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            lang = "Hindi" if "hindi" in post_title or "dubbed" in post_title else "Original"
            found_links.append({"url": urljoin(base_url, iframe['src']), "source": "Cinefreak", "lang": lang})
    except Exception as e:
        print(f"Error scraping Cinefreak: {e}")
    return found_links
    
## --- SECONDARY SCRAPER: Skymovieshd (Re-added) --- ##
def scrape_skymovieshd(query):
    """Text-based scraper for skymovieshd.land."""
    found_links = []
    try:
        base_url = "https://skymovieshd.land/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        search_response = requests.get(search_url, headers=HEADERS, timeout=10)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        
        post = search_soup.find('div', class_='post-content')
        if not post: return []

        post_title = post.find('h2').text.lower() if post.find('h2') else ''
        title_link_element = post.find('a')
        if not title_link_element or not title_link_element.has_attr('href'): return []
        
        movie_page_url = title_link_element['href']
        movie_response = requests.get(movie_page_url, headers=HEADERS, timeout=10)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        
        for link in movie_soup.find_all('a'):
            link_text = link.text.lower()
            if 'stream' in link_text or 'watch' in link_text:
                lang = "Hindi" if "hindi" in post_title or "dubbed" in post_title else "Original"
                full_url = urljoin(base_url, link.get('href', ''))
                if full_url and ('stream' in full_url or 'vcloud' in full_url):
                     found_links.append({"url": full_url, "source": "SkyMoviesHD", "lang": lang})
                     break # Take the first good link
    except Exception as e:
        print(f"Error scraping SkymoviesHD: {e}")
    return found_links

## --- SECONDARY SCRAPER: Dongobd (Re-added) --- ##
def scrape_dongobd(query):
    """Text-based scraper for dongobd.com."""
    found_links = []
    try:
        base_url = "https://dongobd.com/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        search_response = requests.get(search_url, headers=HEADERS, timeout=15)
        search_soup = BeautifulSoup(search_response.text, 'lxml')

        movie_link_element = search_soup.find('a', class_='lnk-blk')
        if not movie_link_element or not movie_link_element.has_attr('href'): return []
            
        movie_page_url = movie_link_element['href']
        post_title = movie_link_element.get('title', '').lower()
        movie_response = requests.get(movie_page_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        
        iframe = movie_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            lang = "Hindi" if "hindi" in post_title or "dubbed" in post_title else "Original"
            found_links.append({"url": urljoin(base_url, iframe['src']), "source": "DongoBD", "lang": lang})
    except Exception as e:
        print(f"Error scraping Dongobd: {e}")
    return found_links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend v11 (All-Sources Edition) is running!"

@app.route('/search')
def search():
    """Step 1: Search for media. Returns a list of potential matches."""
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured on the server."}), 500

    base_query, _ = parse_query_for_language(query)
    search_url = f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(base_query)}"
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
    """Step 2 (Movies): Gets links from ALL available sources using the hybrid model."""
    original_query = request.args.get('query')
    all_links = []
    
    # --- Run all sources ---
    # 1. Primary robust scraper (ID-based)
    all_links.extend(scrape_vidsrc_to_sources(tmdb_id, 'movie'))
    
    # 2. Secondary text-based scrapers (query-based)
    if original_query:
        all_links.extend(scrape_hdhub4u(original_query))
        all_links.extend(scrape_cinefreak(original_query))
        all_links.extend(scrape_skymovieshd(original_query))
        all_links.extend(scrape_dongobd(original_query))

    # Note: StreamBlasters and 2Embed are often covered by VidSrc.to's servers,
    # so we rely on that primary scraper to avoid redundancy and slow-downs.

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
            
    # De-duplicate results
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    """Step 2 (TV): Get season info for a specific TV show."""
    details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
    details_data = get_tmdb_data(details_url)
    
    if not details_data: return jsonify({"error": "TV show not found."}), 404
    
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

    if not tmdb_id or not season_num:
        return jsonify({"error": "tmdb_id and season are required."}), 400

    season_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    season_data = get_tmdb_data(season_details_url)
    if not season_data or not season_data.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
        
    episode_links_list = []
    for episode in season_data.get('episodes', []):
        ep_num = episode.get('episode_number')
        
        # The robust scraper is best for TV episodes as it's ID-based.
        # Text-based scraping for specific episodes is highly unreliable.
        all_links_for_ep = scrape_vidsrc_to_sources(tmdb_id, 'tv', season_num, ep_num)
        
        episode_links_list.append({
            "episode": ep_num,
            "title": episode.get('name', f"Episode {ep_num}"),
            "links": list({link['url']: link for link in all_links_for_ep}.values())
        })

    return jsonify({"season": season_num, "episodes": episode_links_list})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
