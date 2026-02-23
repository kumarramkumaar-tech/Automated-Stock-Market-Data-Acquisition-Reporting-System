"""
Pre-Market News Scraper — Economic Times Prime
Fetches top 3 pre-market news articles, extracts key figures,
formats as structured Telegram messages with tables.
"""

import os
import re
import json
import time
import pickle
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID_PREMARKET = os.getenv(
    "TELEGRAM_CHAT_ID_PREMARKET", os.getenv("TELEGRAM_CHAT_ID")
)
ET_PRIME_EMAIL = os.getenv("ET_PRIME_EMAIL")
ET_PRIME_PASSWORD = os.getenv("ET_PRIME_PASSWORD")

COOKIE_FILE = "et_prime_cookies.pkl"
ET_MARKETS_NEWS_URL = "https://economictimes.indiatimes.com/markets/stocks/news"
ET_PRIME_URL = "https://economictimes.indiatimes.com/prime"
ET_BASE_URL = "https://economictimes.indiatimes.com"

logger = logging.getLogger("premarket_news")


# ──────────────────────────────────────────────
# Browser helpers
# ──────────────────────────────────────────────
def create_driver(headless=True):
    """Create a Selenium Chrome WebDriver."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def save_cookies(driver, path=COOKIE_FILE):
    """Persist browser cookies to disk."""
    with open(path, "wb") as f:
        pickle.dump(driver.get_cookies(), f)
    logger.info("Cookies saved to %s", path)


def load_cookies(driver, path=COOKIE_FILE):
    """Load previously saved cookies into the driver."""
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
    """
    Open ET Prime in a visible browser so the user can log in manually.
    After login, cookies are saved for future headless runs.
    """
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


# ──────────────────────────────────────────────
# Scraping
# ──────────────────────────────────────────────
def fetch_article_links(driver, count=3):
    """Return up to `count` article (title, url) pairs from ET markets news."""
    driver.get(ET_MARKETS_NEWS_URL)
    time.sleep(4)

    links = []
    seen = set()

    # Strategy 1: story list items
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
                    href
                    and title
                    and len(title) > 15
                    and href.startswith("http")
                    and "/articleshow/" in href
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

    # Strategy 2: fallback — all <a> tags with /articleshow/
    if len(links) < count:
        try:
            all_a = driver.find_elements(By.TAG_NAME, "a")
            for el in all_a:
                href = el.get_attribute("href") or ""
                title = el.text.strip()
                if (
                    href
                    and title
                    and len(title) > 15
                    and "/articleshow/" in href
                    and href not in seen
                ):
                    links.append((title, href))
                    seen.add(href)
                if len(links) >= count:
                    break
        except Exception:
            pass

    return links[:count]


def extract_article_content(driver, url, title):
    """Visit an article page and extract summary + key figures."""
    article = {
        "title": title,
        "url": url,
        "summary": "",
        "figures": [],
    }
    try:
        driver.get(url)
        time.sleep(3)

        # Parse the loaded page with BeautifulSoup (more reliable than Selenium selectors)
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # Extract article text — try multiple selectors
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
            # Fallback: collect all <p> tags
            paragraphs = soup.find_all("p")
            full_text = " ".join(p.get_text(strip=True) for p in paragraphs[:10])

        # Summarise: first 3 sentences
        sentences = re.split(r"(?<=[.!?])\s+", full_text)
        article["summary"] = " ".join(sentences[:3]).strip()
        if len(article["summary"]) > 500:
            article["summary"] = article["summary"][:497] + "..."

        # ── Extract key figures / numbers ──
        # Pattern: look for market indices, percentages, currency values
        figure_patterns = [
            # Index values  e.g. "Sensex 76,450" or "Nifty 23,180.50"
            (
                r"((?:Sensex|Nifty|BSE|NSE|Bank\s*Nifty|SGX\s*Nifty|Dow|Nasdaq|S&P)\s*"
                r"[\w]*\s*(?:rose|fell|gained|lost|at|jumped|slipped|closed|opened)?\s*"
                r"[\d,]+\.?\d*\s*(?:points?|%)?)"
            ),
            # Percentage moves  e.g. "+1.5%", "surged 3.2 per cent"
            (r"([+-]?\d+[.,]?\d*\s*(?:%|per\s*cent|percent|bps|basis\s*points))"),
            # Rupee / Dollar amounts
            (r"((?:Rs\.?|₹|INR|\$|USD)\s*[\d,]+\.?\d*\s*(?:crore|lakh|billion|million|trillion)?)"),
            # Generic large numbers with context
            (r"(\d[\d,]*\.?\d*\s+(?:crore|lakh|billion|million|trillion))"),
        ]

        raw_figures = []
        for pat in figure_patterns:
            raw_figures.extend(re.findall(pat, full_text, re.IGNORECASE))

        # Deduplicate while preserving order
        seen_figs = set()
        for fig in raw_figures:
            cleaned = fig.strip()
            if cleaned and cleaned not in seen_figs:
                article["figures"].append(cleaned)
                seen_figs.add(cleaned)
            if len(article["figures"]) >= 8:
                break

    except Exception as e:
        logger.warning("Failed to extract article %s: %s", url, e)
        article["summary"] = title

    return article


# ──────────────────────────────────────────────
# Formatting
# ──────────────────────────────────────────────
def format_telegram_message(articles):
    """Build a rich HTML Telegram message with tables for numerical data."""
    now = datetime.now()
    date_str = now.strftime("%d-%b-%Y")
    time_str = now.strftime("%I:%M %p")

    lines = [
        f"<b>📰 PRE-MARKET NEWS SUMMARY</b>",
        f"📅 {date_str}  |  ⏰ {time_str}",
        "━" * 30,
        "",
    ]

    for idx, art in enumerate(articles, 1):
        lines.append(f"<b>📌 {idx}. {_escape_html(art['title'])}</b>")
        lines.append("")
        lines.append(_escape_html(art.get("summary", "—")))
        lines.append("")

        # Numbers table
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
    """Create a plain-text table suitable for Telegram <pre> block."""
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
    """Escape HTML special characters for Telegram HTML parse mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ──────────────────────────────────────────────
