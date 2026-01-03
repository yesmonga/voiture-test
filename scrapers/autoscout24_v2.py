"""
AutoScout24 Scraper V2 - Compatible avec le nouveau pipeline Orchestrator
Extraction via __NEXT_DATA__ pour robustesse maximale
"""

import asyncio
import json
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from config.settings import get_settings

# Rate limiting
_last_request_time: float = 0
_request_lock = asyncio.Lock()

# User agents rotation
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


@dataclass
class AutoScout24Config:
    """Configuration pour les recherches AutoScout24"""
    marque: str = "peugeot"
    modele: str = ""
    prix_min: int = 0
    prix_max: int = 2000
    km_min: int = 0  # Ajout km_min pour flipping (km élevé = prix bas)
    km_max: int = 180000
    annee_min: int = 2006
    annee_max: int = 2014
    carburant: str = "diesel"
    zip_code: str = ""  # Vide = France entière
    radius_km: int = 0  # 0 = pas de filtre géo
    particulier_only: bool = True


class AutoScout24IndexScraper:
    """
    Index scraper pour AutoScout24.
    Extrait les annonces depuis __NEXT_DATA__ pour robustesse.
    """
    
    BASE_URL = "https://www.autoscout24.fr"
    
    MARQUES_IDS = {
        "peugeot": "58",
        "renault": "66",
        "citroen": "19",
        "dacia": "23",
        "ford": "29",
        "volkswagen": "84",
        "opel": "54",
        "toyota": "80",
        "nissan": "52",
        "fiat": "28",
    }
    
    CARBURANTS = {
        "diesel": "D",
        "essence": "B",
        "hybride": "2",
        "electrique": "E",
    }
    
    def __init__(self, config: AutoScout24Config = None):
        self.config = config or AutoScout24Config()
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None
        self._ua_index = 0
        
        # Fallback marque/modele (set by runner from config)
        self._fallback_marque: str = ""
        self._fallback_modele: str = ""
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy init du client HTTP"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client
    
    async def close(self):
        """Ferme le client HTTP"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _get_headers(self) -> dict[str, str]:
        """Headers avec rotation User-Agent"""
        self._ua_index = (self._ua_index + 1) % len(USER_AGENTS)
        return {
            "User-Agent": USER_AGENTS[self._ua_index],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
        }
    
    async def _rate_limit(self):
        """Rate limiting: min 1.5s entre requêtes"""
        global _last_request_time
        async with _request_lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - _last_request_time
            if elapsed < 1.5:
                await asyncio.sleep(1.5 - elapsed)
            _last_request_time = asyncio.get_event_loop().time()
    
    def build_search_url(self, page: int = 1) -> str:
        """Construit l'URL de recherche"""
        cfg = self.config
        
        # Path avec marque
        marque_lower = cfg.marque.lower()
        path_parts = ["lst", marque_lower]
        if cfg.modele:
            path_parts.append(cfg.modele.lower())
        
        # Params
        params = {
            "sort": "age",  # Tri par date (plus récent)
            "desc": "1",
            "cy": "F",  # France
            "atype": "C",  # Voiture
            "ustate": "N,U",  # Neuf et occasion
        }
        
        if cfg.prix_min:
            params["pricefrom"] = cfg.prix_min
        if cfg.prix_max:
            params["priceto"] = cfg.prix_max
        if cfg.km_min:
            params["kmfrom"] = cfg.km_min
        if cfg.km_max:
            params["kmto"] = cfg.km_max
        if cfg.annee_min:
            params["fregfrom"] = cfg.annee_min
        if cfg.annee_max:
            params["fregto"] = cfg.annee_max
        
        if cfg.carburant and cfg.carburant.lower() in self.CARBURANTS:
            params["fuel"] = self.CARBURANTS[cfg.carburant.lower()]
        
        if cfg.particulier_only:
            params["custtype"] = "P"  # Particulier
        
        if cfg.zip_code:
            params["zip"] = cfg.zip_code
            params["zipr"] = cfg.radius_km
        
        if page > 1:
            params["page"] = page
        
        return f"{self.BASE_URL}/{'/'.join(path_parts)}?{urlencode(params)}"
    
    async def _fetch_html(self, url: str) -> tuple[int, str]:
        """Fetch une page avec rate limiting"""
        await self._rate_limit()
        
        client = await self._get_client()
        
        try:
            response = await client.get(url, headers=self._get_headers())
            return response.status_code, response.text
        except Exception as e:
            print(f"⚠️ Fetch error: {e}")
            return 0, ""
    
    def _extract_next_data(self, html: str) -> Optional[dict]:
        """Extrait le JSON de __NEXT_DATA__"""
        soup = BeautifulSoup(html, "lxml")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        
        if not script or not script.string:
            return None
        
        try:
            return json.loads(script.string)
        except json.JSONDecodeError:
            return None
    
    def _find_listings_recursive(
        self, 
        data: Any, 
        depth: int = 0,
        max_depth: int = 15
    ) -> list[dict]:
        """
        Recherche récursive des objets qui ressemblent à des annonces.
        Cherche des dicts avec: id + (price ou prix) + (title ou make/model)
        """
        if depth > max_depth:
            return []
        
        listings = []
        
        if isinstance(data, dict):
            # Vérifier si c'est une annonce
            has_id = any(k in data for k in ["id", "listingId", "vehicleId", "guid"])
            has_price = any(k in data for k in ["price", "grossPrice", "rawPrice"])
            has_vehicle = any(k in data for k in ["make", "model", "title", "vehicle", "makeModelDescription"])
            
            if has_id and (has_price or has_vehicle):
                listings.append(data)
            
            # Check for listings array
            if "listings" in data and isinstance(data["listings"], list):
                for item in data["listings"]:
                    if isinstance(item, dict):
                        listings.append(item)
            
            # Recurse
            for v in data.values():
                listings.extend(self._find_listings_recursive(v, depth + 1, max_depth))
        
        elif isinstance(data, list):
            for item in data:
                listings.extend(self._find_listings_recursive(item, depth + 1, max_depth))
        
        return listings
    
    def _parse_listing(self, raw: dict) -> Optional[IndexResult]:
        """Parse un listing brut en IndexResult"""
        try:
            # ID - plusieurs possibilités
            listing_id = (
                raw.get("id") or 
                raw.get("listingId") or 
                raw.get("identifier") or
                raw.get("vehicleId") or
                ""
            )
            if not listing_id:
                return None
            
            listing_id = str(listing_id)
            
            # URL
            url = raw.get("url") or raw.get("detailUrl") or raw.get("seoUrl") or ""
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"
            if not url:
                url = f"{self.BASE_URL}/annonce/{listing_id}"
            
            # Prix - format AutoScout24: {"priceFormatted": "€ 1 800"}
            price_data = raw.get("price") or {}
            prix = None
            if isinstance(price_data, dict):
                price_str = price_data.get("priceFormatted") or price_data.get("value") or ""
                if price_str:
                    # Nettoyer: "€ 1 800" -> 1800
                    clean = str(price_str).replace("€", "").replace("\u202f", "").replace(" ", "").replace(",", ".")
                    try:
                        prix = int(float(clean))
                    except ValueError:
                        pass
            elif price_data:
                try:
                    prix = int(float(str(price_data)))
                except ValueError:
                    pass
            
            # Véhicule
            vehicle = raw.get("vehicle") or {}
            marque = vehicle.get("make") or self._fallback_marque or ""
            modele = vehicle.get("model") or self._fallback_modele or ""
            
            # Titre
            titre = (
                raw.get("title") or
                vehicle.get("modelVersionInput") or
                f"{marque} {modele}".strip()
            )
            
            # Kilométrage - format: "268 000 km" dans mileageInKm
            km = None
            km_str = vehicle.get("mileageInKm") or vehicle.get("mileage") or ""
            if km_str:
                clean = str(km_str).replace("\u202f", "").replace(" ", "").replace("km", "")
                try:
                    km = int(clean)
                except ValueError:
                    pass
            
            # Année - plusieurs sources possibles
            annee = None
            
            # 1. Chercher dans firstRegistration (format: "2012" ou "05/2012")
            first_reg = vehicle.get("firstRegistration") or raw.get("firstRegistration") or ""
            if first_reg:
                first_reg_str = str(first_reg)
                if "/" in first_reg_str:
                    try:
                        annee = int(first_reg_str.split("/")[-1])
                    except ValueError:
                        pass
                elif first_reg_str.isdigit() and len(first_reg_str) == 4:
                    annee = int(first_reg_str)
            
            # 2. Fallback: chercher dans vehicleDetails (iconName=calendar)
            if annee is None:
                vehicle_details = raw.get("vehicleDetails") or []
                for detail in vehicle_details:
                    if isinstance(detail, dict) and detail.get("iconName") == "calendar":
                        date_str = detail.get("data", "")  # "05/2006"
                        if "/" in date_str:
                            try:
                                annee = int(date_str.split("/")[-1])
                            except ValueError:
                                pass
                        break
            
            # Location
            location = raw.get("location") or {}
            ville = location.get("city") or ""
            code_postal = location.get("zip") or ""
            
            # Département depuis code postal
            dept = ""
            if code_postal and len(str(code_postal)) >= 2:
                dept = str(code_postal)[:2]
                if dept == "20":  # Corse
                    dept = "2A" if code_postal.startswith("201") else "2B"
            
            # Image
            images = raw.get("images") or []
            thumbnail = ""
            if images and isinstance(images, list):
                first_img = images[0]
                if isinstance(first_img, dict):
                    thumbnail = first_img.get("url") or first_img.get("src") or ""
                elif isinstance(first_img, str):
                    thumbnail = first_img
            
            # Date publication (pas dispo dans __NEXT_DATA__)
            published_at = None
            
            # Carburant
            carburant = vehicle.get("fuel") or ""
            
            return IndexResult(
                url=url,
                source=Source.AUTOSCOUT24,
                titre=titre,
                prix=prix,
                kilometrage=km,
                annee=annee,
                ville=ville,
                departement=dept,
                published_at=published_at,
                thumbnail_url=thumbnail,
                source_listing_id=listing_id,
                marque=marque,
                modele=modele,
                version=titre,  # Le titre contient souvent la version complète
                carburant=carburant,
            )
            
        except Exception as e:
            print(f"⚠️ Parse listing error: {e}")
            return None
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """
        Scan une ou plusieurs pages de résultats.
        Retourne une liste d'IndexResult.
        """
        max_pages = kwargs.get("max_pages", 1)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        for page in range(1, max_pages + 1):
            url = self.build_search_url(page=page)
            print(f"📡 Scanning AutoScout24 page {page}: {url[:80]}...")
            
            status, html = await self._fetch_html(url)
            
            if status == 403:
                print("❌ 403 Forbidden - possible blocage")
                break
            elif status == 429:
                print("⚠️ 429 Too Many Requests - pause 30s")
                await asyncio.sleep(30)
                continue
            elif status != 200:
                print(f"⚠️ Status {status}")
                continue
            
            if not html:
                continue
            
            # Extraire __NEXT_DATA__
            next_data = self._extract_next_data(html)
            
            if not next_data:
                print("⚠️ __NEXT_DATA__ not found, trying HTML fallback")
                # TODO: HTML fallback si nécessaire
                continue
            
            # Trouver les listings
            raw_listings = self._find_listings_recursive(next_data)
            print(f"   Found {len(raw_listings)} raw listings")
            
            # Dédupliquer et parser
            page_count = 0
            for raw in raw_listings:
                listing_id = str(raw.get("id") or raw.get("listingId") or "")
                if listing_id in seen_ids:
                    continue
                seen_ids.add(listing_id)
                
                result = self._parse_listing(raw)
                if result:
                    results.append(result)
                    page_count += 1
            
            print(f"   Parsed {page_count} new listings (total: {len(results)})")
            
            # Si peu de résultats, pas la peine de continuer
            if page_count < 5:
                break
        
        return results


