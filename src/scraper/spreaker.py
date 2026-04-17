import hashlib
import json
import logging
import time

import requests

from .db import VociDB

log = logging.getLogger(__name__)

BASE_URL = "https://api.spreaker.com/v2"

CATEGORY_IDS = {
    92: "Arts", 99: "Business", 106: "Comedy", 110: "Education",
    115: "Fiction", 120: "History", 121: "Health", 128: "Kids",
    133: "Leisure", 142: "Music", 146: "News", 154: "Religion",
    162: "Science", 172: "Society", 178: "Sports", 194: "Technology",
    195: "True Crime", 196: "TV",
}

ITALIAN_KEYWORDS = [
    "italia", "italiano", "notizie", "storia", "cronaca", "politica",
    "sport", "calcio", "tecnologia", "scienza", "cultura", "intervista",
    "dibattito", "podcast italiano", "società", "economia", "salute",
    "musica italiana", "cinema", "comedy", "umorismo", "cucina",
    "viaggi", "libri", "filosofia", "psicologia", "crimini",
    "misteri", "fantascienza", "ambiente", "lavoro", "finanza",
]

RATE_LIMIT_DELAY = 1.0  # seconds between requests


def _make_show_id(source_id: str) -> str:
    return hashlib.sha256(f"spreaker:{source_id}".encode()).hexdigest()[:16]


def _make_episode_id(audio_url: str) -> str:
    return hashlib.sha256(audio_url.encode()).hexdigest()[:16]


def _get(url: str, params: dict = None) -> dict | None:
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning(f"Request failed: {url} — {e}")
        return None


def _fetch_show_detail(source_id: str) -> dict | None:
    """Fetch full show detail (includes language field)."""
    data = _get(f"{BASE_URL}/shows/{source_id}")
    if not data:
        return None
    return data.get("response", {}).get("show", {})


def _is_italian(show_data: dict) -> bool:
    lang = (show_data.get("language") or "").lower()
    if lang in ("it", "ita", "italian", "italiano"):
        return True
    title = (show_data.get("title") or "").lower()
    desc = (show_data.get("description") or "").lower()
    italian_signals = ["italiano", "italiana", "italiani", "italia", "puntata", "episodio"]
    return any(s in title or s in desc for s in italian_signals)


def _multi_speaker_score(show_data: dict) -> float:
    """Heuristic score for multi-speaker likelihood (0-1)."""
    score = 0.0
    desc = (show_data.get("description") or "").lower()
    title = (show_data.get("title") or "").lower()

    multi_signals = [
        "intervista", "ospite", "ospiti", "parliamo con", "dibattito",
        "tavola rotonda", "conversazione", "dialogo", "chiacchierata",
        "panel", "con ", "insieme a", "discussione",
    ]
    for signal in multi_signals:
        if signal in desc or signal in title:
            score += 0.15

    solo_signals = [
        "monologo", "narrazione", "racconto", "meditazione",
        "lettura", "audiolibro", "asmr",
    ]
    for signal in solo_signals:
        if signal in desc or signal in title:
            score -= 0.3

    return max(0.0, min(1.0, score))


def discover_by_search(db: VociDB, max_pages_per_keyword: int = 5) -> int:
    """Search Spreaker for Italian shows using keyword list."""
    total_new = 0
    known_ids = db.get_show_ids_by_source("spreaker")

    for keyword in ITALIAN_KEYWORDS:
        log.info(f"Searching Spreaker for: {keyword}")
        url = f"{BASE_URL}/search"
        params = {"type": "shows", "q": keyword, "limit": 50}
        pages = 0

        while url and pages < max_pages_per_keyword:
            data = _get(url, params)
            if not data:
                break

            response = data.get("response", {})
            items = response.get("items", [])
            if not items:
                break

            new_in_page = 0
            for item in items:
                show = item.get("show") or item
                source_id = str(show.get("show_id", ""))
                if not source_id or source_id in known_ids:
                    continue

                # Search results don't include language — fetch detail
                detail = _fetch_show_detail(source_id)
                if detail:
                    show = {**show, **detail}
                time.sleep(0.3)

                if not _is_italian(show):
                    continue

                show_id = _make_show_id(source_id)
                is_new = db.upsert_show(
                    show_id=show_id,
                    name=show.get("title", "Unknown"),
                    source="spreaker",
                    source_id=source_id,
                    description=show.get("description"),
                    author=show.get("author", {}).get("fullname") if isinstance(show.get("author"), dict) else show.get("author_name"),
                    categories=json.dumps([show.get("category", {}).get("name")]) if show.get("category") else None,
                    episode_count=show.get("episode_count", 0),
                    multi_speaker_score=_multi_speaker_score(show),
                    feed_url=f"https://www.spreaker.com/show/{source_id}/episodes/feed",
                )

                if is_new:
                    new_in_page += 1
                    known_ids.add(source_id)
                    total_new += 1

            log.info(f"  Page {pages + 1}: {len(items)} results, {new_in_page} new Italian shows")

            # Pagination
            next_url = response.get("next_url")
            if next_url:
                url = next_url
                params = None  # next_url includes params
            else:
                break

            pages += 1
            time.sleep(RATE_LIMIT_DELAY)

        db.log_scrape("spreaker", "search", keyword, shows_found=total_new)
        time.sleep(RATE_LIMIT_DELAY)

    return total_new


