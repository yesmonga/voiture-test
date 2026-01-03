#!/usr/bin/env python3
"""
Test complet du pipeline: Scraping -> Scoring -> Base de données -> Discord
"""

import asyncio
from datetime import datetime

from models.annonce import Annonce
from models.database import get_db
from services.scorer import ScoringService
from services.notifier import NotificationService
from services.deduplicator import DeduplicationService


async def test_pipeline():
    """Test le pipeline complet avec des annonces simulées réalistes"""
    
    print("=" * 60)
    print("🚗 TEST PIPELINE COMPLET")
    print("=" * 60)
    
    db = get_db()
    scorer = ScoringService()
    notifier = NotificationService()
    dedup = DeduplicationService()
    
    # Simuler des annonces réalistes trouvées par scraping
    annonces_test = [
        Annonce(
            url="https://www.leboncoin.fr/voitures/2500001.htm",
            source="leboncoin",
            marque="Peugeot",
            modele="207",
            version="1.4 HDi 70",
            motorisation="1.4 HDi",
            carburant="Diesel",
            annee=2009,
            kilometrage=158000,
            prix=2200,
            ville="Créteil",
            code_postal="94000",
            departement="94",
            type_vendeur="particulier",
            titre="Peugeot 207 1.4 HDi 70 - Négociable urgent",
            description="Vend 207 diesel, ventilation hs, ct ok, négociable cause déménagement",
            date_publication=datetime.now(),
        ),
        Annonce(
            url="https://www.leboncoin.fr/voitures/2500002.htm",
            source="leboncoin",
            marque="Renault",
            modele="Clio III",
            version="1.5 dCi 85",
            motorisation="1.5 dCi",
            carburant="Diesel",
            annee=2008,
            kilometrage=142000,
            prix=2500,
            ville="Montreuil",
            code_postal="93100",
            departement="93",
            type_vendeur="particulier",
            titre="Clio 3 dCi 85ch - Petit prix",
            description="Clio diesel 85ch, distribution faite, faire offre",
            date_publication=datetime.now(),
        ),
        Annonce(
            url="https://www.leboncoin.fr/voitures/2500003.htm",
            source="lacentrale",
            marque="Dacia",
            modele="Sandero Stepway",
            version="1.5 dCi",
            motorisation="1.5 dCi",
            carburant="Diesel",
            annee=2011,
            kilometrage=125000,
            prix=3200,
            ville="Meaux",
            code_postal="77100",
            departement="77",
            type_vendeur="particulier",
            titre="Sandero Stepway dCi - Affaire à saisir",
            description="Stepway en bon état, ct ok, à saisir rapidement",
            date_publication=datetime.now(),
        ),
    ]
    
    print(f"\n📥 {len(annonces_test)} annonces à traiter\n")
    
    # Traiter chaque annonce
    annonces_a_notifier = []
    
    for annonce in annonces_test:
        # 1. Déduplication
        if not dedup.est_nouvelle(annonce):
            print(f"⏭️  Doublon ignoré: {annonce.titre}")
            continue
        
        # 2. Scoring
        score, mots_cles = scorer.calculer_score(annonce)
        print(f"📊 Score {score}/100: {annonce.marque} {annonce.modele} - {annonce.prix}€")
        print(f"   Mots-clés: {', '.join(mots_cles) if mots_cles else 'Aucun'}")
        print(f"   Marge estimée: {annonce.marge_estimee_min}€ - {annonce.marge_estimee_max}€")
        print(f"   Niveau: {annonce.emoji_alerte} {annonce.niveau_alerte.upper()}")
        
        # 3. Sauvegarde en base
        is_new = db.save_annonce(annonce)
        print(f"   💾 Sauvegardé: {'Nouveau' if is_new else 'Mis à jour'}")
        
        # 4. Ajouter à la liste des notifications
        if score >= 40:
            annonces_a_notifier.append(annonce)
        
        print()
    
    # 5. Envoyer les notifications Discord
    print("=" * 60)
    print(f"📤 ENVOI NOTIFICATIONS DISCORD ({len(annonces_a_notifier)} annonces)")
    print("=" * 60)
    
    for annonce in annonces_a_notifier:
        print(f"\n🔔 Notification: {annonce.marque} {annonce.modele} - Score {annonce.score_rentabilite}")
        success = await notifier.send_discord(annonce)
        if success:
            print("   ✅ Envoyé sur Discord!")
            db.mark_notified(annonce.id)
        else:
            print("   ❌ Échec envoi Discord")
    
    # 6. Afficher les stats
    print("\n" + "=" * 60)
    print("📈 STATISTIQUES")
    print("=" * 60)
    stats = db.get_stats()
    print(f"Total en base: {stats['total']}")
    print(f"🔴 Urgent: {stats['par_score']['urgent']}")
    print(f"🟠 Intéressant: {stats['par_score']['interessant']}")
    print(f"🟡 À surveiller: {stats['par_score']['surveiller']}")
    print(f"⚪ Archive: {stats['par_score']['archive']}")
    
    print("\n✅ Test terminé! Vérifie Discord pour les notifications.")
    return True


if __name__ == "__main__":
    asyncio.run(test_pipeline())
