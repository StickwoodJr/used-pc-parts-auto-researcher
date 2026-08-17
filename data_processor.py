"""
Data processor, classifier, nuanced scam evaluator, benchmark calculator, and trust ranking engine.
"""

import re
from typing import List, Dict, Tuple, Optional
from ebay_client import ListingItem

# Baseline used market price ranges (in CAD)
MARKET_BASELINES = {
    "i7-7700K": {"min": 90.0, "max": 150.0, "scam_threshold": 25.0},
    "i7-7700": {"min": 70.0, "max": 120.0, "scam_threshold": 20.0},
    "i7-7700T": {"min": 60.0, "max": 110.0, "scam_threshold": 18.0},
    "i7-6700K": {"min": 65.0, "max": 115.0, "scam_threshold": 20.0},
    "i7-6700": {"min": 45.0, "max": 80.0, "scam_threshold": 15.0},
    "i7-6700T": {"min": 40.0, "max": 75.0, "scam_threshold": 15.0},
    "Xeon E3 v5-v6": {"min": 35.0, "max": 90.0, "scam_threshold": 15.0},
    "RAM - DDR4 UDIMM": {"min": 20.0, "max": 70.0, "scam_threshold": 10.0},
}

# Established Multi-Core PassMark CPU Benchmark Index
CPU_BENCHMARKS = {
    "i7-7700K": 9700,
    "i7-6700K": 8900,
    "i7-7700": 8650,
    "i7-6700": 8100,
    "i7-7700T": 7200,
    "i7-6700T": 6700,
    "e3-1280 v6": 9500,
    "e3-1275 v6": 9400,
    "e3-1270 v6": 9400,
    "e3-1245 v6": 8700,
    "e3-1240 v6": 8600,
    "e3-1230 v6": 8600,
    "e3-1280 v5": 8600,
    "e3-1275 v5": 8400,
    "e3-1270 v5": 8400,
    "e3-1245 v5": 8100,
    "e3-1240 v5": 8000,
    "e3-1230 v5": 8000,
    "e3-1225 v5": 7500,
    "e3-1220 v5": 7400,
    "e3-1220 v6": 7500,
}

MODEL_ORDER = [
    "CPU - i7-6700",
    "CPU - i7-6700K",
    "CPU - i7-6700T",
    "CPU - i7-7700",
    "CPU - i7-7700K",
    "CPU - i7-7700T",
    "CPU - Xeon E3 v5-v6",
    "RAM - DDR4 UDIMM",
]


