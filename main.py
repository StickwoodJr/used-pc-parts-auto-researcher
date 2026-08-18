"""
Main runner for PC Parts Search & Tracker.
Orchestrates eBay Browse API, Facebook Marketplace session, deduplication,
Google Sheets sync, and reporting.
"""

import sys
import argparse
import logging
from typing import List
from ebay_client import EbayClient, ListingItem
from ebay_browser_scraper import EbayBrowserScraper
from fb_marketplace_session import FacebookMarketplaceSession
from sheets_manager import SheetsManager, MockSheetsManager
from data_processor import DataProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def generate_mock_fixtures() -> List[ListingItem]:
    """Generates a realistic test dataset representing both eBay and FB Marketplace."""
    return [
        ListingItem(
            category="CPU",
            title="Intel Core i7-6700 3.40GHz Quad-Core LGA1151 CPU",
            price=65.00,
            condition="Used",
            location="Newmarket, ON",
            listing_url="https://www.ebay.ca/itm/112233445566?hash=item1&campid=99",
            status="New",
            location_match_type="Confirmed within-radius (Local Pickup)",
            source="eBay Browser",
        ),
        ListingItem(
            category="CPU",
            title="Intel Core i7-7700K 4.2GHz LGA1151 Processor",
            price=110.00,
            condition="Used",
            location="Aurora, ON",
            listing_url="https://www.ebay.ca/itm/223344556677?_trkparms=abc",
            status="New",
            location_match_type="Approximate location match",
            source="eBay Browser",
        ),
        ListingItem(
            category="CPU",
            title="Intel Xeon E3-1240 v6 3.70GHz LGA1151 CPU",
            price=75.00,
            condition="Used",
            location="Bradford, ON",
            listing_url="https://www.facebook.com/marketplace/item/334455667788990/?ref=search",
            status="New",
            location_match_type="Confirmed within-radius (Marketplace filter)",
            source="Facebook Marketplace",
        ),
        ListingItem(
            category="CPU",
            title="Intel Core i7-6700K Quad Core - $12 Fast Sale",
            price=12.00,
            condition="Used",
            location="Newmarket, ON",
            listing_url="https://www.facebook.com/marketplace/item/445566778899001/?ref=search",
            status="Flagged-Scam",
            location_match_type="Confirmed within-radius (Marketplace filter)",
            source="Facebook Marketplace",
        ),
        ListingItem(
            category="RAM",
            title="Corsair Vengeance LPX 16GB (2x8GB) DDR4 3200MHz Desktop RAM",
            price=40.00,
            condition="Used",
            location="Newmarket, ON",
            listing_url="https://www.ebay.ca/itm/556677889900?epid=123",
            status="New",
            location_match_type="Confirmed within-radius (Local Pickup)",
            source="eBay Browser",
        ),
        ListingItem(
            category="RAM",
            title="Kingston 8GB (1x8GB) DDR4 2666MHz Desktop UDIMM",
            price=20.00,
            condition="Used",
            location="Richmond Hill, ON",
            listing_url="https://www.facebook.com/marketplace/item/667788990011223/?ref=search",
            status="New",
            location_match_type="Confirmed within-radius (Marketplace filter)",
            source="Facebook Marketplace",
        ),
        ListingItem(
            category="RAM",
            title="DDR4 8GB Desktop RAM Stick - $5",
            price=5.00,
            condition="Used",
            location="Newmarket, ON",
            listing_url="https://www.ebay.ca/itm/778899001122?hash=item77",
            status="Flagged-Scam",
            location_match_type="Confirmed within-radius (Local Pickup)",
            source="eBay Browser",
        ),
    ]


