import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin

app = Flask(__name__)
CORS(app)

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
    """Source 6: dongobd.com (Restored)"""
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
        
        # Run direct query scrapers first
        skymovies_link = scrape_skymovieshd(query)
        if skymovies_link: all_links.append(skymovies_link)
        
        cinefreak_link = scrape_cinefreak(query)
        if cinefreak_link: all_links.append(cinefreak_link)

        dongobd_link = scrape_dongobd(query)
        if dongobd_link: all_links.append(dongobd_link)

        # Use TMDB to get IDs for the other scrapers
        tmdb_search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
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
