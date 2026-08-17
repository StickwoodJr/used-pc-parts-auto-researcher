"""
FastAPI Live Updating Web Dashboard Server for PC Parts Auto Researcher.
"""

import os
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ebay_client import ListingItem
from data_processor import DataProcessor
from sheets_manager import SheetsManager
from filters import is_canadian_location, is_local_20km

logger = logging.getLogger(__name__)

app = FastAPI(title="PC Parts Auto Researcher Dashboard")

# Global in-memory cache of current listings
CACHE = {
    "last_updated": None,
    "is_scanning": False,
    "raw_listings": [],
    "buckets": {},
    "top_5_by_model": {},
    "top_5_overall_cpus": [],
    "top_local_cpus": [],
    "top_local_ram": [],
}


def load_cached_data_from_sheet_or_files():
    """Loads latest listings from Google Sheets or local cache."""
    sheets_mgr = SheetsManager()
    all_items: List[ListingItem] = []

    if sheets_mgr.is_configured() and sheets_mgr.connect():
        try:
            raw_rows = sheets_mgr.worksheet.get_all_values()
            if len(raw_rows) > 1:
                for r in raw_rows[1:]:
                    if len(r) > 6 and r[6].strip():
                        loc_str = r[5] if len(r) > 5 else ""
                        if not is_canadian_location(loc_str):
                            continue
                        try:
                            price_val = float(str(r[3]).replace("$", "").replace(",", "").strip())
                        except (ValueError, TypeError):
                            price_val = 0.0
                        all_items.append(
                            ListingItem(
                                date_found=r[0] if len(r) > 0 else "",
                                category=r[1] if len(r) > 1 else "",
                                title=r[2] if len(r) > 2 else "",
                                price=price_val,
                                condition=r[4] if len(r) > 4 else "Used",
                                location=loc_str,
                                listing_url=r[6],
                                status=r[7] if len(r) > 7 else "New",
                                location_match_type=r[8] if len(r) > 8 else "",
                            )
                        )
        except Exception as e:
            logger.error(f"Failed to read from Google Sheet: {e}")

    processor = DataProcessor()
    buckets = processor.process_all_listings(all_items)

    CACHE["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    CACHE["raw_listings"] = all_items
    CACHE["buckets"] = buckets
    CACHE["top_5_by_model"] = processor.get_top_5_per_model(buckets)
    CACHE["top_5_overall_cpus"] = processor.get_top_5_overall_cpus(buckets)
    CACHE["top_local_cpus"] = processor.get_top_local_20km_cpus(buckets)
    CACHE["top_local_ram"] = processor.get_top_local_20km_ram(buckets)


# Warm cache immediately
try:
    load_cached_data_from_sheet_or_files()
except Exception as err:
    logger.warning(f"Initial cache warm failed: {err}")


@app.on_event("startup")
def startup_event():
    load_cached_data_from_sheet_or_files()


@app.get("/api/stats")
def get_stats():
    """Returns top-level metrics for dashboard header."""
    all_items = CACHE.get("raw_listings", [])
    local_count = sum(1 for it in all_items if is_local_20km(it.location))
    cpu_count = sum(1 for it in all_items if it.category.upper() == "CPU")
    ram_count = sum(1 for it in all_items if it.category.upper() == "RAM")

    return {
        "total_verified_canadian": len(all_items),
        "total_local_20km": local_count,
        "total_cpus": cpu_count,
        "total_ram": ram_count,
        "last_updated": CACHE.get("last_updated", "Just now"),
        "is_scanning": CACHE.get("is_scanning", False),
    }


@app.get("/api/summary")
def get_summary():
    """Returns Master Summary rankings (Overall Top 5 CPUs, Top 5 per model, Top 5 RAM)."""
    return {
        "top_5_overall_cpus": [it.model_dump() for it in CACHE.get("top_5_overall_cpus", [])],
        "top_5_by_model": {
            model: [it.model_dump() for it in items]
            for model, items in CACHE.get("top_5_by_model", {}).items()
        },
        "last_updated": CACHE.get("last_updated"),
    }


@app.get("/api/local")
def get_local_summary():
    """Returns Top local deals strictly within 20km of Newmarket, ON."""
    return {
        "top_local_cpus": [it.model_dump() for it in CACHE.get("top_local_cpus", [])],
        "top_local_ram": [it.model_dump() for it in CACHE.get("top_local_ram", [])],
        "last_updated": CACHE.get("last_updated"),
    }


@app.get("/api/listings")
def get_listings(
    category: Optional[str] = Query(None, description="CPU or RAM"),
    model: Optional[str] = Query(None, description="Model bucket filter"),
    local_only: bool = Query(False, description="Filter to within 20km only"),
    search: Optional[str] = Query(None, description="Keyword search in title or location"),
    sort_by: str = Query("overall_score", description="Sort parameter"),
    limit: int = Query(100, description="Max listings to return"),
):
    """Returns filtered, sorted listings for explorer view."""
    all_items: List[ListingItem] = []
    for items in CACHE.get("buckets", {}).values():
        all_items.extend(items)

    # Filter out flagged scam items by default unless searched
    filtered = [it for it in all_items if not it.status.startswith("Flagged")]

    if category:
        filtered = [it for it in filtered if it.category.upper() == category.upper()]

    if model:
        filtered = [it for it in filtered if model.lower() in it.model_bucket.lower()]

    if local_only:
        filtered = [it for it in filtered if is_local_20km(it.location)]

    if search:
        s = search.lower().strip()
        filtered = [it for it in filtered if s in it.title.lower() or s in it.location.lower() or s in it.model_bucket.lower()]

    # Sorting
    if sort_by == "overall_score":
        filtered.sort(key=lambda x: x.overall_score, reverse=True)
    elif sort_by == "benchmark_score":
        filtered.sort(key=lambda x: x.benchmark_score, reverse=True)
    elif sort_by == "price_asc":
        filtered.sort(key=lambda x: x.price)
    elif sort_by == "price_desc":
        filtered.sort(key=lambda x: x.price, reverse=True)
    elif sort_by == "trust_score":
        filtered.sort(key=lambda x: x.trust_score, reverse=True)
    elif sort_by == "date_found":
        filtered.sort(key=lambda x: x.date_found, reverse=True)

    return {
        "total": len(filtered),
        "listings": [it.model_dump() for it in filtered[:limit]],
    }


def run_pipeline_task():
    """Background task to run main search pipeline and reload cache."""
    CACHE["is_scanning"] = True
    try:
        from main import run_pipeline
        run_pipeline(dry_run=False, use_mock=False)
        load_cached_data_from_sheet_or_files()
    except Exception as e:
        logger.error(f"Error during refresh pipeline: {e}")
    finally:
        CACHE["is_scanning"] = False


@app.post("/api/refresh")
def trigger_refresh(background_tasks: BackgroundTasks):
    """Triggers an on-demand scan across eBay and Facebook Marketplace."""
    if CACHE.get("is_scanning"):
        return {"status": "already_running", "message": "Search cycle currently in progress."}

    background_tasks.add_task(run_pipeline_task)
    return {"status": "started", "message": "Live search cycle started in background."}


# Mount static assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def serve_index():
    """Serves the dashboard single page application."""
    index_file = os.path.join(static_dir, "index.html")
    return FileResponse(index_file)