class DataProcessor:
    """
    Categorizes listings into model buckets, calculates seller trust, benchmark ratings,
    overall performance-to-value scores, and generates Top 5 rankings.
    """

    @staticmethod
    def classify_model(item: ListingItem) -> str:
        """
        Classifies an item into an exact hardware model bucket.
        """
        t = item.title.lower()

        if item.category.upper() == "RAM":
            return "RAM - DDR4 UDIMM"

        # CPU Classification
        if re.search(r"\bi7[- ]?7700k\b", t):
            return "CPU - i7-7700K"
        if re.search(r"\bi7[- ]?7700t\b", t):
            return "CPU - i7-7700T"
        if re.search(r"\bi7[- ]?7700\b", t):
            return "CPU - i7-7700"

        if re.search(r"\bi7[- ]?6700k\b", t):
            return "CPU - i7-6700K"
        if re.search(r"\bi7[- ]?6700t\b", t):
            return "CPU - i7-6700T"
        if re.search(r"\bi7[- ]?6700\b", t):
            return "CPU - i7-6700"

        if re.search(r"\b(xeon|e3[- ]?12\d{2})\b", t):
            return "CPU - Xeon E3 v5-v6"

        return "CPU - Other LGA1151"

    @staticmethod
    def get_cpu_benchmark(item: ListingItem) -> int:
        """
        Determines the PassMark Multi-Core benchmark rating for a CPU listing.
        """
        if item.category.upper() != "CPU":
            return 0

        t = item.title.lower()

        # Core i7 models (check K and T before base model)
        if re.search(r"\bi7[- ]?7700k\b", t) or "7700k" in t:
            return 9700
        if re.search(r"\bi7[- ]?7700t\b", t) or "7700t" in t:
            return 7200
        if re.search(r"\bi7[- ]?7700\b", t) or "7700" in t:
            return 8650

        if re.search(r"\bi7[- ]?6700k\b", t) or "6700k" in t:
            return 8900
        if re.search(r"\bi7[- ]?6700t\b", t) or "6700t" in t:
            return 6700
        if re.search(r"\bi7[- ]?6700\b", t) or "6700" in t:
            return 8100

        # Specific model matching for Xeons
        for xeon_key in sorted(CPU_BENCHMARKS.keys(), key=len, reverse=True):
            if xeon_key.startswith("e3") and xeon_key in t:
                return CPU_BENCHMARKS[xeon_key]

        # Default fallback for LGA1151 4C/8T
        if "xeon" in t or "e3" in t:
            return 8200

        return 7500

    @staticmethod
    def evaluate_scam_and_trust(item: ListingItem, model_key: str) -> Tuple[str, float]:
        """
        Calculates Seller Trust Score (0-100) and assigns nuanced status tags:
        - Verified-Good
        - Caution-Untested
        - Flagged-Placeholder
        - Flagged-BoxOnly
        - Flagged-Scam
        """
        t = item.title.lower()
        price = item.price
        clean_model = model_key.replace("CPU - ", "")
        baseline = MARKET_BASELINES.get(clean_model, {"min": 30.0, "max": 100.0, "scam_threshold": 15.0})

        # 1. Box-Only / Picture-Only Scam Check
        if re.search(r"\b(box\s*only|empty\s*box|case\s*only|picture\s*only|photo\s*only|no\s*cpu)\b", t):
            return "Flagged-BoxOnly", 0.0

        # 2. Placeholder Prices ($0, $1, $123, $1234)
        if price in (0.0, 1.0, 1.23, 12.34, 123.0, 1234.0) and "facebook" in item.source.lower():
            return "Flagged-Placeholder", 0.0

        # 3. Model-Specific Extreme Price Scam Check
        if price < baseline["scam_threshold"]:
            return "Flagged-Scam", 0.0

        # 4. Untested / For Parts / Damaged Check
        is_untested = bool(re.search(r"\b(untested|for\s*parts|not\s*working|as-is|as\s*is|for\s*repair|bent\s*pins?|salvage)\b", t))

        # 5. Seller Reputation Scoring
        trust_points = 0.0

        # Rating score (up to 35 pts)
        if item.seller_feedback_count > 0:
            if item.seller_rating_pct >= 99.0:
                trust_points += 35.0
            elif item.seller_rating_pct >= 95.0:
                trust_points += 25.0
            elif item.seller_rating_pct >= 90.0:
                trust_points += 10.0
            else:
                trust_points -= 30.0
        else:
            trust_points += 15.0

        # Volume score (up to 25 pts)
        if item.seller_feedback_count >= 500:
            trust_points += 25.0
        elif item.seller_feedback_count >= 100:
            trust_points += 20.0
        elif item.seller_feedback_count >= 20:
            trust_points += 15.0
        elif item.seller_feedback_count >= 5:
            trust_points += 8.0
        else:
            trust_points += 0.0

        # Condition score (up to 25 pts)
        if re.search(r"\b(tested|working|refurbished|functional|guaranteed|clean)\b", t) or item.condition.lower() in ("refurbished", "open box"):
            trust_points += 25.0
        elif not is_untested:
            trust_points += 18.0

        # Untested penalty
        if is_untested:
            trust_points -= 40.0

        # Suspicious 0-feedback extreme discount
        if item.seller_feedback_count == 0 and price < baseline["min"] * 0.5:
            return "Flagged-Scam", 10.0

        final_trust = max(0.0, min(100.0, trust_points))

        if is_untested:
            status = "Caution-Untested"
        else:
            status = "Verified-Good"

        return status, round(final_trust, 1)

    @staticmethod
    def calculate_composite_score(item: ListingItem, model_key: str) -> float:
        """
        Calculates Composite Value Score (0-100) weighting Price (40%), Trust (35%), and Location (25%).
        """
        if item.status in ("Flagged-Scam", "Flagged-Placeholder", "Flagged-BoxOnly"):
            return 0.0

        clean_model = model_key.replace("CPU - ", "")
        baseline = MARKET_BASELINES.get(clean_model, {"min": 30.0, "max": 100.0, "scam_threshold": 15.0})

        # 1. Price Score (0 - 40 pts)
        min_p = baseline["min"]
        max_p = baseline["max"] * 1.4
        price_norm = max(0.0, min(1.0, (max_p - item.price) / (max_p - min_p))) if max_p > min_p else 0.5
        s_price = price_norm * 40.0

        # 2. Trust Score (0 - 35 pts)
        s_trust = (item.trust_score / 100.0) * 35.0

        # 3. Location Score (0 - 25 pts)
        if "local pickup" in item.location_match_type.lower():
            s_loc = 25.0
        elif "marketplace" in item.location_match_type.lower():
            s_loc = 22.0
        elif "approximate" in item.location_match_type.lower():
            s_loc = 15.0
        else:
            s_loc = 8.0

        return round(s_price + s_trust + s_loc, 1)

    @staticmethod
    def calculate_overall_cpu_score(item: ListingItem) -> float:
        """
        Calculates Cross-Model Overall CPU Score (0-100) weighting:
        - Performance Benchmark: 30 pts
        - Price Efficiency (Benchmark-per-Dollar): 35 pts
        - Seller Trust & Condition: 20 pts
        - Location Proximity: 15 pts
        """
        if item.status in ("Flagged-Scam", "Flagged-Placeholder", "Flagged-BoxOnly"):
            return 0.0

        benchmark = item.benchmark_score or 7500

        # 1. Performance Rating Score (0 - 30 pts)
        # Peak baseline = 9,700 (i7-7700K)
        s_perf = min(30.0, 30.0 * (benchmark / 9700.0))

        # 2. Price Efficiency Score (0 - 35 pts)
        # Normalized based on CAD per 1,000 benchmark points
        # Benchmark score per dollar: higher is better
        # Benchmark / price (e.g. 9700 / $97 = 100 pts/$, 8100 / $41 = 197 pts/$)
        if item.price > 0:
            pts_per_dollar = benchmark / item.price
            # Scale: 50 pts/$ is ~10pts, 150+ pts/$ is ~35pts
            s_value = min(35.0, max(5.0, (pts_per_dollar / 160.0) * 35.0))
        else:
            s_value = 0.0

        # 3. Trust Score (0 - 20 pts)
        s_trust = (item.trust_score / 100.0) * 20.0

        # 4. Location Score (0 - 15 pts)
        if "local pickup" in item.location_match_type.lower():
            s_loc = 15.0
        elif "marketplace" in item.location_match_type.lower():
            s_loc = 13.0
        elif "approximate" in item.location_match_type.lower():
            s_loc = 9.0
        else:
            s_loc = 5.0

        return round(s_perf + s_value + s_trust + s_loc, 1)

    def process_all_listings(self, listings: List[ListingItem]) -> Dict[str, List[ListingItem]]:
        """
        Processes all raw listings:
        - Classifies model bucket
        - Determines CPU benchmark rating
        - Evaluates scam status and trust score
        - Calculates composite and overall scores
        - Returns dict of model_bucket -> sorted List[ListingItem]
        """
        buckets: Dict[str, List[ListingItem]] = {model: [] for model in MODEL_ORDER}

        for item in listings:
            model = self.classify_model(item)
            item.model_bucket = model

            # Benchmark rating
            if item.category.upper() == "CPU":
                item.benchmark_score = self.get_cpu_benchmark(item)

            # Evaluate scam & trust
            status, trust = self.evaluate_scam_and_trust(item, model)
            item.status = status
            item.trust_score = trust

            # Calculate composite model score
            item.composite_score = self.calculate_composite_score(item, model)

            # Calculate cross-model overall CPU score
            if item.category.upper() == "CPU":
                item.overall_score = self.calculate_overall_cpu_score(item)

            if model not in buckets:
                buckets[model] = []
            buckets[model].append(item)

        # Sort each bucket: Valid items first by composite score descending, then scams
        for model in buckets:
            buckets[model].sort(
                key=lambda x: (
                    0 if x.status.startswith("Flagged") else 1,
                    x.composite_score,
                    -x.price,
                ),
                reverse=True,
            )

        return buckets

    def get_top_5_per_model(self, buckets: Dict[str, List[ListingItem]]) -> Dict[str, List[ListingItem]]:
        """
        Extracts Top 5 recommended listings for each model bucket (excluding flagged scams).
        """
        top_5: Dict[str, List[ListingItem]] = {}
        for model, items in buckets.items():
            valid_items = [it for it in items if not it.status.startswith("Flagged") and it.status != "Caution-Untested"]
            if len(valid_items) < 5:
                valid_items.extend([it for it in items if it.status == "Caution-Untested"])
            top_5[model] = valid_items[:5]
        return top_5

    def get_top_5_overall_cpus(self, buckets: Dict[str, List[ListingItem]]) -> List[ListingItem]:
        """
        Extracts the Top 5 Overall CPUs across all models, ranked by overall_score
        (Performance + Price Efficiency + Seller Trust + Location).
        """
        all_cpus: List[ListingItem] = []
        for model, items in buckets.items():
            if model.startswith("CPU"):
                valid_items = [it for it in items if not it.status.startswith("Flagged") and it.status != "Caution-Untested"]
                all_cpus.extend(valid_items)

        all_cpus.sort(key=lambda x: x.overall_score, reverse=True)
        return all_cpus[:5]

    def get_top_local_20km_cpus(self, buckets: Dict[str, List[ListingItem]]) -> List[ListingItem]:
        """
        Extracts the Top CPUs strictly within ~20km of Newmarket, ON (Aurora, Bradford, etc.).
        """
        from filters import is_local_20km
        local_cpus: List[ListingItem] = []
        for model, items in buckets.items():
            if model.startswith("CPU"):
                for it in items:
                    if not it.status.startswith("Flagged") and is_local_20km(it.location):
                        local_cpus.append(it)

        local_cpus.sort(key=lambda x: x.overall_score, reverse=True)
        return local_cpus[:5]

    def get_top_local_20km_ram(self, buckets: Dict[str, List[ListingItem]]) -> List[ListingItem]:
        """
        Extracts the Top RAM listings strictly within ~20km of Newmarket, ON.
        """
        from filters import is_local_20km
        local_ram: List[ListingItem] = []
        for it in buckets.get("RAM - DDR4 UDIMM", []):
            if not it.status.startswith("Flagged") and is_local_20km(it.location):
                local_ram.append(it)

        local_ram.sort(key=lambda x: x.composite_score, reverse=True)
        return local_ram[:5]