class AutoScout24DetailScraper:
    """
    Detail scraper pour AutoScout24.
    Enrichit les annonces avec description, options, etc.
    """
    
    BASE_URL = "https://www.autoscout24.fr"
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._ua_index = 0
    
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
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }
    
    async def _rate_limit(self):
        global _last_request_time
        async with _request_lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - _last_request_time
            if elapsed < 2.0:  # Plus conservateur pour détail
                await asyncio.sleep(2.0 - elapsed)
            _last_request_time = asyncio.get_event_loop().time()
    
    async def fetch_detail(self, url: str) -> Optional[DetailResult]:
        """Fetch et parse une page détail"""
        await self._rate_limit()
        
        try:
            client = await self._get_client()
            response = await client.get(url, headers=self._get_headers())
            
            if response.status_code != 200:
                print(f"⚠️ Detail fetch {response.status_code}: {url[:60]}")
                return None
            
            html = response.text
            
            # Extraire __NEXT_DATA__
            soup = BeautifulSoup(html, "lxml")
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            
            description = ""
            images_urls: list[str] = []
            seller_type = ""
            carburant = ""
            boite = ""
            puissance_ch = None
            version = ""
            motorisation = ""
            ct_info = ""
            
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    
                    # Chercher les données de l'annonce
                    def find_detail(d, depth=0):
                        if depth > 15:
                            return None
                        if isinstance(d, dict):
                            if "description" in d and isinstance(d.get("description"), str):
                                return d
                            for v in d.values():
                                r = find_detail(v, depth + 1)
                                if r:
                                    return r
                        elif isinstance(d, list):
                            for item in d:
                                r = find_detail(item, depth + 1)
                                if r:
                                    return r
                        return None
                    
                    detail = find_detail(data)
                    
                    if detail:
                        description = detail.get("description") or ""
                        
                        # Images
                        imgs = detail.get("images") or detail.get("media", {}).get("images") or []
                        for img in imgs[:10]:
                            if isinstance(img, dict):
                                images_urls.append(img.get("url") or img.get("src") or "")
                            elif isinstance(img, str):
                                images_urls.append(img)
                        
                        # Seller
                        seller = detail.get("seller") or {}
                        seller_type = seller.get("type") or ""
                        if seller_type.upper() == "P" or "particulier" in seller_type.lower():
                            seller_type = "particulier"
                        else:
                            seller_type = "professionnel"
                        
                        # Vehicle specs
                        vehicle = detail.get("vehicle") or detail
                        carburant = vehicle.get("fuelType") or vehicle.get("fuel") or ""
                        boite = vehicle.get("transmission") or vehicle.get("gearbox") or ""
                        
                        power = vehicle.get("power") or {}
                        if isinstance(power, dict):
                            puissance_ch = power.get("hp") or power.get("ch")
                        
                        version = vehicle.get("version") or ""
                        motorisation = vehicle.get("engine") or ""
                
                except json.JSONDecodeError:
                    pass
            
            # Fallback: extraire description du HTML
            if not description:
                desc_elem = soup.find("[class*='Description']") or soup.find("[data-testid='description']")
                if desc_elem:
                    description = desc_elem.get_text(strip=True)
            
            # Chercher infos CT dans description
            desc_lower = description.lower()
            if any(x in desc_lower for x in ["ct ok", "ct vierge", "controle technique ok"]):
                ct_info = "CT OK"
            elif any(x in desc_lower for x in ["ct refusé", "contre visite", "sans ct"]):
                ct_info = "CT à faire"
            
            return DetailResult(
                description=description,
                images_urls=[u for u in images_urls if u],
                seller_type=seller_type,
                seller_name="",
                seller_phone="",
                carburant=carburant,
                boite=boite,
                puissance_ch=puissance_ch,
                version=version,
                motorisation=motorisation,
                ct_info=ct_info,
            )
            
        except Exception as e:
            print(f"❌ Detail error: {e}")
            return None


# Factory functions
def create_autoscout24_scraper(
    config: AutoScout24Config = None
) -> tuple[AutoScout24IndexScraper, AutoScout24DetailScraper]:
    """Crée une paire (index, detail) scraper pour AutoScout24"""
    return (
        AutoScout24IndexScraper(config),
        AutoScout24DetailScraper()
    )
