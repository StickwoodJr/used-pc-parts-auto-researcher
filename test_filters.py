"""
Unit tests for compatibility filters, URL normalizers, proximity checks, and scam detection.
"""

import pytest
from filters import (
    is_cpu_compatible,
    is_ram_compatible,
    normalize_url,
    is_proximity_match,
    determine_status,
)


class TestCPUFilter:
    @pytest.mark.parametrize(
        "title",
        [
            "Intel Core i7-6700 3.4GHz Quad-Core LGA1151 Processor",
            "Intel Core i7-6700K 4.0GHz Unlocked LGA 1151 CPU",
            "Intel Core i7-6700T 2.80GHz Low Power LGA1151 CPU",
            "Intel Core i7-7700 3.6GHz Quad-Core Processor (LGA1151)",
            "Intel Core i7-7700K 4.20GHz Kaby Lake LGA1151 Processor",
            "Intel Core i7-7700T 2.9GHz Quad-Core LGA1151 CPU",
            "Intel Xeon E3-1230 v5 3.4GHz LGA1151 Server / Desktop CPU",
            "Intel Xeon E3-1240 v6 3.7GHz LGA1151 Processor",
            "Intel Xeon E3-1275 v6 3.8GHz Quad Core LGA1151",
            "Intel Xeon E3-1270 v5 Quad Core 3.60GHz LGA 1151",
            "Intel Xeon E3-1245 v5 3.5GHz LGA1151",
            "Xeon E3-1280 v6 3.90GHz Processor LGA1151",
        ],
    )
    def test_compatible_cpus_accepted(self, title):
        assert is_cpu_compatible(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "Intel Core i7-8700K LGA1151 8th Gen 6-Core CPU",  # 8th gen incompatible with H110
            "Intel Core i7-9700K 3.6GHz 9th Gen Processor",     # 9th gen incompatible
            "Intel Core i7-4790K 4.0GHz LGA1150 Haswell CPU",   # LGA1150 4th gen
            "Intel Core i7-3770 3.4GHz LGA1155 Ivy Bridge",     # LGA1155 3rd gen
            "Intel Core i7-2600K LGA1155 Sandy Bridge",         # LGA1155 2nd gen
            "Intel Core i7-10700K LGA1200 Comet Lake",          # LGA1200 10th gen
            "Intel Core i7-12700K LGA1700 Alder Lake",          # LGA1700 12th gen
            "Intel Xeon E5-2670 v3 LGA2011-3 Server CPU",       # Xeon E5 LGA2011
            "Intel Xeon E3-1230 v2 LGA1155 Quad Core",          # Xeon E3 v2 (LGA1155)
            "Intel Xeon E3-1230 v3 LGA1150 Processor",          # Xeon E3 v3 (LGA1150)
            "AMD Ryzen 7 5700X 8-Core AM4 Processor",           # AMD AM4
            "AMD Ryzen 5 3600 AM4 CPU",                         # AMD AM4
        ],
    )
    def test_incompatible_cpus_rejected(self, title):
        assert is_cpu_compatible(title) is False


class TestRAMFilter:
    @pytest.mark.parametrize(
        "title",
        [
            "Corsair Vengeance LPX 16GB (2x8GB) DDR4 3200MHz Desktop UDIMM",
            "G.Skill Ripjaws V 16GB 2x8GB DDR4-3600 CL16 Desktop Memory",
            "Kingston Fury Beast 8GB (1x8GB) DDR4 3200MHz Non-ECC CL16 Desktop Memory",
            "Samsung 8GB 1Rx8 PC4-2400T DDR4 Desktop UDIMM Memory",
            "HyperX Fury 16GB (2x8GB) DDR4 2666MHz Desktop RAM",
            "Corsair Vengeance 8GB DDR4 2400 Desktop Memory Single Stick",
            "16gb ddr4 ram 3200mhz 2x8",
            "Kingston HyperX Fury 16GB (2x8GB) DDR4 2933MHz RAM",
        ],
    )
    def test_compatible_ram_accepted(self, title):
        assert is_ram_compatible(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "Crucial 8GB (2x4GB) DDR4 2400MHz Desktop RAM UDIMM",              # 2x4GB (4GB sticks)
            "SK Hynix 8GB (2x4GB) DDR4 2133MHz PC4-2133P RAM",                 # 2x4GB (4GB sticks)
            "Crucial 4GB DDR4 2400 Desktop RAM",                               # 4GB stick
            "Crucial 16GB Single DDR4 2666 MT/s CL19 DR UDIMM Desktop RAM",   # 16GB single stick
            "Samsung 16GB DDR4 Single Stick",                                  # 16GB single stick
            "Crucial 16GB Single DDR4 3200 SODIMM Laptop Memory",              # Laptop / SODIMM
            "Samsung 8GB PC4-2666V SODIMM Laptop RAM",                         # Laptop / SODIMM
            "Samsung 16GB 2Rx8 PC4-2400T DDR4 ECC Registered RDIMM Server RAM", # ECC Registered / RDIMM
            "Hynix 32GB 2Rx4 PC4-2400T ECC LRDIMM Server Memory",              # 32GB / ECC LRDIMM
            "Corsair Vengeance RGB Pro 32GB (2x16GB) DDR4 3600MHz",             # 32GB kit
            "G.Skill 32GB (4x8GB) DDR4 Desktop RAM Kit",                       # 4x kit
            "Corsair Vengeance 16GB (2x8GB) DDR3 1600MHz Desktop RAM",         # DDR3
            "Crucial 16GB DDR5 4800MHz Desktop UDIMM RAM",                     # DDR5
        ],
    )
    def test_incompatible_ram_rejected(self, title):
        assert is_ram_compatible(title) is False


