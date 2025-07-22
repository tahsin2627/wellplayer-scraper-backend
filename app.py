import os
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from urllib.parse import quote_plus, urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

app = Flask(__name__)
CORS(app)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

# --- Selenium WebDriver Setup ---
def get_driver():
    """Configures and returns a Selenium Chrome WebDriver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    # This user agent helps to avoid being detected as a bot
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

# --- "God-Level" Scraper for Cinefreak using Selenium ---
def scrape_cinefreak_selenium(query):
    """Source 1: cinefreak.net (Using Selenium to bypass security)"""
    driver = get_driver()
    try:
        base_url = "https://cinefreak.net/"
        search_url = f"{base_url}?s={quote_plus(query)}"
        driver.get(search_url)

        # Wait for the search results to load and find the first link
        wait = WebDriverWait(driver, 20) # Increased timeout for reliability
        movie_link_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.post-image-container")))
        movie_page_url = movie_link_element.get_attribute('href')

        if not movie_page_url:
            return None

        # Go to the movie's page
        driver.get(movie_page_url)
        
        # Find the iframe with the video player
        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        iframe_src = iframe.get_attribute('src')
        
        return urljoin(base_url, iframe_src)

    except Exception as e:
        print(f"Error scraping Cinefreak with Selenium: {e}")
        return None
    finally:
        driver.quit()

# --- Your other simple scrapers remain here ---
def get_vidsrc_links(imdb_id, media_type):
    links = []
    if media_type == 'movie':
        links.append(f"https://vidsrc.to/embed/movie/{imdb_id}")
    elif media_type == 'tv':
        links.append(f"https://vidsrc.to/embed/tv/{imdb_id}/1-1")
    return links


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
        
        # Run our new powerful scraper first
        cinefreak_link = scrape_cinefreak_selenium(query)
        if cinefreak_link:
            all_links.append(cinefreak_link)

        # Use TMDB to get IDs for the other, simpler scrapers
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

        if not all_links:
            return jsonify({"error": "Could not find any streaming links."}), 404
            
        return jsonify({ "title": title, "links": list(set(all_links)) })
        
    except Exception as e:
        print(f"An error occurred in /search: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/')
def index():
    return "WellPlayer Scraper Backend is running!"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
