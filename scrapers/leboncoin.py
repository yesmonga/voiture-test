"""
LeBoncoin Scraper - Scraper pour leboncoin.fr
"""

import re
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode, quote

from .base_scraper import BaseScraper
from models.annonce import Annonce
from utils.logger import get_logger, log_error
from config import DEPARTEMENTS_PRIORITAIRES, DEPARTEMENTS_SECONDAIRES

logger = get_logger(__name__)


class LeBoncoinScraper(BaseScraper):
    """Scraper pour LeBoncoin.fr"""
    
    name = "leboncoin"
    base_url = "https://www.leboncoin.fr"
    api_url = "https://api.leboncoin.fr/finder/search"
    
    # Mapping des régions LeBoncoin
    REGIONS_LBC = {
        "ile_de_france": "12",
        "hauts_de_france": "22",
    }
    
    # Mapping carburants
    CARBURANTS = {
        "diesel": "2",
        "essence": "1",
    }
    
    # Mapping marques (IDs LeBoncoin)
    MARQUES = {
        "peugeot": "peugeot",
        "renault": "renault",
        "dacia": "dacia",
        "ford": "ford",
        "toyota": "toyota",
    }
    
    async def build_search_url(self, vehicule_config: Dict, page: int = 1) -> str:
        """Construit l'URL de recherche LeBoncoin"""
        marque = vehicule_config.get("marque", "").lower()
        modeles = vehicule_config.get("modele", [])
        modele = modeles[0].lower() if modeles else ""
        
        # Construction des paramètres
        params = {
            "category": "2",  # Voitures
            "owner_type": "private",  # Particuliers uniquement
            "sort": "time",  # Tri par date
            "order": "desc",
        }
        
        # Prix
        if vehicule_config.get("prix_min"):
            params["price"] = f"{vehicule_config['prix_min']}-{vehicule_config.get('prix_max', '')}"
        
        # Kilométrage
        if vehicule_config.get("km_max"):
            params["mileage"] = f"{vehicule_config.get('km_min', 0)}-{vehicule_config['km_max']}"
        
        # Année
        if vehicule_config.get("annee_min"):
            params["regdate"] = f"{vehicule_config['annee_min']}-{vehicule_config.get('annee_max', 2025)}"
        
        # Carburant
        carburant = vehicule_config.get("carburant")
        if carburant and carburant.lower() in self.CARBURANTS:
            params["fuel"] = self.CARBURANTS[carburant.lower()]
        
        # Marque
        if marque:
            params["brand"] = marque
        
        # Modèle
        if modele:
            params["model"] = modele
        
        # Région (Île-de-France par défaut)
        params["locations"] = "r_12"  # Île-de-France
        
        # Pagination
        if page > 1:
            params["page"] = str(page)
        
        # Construire l'URL
        url = f"{self.base_url}/recherche?{urlencode(params)}"
        
        return url
    
    async def parse_listing_page(self, html: str) -> List[Dict[str, Any]]:
        """Parse une page de résultats LeBoncoin"""
        listings = []
        
        try:
            soup = self.parse_html(html)
            
            # LeBoncoin stocke les données dans un script JSON
            script_tags = soup.find_all("script", {"type": "application/json"})
            
            for script in script_tags:
                try:
                    data = json.loads(script.string)
                    
                    # Chercher les annonces dans la structure de données
                    ads = self._extract_ads_from_json(data)
                    
                    for ad in ads:
                        listing = self._parse_ad_json(ad)
                        if listing:
                            listings.append(listing)
                
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Fallback: parser le HTML directement si pas de JSON
            if not listings:
                listings = self._parse_html_listings(soup)
        
        except Exception as e:
            log_error(f"Erreur parsing page LeBoncoin", e)
        
        return listings
    
    def _extract_ads_from_json(self, data: Any, depth: int = 0) -> List[Dict]:
        """Extrait les annonces d'une structure JSON imbriquée"""
        ads = []
        
        if depth > 10:  # Éviter la récursion infinie
            return ads
        
        if isinstance(data, dict):
            # Vérifier si c'est une annonce
            if "list_id" in data and "subject" in data:
                ads.append(data)
            elif "ads" in data and isinstance(data["ads"], list):
                ads.extend(data["ads"])
            else:
                # Parcourir récursivement
                for value in data.values():
                    ads.extend(self._extract_ads_from_json(value, depth + 1))
        
        elif isinstance(data, list):
            for item in data:
                ads.extend(self._extract_ads_from_json(item, depth + 1))
        
        return ads
    
    def _parse_ad_json(self, ad: Dict) -> Optional[Dict[str, Any]]:
        """Parse une annonce depuis le JSON LeBoncoin"""
        try:
            list_id = ad.get("list_id")
            if not list_id:
                return None
            
            # URL de l'annonce
            url = f"{self.base_url}/ad/voitures/{list_id}.htm"
            
            # Extraire les attributs
            attributes = {attr.get("key"): attr.get("value") for attr in ad.get("attributes", [])}
            
            # Localisation
            location = ad.get("location", {})
            
            # Date de publication
            date_pub = None
            first_pub = ad.get("first_publication_date") or ad.get("index_date")
            if first_pub:
                try:
                    date_pub = datetime.fromisoformat(first_pub.replace("Z", "+00:00"))
                except Exception:
                    pass
            
            # Parse images safely
            images_urls = []
            images_data = ad.get("images", {})
            if isinstance(images_data, dict):
                urls_thumb = images_data.get("urls_thumb", [])
                if isinstance(urls_thumb, list):
                    for img in urls_thumb:
                        if isinstance(img, dict):
                            url_img = img.get("urls", {}).get("default") if isinstance(img.get("urls"), dict) else None
                            if url_img:
                                images_urls.append(url_img)
                        elif isinstance(img, str):
                            images_urls.append(img)
            elif isinstance(images_data, list):
                for img in images_data:
                    if isinstance(img, str):
                        images_urls.append(img)
                    elif isinstance(img, dict):
                        images_urls.append(img.get("url", ""))
            
            listing = {
                "url": url,
                "source": self.name,
                "titre": ad.get("subject"),
                "prix": ad.get("price", [None])[0] if isinstance(ad.get("price"), list) else ad.get("price"),
                "ville": location.get("city"),
                "code_postal": location.get("zipcode"),
                "departement": location.get("department_id"),
                "marque": attributes.get("brand"),
                "modele": attributes.get("model"),
                "annee": self.clean_year(attributes.get("regdate")),
                "kilometrage": self.clean_km(attributes.get("mileage")),
                "carburant": attributes.get("fuel"),
                "motorisation": attributes.get("vehicle_engine"),
                "type_vendeur": "particulier" if ad.get("owner_type") == "private" else "pro",
                "images_urls": images_urls,
                "date_publication": date_pub,
                "description": ad.get("body"),
            }
            
            return listing
            
        except Exception as e:
            log_error(f"Erreur parsing annonce JSON LeBoncoin", e)
            return None
    
    def _parse_html_listings(self, soup) -> List[Dict[str, Any]]:
        """Parse les annonces depuis le HTML (fallback)"""
        listings = []
        
        # Sélecteurs pour les cartes d'annonces
        ad_cards = soup.select("[data-qa-id='aditem_container']") or \
                   soup.select(".styles_adCard__") or \
                   soup.select("article[data-test-id]")
        
        for card in ad_cards:
            try:
                # URL
                link = card.find("a", href=True)
                if not link:
                    continue
                
                href = link.get("href", "")
                url = href if href.startswith("http") else f"{self.base_url}{href}"
                
                # Titre
                title_elem = card.select_one("[data-qa-id='aditem_title']") or card.find("h2") or card.find("p", class_=re.compile(r"title", re.I))
                titre = title_elem.get_text(strip=True) if title_elem else None
                
                # Prix
                price_elem = card.select_one("[data-qa-id='aditem_price']") or card.find("span", class_=re.compile(r"price", re.I))
                prix = self.clean_price(price_elem.get_text()) if price_elem else None
                
                # Localisation
                loc_elem = card.select_one("[data-qa-id='aditem_location']") or card.find("p", class_=re.compile(r"location", re.I))
                ville = loc_elem.get_text(strip=True) if loc_elem else None
                
                listing = {
                    "url": url,
                    "source": self.name,
                    "titre": titre,
                    "prix": prix,
                    "ville": ville,
                }
                
                listings.append(listing)
                
            except Exception as e:
                log_error(f"Erreur parsing carte HTML LeBoncoin", e)
                continue
        
        return listings
    
    async def parse_annonce_detail(self, url: str, data: Dict = None) -> Optional[Annonce]:
        """Parse le détail d'une annonce LeBoncoin"""
        try:
            # Si on a déjà toutes les données du listing, pas besoin de recharger
            if data and all(k in data for k in ["titre", "prix", "marque", "modele"]):
                return self._create_annonce_from_data(data)
            
            # Sinon, charger la page de détail
            html = await self.fetch_page(url)
            if not html:
                return None
            
            soup = self.parse_html(html)
            
            # Extraire les données JSON de la page
            script_tags = soup.find_all("script", {"type": "application/json"})
            
            for script in script_tags:
                try:
                    json_data = json.loads(script.string)
                    ad = self._find_ad_in_json(json_data)
                    
                    if ad:
                        parsed_data = self._parse_ad_json(ad)
                        if parsed_data:
                            # Merger avec les données existantes
                            if data:
                                parsed_data = {**data, **parsed_data}
                            return self._create_annonce_from_data(parsed_data)
                
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Fallback: créer depuis les données existantes
            if data:
                return self._create_annonce_from_data(data)
            
            return None
            
        except Exception as e:
            log_error(f"Erreur parsing détail LeBoncoin {url}", e)
            return None
    
    def _find_ad_in_json(self, data: Any, depth: int = 0) -> Optional[Dict]:
        """Trouve l'annonce principale dans le JSON"""
        if depth > 10:
            return None
        
        if isinstance(data, dict):
            if "list_id" in data and "subject" in data and "attributes" in data:
                return data
            
            for value in data.values():
                result = self._find_ad_in_json(value, depth + 1)
                if result:
                    return result
        
        elif isinstance(data, list):
            for item in data:
                result = self._find_ad_in_json(item, depth + 1)
                if result:
                    return result
        
        return None
    
    def _create_annonce_from_data(self, data: Dict) -> Annonce:
        """Crée un objet Annonce depuis les données parsées"""
        # Extraire le département
        dept = data.get("departement")
        if not dept:
            dept = self.extract_departement(data.get("ville"), data.get("code_postal"))
        
        # Nettoyer le téléphone si présent
        telephone = data.get("telephone")
        if telephone:
            telephone = re.sub(r"[^\d+]", "", telephone)
        
        annonce = Annonce(
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
            telephone=telephone,
            nom_vendeur=data.get("nom_vendeur"),
            type_vendeur=data.get("type_vendeur", "particulier"),
            titre=data.get("titre"),
            description=data.get("description"),
            images_urls=data.get("images_urls", []),
            date_publication=data.get("date_publication"),
        )
        
        return annonce