# Telegram delivery
# ──────────────────────────────────────────────
def send_telegram_html(message, chat_id=None):
    """Send an HTML-formatted message to Telegram (supports channels)."""
    token = TELEGRAM_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID_PREMARKET

    if not token or not cid:
        print("[WARN] Telegram credentials missing (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID_PREMARKET)")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 200:
            logger.info("Telegram message sent to %s", cid)
            return True
        else:
            logger.error("Telegram send failed: %s — %s", resp.status_code, resp.text)
            # If message too long, split and retry
            if resp.status_code == 400 and "message is too long" in resp.text.lower():
                return _send_split_message(message, token, cid)
            return False
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return False


def _send_split_message(message, token, chat_id):
    """Split a long message and send in parts."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    parts = message.split("─" * 30)
    for i, part in enumerate(parts):
        payload = {
            "chat_id": chat_id,
            "text": part.strip() or "—",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            requests.post(url, json=payload, timeout=30)
            time.sleep(0.5)
        except Exception as e:
            logger.error("Split-send part %d failed: %s", i, e)
    return True


# ──────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────
def run_premarket_summary():
    """Fetch → Format → Send pre-market news to Telegram."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("Starting pre-market news fetch at %s", ts)
    print(f"[{ts}] Fetching pre-market news...")

    driver = None
    try:
        # Try headless first (with saved cookies)
        driver = create_driver(headless=True)
        cookie_loaded = load_cookies(driver)

        if not cookie_loaded:
            # No cookies — need interactive login
            driver.quit()
            driver = create_driver(headless=False)
            interactive_login(driver)

        # Fetch articles
        article_links = fetch_article_links(driver, count=3)

        if not article_links:
            msg = "⚠️ No pre-market news articles found today."
            print(msg)
            send_telegram_html(msg)
            return

        # Extract content from each article
        articles = []
        for title, url in article_links:
            art = extract_article_content(driver, url, title)
            articles.append(art)
            print(f"  ✓ {title[:60]}...")

        # Format message
        message = format_telegram_message(articles)

        # Send to Telegram
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
