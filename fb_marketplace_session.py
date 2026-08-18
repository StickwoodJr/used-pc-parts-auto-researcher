"""
Robust Facebook Marketplace scraper using persistent authenticated browser session.
Features infinite-scroll DOM hydration, multi-line card parsing, badge handling,
and strict Canadian compatibility filtering.
"""

import os
import re
import time
import logging
from typing import List, Optional, Dict, Any

from ebay_client import ListingItem
from config import (
    SEARCH_RADIUS_KM,
    CPU_SEARCH_TERMS,
    RAM_SEARCH_TERMS,
)
from filters import (
    normalize_url,
    is_cpu_compatible,
    is_ram_compatible,
    is_canadian_location,
    determine_status,
)

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = os.path.expanduser("~/.config/facebook_search_profile")


class FacebookMarketplaceSession:
    """
    Scrapes Facebook Marketplace listings from Newmarket, ON (20km radius)
    using Playwright with a persistent logged-in browser context.
    """

    def __init__(self, user_data_dir: str = DEFAULT_PROFILE_DIR, headless: bool = True):
        self.user_data_dir = user_data_dir
        self.headless = headless

    def _parse_card_text_robust(self, text_lines: List[str]) -> Optional[Dict[str, Any]]:
        """
        Robust parser for Facebook Marketplace card lines:
        Handles badges ('Just listed', 'Price drop'), struck-through prices,
        multi-line titles, distance tags ('· 18 km'), and municipality names.
        """
        lines = [l.strip() for l in text_lines if l.strip()]
        if not lines:
            return None

        price_val = 0.0
        title = ""
        location = "Newmarket, ON"

        # 1. Identify Price line
        price_idx = -1
        for idx, l in enumerate(lines):
            if re.search(r"(?:ca\$|c\$|\$)\s*[\d,]+(?:\.\d+)?", l, re.I) or l.lower() == "free":
                price_match = re.search(r"(?:ca\$|c\$|\$)\s*([\d,]+(?:\.\d+)?)", l, re.I)
                if price_match:
                    try:
                        price_val = float(price_match.group(1).replace(",", ""))
                    except ValueError:
                        price_val = 0.0
                elif l.lower() == "free":
                    price_val = 0.0
                price_idx = idx
                break

        if price_idx == -1:
            return None

        # 2. Extract remaining lines after price (skip struck-through prices if any)
        remaining_lines = []
        for idx in range(price_idx + 1, len(lines)):
            l = lines[idx]
            if re.search(r"^(?:ca\$|c\$|\$)\s*[\d,]+", l, re.I):
                continue  # Skip old struck-through price
            remaining_lines.append(l)

        if not remaining_lines:
            return None

        # 3. First non-price line is Title
        title = remaining_lines[0]

        # 4. Search for valid Canadian location in remaining lines
        for line in remaining_lines[1:]:
            if line.startswith("·") or re.search(r"^\d+\s*km", line) or "ships" in line.lower():
                continue
            if is_canadian_location(line) or re.search(r",\s*[A-Z]{2}\b", line):
                location = line
                break

        return {"title": title, "price": price_val, "location": location}

    def parse_raw_card(
        self,
        title: str,
        price_str: str,
        location: str,
        raw_url: str,
        category: str,
        condition: str = "Used",
    ) -> Optional[ListingItem]:
        """
        Parses raw card fields directly (for tests or manual injection),
        applies compatibility & Canadian location filters, and returns a ListingItem.
        """
        if not title or not raw_url:
            return None

        title = title.strip()
        if category == "CPU" and not is_cpu_compatible(title):
            return None
        if category == "RAM" and not is_ram_compatible(title):
            return None

        price_match = re.search(r"[\d,]+(?:\.\d+)?", price_str)
        price_val = float(price_match.group(0).replace(",", "")) if price_match else 0.0
        canonical_url = normalize_url(raw_url)
        status = determine_status(price_val, category)

        return ListingItem(
            category=category,
            title=title,
            price=price_val,
            condition=condition or "Used",
            location=location or "Newmarket, ON",
            listing_url=canonical_url,
            status=status,
            location_match_type="Confirmed within-radius (Marketplace filter)",
            source="Facebook Marketplace",
        )

    def search_cpu_and_ram(self) -> List[ListingItem]:
        """
        Executes comprehensive search passes across all CPU and RAM queries
        with infinite scroll DOM hydration.
        """
        listings: List[ListingItem] = []
        seen_urls = set()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("Playwright not available. Skipping live FB browser run.")
            return listings

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 900},
                    locale="en-CA",
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = context.pages[0] if context.pages else context.new_page()

                # Test navigation to marketplace
                page.goto("https://www.facebook.com/marketplace/newmarket/search", timeout=30000)
                page.wait_for_timeout(2000)

                page_content = page.content().lower()
                if "log into facebook" in page_content or "login" in page.url.lower() or "checkpoint" in page.url.lower():
                    logger.warning("Facebook session expired or login required.")
                    print("\n[WARNING] Facebook session expired or login required.")
                    context.close()
                    return listings

                # 1. Search CPUs
                for term in CPU_SEARCH_TERMS:
                    query_url = f"https://www.facebook.com/marketplace/newmarket/search?query={term}&exact=false&radius={SEARCH_RADIUS_KM}"
                    try:
                        page.goto(query_url, timeout=25000)
                        page.wait_for_timeout(1500)

                        # Infinite scroll: 4 passes to trigger dynamic loading
                        for _ in range(4):
                            page.evaluate("window.scrollBy(0, 1800)")
                            page.wait_for_timeout(1000)

                        cards = page.query_selector_all("a[href*='/marketplace/item/']")
                        for card in cards:
                            href = card.get_attribute("href") or ""
                            canonical_url = normalize_url(href if href.startswith("http") else f"https://www.facebook.com{href}")
                            if not canonical_url or canonical_url in seen_urls:
                                continue

                            text_lines = [t.strip() for t in card.inner_text().split("\n") if t.strip()]
                            parsed = self._parse_card_text_robust(text_lines)
                            if not parsed:
                                continue

                            title = parsed["title"]
                            if not is_cpu_compatible(title):
                                continue

                            price_val = parsed["price"]
                            location = parsed["location"]
                            if not is_canadian_location(location):
                                continue

                            status = determine_status(price_val, "CPU")
                            seen_urls.add(canonical_url)

                            listings.append(
                                ListingItem(
                                    category="CPU",
                                    title=title,
                                    price=price_val,
                                    condition="Used",
                                    location=location,
                                    listing_url=canonical_url,
                                    status=status,
                                    location_match_type="Confirmed within-radius (Marketplace filter)",
                                    source="Facebook Marketplace",
                                )
                            )
                    except Exception as q_err:
                        logger.debug(f"Error querying CPU term '{term}': {q_err}")

                # 2. Search RAM
                for term in RAM_SEARCH_TERMS:
                    query_url = f"https://www.facebook.com/marketplace/newmarket/search?query={term}&exact=false&radius={SEARCH_RADIUS_KM}"
                    try:
                        page.goto(query_url, timeout=25000)
                        page.wait_for_timeout(1500)

                        # Infinite scroll: 4 passes
                        for _ in range(4):
                            page.evaluate("window.scrollBy(0, 1800)")
                            page.wait_for_timeout(1000)

                        cards = page.query_selector_all("a[href*='/marketplace/item/']")
                        for card in cards:
                            href = card.get_attribute("href") or ""
                            canonical_url = normalize_url(href if href.startswith("http") else f"https://www.facebook.com{href}")
                            if not canonical_url or canonical_url in seen_urls:
                                continue

                            text_lines = [t.strip() for t in card.inner_text().split("\n") if t.strip()]
                            parsed = self._parse_card_text_robust(text_lines)
                            if not parsed:
                                continue

                            title = parsed["title"]
                            if not is_ram_compatible(title):
                                continue

                            price_val = parsed["price"]
                            location = parsed["location"]
                            if not is_canadian_location(location):
                                continue

                            status = determine_status(price_val, "RAM")
                            seen_urls.add(canonical_url)

                            listings.append(
                                ListingItem(
                                    category="RAM",
                                    title=title,
                                    price=price_val,
                                    condition="Used",
                                    location=location,
                                    listing_url=canonical_url,
                                    status=status,
                                    location_match_type="Confirmed within-radius (Marketplace filter)",
                                    source="Facebook Marketplace",
                                )
                            )
                    except Exception as q_err:
                        logger.debug(f"Error querying RAM term '{term}': {q_err}")

                context.close()
        except Exception as e:
            logger.error(f"Error during Facebook Marketplace session: {e}")

        return listings
