# VERSION: 1.0
# AUTHORS: vesta
# ABOUT: TorrentLeech search plugin for qBittorrent

# qBittorrent nova3 search engine plugin for TorrentLeech (torrentleech.org)
# Install via qBittorrent API:
#   curl -X POST 'http://localhost:$QB_PORT/api/v2/search/installPlugin' \
#     -d 'sources=file://$HOME/agent/skills/media-server/torrentleech.py'
#
# Or copy to the nova3 engines directory:
#   cp torrentleech.py ~/.local/share/qBittorrent/nova3/engines/

import json
import os
import tempfile
import urllib.parse
import urllib.request
import http.cookiejar

# Try importing qBittorrent's novaprinter (works when run as plugin)
try:
    from novaprinter import prettyPrinter
except ImportError:
    # Standalone mode: define our own prettyPrinter
    def prettyPrinter(row):
        print(
            "|".join(
                [
                    row.get("link", ""),
                    row.get("name", ""),
                    str(row.get("size", "-1")),
                    str(row.get("seeds", "0")),
                    str(row.get("leech", "0")),
                    row.get("engine_url", ""),
                    row.get("desc_link", ""),
                ]
            )
        )


try:
    from helpers import retrieve_url
except ImportError:
    retrieve_url = None


class torrentleech:
    """Search engine plugin for TorrentLeech"""

    url = "https://www.torrentleech.org"
    name = "TorrentLeech"
    supported_categories = {
        "all": "",
        "movies": "1,8,9,10,11,12,13,14,15,29,36,37,43,47",
        "tv": "2,26,27,32,44",
        "music": "16,17,18,19,20,21,22,23,24,25",
        "games": "3,33,34,35,38,39,40,41,42",
        "software": "4,28,30,31",
        "anime": "5,6,7",
        "books": "45,46",
    }

    # --- Credentials ---
    # Set via environment variables or edit these defaults
    USERNAME = os.environ.get("TL_USERNAME", "")
    PASSWORD = os.environ.get("TL_PASSWORD", "")

    # Cookie persistence
    COOKIE_FILE = os.environ.get("TL_COOKIE_FILE", os.path.join(tempfile.gettempdir(), "tl_qbt_cookies.txt"))

    # SOCKS5 proxy (optional, for ISP bypass)
    SOCKS5_HOST = os.environ.get("SOCKS5_HOST", "")
    SOCKS5_PORT = os.environ.get("SOCKS5_PORT", "1080")
    SOCKS5_USER = os.environ.get("SOCKS5_USER", "")
    SOCKS5_PASS = os.environ.get("SOCKS5_PASS", "")

    def __init__(self):
        self.cj = http.cookiejar.MozillaCookieJar(self.COOKIE_FILE)
        handlers = [urllib.request.HTTPCookieProcessor(self.cj)]

        # Add SOCKS5 proxy if configured
        if self.SOCKS5_HOST:
            proxy_auth = ""
            if self.SOCKS5_USER and self.SOCKS5_PASS:
                proxy_auth = f"{self.SOCKS5_USER}:{self.SOCKS5_PASS}@"
            proxy_url = f"socks5://{proxy_auth}{self.SOCKS5_HOST}:{self.SOCKS5_PORT}"
            proxy_handler = urllib.request.ProxyHandler(
                {
                    "http": proxy_url,
                    "https": proxy_url,
                }
            )
            handlers.append(proxy_handler)

        self.opener = urllib.request.build_opener(*handlers)
        self.opener.addheaders = [
            ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            ("Accept", "application/json, text/html, */*"),
            ("Referer", self.url + "/"),
        ]

        # Try loading saved cookies
        try:
            self.cj.load(ignore_discard=True, ignore_expires=True)
        except (FileNotFoundError, OSError):
            pass

    def _login(self):
        """Authenticate with TorrentLeech"""
        login_url = f"{self.url}/user/account/login/"
        data = urllib.parse.urlencode(
            {
                "username": self.USERNAME,
                "password": self.PASSWORD,
            }
        ).encode("utf-8")

        try:
            self.opener.open(login_url, data, timeout=30)
            # Save cookies for reuse
            self.cj.save(ignore_discard=True, ignore_expires=True)
            return True
        except Exception:
            return False

    def _is_logged_in(self):
        """Check if we have valid session cookies"""
        for cookie in self.cj:
            if "torrentleech" in cookie.domain and cookie.name in ("tluid", "tlpass", "PHPSESSID", "__cfduid", "member_id"):
                return True
        return False

    def _ensure_auth(self):
        """Ensure we're authenticated"""
        if not self._is_logged_in():
            return self._login()
        return True

    def _fetch_json(self, url):
        """Fetch a URL and parse JSON response"""
        try:
            req = urllib.request.Request(url)
            req.add_header("X-Requested-With", "XMLHttpRequest")
            response = self.opener.open(req, timeout=30)
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
        except json.JSONDecodeError:
            # Might need to re-login
            if self._login():
                try:
                    req = urllib.request.Request(url)
                    req.add_header("X-Requested-With", "XMLHttpRequest")
                    response = self.opener.open(req, timeout=30)
                    raw = response.read().decode("utf-8", errors="replace")
                    return json.loads(raw)
                except Exception:
                    return None
            return None
        except Exception:
            return None

    def search(self, what, cat="all"):
        """
        Search TorrentLeech.
        'what' is the search query with spaces replaced by +
        'cat' is the category key
        """
        self._ensure_auth()

        # Build search URL
        query = urllib.parse.quote(what.replace("+", " "))
        search_url = f"{self.url}/torrents/browse/list/query/{query}"

        # Add category filter
        cat_ids = self.supported_categories.get(cat, "")
        if cat_ids:
            search_url += f"/categories/{cat_ids}"

        search_url += "/orderby/seeders/order/desc"

        data = self._fetch_json(search_url)
        if not data:
            return

        torrents = data.get("torrentList", data.get("torrents", []))

        for t in torrents:
            name = t.get("name", t.get("filename", "Unknown"))
            fid = t.get("fid", t.get("id", ""))
            filename = t.get("filename", name)
            seeds = t.get("seeders", 0)
            leech = t.get("leechers", 0)
            size = t.get("size", -1)

            # Build download URL
            dl_url = f"{self.url}/download/{fid}/{urllib.parse.quote(filename)}.torrent"

            # Description page URL
            desc_url = f"{self.url}/torrent/{fid}"

            prettyPrinter(
                {
                    "link": dl_url,
                    "name": name,
                    "size": str(size),
                    "seeds": str(seeds),
                    "leech": str(leech),
                    "engine_url": self.url,
                    "desc_link": desc_url,
                }
            )


# Allow running standalone for testing
if __name__ == "__main__":
    import sys

    engine = torrentleech()
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "test"
    cat = "all"
    print(f"Searching TorrentLeech for: {query} (category: {cat})")
    print()
    engine.search(query.replace(" ", "+"), cat)
