#!/usr/bin/env python3
"""
Scraping immédiat avec proxies résidentiels FR
Scrape AutoScout24 et envoie les meilleures annonces sur Discord
"""

import asyncio
import httpx
import re
import json
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

from models.annonce import Annonce
from models.database import get_db
from services.scorer import ScoringService
from services.notifier import NotificationService
from utils.anti_bot import anti_bot
from config import VEHICULES_CIBLES, TOUS_DEPARTEMENTS


class QuickScraper:
    """Scraper rapide avec proxies"""
    
    def __init__(self):
        self.db = get_db()
        self.scorer = ScoringService()
        self.notifier = NotificationService()
        self.annonces: List[Annonce] = []
    
    async def scrape_autoscout(self, marque: str, modele: str, config: dict) -> List[Dict]:
        """Scrape AutoScout24 pour un véhicule"""
        proxy = anti_bot.get_proxy()
        headers = anti_bot.get_headers()
        
        # Construire l'URL
        carburant = (config.get("carburant") or "").lower()
        fuel_param = "D" if carburant == "diesel" else "B" if carburant == "essence" else ""
        
        params = [
            f"pricefrom={config.get('prix_min', 1500)}",
            f"priceto={config.get('prix_max', 4000)}",
            f"kmto={config.get('km_max', 200000)}",
            "cy=F",
            "atype=C",
            "sort=age",
            "desc=1",
        ]
        if fuel_param:
            params.append(f"fuel={fuel_param}")
        
        url = f"https://www.autoscout24.fr/lst/{marque.lower()}/{modele.lower()}?{'&'.join(params)}"
        
        print(f"  🔍 {marque} {modele}: {url[:80]}...")
        
        listings = []
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=30, follow_redirects=True) as client:
                r = await client.get(url, headers=headers)
                
                if r.status_code != 200:
                    print(f"    ❌ HTTP {r.status_code}")
                    return []
                
                soup = BeautifulSoup(r.text, "lxml")
                
                # Parser les articles
                cards = soup.select("article")
                
                for card in cards:
                    try:
                        listing = self._parse_autoscout_card(card, marque, modele, config)
                        if listing:
                            listings.append(listing)
                    except Exception:
                        continue
                
                print(f"    ✅ {len(listings)} annonces")
                
        except Exception as e:
            print(f"    ❌ Erreur: {e}")
        
        return listings
    
    def _parse_autoscout_card(self, card, marque: str, modele: str, config: dict) -> Optional[Dict]:
        """Parse une carte AutoScout24"""
        link = card.find("a", href=True)
        if not link:
            return None
        
        href = link.get("href", "")
        if not href or "/annonce/" not in href and "/offers/" not in href:
            # Chercher le bon lien
            all_links = card.find_all("a", href=True)
            for l in all_links:
                h = l.get("href", "")
                if "/annonce/" in h or "/offers/" in h or "/voiture/" in h:
                    href = h
                    break
        
        if not href:
            return None
        
        url = href if href.startswith("http") else f"https://www.autoscout24.fr{href}"
        
        # Titre
        title_elem = card.find("h2") or card.select_one("[class*='title']")
        titre = title_elem.get_text(strip=True) if title_elem else f"{marque} {modele}"
        
        # Prix
        prix = None
        price_elem = card.select_one("[data-testid='price']")
        if not price_elem:
            # Chercher le texte avec €
            for elem in card.find_all(string=True):
                if "€" in elem:
                    cleaned = "".join(c for c in elem if c.isdigit())
                    if cleaned and len(cleaned) >= 3:
                        prix = int(cleaned)
                        break
        else:
            cleaned = "".join(c for c in price_elem.get_text() if c.isdigit())
            if cleaned:
                prix = int(cleaned)
        
        # Kilométrage
        km = None
        km_pattern = re.compile(r'(\d+[\s\.]?\d*)\s*km', re.I)
        for text in card.stripped_strings:
            match = km_pattern.search(text)
            if match:
                km_str = match.group(1).replace(" ", "").replace(".", "")
                km = int(km_str)
                break
        
        # Année
        annee = None
        year_pattern = re.compile(r'\b(20[0-2]\d|19[9]\d)\b')
        for text in card.stripped_strings:
            match = year_pattern.search(text)
            if match:
                annee = int(match.group(1))
                break
        
        # Carburant
        carburant = None
        text_lower = card.get_text().lower()
        if "diesel" in text_lower:
            carburant = "Diesel"
        elif "essence" in text_lower or "petrol" in text_lower:
            carburant = "Essence"
        
        # Localisation
        ville = None
        loc_elem = card.select_one("[class*='location'], [class*='city']")
        if loc_elem:
            ville = loc_elem.get_text(strip=True)
        
        return {
            "url": url,
            "source": "autoscout24",
            "marque": marque,
            "modele": modele,
            "titre": titre,
            "prix": prix,
            "kilometrage": km,
            "annee": annee,
            "carburant": carburant or config.get("carburant"),
            "ville": ville,
        }
    
    def _matches_criteria(self, data: Dict, config: Dict) -> bool:
        """Vérifie si l'annonce correspond aux critères"""
        prix = data.get("prix")
        if prix:
            if prix < config.get("prix_min", 0) * 0.8:  # Marge de 20%
                return False
            if prix > config.get("prix_max", 999999) * 1.2:
                return False
        
        km = data.get("kilometrage")
        if km:
            if km > config.get("km_max", 999999) * 1.1:
                return False
        
        return True
    
    async def scrape_all(self) -> List[Annonce]:
        """Scrape tous les véhicules cibles"""
        print("=" * 60)
        print("🚗 SCRAPING AVEC PROXIES RÉSIDENTIELS FR")
        print("=" * 60)
        
        all_annonces = []
        
        # Scraper AutoScout24 pour chaque véhicule cible
        for vid, config in VEHICULES_CIBLES.items():
            marque = config.get("marque", "")
            modeles = config.get("modele", [])
            
            for modele in modeles[:1]:  # Premier modèle seulement
                await asyncio.sleep(2)  # Pause anti-bot
                
                listings = await self.scrape_autoscout(marque, modele, config)
                
                for data in listings:
                    # Vérifier si nouvelle
                    if self.db.exists(data["url"]):
                        continue
                    
                    # Vérifier critères
                    if not self._matches_criteria(data, config):
                        continue
                    
                    # Créer l'annonce
                    annonce = Annonce(
                        url=data["url"],
                        source=data["source"],
                        marque=data.get("marque") or marque,
                        modele=data.get("modele") or modele,
                        carburant=data.get("carburant"),
                        annee=data.get("annee"),
                        kilometrage=data.get("kilometrage"),
                        prix=data.get("prix"),
                        ville=data.get("ville"),
                        titre=data.get("titre"),
                        type_vendeur="particulier",
                        date_publication=datetime.now(),
                    )
                    annonce.vehicule_cible_id = vid
                    
                    # Scorer
                    score, mots_cles = self.scorer.calculer_score(annonce)
                    
                    # Sauvegarder
                    self.db.save_annonce(annonce)
                    all_annonces.append(annonce)
        
        # Trier par score
        all_annonces.sort(key=lambda a: a.score_rentabilite, reverse=True)
        
        print(f"\n📊 Total: {len(all_annonces)} nouvelles annonces")
        return all_annonces
    
    async def notify_best(self, annonces: List[Annonce], max_notify: int = 10):
        """Envoie les meilleures annonces sur Discord"""
        if not annonces:
            print("❌ Aucune annonce à notifier")
            return
        
        print("\n" + "=" * 60)
        print(f"📤 ENVOI DES {min(len(annonces), max_notify)} MEILLEURES ANNONCES")
        print("=" * 60)
        
        for annonce in annonces[:max_notify]:
            if annonce.score_rentabilite < 30:
                continue
            
            print(f"\n🔔 {annonce.marque} {annonce.modele} - {annonce.prix}€ - Score: {annonce.score_rentabilite}")
            
            success = await self.notifier.send_discord(annonce)
            if success:
                print("   ✅ Envoyé!")
                self.db.mark_notified(annonce.id)
            else:
                print("   ❌ Échec")
            
            await asyncio.sleep(1)  # Rate limit Discord


async def main():
    scraper = QuickScraper()
    
    # Scraper
    annonces = await scraper.scrape_all()
    
    # Afficher les meilleures
    print("\n" + "=" * 60)
    print("🏆 TOP ANNONCES")
    print("=" * 60)
    
    for i, a in enumerate(annonces[:15], 1):
        print(f"{i:2}. [{a.score_rentabilite:3}/100] {a.marque} {a.modele} - {a.prix}€")
        if a.kilometrage:
            print(f"    Km: {a.kilometrage:,} | Année: {a.annee} | {a.ville or 'N/A'}")
        print(f"    {a.url}")
    
    # Notifier
    await scraper.notify_best(annonces, max_notify=10)
    
    print("\n✅ Terminé! Vérifie Discord.")


if __name__ == "__main__":
    asyncio.run(main())
