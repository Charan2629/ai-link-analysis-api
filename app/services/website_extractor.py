import re
from dataclasses import dataclass, field
from typing import List, Optional
from bs4 import BeautifulSoup
import httpx

from app.config import get_settings


class WebsiteExtractionException(Exception):
    """Base exception for website extraction failures."""
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WebsiteTimeoutException(WebsiteExtractionException):
    """Raised when website request times out."""
    def __init__(self, message: str = "Website request timed out."):
        super().__init__(message, status_code=504)


class WebsiteUnreachableException(WebsiteExtractionException):
    """Raised when website is inaccessible, returns 403/404, or fails to connect."""
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message, status_code=status_code)


class EmptyContentException(WebsiteExtractionException):
    """Raised when page has no parseable text content."""
    def __init__(self, message: str = "Website contains insufficient readable content for analysis."):
        super().__init__(message, status_code=422)


@dataclass
class ExtractedWebsiteData:
    url: str
    title: str = ""
    meta_description: str = ""
    og_title: str = ""
    og_description: str = ""
    og_site_name: str = ""
    headings: List[str] = field(default_factory=list)
    nav_links: List[str] = field(default_factory=list)
    cleaned_body_text: str = ""
    truncated_content: str = ""

    def to_llm_context(self) -> str:
        """Format the extracted content into a compact representation for LLM ingestion."""
        parts = [
            f"Website URL: {self.url}",
            f"Page Title: {self.title or 'N/A'}",
            f"Meta Description: {self.meta_description or 'N/A'}",
        ]
        if self.og_site_name:
            parts.append(f"Brand/Site Name (OG): {self.og_site_name}")
        if self.og_title and self.og_title != self.title:
            parts.append(f"OG Title: {self.og_title}")
        if self.og_description and self.og_description != self.meta_description:
            parts.append(f"OG Description: {self.og_description}")

        if self.headings:
            parts.append("Main Headings:")
            for h in self.headings[:20]:
                parts.append(f"  - {h}")

        if self.nav_links:
            parts.append("Navigation & Key Links:")
            for link in self.nav_links[:15]:
                parts.append(f"  - {link}")

        parts.append("\nWebsite Main Content:")
        parts.append(self.truncated_content)

        return "\n".join(parts)


def clean_html_content(html: str, max_chars: int = 12000) -> ExtractedWebsiteData:
    """
    Parse HTML with BeautifulSoup, extract core metadata and headings,
    strip unwanted script/style elements, clean whitespace, and truncate.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract metadata
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)}) or \
               soup.find("meta", attrs={"property": re.compile(r"^og:description$", re.I)})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    og_title = ""
    og_t = soup.find("meta", attrs={"property": "og:title"})
    if og_t and og_t.get("content"):
        og_title = og_t["content"].strip()

    og_desc = ""
    og_d = soup.find("meta", attrs={"property": "og:description"})
    if og_d and og_d.get("content"):
        og_desc = og_d["content"].strip()

    og_site = ""
    og_s = soup.find("meta", attrs={"property": "og:site_name"})
    if og_s and og_s.get("content"):
        og_site = og_s["content"].strip()

    # 2. Extract Headings (h1 - h3)
    headings: List[str] = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(separator=" ", strip=True)
        if text and len(text) > 2 and text not in headings:
            headings.append(text)

    # 3. Extract top navigation link anchors
    nav_links: List[str] = []
    nav = soup.find("nav")
    if nav:
        for a in nav.find_all("a", href=True):
            txt = a.get_text(strip=True)
            if txt and len(txt) > 2 and txt not in nav_links:
                nav_links.append(f"{txt} ({a['href']})")

    # 4. Remove noisy and non-content elements
    for element in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer", "form"]):
        element.decompose()

    # 5. Extract body text
    body = soup.body or soup
    raw_text = body.get_text(separator=" ", strip=True)

    # Collapse multiple whitespaces and newlines
    cleaned_text = re.sub(r"\s+", " ", raw_text).strip()

    if not cleaned_text and not title and not headings:
        raise EmptyContentException("The webpage did not contain sufficient textual content to analyze.")

    # Truncate content to max_chars to optimize LLM tokens and latency
    truncated = cleaned_text[:max_chars]

    return ExtractedWebsiteData(
        url="",
        title=title,
        meta_description=meta_desc,
        og_title=og_title,
        og_description=og_desc,
        og_site_name=og_site,
        headings=headings,
        nav_links=nav_links,
        cleaned_body_text=cleaned_text,
        truncated_content=truncated,
    )


async def fetch_and_extract_website(url: str) -> ExtractedWebsiteData:
    """
    Fetch website HTML asynchronously via httpx, handle timeouts,
    check HTTP status codes, and return cleaned structured content.
    """
    settings = get_settings()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    timeout = httpx.Timeout(
        timeout=float(settings.REQUEST_TIMEOUT_SECONDS),
        connect=5.0,
    )

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            max_redirects=5,
            verify=True,
        ) as client:
            response = await client.get(url)

    except httpx.TimeoutException as exc:
        raise WebsiteTimeoutException(
            f"Connection to '{url}' timed out after {settings.REQUEST_TIMEOUT_SECONDS}s."
        ) from exc
    except httpx.ConnectError as exc:
        raise WebsiteUnreachableException(
            f"Failed to connect to website '{url}'. Host may be offline or unreachable: {exc}",
            status_code=422,
        ) from exc
    except httpx.RequestError as exc:
        raise WebsiteUnreachableException(
            f"Network error while accessing '{url}': {exc}",
            status_code=422,
        ) from exc

    # Handle HTTP error statuses gracefully
    if response.status_code == 404:
        raise WebsiteUnreachableException(
            f"Website returned HTTP 404 Not Found at '{url}'.",
            status_code=422,
        )
    elif response.status_code == 403:
        raise WebsiteUnreachableException(
            f"Access to website '{url}' was denied by remote server (HTTP 403 Forbidden).",
            status_code=422,
        )
    elif response.status_code >= 400:
        raise WebsiteUnreachableException(
            f"Website '{url}' responded with HTTP error {response.status_code}.",
            status_code=422,
        )

    # Content-Type check (skip binary downloads)
    content_type = response.headers.get("content-type", "").lower()
    if content_type and not any(ct in content_type for ct in ("text/html", "application/xhtml+xml", "text/plain")):
        raise WebsiteUnreachableException(
            f"Target URL returned non-HTML content-type '{content_type}'.",
            status_code=422,
        )

    data = clean_html_content(response.text, max_chars=settings.MAX_CONTENT_CHARS)
    data.url = str(response.url)
    return data
