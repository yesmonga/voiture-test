"""
AutoScout24 Scraper - Scraper pour autoscout24.fr
"""

import re
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode

from .base_scraper import BaseScraper
from models.annonce import Annonce
from utils.logger import get_logger, log_error

logger = get_logger(__name__)


class AutoScout24Scraper(BaseScraper):
    """Scraper pour AutoScout24.fr"""
    
    name = "autoscout24"
    base_url = "https://www.autoscout24.fr"
    
    MARQUES = {
        "peugeot": "58",
        "renault": "66",
        "dacia": "23",
        "ford": "29",
        "toyota": "80",
    }
    
    CARBURANTS = {
        "diesel": "D",
        "essence": "B",
    }
    
    async def build_search_url(self, vehicule_config: Dict, page: int = 1) -> str:
        """Construit l'URL de recherche AutoScout24"""
        marque = vehicule_config.get("marque", "").lower()
        
        path_parts = ["lst"]
        if marque in self.MARQUES:
            path_parts.append(marque)
        
        params = {
            "sort": "age",
            "desc": "1",
            "cy": "F",
            "atype": "C",
            "ustate": "N,U",
        }
        
        if vehicule_config.get("prix_min"):
            params["pricefrom"] = vehicule_config["prix_min"]
        if vehicule_config.get("prix_max"):
            params["priceto"] = vehicule_config["prix_max"]
        if vehicule_config.get("km_max"):
            params["kmto"] = vehicule_config["km_max"]
        if vehicule_config.get("annee_min"):
            params["fregfrom"] = vehicule_config["annee_min"]
        if vehicule_config.get("annee_max"):
            params["fregto"] = vehicule_config["annee_max"]
        
        carburant = vehicule_config.get("carburant")
        if carburant and carburant.lower() in self.CARBURANTS:
            params["fuel"] = self.CARBURANTS[carburant.lower()]
        
        params["custtype"] = "P"
        params["zipr"] = "150"
        params["zip"] = "75001"
        
        if page > 1:
            params["page"] = page
        
        return f"{self.base_url}/{'/'.join(path_parts)}?{urlencode(params)}"
    
    async def parse_listing_page(self, html: str) -> List[Dict[str, Any]]:
        """Parse une page de résultats AutoScout24"""
        listings = []
        
        try:
            soup = self.parse_html(html)
            
            for script in soup.find_all("script", {"type": "application/json"}):
                try:
                    data = json.loads(script.string)
                    ads = self._extract_ads(data)
                    for ad in ads:
                        listing = self._parse_ad_data(ad)
                        if listing:
                            listings.append(listing)
                except (json.JSONDecodeError, TypeError):
                    continue
            
            if not listings:
                listings = self._parse_html_listings(soup)
        
        except Exception as e:
            log_error("Erreur parsing page AutoScout24", e)
        
        return listings
    
    def _extract_ads(self, data: Any, depth: int = 0) -> List[Dict]:
        """Extrait les annonces du JSON"""
        ads = []
        if depth > 10:
            return ads
        
        if isinstance(data, dict):
            if "listings" in data:
                ads.extend(data["listings"])
            elif "id" in data and "price" in data:
                ads.append(data)
            else:
                for v in data.values():
                    ads.extend(self._extract_ads(v, depth + 1))
        elif isinstance(data, list):
            for item in data:
                ads.extend(self._extract_ads(item, depth + 1))
        
        return ads
    
    def _parse_ad_data(self, ad: Dict) -> Optional[Dict[str, Any]]:
        """Parse les données d'une annonce"""
        try:
            ad_id = ad.get("id")
            if not ad_id:
                return None
            
            url = ad.get("url") or f"{self.base_url}/annonce/{ad_id}"
            if not url.startswith("http"):
                url = f"{self.base_url}{url}"
            
            price = ad.get("price", {})
            prix = price.get("value") if isinstance(price, dict) else price
            
            vehicle = ad.get("vehicle", ad)
            location = ad.get("location", {})
            
            images = []
            for img in ad.get("images", [])[:10]:
                if isinstance(img, dict):
                    images.append(img.get("url", ""))
                elif isinstance(img, str):
                    images.append(img)
            
            return {
                "url": url,
                "source": self.name,
                "titre": ad.get("title") or vehicle.get("make", "") + " " + vehicle.get("model", ""),
                "prix": int(prix) if prix else None,
                "marque": vehicle.get("make"),
                "modele": vehicle.get("model"),
                "version": vehicle.get("version"),
                "annee": vehicle.get("firstRegistration"),
                "kilometrage": vehicle.get("mileage"),
                "carburant": vehicle.get("fuelType"),
                "ville": location.get("city"),
                "code_postal": location.get("zip"),
                "type_vendeur": "particulier" if ad.get("sellerType") == "P" else "pro",
                "images_urls": images,
            }
        except Exception as e:
            log_error("Erreur parsing annonce AutoScout24", e)
            return None
    
    def _parse_html_listings(self, soup) -> List[Dict[str, Any]]:
        """Parse HTML fallback"""
        listings = []
        
        cards = soup.select("[class*='ListItem']") or soup.select("article")
        
        for card in cards:
            try:
                link = card.find("a", href=True)
                if not link:
                    continue
                
                href = link.get("href", "")
                url = href if href.startswith("http") else f"{self.base_url}{href}"
                
                title_elem = card.find("h2") or card.find("[class*='title']")
                titre = title_elem.get_text(strip=True) if title_elem else None
                
                price_elem = card.find("[class*='price']")
                prix = self.clean_price(price_elem.get_text()) if price_elem else None
                
                listings.append({
                    "url": url,
                    "source": self.name,
                    "titre": titre,
                    "prix": prix,
                })
            except Exception:
                continue
        
        return listings
    
    async def parse_annonce_detail(self, url: str, data: Dict = None) -> Optional[Annonce]:
        """Parse le détail d'une annonce"""
        try:
            if data and all(k in data for k in ["titre", "prix"]):
                return self._create_annonce(data)
            
            html = await self.fetch_page(url)
            if not html:
                return self._create_annonce(data) if data else None
            
            soup = self.parse_html(html)
            parsed = data.copy() if data else {"url": url, "source": self.name}
            
            title = soup.find("h1")
            if title:
                parsed["titre"] = title.get_text(strip=True)
            
            for script in soup.find_all("script", {"type": "application/json"}):
                try:
                    json_data = json.loads(script.string)
                    if "price" in str(json_data):
                        ad_data = self._parse_ad_data(json_data)
                        if ad_data:
                            parsed.update(ad_data)
                            break
                except Exception:
                    continue
            
            return self._create_annonce(parsed)
            
        except Exception as e:
            log_error(f"Erreur parsing détail AutoScout24 {url}", e)
            return self._create_annonce(data) if data else None
    
    def _create_annonce(self, data: Dict) -> Annonce:
        """Crée un objet Annonce"""
        dept = data.get("departement")
        if not dept:
            dept = self.extract_departement(data.get("ville"), data.get("code_postal"))
        
        return Annonce(
            url=data.get("url"),
            source=self.name,
            marque=data.get("marque"),
            modele=data.get("modele"),
            version=data.get("version"),
            motorisation=data.get("motorisation"),
            carburant=data.get("carburant"),
            annee=data.get("annee"),
            kilometrage=data.get("kilometrage"),
            prix=data.get("prix"),
            ville=data.get("ville"),
            code_postal=data.get("code_postal"),
            departement=dept,
            telephone=data.get("telephone"),
            type_vendeur=data.get("type_vendeur", "particulier"),
            titre=data.get("titre"),
            description=data.get("description"),
            images_urls=data.get("images_urls", []),
            date_publication=data.get("date_publication"),
        )
