# V2 Scrapers (Production)
# Import directly to avoid legacy chain issues
try:
    from .autoscout24_v2 import (
        AutoScout24IndexScraper,
        AutoScout24DetailScraper,
        AutoScout24Config,
    )
except ImportError:
    AutoScout24IndexScraper = None
    AutoScout24DetailScraper = None
    AutoScout24Config = None

# Legacy scrapers - commented out to avoid import issues
# from .base_scraper import BaseScraper
# from .leboncoin import LeBoncoinScraper
# from .lacentrale import LaCentraleScraper
# from .paruvendu import ParuVenduScraper
# from .autoscout import AutoScout24Scraper

__all__ = [
    # V2 Production
    "AutoScout24IndexScraper",
    "AutoScout24DetailScraper", 
    "AutoScout24Config",
]
