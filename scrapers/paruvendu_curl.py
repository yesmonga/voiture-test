"""
ParuVendu Scraper via curl-cffi - Bypass anti-bot avec TLS fingerprint Chrome
Production-grade
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.rate_limiter import get_rate_limiter


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
    particulier_only: bool = True


class ParuVenduCurlScraper:
    """
    Scraper ParuVendu via curl-cffi.
    Utilise TLS fingerprint Chrome pour bypass anti-bot.
    """
    
    BASE_URL = "https://www.paruvendu.fr"
    
    CARBURANTS = {
        "diesel": "D",
        "essence": "E",
    }
    
    def __init__(self, config: ParuVenduConfig = None):
        self.config = config or ParuVenduConfig()
        self._rate_limiter = get_rate_limiter()
    
    async def close(self):
        pass
    
    def build_search_url(self, page: int = 1) -> str:
        """Construit l'URL de recherche"""
        cfg = self.config
        
        # Base URL avec marque uniquement (modèle ne marche pas dans l'URL)
        parts = ["a", "voiture-occasion"]
        if cfg.marque:
            parts.append(cfg.marque.lower())
        # Note: le modèle est filtré via les résultats, pas l'URL
        
        base = f"{self.BASE_URL}/{'/'.join(parts)}/"
        
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
            params.append(f"ca={self.CARBURANTS[cfg.carburant.lower()]}")
        if cfg.particulier_only:
            params.append("ty=P")
        
        params.append("tri=d")  # Tri par date
        
        if page > 1:
            params.append(f"p={page}")
        
        return f"{base}?{'&'.join(params)}" if params else base
    
    def _fetch_sync(self, url: str) -> Optional[str]:
        """Fetch synchrone avec curl-cffi"""
        try:
            response = curl_requests.get(
                url,
                impersonate="chrome",
                timeout=30,
            )
            if response.status_code == 200:
                return response.text
            else:
                print(f"   ⚠️ ParuVendu status {response.status_code}")
                return None
        except Exception as e:
            print(f"   ❌ ParuVendu fetch error: {e}")
            return None
    
    def _parse_bloc_annonce(self, bloc) -> Optional[IndexResult]:
        """Parse un bloc d'annonce"""
        try:
            # Lien et ID
            link = bloc.find("a", href=True)
            if not link:
                return None
            
            href = link.get("href", "")
            if not href or "/a/" not in href:
                return None
            
            # Extraire ID de l'URL
            id_match = re.search(r'/([A-Z0-9]{10,})', href)
            listing_id = id_match.group(1) if id_match else href.split("/")[-1]
            
            url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            
            # Titre
            titre_elem = bloc.find("h2") or bloc.find("h3")
            titre = titre_elem.get_text(strip=True) if titre_elem else ""
            
            # Prix - chercher le texte avec €
            prix = None
            for elem in bloc.find_all(string=lambda t: t and "€" in t):
                text = elem.strip()
                # Extraire uniquement les chiffres du prix (généralement 4-6 digits)
                clean = re.sub(r"[^\d]", "", text)
                if clean and 500 <= int(clean) <= 100000:
                    prix = int(clean)
                    break
            
            # Infos véhicule depuis le texte
            text = bloc.get_text(" ", strip=True)
            
            # Année - chercher format 4 digits entre 1990-2026
            annee = None
            year_matches = re.findall(r'\b(19[89]\d|20[0-2]\d)\b', text)
            if year_matches:
                annee = int(year_matches[0])
            
            # Kilométrage - format "XXX XXX km" ou "XXXXXXkm"
            km = None
            km_match = re.search(r'(\d{1,3}(?:\s?\d{3})*)\s*km\b', text, re.I)
            if km_match:
                km_str = km_match.group(1).replace(" ", "").replace("\xa0", "")
                if km_str.isdigit() and int(km_str) < 500000:
                    km = int(km_str)
            
            # Localisation - chercher département (XX)
            dept = ""
            dept_match = re.search(r'\((\d{2})\)', text)
            if dept_match:
                dept = dept_match.group(1)
            
            # Image
            thumbnail = ""
            img = bloc.find("img")
            if img:
                thumbnail = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
                if thumbnail.startswith("data:"):
                    thumbnail = ""
            
            return IndexResult(
                url=url,
                source=Source.PARUVENDU,
                titre=titre[:100] if titre else f"{self.config.marque} {self.config.modele}".strip(),
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
        can_proceed = await self._rate_limiter.wait_for_slot("paruvendu")
        if not can_proceed:
            print("⏸️ ParuVendu: circuit breaker actif")
            return []
        
        for page in range(1, max_pages + 1):
            url = self.build_search_url(page)
            print(f"📡 Scanning ParuVendu (curl-cffi) page {page}: {url[:70]}...")
            
            # Fetch via curl-cffi (sync dans async context)
            html = await asyncio.get_event_loop().run_in_executor(
                None, self._fetch_sync, url
            )
            
            if not html:
                self._rate_limiter.record_failure("paruvendu")
                break
            
            soup = BeautifulSoup(html, "lxml")
            blocs = soup.find_all("div", class_="blocAnnonce")
            
            print(f"   Found {len(blocs)} blocAnnonce")
            
            page_count = 0
            for bloc in blocs:
                result = self._parse_bloc_annonce(bloc)
                if result and result.source_listing_id not in seen_ids:
                    seen_ids.add(result.source_listing_id)
                    results.append(result)
                    page_count += 1
            
            print(f"   Parsed {page_count} listings (total: {len(results)})")
            self._rate_limiter.record_success("paruvendu")
            
            if page_count < 3:
                break
            
            # Délai entre pages
            await asyncio.sleep(1.5)
        
        return results


class ParuVenduCurlDetailScraper:
    """Detail scraper via curl-cffi"""
    
    def __init__(self):
        self._rate_limiter = get_rate_limiter()
    
    async def close(self):
        pass
    
    def _fetch_sync(self, url: str) -> Optional[str]:
        try:
            response = curl_requests.get(url, impersonate="chrome", timeout=30)
            return response.text if response.status_code == 200 else None
        except:
            return None
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        can_proceed = await self._rate_limiter.wait_for_slot("paruvendu")
        if not can_proceed:
            return None
        
        html = await asyncio.get_event_loop().run_in_executor(None, self._fetch_sync, url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, "lxml")
        
        # Description
        description = ""
        desc_elem = soup.find(class_=re.compile(r"description|texte", re.I))
        if desc_elem:
            description = desc_elem.get_text(strip=True)[:2000]
        
        # Images
        images = []
        for img in soup.find_all("img", src=True):
            src = img.get("src", "")
            if "paruvendu" in src and not src.startswith("data:"):
                images.append(src)
        
        self._rate_limiter.record_success("paruvendu")
        
        return DetailResult(
            description=description,
            images_urls=images[:10],
            seller_type="",
            seller_name="",
            seller_phone="",
        )


def create_paruvendu_curl_scraper(config: ParuVenduConfig = None):
    return ParuVenduCurlScraper(config), ParuVenduCurlDetailScraper()
