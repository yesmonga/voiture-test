"""
ParuVendu Scraper V1 - Production-grade
Compatible avec le pipeline Orchestrator (IndexScraper/DetailScraper)
"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.rate_limiter import get_rate_limiter


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


@dataclass
class ParuVenduConfig:
    """Configuration pour les recherches ParuVendu"""
    marque: str = "peugeot"
    modele: str = ""
    prix_min: int = 0
    prix_max: int = 2000
    km_min: int = 0
    km_max: int = 180000
    annee_min: int = 2006
    annee_max: int = 2014
    carburant: str = "diesel"
    region: str = ""  # Vide = France entière
    particulier_only: bool = True


class ParuVenduIndexScraper:
    """
    Index scraper pour ParuVendu.
    Parsing HTML robuste avec fallback.
    """
    
    BASE_URL = "https://www.paruvendu.fr"
    
    MARQUES_CODES = {
        "peugeot": "PEUGEOT",
        "renault": "RENAULT",
        "citroen": "CITROEN",
        "dacia": "DACIA",
        "ford": "FORD",
        "volkswagen": "VOLKSWAGEN",
        "opel": "OPEL",
        "toyota": "TOYOTA",
        "nissan": "NISSAN",
        "fiat": "FIAT",
    }
    
    CARBURANTS = {
        "diesel": "D",
        "essence": "E",
        "hybride": "H",
        "electrique": "L",
    }
    
    def __init__(self, config: ParuVenduConfig = None):
        self.config = config or ParuVenduConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._ua_index = 0
        self._rate_limiter = get_rate_limiter()
        
        self._fallback_marque: str = ""
        self._fallback_modele: str = ""
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _get_headers(self) -> dict[str, str]:
        self._ua_index = (self._ua_index + 1) % len(USER_AGENTS)
        return {
            "User-Agent": USER_AGENTS[self._ua_index],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    
    def build_search_url(self, page: int = 1) -> str:
        """Construit l'URL de recherche ParuVendu"""
        cfg = self.config
        
        params = {}
        
        # Marque
        marque_lower = cfg.marque.lower()
        if marque_lower in self.MARQUES_CODES:
            params["ma0"] = self.MARQUES_CODES[marque_lower]
        
        # Prix
        if cfg.prix_min:
            params["px0"] = cfg.prix_min
        if cfg.prix_max:
            params["px1"] = cfg.prix_max
        
        # Kilométrage
        if cfg.km_min:
            params["km0"] = cfg.km_min
        if cfg.km_max:
            params["km1"] = cfg.km_max
        
        # Année
        if cfg.annee_min:
            params["am0"] = cfg.annee_min
        if cfg.annee_max:
            params["am1"] = cfg.annee_max
        
        # Carburant
        if cfg.carburant and cfg.carburant.lower() in self.CARBURANTS:
            params["ca"] = self.CARBURANTS[cfg.carburant.lower()]
        
        # Particulier uniquement
        if cfg.particulier_only:
            params["ty"] = "P"
        
        # Tri par date
        params["tri"] = "da"
        
        # Pagination
        if page > 1:
            params["p"] = page
        
        return f"{self.BASE_URL}/auto-moto/voiture/?{urlencode(params)}"
    
    async def _fetch_html(self, url: str) -> tuple[int, str]:
        """Fetch une page avec rate limiting"""
        can_proceed = await self._rate_limiter.wait_for_slot("paruvendu")
        if not can_proceed:
            return 0, ""
        
        client = await self._get_client()
        
        try:
            response = await client.get(url, headers=self._get_headers())
            
            if response.status_code == 200:
                self._rate_limiter.record_success("paruvendu")
            elif response.status_code in (403, 429, 503):
                self._rate_limiter.record_failure("paruvendu", is_block=True)
            else:
                self._rate_limiter.record_failure("paruvendu")
            
            return response.status_code, response.text
            
        except Exception as e:
            print(f"⚠️ ParuVendu fetch error: {e}")
            self._rate_limiter.record_failure("paruvendu")
            return 0, ""
    
    def _parse_listing_card(self, card, soup) -> Optional[IndexResult]:
        """Parse une carte d'annonce HTML"""
        try:
            # Lien et ID
            link = card.find("a", href=True)
            if not link:
                return None
            
            href = link.get("href", "")
            if not href or "annonce" not in href.lower() and "auto" not in href.lower():
                return None
            
            # Extraire ID de l'URL
            listing_id = ""
            id_match = re.search(r'/(\d+)(?:\.htm|$|\?)', href)
            if id_match:
                listing_id = id_match.group(1)
            else:
                id_match = re.search(r'a(\d+)', href)
                if id_match:
                    listing_id = id_match.group(1)
            
            if not listing_id:
                return None
            
            url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            
            # Titre
            titre = ""
            titre_elem = card.find(class_=re.compile(r"title|titre", re.I)) or \
                        card.find("h2") or card.find("h3") or \
                        card.find(class_=re.compile(r"ann", re.I))
            if titre_elem:
                titre = titre_elem.get_text(strip=True)
            elif link.get("title"):
                titre = link.get("title")
            
            # Prix
            prix = None
            prix_elem = card.find(class_=re.compile(r"price|prix", re.I))
            if prix_elem:
                prix_text = prix_elem.get_text()
                clean = re.sub(r"[^\d]", "", prix_text)
                if clean and 100 <= int(clean) <= 100000:
                    prix = int(clean)
            
            # Kilométrage et année depuis le texte
            km = None
            annee = None
            
            # Chercher dans les infos
            info_elems = card.find_all(class_=re.compile(r"info|detail|carac", re.I))
            all_text = " ".join(e.get_text() for e in info_elems) if info_elems else card.get_text()
            
            # Km
            km_match = re.search(r'(\d[\d\s]*)\s*km', all_text, re.I)
            if km_match:
                clean = km_match.group(1).replace(" ", "")
                if clean.isdigit():
                    km = int(clean)
            
            # Année
            year_match = re.search(r'\b(20[0-2]\d|19[89]\d)\b', all_text)
            if year_match:
                annee = int(year_match.group(1))
            
            # Localisation
            ville = ""
            dept = ""
            loc_elem = card.find(class_=re.compile(r"loc|ville|city", re.I))
            if loc_elem:
                loc_text = loc_elem.get_text(strip=True)
                # Extraire département
                dept_match = re.search(r'\((\d{2})\)', loc_text)
                if dept_match:
                    dept = dept_match.group(1)
                    ville = loc_text.split("(")[0].strip()
                else:
                    ville = loc_text
            
            # Image
            thumbnail = ""
            img = card.find("img")
            if img:
                thumbnail = img.get("src") or img.get("data-src") or ""
            
            return IndexResult(
                url=url,
                source=Source.PARUVENDU,
                titre=titre or f"{self._fallback_marque} {self._fallback_modele}".strip(),
                prix=prix,
                kilometrage=km,
                annee=annee,
                ville=ville,
                departement=dept,
                published_at=None,
                thumbnail_url=thumbnail,
                source_listing_id=listing_id,
                marque=self._fallback_marque,
                modele=self._fallback_modele,
            )
            
        except Exception as e:
            print(f"⚠️ ParuVendu parse card error: {e}")
            return None
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """Scan une ou plusieurs pages de résultats."""
        max_pages = kwargs.get("max_pages", 1)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        for page in range(1, max_pages + 1):
            url = self.build_search_url(page=page)
            print(f"📡 Scanning ParuVendu page {page}: {url[:80]}...")
            
            status, html = await self._fetch_html(url)
            
            if status == 0:
                print("⏸️ ParuVendu: circuit breaker actif")
                break
            elif status == 403:
                print("❌ ParuVendu: 403 Forbidden")
                break
            elif status == 429:
                print("⚠️ ParuVendu: 429 Too Many Requests")
                await asyncio.sleep(30)
                continue
            elif status != 200:
                print(f"⚠️ ParuVendu: status {status}")
                continue
            
            soup = BeautifulSoup(html, "lxml")
            
            # Sélecteurs pour les cartes d'annonces (plusieurs tentatives)
            cards = (
                soup.select(".ergov3-annonce") or
                soup.select("[class*='annonce']") or
                soup.select(".resultatAnnonce") or
                soup.select("[data-annonce-id]") or
                soup.select("article") or
                soup.select(".liste-annonces li")
            )
            
            print(f"   Found {len(cards)} card elements")
            
            page_count = 0
            for card in cards:
                result = self._parse_listing_card(card, soup)
                if result and result.source_listing_id not in seen_ids:
                    seen_ids.add(result.source_listing_id)
                    results.append(result)
                    page_count += 1
            
            print(f"   Parsed {page_count} new listings (total: {len(results)})")
            
            if page_count < 3:
                break
        
        return results


