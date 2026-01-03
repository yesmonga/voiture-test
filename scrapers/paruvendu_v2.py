"""
ParuVendu Scraper V2 - Production-grade avec HTTP client robuste
URL corrigée pour le nouveau site ParuVendu
"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from bs4 import BeautifulSoup

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.http_client import get_http_client, FetchResult, RobustHttpClient


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
    region: str = ""
    particulier_only: bool = True


class ParuVenduIndexScraper:
    """
    Index scraper pour ParuVendu.
    URL structure mise à jour pour 2024.
    """
    
    BASE_URL = "https://www.paruvendu.fr"
    
    # Codes marques ParuVendu
    MARQUES = {
        "peugeot": "peugeot",
        "renault": "renault",
        "citroen": "citroen",
        "dacia": "dacia",
        "ford": "ford",
        "volkswagen": "volkswagen",
        "opel": "opel",
        "toyota": "toyota",
        "nissan": "nissan",
        "fiat": "fiat",
    }
    
    CARBURANTS = {
        "diesel": "diesel",
        "essence": "essence",
    }
    
    def __init__(self, config: ParuVenduConfig = None):
        self.config = config or ParuVenduConfig()
        self._http_client: Optional[RobustHttpClient] = None
        
        self._fallback_marque: str = ""
        self._fallback_modele: str = ""
    
    def _get_client(self) -> RobustHttpClient:
        if self._http_client is None:
            self._http_client = get_http_client("paruvendu")
        return self._http_client
    
    async def close(self):
        pass
    
    def build_search_url(self, page: int = 1) -> str:
        """Construit l'URL de recherche ParuVendu - format 2024"""
        cfg = self.config
        
        # Nouvelle structure URL ParuVendu
        # https://www.paruvendu.fr/a/voiture-occasion/peugeot/?px1=2000&km1=180000
        
        parts = ["a", "voiture-occasion"]
        
        marque_lower = cfg.marque.lower()
        if marque_lower in self.MARQUES:
            parts.append(self.MARQUES[marque_lower])
        
        base_url = f"{self.BASE_URL}/{'/'.join(parts)}/"
        
        params = []
        
        if cfg.prix_min:
            params.append(f"px0={cfg.prix_min}")
        if cfg.prix_max:
            params.append(f"px1={cfg.prix_max}")
        
        if cfg.km_min:
            params.append(f"km0={cfg.km_min}")
        if cfg.km_max:
            params.append(f"km1={cfg.km_max}")
        
        if cfg.annee_min:
            params.append(f"an0={cfg.annee_min}")
        if cfg.annee_max:
            params.append(f"an1={cfg.annee_max}")
        
        if cfg.carburant and cfg.carburant.lower() in self.CARBURANTS:
            params.append(f"fu={self.CARBURANTS[cfg.carburant.lower()]}")
        
        if cfg.particulier_only:
            params.append("sp=0")  # Particuliers uniquement
        
        # Tri par date
        params.append("tri=date")
        
        if page > 1:
            params.append(f"p={page}")
        
        return f"{base_url}?{'&'.join(params)}" if params else base_url
    
    def _parse_listing_card(self, card) -> Optional[IndexResult]:
        """Parse une carte d'annonce HTML"""
        try:
            # Chercher le lien
            link = card.find("a", href=True)
            if not link:
                return None
            
            href = link.get("href", "")
            if not href:
                return None
            
            # Extraire ID
            listing_id = ""
            # Patterns possibles: /a/123456, /voiture/123456, etc.
            id_match = re.search(r'/a?/?(\d{6,})', href)
            if id_match:
                listing_id = id_match.group(1)
            else:
                # Essayer hash de l'URL
                import hashlib
                listing_id = hashlib.md5(href.encode()).hexdigest()[:12]
            
            url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            
            # Titre
            titre = ""
            titre_elem = card.find(class_=re.compile(r"title|titre", re.I)) or card.find("h2") or card.find("h3")
            if titre_elem:
                titre = titre_elem.get_text(strip=True)
            elif link.get("title"):
                titre = link.get("title")
            else:
                titre = link.get_text(strip=True)[:80]
            
            # Prix
            prix = None
            prix_elem = card.find(class_=re.compile(r"price|prix", re.I))
            if prix_elem:
                prix_text = prix_elem.get_text()
                clean = re.sub(r"[^\d]", "", prix_text)
                if clean and 100 <= int(clean) <= 100000:
                    prix = int(clean)
            
            # Extraire infos du texte
            all_text = card.get_text(" ", strip=True)
            
            # Km
            km = None
            km_match = re.search(r'(\d[\d\s]*)\s*km', all_text, re.I)
            if km_match:
                clean = km_match.group(1).replace(" ", "").replace("\xa0", "")
                if clean.isdigit() and int(clean) < 1000000:
                    km = int(clean)
            
            # Année
            annee = None
            year_match = re.search(r'\b(20[0-2]\d|19[89]\d)\b', all_text)
            if year_match:
                annee = int(year_match.group(1))
            
            # Localisation
            ville = ""
            dept = ""
            loc_match = re.search(r'\((\d{2})\)', all_text)
            if loc_match:
                dept = loc_match.group(1)
            
            # Image
            thumbnail = ""
            img = card.find("img")
            if img:
                thumbnail = img.get("src") or img.get("data-src") or img.get("data-lazy") or ""
            
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
            return None
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """Scan les pages de résultats"""
        max_pages = kwargs.get("max_pages", 1)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        client = self._get_client()
        
        for page in range(1, max_pages + 1):
            url = self.build_search_url(page=page)
            print(f"📡 Scanning ParuVendu page {page}: {url[:80]}...")
            
            response = await client.fetch(url)
            
            if response.status == FetchResult.RATE_LIMITED:
                print("⏸️ ParuVendu: circuit breaker actif")
                break
            elif response.status == FetchResult.BLOCKED:
                print(f"❌ ParuVendu: blocage ({response.status_code})")
                break
            elif response.status == FetchResult.NOT_FOUND:
                print(f"⚠️ ParuVendu: 404 - URL incorrecte")
                # Essayer URL alternative
                alt_url = f"{self.BASE_URL}/auto-moto/voiture/p{page}g0q{self.config.marque}"
                print(f"   Essai URL alternative: {alt_url[:60]}...")
                response = await client.fetch(alt_url)
                if response.status != FetchResult.SUCCESS:
                    break
            elif response.status != FetchResult.SUCCESS:
                print(f"⚠️ ParuVendu: erreur {response.error}")
                continue
            
            html = response.html
            soup = BeautifulSoup(html, "lxml")
            
            # Sélecteurs pour les cartes
            cards = (
                soup.select("article") or
                soup.select("[class*='annonce']") or
                soup.select("[class*='listing']") or
                soup.select("[class*='result']") or
                soup.select("li[class*='ann']")
            )
            
            print(f"   Found {len(cards)} card elements")
            
            page_count = 0
            for card in cards:
                result = self._parse_listing_card(card)
                if result and result.source_listing_id not in seen_ids:
                    seen_ids.add(result.source_listing_id)
                    results.append(result)
                    page_count += 1
            
            print(f"   Parsed {page_count} listings (total: {len(results)})")
            
            if page_count < 3:
                break
        
        return results


