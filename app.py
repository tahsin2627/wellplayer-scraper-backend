import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin

app = Flask(__name__)
CORS(app)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

# --- All of your existing scraper functions are here, UNTOUCHED ---

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

def scrape_skymovieshd(query):
    """Source 4: skymovieshd.land"""
    base_url = "https://skymovieshd.land/"
    try:
        search_url = f"{base_url}?s={quote_plus(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        search_response = requests.get(search_url, headers=headers, timeout=10)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        post_content = search_soup.find('div', class_='post-content')
        if not post_content: return None
        title_link_element = post_content.find('a')
        if not title_link_element or not title_link_element.has_attr('href'): return None
        movie_page_url = title_link_element['href']
        movie_response = requests.get(movie_page_url, headers=headers, timeout=10)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        found_links = []
        for link in movie_soup.find_all('a'):
            link_text = link.text.lower()
            link_href = link.get('href', '').lower()
            if 'stream' in link_text or 'download' in link_text or 'watch' in link_text:
                full_url = urljoin(base_url, link_href)
                found_links.append(full_url)
        return found_links[0] if found_links else None
    except Exception as e:
        print(f"Error scraping SkymoviesHD: {e}")
        return None

def scrape_cinefreak(query):
    """Source 5: cinefreak.net"""
    base_url = "https://cinefreak.net/"
    try:
        search_url = f"{base_url}?s={quote_plus(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        search_response = requests.get(search_url, headers=headers, timeout=15)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        movie_link_element = search_soup.find('a', class_='post-image-container')
        if not movie_link_element or not movie_link_element.has_attr('href'): return None
        movie_page_url = movie_link_element['href']
        movie_response = requests.get(movie_page_url, headers=headers, timeout=15)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        iframe = movie_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            return urljoin(base_url, iframe['src'])
        return None
    except Exception as e:
        print(f"Error scraping Cinefreak: {e}")
        return None

def scrape_dongobd(query):
    """Source 6: dongobd.com"""
    base_url = "https://dongobd.com/"
    try:
        search_url = f"{base_url}?s={quote_plus(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        search_response = requests.get(search_url, headers=headers, timeout=15)
        search_soup = BeautifulSoup(search_response.text, 'lxml')
        movie_link_element = search_soup.find('a', class_='lnk-blk')
        if not movie_link_element or not movie_link_element.has_attr('href'):
            return None
        movie_page_url = movie_link_element['href']
        movie_response = requests.get(movie_page_url, headers=headers, timeout=15)
        movie_soup = BeautifulSoup(movie_response.text, 'lxml')
        iframe = movie_soup.find('iframe')
        if iframe and iframe.has_attr('src'):
            return urljoin(base_url, iframe['src'])
        return None
    except Exception as e:
        print(f"Error scraping Dongobd: {e}")
        return None

# --- UPGRADED Main API Endpoint ---
@app.route('/search')
def search():
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "A 'query' parameter is required."}), 400
    
    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY is not configured on the server."}), 500

    try:
        # --- Step 1: Search TMDB to get ID and media type ---
        tmdb_search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
        tmdb_response = requests.get(tmdb_search_url)
        tmdb_data = tmdb_response.json()

        if not tmdb_data.get("results"):
            return jsonify({"error": f"Could not find '{query}'."}), 404
        
        first_result = tmdb_data["results"][0]
        media_type = first_result.get("media_type")
        tmdb_id = first_result.get("id")
        title = first_result.get("name") or first_result.get("title")

        # --- Step 2: Handle based on media type ---
        if media_type == 'movie':
            # If it's a movie, scrape for links directly
            details_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
            details_response = requests.get(details_url)
            details_data = details_response.json()
            imdb_id = details_data.get("imdb_id")

            all_links = []
            if imdb_id:
                all_links.extend(get_vidsrc_links(imdb_id, 'movie'))
                link_2embed = get_2embed_link(imdb_id, 'movie')
                if link_2embed: all_links.append(link_2embed)
            
            # You can add more movie-specific direct scrapers here if you want
            # skymovies_link = scrape_skymovieshd(query)
            # if skymovies_link: all_links.append(skymovies_link)

            if not all_links:
                return jsonify({"error": "No streaming links found for this movie."}), 404
            
            return jsonify({ "type": "movie", "title": title, "links": list(set(all_links)) })

        elif media_type == 'tv':
            # If it's a TV series, get season details
            details_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
            details_response = requests.get(details_url)
            details_data = details_response.json()
            
            seasons = details_data.get('seasons', [])
            # Filter out "Specials" seasons which are often season 0
            season_numbers = [s['season_number'] for s in seasons if s.get('season_number', 0) > 0]
            
            return jsonify({
                "type": "tv",
                "title": title,
                "tmdb_id": tmdb_id,
                "seasons": season_numbers
            })
        
        else:
            return jsonify({"error": "Unsupported media type found."}), 400
        
    except Exception as e:
        print(f"An error occurred in /search: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

# --- NEW Endpoint for fetching episodes ---
@app.route('/episodes')
def get_episodes():
    tmdb_id = request.args.get('tmdb_id')
    season_num = request.args.get('season')
    if not tmdb_id or not season_num:
        return jsonify({"error": "tmdb_id and season are required."}), 400

    try:
        # Step 1: Get external IMDb ID for the series
        external_ids_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}"
        ids_response = requests.get(external_ids_url)
        ids_data = ids_response.json()
        imdb_id = ids_data.get("imdb_id")

        if not imdb_id:
            return jsonify({"error": "Could not find IMDb ID for this series."}), 404

        # Step 2: Get details for the specific season to find out how many episodes it has
        season_details_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
        season_response = requests.get(season_details_url)
        season_data = season_response.json()
        episodes = season_data.get('episodes', [])
        
        episode_links = []
        for episode in episodes:
            ep_num = episode.get('episode_number')
            if ep_num:
                # Construct links for each episode using our reliable sources
                links = get_vidsrc_links(imdb_id, 'tv', season_num, ep_num)
                link_2embed = get_2embed_link(imdb_id, 'tv', season_num, ep_num)
                if link_2embed:
                    links.append(link_2embed)
                
                episode_links.append({
                    "episode": ep_num,
                    "title": episode.get('name', f"Episode {ep_num}"),
                    "links": links
                })

        return jsonify({"season": season_num, "episodes": episode_links})

    except Exception as e:
        print(f"An error occurred in /episodes: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500


@app.route('/')
def index():
    return "WellPlayer Scraper Backend is running!"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
