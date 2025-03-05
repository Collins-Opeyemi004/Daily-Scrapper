import asyncio
import time
import schedule
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

WEBHOOK_URL = "https://hook.us2.make.com/8ng1v9fw7x63kfsrw4siix8a7jdyybqi"  # Replace with your Make.com webhook URL

leaderboard_data = []

async def click_x_icons_and_get_urls(page):
    """
    From the main leaderboard page (already loaded), finds each player's container,
    clicks the X icon (if it exists), captures the popup URL, and returns a list
    of X profile URLs in the same order as the containers.
    """
    x_urls = []
    
    # Wait until all player containers are present
    await page.wait_for_selector("div.leaderboard_leaderboardUser__8OZpJ", timeout=15000)
    players_locator = page.locator("div.leaderboard_leaderboardUser__8OZpJ")
    count = await players_locator.count()
    
    for i in range(count):
        container = players_locator.nth(i)
        x_icon = container.locator("img[src*='Twitter.webp'], img[src*='twitter.png']")
        
        if await x_icon.count() > 0:
            # We expect a popup (new tab) OR a navigation in the same tab
            try:
                async with page.expect_popup() as popup_info:
                    await x_icon.first.click(force=True)
                popup_page = await popup_info.value
                x_url = popup_page.url
                await popup_page.close()
                
                # Verify it's really a Twitter/X URL
                if "twitter.com" in x_url or "x.com" in x_url:
                    x_urls.append(x_url)
                else:
                    x_urls.append("N/A")
                
            except:
                # Fallback if it doesn't open a popup, but navigates the same page
                try:
                    async with page.expect_navigation():
                        await x_icon.first.click(force=True)
                    new_url = page.url
                    if "twitter.com" in new_url or "x.com" in new_url:
                        x_urls.append(new_url)
                        await page.go_back()
                    else:
                        x_urls.append("N/A")
                except:
                    x_urls.append("N/A")
        else:
            x_urls.append("N/A")
    
    return x_urls

async def async_scrape_leaderboard():
    """
    1) Scrapes the leaderboard page (requests + BeautifulSoup) for basic info.
    2) Uses Playwright to open the same leaderboard page and click each X icon,
       capturing the real X (Twitter) profile URL.
    3) Combines both sets of data into one list of dicts.
    """
    global leaderboard_data
    leaderboard_url = "https://kolscan.io/leaderboard"
    
    # ---- First, scrape basic data with requests + BeautifulSoup
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(leaderboard_url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to fetch leaderboard page: {e}")
        return
    
    soup = BeautifulSoup(resp.text, "html.parser")
    players = soup.select(".leaderboard_leaderboardUser__8OZpJ")  # Adjust selector if needed
    if not players:
        print("⚠️ No leaderboard data found. The page structure might have changed.")
        return
    
    # We'll store partial info from BeautifulSoup in a list
    # then fill in the x_profile_url from Playwright
    partial_data = []
    
    for player in players:
        try:
            # Extract rank by checking the container's classes:
            classes = player.get("class", [])
            if any("firstPlace" in cls for cls in classes):
                rank = "1"
            elif any("secondPlace" in cls for cls in classes):
                rank = "2"
            elif any("thirdPlace" in cls for cls in classes):
                rank = "3"
            else:
                # Fallback: try to select an element that may contain the rank.
                # Adjust the selector below if Kolscan shows rank in a child element.
                rank_element = player.select_one(".leaderboard_rank")
                rank = rank_element.text.strip() if rank_element else "N/A"
            
            profile_icon = player.select_one("img")["src"]
            profile_url = player.select_one("a")["href"]
            wallet_address = profile_url.split("/account/")[-1] if "/account/" in profile_url else "N/A"
            name_element = player.select_one("a h1")
            name = name_element.text.strip() if name_element else "Unknown"
            
            stats = player.select(".remove-mobile p")
            sol_number = player.select_one(".leaderboard_totalProfitNum__HzfFO h1:nth-child(1)").text.strip()
            dollar_value = player.select_one(".leaderboard_totalProfitNum__HzfFO h1:nth-child(2)").text.strip()
            
            full_profile_url = f"https://kolscan.io{profile_url}"
            
            partial_data.append({
                "rank": rank,
                "profile_icon": profile_icon,
                "name": name,
                "profile_url": full_profile_url,
                "wallet_address": wallet_address,
                "wins": stats[0].text.strip() if len(stats) > 0 else "0",
                "losses": stats[1].text.strip() if len(stats) > 1 else "0",
                "sol_number": sol_number,
                "dollar_value": dollar_value
            })
        except Exception as e:
            print(f"❌ Error extracting data: {e}")
    
    # ---- Next, open the same leaderboard page in Playwright and click X icons
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--no-sandbox"]
        )
        page = await browser.new_page()
        
        # Go to the leaderboard page
        await page.goto(leaderboard_url, timeout=15000)
        
        # This function clicks each X icon (if present) and returns the discovered URLs
        x_urls = await click_x_icons_and_get_urls(page)
        
        await browser.close()
    
    # x_urls is in the same order as partial_data
    # Combine them
    leaderboard = []
    for i, p_data in enumerate(partial_data):
        p_data["x_profile_url"] = x_urls[i]
        leaderboard.append(p_data)
    
    # Store globally
    leaderboard_data = leaderboard
    
    # Send to Make.com
    try:
        r = requests.post(WEBHOOK_URL, json={"data": leaderboard}, timeout=10)
        r.raise_for_status()
        print(f"✅ Data sent successfully: {r.status_code}")
    except Exception as e:
        print(f"❌ Failed to send data: {e}")

def scrape_leaderboard_wrapper():
    asyncio.run(async_scrape_leaderboard())

# Schedule the scraper to run every 6 hours
schedule.every(6).hours.do(scrape_leaderboard_wrapper)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check the schedule every minute

threading.Thread(target=run_scheduler, daemon=True).start()

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Welcome to your scraping API! Use /scrape to trigger scraping."})

@app.route("/scrape", methods=["GET"])
def manual_scrape():
    scrape_leaderboard_wrapper()
    return jsonify({"message": "Scraping triggered!", "data": leaderboard_data})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
