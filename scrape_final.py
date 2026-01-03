#!/usr/bin/env python3
"""
Scraping final - AutoScout24 avec proxies FR
"""

import asyncio
import httpx
import re
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, Dict

from models.annonce import Annonce
from models.database import get_db
from services.scorer import ScoringService
from services.notifier import NotificationService
from utils.anti_bot import anti_bot

# Véhicules à scraper
RECHERCHES = [
    {"marque": "peugeot", "modele": "207", "prix_max": 4000},
    {"marque": "renault", "modele": "clio", "prix_max": 4000},
    {"marque": "dacia", "modele": "sandero", "prix_max": 5000},
    {"marque": "renault", "modele": "twingo", "prix_max": 4000},
    {"marque": "ford", "modele": "fiesta", "prix_max": 5000},
    {"marque": "toyota", "modele": "yaris", "prix_max": 5000},
    {"marque": "citroen", "modele": "c3", "prix_max": 4000},
    {"marque": "volkswagen", "modele": "polo", "prix_max": 5000},
]


async def scrape_autoscout(marque: str, modele: str, prix_max: int) -> List[Dict]:
    """Scrape AutoScout24"""
    proxy = anti_bot.get_proxy()
    headers = anti_bot.get_headers()
    
    url = f"https://www.autoscout24.fr/lst/{marque}/{modele}?cy=F&atype=C&sort=age&desc=1&priceto={prix_max}&kmto=200000"
    
    print(f"🔍 {marque.title()} {modele.title()}...", end=" ", flush=True)
    
    annonces = []
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=30, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            
            if r.status_code != 200:
                print(f"❌ HTTP {r.status_code}")
                return []
            
            soup = BeautifulSoup(r.text, "lxml")
            articles = soup.find_all("article")
            
            for art in articles:
                try:
                    # Titre
                    h2 = art.find("h2")
                    titre = h2.get_text(strip=True) if h2 else None
                    if not titre:
                        continue
                    
                    # Lien
                    link = art.find("a", href=True)
                    href = link.get("href", "") if link else ""
                    if not href:
                        continue
                    full_url = href if href.startswith("http") else f"https://www.autoscout24.fr{href}"
                    
                    # Prix
                    prix = None
                    for text in art.stripped_strings:
                        if "€" in text:
                            cleaned = re.sub(r"[^\d]", "", text)
                            if cleaned:
                                val = int(cleaned)
                                if 500 <= val <= 50000:
                                    prix = val
                                    break
                    
                    # Km
                    km = None
                    text = art.get_text()
                    km_match = re.search(r"(\d{1,3}(?:[\s\.\u202f]\d{3})*)\s*km", text, re.I)
                    if km_match:
                        km_str = re.sub(r"[^\d]", "", km_match.group(1))
                        if km_str:
                            val = int(km_str)
                            if 1000 <= val <= 500000:
                                km = val
                    
                    # Année
                    annee = None
                    year_match = re.search(r"[-/](20[0-2]\d)\b", text)
                    if year_match:
                        annee = int(year_match.group(1))
                    
                    # Carburant
                    carburant = None
                    text_lower = text.lower()
                    if "diesel" in text_lower or "hdi" in text_lower or "dci" in text_lower or "tdi" in text_lower:
                        carburant = "Diesel"
                    elif "essence" in text_lower or "vti" in text_lower:
                        carburant = "Essence"
                    
                    annonces.append({
                        "url": full_url,
                        "source": "autoscout24",
                        "marque": marque.title(),
                        "modele": modele.title(),
                        "titre": titre,
                        "prix": prix,
                        "kilometrage": km,
                        "annee": annee,
                        "carburant": carburant,
                    })
                    
                except Exception:
                    continue
            
            print(f"✅ {len(annonces)}")
            
    except Exception as e:
        print(f"❌ {str(e)[:30]}")
    
    return annonces


async def main():
    print("=" * 60)
    print("🚗 SCRAPING AUTOSCOUT24 AVEC PROXIES FR")
    print("=" * 60)
    
    db = get_db()
    scorer = ScoringService()
    notifier = NotificationService()
    
    all_annonces = []
    
    # Scraper chaque recherche
    for rech in RECHERCHES:
        await asyncio.sleep(2)
        listings = await scrape_autoscout(rech["marque"], rech["modele"], rech["prix_max"])
        
        for data in listings:
            # Skip si déjà en base
            if db.exists(data["url"]):
                continue
            
            # Créer l'annonce
            annonce = Annonce(
                url=data["url"],
                source=data["source"],
                marque=data["marque"],
                modele=data["modele"],
                titre=data["titre"],
                prix=data["prix"],
                kilometrage=data["kilometrage"],
                annee=data["annee"],
                carburant=data["carburant"],
                type_vendeur="particulier",
                date_publication=datetime.now(),
            )
            
            # Scorer
            score, mots = scorer.calculer_score(annonce)
            
            # Sauvegarder
            db.save_annonce(annonce)
            all_annonces.append(annonce)
    
    # Trier par score
    all_annonces.sort(key=lambda a: a.score_rentabilite, reverse=True)
    
    # Afficher les résultats
    print("\n" + "=" * 60)
    print(f"📊 {len(all_annonces)} NOUVELLES ANNONCES")
    print("=" * 60)
    
    for i, a in enumerate(all_annonces[:20], 1):
        km_str = f"{a.kilometrage:,}km" if a.kilometrage else "?km"
        print(f"{i:2}. [{a.score_rentabilite:2}/100] {a.marque} {a.modele} | {a.prix or '?'}€ | {km_str} | {a.annee or '?'}")
    
    # Envoyer sur Discord les meilleures
    print("\n" + "=" * 60)
    print("📤 ENVOI SUR DISCORD")
    print("=" * 60)
    
    sent = 0
    for annonce in all_annonces[:15]:
        if annonce.score_rentabilite < 20:
            continue
        
        print(f"🔔 {annonce.marque} {annonce.modele} - {annonce.prix}€ - Score {annonce.score_rentabilite}")
        success = await notifier.send_discord(annonce)
        if success:
            print("   ✅ Envoyé!")
            db.mark_notified(annonce.id)
            sent += 1
        await asyncio.sleep(1)
    
    print(f"\n✅ {sent} notifications envoyées sur Discord!")


if __name__ == "__main__":
    asyncio.run(main())
