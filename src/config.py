"""
config.py — Constants, hyperparameters, and category definitions.

All tunable parameters for synthetic data generation are centralized here
so the entire system can be scaled (e.g., 200 -> 5000 SKUs) with a single change.
"""

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# Global
# ──────────────────────────────────────────────────────────────────────────────
RANDOM_SEED = 42
DATE_START = "2022-01-01"
DATE_END = "2025-12-31"
FREQ = "W-MON"  # Weekly, anchored on Monday


# ──────────────────────────────────────────────────────────────────────────────
# SKU Configuration
# ──────────────────────────────────────────────────────────────────────────────
TOTAL_SKUS = 200  # Change to 5000 for production scale

CATEGORIES = {
    "Spare Parts": {
        "prefix": "SP",
        "share": 0.40,  # 40% of SKUs
        "sub_categories": ["Filters", "Piston Kits", "Gaskets", "Bearings", "Seals"],
        "shelf_life_days": None,  # Metal — no expiry
        "unit_volume_m3": (0.001, 0.02),  # Small parts
        "criticality_range": (2, 4),
        "base_demand_weekly": (5, 50),  # Units per week
        "seasonality": {
            "type": "post_harvest",  # Spikes Nov–Dec
            "multiplier": 1.6,
        },
    },
    "Lubricants": {
        "prefix": "LB",
        "share": 0.15,
        "sub_categories": ["Engine Oil", "Hydraulic Fluid", "Grease", "Coolant"],
        "shelf_life_days": (365, 730),
        "unit_volume_m3": (0.001, 0.005),
        "criticality_range": (1, 3),
        "base_demand_weekly": (10, 80),
        "seasonality": {
            "type": "mild_uptick",  # Slight increase during sowing
            "multiplier": 1.2,
        },
    },
    "Electric Pumps": {
        "prefix": "EP",
        "share": 0.20,
        "sub_categories": [
            "Submersible Pump",
            "Centrifugal Pump",
            "Domestic Pump",
            "Monoblock Pump",
        ],
        "shelf_life_days": (1825, 3650),  # 5–10 years
        "unit_volume_m3": (0.05, 0.3),
        "criticality_range": (3, 5),
        "base_demand_weekly": (2, 20),
        "seasonality": {
            "type": "monsoon_spike",  # Heavy spike May–Jun (pre-monsoon buying)
            "multiplier": 2.5,
        },
    },
    "Engines": {
        "prefix": "EN",
        "share": 0.10,
        "sub_categories": [
            "Diesel Engine",
            "Power Tiller Engine",
            "Pump Engine",
        ],
        "shelf_life_days": (3650, 7300),  # 10–20 years
        "unit_volume_m3": (0.5, 2.0),
        "criticality_range": (4, 5),
        "base_demand_weekly": (1, 8),
        "seasonality": {
            "type": "sowing_aligned",  # Tracks Kharif/Rabi
            "multiplier": 1.4,
        },
    },
    "Precision Components": {
        "prefix": "PC",
        "share": 0.15,
        "sub_categories": [
            "Rotary Assembly",
            "Locomotive Coupling",
            "Precision Gear",
            "Valve Assembly",
        ],
        "shelf_life_days": None,  # Metal — no expiry
        "unit_volume_m3": (0.01, 0.1),
        "criticality_range": (4, 5),
        "base_demand_weekly": (1, 10),
        "seasonality": {
            "type": "steady",
            "multiplier": 1.0,
        },
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Machine Compatibility
# ──────────────────────────────────────────────────────────────────────────────
MACHINE_TYPES = [
    "Power Tiller",
    "Tractor",
    "Pump Set",
    "Diesel Engine",
    "Multi-Purpose",
]

# ──────────────────────────────────────────────────────────────────────────────
# Supplier Configuration
# ──────────────────────────────────────────────────────────────────────────────
TOTAL_SUPPLIERS = 30

SUPPLIER_PROFILES = {
    "Japan": {
        "code": "JP",
        "count_share": 0.20,  # 6 suppliers
        "base_lead_time_days": (45, 90),
        "lead_time_volatility": (0.15, 0.25),  # CV (coefficient of variation)
        "primary_categories": ["Engines", "Precision Components"],
        "cost_multiplier": 1.3,  # Premium
    },
    "China": {
        "code": "CN",
        "count_share": 0.30,  # 9 suppliers
        "base_lead_time_days": (30, 75),
        "lead_time_volatility": (0.30, 0.50),  # Highest variance
        "primary_categories": ["Electric Pumps", "Spare Parts"],
        "cost_multiplier": 0.8,  # Budget
    },
    "Germany": {
        "code": "DE",
        "count_share": 0.15,  # ~4-5 suppliers
        "base_lead_time_days": (60, 120),
        "lead_time_volatility": (0.10, 0.20),
        "primary_categories": ["Precision Components"],
        "cost_multiplier": 1.5,  # Premium
    },
    "India": {
        "code": "IN",
        "count_share": 0.35,  # ~10-11 suppliers
        "base_lead_time_days": (7, 30),
        "lead_time_volatility": (0.05, 0.15),  # Most reliable
        "primary_categories": ["Spare Parts", "Lubricants"],
        "cost_multiplier": 1.0,  # Baseline
    },
}

# Base unit costs per category (INR)
BASE_UNIT_COSTS = {
    "Spare Parts": (150, 2500),
    "Lubricants": (200, 1500),
    "Electric Pumps": (3000, 25000),
    "Engines": (15000, 150000),
    "Precision Components": (5000, 50000),
}

# MOQ ranges per category
MOQ_RANGES = {
    "Spare Parts": (20, 200),
    "Lubricants": (50, 500),
    "Electric Pumps": (5, 50),
    "Engines": (1, 10),
    "Precision Components": (5, 30),
}

# ──────────────────────────────────────────────────────────────────────────────
# Fulfillment Regions
# ──────────────────────────────────────────────────────────────────────────────
FULFILLMENT_REGIONS = {
    "South India": 0.60,
    "West India": 0.20,
    "North India": 0.15,
    "Export": 0.05,
}

# ──────────────────────────────────────────────────────────────────────────────
# Stockout Configuration
# ──────────────────────────────────────────────────────────────────────────────
BASE_STOCKOUT_RATE = 0.08  # 8% baseline
PEAK_STOCKOUT_RATE = 0.15  # 15% during high-demand seasons

# ──────────────────────────────────────────────────────────────────────────────
# Visualization
# ──────────────────────────────────────────────────────────────────────────────
CHART_STYLE = "seaborn-v0_8-darkgrid"
FIGURE_DPI = 150
COLOR_PALETTE = {
    "primary": "#1B4F72",      # Deep navy
    "secondary": "#2ECC71",    # Green (fill rate)
    "danger": "#E74C3C",       # Red (stockouts)
    "warning": "#F39C12",      # Amber (alerts)
    "info": "#3498DB",         # Blue
    "categories": ["#1B4F72", "#2ECC71", "#E74C3C", "#F39C12", "#9B59B6"],
}
OUTPUT_DIR = "output/charts"
DATA_DIR = "data"
