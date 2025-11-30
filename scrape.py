import os
import time
import json
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

def get_username_from_url(url):
    if "@" in url:
        return url.split("@")[1].split("/")[0].split("?")[0]
    return "unknown"

def download_file(url, folder, filename, cookies=None, user_agent=None):
    try:
        print(f"Downloading to {filename}...")
        headers = {
            "User-Agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com"
        }
        
        # Convert playwright cookies to requests cookies
        req_cookies = {}
        if cookies:
            for c in cookies:
                req_cookies[c['name']] = c['value']

        response = requests.get(url, stream=True, headers=headers, cookies=req_cookies)
        
        if response.status_code == 200 or response.status_code == 206:
            filepath = os.path.join(folder, filename)
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(1024*1024):
                    f.write(chunk)
            
            # Check if file is too small (likely an error/placeholder)
            if os.path.getsize(filepath) < 10000:
                print(f"Warning: File {filename} is very small, might be invalid.")
            else:
                print(f"Success: {filepath}")
        else:
            print(f"Failed to download. Status: {response.status_code}")
    except Exception as e:
        print(f"Error downloading: {e}")

def extract_video_url_from_data(page):
    # Try to find the video URL in the page's JSON data
    try:
        data = page.evaluate("""
            () => {
                const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                if (el) return JSON.parse(el.textContent);
                const sigi = document.getElementById('SIGI_STATE');
                if (sigi) return JSON.parse(sigi.textContent);
                return null;
            }
        """)
        
        if data:
            # Navigate the JSON structure to find playAddr
            # Structure varies, but usually under 'webapp.videoDetail.itemInfo.itemStruct.video.playAddr'
            # or similar paths. We'll try to search recursively or check common paths.
            
            # Helper to find key recursively
            def find_key(obj, key):
                if isinstance(obj, dict):
                    if key in obj:
                        return obj[key]
                    for k, v in obj.items():
                        res = find_key(v, key)
                        if res: return res
                elif isinstance(obj, list):
                    for item in obj:
                        res = find_key(item, key)
                        if res: return res
                return None

            play_addr = find_key(data, 'playAddr')
            if play_addr:
                return play_addr
            
            # Fallback: look for 'downloadAddr'
            download_addr = find_key(data, 'downloadAddr')
            if download_addr:
                return download_addr
                
    except Exception as e:
        print(f"Error extracting from JSON: {e}")
    return None

def process_video(context, link, folder, index):
    page = context.new_page()
    video_urls = []
    
    def handle_response(response):
        try:
            if "video/mp4" in response.headers.get("content-type", "") or "/video/tos/" in response.url:
                video_urls.append(response.url)
        except:
            pass

    page.on("response", handle_response)
    
    try:
        print(f"Opening video page: {link}")
        page.goto(link)
        time.sleep(3)
        
        video_url_to_download = None
        
        # Priority 1: JSON Data (often contains the clean, unexpired link)
        json_url = extract_video_url_from_data(page)
        if json_url:
            print("Found video URL via Page JSON data.")
            video_url_to_download = json_url
        
        # Priority 2: Network Interception
        if not video_url_to_download and video_urls:
            video_url_to_download = video_urls[0]
            print("Found video URL via network interception.")
            
        # Priority 3: DOM
        if not video_url_to_download:
            video_src = page.evaluate("document.querySelector('video') ? document.querySelector('video').src : null")
            if video_src:
                video_url_to_download = video_src
                print("Found video URL via DOM.")

        if video_url_to_download:
            filename = f"video_{index}_{int(time.time())}.mp4"
            # Get cookies and UA from context to pass to downloader
            cookies = context.cookies()
            ua = page.evaluate("navigator.userAgent")
            download_file(video_url_to_download, folder, filename, cookies=cookies, user_agent=ua)
        else:
            print(f"Could not find video content for {link}")

    except Exception as e:
        print(f"Error processing video {link}: {e}")
    finally:
        page.close()

def process_photo(context, link, folder, index):
    page = context.new_page()
    try:
        print(f"Opening photo page: {link}")
        page.goto(link)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        
        image_srcs = page.evaluate("""
            () => {
                const images = Array.from(document.querySelectorAll('img'));
                return images
                    .filter(img => img.naturalWidth > 400 && img.naturalHeight > 400)
                    .map(img => img.src);
            }
        """)
        
        image_srcs = list(set(image_srcs))
        print(f"Found {len(image_srcs)} potential images.")

        cookies = context.cookies()
        ua = page.evaluate("navigator.userAgent")

        for j, img_src in enumerate(image_srcs):
            filename = f"image_{index}_{j}_{int(time.time())}.jpg"
            download_file(img_src, folder, filename, cookies=cookies, user_agent=ua)

    except Exception as e:
        print(f"Error processing photo {link}: {e}")
    finally:
        page.close()

def scrape_tiktok(profile_url):
    username = get_username_from_url(profile_url)
    date_str = datetime.now().strftime("%Y%m%d")
    base_folder = f"{username}-{date_str}"
    videos_folder = os.path.join(base_folder, "videos")
    images_folder = os.path.join(base_folder, "images")

    os.makedirs(videos_folder, exist_ok=True)
    os.makedirs(images_folder, exist_ok=True)

    with sync_playwright() as p:
        print("Launching browser...")
        # Use args to try to mimic a real user better
        browser = p.chromium.launch(headless=False, args=["--start-maximized", "--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport=None, # Let it be maximized
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"Navigating to profile: {profile_url}")
        page.goto(profile_url)
        
        print("\n" + "="*50)
        print("ACTION REQUIRED: Please solve the CAPTCHA/Puzzle in the browser window.")
        print("Once the profile page is fully visible and you are ready, press ENTER here.")
        print("="*50 + "\n")
        input()
        
        print("Starting infinite scroll...")
        last_scroll_height = 0
        no_change_count = 0
        
        while True:
            page.mouse.wheel(0, 15000)
            time.sleep(3)
            current_scroll_height = page.evaluate("document.body.scrollHeight")
            if current_scroll_height == last_scroll_height:
                no_change_count += 1
                if no_change_count >= 3:
                    break
            else:
                no_change_count = 0
                print("Scrolling...")
            last_scroll_height = current_scroll_height
        
        # --- EXTRACT LINKS ---
        print("Extracting links...")
        links = page.evaluate("""
            () => {
                const selectors = [
                    '#user-post-item-list a',
                    '[data-e2e="user-post-item-list"] a',
                    'a[href*="/video/"]',
                    'a[href*="/photo/"]'
                ];
                
                let foundLinks = [];
                for (const sel of selectors) {
                    const elements = document.querySelectorAll(sel);
                    if (elements.length > 0) {
                        const hrefs = Array.from(elements).map(a => a.href);
                        foundLinks = foundLinks.concat(hrefs);
                    }
                }
                
                return foundLinks.filter(href => href.includes('/video/') || href.includes('/photo/'));
            }
        """)
        
        unique_links = list(set(links))
        print(f"Found {len(unique_links)} unique links.")
        
        if len(unique_links) == 0:
            print("DEBUG: Dumping page content to debug_page.html")
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
        
        for i, link in enumerate(unique_links):
            print(f"\nProcessing {i+1}/{len(unique_links)}")
            if "/video/" in link:
                process_video(context, link, videos_folder, i)
            elif "/photo/" in link:
                process_photo(context, link, images_folder, i)
        
        print("\nScraping completed!")
        browser.close()

if __name__ == "__main__":
    url = "https://www.tiktok.com/@berlinibrahim"
    scrape_tiktok(url)
