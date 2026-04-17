import hashlib
import json
import logging
import time

import requests

from .db import VociDB

log = logging.getLogger(__name__)

BASE_URL = "https://api.podcastindex.org/api/1.0"
RATE_LIMIT_DELAY = 1.0

SEARCH_TERMS = [
    "italia", "italiano", "podcast italiano", "notizie italia",
    "storia italiana", "politica italiana", "sport italia", "calcio",
    "tecnologia", "scienza", "cultura italiana", "intervista",
    "società", "economia italiana", "cronaca", "musica italiana",
    "cinema italiano", "comedy italiano", "cucina italiana",
    "filosofia", "psicologia", "crimini", "ambiente",
]


def _make_auth_headers(api_key: str, api_secret: str) -> dict:
    ts = str(int(time.time()))
    auth_hash = hashlib.sha1(f"{api_key}{api_secret}{ts}".encode()).hexdigest()
    return {
        "User-Agent": "VociCollector/1.0",
        "X-Auth-Key": api_key,
        "X-Auth-Date": ts,
        "Authorization": auth_hash,
    }


def _make_show_id(feed_url: str) -> str:
    return hashlib.sha256(f"podcastindex:{feed_url}".encode()).hexdigest()[:16]


def _get(url: str, api_key: str, api_secret: str, params: dict = None) -> dict | None:
    headers = _make_auth_headers(api_key, api_secret)
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning(f"Request failed: {url} — {e}")
        return None


def _process_feeds(db: VociDB, feeds: list, known_urls: set) -> int:
    new_count = 0
    for feed in feeds:
        feed_url = feed.get("url") or feed.get("originalUrl")
        if not feed_url or feed_url in known_urls:
            continue

        language = (feed.get("language") or "").lower()
        if not language.startswith("it"):
            continue

        show_id = _make_show_id(feed_url)
        categories_raw = feed.get("categories") or {}
        categories = list(categories_raw.values()) if isinstance(categories_raw, dict) else []

        is_new = db.upsert_show(
            show_id=show_id,
            name=feed.get("title", "Unknown"),
            source="podcast_index",
            source_id=str(feed.get("id", "")),
            feed_url=feed_url,
            description=feed.get("description"),
            author=feed.get("author"),
            categories=json.dumps(categories) if categories else None,
            episode_count=feed.get("episodeCount", 0),
            itunes_id=str(feed.get("itunesId", "")) if feed.get("itunesId") else None,
        )

        if is_new:
            new_count += 1
            known_urls.add(feed_url)

    return new_count


def discover_by_search(db: VociDB, api_key: str, api_secret: str) -> int:
    """Search Podcast Index for Italian podcasts."""
    total_new = 0
    known_urls = db.get_all_feed_urls()

    for term in SEARCH_TERMS:
        log.info(f"Searching Podcast Index for: {term}")
        data = _get(
            f"{BASE_URL}/search/byterm",
            api_key, api_secret,
            params={"q": term, "lang": "it", "max": 1000},
        )
        if not data:
            time.sleep(RATE_LIMIT_DELAY)
            continue

        feeds = data.get("feeds", [])
        new = _process_feeds(db, feeds, known_urls)
        total_new += new
        log.info(f"  Found {len(feeds)} feeds, {new} new Italian shows")
        db.log_scrape("podcast_index", "search", term, shows_found=new)
        time.sleep(RATE_LIMIT_DELAY)

    return total_new


def discover_trending(db: VociDB, api_key: str, api_secret: str) -> int:
    """Get trending Italian podcasts."""
    known_urls = db.get_all_feed_urls()

    log.info("Fetching trending Italian podcasts from Podcast Index")
    data = _get(
        f"{BASE_URL}/podcasts/trending",
        api_key, api_secret,
        params={"lang": "it", "max": 100},
    )
    if not data:
        return 0

    feeds = data.get("feeds", [])
    new = _process_feeds(db, feeds, known_urls)
    log.info(f"  Trending: {len(feeds)} feeds, {new} new")
    db.log_scrape("podcast_index", "trending", shows_found=new)
    return new


def discover_recent(db: VociDB, api_key: str, api_secret: str) -> int:
    """Get recently updated Italian feeds."""
    known_urls = db.get_all_feed_urls()
    total_new = 0

    log.info("Fetching recent Italian feeds from Podcast Index")
    data = _get(
        f"{BASE_URL}/recent/feeds",
        api_key, api_secret,
        params={"lang": "it", "max": 1000},
    )
    if not data:
        return 0

    feeds = data.get("feeds", [])
    new = _process_feeds(db, feeds, known_urls)
    total_new += new
    log.info(f"  Recent: {len(feeds)} feeds, {new} new")
    db.log_scrape("podcast_index", "recent", shows_found=new)

    return total_new


def lookup_by_itunes_id(db: VociDB, api_key: str, api_secret: str, itunes_id: str) -> str | None:
    """Look up a podcast by iTunes ID and return its feed URL."""
    data = _get(
        f"{BASE_URL}/podcasts/byitunesid",
        api_key, api_secret,
        params={"id": itunes_id},
    )
    if not data:
        return None

    feed = data.get("feed", {})
    return feed.get("url") or feed.get("originalUrl")


def discover_all(db: VociDB, api_key: str, api_secret: str) -> int:
    """Run all Podcast Index discovery methods."""
    total = 0
    total += discover_by_search(db, api_key, api_secret)
    time.sleep(RATE_LIMIT_DELAY)
    total += discover_trending(db, api_key, api_secret)
    time.sleep(RATE_LIMIT_DELAY)
    total += discover_recent(db, api_key, api_secret)
    log.info(f"Podcast Index total: {total} new Italian shows")
    return total