def run_pipeline(mock: bool = False, dry_run: bool = False, shared_mock_sheet: MockSheetsManager = None) -> List[ListingItem]:
    """
    Executes the search, deduplication, and synchronization pipeline.
    """
    print("\n" + "=" * 70)
    print("  PC PARTS AUTO RESEARCHER (CPU & RAM) — RUNNING SEARCH CHECK")
    print("=" * 70)

    all_discovered_items: List[ListingItem] = []

    if mock:
        print("[MODE] Running in MOCK mode (using fixture data for validation).")
        raw_items = generate_mock_fixtures()
        all_discovered_items.extend(raw_items)
    else:
        # 1. Query eBay (Direct Web/Browser Scraper or API fallback)
        print("[1/3] Querying eBay.ca (Local Pickup + National Proximity)...")
        ebay_api = EbayClient()
        if ebay_api.is_configured():
            print("      -> Using configured eBay Developer API...")
            ebay_items = ebay_api.search_cpu_and_ram()
        else:
            print("      -> Using direct eBay.ca browser scraper (no API wait)...")
            ebay_scraper = EbayBrowserScraper()
            ebay_items = ebay_scraper.search_cpu_and_ram()

        print(f"      -> Found {len(ebay_items)} matching eBay listings.")
        all_discovered_items.extend(ebay_items)

        # 2. Run Facebook Marketplace Session (Pre-authenticated profile)
        print("[2/3] Querying Facebook Marketplace session (Newmarket, ON 20km)...")
        fb = FacebookMarketplaceSession(headless=True)
        fb_items = fb.search_cpu_and_ram()
        print(f"      -> Found {len(fb_items)} matching Facebook Marketplace listings.")
        all_discovered_items.extend(fb_items)

    print(f"\n[3/3] Total compatible listings collected: {len(all_discovered_items)}")

    # 3. Synchronize with Google Sheet / Deduplicate
    newly_added: List[ListingItem] = []
    total_count = 0

    if mock or dry_run:
        sheet_mgr = shared_mock_sheet if shared_mock_sheet is not None else MockSheetsManager()
        newly_added, total_count = sheet_mgr.sync_listings(all_discovered_items)
        print(f"      -> [MOCK SHEET] Added {len(newly_added)} new items. Total items in sheet: {total_count}")
    else:
        sheet_mgr = SheetsManager()
        if sheet_mgr.is_configured():
            try:
                newly_added, total_count = sheet_mgr.sync_listings(all_discovered_items)
                print(f"      -> [GOOGLE SHEET] Added {len(newly_added)} new items. Total in sheet: {total_count}")
            except Exception as e:
                logger.error(f"Google Sheets sync failed: {e}")
                print(f"      -> [ERROR] Failed syncing to Google Sheet: {e}")
        else:
            print(f"      -> [INFO] Google Service Account '{sheet_mgr.service_account_file}' not found.")
            print("         Please place your service_account.json in the project root to enable live Sheet sync.")

    # 4. Summary of Top Picks and New Findings
    processor = DataProcessor()
    buckets = processor.process_all_listings(all_discovered_items)
    top_5_by_model = processor.get_top_5_per_model(buckets)
    top_5_overall_cpus = processor.get_top_5_overall_cpus(buckets)
    top_local_cpus = processor.get_top_local_20km_cpus(buckets)
    top_local_ram = processor.get_top_local_20km_ram(buckets)

    print("\n" + "=" * 70)
    print("📍 LOCAL 20km RADIUS TOP PICKS (NEWMARKET & SURROUNDING)")
    print("=" * 70)
    if top_local_cpus:
        print("\n🔹 Top Local 20km CPUs:")
        for rank, item in enumerate(top_local_cpus[:3], start=1):
            seller_str = f" | Seller: {item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else ""
            print(f"   #{rank} [{item.model_bucket.replace('CPU - ', '')}] CAD ${item.price:.2f} — {item.title}")
            print(f"      • PassMark: {item.benchmark_score:,} pts | Overall: {item.overall_score:.1f}/100 | Loc: {item.location}{seller_str}")
            print(f"      • Link: {item.listing_url}")
    else:
        print("\n🔹 No active local 20km CPU listings found at this time.")

    if top_local_ram:
        print("\n🔹 Top Local 20km RAM:")
        for rank, item in enumerate(top_local_ram[:3], start=1):
            seller_str = f" | Seller: {item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else ""
            print(f"   #{rank} CAD ${item.price:.2f} — {item.title}")
            print(f"      • Trust: {item.trust_score:.0f}/100 | Loc: {item.location}{seller_str}")
            print(f"      • Link: {item.listing_url}")
    else:
        print("\n🔹 No active local 20km RAM listings found at this time.")

    print("\n" + "=" * 70)
    print("🥇 TOP 5 OVERALL BEST CPUs (PERFORMANCE + VALUE + TRUST)")
    print("=" * 70)
    for rank, item in enumerate(top_5_overall_cpus, start=1):
        seller_str = f" | Seller: {item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else ""
        print(f"#{rank} [{item.model_bucket.replace('CPU - ', '')}] CAD ${item.price:.2f} — {item.title}")
        print(f"   • PassMark: {item.benchmark_score:,} pts | Overall Score: {item.overall_score:.1f}/100 | Trust: {item.trust_score:.0f}/100")
        print(f"   • Location: {item.location} ({item.location_match_type}){seller_str}")
        print(f"   • Link: {item.listing_url}\n")

    print("=" * 70)
    print("🏆 MASTER SUMMARY — TOP RECOMMENDED PICKS PER HARDWARE MODEL")
    print("=" * 70)

    for model, items in top_5_by_model.items():
        if not items:
            continue
        print(f"\n📌 {model.upper()} (Top Value Deals):")
        for rank, item in enumerate(items[:3], start=1):  # Show top 3 in terminal
            seller_str = f" | Seller: {item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else ""
            print(f"   #{rank} [CAD ${item.price:.2f}] {item.title}")
            print(f"      • Trust: {item.trust_score:.0f}/100 | Loc: {item.location} ({item.location_match_type}){seller_str}")
            print(f"      • Link: {item.listing_url}")

    print("\n" + "-" * 70)
    print(f"SUMMARY OF NEW LISTINGS DISCOVERED THIS CYCLE ({len(newly_added)} NEW)")
    print("-" * 70)

    if not newly_added:
        print("No new listings found in this cycle. All existing listings are already tracked.")
    else:
        for idx, item in enumerate(newly_added[:15], start=1):
            scam_warning = f" [⚠️ {item.status}]" if item.status != "Verified-Good" and item.status != "New" else ""
            print(f"\n{idx}. [{item.category}] {item.title}{scam_warning}")
            print(f"   • Price: CAD ${item.price:.2f}")
            print(f"   • Condition: {item.condition} | Trust: {item.trust_score:.0f}/100")
            print(f"   • Location: {item.location} ({item.location_match_type})")
            print(f"   • Source: {item.source}")
            print(f"   • URL: {item.listing_url}")

    print("-" * 70 + "\n")
    return newly_added


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PC Parts Search & Tracker (CPU & RAM)")
    parser.add_argument("--mock", action="store_true", help="Run with mock data fixtures")
    parser.add_argument("--dry-run", action="store_true", help="Run search without modifying live Google Sheet")
    args = parser.parse_args()

    run_pipeline(mock=args.mock, dry_run=args.dry_run)
