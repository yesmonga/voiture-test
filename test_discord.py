#!/usr/bin/env python3
"""Test Discord webhook notification"""

import asyncio
from datetime import datetime
from models.annonce import Annonce
from services.notifier import NotificationService

async def test_discord():
    """Envoie une notification de test sur Discord"""
    
    # Créer une annonce de test
    annonce_test = Annonce(
        url="https://www.leboncoin.fr/voitures/test123",
        source="leboncoin",
        marque="Peugeot",
        modele="207",
        version="1.4 HDi 70",
        motorisation="1.4 HDi 70ch",
        carburant="Diesel",
        annee=2010,
        kilometrage=165000,
        prix=2300,
        ville="Créteil",
        code_postal="94000",
        departement="94",
        telephone="06.XX.XX.XX.XX",
        type_vendeur="particulier",
        titre="Peugeot 207 1.4 HDi - Négociable",
        description="Vend 207 en bon état, ventilation hs, négociable, cause achat autre véhicule",
        images_urls=["https://images.unsplash.com/photo-1552519507-da3b142c6e3d?w=400"],
        score_rentabilite=85,
        mots_cles_detectes=["ventilation hs", "négociable", "cause achat autre"],
        vehicule_cible_id="peugeot_207_hdi",
        marge_estimee_min=1200,
        marge_estimee_max=1600,
        date_publication=datetime.now(),
    )
    
    # Tester le service de notification
    notifier = NotificationService()
    
    print("📊 Statut des notifications:")
    status = notifier.get_status()
    for canal, actif in status.items():
        emoji = "✅" if actif else "❌"
        print(f"  {emoji} {canal}: {'Actif' if actif else 'Inactif'}")
    
    if not status.get("discord"):
        print("\n❌ Discord non configuré! Vérifiez DISCORD_WEBHOOK_URL dans .env")
        return False
    
    print("\n🚀 Envoi notification Discord de test...")
    success = await notifier.send_discord(annonce_test)
    
    if success:
        print("✅ Notification Discord envoyée avec succès!")
        return True
    else:
        print("❌ Échec de l'envoi Discord")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_discord())
    exit(0 if result else 1)
