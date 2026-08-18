"""
Facebook Marketplace session runner.
Uses the persistent authenticated browser profile in ~/.config/facebook_search_profile.
Extracts title, price (CAD), condition, location, canonical URL, and assigns
Location Match Type = 'Confirmed within-radius (Marketplace filter)'.
"""

import os
import re
import logging
from typing import List, Optional, Dict, Any
from ebay_client import ListingItem
from config import (
    CPU_SEARCH_TERMS,
    RAM_SEARCH_TERMS,
    SEARCH_RADIUS_KM,
)
from filters import (
    normalize_url,
    is_cpu_compatible,
    is_ram_compatible,
    determine_status,
)

logger = logging.getLogger(__name__)


class FacebookMarketplaceSession:
    """
    Manages Facebook Marketplace search passes within the authenticated user profile.
    """

    def __init__(self, headless: bool = True, **kwargs):
        self.headless = headless
        self.user_data_dir = os.path.expanduser("~/.config/facebook_search_profile")

    def _parse_price_text(self, price_str: str) -> float:
        """Parses price text like '$45', 'CA$80', 'FREE' to float CAD value."""
        if not price_str:
            return 0.0
        cleaned = price_str.upper().replace("CA$", "").replace("$", "").replace(",", "").strip()
        if "FREE" in cleaned:
            return 0.0
        match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
        return 0.0

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
        Parses a single FB Marketplace item card, applies compatibility & scam filters,
        and sets Location Match Type to 'Confirmed within-radius (Marketplace filter)'.
        """
        if not title or not raw_url:
            return None

        title = title.strip()
        if category == "CPU" and not is_cpu_compatible(title):
            return None
        if category == "RAM" and not is_ram_compatible(title):
            return None

        price_val = self._parse_price_text(price_str)
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
        Executes search passes on Facebook Marketplace using the signed-in profile.
        """
        listings: List[ListingItem] = []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("Playwright not available. Skipping live FB browser run.")
            return listings

        try:
            with sync_playwright() as p:
                # Use persistent context from the user's login session
                context = p.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    headless=self.headless,
                    viewport={"width": 1280, "height": 800},
                    locale="en-CA",
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = context.pages[0] if context.pages else context.new_page()

                # Test navigation to marketplace
                page.goto("https://www.facebook.com/marketplace/newmarket/search", timeout=30000)
                page.wait_for_timeout(2000)

                page_content = page.content().lower()
                if "log into facebook" in page_content or "login" in page.url.lower() or "checkpoint" in page.url.lower():
                    logger.warning("Facebook session expired or login required — please re-log in manually.")
                    print("\n[WARNING] Facebook session expired or login required — please log in manually in Chrome.")
                    context.close()
                    return listings

                # 1. Search CPUs (Model-specific, Socket, and Broad queries)
                fb_cpu_terms = [
                    "i7-7700K",
                    "i7-6700K",
                    "i7-7700",
                    "i7-6700",
                    "LGA1151 CPU",
                    "LGA 1151",
                    "Intel Core i7",
                    "Intel CPU",
                    "Xeon LGA 1151",
                ]
                for term in fb_cpu_terms:
                    query_url = f"https://www.facebook.com/marketplace/newmarket/search?query={term}&exact=false&radius={SEARCH_RADIUS_KM}"
                    try:
                        page.goto(query_url, timeout=25000)
                        page.wait_for_timeout(2000)

                        cards = page.query_selector_all("a[href*='/marketplace/item/']")
                        for card in cards[:25]:
                            href = card.get_attribute("href") or ""
                            full_url = f"https://www.facebook.com{href}" if href.startswith("/") else href
                            text_lines = [t.strip() for t in card.inner_text().split("\n") if t.strip()]

                            if len(text_lines) >= 2:
                                price_str = text_lines[0]
                                title = text_lines[1]
                                loc = text_lines[2] if len(text_lines) > 2 else "Newmarket, ON"
                                parsed = self.parse_raw_card(title, price_str, loc, full_url, "CPU")
                                if parsed:
                                    listings.append(parsed)
                    except Exception as q_err:
                        logger.debug(f"Error querying term {term}: {q_err}")

                # 2. Search RAM (DDR4 speeds, kits, and desktop queries)
                fb_ram_terms = [
                    "16GB DDR4 RAM",
                    "8GB DDR4 RAM",
                    "2x8GB DDR4",
                    "2x4GB DDR4",
                    "DDR4 Desktop RAM",
                    "DDR4 UDIMM",
                    "desktop RAM",
                ]
                for term in fb_ram_terms:
                    query_url = f"https://www.facebook.com/marketplace/newmarket/search?query={term}&exact=false&radius={SEARCH_RADIUS_KM}"
                    try:
                        page.goto(query_url, timeout=25000)
                        page.wait_for_timeout(2000)

                        cards = page.query_selector_all("a[href*='/marketplace/item/']")
                        for card in cards[:25]:
                            href = card.get_attribute("href") or ""
                            full_url = f"https://www.facebook.com{href}" if href.startswith("/") else href
                            text_lines = [t.strip() for t in card.inner_text().split("\n") if t.strip()]

                            if len(text_lines) >= 2:
                                price_str = text_lines[0]
                                title = text_lines[1]
                                loc = text_lines[2] if len(text_lines) > 2 else "Newmarket, ON"
                                parsed = self.parse_raw_card(title, price_str, loc, full_url, "RAM")
                                if parsed:
                                    listings.append(parsed)
                    except Exception as q_err:
                        logger.debug(f"Error querying RAM term {term}: {q_err}")

                context.close()

        except Exception as e:
            logger.warning(f"Facebook Marketplace pass encountered an issue: {e}. Proceeding with eBay results.")
            print(f"\n[INFO] Facebook Marketplace note: {e}. Continuing with eBay pipeline.")

        return listings
