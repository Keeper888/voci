import hashlib
import json
import logging
import time

import requests

from .db import VociDB

log = logging.getLogger(__name__)

CHARTS_BASE = "https://rss.applemarketingtools.com/api/v2"
LOOKUP_BASE = "https://itunes.apple.com/lookup"

GENRE_IDS = {
    1301: "Arts",
    1321: "Business",
    1303: "Comedy",
    1304: "Education",
    1483: "Fiction",
    1487: "History",
    1512: "Health & Fitness",
    1305: "Kids & Family",
    1502: "Leisure",
    1310: "Music",
    1489: "News",
    1314: "Religion & Spirituality",
    1533: "Science",
    1324: "Society & Culture",
    1545: "Sports",
    1318: "Technology",
    1488: "True Crime",
    1309: "TV & Film",
}

RATE_LIMIT_DELAY = 3.0  # iTunes Lookup is rate-limited (~20/min)


def _make_show_id(itunes_id: str) -> str:
    return hashlib.sha256(f"apple:{itunes_id}".encode()).hexdigest()[:16]


def fetch_charts(genre_id: int = None) -> list[dict]:
    """Fetch top 100 Italian podcasts from Apple Charts."""
    url = f"{CHARTS_BASE}/it/podcasts/top/100/podcasts.json"
    params = {}
    if genre_id:
        params["genre"] = genre_id

    try:
        resp = requests.get(url, params=params, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        return data.get("feed", {}).get("results", [])
    except requests.RequestException as e:
        log.warning(f"Apple Charts request failed (genre {genre_id}): {e}")
        return []


def batch_lookup_feed_urls(itunes_ids: list[str]) -> dict[str, dict]:
    """Batch lookup iTunes IDs to get feed URLs and metadata.
    Returns dict of itunes_id -> {feed_url, name, track_count, artist}
    """
    results = {}
    # iTunes API accepts comma-separated IDs, batch of up to 200
    for i in range(0, len(itunes_ids), 50):
        batch = itunes_ids[i:i + 50]
        ids_str = ",".join(batch)

        try:
            resp = requests.get(
                LOOKUP_BASE,
                params={"id": ids_str, "entity": "podcast"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            log.warning(f"iTunes Lookup failed for batch: {e}")
            time.sleep(RATE_LIMIT_DELAY)
            continue

        for item in data.get("results", []):
            iid = str(item.get("collectionId") or item.get("trackId", ""))
            if iid and item.get("feedUrl"):
                results[iid] = {
                    "feed_url": item["feedUrl"],
                    "name": item.get("collectionName", "Unknown"),
                    "track_count": item.get("trackCount", 0),
                    "artist": item.get("artistName"),
                    "genres": item.get("genres", []),
                }

        log.info(f"  Looked up {len(batch)} IDs, got {len(data.get('results', []))} results")
        time.sleep(RATE_LIMIT_DELAY)

    return results


def discover_all(db: VociDB) -> int:
    """Discover Italian podcasts via Apple Charts + iTunes Lookup."""
    total_new = 0
    all_itunes_ids = set()
    known_urls = db.get_all_feed_urls()

    # Step 1: Fetch charts for all genres
    log.info("Fetching Apple Charts for Italian store (all genres)")

    # Overall top 100 first
    results = fetch_charts()
    for r in results:
        iid = r.get("id")
        if iid:
            all_itunes_ids.add(str(iid))
    log.info(f"  Overall top: {len(results)} podcasts")
    time.sleep(1)

    # Then per-genre
    for genre_id, genre_name in GENRE_IDS.items():
        results = fetch_charts(genre_id)
        for r in results:
            iid = r.get("id")
            if iid:
                all_itunes_ids.add(str(iid))
        log.info(f"  {genre_name}: {len(results)} podcasts")
        time.sleep(1)

    log.info(f"Total unique iTunes IDs from charts: {len(all_itunes_ids)}")

    # Step 2: Batch lookup to get feed URLs
    log.info("Looking up feed URLs via iTunes API...")
    lookup_results = batch_lookup_feed_urls(list(all_itunes_ids))

    # Step 3: Store in database
    for itunes_id, info in lookup_results.items():
        feed_url = info["feed_url"]
        if feed_url in known_urls:
            continue

        show_id = _make_show_id(itunes_id)
        is_new = db.upsert_show(
            show_id=show_id,
            name=info["name"],
            source="apple",
            source_id=itunes_id,
            feed_url=feed_url,
            author=info.get("artist"),
            categories=json.dumps(info.get("genres", [])),
            episode_count=info.get("track_count", 0),
            itunes_id=itunes_id,
        )

        if is_new:
            total_new += 1
            known_urls.add(feed_url)

    log.info(f"Apple Charts: {total_new} new shows with feed URLs")
    db.log_scrape("apple", "charts", shows_found=total_new)
    return total_new
