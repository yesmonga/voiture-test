"""
Facebook Marketplace Scraper V1 - SKELETON
⚠️ ATTENTION: Nécessite authentification Facebook + anti-bot très strict.

Ce skeleton est prêt à être complété mais NE FONCTIONNE PAS sans login.

TODO:
- [ ] Implémenter avec Playwright + session Facebook authentifiée
- [ ] Gérer le login Facebook (cookies persistants)
- [ ] Parser les listings via GraphQL ou DOM
- [ ] Attention aux Terms of Service Facebook

ALTERNATIVE: Utiliser l'API Facebook Graph (nécessite app review)
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.rate_limiter import get_rate_limiter


@dataclass
class MarketplaceConfig:
    """Configuration pour les recherches Facebook Marketplace"""
    marque: str = "peugeot"
    modele: str = ""
    prix_min: int = 0
    prix_max: int = 2000
    km_min: int = 0
    km_max: int = 180000
    location: str = "Paris, France"
    radius_km: int = 100


class MarketplaceIndexScraper:
    """
    Index scraper pour Facebook Marketplace.
    
    ⚠️ SKELETON - Nécessite login Facebook.
    
    Options d'implémentation:
    1. Playwright + cookies Facebook persistants (risque ban compte)
    2. Facebook Graph API (nécessite app review, accès limité)
    3. Service tiers (ex: Apify Marketplace scraper)
    """
    
    BASE_URL = "https://www.facebook.com/marketplace"
    
    # État: désactivé par défaut
    ENABLED = False
    BLOCKED_REASON = "Nécessite authentification Facebook"
    
    def __init__(self, config: MarketplaceConfig = None):
        self.config = config or MarketplaceConfig()
        self._rate_limiter = get_rate_limiter()
        
        self._fallback_marque: str = ""
        self._fallback_modele: str = ""
    
    async def close(self):
        """Cleanup"""
        pass
    
    def build_search_url(self) -> str:
        """Construit l'URL de recherche Marketplace"""
        cfg = self.config
        
        # URL de base pour les véhicules
        # Note: Les paramètres exacts changent souvent
        query = f"{cfg.marque} {cfg.modele}".strip()
        
        return f"{self.BASE_URL}/category/vehicles?query={query}&minPrice={cfg.prix_min}&maxPrice={cfg.prix_max}"
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """
        ⚠️ SKELETON - Retourne une liste vide.
        
        Pour implémenter avec Playwright:
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # headless=False requis
            context = await browser.new_context(storage_state="facebook_cookies.json")
            page = await context.new_page()
            await page.goto(self.build_search_url())
            
            # Attendre le chargement des listings
            await page.wait_for_selector('[data-testid="marketplace_search_results"]')
            
            # Parser les résultats
            listings = await page.query_selector_all('[data-testid="marketplace_feed_item"]')
            
            for listing in listings:
                # Extraire les données...
                pass
        """
        if not self.ENABLED:
            print(f"⚠️ Marketplace: {self.BLOCKED_REASON}")
            return []
        
        return []


class MarketplaceDetailScraper:
    """
    Detail scraper pour Facebook Marketplace.
    ⚠️ SKELETON
    """
    
    def __init__(self):
        self._rate_limiter = get_rate_limiter()
    
    async def close(self):
        pass
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        """⚠️ SKELETON - Retourne None"""
        print(f"⚠️ Marketplace detail: skeleton, non implémenté")
        return None


def create_marketplace_scraper(
    config: MarketplaceConfig = None
) -> tuple[MarketplaceIndexScraper, MarketplaceDetailScraper]:
    """Crée une paire (index, detail) scraper pour Marketplace"""
    return (
        MarketplaceIndexScraper(config),
        MarketplaceDetailScraper()
    )