class ParuVenduDetailScraper:
    """
    Detail scraper pour ParuVendu.
    Note: Le détail est souvent limité sur ParuVendu.
    """
    
    BASE_URL = "https://www.paruvendu.fr"
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._ua_index = 0
        self._rate_limiter = get_rate_limiter()
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _get_headers(self) -> dict[str, str]:
        self._ua_index = (self._ua_index + 1) % len(USER_AGENTS)
        return {
            "User-Agent": USER_AGENTS[self._ua_index],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        """Fetch et parse une page détail"""
        can_proceed = await self._rate_limiter.wait_for_slot("paruvendu")
        if not can_proceed:
            return None
        
        try:
            client = await self._get_client()
            response = await client.get(url, headers=self._get_headers())
            
            if response.status_code != 200:
                print(f"⚠️ ParuVendu detail {response.status_code}: {url[:60]}")
                return None
            
            self._rate_limiter.record_success("paruvendu")
            html = response.text
            soup = BeautifulSoup(html, "lxml")
            
            description = ""
            images_urls: list[str] = []
            seller_type = ""
            
            # Description
            desc_elem = soup.find(class_=re.compile(r"description|texte", re.I)) or \
                       soup.find(id=re.compile(r"description", re.I))
            if desc_elem:
                description = desc_elem.get_text(strip=True)
            
            # Images
            for img in soup.find_all("img", src=True):
                src = img.get("src", "")
                if any(x in src for x in ["annonce", "photo", "image", "cdn"]):
                    if src.startswith("http"):
                        images_urls.append(src)
            
            # Type vendeur
            seller_elem = soup.find(class_=re.compile(r"vendeur|seller|particulier", re.I))
            if seller_elem:
                text = seller_elem.get_text().lower()
                if "particulier" in text:
                    seller_type = "particulier"
                elif "pro" in text:
                    seller_type = "professionnel"
            
            return DetailResult(
                description=description[:2000],
                images_urls=images_urls[:10],
                seller_type=seller_type,
                seller_name="",
                seller_phone="",
                carburant="",
                boite="",
                puissance_ch=None,
                version="",
                motorisation="",
                ct_info="",
            )
            
        except Exception as e:
            print(f"❌ ParuVendu detail error: {e}")
            self._rate_limiter.record_failure("paruvendu")
            return None


def create_paruvendu_scraper(
    config: ParuVenduConfig = None
) -> tuple[ParuVenduIndexScraper, ParuVenduDetailScraper]:
    """Crée une paire (index, detail) scraper pour ParuVendu"""
    return (
        ParuVenduIndexScraper(config),
        ParuVenduDetailScraper()
    )
