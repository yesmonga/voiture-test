"""
La Centrale Scraper V2 - Production-grade avec HTTP client robuste
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
    region: str = ""
    particulier_only: bool = True


class LaCentraleIndexScraper:
    """
    Index scraper pour La Centrale.
    Utilise le client HTTP robuste commun.
    """
    
    BASE_URL = "https://www.lacentrale.fr"
    
    MARQUES_SLUG = {
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
        "diesel": "DIESEL",
        "essence": "ESSENCE",
        "hybride": "HYBRID",
        "electrique": "ELECTRIC",
    }
    
    def __init__(self, config: LaCentraleConfig = None):
        self.config = config or LaCentraleConfig()
        self._http_client: Optional[RobustHttpClient] = None
        
        self._fallback_marque: str = ""
        self._fallback_modele: str = ""
    
    def _get_client(self) -> RobustHttpClient:
        if self._http_client is None:
            self._http_client = get_http_client("lacentrale")
        return self._http_client
    
    async def close(self):
        pass  # Client géré globalement
    
    def build_search_url(self, page: int = 1) -> str:
        """Construit l'URL de recherche La Centrale - nouveau format"""
        cfg = self.config
        
        # URL structure: /listing?makesModelsCommercialNames=PEUGEOT:207&...
        params = []
        
        marque_lower = cfg.marque.lower()
        if marque_lower in self.MARQUES_SLUG:
            marque_upper = marque_lower.upper()
            if cfg.modele:
                params.append(f"makesModelsCommercialNames={marque_upper}%3A{cfg.modele.upper()}")
            else:
                params.append(f"makesModelsCommercialNames={marque_upper}")
        
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
        
        if page > 1:
            params.append(f"page={page}")
        
        return f"{self.BASE_URL}/listing?{'&'.join(params)}"
    
    def _extract_json_data(self, html: str) -> Optional[dict]:
        """Extrait __NEXT_DATA__ ou autres JSON embarqués"""
        soup = BeautifulSoup(html, "lxml")
        
        # Méthode 1: __NEXT_DATA__
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                return json.loads(script.string)
            except json.JSONDecodeError:
                pass
        
        # Méthode 2: window.__INITIAL_STATE__
        for script in soup.find_all("script"):
            if script.string and "__INITIAL_STATE__" in script.string:
                match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        pass
        
        return None
    
    def _find_listings_in_json(self, data: Any, depth: int = 0) -> list[dict]:
        """Recherche récursive des listings"""
        if depth > 12:
            return []
        
        listings = []
        
        if isinstance(data, dict):
            for key in ["listings", "ads", "results", "classifieds", "vehicles"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            
            # Check if this is a listing
            has_id = any(k in data for k in ["id", "classifiedId", "adId", "listingId"])
            has_price = any(k in data for k in ["price", "prix", "displayPrice"])
            if has_id and has_price:
                listings.append(data)
            
            for v in data.values():
                listings.extend(self._find_listings_in_json(v, depth + 1))
        
        elif isinstance(data, list):
            for item in data:
                listings.extend(self._find_listings_in_json(item, depth + 1))
        
        return listings
    
    def _parse_listing(self, raw: dict) -> Optional[IndexResult]:
        """Parse un listing brut"""
        try:
            listing_id = str(raw.get("id") or raw.get("classifiedId") or raw.get("adId") or "")
            if not listing_id:
                return None
            
            url = raw.get("url") or raw.get("link") or ""
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"
            if not url:
                url = f"{self.BASE_URL}/auto-occasion-annonce-{listing_id}.html"
            
            # Prix
            prix = None
            price_data = raw.get("price") or raw.get("displayPrice") or {}
            if isinstance(price_data, dict):
                prix = price_data.get("value") or price_data.get("amount")
            elif isinstance(price_data, (int, float)):
                prix = int(price_data)
            elif isinstance(price_data, str):
                clean = re.sub(r"[^\d]", "", price_data)
                if clean:
                    prix = int(clean)
            
            # Véhicule
            vehicle = raw.get("vehicle") or raw.get("vehicleInfo") or raw
            marque = vehicle.get("make") or vehicle.get("brand") or self._fallback_marque or ""
            modele = vehicle.get("model") or self._fallback_modele or ""
            version = vehicle.get("version") or vehicle.get("trim") or ""
            
            titre = raw.get("title") or raw.get("subject") or f"{marque} {modele}".strip()
            
            # Km
            km = None
            km_data = vehicle.get("mileage") or raw.get("mileage")
            if isinstance(km_data, dict):
                km = km_data.get("value")
            elif km_data:
                clean = str(km_data).replace(" ", "").replace("km", "")
                try:
                    km = int(clean)
                except ValueError:
                    pass
            
            # Année
            annee = None
            year_data = vehicle.get("year") or raw.get("year") or vehicle.get("firstRegistrationDate")
            if year_data:
                year_str = str(year_data)
                if "/" in year_str:
                    annee = int(year_str.split("/")[-1])
                elif len(year_str) >= 4:
                    match = re.search(r"(20\d{2}|19\d{2})", year_str)
                    if match:
                        annee = int(match.group(1))
            
            # Localisation
            location = raw.get("location") or raw.get("localization") or {}
            ville = location.get("city") or location.get("cityName") or ""
            code_postal = location.get("zipCode") or location.get("postalCode") or ""
            dept = str(code_postal)[:2] if code_postal else ""
            
            carburant = vehicle.get("energy") or vehicle.get("fuel") or ""
            
            # Image
            images = raw.get("images") or raw.get("photos") or []
            thumbnail = ""
            if images:
                first = images[0] if isinstance(images, list) else images
                if isinstance(first, dict):
                    thumbnail = first.get("url") or first.get("src") or ""
                elif isinstance(first, str):
                    thumbnail = first
            
            return IndexResult(
                url=url,
                source=Source.LACENTRALE,
                titre=titre,
                prix=prix,
                kilometrage=km,
                annee=annee,
                ville=ville,
                departement=dept,
                published_at=None,
                thumbnail_url=thumbnail,
                source_listing_id=listing_id,
                marque=marque,
                modele=modele,
                version=version,
                carburant=carburant,
            )
        except Exception as e:
            print(f"⚠️ LaCentrale parse error: {e}")
            return None
    
    def _parse_html_fallback(self, html: str) -> list[IndexResult]:
        """Fallback parsing HTML si JSON non dispo"""
        results = []
        soup = BeautifulSoup(html, "lxml")
        
        # Chercher les liens d'annonces
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "/auto-occasion-annonce-" in href or "classified" in href.lower():
                id_match = re.search(r'-(\d{6,})\.html', href)
                if id_match:
                    listing_id = id_match.group(1)
                    url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                    
                    # Extraire titre du lien
                    titre = link.get("title") or link.get_text(strip=True) or ""
                    
                    results.append(IndexResult(
                        url=url,
                        source=Source.LACENTRALE,
                        titre=titre[:100],
                        prix=None,
                        kilometrage=None,
                        annee=None,
                        ville="",
                        departement="",
                        published_at=None,
                        thumbnail_url="",
                        source_listing_id=listing_id,
                        marque=self._fallback_marque,
                        modele=self._fallback_modele,
                    ))
        
        # Déduplique
        seen = set()
        unique = []
        for r in results:
            if r.source_listing_id not in seen:
                seen.add(r.source_listing_id)
                unique.append(r)
        
        return unique[:20]
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """Scan les pages de résultats"""
        max_pages = kwargs.get("max_pages", 1)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        client = self._get_client()
        
        for page in range(1, max_pages + 1):
            url = self.build_search_url(page=page)
            print(f"📡 Scanning LaCentrale page {page}: {url[:80]}...")
            
            response = await client.fetch(url)
            
            if response.status == FetchResult.RATE_LIMITED:
                print("⏸️ LaCentrale: circuit breaker actif")
                break
            elif response.status == FetchResult.BLOCKED:
                print(f"❌ LaCentrale: blocage détecté ({response.status_code})")
                break
            elif response.status == FetchResult.NOT_FOUND:
                print(f"⚠️ LaCentrale: 404 Not Found")
                break
            elif response.status != FetchResult.SUCCESS:
                print(f"⚠️ LaCentrale: erreur {response.error}")
                continue
            
            html = response.html
            
            # Essayer JSON
            json_data = self._extract_json_data(html)
            page_results = []
            
            if json_data:
                raw_listings = self._find_listings_in_json(json_data)
                print(f"   Found {len(raw_listings)} listings via JSON")
                
                for raw in raw_listings:
                    result = self._parse_listing(raw)
                    if result and result.source_listing_id not in seen_ids:
                        seen_ids.add(result.source_listing_id)
                        page_results.append(result)
            else:
                print("   JSON not found, using HTML fallback")
                page_results = self._parse_html_fallback(html)
                page_results = [r for r in page_results if r.source_listing_id not in seen_ids]
                for r in page_results:
                    seen_ids.add(r.source_listing_id)
            
            results.extend(page_results)
            print(f"   Parsed {len(page_results)} listings (total: {len(results)})")
            
            if len(page_results) < 5:
                break
        
        return results


class LaCentraleDetailScraper:
    """Detail scraper pour La Centrale"""
    
    def __init__(self):
        self._http_client: Optional[RobustHttpClient] = None
    
    def _get_client(self) -> RobustHttpClient:
        if self._http_client is None:
            self._http_client = get_http_client("lacentrale")
        return self._http_client
    
    async def close(self):
        pass
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        client = self._get_client()
        response = await client.fetch(url)
        
        if response.status != FetchResult.SUCCESS:
            print(f"⚠️ LaCentrale detail error: {response.error}")
            return None
        
        soup = BeautifulSoup(response.html, "lxml")
        
        description = ""
        desc_elem = soup.find(class_=re.compile(r"description", re.I))
        if desc_elem:
            description = desc_elem.get_text(strip=True)
        
        images_urls = []
        for img in soup.find_all("img", src=True):
            src = img.get("src", "")
            if "classified" in src or "annonce" in src:
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


def create_lacentrale_scraper(config: LaCentraleConfig = None):
    return LaCentraleIndexScraper(config), LaCentraleDetailScraper()
