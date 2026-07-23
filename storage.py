import json
import os
from threading import Lock

DATA_FILE = os.path.join(os.path.dirname(__file__), "channels.json")
_lock = Lock()


def _read() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(channels: list) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)


def get_channels() -> list:
    with _lock:
        return _read()


def add_channel(chat_id: int, title: str) -> bool:
    """Возвращает True, если канал новый (не был добавлен раньше)."""
    with _lock:
        channels = _read()
        for ch in channels:
            if ch["id"] == chat_id:
                return False
        channels.append({"id": chat_id, "title": title, "enabled": True})
        _write(channels)
        return True


def set_channel_enabled(chat_id: int, enabled: bool) -> bool:
    with _lock:
        channels = _read()
        for ch in channels:
            if ch["id"] == chat_id:
                ch["enabled"] = enabled
                _write(channels)
                return True
        return False


def is_channel_enabled(chat_id: int) -> bool:
    for ch in _read():
        if ch["id"] == chat_id:
            return ch.get("enabled", True)
    return False


def set_channel_news_enabled(chat_id: int, enabled: bool) -> bool:
    with _lock:
        channels = _read()
        for ch in channels:
            if ch["id"] == chat_id:
                ch["news_enabled"] = enabled
                _write(channels)
                return True
        return False


def is_channel_news_enabled(chat_id: int) -> bool:
    for ch in _read():
        if ch["id"] == chat_id:
            return ch.get("news_enabled", False)
    return False


def get_seen_news() -> list:
    data_dir = os.path.dirname(DATA_FILE)
    path = os.path.join(data_dir, "seen_news.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def add_seen_news(link: str) -> None:
    data_dir = os.path.dirname(DATA_FILE)
    path = os.path.join(data_dir, "seen_news.json")
    seen = get_seen_news()
    seen.append(link)
    seen = seen[-300:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def get_primed_feeds() -> list:
    data_dir = os.path.dirname(DATA_FILE)
    path = os.path.join(data_dir, "primed_feeds.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def mark_feed_primed(feed_url: str) -> None:
    data_dir = os.path.dirname(DATA_FILE)
    path = os.path.join(data_dir, "primed_feeds.json")
    primed = get_primed_feeds()
    if feed_url not in primed:
        primed.append(feed_url)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(primed, f, ensure_ascii=False, indent=2)


SOURCES_FILE = os.path.join(os.path.dirname(__file__), "sources.json")

_DEFAULT_SOURCES = [
    {"name": "УНІАН", "type": "rss", "url": "https://rss.unian.net/site/news_ukr.rss", "enabled": True},
    {"name": "Українська правда", "type": "rss", "url": "https://www.pravda.com.ua/rss/", "enabled": True},
    {"name": "РБК-Україна", "type": "rss", "url": "https://www.rbc.ua/static/rss/all.ukr.rss.xml", "enabled": True},
    {"name": "НВ", "type": "rss", "url": "https://nv.ua/rss/all.xml", "enabled": True},
]


def _read_sources() -> list:
    if not os.path.exists(SOURCES_FILE):
        _write_sources(_DEFAULT_SOURCES)
        return list(_DEFAULT_SOURCES)
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_sources(sources: list) -> None:
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)


def get_sources() -> list:
    with _lock:
        return _read_sources()


def get_active_rss_sources() -> list:
    """Возвращает список (name, url) только для включённых RSS-джерел (сайтів)."""
    return [
        (s["name"], s["url"])
        for s in get_sources()
        if s.get("enabled", True) and s.get("type", "rss") == "rss"
    ]


def get_telegram_source_by_chat_id(chat_id: int):
    for s in get_sources():
        if s.get("type") == "telegram" and s.get("chat_id") == chat_id and s.get("enabled", True):
            return s
    return None


def add_source(name: str, url: str) -> bool:
    """Добавляет RSS-джерело (сайт). Возвращает False, якщо джерело з такою назвою вже є."""
    with _lock:
        sources = _read_sources()
        for s in sources:
            if s["name"].lower() == name.lower():
                return False
        sources.append({"name": name, "type": "rss", "url": url, "enabled": True})
        _write_sources(sources)
        return True


def add_telegram_source(name: str, chat_id: int) -> bool:
    """Добавляет Telegram-канал как джерело новин. Возвращает False, якщо вже додано."""
    with _lock:
        sources = _read_sources()
        for s in sources:
            if s.get("type") == "telegram" and s.get("chat_id") == chat_id:
                return False
        sources.append({"name": name, "type": "telegram", "chat_id": chat_id, "enabled": True})
        _write_sources(sources)
        return True


def remove_source(name: str) -> bool:
    with _lock:
        sources = _read_sources()
        before = len(sources)
        sources = [s for s in sources if s["name"].lower() != name.lower()]
        _write_sources(sources)
        return len(sources) != before


def set_source_enabled(name: str, enabled: bool) -> bool:
    with _lock:
        sources = _read_sources()
        for s in sources:
            if s["name"].lower() == name.lower():
                s["enabled"] = enabled
                _write_sources(sources)
                return True
        return False


def get_recent_titles() -> list:
    data_dir = os.path.dirname(DATA_FILE)
    path = os.path.join(data_dir, "recent_titles.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def add_recent_title(title: str) -> None:
    data_dir = os.path.dirname(DATA_FILE)
    path = os.path.join(data_dir, "recent_titles.json")
    titles = get_recent_titles()
    titles.append(title)
    titles = titles[-150:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False, indent=2)


def set_channel_keywords(chat_id: int, keywords: list) -> bool:
    with _lock:
        channels = _read()
        for ch in channels:
            if ch["id"] == chat_id:
                ch["news_keywords"] = keywords
                _write(channels)
                return True
        return False


def get_channel_keywords(chat_id: int) -> list:
    for ch in _read():
        if ch["id"] == chat_id:
            return ch.get("news_keywords", [])
    return []


def remove_channel(chat_id: int) -> bool:
    with _lock:
        channels = _read()
        before = len(channels)
        channels = [c for c in channels if c["id"] != chat_id]
        _write(channels)
        return len(channels) != before