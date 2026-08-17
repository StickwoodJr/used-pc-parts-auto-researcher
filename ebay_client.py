"""
eBay Browse API client supporting dual-mode local search, native CAD pricing,
exponential backoff retries, and cross-mode deduplication.
"""

import base64
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests
from pydantic import BaseModel, Field

from config import (
    EBAY_CLIENT_ID,
    EBAY_CLIENT_SECRET,
    EBAY_OAUTH_URL,
    EBAY_BROWSE_API_URL,
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
    determine_status,
)

logger = logging.getLogger(__name__)


class ListingItem(BaseModel):
    date_found: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    category: str
    title: str
    price: float
    condition: str
    location: str
    listing_url: str
    status: str = "New"
    location_match_type: str
    source: str = "eBay API"
    seller_name: str = ""
    seller_rating_pct: float = 100.0
    seller_feedback_count: int = 0
    seller_badge: str = ""
    trust_score: float = 70.0
    composite_score: float = 0.0
    benchmark_score: int = 0
    overall_score: float = 0.0
    model_bucket: str = ""

    def to_row(self) -> List[Any]:
        return [
            self.date_found,
            self.category,
            self.title,
            self.price,
            self.condition,
            self.location,
            self.listing_url,
            self.status,
            self.location_match_type,
            f"{self.seller_rating_pct:.1f}% ({self.seller_feedback_count})" if self.seller_feedback_count > 0 else "New/Unrated",
            f"{self.trust_score:.0f}/100",
            f"{self.composite_score:.1f}",
        ]


