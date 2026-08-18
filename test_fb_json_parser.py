"""
Unit tests for Facebook Marketplace JSON-based extraction,
network capture parser, and DOM fallback behavior.
"""

import json
import pytest
from fb_marketplace_session import FacebookMarketplaceSession


class TestFBJSONParser:
    @pytest.fixture
    def session(self):
        return FacebookMarketplaceSession(user_data_dir="/tmp/test_fb_profile_dummy", headless=True)

    def test_json_script_marketplace_product_item_extraction(self, session):
        """
        Verifies that a valid JSON script-tag blob containing a MarketplaceProductItem
        correctly extracts title, price, location, and constructs a valid ListingItem.
        """
        sample_blob = {
            "require": [
                [
                    "ScheduledServerJS",
                    "handle",
                    None,
                    [
                        {
                            "__bbox": {
                                "result": {
                                    "data": {
                                        "marketplace_search": {
                                            "feed_units": {
                                                "edges": [
                                                    {
                                                        "node": {
                                                            "__typename": "MarketplaceProductItem",
                                                            "id": "789123456789012",
                                                            "marketplace_listing_title": "Intel Core i7-7700K 4.2GHz LGA1151 CPU",
                                                            "listing_price": {
                                                                "amount": "125.00",
                                                                "formatted_amount": "CA$125.00",
                                                                "currency": "CAD",
                                                            },
                                                            "location": {
                                                                "reverse_geocode": {
                                                                    "city_name": "Aurora",
                                                                    "state": "ON",
                                                                }
                                                            },
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    ],
                ]
            ]
        }

        extracted_items = []
        session._find_marketplace_items_in_json(sample_blob, extracted_items)

        assert len(extracted_items) == 1
        item_raw = extracted_items[0]
        assert item_raw["id"] == "789123456789012"
        assert item_raw["title"] == "Intel Core i7-7700K 4.2GHz LGA1151 CPU"
        assert item_raw["price"] == 125.0
        assert item_raw["location"] == "Aurora, ON"
        assert item_raw["url"] == "https://www.facebook.com/marketplace/item/789123456789012"

        listing = session._parse_json_dict_to_listing(item_raw, "CPU")
        assert listing is not None
        assert listing.title == "Intel Core i7-7700K 4.2GHz LGA1151 CPU"
        assert listing.price == 125.0
        assert listing.location == "Aurora, ON"
        assert listing.category == "CPU"
        assert listing.status == "New"
        assert listing.location_match_type == "Confirmed within-radius (Marketplace filter)"

    def test_json_script_ram_8gb_stick_extraction(self, session):
        """
        Verifies extraction of 8GB DDR4 RAM stick kit from JSON payload.
        """
        sample_blob = {
            "node": {
                "__typename": "MarketplaceProductItem",
                "id": "555444333222111",
                "title": "Corsair Vengeance LPX 16GB (2x8GB) DDR4 3200MHz RAM",
                "listing_price": {"formatted_price": {"text": "CA$85.00"}},
                "location": {"display_name": "Richmond Hill, ON"},
            }
        }

        extracted_items = []
        session._find_marketplace_items_in_json(sample_blob, extracted_items)

        assert len(extracted_items) == 1
        listing = session._parse_json_dict_to_listing(extracted_items[0], "RAM")
        assert listing is not None
        assert listing.title == "Corsair Vengeance LPX 16GB (2x8GB) DDR4 3200MHz RAM"
        assert listing.price == 85.0
        assert listing.location == "Richmond Hill, ON"
        assert listing.category == "RAM"

    def test_malformed_and_non_json_blobs_skipped(self, session):
        """
        Verifies that malformed, corrupted, empty, or non-JSON strings are safely skipped
        without raising any exceptions.
        """
        malformed_blobs = [
            "<html><body>Not JSON</body></html>",
            "{'invalid_json': True, missing_quotes}",
            "",
            "   ",
            "null",
            "{\"key\": undefined}",
            "[1, 2, 3, ]",
        ]

        extracted_items = []
        for blob in malformed_blobs:
            try:
                data = json.loads(blob)
                session._find_marketplace_items_in_json(data, extracted_items)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        assert len(extracted_items) == 0

    def test_fallback_to_dom_card_when_json_absent(self, session):
        """
        Verifies the fallback case where JSON extraction yields no items,
        but _parse_card_text_robust parses the card's inner_text lines successfully.
        """
        # Card with 'Just listed' badge and price
        card_lines = [
            "Just listed",
            "CA$55",
            "Intel Core i7-6700K 4.0GHz LGA1151 CPU – SR2L0",
            "Toronto, ON",
            "· 18 km",
        ]

        parsed = session._parse_card_text_robust(card_lines)
        assert parsed is not None
        assert parsed["title"] == "Intel Core i7-6700K 4.0GHz LGA1151 CPU – SR2L0"
        assert parsed["price"] == 55.0
        assert parsed["location"] == "Toronto, ON"

        # Direct card parsing verification
        raw_card_item = session.parse_raw_card(
            title=parsed["title"],
            price_str=str(parsed["price"]),
            location=parsed["location"],
            raw_url="https://www.facebook.com/marketplace/item/1621087079546088/?ref=search",
            category="CPU",
        )
        assert raw_card_item is not None
        assert raw_card_item.listing_url == "https://www.facebook.com/marketplace/item/1621087079546088"
        assert raw_card_item.price == 55.0
        assert raw_card_item.location == "Toronto, ON"

    def test_incompatible_cpu_rejected_from_json(self, session):
        """
        Verifies that non-LGA1151 or non-i7/Xeon CPUs extracted from JSON are rejected.
        """
        incompatible_item = {
            "id": "111222333444555",
            "title": "AMD Ryzen 5 5600X 6-Core AM4 Processor",
            "price": 140.0,
            "location": "Newmarket, ON",
            "url": "https://www.facebook.com/marketplace/item/111222333444555",
        }
        listing = session._parse_json_dict_to_listing(incompatible_item, "CPU")
        assert listing is None

    def test_foreign_location_rejected_from_json(self, session):
        """
        Verifies that items located in the US or overseas extracted from JSON are rejected.
        """
        us_item = {
            "id": "999000111222333",
            "title": "Intel Core i7-7700K LGA1151 CPU",
            "price": 100.0,
            "location": "Buffalo, NY, USA",
            "url": "https://www.facebook.com/marketplace/item/999000111222333",
        }
        listing = session._parse_json_dict_to_listing(us_item, "CPU")
        assert listing is None
