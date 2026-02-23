"""
Pre-Market News Scraper — Economic Times
Fetches top 3 pre-market news articles, extracts key figures,
formats as structured Telegram messages with tables.

Standalone project — runs independently from the Quantsapp automation.

Two modes:
  1. requests + BeautifulSoup (default, no browser needed)
  2. Selenium (fallback for premium/JS-heavy pages)
"""

import os
import re
import json
import time
import pickle
import logging
from datetime import datetime

import requests as http_requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from helpers.notify import send_telegram_html

load_dotenv()

# --- Configuration ---
ET_PRIME_EMAIL = os.getenv("ET_PRIME_EMAIL")
ET_PRIME_PASSWORD = os.getenv("ET_PRIME_PASSWORD")

COOKIE_FILE = "et_prime_cookies.pkl"
ET_MARKETS_NEWS_URL = "https://economictimes.indiatimes.com/markets/stocks/news"
ET_PRIME_URL = "https://economictimes.indiatimes.com/prime"
ET_BASE_URL = "https://economictimes.indiatimes.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

logger = logging.getLogger("premarket_news")


# ══════════════════════════════════════════════
#  MODE 1 — requests + BeautifulSoup (default)
# ══════════════════════════════════════════════
def fetch_article_links_requests(count=3):
    """Fetch article links using plain HTTP requests (no browser)."""
    try:
        resp = http_requests.get(ET_MARKETS_NEWS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Failed to fetch news page: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    links = []
    seen = set()

    # Find all <a> tags with article links
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        title = a_tag.get_text(strip=True)

        # Normalise relative URLs
        if href.startswith("/"):
            href = ET_BASE_URL + href

        if (
            title
            and len(title) > 15
            and "/articleshow/" in href
            and href not in seen
        ):
            links.append((title, href))
            seen.add(href)
        if len(links) >= count:
            break

    return links[:count]


def extract_article_content_requests(url, title):
    """Extract article summary + key figures using plain HTTP requests."""
    article = {
        "title": title,
        "url": url,
        "summary": "",
        "figures": [],
    }
    try:
        resp = http_requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Extract article text
        body_selectors = [
            "div.artText",
            "div.article_content",
            "div.prime_content",
            "div.Normal",
            "div.artSyn",
            "article",
            "div[data-article]",
        ]
        full_text = ""
        for sel in body_selectors:
            elem = soup.select_one(sel)
            if elem and len(elem.get_text(strip=True)) > 50:
                full_text = elem.get_text(separator=" ", strip=True)
                break

        if not full_text:
            paragraphs = soup.find_all("p")
            full_text = " ".join(p.get_text(strip=True) for p in paragraphs[:10])

        # Summary: first 3 sentences
        sentences = re.split(r"(?<=[.!?])\s+", full_text)
        article["summary"] = " ".join(sentences[:3]).strip()
        if len(article["summary"]) > 500:
            article["summary"] = article["summary"][:497] + "..."

        # ── Extract key figures / numbers ──
        article["figures"] = _extract_figures(full_text)

    except Exception as e:
        logger.warning("Failed to extract article %s: %s", url, e)
        article["summary"] = title

    return article


# ══════════════════════════════════════════════
#  MODE 2 — Selenium (fallback)
# ══════════════════════════════════════════════
def _selenium_available():
    """Check if Selenium + Chrome are available."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.quit()
        return True
    except Exception:
        return False


def create_driver(headless=True):
    """Create a Selenium Chrome WebDriver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def save_cookies(driver, path=COOKIE_FILE):
    with open(path, "wb") as f:
        pickle.dump(driver.get_cookies(), f)
    logger.info("Cookies saved to %s", path)


def load_cookies(driver, path=COOKIE_FILE):
    if not os.path.exists(path):
        return False
    driver.get(ET_BASE_URL)
    time.sleep(2)
    with open(path, "rb") as f:
        cookies = pickle.load(f)
    for cookie in cookies:
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass
    driver.refresh()
    time.sleep(2)
    logger.info("Cookies loaded from %s", path)
    return True


def interactive_login(driver):
    print("\n┌─────────────────────────────────────────────────┐")
    print("│  ET Prime — Manual Login Required (first time)  │")
    print("├─────────────────────────────────────────────────┤")
    print("│  A browser window will open.                    │")
    print("│  1. Log in to your ET Prime account.            │")
    print("│  2. Come back here and press ENTER.             │")
    print("└─────────────────────────────────────────────────┘\n")
    driver.get(ET_PRIME_URL)
    input("Press ENTER after you have logged in to ET Prime...")
    save_cookies(driver)
    print("[OK] Login session saved. Future runs will use saved cookies.\n")


def fetch_article_links_selenium(driver, count=3):
    from selenium.webdriver.common.by import By

    driver.get(ET_MARKETS_NEWS_URL)
    time.sleep(4)

    links = []
    seen = set()

    selectors = [
        "div.eachStory h3 a",
        "div.clr.flt.topnews a",
        "ul.newsList li a",
        "div.story_list h4 a",
        "div.eachStory a.wrapLines",
        "div.cardHolder a",
    ]

    for sel in selectors:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elems:
                href = el.get_attribute("href") or ""
                title = el.text.strip()
                if (
                    href and title and len(title) > 15
                    and href.startswith("http") and "/articleshow/" in href
                    and href not in seen
                ):
                    links.append((title, href))
                    seen.add(href)
                if len(links) >= count:
                    break
        except Exception:
            continue
        if len(links) >= count:
            break

    if len(links) < count:
        try:
            all_a = driver.find_elements(By.TAG_NAME, "a")
            for el in all_a:
                href = el.get_attribute("href") or ""
                title = el.text.strip()
                if (
                    href and title and len(title) > 15
                    and "/articleshow/" in href and href not in seen
                ):
                    links.append((title, href))
                    seen.add(href)
                if len(links) >= count:
                    break
        except Exception:
            pass

    return links[:count]


def extract_article_content_selenium(driver, url, title):
    article = {"title": title, "url": url, "summary": "", "figures": []}
    try:
        driver.get(url)
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "lxml")

        body_selectors = [
            "div.artText", "div.article_content", "div.prime_content",
            "div.Normal", "div.artSyn", "article", "div[data-article]",
        ]
        full_text = ""
        for sel in body_selectors:
            elem = soup.select_one(sel)
            if elem and len(elem.get_text(strip=True)) > 50:
                full_text = elem.get_text(separator=" ", strip=True)
                break

        if not full_text:
            paragraphs = soup.find_all("p")
            full_text = " ".join(p.get_text(strip=True) for p in paragraphs[:10])

        sentences = re.split(r"(?<=[.!?])\s+", full_text)
        article["summary"] = " ".join(sentences[:3]).strip()
        if len(article["summary"]) > 500:
            article["summary"] = article["summary"][:497] + "..."

        article["figures"] = _extract_figures(full_text)

    except Exception as e:
        logger.warning("Failed to extract article %s: %s", url, e)
        article["summary"] = title

    return article


