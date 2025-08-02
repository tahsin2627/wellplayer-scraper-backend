import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

# --- Configuration & Global Variables ---
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_API_BASE = "https://api.themoviedb.org/3"
STREAMING_API_URL = "https://consumet-api-movies-nine.vercel.app"
API_PROVIDERS = ['flixhq', 'goku', 'dramacool']

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
HEADERS = { 'User-Agent': USER_AGENT, 'Referer': 'https://www.google.com/' }

# --- Helper Functions ---
@lru_cache(maxsize=128)
def get_tmdb_data(url):
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e: print(f"Error fetching TMDB data: {e}"); return None

def find_on_tmdb_by_imdb_id(imdb_id):
    find_url = f"{TMDB_API_BASE}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
    data = get_tmdb_data(find_url)
    if data:
        results = data.get('movie_results', []) + data.get('tv_results', [])
        if results:
            media_type = 'movie' if 'title' in results[0] else 'tv'
            return results[0], media_type
    return None, None

# --- Source Functions ---

def scrape_imdb_search(query):
    results = []
    try:
        url = f"https://www.imdb.com/find/?q={quote_plus(query)}&s=tt&ttype=ft&ref_=fn_ft"
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'lxml')
        for item in soup.select('.ipc-metadata-list-summary-item__c'):
            title_tag = item.select_one('a.ipc-mdem')
            if not title_tag: continue
            title = title_tag.text.strip()
            imdb_id = title_tag['href'].split('/title/')[1].split('/')[0]
            year_tag = item.select_one('.ipc-metadata-list-summary-item__li')
            year = year_tag.text.strip() if year_tag else "N/A"
            results.append({
                "id": imdb_id, "type": "movie", "title": f"{title} (IMDb)",
                "year": year, "poster_path": None
            })
    except Exception as e:
        print(f"Error scraping IMDb search: {e}")
    return results

def get_stream_links_from_api(tmdb_id, media_type, s=None, e=None):
    all_links = []
    media_id_str = f"tv/{tmdb_id}" if media_type == 'tv' else f"movie/{tmdb_id}"
    for provider in API_PROVIDERS:
        try:
            info_url = f"{STREAMING_API_URL}/movies/{provider}/info?id={media_id_str}"
            info_res = requests.get(info_url, timeout=20)
            if info_res.status_code != 200: continue
            info_data = info_res.json()
            episode_id = None
            if media_type == 'movie':
                episode_id = info_data.get('id')
            else:
                target_season = next((s_item for s_item in info_data.get('episodes', []) if str(s_item.get('season')) == str(s)), None)
                if target_season:
                    target_episode = next((e_item for e_item in target_season.get('episodes', []) if str(e_item.get('number')) == str(e)), None)
                    if target_episode: episode_id = target_episode.get('id')
            if not episode_id: continue
            watch_url = f"{STREAMING_API_URL}/movies/{provider}/watch?episodeId={episode_id}&mediaId={media_id_str}"
            watch_res = requests.get(watch_url, timeout=20)
            if watch_res.status_code != 200: continue
            watch_data = watch_res.json()
            for source in watch_data.get('sources', []):
                all_links.append({"url": source['url'], "source": f"{provider.title()} ({source.get('quality', 'auto')})", "lang": "Original"})
            if all_links: break
        except Exception as err:
            print(f"Error with API provider {provider}: {err}")
            continue
    return all_links

def get_fallback_links(imdb_id, media_type, s=None, e=None):
    links = []
    if not imdb_id: return []
    try:
        url = f"https://vidsrc.to/embed/{media_type}/{imdb_id}"
        if media_type == 'tv': url += f"/{s}/{e}"
        links.append({"url": url, "source": "VidSrc.to", "lang": "Backup"})
    except Exception as err: print(f"Error with VidSrc fallback: {err}")
    try:
        url = f"https://www.2embed.cc/embed/{media_type}/{imdb_id}"
        if media_type == 'tv': url += f"&s={s}&e={e}"
        links.append({"url": url, "source": "2Embed", "lang": "Backup"})
    except Exception as err: print(f"Error with 2Embed fallback: {err}")
    return links

def scrape_filmcave(query):
    found_links = []
    try:
        base_url = "https://filmcave.net/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        result_link = soup.select_one('.movies-list .ml-item a')
        if not result_link: return []
        movie_url = result_link['href']
        movie_res = requests.get(movie_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_res.text, 'lxml')
        iframe_src = movie_soup.select_one('#playeriframe')['src']
        if iframe_src:
            lang = "Dubbed" if "hindi" in query.lower() or "dubbed" in query.lower() else "Original"
            found_links.append({"url": iframe_src, "source": "FilmCave", "lang": lang})
    except Exception as e:
        print(f"Error scraping FilmCave: {e}")
    return found_links

def scrape_moviemaze(query):
    found_links = []
    try:
        base_url = "https://moviemaze.cc/"
        search_url = f"{base_url}search/?q={quote_plus(query)}"
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        result_link = soup.select_one('.movie-item a')
        if not result_link: return []
        movie_url = urljoin(base_url, result_link['href'])
        movie_res = requests.get(movie_url, headers=HEADERS, timeout=15)
        movie_soup = BeautifulSoup(movie_res.text, 'lxml')
        iframe_src = movie_soup.select_one('.iframe-container iframe')['src']
        if iframe_src:
            lang = "Dubbed" if "hindi" in query.lower() or "dubbed" in query.lower() else "Original"
            found_links.append({"url": iframe_src, "source": "MovieMaze", "lang": lang})
    except Exception as e:
        print(f"Error scraping MovieMaze: {e}")
    return found_links

