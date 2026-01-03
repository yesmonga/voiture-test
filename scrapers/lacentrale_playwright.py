"""
La Centrale Scraper via Playwright - Pour contourner le JS rendering
Production-grade avec anti-détection
"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.rate_limiter import get_rate_limiter


@dataclass
class LaCentraleConfig:
    """Configuration pour les recherches La Centrale"""
    marque: str = "peugeot"
    modele: str = ""
    prix_min: int = 0
    prix_max: int = 2000
    km_min: int = 0
    km_max: int = 180000
    annee_min: int = 2006
    annee_max: int = 2014
    carburant: str = "diesel"
    particulier_only: bool = True


class LaCentralePlaywrightScraper:
    """
    Scraper La Centrale via Playwright.
    Headless browser pour contourner l'anti-bot.
    """
    
    BASE_URL = "https://www.lacentrale.fr"
    
    CARBURANTS = {
        "diesel": "DIESEL",
        "essence": "ESSENCE",
    }
    
    def __init__(self, config: LaCentraleConfig = None):
        self.config = config or LaCentraleConfig()
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._rate_limiter = get_rate_limiter()
        
        self._fallback_marque: str = ""
        self._fallback_modele: str = ""
    
    async def _ensure_browser(self):
        """Initialise le browser si nécessaire"""
        if self._browser is None:
            playwright = await async_playwright().start()
            self._browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="fr-FR",
            )
    
    async def close(self):
        """Ferme le browser"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        self._browser = None
        self._context = None
    
    def build_search_url(self, page_num: int = 1) -> str:
        """Construit l'URL de recherche"""
        cfg = self.config
        params = []
        
        marque = cfg.marque.upper()
        if cfg.modele:
            params.append(f"makesModelsCommercialNames={marque}%3A{cfg.modele.upper()}")
        else:
            params.append(f"makesModelsCommercialNames={marque}")
        
        if cfg.prix_min:
            params.append(f"priceMin={cfg.prix_min}")
        if cfg.prix_max:
            params.append(f"priceMax={cfg.prix_max}")
        if cfg.km_min:
            params.append(f"mileageMin={cfg.km_min}")
        if cfg.km_max:
            params.append(f"mileageMax={cfg.km_max}")
        if cfg.annee_min:
            params.append(f"yearMin={cfg.annee_min}")
        if cfg.annee_max:
            params.append(f"yearMax={cfg.annee_max}")
        if cfg.carburant and cfg.carburant.lower() in self.CARBURANTS:
            params.append(f"energies={self.CARBURANTS[cfg.carburant.lower()]}")
        if cfg.particulier_only:
            params.append("customerType=part")
        
        params.append("sortBy=firstOnlineDateDesc")
        if page_num > 1:
            params.append(f"page={page_num}")
        
        return f"{self.BASE_URL}/listing?{'&'.join(params)}"
    
    async def _extract_listings_from_page(self, page: Page) -> list[dict]:
        """Extrait les listings depuis la page rendue"""
        listings = []
        
        # Attendre le chargement des résultats
        try:
            await page.wait_for_selector('[data-testid="classified-card"], .searchCard, article', timeout=10000)
        except Exception:
            print("   ⚠️ Timeout waiting for listings")
            return []
        
        # Extraire via JavaScript
        raw_listings = await page.evaluate("""
            () => {
                const listings = [];
                const cards = document.querySelectorAll('[data-testid="classified-card"], .searchCard, article');
                
                cards.forEach(card => {
                    try {
                        const link = card.querySelector('a[href*="auto-occasion"]') || card.querySelector('a');
                        if (!link) return;
                        
                        const href = link.getAttribute('href') || '';
                        const idMatch = href.match(/-(\\d{6,})\\.html/) || href.match(/(\\d{6,})/);
                        if (!idMatch) return;
                        
                        const titleEl = card.querySelector('[class*="Title"], h2, h3');
                        const priceEl = card.querySelector('[class*="Price"], [class*="price"]');
                        const kmEl = card.querySelector('[class*="mileage"], [class*="km"]');
                        const yearEl = card.querySelector('[class*="year"]');
                        const locEl = card.querySelector('[class*="location"], [class*="city"]');
                        const imgEl = card.querySelector('img');
                        
                        const priceText = priceEl?.textContent || '';
                        const priceMatch = priceText.replace(/[^\\d]/g, '');
                        
                        const kmText = kmEl?.textContent || '';
                        const kmMatch = kmText.replace(/[^\\d]/g, '');
                        
                        listings.push({
                            id: idMatch[1],
                            url: href.startsWith('http') ? href : 'https://www.lacentrale.fr' + href,
                            title: titleEl?.textContent?.trim() || '',
                            price: priceMatch ? parseInt(priceMatch) : null,
                            km: kmMatch ? parseInt(kmMatch) : null,
                            year: yearEl?.textContent?.match(/\\d{4}/)?.[0] || null,
                            location: locEl?.textContent?.trim() || '',
                            image: imgEl?.src || imgEl?.getAttribute('data-src') || ''
                        });
                    } catch (e) {}
                });
                
                return listings;
            }
        """)
        
        return raw_listings
    
    def _parse_listing(self, raw: dict) -> Optional[IndexResult]:
        """Parse un listing brut en IndexResult"""
        try:
            listing_id = str(raw.get("id", ""))
            if not listing_id:
                return None
            
            url = raw.get("url", "")
            titre = raw.get("title", "") or f"{self._fallback_marque} {self._fallback_modele}".strip()
            prix = raw.get("price")
            km = raw.get("km")
            
            annee = None
            if raw.get("year"):
                try:
                    annee = int(raw["year"])
                except ValueError:
                    pass
            
            location = raw.get("location", "")
            dept = ""
            dept_match = re.search(r'\((\d{2})\)', location)
            if dept_match:
                dept = dept_match.group(1)
            
            return IndexResult(
                url=url,
                source=Source.LACENTRALE,
                titre=titre,
                prix=prix,
                kilometrage=km,
                annee=annee,
                ville=location.split("(")[0].strip() if "(" in location else location,
                departement=dept,
                published_at=None,
                thumbnail_url=raw.get("image", ""),
                source_listing_id=listing_id,
                marque=self._fallback_marque,
                modele=self._fallback_modele,
            )
        except Exception as e:
            print(f"   ⚠️ Parse error: {e}")
            return None
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """Scan les pages de résultats via Playwright"""
        max_pages = kwargs.get("max_pages", 1)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        # Rate limiting
        can_proceed = await self._rate_limiter.wait_for_slot("lacentrale")
        if not can_proceed:
            print("⏸️ LaCentrale: circuit breaker actif")
            return []
        
        try:
            await self._ensure_browser()
            page = await self._context.new_page()
            
            for page_num in range(1, max_pages + 1):
                url = self.build_search_url(page_num)
                print(f"📡 Scanning LaCentrale (Playwright) page {page_num}: {url[:70]}...")
                
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(2)  # Laisser le JS se charger
                    
                    raw_listings = await self._extract_listings_from_page(page)
                    print(f"   Found {len(raw_listings)} listings via Playwright")
                    
                    page_count = 0
                    for raw in raw_listings:
                        result = self._parse_listing(raw)
                        if result and result.source_listing_id not in seen_ids:
                            seen_ids.add(result.source_listing_id)
                            results.append(result)
                            page_count += 1
                    
                    print(f"   Parsed {page_count} new listings (total: {len(results)})")
                    self._rate_limiter.record_success("lacentrale")
                    
                    if page_count < 3:
                        break
                        
                except Exception as e:
                    print(f"   ❌ Page error: {e}")
                    self._rate_limiter.record_failure("lacentrale")
                    break
            
            await page.close()
            
        except Exception as e:
            print(f"❌ LaCentrale Playwright error: {e}")
            self._rate_limiter.record_failure("lacentrale")
        
        return results


class LaCentralePlaywrightDetailScraper:
    """Detail scraper via Playwright"""
    
    def __init__(self):
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._rate_limiter = get_rate_limiter()
    
    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        # Pour l'instant, on skip le détail via Playwright (trop lent)
        return None


def create_lacentrale_playwright_scraper(config: LaCentraleConfig = None):
    """Crée les scrapers Playwright pour LaCentrale"""
    return (
        LaCentralePlaywrightScraper(config),
        LaCentralePlaywrightDetailScraper()
    )
