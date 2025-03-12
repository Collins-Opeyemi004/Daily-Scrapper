import time
import requests
import schedule
import threading
from flask import Flask, jsonify
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

app = Flask(__name__)

WEBHOOK_URL = "https://hook.us2.make.com/8ng1v9fw7x63kfsrw4siix8a7jdyybqi"  # Replace with your webhook URL
leaderboard_data = []

def click_x_icons_and_get_urls(page):
    """
    From the loaded leaderboard page, clicks each player's X icon,
    captures the popup URL (or same‑tab navigation), and returns a list
    of Twitter/X URLs (or "N/A" if not available).
    """
    x_urls = []
    # Wait until the containers are present (15s timeout)
    page.wait_for_selector("div.leaderboard_leaderboardUser__8OZpJ", timeout=15000)
    players_locator = page.locator("div.leaderboard_leaderboardUser__8OZpJ")
    count = players_locator.count()
    
    for i in range(count):
        container = players_locator.nth(i)
        x_icon = container.locator("img[src*='Twitter.webp'], img[src*='twitter.png']")
        
        if x_icon.count() > 0:
            try:
                with page.expect_popup(timeout=5000) as popup_info:
                    x_icon.first.click(force=True)
                popup_page = popup_info.value
                x_url = popup_page.url
                popup_page.close()
                if "twitter.com" in x_url or "x.com" in x_url:
                    x_urls.append(x_url)
                else:
                    x_urls.append("N/A")
            except Exception:
                try:
                    with page.expect_navigation(timeout=5000):
                        x_icon.first.click(force=True)
                    new_url = page.url
                    if "twitter.com" in new_url or "x.com" in new_url:
                        x_urls.append(new_url)
                        page.go_back()
                    else:
                        x_urls.append("N/A")
                except Exception:
                    x_urls.append("N/A")
        else:
            x_urls.append("N/A")
    return x_urls

def scrape_leaderboard():
    global leaderboard_data
    leaderboard_url = "https://kolscan.io/leaderboard"

    # ---- Step 1: Basic data extraction via requests and BeautifulSoup ----
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
    players = soup.select(".leaderboard_leaderboardUser__8OZpJ")
    if not players:
        print("⚠️ No leaderboard data found. The page structure might have changed.")
        return

    partial_data = []
    for player in players:
        try:
            # Extract rank
            classes = player.get("class", [])
            if any("firstPlace" in cls for cls in classes):
                rank = "1"
            elif any("secondPlace" in cls for cls in classes):
                rank = "2"
            elif any("thirdPlace" in cls for cls in classes):
                rank = "3"
            else:
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

    # ---- Step 2: Use Playwright (sync) to click on X icons and capture Twitter/X URLs ----
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        page = browser.new_page()
        try:
            page.goto(leaderboard_url, timeout=15000)
        except Exception as e:
            print(f"❌ Playwright navigation failed: {e}")
            browser.close()
            return

        x_urls = click_x_icons_and_get_urls(page)
        browser.close()

    # ---- Step 3: Combine data from BeautifulSoup and Playwright ----
    leaderboard = []
    for i, p_data in enumerate(partial_data):
        if i < len(x_urls):
            p_data["x_profile_url"] = x_urls[i]
        else:
            p_data["x_profile_url"] = "N/A"
        leaderboard.append(p_data)

    leaderboard_data = leaderboard

    # ---- Step 4: Send data to Make.com webhook ----
    try:
        r = requests.post(WEBHOOK_URL, json={"data": leaderboard}, timeout=10)
        r.raise_for_status()
        print(f"✅ Data sent successfully: {r.status_code}")
    except Exception as e:
        print(f"❌ Failed to send data: {e}")

def scrape_leaderboard_wrapper():
    scrape_leaderboard()

# Schedule the scraper to run every 6 hours
schedule.every(6).hours.do(scrape_leaderboard_wrapper)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)

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