class TestURLNormalization:
    def test_ebay_url_normalization(self):
        raw_ebay = (
            "https://www.ebay.ca/itm/123456789012?hash=item1c&_trkparms=ispr%3D1"
            "&amdata=enc%3AAQAJAAAA&campid=5338&customid=123"
        )
        assert normalize_url(raw_ebay) == "https://www.ebay.ca/itm/123456789012"

    def test_ebay_url_with_title_slug(self):
        raw_slug = "https://www.ebay.ca/itm/Intel-Core-i7-6700-CPU-LGA1151/334567890123?epid=219503461"
        assert normalize_url(raw_slug) == "https://www.ebay.ca/itm/334567890123"

    def test_facebook_url_normalization(self):
        raw_fb = (
            "https://www.facebook.com/marketplace/item/987654321098765/"
            "?ref=search&referral_code=null&tracking=browse_serp%3Aabc"
        )
        assert normalize_url(raw_fb) == "https://www.facebook.com/marketplace/item/987654321098765"


class TestProximityAndScam:
    @pytest.mark.parametrize(
        "location",
        [
            "Newmarket, ON",
            "Aurora, Ontario",
            "Bradford, ON",
            "Richmond Hill, ON",
            "Markham, ON",
            "East Gwillimbury, ON",
            "Toronto, ON",
            "L3Y 8B4",
            "Postal: L4G 3X1, Canada",
        ],
    )
    def test_proximity_match_positive(self, location):
        assert is_proximity_match(location) is True

    @pytest.mark.parametrize(
        "location",
        [
            "Newmarket, ON",
            "Aurora, Ontario",
            "Bradford, ON",
            "Richmond Hill, ON",
            "East Gwillimbury, ON",
            "King City, ON",
            "Keswick, ON",
            "Stouffville, ON",
            "L3Y 8B4",
            "Postal: L4G 3X1, Canada",
        ],
    )
    def test_is_local_20km_positive(self, location):
        from filters import is_local_20km
        assert is_local_20km(location) is True

    @pytest.mark.parametrize(
        "location",
        [
            "Toronto, ON",
            "Mississauga, ON",
            "Brampton, ON",
            "Hamilton, ON",
            "Kitchener, ON",
            "Montreal, QC",
            "Vancouver, BC",
            "Ottawa, ON",
            "San Jose, CA, USA",
        ],
    )
    def test_is_local_20km_negative(self, location):
        from filters import is_local_20km
        assert is_local_20km(location) is False

    @pytest.mark.parametrize(
        "location",
        [
            "Newmarket, ON",
            "Aurora, Ontario",
            "Bradford, ON",
            "Richmond Hill, ON",
            "Markham, ON",
            "East Gwillimbury, ON",
            "Toronto, ON",
            "L3Y 8B4",
            "Postal: L4G 3X1, Canada",
            "Montreal, QC",
            "Vancouver, BC",
            "Calgary, AB",
            "Ottawa, ON",
            "Halifax, NS",
            "Winnipeg, MB",
            "Ontario, Canada",
        ],
    )
    def test_is_canadian_location_positive(self, location):
        from filters import is_canadian_location
        assert is_canadian_location(location) is True

    @pytest.mark.parametrize(
        "location",
        [
            "San Jose, CA, United States",
            "Los Angeles, CA, USA",
            "Miami, FL, United States",
            "Dallas, Texas, USA",
            "New York, NY",
            "Shenzhen, China",
            "Hong Kong, HK",
            "London, United Kingdom",
            "Berlin, Germany",
            "Tokyo, Japan",
            "Taipei, Taiwan",
            "Paris, France",
            "Sydney, Australia",
        ],
    )
    def test_is_canadian_location_negative(self, location):
        from filters import is_canadian_location
        assert is_canadian_location(location) is False

    def test_extract_located_in(self):
        from filters import extract_located_in, is_canadian_location

        card_us = "Intel Core i7-7700K Quad-Core CPU | $120.00 | Located in: San Jose, California, United States | Top Rated Seller"
        loc_us = extract_located_in(card_us)
        assert loc_us is not None
        assert is_canadian_location(loc_us) is False

        card_cn = "Intel Xeon E3-1270 V5 CPU | $18.00 | Item location: Shenzhen, Guangdong, China | Free International Shipping"
        loc_cn = extract_located_in(card_cn)
        assert loc_cn is not None
        assert is_canadian_location(loc_cn) is False

        card_ca = "Intel Core i7-6700K 4.0GHz CPU | $65.00 | Located in: Markham, Ontario, Canada | Local Pickup Available"
        loc_ca = extract_located_in(card_ca)
        assert loc_ca is not None
        assert is_canadian_location(loc_ca) is True

    def test_scam_status_flagging(self):
        # CPU thresholds: < $20 CAD is scam
        assert determine_status(15.00, "CPU") == "Flagged-Scam"
        assert determine_status(19.99, "CPU") == "Flagged-Scam"
        assert determine_status(20.00, "CPU") == "New"
        assert determine_status(85.00, "CPU") == "New"

        # RAM thresholds: < $10 CAD is scam
        assert determine_status(8.50, "RAM") == "Flagged-Scam"
        assert determine_status(9.99, "RAM") == "Flagged-Scam"
        assert determine_status(10.00, "RAM") == "New"
        assert determine_status(35.00, "RAM") == "New"
