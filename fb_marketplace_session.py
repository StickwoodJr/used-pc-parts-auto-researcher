"""
Robust Facebook Marketplace scraper using persistent authenticated browser session.
Features explicit waits, JSON script-tag & GraphQL network response parsing,
DOM fallback extraction, human-like pacing, and strict Canadian compatibility filtering.
"""

import os
import re
import time
import json
import random
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus

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

    def __init__(self, user_data_dir: str = DEFAULT_PROFILE_DIR, headless: bool = False):
        self.user_data_dir = user_data_dir
        self.headless = headless

    def _parse_price_from_json(self, price_obj: Any) -> float:
        """Parses price from various Facebook JSON representations."""
        if price_obj is None:
            return 0.0
        if isinstance(price_obj, (int, float)):
            return float(price_obj)
        if isinstance(price_obj, str):
            m = re.search(r"[\d,]+(?:\.\d+)?", price_obj)
            return float(m.group(0).replace(",", "")) if m else 0.0
        if isinstance(price_obj, dict):
            if "amount" in price_obj and price_obj["amount"] is not None:
                try:
                    return float(str(price_obj["amount"]).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            if "formatted_amount" in price_obj:
                return self._parse_price_from_json(price_obj["formatted_amount"])
            if "formatted_price" in price_obj:
                return self._parse_price_from_json(price_obj["formatted_price"])
            if "text" in price_obj:
                return self._parse_price_from_json(price_obj["text"])
            if "amount_with_offset" in price_obj:
                try:
                    raw_amt = float(price_obj["amount_with_offset"])
                    offset = float(price_obj.get("offset", 100))
                    return raw_amt / (offset if offset > 0 else 100)
                except (ValueError, TypeError):
                    pass
        return 0.0

    def _parse_location_from_json(self, loc_obj: Any) -> str:
        """Extracts Canadian location string from Facebook JSON location objects."""
        if not loc_obj:
            return "Newmarket, ON"
        if isinstance(loc_obj, str):
            return loc_obj.strip() or "Newmarket, ON"
        if isinstance(loc_obj, dict):
            if "reverse_geocode" in loc_obj and isinstance(loc_obj["reverse_geocode"], dict):
                rg = loc_obj["reverse_geocode"]
                city = rg.get("city_name") or rg.get("city") or rg.get("name") or ""
                state = rg.get("state") or rg.get("province") or ""
                if city and state:
                    return f"{city}, {state}"
                if city:
                    return city
            city = loc_obj.get("city") or loc_obj.get("city_name") or loc_obj.get("name") or ""
            state = loc_obj.get("state") or loc_obj.get("province") or ""
            if city and state:
                return f"{city}, {state}"
            if "display_name" in loc_obj and loc_obj["display_name"]:
                return str(loc_obj["display_name"]).strip()
            if "text" in loc_obj and loc_obj["text"]:
                return str(loc_obj["text"]).strip()
        return "Newmarket, ON"

    def _find_marketplace_items_in_json(self, data: Any, items_list: List[Dict[str, Any]]) -> None:
        """Recursively traverses nested JSON/dict/list structures for MarketplaceProductItem objects."""
        if isinstance(data, dict):
            typename = data.get("__typename", "")
            if (
                typename in ("MarketplaceProductItem", "MarketplaceListing", "MarketplaceSearchFeedUnit")
                or ("id" in data and ("marketplace_listing_title" in data or "listing_price" in data))
            ):
                item_id = str(data.get("id") or "")
                title = (
                    data.get("marketplace_listing_title")
                    or data.get("title")
                    or data.get("listing_title")
                    or data.get("story_title")
                    or ""
                )
                price = self._parse_price_from_json(
                    data.get("listing_price") or data.get("price") or data.get("target_price")
                )
                loc = self._parse_location_from_json(
                    data.get("location")
                    or data.get("location_text")
                    or data.get("location_description")
                    or data.get("location_name")
                )
                if item_id and title:
                    items_list.append({
                        "id": item_id,
                        "title": str(title).strip(),
                        "price": price,
                        "location": loc,
                        "url": f"https://www.facebook.com/marketplace/item/{item_id}",
                    })
            for v in data.values():
                self._find_marketplace_items_in_json(v, items_list)
        elif isinstance(data, list):
            for elem in data:
                self._find_marketplace_items_in_json(elem, items_list)

    def _parse_json_dict_to_listing(self, item_dict: Dict[str, Any], category: str) -> Optional[ListingItem]:
        """Converts an extracted JSON item dict to a validated ListingItem."""
        title = item_dict.get("title", "").strip()
        if not title:
            return None

        if category == "CPU" and not is_cpu_compatible(title):
            return None
        if category == "RAM" and not is_ram_compatible(title):
            return None

        loc = item_dict.get("location", "Newmarket, ON")
        if not is_canadian_location(loc):
            return None

        price = float(item_dict.get("price", 0.0))
        raw_url = item_dict.get("url", "")
        canonical_url = normalize_url(raw_url)
        if not canonical_url:
            return None

        status = determine_status(price, category)
        return ListingItem(
            category=category,
            title=title,
            price=price,
            condition="Used",
            location=loc,
            listing_url=canonical_url,
            status=status,
            location_match_type="Confirmed within-radius (Marketplace filter)",
            source="Facebook Marketplace",
        )

    def _parse_card_text_robust(self, text_lines: List[str]) -> Optional[Dict[str, Any]]:
        """
        Robust fallback parser for Facebook Marketplace card DOM lines:
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

    def _is_login_or_checkpoint(self, page_content: str, current_url: str) -> bool:
        """Checks if Facebook has redirected to a login page, checkpoint, or CAPTCHA."""
        url_lower = current_url.lower()
        content_lower = page_content.lower()
        if "/login" in url_lower or "login.php" in url_lower or "checkpoint" in url_lower:
            return True
        if "security check" in content_lower and "captcha" in content_lower:
            return True
        if "you must log in to continue" in content_lower:
            return True
        return False

    def search_cpu_and_ram(self) -> List[ListingItem]:
        """
        Executes comprehensive search passes across all CPU and RAM queries.
        Uses explicit waits, JSON script-tag extraction, network response capture,
        and robust DOM fallback parsing with human-like randomized pacing.
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

                # Secondary structured-data capture: network response listener
                network_captured_items: List[Dict[str, Any]] = []

                def handle_response(response):
                    try:
                        resp_url = response.url
                        if ("graphql" in resp_url or "marketplace" in resp_url) and response.status == 200:
                            ct = response.headers.get("content-type", "").lower()
                            if "json" in ct or "javascript" in ct:
                                try:
                                    resp_data = response.json()
                                    self._find_marketplace_items_in_json(resp_data, network_captured_items)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                page.on("response", handle_response)

                # Test navigation to marketplace root
                try:
                    page.goto("https://www.facebook.com/marketplace/newmarket/search", timeout=30000)
                    page.wait_for_timeout(random.uniform(1500, 2500))
                except Exception as nav_err:
                    logger.warning(f"Initial navigation error: {nav_err}")

                if self._is_login_or_checkpoint(page.content(), page.url):
                    logger.warning(
                        "Facebook session expired or login/checkpoint required. "
                        "Stopping search early and returning collected listings."
                    )
                    print("\n[WARNING] Facebook session expired or login/checkpoint required.")
                    context.close()
                    return listings

                all_search_tasks = [("CPU", term) for term in CPU_SEARCH_TERMS] + [
                    ("RAM", term) for term in RAM_SEARCH_TERMS
                ]

                for category, term in all_search_tasks:
                    query_url = (
                        f"https://www.facebook.com/marketplace/newmarket/search?"
                        f"query={quote_plus(term)}&exact=false&radius={SEARCH_RADIUS_KM}"
                    )
                    
                    found_count = 0
                    passed_count = 0
                    dupe_count = 0

                    try:
                        # Human pacing: randomized pause (3-7s) between queries
                        time.sleep(random.uniform(3.0, 7.0))

                        # Reset query-scoped network capture buffer
                        network_captured_items.clear()

                        page.goto(query_url, timeout=25000)

                        # Check for login wall or checkpoint
                        if self._is_login_or_checkpoint(page.content(), page.url):
                            logger.warning(
                                f"Login wall or checkpoint encountered during term '{term}'. "
                                "Halting search early to protect session."
                            )
                            break

                        # Explicit wait for listing item cards to appear
                        try:
                            page.wait_for_selector("a[href*='/marketplace/item/']", timeout=10000)
                        except Exception as wait_err:
                            logger.warning(f"No item selector appeared within timeout for '{term}': {wait_err}")

                        # Human-like infinite scrolling with randomized distance and pacing
                        num_scrolls = random.randint(3, 5)
                        for _ in range(num_scrolls):
                            scroll_px = random.randint(1200, 2200)
                            page.evaluate(f"window.scrollBy(0, {scroll_px})")
                            page.wait_for_timeout(random.uniform(800, 1800))

                        # --- 1. Primary Extraction: JSON from <script type="application/json"> tags ---
                        json_script_items: List[Dict[str, Any]] = []
                        try:
                            script_blobs = page.evaluate(
                                "() => Array.from(document.querySelectorAll('script[type=\"application/json\"]')).map(s => s.textContent || '')"
                            )
                            for blob in script_blobs:
                                if not blob or not blob.strip():
                                    continue
                                try:
                                    parsed_data = json.loads(blob)
                                    self._find_marketplace_items_in_json(parsed_data, json_script_items)
                                except (json.JSONDecodeError, TypeError, ValueError):
                                    continue
                        except Exception as json_err:
                            logger.debug(f"JSON script extraction failed for '{term}': {json_err}")

                        # Merge JSON script items + network captured items
                        combined_structured_items = json_script_items + list(network_captured_items)
                        found_count += len(combined_structured_items)

                        for item_dict in combined_structured_items:
                            parsed_listing = self._parse_json_dict_to_listing(item_dict, category)
                            if parsed_listing:
                                if parsed_listing.listing_url in seen_urls:
                                    dupe_count += 1
                                else:
                                    seen_urls.add(parsed_listing.listing_url)
                                    listings.append(parsed_listing)
                                    passed_count += 1

                        # --- 2. Fallback Extraction: DOM Card inner_text parsing ---
                        cards = page.query_selector_all("a[href*='/marketplace/item/']")
                        found_count += len(cards)

                        for card in cards:
                            href = card.get_attribute("href") or ""
                            canonical_url = normalize_url(
                                href if href.startswith("http") else f"https://www.facebook.com{href}"
                            )
                            if not canonical_url:
                                continue

                            if canonical_url in seen_urls:
                                dupe_count += 1
                                continue

                            text_lines = [t.strip() for t in card.inner_text().split("\n") if t.strip()]
                            parsed = self._parse_card_text_robust(text_lines)
                            if not parsed:
                                continue

                            title = parsed["title"]
                            if category == "CPU" and not is_cpu_compatible(title):
                                continue
                            if category == "RAM" and not is_ram_compatible(title):
                                continue

                            price_val = parsed["price"]
                            location = parsed["location"]
                            if not is_canadian_location(location):
                                continue

                            status = determine_status(price_val, category)
                            seen_urls.add(canonical_url)
                            listings.append(
                                ListingItem(
                                    category=category,
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
                            passed_count += 1

                        logger.debug(
                            f"[{category}] Query '{term}' summary: {found_count} raw items found, "
                            f"{passed_count} passed filters, {dupe_count} duplicates skipped."
                        )

                    except Exception as q_err:
                        logger.warning(f"Error querying {category} term '{term}': {q_err}")

                context.close()
        except Exception as e:
            logger.error(f"Error during Facebook Marketplace session: {e}")

        return listings
