"""
ParuVendu Scraper - Scraper pour paruvendu.fr
"""

import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode

from .base_scraper import BaseScraper
from models.annonce import Annonce
from utils.logger import get_logger, log_error

logger = get_logger(__name__)


class ParuVenduScraper(BaseScraper):
    """Scraper pour ParuVendu.fr"""
    
    name = "paruvendu"
    base_url = "https://www.paruvendu.fr"
    
    # Codes régions ParuVendu
    REGIONS = {
        "ile_de_france": "R12",
        "hauts_de_france": "R22",
    }
    
    # Mapping marques
    MARQUES = {
        "peugeot": "PEUGEOT",
        "renault": "RENAULT",
        "dacia": "DACIA",
        "ford": "FORD",
        "toyota": "TOYOTA",
    }
    
    async def build_search_url(self, vehicule_config: Dict, page: int = 1) -> str:
        """Construit l'URL de recherche ParuVendu"""
        marque = vehicule_config.get("marque", "").lower()
        
        # Base URL
        base = f"{self.base_url}/auto-moto/voiture/"
        
        # Paramètres
        params = {
            "r": "R12",  # Île-de-France
            "ty": "P",  # Particuliers
        }
        
        # Marque
        if marque and marque in self.MARQUES:
            params["ma0"] = self.MARQUES[marque]
        
        # Prix
        if vehicule_config.get("prix_min"):
            params["px0"] = vehicule_config["prix_min"]
        if vehicule_config.get("prix_max"):
            params["px1"] = vehicule_config["prix_max"]
        
        # Kilométrage
        if vehicule_config.get("km_max"):
            params["km1"] = vehicule_config["km_max"]
        
        # Année
        if vehicule_config.get("annee_min"):
            params["am0"] = vehicule_config["annee_min"]
        if vehicule_config.get("annee_max"):
            params["am1"] = vehicule_config["annee_max"]
        
        # Carburant
        carburant = vehicule_config.get("carburant")
        if carburant:
            if carburant.lower() == "diesel":
                params["ca"] = "D"
            elif carburant.lower() == "essence":
                params["ca"] = "E"
        
        # Pagination
        if page > 1:
            params["p"] = page
        
        # Tri par date
        params["tri"] = "da"
        
        url = f"{base}?{urlencode(params)}"
        
        return url
    
    async def parse_listing_page(self, html: str) -> List[Dict[str, Any]]:
        """Parse une page de résultats ParuVendu"""
        listings = []
        
        try:
            soup = self.parse_html(html)
            
            # Sélecteurs pour les annonces
            ad_cards = soup.select(".ergov3-annonce") or \
                       soup.select("[class*='annonce']") or \
                       soup.select(".resultatAnnonce")
            
            for card in ad_cards:
                try:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                except Exception as e:
                    log_error("Erreur parsing carte ParuVendu", e)
                    continue
        
        except Exception as e:
            log_error("Erreur parsing page ParuVendu", e)
        
        return listings
    
    def _parse_card(self, card) -> Optional[Dict[str, Any]]:
        """Parse une carte d'annonce"""
        # URL
        link = card.find("a", href=True)
        if not link:
            return None
        
        href = link.get("href", "")
        if not href:
            return None
        
        url = href if href.startswith("http") else f"{self.base_url}{href}"
        
        # Vérifier que c'est une annonce auto
        if "/auto-moto/" not in url and "/voiture/" not in url:
            return None
        
        # Titre
        title_elem = card.find("h3") or card.find("h2") or card.find("[class*='titre']")
        titre = title_elem.get_text(strip=True) if title_elem else None
        
        # Prix
        price_elem = card.find("[class*='prix']") or card.find("[class*='price']")
        prix = None
        if price_elem:
            prix = self.clean_price(price_elem.get_text())
        
        # Localisation
        loc_elem = card.find("[class*='localisation']") or card.find("[class*='location']")
        ville = None
        code_postal = None
        if loc_elem:
            loc_text = loc_elem.get_text(strip=True)
            ville = loc_text
            # Extraire le code postal
            cp_match = re.search(r"\b(\d{5})\b", loc_text)
            if cp_match:
                code_postal = cp_match.group(1)
        
        # Détails (km, année, etc.)
        details_elem = card.find("[class*='caracteristiques']") or card.find("[class*='details']")
        km = None
        annee = None
        carburant = None
        
        if details_elem:
            details_text = details_elem.get_text(strip=True)
            
            # Kilométrage
            km_match = re.search(r"(\d[\d\s]*)\s*km", details_text, re.I)
            if km_match:
                km = self.clean_km(km_match.group(1))
            
            # Année
            year_match = re.search(r"\b(19|20)\d{2}\b", details_text)
            if year_match:
                annee = int(year_match.group())
            
            # Carburant
            if re.search(r"diesel", details_text, re.I):
                carburant = "diesel"
            elif re.search(r"essence", details_text, re.I):
                carburant = "essence"
        
        # Images
        images = []
        img_elem = card.find("img", src=True)
        if img_elem:
            src = img_elem.get("src") or img_elem.get("data-src")
            if src:
                images.append(src if src.startswith("http") else f"{self.base_url}{src}")
        
        # Extraire marque/modèle du titre
        marque = None
        modele = None
        if titre:
            # Pattern: "MARQUE MODELE ..."
            for m in ["peugeot", "renault", "dacia", "ford", "toyota"]:
                if m in titre.lower():
                    marque = m.capitalize()
                    # Le modèle est généralement après la marque
                    parts = titre.lower().split(m)
                    if len(parts) > 1:
                        modele_part = parts[1].strip().split()[0] if parts[1].strip() else None
                        if modele_part:
                            modele = modele_part
                    break
        
        listing = {
            "url": url,
            "source": self.name,
            "titre": titre,
            "prix": prix,
            "marque": marque,
            "modele": modele,
            "annee": annee,
            "kilometrage": km,
            "carburant": carburant,
            "ville": ville,
            "code_postal": code_postal,
            "images_urls": images,
            "type_vendeur": "particulier",
        }
        
        return listing
    
    async def parse_annonce_detail(self, url: str, data: Dict = None) -> Optional[Annonce]:
        """Parse le détail d'une annonce ParuVendu"""
        try:
            # Charger la page de détail
            html = await self.fetch_page(url)
            if not html:
                if data:
                    return self._create_annonce_from_data(data)
                return None
            
            soup = self.parse_html(html)
            
            parsed_data = data.copy() if data else {"url": url, "source": self.name}
            
            # Titre
            title_elem = soup.find("h1")
            if title_elem:
                parsed_data["titre"] = title_elem.get_text(strip=True)
            
            # Prix
            price_elem = soup.find("[class*='prix-annonce']") or soup.find("[itemprop='price']")
            if price_elem:
                parsed_data["prix"] = self.clean_price(price_elem.get_text())
            
            # Description
            desc_elem = soup.find("[class*='description']") or soup.find("[itemprop='description']")
            if desc_elem:
                parsed_data["description"] = desc_elem.get_text(strip=True)
            
            # Caractéristiques
            chars = soup.find_all("[class*='caracteristique']") or soup.find_all("li", class_=re.compile(r"carac"))
            
            for char in chars:
                text = char.get_text(strip=True).lower()
                
                if "année" in text or "mise en circulation" in text:
                    parsed_data["annee"] = self.clean_year(text)
                elif "kilométrage" in text or "km" in text:
                    parsed_data["kilometrage"] = self.clean_km(text)
                elif "carburant" in text or "énergie" in text:
                    if "diesel" in text:
                        parsed_data["carburant"] = "diesel"
                    elif "essence" in text:
                        parsed_data["carburant"] = "essence"
                elif "marque" in text:
                    # Extraire la valeur
                    for m in ["peugeot", "renault", "dacia", "ford", "toyota"]:
                        if m in text:
                            parsed_data["marque"] = m.capitalize()
                            break
            
            # Téléphone
            tel_elem = soup.find("[class*='telephone']") or soup.find("a", href=re.compile(r"^tel:"))
            if tel_elem:
                tel_text = tel_elem.get("href", "") or tel_elem.get_text()
                tel = re.sub(r"[^\d+]", "", tel_text)
                if len(tel) >= 10:
                    parsed_data["telephone"] = tel
            
            # Images
            images = []
            for img in soup.select("[class*='photo'] img, [class*='galerie'] img"):
                src = img.get("src") or img.get("data-src")
                if src and "http" in src:
                    images.append(src)
            
            if images:
                parsed_data["images_urls"] = images
            
            return self._create_annonce_from_data(parsed_data)
            
        except Exception as e:
            log_error(f"Erreur parsing détail ParuVendu {url}", e)
            if data:
                return self._create_annonce_from_data(data)
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