# ══════════════════════════════════════════════
#  Shared helpers
# ══════════════════════════════════════════════
def _extract_figures(full_text):
    """Pull key financial numbers from article text."""
    figure_patterns = [
        (
            r"((?:Sensex|Nifty|BSE|NSE|Bank\s*Nifty|SGX\s*Nifty|Dow|Nasdaq|S&P)\s*"
            r"[\w]*\s*(?:rose|fell|gained|lost|at|jumped|slipped|closed|opened)?\s*"
            r"[\d,]+\.?\d*\s*(?:points?|%)?)"
        ),
        (r"([+-]?\d+[.,]?\d*\s*(?:%|per\s*cent|percent|bps|basis\s*points))"),
        (r"((?:Rs\.?|₹|INR|\$|USD)\s*[\d,]+\.?\d*\s*(?:crore|lakh|billion|million|trillion)?)"),
        (r"(\d[\d,]*\.?\d*\s+(?:crore|lakh|billion|million|trillion))"),
    ]

    raw_figures = []
    for pat in figure_patterns:
        raw_figures.extend(re.findall(pat, full_text, re.IGNORECASE))

    figures = []
    seen_figs = set()
    for fig in raw_figures:
        cleaned = fig.strip()
        if cleaned and cleaned not in seen_figs:
            figures.append(cleaned)
            seen_figs.add(cleaned)
        if len(figures) >= 8:
            break
    return figures