# --- API Endpoints ---
@app.route('/')
def index():
    return "WellPlayer Scraper Backend (Definitive Final Edition) is running!"

@app.route('/search')
def search():
    query = request.args.get('query')
    if not query: return jsonify({"error": "A 'query' parameter is required."}), 400
    
    all_results = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_tmdb = executor.submit(get_tmdb_data, f"{TMDB_API_BASE}/search/multi?api_key={TMDB_API_KEY}&query={quote_plus(query)}")
        future_imdb = executor.submit(scrape_imdb_search, query)
        
        tmdb_data = future_tmdb.result()
        if tmdb_data and tmdb_data.get("results"):
            tmdb_results = [
                {"id": item.get("id"), "type": item.get("media_type"), "title": item.get("title") or item.get("name"), "year": (item.get("release_date", "") or item.get("first_air_date", ""))[0:4], "poster_path": item.get("poster_path")}
                for item in tmdb_data.get("results", []) if item.get("media_type") in ["movie", "tv"]
            ]
            all_results.extend(tmdb_results)

        imdb_results = future_imdb.result()
        all_results.extend(imdb_results)

    if not all_results:
        return jsonify({"error": f"Could not find '{query}'."}), 404
    
    final_results = {str(res.get('id')): res for res in all_results}
    return jsonify(list(final_results.values()))

@app.route('/movie/<string:media_id>')
def get_movie_details(media_id):
    original_query = request.args.get('query')
    all_links = []
    
    tmdb_id, imdb_id = (None, media_id) if media_id.startswith('tt') else (int(media_id), None)
    
    if tmdb_id and not imdb_id:
        ids_data = get_tmdb_data(f"{TMDB_API_BASE}/movie/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
        imdb_id = ids_data.get("imdb_id") if ids_data else None

    # --- "Fetch All" Strategy ---
    id_based_scrapers = []
    if tmdb_id:
        id_based_scrapers.append(lambda: get_stream_links_from_api(tmdb_id, 'movie'))
    if imdb_id:
        id_based_scrapers.append(lambda: get_fallback_links(imdb_id, 'imdb', 'movie'))

    text_scrapers = []
    if original_query:
        text_scrapers.append(lambda: scrape_filmcave(original_query))
        text_scrapers.append(lambda: scrape_moviemaze(original_query))

    with ThreadPoolExecutor(max_workers=len(id_based_scrapers) + len(text_scrapers) or 1) as executor:
        futures = [executor.submit(f) for f in id_based_scrapers + text_scrapers]
        for future in futures:
            all_links.extend(future.result())

    if not all_links:
        return jsonify({"error": "No streaming links found for this movie."}), 404
        
    final_links = {link['url']: link for link in all_links}
    return jsonify({"links": list(final_links.values())})

# ... TV Endpoints ...
@app.route('/tv/<int:tmdb_id>')
def get_tv_details(tmdb_id):
    details_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}?api_key={TMDB_API_KEY}")
    if not details_data: return jsonify({"error": "TV show not found."}), 404
    seasons = [
        {"season_number": s.get("season_number"), "name": s.get("name"), "episode_count": s.get("episode_count")}
        for s in details_data.get('seasons', []) if s.get('season_number', 0) > 0
    ]
    return jsonify({"title": details_data.get("name"), "seasons": seasons})

@app.route('/episodes')
def get_episodes():
    tmdb_id, season_num = request.args.get('tmdb_id'), request.args.get('season')
    if not tmdb_id or not season_num: return jsonify({"error": "tmdb_id and season are required."}), 400
    season_details_url = f"{TMDB_API_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    season_data = get_tmdb_data(season_details_url)
    if not season_data or not season_data.get('episodes'):
        return jsonify({"error": "Could not find episodes for this season."}), 404
    episodes_list = [{"episode": ep.get('episode_number'), "title": ep.get('name')} for ep in season_data.get('episodes', [])]
    return jsonify({"season": season_num, "episodes": episodes_list})

@app.route('/episode-links')
def get_episode_links():
    tmdb_id, season_num, ep_num = request.args.get('tmdb_id'), request.args.get('season'), request.args.get('episode')
    if not all([tmdb_id, season_num, ep_num]):
        return jsonify({"error": "tmdb_id, season, and episode are required."}), 400
    
    all_links = get_stream_links_from_api(tmdb_id, 'tv', season_num, ep_num)
    
    if not all_links:
        ids_data = get_tmdb_data(f"{TMDB_API_BASE}/tv/{tmdb_id}/external_ids?api_key={TMDB_API_KEY}")
        imdb_id = ids_data.get("imdb_id") if ids_data else None
        if imdb_id:
            all_links.extend(get_fallback_links(imdb_id, 'imdb', 'tv', season_num, ep_num))

    if not all_links:
        return jsonify({"error": f"No sources found for Episode {ep_num}."}), 404
    
    return jsonify({"links": list({link['url']: link for link in all_links}.values())})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
