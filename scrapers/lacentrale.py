"""
LaCentrale Scraper - Scraper pour lacentrale.fr
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


class LaCentraleScraper(BaseScraper):
    """Scraper pour LaCentrale.fr"""
    
    name = "lacentrale"
    base_url = "https://www.lacentrale.fr"
    
    # Mapping des carburants
    CARBURANTS = {
        "diesel": "DIESEL",
        "essence": "ESSENCE",
    }
    
    # Mapping des marques
    MARQUES = {
        "peugeot": "PEUGEOT",
        "renault": "RENAULT",
        "dacia": "DACIA",
        "ford": "FORD",
        "toyota": "TOYOTA",
    }
    
    async def build_search_url(self, vehicule_config: Dict, page: int = 1) -> str:
        """Construit l'URL de recherche LaCentrale"""
        marque = vehicule_config.get("marque", "").lower()
        modeles = vehicule_config.get("modele", [])
        modele = modeles[0] if modeles else ""
        
        # Base path
        path_parts = ["listing"]
        
        # Construire les paramètres
        params = []
        
        # Marque
        if marque and marque in self.MARQUES:
            params.append(f"makesModelsCommercialNames={self.MARQUES[marque]}")
        
        # Prix
        if vehicule_config.get("prix_min"):
            params.append(f"priceMin={vehicule_config['prix_min']}")
        if vehicule_config.get("prix_max"):
            params.append(f"priceMax={vehicule_config['prix_max']}")
        
        # Kilométrage
        if vehicule_config.get("km_min"):
            params.append(f"mileageMin={vehicule_config['km_min']}")
        if vehicule_config.get("km_max"):
            params.append(f"mileageMax={vehicule_config['km_max']}")
        
        # Année
        if vehicule_config.get("annee_min"):
            params.append(f"yearMin={vehicule_config['annee_min']}")
        if vehicule_config.get("annee_max"):
            params.append(f"yearMax={vehicule_config['annee_max']}")
        
        # Carburant
        carburant = vehicule_config.get("carburant")
        if carburant and carburant.lower() in self.CARBURANTS:
            params.append(f"energies={self.CARBURANTS[carburant.lower()]}")
        
        # Vendeur particulier
        params.append("customerType=part")
        
        # Région Île-de-France
        params.append("regions=FR-IDF")
        
        # Pagination
        if page > 1:
            params.append(f"page={page}")
        
        # Tri par date
        params.append("sortBy=firstOnlineDateDesc")
        
        url = f"{self.base_url}/{'/'.join(path_parts)}?{'&'.join(params)}"
        
        return url
    
    async def parse_listing_page(self, html: str) -> List[Dict[str, Any]]:
        """Parse une page de résultats LaCentrale"""
        listings = []
        
        try:
            soup = self.parse_html(html)
            
            # Chercher les données JSON dans la page
            scripts = soup.find_all("script")
            
            for script in scripts:
                if script.string and "__NEXT_DATA__" in script.string:
                    try:
                        # Extraire le JSON de Next.js
                        match = re.search(r'__NEXT_DATA__\s*=\s*({.*?});', script.string, re.DOTALL)
                        if match:
                            data = json.loads(match.group(1))
                            ads = self._extract_ads_from_nextjs(data)
                            
                            for ad in ads:
                                listing = self._parse_ad_data(ad)
                                if listing:
                                    listings.append(listing)
                    except Exception as e:
                        log_error("Erreur extraction JSON Next.js", e)
                        continue
            
            # Chercher dans les scripts JSON-LD ou autres
            for script in soup.find_all("script", {"type": "application/json"}):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and "props" in data:
                        ads = self._extract_ads_from_nextjs(data)
                        for ad in ads:
                            listing = self._parse_ad_data(ad)
                            if listing:
                                listings.append(listing)
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Fallback: parser le HTML
            if not listings:
                listings = self._parse_html_listings(soup)
        
        except Exception as e:
            log_error("Erreur parsing page LaCentrale", e)
        
        return listings
    
    def _extract_ads_from_nextjs(self, data: Dict) -> List[Dict]:
        """Extrait les annonces du JSON Next.js"""
        ads = []
        
        try:
            # Parcourir la structure Next.js
            props = data.get("props", {})
            page_props = props.get("pageProps", {})
            
            # Chercher les résultats de recherche
            search_results = page_props.get("searchResults", {})
            vehicles = search_results.get("vehicles", [])
            
            if vehicles:
                ads.extend(vehicles)
            
            # Alternative: chercher dans d'autres clés
            for key in ["results", "listings", "ads", "vehicles"]:
                if key in page_props and isinstance(page_props[key], list):
                    ads.extend(page_props[key])
        
        except Exception:
            pass
        
        return ads
    
    def _parse_ad_data(self, ad: Dict) -> Optional[Dict[str, Any]]:
        """Parse les données d'une annonce LaCentrale"""
        try:
            # ID et URL
            ad_id = ad.get("id") or ad.get("classifiedId")
            if not ad_id:
                return None
            
            url = ad.get("url") or f"{self.base_url}/auto-occasion-annonce-{ad_id}.html"
            if not url.startswith("http"):
                url = f"{self.base_url}{url}"
            
            # Extraire les informations du véhicule
            vehicle = ad.get("vehicle", ad)
            
            # Prix
            prix = None
            price_data = ad.get("price", ad.get("prices", {}))
            if isinstance(price_data, dict):
                prix = price_data.get("price") or price_data.get("mainPrice")
            elif isinstance(price_data, (int, float)):
                prix = int(price_data)
            
            # Localisation
            location = ad.get("location", {})
            
            # Images
            images = []
            media = ad.get("media", ad.get("images", []))
            if isinstance(media, list):
                for m in media[:10]:
                    if isinstance(m, dict):
                        images.append(m.get("url") or m.get("src", ""))
                    elif isinstance(m, str):
                        images.append(m)
            
            listing = {
                "url": url,
                "source": self.name,
                "titre": ad.get("title") or vehicle.get("commercialName"),
                "prix": prix,
                "marque": vehicle.get("make") or vehicle.get("brand"),
                "modele": vehicle.get("model") or vehicle.get("range"),
                "version": vehicle.get("version") or vehicle.get("commercialName"),
                "annee": vehicle.get("year") or vehicle.get("firstRegistrationYear"),
                "kilometrage": vehicle.get("mileage") or vehicle.get("km"),
                "carburant": vehicle.get("energy") or vehicle.get("fuel"),
                "motorisation": vehicle.get("engine"),
                "ville": location.get("city") or location.get("cityName"),
                "code_postal": location.get("zipCode") or location.get("postalCode"),
                "departement": location.get("department"),
                "type_vendeur": "particulier" if ad.get("isPrivate") or ad.get("customerType") == "part" else "pro",
                "images_urls": images,
            }
            
            return listing
            
        except Exception as e:
            log_error("Erreur parsing annonce LaCentrale", e)
            return None
    
    def _parse_html_listings(self, soup) -> List[Dict[str, Any]]:
        """Parse les annonces depuis le HTML (fallback)"""
        listings = []
        
        # Sélecteurs possibles pour les cartes d'annonces
        selectors = [
            "[data-testid='classified-card']",
            ".searchCard",
            ".classified-card",
            "article.vehicle-card",
        ]
        
        ad_cards = []
        for selector in selectors:
            ad_cards = soup.select(selector)
            if ad_cards:
                break
        
        for card in ad_cards:
            try:
                # URL
                link = card.find("a", href=True)
                if not link:
                    continue
                
                href = link.get("href", "")
                url = href if href.startswith("http") else f"{self.base_url}{href}"
                
                # Titre
                title_elem = card.find("h2") or card.find("h3") or card.find("[class*='title']")
                titre = title_elem.get_text(strip=True) if title_elem else None
                
                # Prix
                price_elem = card.find("[class*='price']") or card.find("[data-testid='price']")
                prix = self.clean_price(price_elem.get_text()) if price_elem else None
                
                # Localisation
                loc_elem = card.find("[class*='location']") or card.find("[class*='city']")
                ville = loc_elem.get_text(strip=True) if loc_elem else None
                
                # Kilométrage
                km_elem = card.find("[class*='mileage']") or card.find("[class*='km']")
                km = self.clean_km(km_elem.get_text()) if km_elem else None
                
                # Année
                year_elem = card.find("[class*='year']")
                annee = self.clean_year(year_elem.get_text()) if year_elem else None
                
                listing = {
                    "url": url,
                    "source": self.name,
                    "titre": titre,
                    "prix": prix,
                    "ville": ville,
                    "kilometrage": km,
                    "annee": annee,
                }
                
                listings.append(listing)
                
            except Exception as e:
                log_error("Erreur parsing carte HTML LaCentrale", e)
                continue
        
        return listings
    
    async def parse_annonce_detail(self, url: str, data: Dict = None) -> Optional[Annonce]:
        """Parse le détail d'une annonce LaCentrale"""
        try:
            # Si on a déjà les données complètes
            if data and all(k in data for k in ["titre", "prix", "marque"]):
                return self._create_annonce_from_data(data)
            
            # Charger la page de détail
            html = await self.fetch_page(url)
            if not html:
                return None
            
            soup = self.parse_html(html)
            
            # Chercher les données JSON
            for script in soup.find_all("script"):
                if script.string and "__NEXT_DATA__" in script.string:
                    try:
                        match = re.search(r'__NEXT_DATA__\s*=\s*({.*?});', script.string, re.DOTALL)
                        if match:
                            json_data = json.loads(match.group(1))
                            ad_data = self._extract_detail_from_nextjs(json_data)
                            
                            if ad_data:
                                if data:
                                    ad_data = {**data, **ad_data}
                                return self._create_annonce_from_data(ad_data)
                    except Exception:
                        continue
            
            # Fallback
            if data:
                return self._create_annonce_from_data(data)
            
            return None
            
        except Exception as e:
            log_error(f"Erreur parsing détail LaCentrale {url}", e)
            return None
    
    def _extract_detail_from_nextjs(self, data: Dict) -> Optional[Dict]:
        """Extrait les détails d'une annonce du JSON Next.js"""
        try:
            props = data.get("props", {}).get("pageProps", {})
            
            # Chercher l'annonce
            classified = props.get("classified") or props.get("vehicle") or props.get("ad")
            
            if classified:
                return self._parse_ad_data(classified)
        
        except Exception:
            pass
        
        return None
    
    def _create_annonce_from_data(self, data: Dict) -> Annonce:
        """Crée un objet Annonce depuis les données parsées"""
        dept = data.get("departement")
        if not dept:
            dept = self.extract_departement(data.get("ville"), data.get("code_postal"))
        
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
            telephone=data.get("telephone"),
            nom_vendeur=data.get("nom_vendeur"),
            type_vendeur=data.get("type_vendeur", "particulier"),
            titre=data.get("titre"),
            description=data.get("description"),
            images_urls=data.get("images_urls", []),
            date_publication=data.get("date_publication"),
        )
        
        return annonce
