"""
Direct eBay.ca search scraper (No eBay Developer Program / API keys required).
Performs dual-mode search (Local Pickup radius + Canada-wide proximity post-filtering),
extracts native CAD prices, applies compatibility filters, and deduplicates across modes.
"""

import re
import time
import logging
from typing import List, Dict, Optional
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

from ebay_client import ListingItem
from config import (
    SEARCH_POSTAL_CODE,
    SEARCH_RADIUS_KM,
    CPU_SEARCH_TERMS,
    RAM_SEARCH_TERMS,
)
from filters import (
    normalize_url,
    is_cpu_compatible,
    is_ram_compatible,
    is_proximity_match,
    is_canadian_location,
    extract_located_in,
    determine_status,
)

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.ebay.ca/",
}


class EbayBrowserScraper:
    """
    Direct web scraper for eBay.ca without requiring API credentials.
    """

    def __init__(self, postal_code: str = SEARCH_POSTAL_CODE, radius_km: int = SEARCH_RADIUS_KM):
        self.postal_code = postal_code
        self.radius_km = radius_km
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _parse_price(self, price_str: str) -> float:
        """Parses price strings like 'C $65.00', '$45.00 to $50.00', 'CA $80.00' to float."""
        if not price_str:
            return 0.0
        # If range (e.g. $45 to $50), take the lower bound
        first_part = price_str.split("to")[0]
        cleaned = re.sub(r"[^\d.]", "", first_part.replace(",", ""))
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

    def _parse_seller_info(self, seller_text: str):
        """
        Parses seller info text like 'seller123 (1,452) 99.4%' or 'top_rated (500) 100%'.
        Returns (seller_name, rating_pct, feedback_count, badge).
        """
        if not seller_text:
            return "", 100.0, 0, ""

        name_match = re.search(r"^([a-zA-Z0-9_-]+)", seller_text.strip())
        seller_name = name_match.group(1) if name_match else ""

        # Feedback count (e.g. (1,452) or 500 reviews)
        count_match = re.search(r"\(([0-9,]+)\)", seller_text)
        feedback_count = 0
        if count_match:
            try:
                feedback_count = int(count_match.group(1).replace(",", ""))
            except ValueError:
                feedback_count = 0

        # Rating percentage (e.g. 99.4%)
        rating_match = re.search(r"(\d+(?:\.\d+)?)\s*%", seller_text)
        rating_pct = 100.0
        if rating_match:
            try:
                rating_pct = float(rating_match.group(1))
            except ValueError:
                rating_pct = 100.0

        badge = "Top Rated" if "top rated" in seller_text.lower() else ""
        return seller_name, rating_pct, feedback_count, badge

    def _extract_items_from_html(
        self,
        html_content: str,
        category: str,
        location_match_type: str,
        require_proximity_check: bool = False,
    ) -> List[ListingItem]:
        """
        Parses eBay search results HTML and returns filtered ListingItems.
        """
        items: List[ListingItem] = []
        soup = BeautifulSoup(html_content, "html.parser")

        # Listing card selectors
        listing_cards = soup.select(".s-item, .s-card, li.s-item")
        if not listing_cards:
            listing_cards = soup.find_all("div", class_=lambda c: c and "s-item__wrapper" in c)

        for card in listing_cards:
            # Skip promotional / banner items
            title_elem = card.select_one(".s-item__title, span[role='heading'], .s-card__title")
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True).replace("Opens in a new window or tab", "").strip()
            if not title or "Shop on eBay" in title:
                continue

            # Link & URL
            link_elem = card.select_one("a.s-item__link, a[href*='/itm/']")
            if not link_elem:
                continue
            raw_url = link_elem.get("href", "")
            canonical_url = normalize_url(raw_url)
            if not canonical_url or "/itm/" not in canonical_url:
                continue

            # Check category compatibility filter
            if category == "CPU" and not is_cpu_compatible(title):
                continue
            if category == "RAM" and not is_ram_compatible(title):
                continue

            # Price
            price_elem = card.select_one(".s-item__price, .s-card__price")
            price_str = price_elem.get_text(strip=True) if price_elem else ""
            price_val = self._parse_price(price_str)

            # Condition
            cond_elem = card.select_one(".SECONDARY_INFO, .s-item__subtitle")
            condition = cond_elem.get_text(strip=True) if cond_elem else "Used"

            # Location & Strict Canadian Verification via 'Located in:' and location tags
            card_all_text = card.get_text(separator=" ", strip=True)
            extracted_loc = extract_located_in(card_all_text)

            loc_elem = card.select_one(".s-item__location, .s-item__itemLocation, .s-card__location, .s-item__dynamic")
            tag_loc = loc_elem.get_text(strip=True).replace("from ", "").strip() if loc_elem else ""

            loc_candidate = extracted_loc if extracted_loc else tag_loc

            # If no location or location is not verified in Canada, reject immediately
            if not loc_candidate or not is_canadian_location(loc_candidate):
                continue

            loc_text = loc_candidate

            # Proximity post-filter for Mode 2
            if require_proximity_check and not is_proximity_match(loc_text):
                continue

            # Seller Info
            seller_elem = card.select_one(".s-item__seller-info-text, .s-item__user-info, .s-card__seller-info")
            seller_text = seller_elem.get_text(strip=True) if seller_elem else ""
            seller_name, rating_pct, feedback_count, badge = self._parse_seller_info(seller_text)

            status = determine_status(price_val, category)

            items.append(
                ListingItem(
                    category=category,
                    title=title,
                    price=price_val,
                    condition=condition,
                    location=loc_text,
                    listing_url=canonical_url,
                    status=status,
                    location_match_type=location_match_type,
                    source="eBay Browser",
                    seller_name=seller_name,
                    seller_rating_pct=rating_pct,
                    seller_feedback_count=feedback_count,
                    seller_badge=badge,
                )
            )

        return items

    def _fetch_html(self, url: str) -> str:
        """Fetches page content with exponential backoff retry."""
        for attempt in range(1, 4):
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(f"eBay fetch received {resp.status_code}. Retry {attempt}/3...")
                    time.sleep(2 ** attempt)
                else:
                    return ""
            except requests.RequestException as e:
                if attempt == 3:
                    logger.error(f"eBay fetch failed after 3 attempts: {e}")
                    return ""
                time.sleep(2 ** attempt)
        return ""

    def search_cpu_and_ram(self) -> List[ListingItem]:
        """
        Executes dual-mode web search on eBay.ca:
        1. Mode 1: Local Pickup within radius (LH_LocalPickup=1)
        2. Mode 2: Canada-wide with GTA proximity post-filter (LH_PrefLoc=1)
        Merges results with Local Pickup priority.
        """
        raw_mode1_items: List[ListingItem] = []
        raw_mode2_items: List[ListingItem] = []

        # 1. CPUs
        for term in CPU_SEARCH_TERMS:
            encoded_query = quote_plus(term)
            
            # Mode 1: Local Pickup within radius
            m1_url = (
                f"https://www.ebay.ca/sch/i.html?_nkw={encoded_query}&_sacat=0"
                f"&_stpos={self.postal_code}&_sadis={self.radius_km}&LH_LocalPickup=1&LH_PrefLoc=1"
            )
            html1 = self._fetch_html(m1_url)
            if html1:
                m1_items = self._extract_items_from_html(
                    html1, "CPU", "Confirmed within-radius (Local Pickup)", require_proximity_check=False
                )
                raw_mode1_items.extend(m1_items)

            # Mode 2: Canada-wide (LH_PrefLoc=1) + proximity post-filter
            m2_url = f"https://www.ebay.ca/sch/i.html?_nkw={encoded_query}&_sacat=0&LH_PrefLoc=1"
            html2 = self._fetch_html(m2_url)
            if html2:
                m2_items = self._extract_items_from_html(
                    html2, "CPU", "Approximate location match", require_proximity_check=True
                )
                raw_mode2_items.extend(m2_items)

        # 2. RAM
        for term in RAM_SEARCH_TERMS:
            encoded_query = quote_plus(term)

            # Mode 1: Local Pickup
            m1_url = (
                f"https://www.ebay.ca/sch/i.html?_nkw={encoded_query}&_sacat=0"
                f"&_stpos={self.postal_code}&_sadis={self.radius_km}&LH_LocalPickup=1&LH_PrefLoc=1"
            )
            html1 = self._fetch_html(m1_url)
            if html1:
                m1_items = self._extract_items_from_html(
                    html1, "RAM", "Confirmed within-radius (Local Pickup)", require_proximity_check=False
                )
                raw_mode1_items.extend(m1_items)

            # Mode 2: Canada-wide + proximity
            m2_url = f"https://www.ebay.ca/sch/i.html?_nkw={encoded_query}&_sacat=0&LH_PrefLoc=1"
            html2 = self._fetch_html(m2_url)
            if html2:
                m2_items = self._extract_items_from_html(
                    html2, "RAM", "Approximate location match", require_proximity_check=True
                )
                raw_mode2_items.extend(m2_items)

        # 3. Cross-Mode Deduplication & Priority Merging
        merged_by_url: Dict[str, ListingItem] = {}

        # Add Mode 2 first
        for item in raw_mode2_items:
            merged_by_url[item.listing_url] = item

        # Mode 1 takes priority
        for item in raw_mode1_items:
            merged_by_url[item.listing_url] = item

        return list(merged_by_url.values())
