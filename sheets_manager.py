"""
Google Sheets API manager for multi-tab organization: Master Summary,
per-model ranking sheets, and full raw listing archive.
"""

import os
import logging
from typing import List, Set, Tuple, Dict
import gspread
from google.oauth2.service_account import Credentials

from config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SHEET_TITLE,
    GOOGLE_SHEET_TAB_NAME,
    SHEET_HEADERS,
    MASTER_SUMMARY_HEADERS,
    MODEL_TABS,
)
from ebay_client import ListingItem
from filters import normalize_url, is_canadian_location
from data_processor import DataProcessor

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsManager:
    """
    Manages reading existing listings, deduplication by canonical URL,
    updating the raw archive, populating the Master Summary tab with Top 5 per model,
    and generating dedicated per-model ranked tabs.
    """

    def __init__(
        self,
        service_account_file: str = GOOGLE_SERVICE_ACCOUNT_FILE,
        sheet_title: str = GOOGLE_SHEET_TITLE,
        tab_name: str = GOOGLE_SHEET_TAB_NAME,
    ):
        self.service_account_file = service_account_file
        self.sheet_title = sheet_title
        self.tab_name = tab_name
        self.client: gspread.Client = None
        self.sheet: gspread.Spreadsheet = None
        self.worksheet: gspread.Worksheet = None

    def is_configured(self) -> bool:
        """Checks if service account JSON file exists."""
        return os.path.exists(self.service_account_file)

    def connect(self) -> bool:
        """Authenticates with Google Sheets API and connects to the workbook."""
        if not self.is_configured():
            logger.warning(f"Google Service Account file not found at '{self.service_account_file}'.")
            return False

        try:
            creds = Credentials.from_service_account_file(self.service_account_file, scopes=SCOPES)
            self.client = gspread.authorize(creds)

            sheet_url_or_key = os.getenv("GOOGLE_SHEET_URL", os.getenv("GOOGLE_SHEET_KEY", "")).strip()

            if sheet_url_or_key:
                if sheet_url_or_key.startswith("https://"):
                    self.sheet = self.client.open_by_url(sheet_url_or_key)
                else:
                    self.sheet = self.client.open_by_key(sheet_url_or_key)
            else:
                try:
                    self.sheet = self.client.open(self.sheet_title)
                except gspread.SpreadsheetNotFound:
                    logger.info(f"Spreadsheet '{self.sheet_title}' not found. Creating new spreadsheet...")
                    self.sheet = self.client.create(self.sheet_title)

            # Ensure raw archive tab exists
            try:
                self.worksheet = self.sheet.worksheet(self.tab_name)
            except gspread.WorksheetNotFound:
                logger.info(f"Tab '{self.tab_name}' not found. Creating worksheet tab...")
                self.worksheet = self.sheet.add_worksheet(title=self.tab_name, rows=100, cols=len(SHEET_HEADERS))

            # Ensure headers exist in row 1 of raw archive
            existing_values = self.worksheet.get_all_values()
            if not existing_values or existing_values[0] != SHEET_HEADERS:
                self.worksheet.insert_row(SHEET_HEADERS, index=1)
                try:
                    self.worksheet.format("A1:L1", {"textFormat": {"bold": True}})
                except Exception:
                    pass

            return True
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            return False

    def get_existing_urls(self) -> Set[str]:
        """
        Fetches all URLs currently stored in the raw archive tab.
        Column G is 'Listing URL' (index 7).
        """
        if not self.worksheet:
            return set()

        try:
            url_col_values = self.worksheet.col_values(7)
            urls = url_col_values[1:] if len(url_col_values) > 1 else []
            return {normalize_url(u) for u in urls if u.strip()}
        except Exception as e:
            logger.error(f"Error fetching existing URLs from Google Sheet: {e}")
            return set()

    def get_or_create_tab(self, tab_title: str, headers: List[str]) -> gspread.Worksheet:
        """Helper to get or create a worksheet tab with headers."""
        try:
            ws = self.sheet.worksheet(tab_title)
        except gspread.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title=tab_title, rows=50, cols=len(headers))
            ws.insert_row(headers, index=1)
            try:
                ws.format(f"A1:{chr(64+len(headers))}1", {"textFormat": {"bold": True}})
            except Exception:
                pass
        return ws

    def update_master_summary_tab(self, top_5_by_model: Dict[str, List[ListingItem]], top_5_overall_cpus: List[ListingItem]):
        """
        Populates the 'Master Summary' tab with:
        1. Top 5 Overall CPUs (Performance Benchmark + Value + Trust)
        2. Top 5 per CPU Model
        3. Top 5 RAM listings
        """
        try:
            ws = self.get_or_create_tab("Master Summary", MASTER_SUMMARY_HEADERS)
            rows: List[List[Any]] = [MASTER_SUMMARY_HEADERS]

            # 1. TOP 5 OVERALL CPUs SECTION
            if top_5_overall_cpus:
                rows.append(["🥇 TOP 5 OVERALL BEST CPUs (PERFORMANCE + VALUE + TRUST LEADERBOARD)", "", "", "", "", "", "", ""])
                for rank, item in enumerate(top_5_overall_cpus, start=1):
                    seller_info = f"{item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else "New/Unrated"
                    perf_str = f"PassMark: {item.benchmark_score:,} pts | Overall: {item.overall_score:.1f}/100"
                    rows.append([
                        f"#{rank} Overall",
                        item.model_bucket.replace("CPU - ", ""),
                        f"{item.title} [{perf_str}]",
                        item.price,
                        seller_info,
                        f"{item.trust_score:.0f}/100",
                        f"{item.location} ({item.location_match_type})",
                        item.listing_url,
                    ])
                rows.append(["", "", "", "", "", "", "", ""])

            # 2. PER-MODEL BREAKDOWNS
            for model_name, items in top_5_by_model.items():
                if not items:
                    continue
                # Section separator
                rows.append([f"--- {model_name.upper()} TOP PICKS ---", "", "", "", "", "", "", ""])

                for rank, item in enumerate(items, start=1):
                    seller_info = f"{item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else "New/Unrated"
                    rows.append([
                        f"#{rank}",
                        model_name,
                        item.title,
                        item.price,
                        seller_info,
                        f"{item.trust_score:.0f}/100",
                        f"{item.location} ({item.location_match_type})",
                        item.listing_url,
                    ])

            ws.clear()
            ws.update(f"A1:H{len(rows)}", rows)
            try:
                ws.format("A1:H1", {"textFormat": {"bold": True}})
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to update Master Summary tab: {e}")

    def update_local_summary_tab(self, top_local_cpus: List[ListingItem], top_local_ram: List[ListingItem]):
        """
        Populates the 'Local Summary (20km)' tab strictly with listings within 20km of Newmarket, ON.
        """
        try:
            ws = self.get_or_create_tab("Local Summary (20km)", MASTER_SUMMARY_HEADERS)
            rows: List[List[Any]] = [MASTER_SUMMARY_HEADERS]

            # 1. Local CPUs
            rows.append(["📍 NEWMARKET 20km RADIUS — TOP LOCAL CPU PICKS", "", "", "", "", "", "", ""])
            if top_local_cpus:
                for rank, item in enumerate(top_local_cpus, start=1):
                    seller_info = f"{item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else "New/Unrated"
                    perf_str = f"PassMark: {item.benchmark_score:,} pts | Overall: {item.overall_score:.1f}/100"
                    rows.append([
                        f"#{rank} Local CPU",
                        item.model_bucket.replace("CPU - ", ""),
                        f"{item.title} [{perf_str}]",
                        item.price,
                        seller_info,
                        f"{item.trust_score:.0f}/100",
                        f"{item.location} ({item.location_match_type})",
                        item.listing_url,
                    ])
            else:
                rows.append(["No current local 20km CPU listings found", "", "", "", "", "", "", ""])

            rows.append(["", "", "", "", "", "", "", ""])

            # 2. Local RAM
            rows.append(["📍 NEWMARKET 20km RADIUS — TOP LOCAL RAM PICKS", "", "", "", "", "", "", ""])
            if top_local_ram:
                for rank, item in enumerate(top_local_ram, start=1):
                    seller_info = f"{item.seller_rating_pct:.1f}% ({item.seller_feedback_count})" if item.seller_feedback_count > 0 else "New/Unrated"
                    rows.append([
                        f"#{rank} Local RAM",
                        "RAM - DDR4 UDIMM",
                        item.title,
                        item.price,
                        seller_info,
                        f"{item.trust_score:.0f}/100",
                        f"{item.location} ({item.location_match_type})",
                        item.listing_url,
                    ])
            else:
                rows.append(["No current local 20km RAM listings found", "", "", "", "", "", "", ""])

            ws.clear()
            ws.update(f"A1:H{len(rows)}", rows)
            try:
                ws.format("A1:H1", {"textFormat": {"bold": True}})
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to update Local Summary (20km) tab: {e}")

    def update_model_tabs(self, buckets: Dict[str, List[ListingItem]]):
        """
        Updates each dedicated model tab with all ranked listings.
        """
        for model_name, items in buckets.items():
            if not items or model_name not in MODEL_TABS:
                continue
            try:
                ws = self.get_or_create_tab(model_name, SHEET_HEADERS)
                rows: List[List[Any]] = [SHEET_HEADERS]
                for it in items:
                    rows.append(it.to_row())

                ws.clear()
                ws.update(f"A1:L{len(rows)}", rows)
                try:
                    ws.format("A1:L1", {"textFormat": {"bold": True}})
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Failed to update tab '{model_name}': {e}")

    def sync_listings(self, incoming_items: List[ListingItem]) -> Tuple[List[ListingItem], int]:
        """
        Clears existing raw listings from the worksheet and populates with fresh scan results,
        processes all listings with DataProcessor, and updates the Master Summary,
        Local Summary (20km), and all dedicated model tabs.
        """
        if not self.connect():
            raise RuntimeError(
                f"Google Sheets connection failed. Please ensure '{self.service_account_file}' exists and is shared."
            )

        # Deduplicate incoming items and enforce Canadian location
        seen_urls = set()
        valid_items: List[ListingItem] = []

        for item in incoming_items:
            norm_url = normalize_url(item.listing_url)
            if norm_url and norm_url not in seen_urls and is_canadian_location(item.location):
                seen_urls.add(norm_url)
                valid_items.append(item)

        # Sort valid items by category then price
        valid_items.sort(key=lambda x: (x.category, x.price))

        # Clear existing listings and write fresh entries
        self.worksheet.clear()
        fresh_rows = [SHEET_HEADERS] + [it.to_row() for it in valid_items]
        self.worksheet.update(f"A1:L{len(fresh_rows)}", fresh_rows, value_input_option="USER_ENTERED")
        try:
            self.worksheet.format("A1:L1", {"textFormat": {"bold": True}})
        except Exception:
            pass

        # Process with DataProcessor
        processor = DataProcessor()
        buckets = processor.process_all_listings(valid_items)
        top_5_by_model = processor.get_top_5_per_model(buckets)
        top_5_overall_cpus = processor.get_top_5_overall_cpus(buckets)
        top_local_cpus = processor.get_top_local_20km_cpus(buckets)
        top_local_ram = processor.get_top_local_20km_ram(buckets)

        # Update Master Summary tab, Local Summary (20km) tab, and individual model tabs
        self.update_master_summary_tab(top_5_by_model, top_5_overall_cpus)
        self.update_local_summary_tab(top_local_cpus, top_local_ram)
        self.update_model_tabs(buckets)

        total_rows = len(valid_items)
        return valid_items, total_rows


