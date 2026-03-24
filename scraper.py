"""
Fortress HK TV Price Tracker
Scrapes TV product names and prices from fortress.com.hk and saves them
to a CSV file with weekly timestamps for price tracking.
"""

import csv
import json
import os
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "https://www.fortress.com.hk"
TV_CATEGORY_URL = f"{BASE_URL}/en/category/television.html"
DATA_DIR = Path("data")
CSV_FILE = DATA_DIR / "tv_prices.csv"
CSV_HEADERS = ["date", "product_name", "product_url", "price_hkd", "original_price_hkd"]


def ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)


def scrape_tv_products() -> list[dict]:
    """Scrape all TV products from Fortress using Playwright."""
    products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-HK",
        )
        page = context.new_page()

        page_num = 1
        while True:
            url = f"{TV_CATEGORY_URL}?page={page_num}" if page_num > 1 else TV_CATEGORY_URL
            print(f"Fetching page {page_num}: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for product cards to load
            page.wait_for_selector(".product-item, .product-card, [data-product-id]", timeout=15000)

            page_products = _extract_products(page)
            if not page_products:
                break

            products.extend(page_products)
            print(f"  Found {len(page_products)} products on page {page_num}")

            # Check if there is a next page
            next_btn = page.query_selector("a.next, .pagination-next, [aria-label='Next page']")
            if not next_btn or not next_btn.is_visible():
                break

            page_num += 1
            time.sleep(1)  # polite delay

        context.close()
        browser.close()

    return products


def _extract_products(page) -> list[dict]:
    """Extract product info from the current page."""
    products = []

    # Try to get product data from the page's JSON-LD or inline JS first
    json_ld = page.evaluate("""() => {
        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
        for (const s of scripts) {
            try {
                const data = JSON.parse(s.textContent);
                if (data['@type'] === 'ItemList') return data;
                if (Array.isArray(data) && data.some(d => d['@type'] === 'Product')) return data;
            } catch {}
        }
        return null;
    }""")

    if json_ld:
        items = json_ld.get("itemListElement", []) if isinstance(json_ld, dict) else json_ld
        for item in items:
            if isinstance(item, dict):
                product = item.get("item", item)
                offers = product.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                products.append({
                    "product_name": product.get("name", "").strip(),
                    "product_url": product.get("url", ""),
                    "price_hkd": offers.get("price", ""),
                    "original_price_hkd": "",
                })
        if products:
            return products

    # Fallback: scrape HTML elements directly
    cards = page.query_selector_all(
        ".product-item, .product-card, [data-product-id], "
        ".ProductCard, .product-listing__item"
    )
    for card in cards:
        name_el = card.query_selector(
            ".product-name, .product-title, h2, h3, "
            "[class*='name'], [class*='title']"
        )
        price_el = card.query_selector(
            ".product-price .current, .selling-price, "
            "[class*='selling'], [class*='current-price'], "
            ".price-box .price"
        )
        original_price_el = card.query_selector(
            ".original-price, .was-price, "
            "[class*='original'], [class*='was']"
        )
        link_el = card.query_selector("a[href]")

        name = name_el.inner_text().strip() if name_el else ""
        price_raw = price_el.inner_text().strip() if price_el else ""
        original_raw = original_price_el.inner_text().strip() if original_price_el else ""
        href = link_el.get_attribute("href") if link_el else ""

        if name and price_raw:
            products.append({
                "product_name": name,
                "product_url": href if href.startswith("http") else f"{BASE_URL}{href}",
                "price_hkd": _clean_price(price_raw),
                "original_price_hkd": _clean_price(original_raw),
            })

    return products


def _clean_price(raw: str) -> str:
    """Strip currency symbols and whitespace, return numeric string."""
    return raw.replace("HK$", "").replace("$", "").replace(",", "").strip()


def save_to_csv(products: list[dict]):
    """Append today's prices to the CSV file."""
    today = date.today().isoformat()
    file_exists = CSV_FILE.exists()

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        for p in products:
            writer.writerow({
                "date": today,
                "product_name": p["product_name"],
                "product_url": p["product_url"],
                "price_hkd": p["price_hkd"],
                "original_price_hkd": p["original_price_hkd"],
            })

    print(f"Saved {len(products)} products to {CSV_FILE}")


def print_summary(products: list[dict]):
    """Print a quick summary to stdout."""
    print(f"\n{'='*60}")
    print(f"Fortress TV Price Snapshot — {date.today().isoformat()}")
    print(f"{'='*60}")
    for p in products[:20]:
        name = p["product_name"][:50]
        price = p["price_hkd"] or "N/A"
        orig = f"  (was {p['original_price_hkd']})" if p["original_price_hkd"] else ""
        print(f"  HK${price:<10}{orig:<20} {name}")
    if len(products) > 20:
        print(f"  ... and {len(products) - 20} more")
    print(f"{'='*60}\n")


def main():
    ensure_data_dir()
    print("Starting Fortress TV price scrape...")
    products = scrape_tv_products()
    if not products:
        print("No products found — check selectors or site structure.")
        return
    save_to_csv(products)
    print_summary(products)


if __name__ == "__main__":
    main()
