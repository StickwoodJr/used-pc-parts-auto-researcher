"""
Unit tests for data_processor.py: model classification, seller trust scoring,
nuanced scam detection, and Top 5 selection.
"""

import pytest
from ebay_client import ListingItem
from data_processor import DataProcessor


class TestDataProcessor:
    def setup_method(self):
        self.processor = DataProcessor()

    def test_model_classification(self):
        items = [
            ("Intel Core i7-6700 3.4GHz Quad Core LGA1151", "CPU", "CPU - i7-6700"),
            ("Intel Core i7-6700K 4.0GHz Unlocked CPU", "CPU", "CPU - i7-6700K"),
            ("Intel Core i7-6700T 2.8GHz 35W Low Power", "CPU", "CPU - i7-6700T"),
            ("Intel Core i7-7700 3.6GHz Processor", "CPU", "CPU - i7-7700"),
            ("Intel Core i7-7700K 4.2GHz Kaby Lake", "CPU", "CPU - i7-7700K"),
            ("Intel Core i7-7700T 2.9GHz Quad-Core", "CPU", "CPU - i7-7700T"),
            ("Intel Xeon E3-1240 v6 3.7GHz LGA1151", "CPU", "CPU - Xeon E3 v5-v6"),
            ("Corsair Vengeance LPX 16GB (2x8GB) DDR4", "RAM", "RAM - DDR4 UDIMM"),
        ]
        for title, category, expected_bucket in items:
            item = ListingItem(
                category=category,
                title=title,
                price=50.0,
                condition="Used",
                location="Newmarket, ON",
                listing_url="https://www.ebay.ca/itm/123456",
                location_match_type="Confirmed within-radius (Local Pickup)",
            )
            assert self.processor.classify_model(item) == expected_bucket

    def test_box_only_scam_detection(self):
        item = ListingItem(
            category="CPU",
            title="Intel Core i7-7700K Original Packaging Box Only No CPU",
            price=25.0,
            condition="Used",
            location="Canada",
            listing_url="https://www.ebay.ca/itm/111222",
            location_match_type="Confirmed within-radius (Local Pickup)",
        )
        status, trust = self.processor.evaluate_scam_and_trust(item, "CPU - i7-7700K")
        assert status == "Flagged-BoxOnly"
        assert trust == 0.0

    def test_placeholder_price_detection(self):
        item = ListingItem(
            category="RAM",
            title="Corsair Vengeance 16GB DDR4 RAM - $1 Quick Sale",
            price=1.0,
            condition="Used",
            location="Newmarket, ON",
            listing_url="https://www.facebook.com/marketplace/item/999888",
            location_match_type="Confirmed within-radius (Marketplace filter)",
            source="Facebook Marketplace",
        )
        status, trust = self.processor.evaluate_scam_and_trust(item, "RAM - DDR4 UDIMM")
        assert status == "Flagged-Placeholder"
        assert trust == 0.0

    def test_untested_condition_flagging(self):
        item = ListingItem(
            category="CPU",
            title="Intel Core i7-6700 CPU Untested For Parts As Is",
            price=30.0,
            condition="For parts or not working",
            location="Canada",
            listing_url="https://www.ebay.ca/itm/333444",
            location_match_type="Confirmed within-radius (Local Pickup)",
            seller_rating_pct=99.0,
            seller_feedback_count=150,
        )
        status, trust = self.processor.evaluate_scam_and_trust(item, "CPU - i7-6700")
        assert status == "Caution-Untested"
        assert trust < 50.0  # Penalized for being untested

    def test_high_reputation_seller_trust_score(self):
        item = ListingItem(
            category="CPU",
            title="Intel Core i7-6700K 4.0GHz LGA1151 Tested Working 100%",
            price=85.0,
            condition="Used",
            location="Newmarket, ON",
            listing_url="https://www.ebay.ca/itm/555666",
            location_match_type="Confirmed within-radius (Local Pickup)",
            seller_rating_pct=99.8,
            seller_feedback_count=1200,
            seller_badge="Top Rated",
        )
        status, trust = self.processor.evaluate_scam_and_trust(item, "CPU - i7-6700K")
        assert status == "Verified-Good"
        assert trust >= 85.0

    def test_top_5_excludes_flagged_scams(self):
        items = [
            ListingItem(
                category="CPU",
                title=f"Intel Core i7-7700K Tested Deal {i}",
                price=90.0 + i * 5,
                condition="Used",
                location="Newmarket, ON",
                listing_url=f"https://www.ebay.ca/itm/7700_{i}",
                location_match_type="Confirmed within-radius (Local Pickup)",
                seller_rating_pct=99.0,
                seller_feedback_count=100,
            )
            for i in range(1, 8)
        ]
        # Add a scam item with a low price
        scam_item = ListingItem(
            category="CPU",
            title="Intel Core i7-7700K Box Only Empty Box",
            price=15.0,
            condition="Used",
            location="Canada",
            listing_url="https://www.ebay.ca/itm/7700_scam",
            location_match_type="Confirmed within-radius (Local Pickup)",
        )
        items.append(scam_item)

        buckets = self.processor.process_all_listings(items)
        top_5 = self.processor.get_top_5_per_model(buckets)

        i7_7700k_top5 = top_5["CPU - i7-7700K"]
        assert len(i7_7700k_top5) == 5
        # Verify the scam item was excluded
        assert all(it.listing_url != "https://www.ebay.ca/itm/7700_scam" for it in i7_7700k_top5)
        assert all(it.status == "Verified-Good" for it in i7_7700k_top5)

    def test_cpu_benchmark_ratings(self):
        items = [
            ("Intel Core i7-7700K 4.20GHz LGA1151 CPU", 9700),
            ("Intel Core i7-6700K 4.00GHz Quad Core", 8900),
            ("Intel Core i7-7700 3.6GHz Quad-Core CPU", 8650),
            ("Intel Core i7-6700 3.4GHz LGA1151", 8100),
            ("Intel Xeon E3-1270 v6 3.8GHz Server CPU", 9400),
            ("Intel Xeon E3-1240 v6 3.7GHz LGA1151", 8600),
            ("Intel Xeon E3-1270 v5 3.6GHz LGA1151", 8400),
            ("Intel Core i7-7700T 2.9GHz Low Power CPU", 7200),
            ("Intel Core i7-6700T 2.8GHz 35W Low Power", 6700),
        ]
        for title, expected_score in items:
            item = ListingItem(
                category="CPU",
                title=title,
                price=60.0,
                condition="Used",
                location="Newmarket, ON",
                listing_url="https://www.ebay.ca/itm/123",
                location_match_type="Confirmed within-radius (Local Pickup)",
            )
            assert self.processor.get_cpu_benchmark(item) == expected_score

    def test_top_5_overall_ranking_rewards_high_performance(self):
        items = [
            # High performance i7-7700K at good price
            ListingItem(
                category="CPU",
                title="Intel Core i7-7700K 4.2GHz LGA1151 Tested",
                price=95.0,
                condition="Used",
                location="Newmarket, ON",
                listing_url="https://www.ebay.ca/itm/7700k_good",
                location_match_type="Confirmed within-radius (Local Pickup)",
                seller_rating_pct=99.5,
                seller_feedback_count=500,
            ),
            # Xeon E3-1270 v6 at great price
            ListingItem(
                category="CPU",
                title="Intel Xeon E3-1270 v6 3.8GHz LGA1151 CPU",
                price=70.0,
                condition="Used",
                location="Canada",
                listing_url="https://www.ebay.ca/itm/1270v6_good",
                location_match_type="Confirmed within-radius (Local Pickup)",
                seller_rating_pct=99.0,
                seller_feedback_count=200,
            ),
            # Low power i7-6700T at moderate price
            ListingItem(
                category="CPU",
                title="Intel Core i7-6700T 2.8GHz Low Power",
                price=55.0,
                condition="Used",
                location="Canada",
                listing_url="https://www.ebay.ca/itm/6700t_deal",
                location_match_type="Approximate location match",
                seller_rating_pct=95.0,
                seller_feedback_count=50,
            ),
        ]
        buckets = self.processor.process_all_listings(items)
        top_5_overall = self.processor.get_top_5_overall_cpus(buckets)

        assert len(top_5_overall) == 3
        # High performance / high value chips rank at the top
        assert top_5_overall[0].listing_url in ("https://www.ebay.ca/itm/1270v6_good", "https://www.ebay.ca/itm/7700k_good")
        assert top_5_overall[0].benchmark_score >= 8900
