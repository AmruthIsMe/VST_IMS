"""
Shared constants for VST IMS forecasting and dashboard.
Single source of truth for risk thresholds, category mappings, etc.
"""

# SKU prefix → category mapping (fallback when products table is unavailable)
SKU_CATEGORY_PREFIX = {
    "SP": "Spare Parts",
    "LU": "Lubricants",
    "EP": "Electric Pumps",
    "EN": "Engines",
    "PC": "Precision Components",
}


def get_risk_level(coverage_weeks: float, trend: float = 1.0, shortfall: float = 0) -> str:
    """
    Classify stock risk based on coverage weeks, demand trend, and shortfall.
    
    Args:
        coverage_weeks: Weeks of stock remaining at current burn rate (None = no demand)
        trend: Demand trend ratio (>1.0 = increasing demand)
        shortfall: Units shortfall for the period
    
    Returns:
        "CRITICAL", "HIGH", "MEDIUM", or "LOW"
    """
    if coverage_weeks is None:
        return "LOW"
    if coverage_weeks < 4 or shortfall > 0 or (coverage_weeks < 6 and trend > 1.1):
        return "CRITICAL"
    elif coverage_weeks < 6:
        return "HIGH"
    elif coverage_weeks < 8:
        return "MEDIUM"
    else:
        return "LOW"


def get_stockout_severity(coverage_weeks: float) -> str:
    """
    Determine stockout alert severity based on coverage weeks.
    
    Returns:
        "CRITICAL" if < 4 weeks, "HIGH" if < 6 weeks, else None
    """
    if coverage_weeks is None:
        return None
    if coverage_weeks < 4:
        return "CRITICAL"
    elif coverage_weeks < 6:
        return "HIGH"
    return None
