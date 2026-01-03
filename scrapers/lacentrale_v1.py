"""
La Centrale Scraper V1 - Production-grade
Compatible avec le pipeline Orchestrator (IndexScraper/DetailScraper)
Extraction via données JSON embarquées (__NEXT_DATA__ ou API interne)
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


# User agents rotation
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
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
    region: str = ""  # Vide = France entière
    particulier_only: bool = True


class LaCentraleIndexScraper:
    """
    Index scraper pour La Centrale.
    Extrait les annonces depuis les données JSON embarquées.
    """
    
    BASE_URL = "https://www.lacentrale.fr"
    
    # Mapping marques vers slug URL
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
        self._client: Optional[httpx.AsyncClient] = None
        self._ua_index = 0
        self._rate_limiter = get_rate_limiter()
        
        # Fallback marque/modele
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
    
    def build_search_url(self, page: int = 1) -> str:
        """Construit l'URL de recherche La Centrale"""
        cfg = self.config
        
        # Nouvelle structure URL La Centrale
        params = []
        
        # Marque
        marque_lower = cfg.marque.lower()
        if marque_lower in self.MARQUES_SLUG:
            params.append(f"makesModelsCommercialNames={marque_lower.upper()}")
        
        # Modèle
        if cfg.modele:
            params.append(f"makesModelsCommercialNames={marque_lower.upper()}%3A{cfg.modele.upper()}")
        
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
        
        # Particulier uniquement
        if cfg.particulier_only:
            params.append("customerType=part")
        
        # Tri par date décroissante
        params.append("sortBy=firstOnlineDateDesc")
        
        # Pagination
        if page > 1:
            params.append(f"page={page}")
        
        return f"{self.BASE_URL}/listing?{'&'.join(params)}"
    
    async def _fetch_html(self, url: str) -> tuple[int, str]:
        """Fetch une page avec rate limiting"""
        # Vérifier le circuit breaker
        can_proceed = await self._rate_limiter.wait_for_slot("lacentrale")
        if not can_proceed:
            return 0, ""
        
        client = await self._get_client()
        
        try:
            response = await client.get(url, headers=self._get_headers())
            
            if response.status_code == 200:
                self._rate_limiter.record_success("lacentrale")
            elif response.status_code in (403, 429, 503):
                self._rate_limiter.record_failure("lacentrale", is_block=True)
            else:
                self._rate_limiter.record_failure("lacentrale")
            
            return response.status_code, response.text
            
        except Exception as e:
            print(f"⚠️ LaCentrale fetch error: {e}")
            self._rate_limiter.record_failure("lacentrale")
            return 0, ""
    
    def _extract_json_data(self, html: str) -> Optional[dict]:
        """Extrait les données JSON de la page (plusieurs méthodes)"""
        soup = BeautifulSoup(html, "lxml")
        
        # Méthode 1: __NEXT_DATA__ (Next.js)
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                return json.loads(script.string)
            except json.JSONDecodeError:
                pass
        
        # Méthode 2: window.__INITIAL_STATE__
        for script in soup.find_all("script"):
            if script.string and "window.__INITIAL_STATE__" in script.string:
                match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        pass
        
        # Méthode 3: data-testid="searchResults" avec JSON
        results_div = soup.find(attrs={"data-testid": "searchResults"})
        if results_div and results_div.get("data-results"):
            try:
                return json.loads(results_div["data-results"])
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _find_listings_in_json(self, data: Any, depth: int = 0, max_depth: int = 15) -> list[dict]:
        """Recherche récursive des listings dans le JSON"""
        if depth > max_depth:
            return []
        
        listings = []
        
        if isinstance(data, dict):
            # Chercher des clés qui ressemblent à des listings
            if "listings" in data and isinstance(data["listings"], list):
                return data["listings"]
            
            if "ads" in data and isinstance(data["ads"], list):
                return data["ads"]
            
            if "results" in data and isinstance(data["results"], list):
                return data["results"]
            
            # Vérifier si c'est un listing individuel
            has_id = any(k in data for k in ["id", "classifiedId", "adId"])
            has_price = any(k in data for k in ["price", "prix", "priceBrut"])
            if has_id and has_price:
                listings.append(data)
            
            # Recurse
            for v in data.values():
                listings.extend(self._find_listings_in_json(v, depth + 1, max_depth))
        
        elif isinstance(data, list):
            for item in data:
                listings.extend(self._find_listings_in_json(item, depth + 1, max_depth))
        
        return listings
    
    def _parse_listing(self, raw: dict) -> Optional[IndexResult]:
        """Parse un listing brut en IndexResult"""
        try:
            # ID
            listing_id = str(
                raw.get("id") or 
                raw.get("classifiedId") or 
                raw.get("adId") or 
                ""
            )
            if not listing_id:
                return None
            
            # URL
            url = raw.get("url") or raw.get("link") or ""
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"
            if not url:
                url = f"{self.BASE_URL}/auto-occasion-annonce-{listing_id}.html"
            
            # Prix
            prix = None
            price_data = raw.get("price") or raw.get("priceBrut") or {}
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
            
            # Titre
            titre = raw.get("title") or raw.get("subject") or f"{marque} {modele}".strip()
            
            # Kilométrage
            km = None
            km_data = vehicle.get("mileage") or raw.get("mileage") or raw.get("km")
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
                elif len(year_str) == 4 and year_str.isdigit():
                    annee = int(year_str)
            
            # Localisation
            location = raw.get("location") or raw.get("localization") or {}
            ville = location.get("city") or location.get("cityName") or ""
            code_postal = location.get("zipCode") or location.get("postalCode") or ""
            dept = ""
            if code_postal and len(str(code_postal)) >= 2:
                dept = str(code_postal)[:2]
            
            # Carburant
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
                published_at=None,  # Pas toujours dispo
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
        """Fallback: parsing HTML si JSON non disponible"""
        results = []
        soup = BeautifulSoup(html, "lxml")
        
        # Chercher les cartes d'annonces
        cards = soup.select("[data-testid='classified-card']") or \
                soup.select(".searchCard") or \
                soup.select("[class*='classified']")
        
        for card in cards:
            try:
                # ID depuis le lien
                link = card.find("a", href=True)
                if not link:
                    continue
                
                href = link.get("href", "")
                listing_id = ""
                
                # Extraire ID de l'URL
                id_match = re.search(r'-(\d+)\.html', href)
                if id_match:
                    listing_id = id_match.group(1)
                else:
                    id_match = re.search(r'/(\d+)$', href)
                    if id_match:
                        listing_id = id_match.group(1)
                
                if not listing_id:
                    continue
                
                url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                
                # Titre
                titre_elem = card.find(class_=re.compile(r"title", re.I)) or card.find("h2") or card.find("h3")
                titre = titre_elem.get_text(strip=True) if titre_elem else ""
                
                # Prix
                prix = None
                prix_elem = card.find(class_=re.compile(r"price", re.I))
                if prix_elem:
                    prix_text = prix_elem.get_text()
                    clean = re.sub(r"[^\d]", "", prix_text)
                    if clean and len(clean) <= 6:
                        prix = int(clean)
                
                # Image
                img = card.find("img")
                thumbnail = img.get("src", "") if img else ""
                
                results.append(IndexResult(
                    url=url,
                    source=Source.LACENTRALE,
                    titre=titre,
                    prix=prix,
                    kilometrage=None,
                    annee=None,
                    ville="",
                    departement="",
                    published_at=None,
                    thumbnail_url=thumbnail,
                    source_listing_id=listing_id,
                    marque=self._fallback_marque,
                    modele=self._fallback_modele,
                ))
                
            except Exception:
                continue
        
        return results
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """
        Scan une ou plusieurs pages de résultats.
        """
        max_pages = kwargs.get("max_pages", 1)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        for page in range(1, max_pages + 1):
            url = self.build_search_url(page=page)
            print(f"📡 Scanning LaCentrale page {page}: {url[:80]}...")
            
            status, html = await self._fetch_html(url)
            
            if status == 0:
                print("⏸️ LaCentrale: circuit breaker actif")
                break
            elif status == 403:
                print("❌ LaCentrale: 403 Forbidden - blocage détecté")
                break
            elif status == 429:
                print("⚠️ LaCentrale: 429 Too Many Requests")
                await asyncio.sleep(30)
                continue
            elif status != 200:
                print(f"⚠️ LaCentrale: status {status}")
                continue
            
            # Essayer extraction JSON
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
                # Fallback HTML
                print("   JSON not found, using HTML fallback")
                page_results = self._parse_html_fallback(html)
                page_results = [r for r in page_results if r.source_listing_id not in seen_ids]
                for r in page_results:
                    seen_ids.add(r.source_listing_id)
            
            results.extend(page_results)
            print(f"   Parsed {len(page_results)} new listings (total: {len(results)})")
            
            if len(page_results) < 5:
                break
        
        return results


