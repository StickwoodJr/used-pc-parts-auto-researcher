"""
Configuration and settings for PC Parts Search & Tracker.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# eBay Configuration
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")
EBAY_ENVIRONMENT = os.getenv("EBAY_ENVIRONMENT", "PRODUCTION").upper()

if EBAY_ENVIRONMENT == "SANDBOX":
    EBAY_OAUTH_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    EBAY_BROWSE_API_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
else:
    EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    EBAY_BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# Google Sheets Configuration
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
GOOGLE_SHEET_TITLE = os.getenv("GOOGLE_SHEET_TITLE", "PC Parts Search - CPU & RAM")
GOOGLE_SHEET_TAB_NAME = os.getenv("GOOGLE_SHEET_TAB_NAME", "Listings")

# Location & Radius Filters
SEARCH_POSTAL_CODE = os.getenv("SEARCH_POSTAL_CODE", "L3Y8B4")
SEARCH_RADIUS_KM = int(os.getenv("SEARCH_RADIUS_KM", "20"))
SEARCH_CITY = "Newmarket"
SEARCH_PROVINCE = "ON"

# Pricing & Scam Flags
CPU_SCAM_PRICE_THRESHOLD = float(os.getenv("CPU_SCAM_PRICE_THRESHOLD", "20.0"))
RAM_SCAM_PRICE_THRESHOLD = float(os.getenv("RAM_SCAM_PRICE_THRESHOLD", "10.0"))

# Search Queries
CPU_SEARCH_TERMS = [
    "i7-6700",
    "i7-6700K",
    "i7-6700T",
    "i7-7700",
    "i7-7700K",
    "i7-7700T",
    "Xeon E3-1230 v5",
    "Xeon E3-1240 v5",
    "Xeon E3-1270 v5",
    "Xeon E3-1275 v5",
    "Xeon E3-1230 v6",
    "Xeon E3-1240 v6",
    "Xeon E3-1270 v6",
    "Xeon E3-1275 v6",
]

RAM_SEARCH_TERMS = [
    "8GB DDR4 RAM",
    "16GB DDR4 RAM",
    "2x8GB DDR4",
    "2x4GB DDR4",
    "16GB 2x8GB DDR4 desktop",
    "8GB DDR4 desktop UDIMM",
]

# Proximity matching for Newmarket / York Region / Greater Toronto Area (GTA)
PROXIMITY_CITIES = {
    "newmarket",
    "aurora",
    "bradford",
    "bradford west gwillimbury",
    "east gwillimbury",
    "holland landing",
    "sharon",
    "queensville",
    "mount albert",
    "richmond hill",
    "markham",
    "stouffville",
    "whitchurch-stouffville",
    "king city",
    "king",
    "nobleton",
    "schomberg",
    "vaughan",
    "maple",
    "woodbridge",
    "concord",
    "thornhill",
    "keswick",
    "georgina",
    "sutton",
    "innisfil",
    "barrie",
    "uxbridge",
    "toronto",
    "north york",
    "scarborough",
    "etobicoke",
    "york region",
    "simcoe",
    "gta",
    "greater toronto area",
}

PROXIMITY_POSTAL_PREFIXES = {
    "L3Y", "L3X", "L3Z", "L4G", "L9N", "L4A", "L4C", "L4B", "L4S", "L4E",
    "L6A", "L6B", "L6C", "L6E", "L3T", "L3P", "L3R", "L3S", "L4J", "L4K",
    "L4L", "L4H", "L7B", "L0G", "L4M", "L4N", "L9S", "L4P", "L0E",
}

# Sheet Schema Headers
SHEET_HEADERS = [
    "Date Found",
    "Category",
    "Title",
    "Price (CAD)",
    "Condition",
    "Location",
    "Listing URL",
    "Status",
    "Location Match Type",
    "Seller Rating & Count",
    "Trust Score",
    "Composite Score",
]

MASTER_SUMMARY_HEADERS = [
    "Rank",
    "Hardware Model",
    "Title",
    "Price (CAD)",
    "Seller Rating & Sales Count",
    "Trust Score",
    "Location & Match Type",
    "Listing URL",
]

MODEL_TABS = [
    "CPU - i7-6700",
    "CPU - i7-6700K",
    "CPU - i7-6700T",
    "CPU - i7-7700",
    "CPU - i7-7700K",
    "CPU - i7-7700T",
    "CPU - Xeon E3 v5-v6",
    "RAM - DDR4 UDIMM",
]
