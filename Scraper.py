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
    """Extracts X (Twitter) profile links by clicking icons."""
    x_urls = []
    page.wait_for_selector("div.leaderboard_leaderboardUser__8OZpJ", timeout=10000)
    players_locator = page.locator("div.leaderboard_leaderboardUser__8OZpJ")
    count = players_locator.count()

    for i in range(count):
        container = players_locator.nth(i)
        x_icon = container.locator("img[src*='Twitter.webp'], img[src*='twitter.png']")

        if x_icon.count() > 0:
            try:
                with page.expect_popup(timeout=3000) as popup_info:
                    x_icon.first.click(force=True)
                popup_page = popup_info.value
                x_url = popup_page.url
                popup_page.close()
                x_urls.append(x_url if "twitter.com" in x_url or "x.com" in x_url else "N/A")
            except:
                try:
                    with page.expect_navigation(timeout=3000):
                        x_icon.first.click(force=True)
                    new_url = page.url
                    x_urls.append(new_url if "twitter.com" in new_url or "x.com" in new_url else "N/A")
                    page.go_back()
                except:
                    x_urls.append("N/A")
        else:
            x_urls.append("N/A")

    return x_urls


def scrape_leaderboard():
    """Scrapes leaderboard data and sends it to Make.com webhook."""
    global leaderboard_data
    leaderboard_url = "https://kolscan.io/leaderboard"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
    try:
        resp = requests.get(leaderboard_url, headers=headers, timeout=8)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to fetch leaderboard page: {e}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    players = soup.select(".leaderboard_leaderboardUser__8OZpJ")
    if not players:
        print("⚠️ No leaderboard data found.")
        return

    partial_data = []
    for player in players:
        try:
            classes = player.get("class", [])
            rank = "1" if any("firstPlace" in cls for cls in classes) else \
                   "2" if any("secondPlace" in cls for cls in classes) else \
                   "3" if any("thirdPlace" in cls for cls in classes) else \
                   player.select_one(".leaderboard_rank").text.strip() if player.select_one(".leaderboard_rank") else "N/A"

            profile_icon = player.select_one("img")["src"]
            profile_url = player.select_one("a")["href"]
            wallet_address = profile_url.split("/account/")[-1] if "/account/" in profile_url else "N/A"
            name = player.select_one("a h1").text.strip() if player.select_one("a h1") else "Unknown"

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

    # Get X (Twitter) profiles using Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        page = browser.new_page()
        try:
            page.goto(leaderboard_url, timeout=10000, wait_until="domcontentloaded")
            x_urls = click_x_icons_and_get_urls(page)
        except Exception as e:
            print(f"❌ Playwright navigation failed: {e}")
            x_urls = ["N/A"] * len(partial_data)
        finally:
            browser.close()

    # Merge data
    leaderboard = []
    for i, p_data in enumerate(partial_data):
        p_data["x_profile_url"] = x_urls[i] if i < len(x_urls) else "N/A"
        leaderboard.append(p_data)

    leaderboard_data = leaderboard

    # Send to Make.com webhook
    try:
        r = requests.post(WEBHOOK_URL, json={"data": leaderboard}, timeout=8)
        r.raise_for_status()
        print(f"✅ Data sent successfully: {r.status_code}")
    except Exception as e:
        print(f"❌ Failed to send data: {e}")


def scrape_leaderboard_wrapper():
    """Wrapper function to run scraper."""
    scrape_leaderboard()


# Schedule scraper every 6 hours
schedule.every(6).hours.do(scrape_leaderboard_wrapper)


def run_scheduler():
    """Background scheduler thread."""
    while True:
        schedule.run_pending()
        time.sleep(30)


threading.Thread(target=run_scheduler, daemon=True).start()


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Welcome to your scraping API! Use /scrape to trigger scraping."})


@app.route("/scrape", methods=["GET"])
def manual_scrape():
    """Trigger scraping and return JSON output."""
    scrape_leaderboard_wrapper()  # Run scraper before returning data
    return jsonify({"message": "Scraping completed!", "data": leaderboard_data})  # Returns scraped data


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