class MockSheetsManager:
    """
    In-memory mock sheets manager for dry-runs and automated verification.
    """

    def __init__(self):
        self.rows: List[List[Any]] = [SHEET_HEADERS]
        self.tabs: Dict[str, List[List[Any]]] = {}

    def is_configured(self) -> bool:
        return True

    def get_existing_urls(self) -> Set[str]:
        return {normalize_url(row[6]) for row in self.rows[1:] if len(row) > 6}

    def sync_listings(self, incoming_items: List[ListingItem]) -> Tuple[List[ListingItem], int]:
        self.rows = [SHEET_HEADERS]
        seen_urls = set()
        valid_items: List[ListingItem] = []

        for item in incoming_items:
            norm_url = normalize_url(item.listing_url)
            if norm_url and norm_url not in seen_urls and is_canadian_location(item.location):
                seen_urls.add(norm_url)
                valid_items.append(item)
                self.rows.append(item.to_row())

        processor = DataProcessor()
        buckets = processor.process_all_listings(incoming_items)
        top_5 = processor.get_top_5_per_model(buckets)

        self.tabs["Master Summary"] = [MASTER_SUMMARY_HEADERS]
        for model, items in top_5.items():
            for rank, it in enumerate(items, start=1):
                self.tabs["Master Summary"].append([
                    f"#{rank}", model, it.title, it.price, "", f"{it.trust_score:.0f}/100", it.location, it.listing_url
                ])

        for model, items in buckets.items():
            self.tabs[model] = [SHEET_HEADERS] + [it.to_row() for it in items]

        self._sort_rows()
        total_count = len(self.rows) - 1
        return valid_items, total_count

    def _sort_rows(self):
        if len(self.rows) <= 2:
            return
        header = self.rows[0]
        data = self.rows[1:]
        sorted_data = sorted(
            data,
            key=lambda r: (r[1], float(r[3]) if isinstance(r[3], (int, float)) else 999999.0),
        )
        self.rows = [header] + sorted_data
