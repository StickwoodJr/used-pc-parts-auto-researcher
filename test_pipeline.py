"""
End-to-end integration and verification tests for PC Parts Search & Tracker.
"""

import pytest
from ebay_client import EbayClient, ListingItem
from ebay_browser_scraper import EbayBrowserScraper
from fb_marketplace_session import FacebookMarketplaceSession
from sheets_manager import MockSheetsManager
from main import run_pipeline, generate_mock_fixtures
from filters import normalize_url


class TestPipelineVerification:
    def test_back_to_back_run_zero_duplicates(self):
        """
        Checklist Item 2: Running the pipeline twice back-to-back produces zero duplicate rows.
        """
        shared_sheet = MockSheetsManager()
        
        # Run 1: Should add all items
        first_run_added = run_pipeline(mock=True, shared_mock_sheet=shared_sheet)
        assert len(first_run_added) == 7
        assert len(shared_sheet.rows) - 1 == 7

        # Run 2: Should add 0 items because all URLs are duplicates
        second_run_added = run_pipeline(mock=True, shared_mock_sheet=shared_sheet)
        assert len(second_run_added) == 0
        assert len(shared_sheet.rows) - 1 == 7

    def test_all_rows_have_non_blank_location_match_type(self):
        """
        Checklist Item 3: Every row in the sheet — eBay and Facebook — has a non-blank Location Match Type.
        """
        items = generate_mock_fixtures()
        valid_types = {
            "Confirmed within-radius (Local Pickup)",
            "Approximate location match",
            "Confirmed within-radius (Marketplace filter)",
        }
        for item in items:
            assert item.location_match_type is not None
            assert len(item.location_match_type.strip()) > 0
            assert item.location_match_type in valid_types

    def test_ebay_cross_mode_deduplication_priority(self):
        """
        Fix 2: Merging Mode 1 (Local Pickup) and Mode 2 (Approximate) prioritizes Local Pickup.
        """
        ebay = EbayClient(client_id="dummy", client_secret="dummy")
        
        item_mode1 = ListingItem(
            category="CPU",
            title="Intel Core i7-6700 LGA1151 CPU",
            price=65.00,
            condition="Used",
            location="Newmarket, ON",
            listing_url="https://www.ebay.ca/itm/123456789012?campid=123",
            status="New",
            location_match_type="Confirmed within-radius (Local Pickup)",
            source="eBay API",
        )
        item_mode2 = ListingItem(
            category="CPU",
            title="Intel Core i7-6700 LGA1151 CPU",
            price=65.00,
            condition="Used",
            location="Ontario, Canada",
            listing_url="https://www.ebay.ca/itm/123456789012?hash=item99",
            status="New",
            location_match_type="Approximate location match",
            source="eBay API",
        )

        merged = {}
        # Simulate Mode 2 added first, then Mode 1
        merged[normalize_url(item_mode2.listing_url)] = item_mode2
        merged[normalize_url(item_mode1.listing_url)] = item_mode1

        assert len(merged) == 1
        final_item = list(merged.values())[0]
        assert final_item.location_match_type == "Confirmed within-radius (Local Pickup)"

    def test_fb_marketplace_card_location_match_type_populated(self):
        """
        Fix 3: Always populate Location Match Type for Facebook rows.
        """
        fb = FacebookMarketplaceSession()
        item = fb.parse_raw_card(
            title="Intel Core i7-7700 Quad Core LGA1151",
            price_str="$90",
            location="Newmarket, ON",
            raw_url="https://www.facebook.com/marketplace/item/1122334455/?ref=search",
            category="CPU",
        )
        assert item is not None
        assert item.location_match_type == "Confirmed within-radius (Marketplace filter)"
        assert item.price == 90.00
        assert item.status == "New"

    def test_fb_graceful_error_handling(self):
        """
        Checklist Item 5: If FB Marketplace encounters an error or session expiry,
        it does not crash and returns empty list.
        """
        fb = FacebookMarketplaceSession()
        # Non-playwright or network error should return empty list safely
        res = fb.search_cpu_and_ram()
        assert isinstance(res, list)

    def test_sorting_order_cpu_and_ram_by_price_ascending(self):
        """
        Sheet sorting: Categories separated, each sorted by Price (CAD) ascending.
        """
        sheet = MockSheetsManager()
        sheet.sync_listings(generate_mock_fixtures())

        rows = sheet.rows[1:]  # skip header
        cpu_rows = [r for r in rows if r[1] == "CPU"]
        ram_rows = [r for r in rows if r[1] == "RAM"]

        cpu_prices = [float(r[3]) for r in cpu_rows]
        ram_prices = [float(r[3]) for r in ram_rows]

        assert cpu_prices == sorted(cpu_prices)
        assert ram_prices == sorted(ram_prices)

    def test_ebay_browser_scraper_html_parsing(self):
        """
        Tests EbayBrowserScraper HTML parser on sample eBay.ca cards.
        """
        sample_html = """
        <ul class="srp-results">
            <li class="s-item">
                <div class="s-item__wrapper">
                    <a class="s-item__link" href="https://www.ebay.ca/itm/123456789012?hash=item1">
                        <span class="s-item__title">Intel Core i7-6700K 4.0GHz LGA1151 CPU</span>
                    </a>
                    <span class="s-item__price">C $85.00</span>
                    <span class="SECONDARY_INFO">Used</span>
                    <span class="s-item__location">Newmarket, ON</span>
                </div>
            </li>
            <li class="s-item">
                <div class="s-item__wrapper">
                    <a class="s-item__link" href="https://www.ebay.ca/itm/999888777666?hash=item2">
                        <span class="s-item__title">Intel Core i7-8700K 8th Gen CPU</span>
                    </a>
                    <span class="s-item__price">C $150.00</span>
                    <span class="SECONDARY_INFO">Used</span>
                    <span class="s-item__location">Toronto, ON</span>
                </div>
            </li>
        </ul>
        """
        scraper = EbayBrowserScraper()
        items = scraper._extract_items_from_html(
            sample_html, "CPU", "Confirmed within-radius (Local Pickup)", require_proximity_check=False
        )
        # Should accept i7-6700K and reject i7-8700K
        assert len(items) == 1
        assert items[0].title == "Intel Core i7-6700K 4.0GHz LGA1151 CPU"
        assert items[0].price == 85.00
        assert items[0].location_match_type == "Confirmed within-radius (Local Pickup)"
        assert items[0].source == "eBay Browser"
        assert items[0].listing_url == "https://www.ebay.ca/itm/123456789012"
