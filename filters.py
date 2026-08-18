"""
Compatibility filters, URL normalizers, proximity checks, and scam detection rules.
"""

import re
from urllib.parse import urlparse
from typing import Optional
from config import (
    CPU_SCAM_PRICE_THRESHOLD,
    RAM_SCAM_PRICE_THRESHOLD,
    PROXIMITY_CITIES,
    PROXIMITY_POSTAL_PREFIXES,
)


def normalize_url(url: str) -> str:
    """
    Normalizes eBay and Facebook Marketplace URLs to their canonical form,
    stripping tracking query parameters (campid, hash, _trkparms, ref, etc.).
    """
    if not url:
        return ""
    
    url = url.strip()
    parsed = urlparse(url)
    
    # eBay Normalization: Extract item ID
    # Patterns: /itm/123456789012 or /itm/title-slug/123456789012
    if "ebay" in parsed.netloc.lower():
        match = re.search(r"/itm/(?:[^/]+/)?(\d{9,19})", parsed.path)
        if match:
            item_id = match.group(1)
            domain = "www.ebay.ca" if "ebay.ca" in parsed.netloc.lower() else parsed.netloc.lower()
            return f"https://{domain}/itm/{item_id}"
        # Fallback for other eBay links without /itm/
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")

    # Facebook Marketplace Normalization: Extract item ID
    # Pattern: /marketplace/item/123456789012345/
    if "facebook.com" in parsed.netloc.lower():
        match = re.search(r"/marketplace/item/(\d+)", parsed.path)
        if match:
            item_id = match.group(1)
            return f"https://www.facebook.com/marketplace/item/{item_id}"
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")

    # Generic URL normalization: Strip query params and fragments
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def is_cpu_compatible(title: str) -> bool:
    """
    Evaluates whether a CPU title matches LGA1151 6th/7th Gen Core i7 or Xeon E3 v5/v6.
    Explicitly rejects 8th/9th+ Gen, LGA1150/1155/1200/1700, and non-LGA1151 CPUs.
    """
    if not title:
        return False
    
    t = title.lower()

    # Reject non-Intel / AMD
    if re.search(r"\b(amd|ryzen|threadripper|athlon|am4|am5|epyc|opteron)\b", t):
        return False

    # Reject incompatible Intel Generations / Sockets
    # 8th/9th Gen (Coffee Lake)
    if re.search(r"\b(i[3579]-?8\d{3}[a-z]?|i[3579]-?9\d{3}[a-z]?|8700k?|9700k?|9900k?)\b", t):
        return False
    # 10th/11th Gen (Comet Lake / Rocket Lake - LGA1200)
    if re.search(r"\b(i[3579]-?10\d{3}[a-z]?|i[3579]-?11\d{3}[a-z]?|lga\s*1200)\b", t):
        return False
    # 12th/13th/14th Gen (Alder/Raptor Lake - LGA1700)
    if re.search(r"\b(i[3579]-?1[234]\d{3}[a-z]?|lga\s*1700)\b", t):
        return False
    # 2nd/3rd Gen (Sandy/Ivy Bridge - LGA1155)
    if re.search(r"\b(i[357]-?[23]\d{3}[a-z]?|2600k?|3770k?|lga\s*1155)\b", t):
        return False
    # 4th/5th Gen (Haswell/Broadwell - LGA1150)
    if re.search(r"\b(i[357]-?[45]\d{3}[a-z]?|4770k?|4790k?|lga\s*1150)\b", t):
        return False
    # Incompatible Xeon series (E5, E7, Scalable, Bronze, Silver, Gold, Platinum, v1, v2, v3, v4, v7, v8)
    if re.search(r"\b(e5-?\d{4}|e7-?\d{4}|lga\s*2011|lga\s*1366|lga\s*2066|scalable|silver|gold|platinum)\b", t):
        return False
    if re.search(r"\be3-?12\d{2}\s*v[1234789]\b", t):
        return False

    # Positive Match: Intel 6th & 7th Gen Core i7
    # i7-6700, i7-6700K, i7-6700T, i7-7700, i7-7700K, i7-7700T
    i7_pattern = r"\b(i7[- ]?(6700k?|6700t|7700k?|7700t)|core[- ]i7[- ](6700|7700)[kt]?)\b"
    if re.search(i7_pattern, t):
        return True

    # Positive Match: Xeon E3-1200 v5 & v6 series
    # Examples: E3-1220 v5, E3-1230 v5, E3-1240 v5, E3-1245 v5, E3-1270 v5, E3-1275 v5, E3-1280 v5
    #           E3-1220 v6, E3-1230 v6, E3-1240 v6, E3-1245 v6, E3-1270 v6, E3-1275 v6, E3-1280 v6
    xeon_pattern = r"\b(e3[- ]?12[23478][05]\s*v[56]|xeon\s*e3[- ]12\d{2}\s*v[56])\b"
    if re.search(xeon_pattern, t):
        return True

    return False