# ══════════════════════════════════════════════
#  Formatting
# ══════════════════════════════════════════════
def format_telegram_message(articles):
    """Build a rich HTML Telegram message with tables for numerical data."""
    now = datetime.now()
    date_str = now.strftime("%d-%b-%Y")
    time_str = now.strftime("%I:%M %p")

    lines = [
        "<b>📰 PRE-MARKET NEWS SUMMARY</b>",
        f"📅 {date_str}  |  ⏰ {time_str}",
        "━" * 30,
        "",
    ]

    for idx, art in enumerate(articles, 1):
        lines.append(f"<b>📌 {idx}. {_escape_html(art['title'])}</b>")
        lines.append("")
        lines.append(_escape_html(art.get("summary", "—")))
        lines.append("")

        if art.get("figures"):
            table_lines = _build_table("Key Figures", art["figures"])
            lines.append("<pre>")
            lines.extend(table_lines)
            lines.append("</pre>")
            lines.append("")

        lines.append(f'🔗 <a href="{art["url"]}">Read full article</a>')
        lines.append("─" * 30)
        lines.append("")

    lines.append("<i>Source: Economic Times</i>")
    lines.append(f"<i>Auto-generated at {time_str}</i>")

    return "\n".join(lines)


def _build_table(header, items):
    width = max(len(str(it)) for it in items) + 2
    width = max(width, len(header) + 2)
    border = "─" * (width + 2)
    rows = [
        f"┌{border}┐",
        f"│ {header:<{width}} │",
        f"├{border}┤",
    ]
    for item in items:
        rows.append(f"│ {str(item):<{width}} │")
    rows.append(f"└{border}┘")
    return rows


def _escape_html(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ══════════════════════════════════════════════
#  Main entry point
# ══════════════════════════════════════════════
def run_premarket_summary():
    """Fetch → Format → Send pre-market news to Telegram."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("Starting pre-market news fetch at %s", ts)
    print(f"[{ts}] Fetching pre-market news...")

    # ── Try requests-based scraping first (fast, no browser) ──
    print("  Using requests mode (no browser needed)...")
    article_links = fetch_article_links_requests(count=3)

    if article_links:
        articles = []
        for title, url in article_links:
            art = extract_article_content_requests(url, title)
            articles.append(art)
            print(f"  ✓ {title[:60]}...")

        message = format_telegram_message(articles)
        success = send_telegram_html(message)
        status = "sent" if success else "FAILED to send"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Pre-market summary {status} ({len(articles)} articles)")
        return

    # ── Fallback: Selenium (for JS-heavy / premium pages) ──
    print("  Requests mode found no articles. Trying Selenium fallback...")
    driver = None
    try:
        driver = create_driver(headless=True)
        cookie_loaded = load_cookies(driver)

        if not cookie_loaded:
            driver.quit()
            driver = create_driver(headless=False)
            interactive_login(driver)

        article_links = fetch_article_links_selenium(driver, count=3)

        if not article_links:
            msg = "⚠️ No pre-market news articles found today."
            print(msg)
            send_telegram_html(msg)
            return

        articles = []
        for title, url in article_links:
            art = extract_article_content_selenium(driver, url, title)
            articles.append(art)
            print(f"  ✓ {title[:60]}...")

        message = format_telegram_message(articles)
        success = send_telegram_html(message)
        status = "sent" if success else "FAILED to send"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Pre-market summary {status} ({len(articles)} articles)")

    except Exception as e:
        err = f"❌ Pre-market news error: {e}"
        logger.error(err, exc_info=True)
        print(err)
        try:
            send_telegram_html(err)
        except Exception:
            pass
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    run_premarket_summary()