class EbayClient:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or EBAY_CLIENT_ID
        self.client_secret = client_secret or EBAY_CLIENT_SECRET
        self.access_token: Optional[str] = None
        self.token_expiry: float = 0.0

    def is_configured(self) -> bool:
        """Returns True if eBay API credentials are provided."""
        return bool(self.client_id and self.client_secret and self.client_id != "your_ebay_client_id_here")

    def _get_access_token(self) -> str:
        """
        Retrieves or refreshes OAuth2 Application Token using Client Credentials grant.
        """
        if self.access_token and time.time() < self.token_expiry - 60:
            return self.access_token

        if not self.is_configured():
            raise ValueError("eBay Client ID and Client Secret must be configured in .env")

        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_creds = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

        headers = {
            "Authorization": f"Basic {encoded_creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }

        # Backoff retry for token generation
        for attempt in range(1, 4):
            try:
                response = requests.post(EBAY_OAUTH_URL, headers=headers, data=data, timeout=15)
                if response.status_code == 200:
                    payload = response.json()
                    self.access_token = payload["access_token"]
                    self.token_expiry = time.time() + payload.get("expires_in", 7200)
                    return self.access_token
                elif response.status_code in (429, 500, 502, 503, 504):
                    logger.warning(f"OAuth token request received {response.status_code}. Retry {attempt}/3...")
                    time.sleep(2 ** attempt)
                else:
                    response.raise_for_status()
            except requests.RequestException as e:
                if attempt == 3:
                    raise RuntimeError(f"Failed to obtain eBay OAuth token after 3 attempts: {e}") from e
                time.sleep(2 ** attempt)

        raise RuntimeError("Failed to obtain eBay OAuth token.")

    def _execute_search_query(self, query: str, filter_str: str) -> List[Dict[str, Any]]:
        """
        Calls eBay Browse API search endpoint with exponential backoff and EBAY_CA header.
        """
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_CA",
            "Content-Type": "application/json",
        }
        params = {
            "q": query,
            "filter": filter_str,
            "limit": "50",
        }

        for attempt in range(1, 4):
            try:
                resp = requests.get(EBAY_BROWSE_API_URL, headers=headers, params=params, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("itemSummaries", [])
                elif resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(f"eBay search ({query}) received {resp.status_code}. Retry {attempt}/3...")
                    time.sleep(2 ** attempt)
                elif resp.status_code == 404 or "itemSummaries" not in resp.text:
                    return []
                else:
                    logger.error(f"eBay API error ({resp.status_code}): {resp.text}")
                    return []
            except requests.RequestException as e:
                if attempt == 3:
                    logger.error(f"eBay search error after 3 attempts: {e}")
                    return []
                time.sleep(2 ** attempt)

        return []

    def _parse_item(self, item: Dict[str, Any], category: str, location_match_type: str) -> Optional[ListingItem]:
        """
        Parses raw eBay JSON item, runs compatibility filters, and returns ListingItem.
        """
        title = item.get("title", "").strip()
        if not title:
            return None

        # Filter compatibility
        if category == "CPU" and not is_cpu_compatible(title):
            return None
        if category == "RAM" and not is_ram_compatible(title):
            return None

        # Price in CAD (native via EBAY_CA)
        price_obj = item.get("price", {})
        try:
            price_val = float(price_obj.get("value", 0.0))
        except (ValueError, TypeError):
            price_val = 0.0

        condition = item.get("condition", "Used")
        
        # Location string
        loc_obj = item.get("itemLocation", {})
        city = loc_obj.get("city", "")
        state_or_province = loc_obj.get("stateOrProvince", "")
        country = loc_obj.get("country", "")
        postal_code = loc_obj.get("postalCode", "")
        
        loc_parts = [p for p in [city, state_or_province, postal_code, country] if p]
        location_str = ", ".join(loc_parts) if loc_parts else "Canada"

        raw_url = item.get("itemWebUrl") or f"https://www.ebay.ca/itm/{item.get('itemId')}"
        canonical_url = normalize_url(raw_url)

        status = determine_status(price_val, category)

        return ListingItem(
            category=category,
            title=title,
            price=price_val,
            condition=condition,
            location=location_str,
            listing_url=canonical_url,
            status=status,
            location_match_type=location_match_type,
            source="eBay API",
        )

    def search_cpu_and_ram(self) -> List[ListingItem]:
        """
        Executes dual-mode search (Pickup Radius + National GTA Proximity) for CPU and RAM,
        then merges and deduplicates across modes with priority resolution.
        """
        if not self.is_configured():
            logger.warning("eBay credentials not configured. Skipping live eBay search.")
            return []

        # Mode 1 filter: local pickup within radius
        # Note: eBay Browse API supports pickupRadius / buyerPostalCode or distance filters
        mode1_filter = (
            f"deliveryOptions:{{SELLER_ARRANGED_LOCAL_PICKUP}},"
            f"itemLocationCountry:CA,"
            f"pickupRadius:{SEARCH_RADIUS_KM}km,"
            f"buyerPostalCode:{SEARCH_POSTAL_CODE}"
        )
        
        # Mode 2 filter: all Canada listings (to be post-filtered in Python for proximity)
        mode2_filter = "itemLocationCountry:CA"

        raw_mode1_items: List[ListingItem] = []
        raw_mode2_items: List[ListingItem] = []

        # 1. Search CPUs
        for term in CPU_SEARCH_TERMS:
            # Mode 1
            m1_results = self._execute_search_query(term, mode1_filter)
            for it in m1_results:
                parsed = self._parse_item(it, "CPU", "Confirmed within-radius (Local Pickup)")
                if parsed:
                    raw_mode1_items.append(parsed)

            # Mode 2
            m2_results = self._execute_search_query(term, mode2_filter)
            for it in m2_results:
                # Proximity check for Mode 2
                loc_obj = it.get("itemLocation", {})
                loc_str = f"{loc_obj.get('city', '')} {loc_obj.get('stateOrProvince', '')} {loc_obj.get('postalCode', '')}"
                if is_proximity_match(loc_str):
                    parsed = self._parse_item(it, "CPU", "Approximate location match")
                    if parsed:
                        raw_mode2_items.append(parsed)

        # 2. Search RAM
        for term in RAM_SEARCH_TERMS:
            # Mode 1
            m1_results = self._execute_search_query(term, mode1_filter)
            for it in m1_results:
                parsed = self._parse_item(it, "RAM", "Confirmed within-radius (Local Pickup)")
                if parsed:
                    raw_mode1_items.append(parsed)

            # Mode 2
            m2_results = self._execute_search_query(term, mode2_filter)
            for it in m2_results:
                loc_obj = it.get("itemLocation", {})
                loc_str = f"{loc_obj.get('city', '')} {loc_obj.get('stateOrProvince', '')} {loc_obj.get('postalCode', '')}"
                if is_proximity_match(loc_str):
                    parsed = self._parse_item(it, "RAM", "Approximate location match")
                    if parsed:
                        raw_mode2_items.append(parsed)

        # 3. Cross-Mode Deduplication & Priority Merging
        merged_by_url: Dict[str, ListingItem] = {}

        # Add Mode 2 (Approximate) first
        for item in raw_mode2_items:
            merged_by_url[item.listing_url] = item

        # Mode 1 (Confirmed Local Pickup) takes priority
        for item in raw_mode1_items:
            merged_by_url[item.listing_url] = item

        return list(merged_by_url.values())