def is_ram_compatible(title: str) -> bool:
    """
    Evaluates whether a RAM title matches Desktop DDR4 UDIMM (non-ECC) with 8GB stick capacity.
    Matches:
      - Single 8GB sticks (1x8GB, 8GB DDR4 UDIMM, 8GB 2400/2666/3200MHz)
      - 2x8GB kits (16GB kit consisting of two 8GB sticks)
    Rejects:
      - 4GB sticks and 2x4GB kits (4GB stick capacity)
      - Single 16GB / 32GB / 64GB modules
      - Laptop SODIMM, Server ECC/RDIMM, DDR3, DDR5.
    """
    if not title:
        return False
    
    t = title.lower()

    # Reject Laptop / Notebook / SODIMM
    if re.search(r"\b(sodimm|so-dimm|laptop|notebook|macbook|imac)\b", t):
        return False

    # Reject ECC / Registered / Server / RDIMM / LRDIMM
    if re.search(r"\b(rdimm|lrdimm|registered|buffered|server ram)\b", t):
        return False
    if re.search(r"\becc\b", t) and not re.search(r"\b(non-ecc|non ecc|unbuffered)\b", t):
        return False

    # Reject other DDR generations
    if re.search(r"\b(ddr3|ddr3l|ddr5|ddr2|pc3|pc5)\b", t):
        return False

    # Must be DDR4 (or PC4)
    if not re.search(r"\b(ddr4|pc4)\b", t):
        return False

    # Reject 4GB sticks / 2x4GB kits / 4-stick kits
    if re.search(r"\b(2x4gb|2\s*x\s*4gb|2x4g|1x4gb|4x8gb|4x16gb|4x4gb|kit of 4|4 sticks)\b", t):
        return False
    if re.search(r"\b4gb\b", t) and not re.search(r"\b(8gb|16gb)\b", t):
        return False

    # Reject 32GB / 64GB / 128GB modules
    if re.search(r"\b(32gb|32g|64gb|64g|128gb)\b", t):
        return False

    # Reject single 16GB sticks
    if re.search(r"\b(1x16gb|1\s*x\s*16gb|single\s*16gb|16gb\s*\(?1x16gb\)?)\b", t):
        return False

    # Positive Match 1: 2x8GB (Kit of two 8GB sticks)
    if re.search(r"\b(2x8gb|2\s*x\s*8gb|2x8g|16gb\s*\(?2x8gb\)?|16gb\s*kit\s*\(?2x8gb\)?|16gb\s*2x8|2x\s*8g)\b", t):
        return True

    # Positive Match 2: If title mentions 16GB total with explicit dual/2-stick indicator
    if re.search(r"\b16gb\b", t) and re.search(r"\b(2x|2 sticks|2x8|kit of 2|pair|dual)\b", t):
        return True

    # Reject ambiguous 16GB listings that don't indicate 2x8GB
    if re.search(r"\b16gb\b", t):
        return False

    # Positive Match 3: Single 8GB desktop stick
    if re.search(r"\b(1x8gb|1\s*x\s*8gb|8gb\s*\(?1x8gb\)?|single\s*8gb|8gb\s*(stick|dimm|udimm|module|ram|desktop|memory|2400|2666|3000|3200))\b", t):
        return True
    if re.search(r"\b8gb\b", t):
        return True

    return False


