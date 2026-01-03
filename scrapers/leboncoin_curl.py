"""
LeBoncoin Scraper via curl-cffi - Bypass DataDome avec TLS fingerprint Chrome
Extraction via __NEXT_DATA__ JSON embarqué
Production-grade
"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

from models.enums import Source
from services.orchestrator import IndexResult, DetailResult
from scrapers.rate_limiter import get_rate_limiter


# Proxies résidentiels FR pour bypass DataDome
RESIDENTIAL_PROXIES = [
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-f994hiwl-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-q2r6263u-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-1n4t8nkg-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-jp6c4ji7-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-xkcvd8ij-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-zmc3hkqd-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-r76z9e9l-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-kx0zahrb-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-5cgx9vhl-duration-60@resi.thexyzstore.com:8000",
    "http://aigrinchxyz:8jqb7dml-country-FR-hardsession-o87lqgdd-duration-60@resi.thexyzstore.com:8000",
]


@dataclass
class LeboncoinConfig:
    """Configuration pour les recherches LeBoncoin"""
    marque: str = "peugeot"
    modele: str = "207"
    prix_min: int = 0
    prix_max: int = 2000
    km_min: int = 0
    km_max: int = 180000
    annee_min: int = 2006
    annee_max: int = 2014
    carburant: str = "diesel"
    particulier_only: bool = True


class LeboncoinCurlScraper:
    """
    Scraper LeBoncoin via curl-cffi.
    Utilise TLS fingerprint Chrome pour bypass DataDome.
    Extraction des données via __NEXT_DATA__ JSON.
    """
    
    BASE_URL = "https://www.leboncoin.fr"
    
    # Mapping carburants LeBoncoin
    CARBURANTS = {
        "diesel": "2",
        "essence": "1",
        "electrique": "3",
        "hybride": "4",
    }
    
    # Mapping marques vers u_car_brand
    MARQUES = {
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
    
    def __init__(self, config: LeboncoinConfig = None, use_proxy: bool = True):
        self.config = config or LeboncoinConfig()
        self._rate_limiter = get_rate_limiter()
        self._use_proxy = use_proxy
        self._proxy_index = 0
    
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
        """Construit l'URL de recherche LeBoncoin"""
        cfg = self.config
        
        params = ["category=2"]  # Voitures
        
        # Marque
        marque_upper = self.MARQUES.get(cfg.marque.lower(), cfg.marque.upper())
        params.append(f"u_car_brand={marque_upper}")
        
        # Modèle
        if cfg.modele:
            model_code = f"{marque_upper}_{cfg.modele.upper()}"
            params.append(f"u_car_model={model_code}")
        
        # Prix
        if cfg.prix_min:
            params.append(f"price_min={cfg.prix_min}")
        if cfg.prix_max:
            params.append(f"price_max={cfg.prix_max}")
        
        # Kilométrage
        if cfg.km_min:
            params.append(f"mileage_min={cfg.km_min}")
        if cfg.km_max:
            params.append(f"mileage_max={cfg.km_max}")
        
        # Année
        if cfg.annee_min:
            params.append(f"regdate_min={cfg.annee_min}")
        if cfg.annee_max:
            params.append(f"regdate_max={cfg.annee_max}")
        
        # Carburant
        if cfg.carburant and cfg.carburant.lower() in self.CARBURANTS:
            params.append(f"fuel={self.CARBURANTS[cfg.carburant.lower()]}")
        
        # Vendeur particulier
        if cfg.particulier_only:
            params.append("owner_type=private")
        
        # Tri par date
        params.append("sort=time")
        params.append("order=desc")
        
        # Pagination
        if page > 1:
            params.append(f"page={page}")
        
        return f"{self.BASE_URL}/recherche?{'&'.join(params)}"
    
    def _fetch_sync(self, url: str) -> Optional[str]:
        """Fetch synchrone avec curl-cffi + proxy résidentiel"""
        proxy = self._get_next_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        try:
            response = curl_requests.get(
                url,
                impersonate="chrome",
                proxies=proxies,
                timeout=30,
            )
            if response.status_code == 200:
                return response.text
            else:
                print(f"   ⚠️ LeBoncoin status {response.status_code}")
                return None
        except Exception as e:
            print(f"   ❌ LeBoncoin fetch error: {e}")
            return None
    
    def _extract_next_data(self, html: str) -> Optional[dict]:
        """Extrait les données JSON de __NEXT_DATA__"""
        soup = BeautifulSoup(html, "lxml")
        script = soup.find("script", id="__NEXT_DATA__")
        
        if script and script.string:
            try:
                return json.loads(script.string)
            except json.JSONDecodeError:
                pass
        return None
    
    def _get_attribute(self, attrs: list, key: str) -> Optional[str]:
        """Extrait un attribut de la liste d'attributs LeBoncoin"""
        for attr in attrs:
            if attr.get("key") == key:
                return attr.get("value")
        return None
    
    def _parse_ad(self, ad: dict) -> Optional[IndexResult]:
        """Parse une annonce LeBoncoin"""
        try:
            listing_id = str(ad.get("list_id", ""))
            if not listing_id:
                return None
            
            url = ad.get("url", "")
            if not url:
                url = f"{self.BASE_URL}/ad/voitures/{listing_id}"
            
            titre = ad.get("subject", "")
            
            # Prix
            prix = None
            price_data = ad.get("price", [])
            if price_data and isinstance(price_data, list):
                prix = price_data[0]
            elif isinstance(price_data, (int, float)):
                prix = int(price_data)
            
            # Attributs
            attrs = ad.get("attributes", [])
            
            # Kilométrage
            km = None
            mileage = self._get_attribute(attrs, "mileage")
            if mileage:
                try:
                    km = int(mileage)
                except ValueError:
                    pass
            
            # Année
            annee = None
            regdate = self._get_attribute(attrs, "regdate")
            if regdate:
                try:
                    annee = int(regdate)
                except ValueError:
                    pass
            
            # Marque/Modèle
            marque = self._get_attribute(attrs, "brand") or self.config.marque.capitalize()
            modele = self._get_attribute(attrs, "model") or self.config.modele
            
            # Localisation
            location = ad.get("location", {})
            ville = location.get("city", "")
            dept = location.get("department_id", "")
            if dept:
                dept = str(dept)
            
            # Images
            images = ad.get("images", {})
            thumbnail = ""
            if images:
                urls = images.get("urls", [])
                if urls:
                    thumbnail = urls[0] if isinstance(urls[0], str) else ""
                elif images.get("thumb_url"):
                    thumbnail = images["thumb_url"]
            
            # Vendeur
            owner = ad.get("owner", {})
            seller_type = owner.get("type", "")
            
            return IndexResult(
                url=url,
                source=Source.LEBONCOIN,
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
            )
        except Exception as e:
            return None
    
    async def scan_index(self, **kwargs) -> list[IndexResult]:
        """Scan les pages de résultats"""
        max_pages = kwargs.get("max_pages", 1)
        results: list[IndexResult] = []
        seen_ids: set[str] = set()
        
        # Rate limiting
        can_proceed = await self._rate_limiter.wait_for_slot("leboncoin")
        if not can_proceed:
            print("⏸️ LeBoncoin: circuit breaker actif")
            return []
        
        for page in range(1, max_pages + 1):
            url = self.build_search_url(page)
            print(f"📡 Scanning LeBoncoin (curl-cffi) page {page}: {url[:70]}...")
            
            # Fetch
            html = await asyncio.get_event_loop().run_in_executor(
                None, self._fetch_sync, url
            )
            
            if not html:
                self._rate_limiter.record_failure("leboncoin")
                break
            
            # Extraire __NEXT_DATA__
            data = self._extract_next_data(html)
            if not data:
                print("   ⚠️ __NEXT_DATA__ not found")
                self._rate_limiter.record_failure("leboncoin")
                break
            
            # Naviguer vers les annonces
            try:
                ads = data["props"]["pageProps"]["searchData"]["ads"]
            except KeyError:
                print("   ⚠️ ads not found in JSON")
                self._rate_limiter.record_failure("leboncoin")
                break
            
            print(f"   Found {len(ads)} ads in JSON")
            
            page_count = 0
            for ad in ads:
                result = self._parse_ad(ad)
                if result and result.source_listing_id not in seen_ids:
                    seen_ids.add(result.source_listing_id)
                    results.append(result)
                    page_count += 1
            
            print(f"   Parsed {page_count} listings (total: {len(results)})")
            self._rate_limiter.record_success("leboncoin")
            
            if page_count < 5:
                break
            
            # Délai entre pages
            await asyncio.sleep(2.0)
        
        return results


