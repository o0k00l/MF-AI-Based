"""
services/acquisition/adapters - Upstream financial data source adapters.
"""

from services.acquisition.adapters.base import BaseSourceAdapter
from services.acquisition.adapters.amfi_nav import AmfiNavAdapter
from services.acquisition.adapters.amfi_scheme_master import AmfiSchemeMasterAdapter
from services.acquisition.adapters.portfolio_disclosure import PortfolioDisclosureAdapter

__all__ = [
    "BaseSourceAdapter",
    "AmfiNavAdapter",
    "AmfiSchemeMasterAdapter",
    "PortfolioDisclosureAdapter",
]