# Canadian Provinces and Territories
CANADIAN_PROVINCES = {
    "ontario", "quebec", "british columbia", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick", "newfoundland",
    "prince edward island", "pei", "yukon", "nunavut", "northwest territories", "nwt",
}

CANADIAN_PROVINCE_CODES = {
    "ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"
}

# Major Canadian Cities / Municipalities
CANADIAN_CITIES = {
    "newmarket", "aurora", "bradford", "richmond hill", "markham", "vaughan",
    "toronto", "mississauga", "brampton", "oakville", "burlington", "hamilton",
    "kitchener", "waterloo", "cambridge", "guelph", "london", "windsor",
    "barrie", "oshawa", "whitby", "ajax", "pickering", "stouffville",
    "king city", "east gwillimbury", "keswick", "georgina", "innisfil", "uxbridge",
    "ottawa", "montreal", "laval", "gatineau", "quebec", "quebec city", "sherbrooke",
    "vancouver", "burnaby", "surrey", "richmond", "coquitlam", "victoria", "kelowna",
    "calgary", "edmonton", "red deer", "lethbridge", "winnipeg", "saskatoon", "regina",
    "halifax", "moncton", "fredericton", "saint john", "st. john's", "st johns",
}

# Disqualified Foreign Countries & Regions
FOREIGN_COUNTRIES = {
    "united states", "usa", "u.s.", "u.s.a", "china", "hong kong", "taiwan",
    "united kingdom", "uk", "great britain", "germany", "deutschland", "japan",
    "australia", "france", "italy", "korea", "singapore", "india", "mexico",
    "spain", "netherlands", "poland", "russia", "brazil", "philippines",
    "vietnam", "malaysia", "israel", "switzerland", "sweden", "austria",
}

# US State names and common codes
US_STATES = {
    "california", "texas", "florida", "new york", "pennsylvania", "illinois",
    "ohio", "georgia", "north carolina", "michigan", "new jersey", "virginia",
    "washington", "arizona", "massachusetts", "tennessee", "indiana", "missouri",
    "maryland", "wisconsin", "colorado", "minnesota", "south carolina", "alabama",
    "louisiana", "kentucky", "oregon", "oklahoma", "connecticut", "utah", "iowa",
    "nevada", "arkansas", "mississippi", "kansas", "new mexico", "nebraska",
    "idaho", "west virginia", "hawaii", "new hampshire", "maine", "montana",
    "rhode island", "delaware", "south dakota", "north dakota", "alaska", "vermont", "wyoming",
}