def discover_by_category(db: VociDB, max_pages_per_category: int = 10) -> int:
    """Browse all Spreaker categories for Italian shows."""
    total_new = 0
    known_ids = db.get_show_ids_by_source("spreaker")

    for cat_id, cat_name in CATEGORY_IDS.items():
        log.info(f"Browsing Spreaker category: {cat_name} ({cat_id})")
        url = f"{BASE_URL}/explore/categories/{cat_id}/items"
        params = {"limit": 50}
        pages = 0

        while url and pages < max_pages_per_category:
            data = _get(url, params)
            if not data:
                break

            response = data.get("response", {})
            items = response.get("items", [])
            if not items:
                break

            new_in_page = 0
            for item in items:
                show = item.get("show") or item
                source_id = str(show.get("show_id", ""))
                if not source_id or source_id in known_ids:
                    continue

                # Fetch detail for language field
                detail = _fetch_show_detail(source_id)
                if detail:
                    show = {**show, **detail}
                time.sleep(0.3)

                if not _is_italian(show):
                    continue

                show_id = _make_show_id(source_id)
                is_new = db.upsert_show(
                    show_id=show_id,
                    name=show.get("title", "Unknown"),
                    source="spreaker",
                    source_id=source_id,
                    description=show.get("description"),
                    author=show.get("author", {}).get("fullname") if isinstance(show.get("author"), dict) else show.get("author_name"),
                    categories=json.dumps([cat_name]),
                    episode_count=show.get("episode_count", 0),
                    multi_speaker_score=_multi_speaker_score(show),
                    feed_url=f"https://www.spreaker.com/show/{source_id}/episodes/feed",
                )

                if is_new:
                    new_in_page += 1
                    known_ids.add(source_id)
                    total_new += 1

            log.info(f"  {cat_name} page {pages + 1}: {len(items)} items, {new_in_page} new Italian")

            next_url = response.get("next_url")
            if next_url:
                url = next_url
                params = None
            else:
                break

            pages += 1
            time.sleep(RATE_LIMIT_DELAY)

        db.log_scrape("spreaker", "browse", cat_name, shows_found=total_new)

    return total_new


def fetch_episodes(db: VociDB, show_id: str, source_id: str, max_pages: int = 50) -> int:
    """Fetch all episodes for a Spreaker show."""
    total_new = 0
    url = f"{BASE_URL}/shows/{source_id}/episodes"
    params = {"limit": 50}
    pages = 0

    while url and pages < max_pages:
        data = _get(url, params)
        if not data:
            break

        response = data.get("response", {})
        items = response.get("items", [])
        if not items:
            break

        for ep in items:
            audio_url = ep.get("download_url") or ep.get("playback_url")
            if not audio_url:
                continue

            episode_id = _make_episode_id(audio_url)
            duration_ms = ep.get("duration")
            duration_s = int(duration_ms / 1000) if duration_ms else None

            is_new = db.upsert_episode(
                episode_id=episode_id,
                show_id=show_id,
                audio_url=audio_url,
                title=ep.get("title"),
                published_at=ep.get("published_at"),
                duration_seconds=duration_s,
            )
            if is_new:
                total_new += 1

        next_url = response.get("next_url")
        if next_url:
            url = next_url
            params = None
        else:
            break

        pages += 1
        time.sleep(RATE_LIMIT_DELAY)

    return total_new


def fetch_all_episodes(db: VociDB) -> int:
    """Fetch episodes for all discovered Spreaker shows."""
    shows = db.conn.execute(
        "SELECT show_id, source_id FROM shows "
        "WHERE source = 'spreaker' AND state = 'discovered' AND source_id IS NOT NULL"
    ).fetchall()

    total = 0
    for i, show in enumerate(shows):
        log.info(f"Fetching episodes [{i+1}/{len(shows)}]: {show['show_id']}")
        new = fetch_episodes(db, show["show_id"], show["source_id"])
        total += new
        db.update_show_state(show["show_id"], "validated")
        db.log_scrape("spreaker", "episodes", show["source_id"], episodes_found=new)
        log.info(f"  → {new} new episodes")
        time.sleep(RATE_LIMIT_DELAY)

    return total
