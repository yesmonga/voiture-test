"""
La Centrale Scraper avec curl-cffi + Cookie DataDome + Proxy Résidentiel
Le cookie DataDome doit être obtenu manuellement depuis un navigateur.
"""

import re
import os
from dataclasses import dataclass
from typing import Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.rate_limiter import get_rate_limiter


# Proxies résidentiels FR
RESIDENTIAL_PROXIES = [
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-f994hiwl-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-q2r6263u-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-1n4t8nkg-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-jp6c4ji7-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-xkcvd8ij-duration-60@resi.thexyzstore.com:8000",
]

# Cookie DataDome (à mettre à jour si expiré)
# Peut être défini via variable d'environnement DATADOME_COOKIE
DEFAULT_DATADOME_COOKIE = "EJwWhPHu4rVS7bGzvnk1awXmv9If_ACKwLMvdSzVHn_XB4O1ZlWNAALOAKZzLuozoO1nxyrEikmr91xImcF_aYswGHRXamM2JsRso_CTnz3TcTeMe6IT9ty3fcNI6Smi"


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


class LaCentraleCurlScraper:
    """
    Scraper La Centrale utilisant curl-cffi avec:
    - Cookie DataDome (bypass anti-bot)
    - Proxy résidentiel FR
    - Impersonation Firefox
    """
    
    BASE_URL = "https://www.lacentrale.fr"
    
    CARBURANTS = {
        "diesel": "DIESEL",
        "essence": "ESSENCE",
    }
    
    def __init__(self, config: LaCentraleConfig = None, use_proxy: bool = True):
        self.config = config or LaCentraleConfig()
        self._rate_limiter = get_rate_limiter()
        self._use_proxy = use_proxy
        self._proxy_index = 0
        self._datadome_cookie = os.getenv("DATADOME_COOKIE", DEFAULT_DATADOME_COOKIE)
    
    def _get_next_proxy(self) -> Optional[str]:
        """Retourne le prochain proxy en rotation"""
        if not self._use_proxy or not RESIDENTIAL_PROXIES:
            return None
        proxy = RESIDENTIAL_PROXIES[self._proxy_index % len(RESIDENTIAL_PROXIES)]
        self._proxy_index += 1
        return proxy
    
    async def close(self):
        pass
    
    def build_search_url(self, page: int = 1) -> str:
        """Construit l'URL de recherche La Centrale"""
        cfg = self.config
        params = []
        
        # Marque et modèle
        marque = cfg.marque.upper()
        if cfg.modele:
            params.append(f"makesModelsCommercialNames={marque}%3A{cfg.modele.upper()}")
        else:
            params.append(f"makesModelsCommercialNames={marque}")
        
        # Prix
        if cfg.prix_min:
            params.append(f"priceMin={cfg.prix_min}")
        if cfg.prix_max:
            params.append(f"priceMax={cfg.prix_max}")
        
        # Kilométrage
        if cfg.km_min:
            params.append(f"mileageMin={cfg.km_min}")
        if cfg.km_max:
            params.append(f"mileageMax={cfg.km_max}")
        
        # Année
        if cfg.annee_min:
            params.append(f"yearMin={cfg.annee_min}")
        if cfg.annee_max:
            params.append(f"yearMax={cfg.annee_max}")
        
        # Carburant
        if cfg.carburant and cfg.carburant.lower() in self.CARBURANTS:
            params.append(f"energies={self.CARBURANTS[cfg.carburant.lower()]}")
        
        # Particulier seulement
        if cfg.particulier_only:
            params.append("customerType=part")
        
        # Tri par date
        params.append("sortBy=firstOnlineDateDesc")
        
        # Pagination
        if page > 1:
            params.append(f"page={page}")
        
        return f"{self.BASE_URL}/listing?{'&'.join(params)}"
    
    def _fetch_sync(self, url: str) -> Optional[str]:
        """Fetch synchrone avec curl-cffi + cookie DataDome + proxy"""
        proxy = self._get_next_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3',
            'Cookie': f'datadome={self._datadome_cookie}',
        }
        
        try:
            response = curl_requests.get(
                url,
                headers=headers,
                proxies=proxies,
                impersonate="firefox",
                timeout=30,
            )
            if response.status_code == 200 and len(response.text) > 10000:
                return response.text
            else:
                print(f"   ⚠️ LaCentrale status {response.status_code}, len={len(response.text)}")
                if response.status_code == 403:
                    print("   ⚠️ Cookie DataDome expiré - besoin de renouvellement")
                return None
        except Exception as e:
            print(f"   ❌ LaCentrale fetch error: {e}")
            return None
    
    def _parse_listing_html(self, html: str) -> list[IndexResult]:
        """Parse le HTML de la page de listing"""
        results: list[IndexResult] = []
        soup = BeautifulSoup(html, 'lxml')
        
        # Trouver tous les liens vers les annonces
        annonce_links = soup.find_all('a', href=re.compile(r'auto-occasion-annonce-\d+'))
        seen_ids: set[str] = set()
        
        for link in annonce_links:
            try:
                href = link.get('href', '')
                id_match = re.search(r'auto-occasion-annonce-(\d+)', href)
                if not id_match:
                    continue
                
                listing_id = id_match.group(1)
                if listing_id in seen_ids:
                    continue
                seen_ids.add(listing_id)
                
                url = f"{self.BASE_URL}{href}" if not href.startswith('http') else href
                
                # Remonter au conteneur parent pour extraire les infos
                container = link.find_parent('div', recursive=True) or link.find_parent('article')
                if not container:
                    container = link
                
                text = container.get_text(' ', strip=True)
                
                # Titre
                titre = ""
                h2 = container.find('h2') or container.find('h3')
                if h2:
                    titre = h2.get_text(strip=True)
                if not titre:
                    titre = f"{self.config.marque.capitalize()} {self.config.modele}".strip()
                
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
                
                # Département
                dept = ""
                dept_match = re.search(r'\((\d{2})\)', text)
                if dept_match:
                    dept = dept_match.group(1)
                
                # Image
                thumbnail = ""
                img = container.find('img')
                if img:
                    thumbnail = img.get('src') or img.get('data-src') or ""
                
                results.append(IndexResult(
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
                ))
                
            except Exception:
                continue
        
        return results
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """Scan les pages de résultats La Centrale"""
        max_pages = kwargs.get("max_pages", 2)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        # Rate limiting
        can_proceed = await self._rate_limiter.wait_for_slot("lacentrale")
        if not can_proceed:
            print("⏸️ LaCentrale: circuit breaker actif")
            return []
        
        for page_num in range(1, max_pages + 1):
            url = self.build_search_url(page_num)
            print(f"📡 Scanning LaCentrale (curl-cffi) page {page_num}: {url[:65]}...")
            
            html = self._fetch_sync(url)
            if not html:
                self._rate_limiter.record_failure("lacentrale")
                break
            
            page_results = self._parse_listing_html(html)
            print(f"   Found {len(page_results)} listings in HTML")
            
            new_count = 0
            for result in page_results:
                if result.source_listing_id not in seen_ids:
                    seen_ids.add(result.source_listing_id)
                    results.append(result)
                    new_count += 1
            
            print(f"   Parsed {new_count} listings (total: {len(results)})")
            self._rate_limiter.record_success("lacentrale")
            
            if new_count < 3:
                break
        
        return results


class LaCentraleCurlDetailScraper:
    """Detail scraper pour La Centrale"""
    
    async def close(self):
        pass
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        # Pour l'instant, on skip le detail scraping
        return None