def extract_located_in(card_text: str) -> Optional[str]:
    """
    Extracts the 'Located in: <location>' or 'Item location: <location>' string
    from listing text or HTML snippets.
    """
    if not card_text:
        return None

    # Matches "Located in: <location>", "Item location: <location>", "from <location>"
    match = re.search(
        r"(?:located\s+in|item\s+location|ships\s+from|from)\s*:\s*([^\n\r\|;]+)",
        card_text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    # Fallback to "from <City, Country>"
    match_from = re.search(r"\bfrom\s+([A-Z][a-zA-Z\s,]+(?:Canada|United States|USA|China|UK|Hong Kong|Japan))", card_text, re.IGNORECASE)
    if match_from:
        return match_from.group(1).strip()

    return None


def is_canadian_location(location_str: str) -> bool:
    """
    Strictly verifies whether a location is located within Canada.
    Explicitly rejects listings from the US, China, UK, and other foreign countries.
    Rejects generic unverified 'Canada' if it originates from international dropshippers.
    """
    if not location_str:
        return False

    loc_clean = location_str.lower().strip()

    # 1. Reject explicit foreign countries
    for country in FOREIGN_COUNTRIES:
        if re.search(rf"\b{re.escape(country)}\b", loc_clean):
            return False

    # 2. Reject US states
    for state in US_STATES:
        if re.search(rf"\b{re.escape(state)}\b", loc_clean):
            return False

    # 3. Reject US state abbreviation patterns (e.g., 'San Jose, CA', 'Miami, FL', 'Dallas, TX')
    if re.search(r",\s*(al|ak|az|ar|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)\b", loc_clean):
        return False
    if re.search(r"\bca\b.*\b(usa|united states)\b", loc_clean) or re.search(r"\b(usa|united states)\b.*\bca\b", loc_clean):
        return False

    # 4. Positive Match: Canadian Provinces / Territories
    for prov in CANADIAN_PROVINCES:
        if re.search(rf"\b{re.escape(prov)}\b", loc_clean):
            return True

    # 5. Positive Match: Canadian Cities / Municipalities
    for city in CANADIAN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", loc_clean):
            return True

    # 6. Positive Match: Canadian Postal Code (e.g. L3Y 8B4 or prefix L3Y)
    if re.search(r"\b[a-ceghj-npr-tvxy]\d[a-ceghj-npr-tv-z]\s*\d[a-ceghj-npr-tv-z]\d\b", loc_clean) or re.search(r"\b[a-ceghj-npr-tvxy]\d[a-ceghj-npr-tv-z]\b", loc_clean):
        return True

    # 7. Positive Match: Province Code in Canadian context (e.g. 'Newmarket, ON', 'Toronto, ON', 'ON, Canada')
    prov_match = re.search(r",\s*([a-z]{2})\b", loc_clean)
    if prov_match and prov_match.group(1).upper() in CANADIAN_PROVINCE_CODES:
        return True

    # 8. Verified Canadian city / region with explicit Canada (e.g. 'Ontario, Canada', 'Markham, Canada')
    if "canada" in loc_clean and any(p in loc_clean for p in CANADIAN_PROVINCE_CODES | CANADIAN_PROVINCES | CANADIAN_CITIES):
        return True

    return False


# 20km Immediate Local Radius around Newmarket, ON (L3Y 8B4)
LOCAL_20KM_CITIES = {
    "newmarket", "aurora", "bradford", "east gwillimbury", "holland landing",
    "sharon", "keswick", "king city", "stouffville", "whitchurch-stouffville",
    "oak ridges", "richmond hill", "innisfil",
}

LOCAL_20KM_POSTAL_PREFIXES = {
    "L3Y", "L3X", "L4G", "L3Z", "L9N", "L4P", "L7B", "L4A", "L4E", "L4C", "L4S"
}


def is_local_20km(location_str: str) -> bool:
    """
    Checks whether a location falls strictly within the ~20km immediate radius
    of Newmarket, ON (Aurora, Bradford, East Gwillimbury, King City, Keswick, Stouffville, Richmond Hill).
    """
    if not location_str or not is_canadian_location(location_str):
        return False

    loc_clean = location_str.lower().strip()

    # Check local city/municipality names
    for city in LOCAL_20KM_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", loc_clean):
            return True

    # Check local postal code prefixes
    postal_matches = re.findall(r"\b([a-z]\d[a-z])\b", loc_clean, re.IGNORECASE)
    for prefix in postal_matches:
        if prefix.upper() in LOCAL_20KM_POSTAL_PREFIXES:
            return True

    return False


def is_proximity_match(location_str: str) -> bool:
    """
    Checks whether a location string falls within proximity of Newmarket / GTA / York Region,
    and strictly verifies it is in Canada.
    """
    if not location_str or not is_canadian_location(location_str):
        return False
    
    loc_clean = location_str.lower().strip()

    # Check city / municipality matches
    for city in PROXIMITY_CITIES:
        if city in loc_clean:
            return True

    # Check postal code prefixes (e.g., L3Y, L4G, etc.)
    postal_matches = re.findall(r"\b([a-z]\d[a-z])\b", loc_clean, re.IGNORECASE)
    for prefix in postal_matches:
        if prefix.upper() in PROXIMITY_POSTAL_PREFIXES:
            return True

    return False


def determine_status(price: float, category: str) -> str:
    """
    Determines status (New vs Flagged-Scam) based on price thresholds.
    """
    if category.upper() == "CPU" and price < CPU_SCAM_PRICE_THRESHOLD:
        return "Flagged-Scam"
    if category.upper() == "RAM" and price < RAM_SCAM_PRICE_THRESHOLD:
        return "Flagged-Scam"
    return "New"
