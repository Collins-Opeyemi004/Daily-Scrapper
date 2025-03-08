import asyncio
import time
import schedule
import threading
import requests
from flask import Flask, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

WEBHOOK_URL = "https://hook.us2.make.com/8ng1v9fw7x63kfsrw4siix8a7jdyybqi"  # Replace with your webhook URL
leaderboard_data = []

async def async_scrape_leaderboard():
    """
    1) Navigates to https://kolscan.io/leaderboard using Playwright.
    2) Extracts each player's data (rank, name, profile icon, wallet address, stats, etc.).
    3) Clicks the X icon to capture the Twitter/X profile URL (via popup or same-tab navigation).
    4) Sends the final data to your Make.com webhook.
    """
    global leaderboard_data
    leaderboard_url = "https://kolscan.io/leaderboard"

    async with async_playwright() as p:
        # Launch headless Chromium
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--no-sandbox"]
        )
        page = await browser.new_page()

        # Navigate to the leaderboard with a 30-second timeout
        try:
            await page.goto(
                leaderboard_url,
                timeout=30000,              # 30s timeout
                wait_until="domcontentloaded"
            )
        except Exception as e:
            print(f"❌ Navigation failed: {e}")
            await browser.close()
            return

        # Wait for the leaderboard containers to appear (up to 15s)
        try:
            await page.wait_for_selector("div.leaderboard_leaderboardUser__8OZpJ", timeout=15000)
        except Exception as e:
            print(f"❌ Selector not found: {e}")
            await browser.close()
            return

        # Locate all player containers
        player_containers = page.locator("div.leaderboard_leaderboardUser__8OZpJ")
        count = await player_containers.count()
        leaderboard = []

        for i in range(count):
            container = player_containers.nth(i)

            # --- Extract basic data ---
            # 1. Rank
            classes = await container.get_attribute("class") or ""
            if "firstPlace" in classes:
                rank = "1"
            elif "secondPlace" in classes:
                rank = "2"
            elif "thirdPlace" in classes:
                rank = "3"
            else:
                try:
                    rank = (await container.locator(".leaderboard_rank").inner_text()).strip()
                except Exception:
                    rank = "N/A"

            # 2. Profile icon
            try:
                profile_icon = await container.locator("img").first.get_attribute("src")
            except Exception:
                profile_icon = "N/A"

            # 3. Profile URL + wallet address
            try:
                profile_url_part = await container.locator("a").first.get_attribute("href")
                if profile_url_part:
                    full_profile_url = f"https://kolscan.io{profile_url_part}"
                    wallet_address = (profile_url_part.split("/account/")[-1]
                                      if "/account/" in profile_url_part else "N/A")
                else:
                    full_profile_url = "N/A"
                    wallet_address = "N/A"
            except Exception:
                full_profile_url = "N/A"
                wallet_address = "N/A"

            # 4. Name
            try:
                name = (await container.locator("a h1").inner_text()).strip()
            except Exception:
                name = "Unknown"

            # 5. Wins & Losses
            try:
                wins = (await container.locator(".remove-mobile p").nth(0).inner_text()
                        if await container.locator(".remove-mobile p").count() > 0 else "0")
            except Exception:
                wins = "0"

            try:
                losses = (await container.locator(".remove-mobile p").nth(1).inner_text()
                          if await container.locator(".remove-mobile p").count() > 1 else "0")
            except Exception:
                losses = "0"

            # 6. Sol number & dollar value
            try:
                sol_number = (await container.locator(
                    ".leaderboard_totalProfitNum__HzfFO h1:nth-child(1)"
                ).inner_text()).strip()
            except Exception:
                sol_number = "N/A"

            try:
                dollar_value = (await container.locator(
                    ".leaderboard_totalProfitNum__HzfFO h1:nth-child(2)"
                ).inner_text()).strip()
            except Exception:
                dollar_value = "N/A"

            # --- Extract the Twitter/X URL by clicking the icon ---
            x_profile_url = "N/A"
            icon_locator = container.locator("img[src*='Twitter.webp'], img[src*='twitter.png']")
            if await icon_locator.count() > 0:
                try:
                    # First attempt: expect a popup
                    async with page.expect_popup() as popup_info:
                        await icon_locator.first.click(force=True)
                    popup_page = await popup_info.value
                    x_url = popup_page.url
                    await popup_page.close()
                    if "twitter.com" in x_url or "x.com" in x_url:
                        x_profile_url = x_url
                except Exception:
                    # Second attempt: maybe it navigates in the same tab
                    try:
                        async with page.expect_navigation():
                            await icon_locator.first.click(force=True)
                        new_url = page.url
                        if "twitter.com" in new_url or "x.com" in new_url:
                            x_profile_url = new_url
                            await page.go_back()
                    except Exception:
                        x_profile_url = "N/A"

            # Combine the data
            player_data = {
                "rank": rank,
                "profile_icon": profile_icon,
                "name": name,
                "profile_url": full_profile_url,
                "wallet_address": wallet_address,
                "wins": wins,
                "losses": losses,
                "sol_number": sol_number,
                "dollar_value": dollar_value,
                "x_profile_url": x_profile_url
            }
            leaderboard.append(player_data)

        # Store data globally
        leaderboard_data = leaderboard

        # Send data to Make.com
        try:
            r = requests.post(WEBHOOK_URL, json={"data": leaderboard}, timeout=10)
            r.raise_for_status()
            print(f"✅ Data sent successfully: {r.status_code}")
        except Exception as e:
            print(f"❌ Failed to send data: {e}")

        await browser.close()

def scrape_leaderboard_wrapper():
    asyncio.run(async_scrape_leaderboard())

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