class LeboncoinCurlDetailScraper:
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
        can_proceed = await self._rate_limiter.wait_for_slot("leboncoin")
        if not can_proceed:
            return None
        
        html = await asyncio.get_event_loop().run_in_executor(None, self._fetch_sync, url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, "lxml")
        
        # Extraire __NEXT_DATA__ pour le détail
        script = soup.find("script", id="__NEXT_DATA__")
        if script:
            try:
                data = json.loads(script.string)
                ad = data.get("props", {}).get("pageProps", {}).get("ad", {})
                
                description = ad.get("body", "")
                
                images = []
                images_data = ad.get("images", {}).get("urls", [])
                images = images_data[:10] if images_data else []
                
                owner = ad.get("owner", {})
                seller_type = owner.get("type", "")
                seller_name = owner.get("name", "")
                
                self._rate_limiter.record_success("leboncoin")
                
                return DetailResult(
                    description=description[:2000],
                    images_urls=images,
                    seller_type=seller_type,
                    seller_name=seller_name,
                    seller_phone="",
                )
            except:
                pass
        
        self._rate_limiter.record_failure("leboncoin")
        return None


def create_leboncoin_curl_scraper(config: LeboncoinConfig = None):
    return LeboncoinCurlScraper(config), LeboncoinCurlDetailScraper()
