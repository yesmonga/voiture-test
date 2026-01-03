"""
La Centrale Scraper avec Proxy Résidentiel + Playwright
Nécessite warm-up session pour bypass DataDome
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from bs4 import BeautifulSoup

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.rate_limiter import get_rate_limiter


# Proxies résidentiels FR
RESIDENTIAL_PROXIES = [
    {"server": "http://resi.thexyzstore.com:8000", "username": "aigrinchxyz", "password": "8jqb7dml-country-FR-hardsession-f994hiwl-duration-60"},
    {"server": "http://resi.thexyzstore.com:8000", "username": "aigrinchxyz", "password": "8jqb7dml-country-FR-hardsession-q2r6263u-duration-60"},
    {"server": "http://resi.thexyzstore.com:8000", "username": "aigrinchxyz", "password": "8jqb7dml-country-FR-hardsession-1n4t8nkg-duration-60"},
    {"server": "http://resi.thexyzstore.com:8000", "username": "aigrinchxyz", "password": "8jqb7dml-country-FR-hardsession-jp6c4ji7-duration-60"},
    {"server": "http://resi.thexyzstore.com:8000", "username": "aigrinchxyz", "password": "8jqb7dml-country-FR-hardsession-xkcvd8ij-duration-60"},
]


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


class LaCentraleProxyScraper:
    """
    Scraper LaCentrale avec proxy résidentiel + Playwright.
    Utilise warm-up session pour bypass DataDome.
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
        self._page: Optional[Page] = None
        self._rate_limiter = get_rate_limiter()
        self._proxy_index = 0
        self._warmed_up = False
    
    def _get_next_proxy(self) -> dict:
        """Retourne le prochain proxy en rotation"""
        proxy = RESIDENTIAL_PROXIES[self._proxy_index % len(RESIDENTIAL_PROXIES)]
        self._proxy_index += 1
        return proxy
    
    async def _ensure_browser(self):
        """Initialise le browser avec proxy"""
        if self._browser is None:
            proxy = self._get_next_proxy()
            print(f"   🔄 Using proxy: {proxy['server']}")
            
            playwright = await async_playwright().start()
            self._browser = await playwright.chromium.launch(
                headless=True,
                proxy=proxy,
                args=['--disable-blink-features=AutomationControlled']
            )
            self._context = await self._browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='fr-FR',
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            )
            self._page = await self._context.new_page()
            
            # Stealth
            await self._page.add_init_script('''
                Object.defineProperty(navigator, "webdriver", {get: () => undefined});
            ''')
    
    async def _warm_up(self):
        """Warm-up session en visitant la homepage"""
        if self._warmed_up:
            return
        
        print("   🔥 Warming up session...")
        try:
            await self._page.goto(f"{self.BASE_URL}/", wait_until='networkidle', timeout=30000)
            await asyncio.sleep(2)
            self._warmed_up = True
            print("   ✅ Warm-up done")
        except Exception as e:
            print(f"   ⚠️ Warm-up error: {e}")
    
    async def close(self):
        """Ferme le browser"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        self._browser = None
        self._context = None
        self._page = None
        self._warmed_up = False
    
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
    
    def _parse_card(self, card) -> Optional[IndexResult]:
        """Parse une carte d'annonce HTML"""
        try:
            # Lien
            link = card.find('a', href=True)
            if not link:
                return None
            
            href = link.get('href', '')
            if '/auto-occasion-annonce-' not in href:
                return None
            
            # ID
            id_match = re.search(r'-(\d{6,})\.html', href)
            if not id_match:
                return None
            
            listing_id = id_match.group(1)
            url = f"{self.BASE_URL}{href}" if not href.startswith('http') else href
            
            # Texte pour extraction
            text = card.get_text(' ', strip=True)
            
            # Titre
            titre_elem = card.find('h2') or card.find('h3') or card.find(class_=re.compile(r'title', re.I))
            titre = titre_elem.get_text(strip=True) if titre_elem else ""
            if not titre:
                titre = f"{self.config.marque} {self.config.modele}".strip()
            
            # Prix
            prix = None
            prix_match = re.search(r'(\d[\d\s]*?)\s*€', text)
            if prix_match:
                prix_str = prix_match.group(1).replace(' ', '').replace('\xa0', '')
                if prix_str.isdigit():
                    prix = int(prix_str)
            
            # Kilométrage
            km = None
            km_match = re.search(r'(\d[\d\s]*?)\s*km', text, re.I)
            if km_match:
                km_str = km_match.group(1).replace(' ', '').replace('\xa0', '')
                if km_str.isdigit() and int(km_str) < 500000:
                    km = int(km_str)
            
            # Année
            annee = None
            year_match = re.search(r'\b(20[0-2]\d|19[89]\d)\b', text)
            if year_match:
                annee = int(year_match.group(1))
            
            # Localisation
            dept = ""
            dept_match = re.search(r'\((\d{2})\)', text)
            if dept_match:
                dept = dept_match.group(1)
            
            # Image
            thumbnail = ""
            img = card.find('img')
            if img:
                thumbnail = img.get('src') or img.get('data-src') or ""
            
            return IndexResult(
                url=url,
                source=Source.LACENTRALE,
                titre=titre[:100],
                prix=prix,
                kilometrage=km,
                annee=annee,
                ville="",
                departement=dept,
                published_at=None,
                thumbnail_url=thumbnail,
                source_listing_id=listing_id,
                marque=self.config.marque.capitalize(),
                modele=self.config.modele,
            )
        except Exception as e:
            return None
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """Scan les pages de résultats"""
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
            await self._warm_up()
            
            for page_num in range(1, max_pages + 1):
                url = self.build_search_url(page_num)
                print(f"📡 Scanning LaCentrale (proxy) page {page_num}: {url[:65]}...")
                
                try:
                    await self._page.goto(url, wait_until='networkidle', timeout=30000)
                    await asyncio.sleep(3)
                    
                    html = await self._page.content()
                    soup = BeautifulSoup(html, 'lxml')
                    
                    # Chercher les cartes
                    cards = soup.find_all(class_=re.compile(r'searchCard|classified', re.I))
                    print(f"   Found {len(cards)} cards")
                    
                    page_count = 0
                    for card in cards:
                        result = self._parse_card(card)
                        if result and result.source_listing_id not in seen_ids:
                            seen_ids.add(result.source_listing_id)
                            results.append(result)
                            page_count += 1
                    
                    print(f"   Parsed {page_count} listings (total: {len(results)})")
                    self._rate_limiter.record_success("lacentrale")
                    
                    if page_count < 3:
                        break
                    
                except Exception as e:
                    print(f"   ❌ Page error: {e}")
                    self._rate_limiter.record_failure("lacentrale")
                    break
                
        except Exception as e:
            print(f"❌ LaCentrale error: {e}")
            self._rate_limiter.record_failure("lacentrale")
        
        return results


class LaCentraleProxyDetailScraper:
    """Detail scraper (skip pour l'instant - trop lent)"""
    
    async def close(self):
        pass
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        return None


def create_lacentrale_proxy_scraper(config: LaCentraleConfig = None):
    return LaCentraleProxyScraper(config), LaCentraleProxyDetailScraper()
