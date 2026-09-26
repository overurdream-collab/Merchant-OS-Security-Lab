from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Protocol
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


@dataclass(frozen=True)
class ResearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "web_search"
    captured_at: str = ""


class ResearchProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> List[ResearchResult]:
        ...


class _DuckParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items: List[Dict[str, str]] = []
        self._current: Dict[str, str] | None = None
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "url": attrs.get("href", "")}
            self._in_title = True
        elif self._current and tag in ("a", "div") and "result__snippet" in classes:
            self._in_snippet = True

    def handle_data(self, data):
        if not self._current:
            return
        if self._in_title:
            self._current["title"] += data.strip()
        elif self._in_snippet:
            self._current["snippet"] += data.strip()

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title and self._current:
            self._in_title = False
            if self._current["title"] and self._current["url"]:
                self.items.append(self._current)
                self._current = None
        elif tag in ("div", "a"):
            self._in_snippet = False


class DuckDuckGoResearchProvider:
    def __init__(self, timeout: float = 12.0, user_agent: str = "Merchant-OS/1.0"):
        self.timeout = timeout
        self.user_agent = user_agent

    def search(self, query: str, limit: int = 10) -> List[ResearchResult]:
        if not query.strip():
            return []
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        parser = _DuckParser()
        parser.feed(body)
        now = datetime.now(timezone.utc).isoformat()
        results: List[ResearchResult] = []
        seen = set()
        for item in parser.items:
            target = self._normalize_url(item["url"])
            if not target or target in seen:
                continue
            seen.add(target)
            results.append(ResearchResult(item["title"], target, item.get("snippet", ""), captured_at=now))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _normalize_url(value: str) -> str:
        parsed = urlparse(value)
        if parsed.netloc:
            return value
        query = parse_qs(parsed.query)
        uddg = query.get("uddg", [None])[0]
        return uddg or value


class StaticResearchProvider:
    def __init__(self, results: Iterable[ResearchResult]):
        self.results = list(results)

    def search(self, query: str, limit: int = 10) -> List[ResearchResult]:
        return self.results[:limit]


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("blocked_url_scheme_or_host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("blocked_url_credentials")

    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("blocked_private_host")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if not _is_public_ip(str(literal)):
            raise ValueError("blocked_private_ip")
        return value

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValueError("host_resolution_failed") from exc

    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ValueError("blocked_private_host")

    return value


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        _validate_public_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


class WebPageEnricher:
    """Fetch public HTTP(S) pages while rejecting private/link-local destinations."""

    def __init__(self, timeout: float = 10.0, user_agent: str = "Merchant-OS/1.0"):
        self.timeout = timeout
        self.user_agent = user_agent
        self._opener = build_opener(_SafeRedirectHandler())

    def enrich(self, result: ResearchResult) -> Dict[str, Any]:
        try:
            _validate_public_url(result.url)
            request = Request(result.url, headers={"User-Agent": self.user_agent})
            with self._opener.open(request, timeout=self.timeout) as response:
                final_url = response.geturl()
                _validate_public_url(final_url)
                body = response.read(300_000).decode("utf-8", errors="replace")
        except Exception as exc:
            return {"url": result.url, "fetch_ok": False, "fetch_error": str(exc)}

        lower = body.lower()
        channels = []
        for marker, name in (("facebook.com", "facebook"), ("whatsapp", "whatsapp"),
                             ("instagram.com", "instagram"), ("t.me/", "telegram")):
            if marker in lower:
                channels.append(name)
        phones = []
        for value in re.findall(r"(?:\\+?967|00967)?\\s?7\\d{8}", body):
            digits = re.sub(r"\\D", "", value)
            if digits.startswith("967") and len(digits) == 12:
                phones.append("+" + digits)
            elif len(digits) == 9 and digits.startswith("7"):
                phones.append("+967" + digits)
        title = result.title
        match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        if match:
            title = re.sub(r"\\s+", " ", match.group(1)).strip()[:300] or title
        return {
            "url": result.url,
            "final_url": final_url,
            "fetch_ok": True,
            "title": title,
            "channels": sorted(set(channels)),
            "phones": sorted(set(phones)),
            "text_length": len(body),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