class ParuVenduDetailScraper:
    """Detail scraper pour ParuVendu"""
    
    def __init__(self):
        self._http_client: Optional[RobustHttpClient] = None
    
    def _get_client(self) -> RobustHttpClient:
        if self._http_client is None:
            self._http_client = get_http_client("paruvendu")
        return self._http_client
    
    async def close(self):
        pass
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        client = self._get_client()
        response = await client.fetch(url)
        
        if response.status != FetchResult.SUCCESS:
            return None
        
        soup = BeautifulSoup(response.html, "lxml")
        
        description = ""
        desc_elem = soup.find(class_=re.compile(r"description|texte", re.I))
        if desc_elem:
            description = desc_elem.get_text(strip=True)
        
        images_urls = []
        for img in soup.find_all("img", src=True):
            src = img.get("src", "")
            if any(x in src for x in ["annonce", "photo", "image"]):
                images_urls.append(src)
        
        return DetailResult(
            description=description[:2000],
            images_urls=images_urls[:10],
            seller_type="",
            seller_name="",
            seller_phone="",
            carburant="",
            boite="",
            puissance_ch=None,
            version="",
            motorisation="",
            ct_info="",
        )


def create_paruvendu_scraper(config: ParuVenduConfig = None):
    return ParuVenduIndexScraper(config), ParuVenduDetailScraper()