class LaCentraleDetailScraper:
    """
    Detail scraper pour La Centrale.
    Enrichit les annonces avec description, options, etc.
    """
    
    BASE_URL = "https://www.lacentrale.fr"
    
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
        can_proceed = await self._rate_limiter.wait_for_slot("lacentrale")
        if not can_proceed:
            return None
        
        try:
            client = await self._get_client()
            response = await client.get(url, headers=self._get_headers())
            
            if response.status_code != 200:
                print(f"⚠️ LaCentrale detail {response.status_code}: {url[:60]}")
                return None
            
            self._rate_limiter.record_success("lacentrale")
            html = response.text
            soup = BeautifulSoup(html, "lxml")
            
            description = ""
            images_urls: list[str] = []
            seller_type = ""
            carburant = ""
            boite = ""
            puissance_ch = None
            version = ""
            
            # Description
            desc_elem = soup.find(class_=re.compile(r"description", re.I)) or \
                       soup.find(attrs={"data-testid": "description"})
            if desc_elem:
                description = desc_elem.get_text(strip=True)
            
            # Images
            for img in soup.find_all("img", src=True):
                src = img.get("src", "")
                if "classified" in src or "annonce" in src:
                    images_urls.append(src)
            
            # Vendeur
            seller_elem = soup.find(class_=re.compile(r"seller", re.I))
            if seller_elem:
                text = seller_elem.get_text().lower()
                if "particulier" in text:
                    seller_type = "particulier"
                elif "pro" in text or "garage" in text:
                    seller_type = "professionnel"
            
            return DetailResult(
                description=description[:2000],
                images_urls=images_urls[:10],
                seller_type=seller_type,
                seller_name="",
                seller_phone="",
                carburant=carburant,
                boite=boite,
                puissance_ch=puissance_ch,
                version=version,
                motorisation="",
                ct_info="",
            )
            
        except Exception as e:
            print(f"❌ LaCentrale detail error: {e}")
            self._rate_limiter.record_failure("lacentrale")
            return None


def create_lacentrale_scraper(
    config: LaCentraleConfig = None
) -> tuple[LaCentraleIndexScraper, LaCentraleDetailScraper]:
    """Crée une paire (index, detail) scraper pour LaCentrale"""
    return (
        LaCentraleIndexScraper(config),
        LaCentraleDetailScraper()
    )
