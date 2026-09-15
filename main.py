"""
GDMO (Digimon Master Online) Omegamon server — Teras price checker.

Scrapes the G2G offer-group page for your server/currency and posts
a sorted price list to a Discord channel via webhook.

Run manually:
    DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python main.py

In GitHub Actions, DISCORD_WEBHOOK_URL is pulled from a repo secret
(see README.md).
"""

import asyncio
import os
from datetime import datetime, timezone

import requests
from playwright.async_api import async_playwright

G2G_URL = os.environ.get(
    "G2G_URL",
    "https://www.g2g.com/categories/digimon-master-online-global-currency/"
    "offer/group?fa=lgc_14520_server%3Algc_14520_server_25332&sort=lowest_price",
)
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# ---------------------------------------------------------------------------
# SELECTORS
# G2G renders offers with JavaScript, so these CSS selectors are best-guess
# starting points and will very likely need a small tweak once you inspect
# the real page in your browser. See README.md "Step 4: find the real
# selectors" for exactly how to do that (takes ~5 minutes).
#
# Each entry is a comma-separated list of fallback selectors — the script
# tries them in order until one matches.
# ---------------------------------------------------------------------------
OFFER_ROW_SELECTOR = "[data-testid='offer-row'], .offer-list-row, .js-offer, tr.offer"
SELLER_NAME_SELECTOR = "[data-testid='seller-username'], .seller-name, .seller-username"
PRICE_SELECTOR = "[data-testid='offer-price'], .offer-price, .price"
STOCK_SELECTOR = "[data-testid='offer-stock'], .stock, .offer-stock, .delivery-time"


async def scrape_offers():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        )
        await page.goto(G2G_URL, wait_until="networkidle", timeout=60000)

        try:
            await page.wait_for_selector(OFFER_ROW_SELECTOR, timeout=15000)
        except Exception:
            # Couldn't find offer rows — save evidence so we can fix the
            # selectors instead of failing silently every hour.
            await page.screenshot(path="debug_page.png", full_page=True)
            html = await page.content()
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            await browser.close()
            raise RuntimeError(
                "Could not find offer rows on the page with the current "
                "selectors. Saved debug_page.png / debug_page.html as "
                "workflow artifacts — see README.md Step 4 to update "
                "OFFER_ROW_SELECTOR and friends in main.py."
            )

        rows = await page.query_selector_all(OFFER_ROW_SELECTOR)

        offers = []
        for row in rows:
            seller_el = await row.query_selector(SELLER_NAME_SELECTOR)
            price_el = await row.query_selector(PRICE_SELECTOR)
            stock_el = await row.query_selector(STOCK_SELECTOR)

            seller = (await seller_el.inner_text()).strip() if seller_el else "Unknown seller"
            price_raw = (await price_el.inner_text()).strip() if price_el else None
            stock = (await stock_el.inner_text()).strip() if stock_el else None

            if price_raw:
                offers.append({"seller": seller, "price_raw": price_raw, "stock": stock})

        await browser.close()
        return offers


def _price_value(price_raw: str) -> float:
    """Pull a sortable float out of a price string like '$0.0123' or '0.0123 USD'."""
    cleaned = "".join(ch for ch in price_raw if ch.isdigit() or ch == ".")
    try:
        return float(cleaned)
    except ValueError:
        return float("inf")


def build_embed(offers):
    if not offers:
        return {
            "title": "GDMO Omegamon — Teras Prices",
            "description": "No offers found this run. Selectors may need updating — check the workflow's debug artifacts.",
            "color": 0xE74C3C,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    offers_sorted = sorted(offers, key=lambda o: _price_value(o["price_raw"]))
    top = offers_sorted[:10]

    lines = []
    for o in top:
        stock_txt = f" · {o['stock']}" if o.get("stock") else ""
        lines.append(f"**{o['price_raw']}** — {o['seller']}{stock_txt}")

    return {
        "title": "GDMO Omegamon — Teras Prices (lowest first)",
        "description": "\n".join(lines),
        "color": 0x2ECC71,
        "footer": {"text": f"{len(offers)} sellers found · updates hourly"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def post_to_discord(embed):
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)
    resp.raise_for_status()


async def main():
    offers = await scrape_offers()
    embed = build_embed(offers)
    post_to_discord(embed)
    print(f"Posted {len(offers)} offers to Discord.")


if __name__ == "__main__":
    asyncio.run(main())
