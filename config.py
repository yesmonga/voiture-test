"""
Configuration du Bot de Détection de Véhicules d'Occasion
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ===========================================
# VÉHICULES CIBLES
# ===========================================

VEHICULES_CIBLES = {
    "peugeot_207_hdi": {
        "marque": "Peugeot",
        "modele": ["207"],
        "motorisation_include": ["1.4 hdi", "1.4hdi", "hdi 70", "hdi 68", "1.4 hdi 70", "1.4 hdi 68"],
        "motorisation_exclude": ["1.6 hdi", "vti", "thp", "1.6hdi 110", "1.6 hdi 110", "hdi 90", "hdi 110", "hdi 112"],
        "carburant": "diesel",
        "km_min": 140000,
        "km_max": 220000,
        "km_ideal_min": 140000,
        "km_ideal_max": 180000,
        "prix_min": 1500,
        "prix_max": 3000,
        "prix_ideal_max": 2500,
        "annee_min": 2006,
        "annee_max": 2014,
        "priorite": 1,
        "marge_estimee": {"min": 800, "max": 1500},
        "prix_revente": {"min": 3500, "max": 4500}
    },
    "renault_clio3_dci": {
        "marque": "Renault",
        "modele": ["Clio", "Clio III", "Clio 3"],
        "motorisation_include": ["1.5 dci", "1.5dci", "dci 85", "dci 90", "dci85", "dci90"],
        "motorisation_exclude": ["dci 105", "dci 110", "dci105", "dci110", "rs", "sport"],
        "carburant": "diesel",
        "km_min": 120000,
        "km_max": 200000,
        "km_ideal_min": 120000,
        "km_ideal_max": 160000,
        "prix_min": 2000,
        "prix_max": 3000,
        "prix_ideal_max": 2500,
        "annee_min": 2005,
        "annee_max": 2012,
        "priorite": 2,
        "marge_estimee": {"min": 700, "max": 1300},
        "prix_revente": {"min": 3800, "max": 4800},
        "note": "Priorité: versions sans FAP (avant 2010)"
    },
    "renault_clio3_essence": {
        "marque": "Renault",
        "modele": ["Clio", "Clio III", "Clio 3"],
        "motorisation_include": ["1.2 16v", "1.2 16", "1.2", "75ch", "75 ch"],
        "motorisation_exclude": ["tce", "rs", "sport", "gordini", "dci"],
        "carburant": "essence",
        "km_min": 100000,
        "km_max": 180000,
        "km_ideal_min": 100000,
        "km_ideal_max": 140000,
        "prix_min": 2000,
        "prix_max": 3200,
        "prix_ideal_max": 2800,
        "annee_min": 2005,
        "annee_max": 2012,
        "priorite": 2,
        "marge_estimee": {"min": 600, "max": 1200},
        "prix_revente": {"min": 3500, "max": 4500}
    },
    "dacia_sandero": {
        "marque": "Dacia",
        "modele": ["Sandero", "Sandero Stepway"],
        "motorisation_include": ["1.4 mpi", "1.5 dci", "1.4", "1.5", "mpi", "75ch"],
        "motorisation_exclude": ["gpl", "bicarburation", "bioéthanol", "e85"],
        "carburant": None,  # Diesel ou essence acceptés
        "km_min": 100000,
        "km_max": 180000,
        "km_ideal_min": 100000,
        "km_ideal_max": 140000,
        "prix_min": 2500,
        "prix_max": 3800,
        "prix_ideal_max": 3200,
        "annee_min": 2008,
        "annee_max": 2012,
        "priorite": 3,
        "marge_estimee": {"min": 700, "max": 1200},
        "prix_revente": {"min": 4000, "max": 5000},
        "bonus_stepway": 500,  # Alerte spéciale si Stepway au prix Sandero
        "note": "ALERTE si Stepway au prix Sandero = +500€ revente"
    },
    "renault_twingo2": {
        "marque": "Renault",
        "modele": ["Twingo", "Twingo II", "Twingo 2"],
        "motorisation_include": ["1.2 16v", "1.2 lev", "1.5 dci", "75ch", "75 ch", "1.2 16"],
        "motorisation_exclude": ["rs", "gordini", "sport"],
        "carburant": None,
        "km_min": 80000,
        "km_max": 160000,
        "km_ideal_min": 80000,
        "km_ideal_max": 120000,
        "prix_min": 2000,
        "prix_max": 3200,
        "prix_ideal_max": 2800,
        "annee_min": 2007,
        "annee_max": 2014,
        "priorite": 3,
        "marge_estimee": {"min": 600, "max": 1100},
        "prix_revente": {"min": 3400, "max": 4500},
        "note": "Priorité: Phase 2 (après 2012) au prix Phase 1"
    },
    "ford_fiesta6": {
        "marque": "Ford",
        "modele": ["Fiesta", "Fiesta VI", "Fiesta 6"],
        "motorisation_include": ["1.25", "duratec", "1.4 tdci", "60ch", "82ch", "1.25 duratec"],
        "motorisation_exclude": ["ecoboost", "1.0", "st", "sport", "rs"],
        "carburant": None,
        "km_min": 100000,
        "km_max": 180000,
        "km_ideal_min": 100000,
        "km_ideal_max": 140000,
        "prix_min": 2800,
        "prix_max": 4000,
        "prix_ideal_max": 3500,
        "annee_min": 2008,
        "annee_max": 2017,
        "priorite": 4,
        "marge_estimee": {"min": 600, "max": 1000},
        "prix_revente": {"min": 4200, "max": 5200},
        "note": "EXCLURE moteur 1.0 Ecoboost (courroie humide)"
    },
    "toyota_yaris2": {
        "marque": "Toyota",
        "modele": ["Yaris", "Yaris II", "Yaris 2"],
        "motorisation_include": ["1.3 vvti", "1.3", "vvt-i", "vvti", "1.3 vvt"],
        "motorisation_exclude": ["hybride", "d4d", "d-4d", "hybrid"],
        "carburant": "essence",
        "km_min": 100000,
        "km_max": 180000,
        "km_ideal_min": 100000,
        "km_ideal_max": 140000,
        "prix_min": 2800,
        "prix_max": 4000,
        "prix_ideal_max": 3500,
        "annee_min": 2005,
        "annee_max": 2011,
        "priorite": 4,
        "marge_estimee": {"min": 600, "max": 1000},
        "prix_revente": {"min": 4200, "max": 5200}
    }
}

# ===========================================
# ZONES GÉOGRAPHIQUES
# ===========================================

DEPARTEMENTS_PRIORITAIRES = ["93", "94", "77", "91", "78", "95", "75"]
DEPARTEMENTS_SECONDAIRES = ["60", "02", "80", "59", "62"]
TOUS_DEPARTEMENTS = DEPARTEMENTS_PRIORITAIRES + DEPARTEMENTS_SECONDAIRES

REGIONS = {
    "ile_de_france": ["75", "77", "78", "91", "92", "93", "94", "95"],
    "hauts_de_france": ["02", "59", "60", "62", "80"]
}

RAYON_RECHERCHE_KM = 150  # km autour de Paris

# ===========================================
# MOTS-CLÉS OPPORTUNITÉ
# ===========================================

MOTS_CLES_OPPORTUNITE = [
    # État / Réparations
    "à réparer", "en l'état", "dans l'état", "vend en l'état",
    "pour bricoleur", "petit bricoleur", "bricolage",
    
    # Problèmes mécaniques
    "voyant allumé", "voyant moteur", "voyant orange", "voyant",
    "problème", "panne", "défaut",
    "perte puissance", "perte de puissance", "manque de puissance",
    "fume", "fume noir", "fumée",
    "pollution", "contre-visite pollution", "anti-pollution",
    
    # Équipements HS
    "chauffage hs", "ventilation hs", "clim hs",
    "vitre bloquée", "lève vitre", "vitre hs",
    
    # Entretien à faire
    "embrayage mou", "embrayage à faire",
    "distribution à faire", "courroie à faire",
    "ct à faire", "contrôle technique à faire",
    
    # Démarrage
    "moteur tourne mais", "démarre mais",
    
    # Prix négociable
    "urgent", "vente urgente", "départ",
    "faire offre", "prix à débattre", "négociable",
    "cause décès", "cause déménagement", "cause achat autre",
    
    # Autres opportunités
    "petit prix", "à saisir", "affaire", "occasion à saisir"
]

MOTS_CLES_EXCLUSION = [
    "accident", "accidenté", "accidentée",
    "epave", "épave", "pour pièces", "pour pieces",
    "non roulant", "non roulante", "ne roule pas",
    "export", "exportation",
    "professionnel", "garage", "concessionnaire"
]

# ===========================================
# INTERVALLES DE SCRAPING (secondes)
# ===========================================

SCRAPING_INTERVALS = {
    "leboncoin": 120,      # 2 minutes
    "lacentrale": 180,     # 3 minutes
    "paruvendu": 300,      # 5 minutes
    "autoscout24": 600,    # 10 minutes
}

# ===========================================
# SCORING
# ===========================================

SEUILS_ALERTE = {
    "urgent": 80,       # 🔴 Score >= 80: Notification push + SMS
    "interessant": 60,  # 🟠 Score >= 60: Notification push + Email
    "surveiller": 40,   # 🟡 Score >= 40: Email récapitulatif
    "archive": 0        # ⚪ Score < 40: Stockage uniquement
}

# ===========================================
# NOTIFICATIONS
# ===========================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_FROM = os.getenv("TWILIO_PHONE_FROM")
PHONE_TO = os.getenv("PHONE_TO")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

# Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# ===========================================
# BASE DE DONNÉES
# ===========================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/annonces.db")

# ===========================================
# ANTI-BOT
# ===========================================

PROXY_URL = os.getenv("PROXY_URL")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")

REQUEST_TIMEOUT = 30  # secondes
MAX_RETRIES = 3
RETRY_DELAY = 5  # secondes

# ===========================================
# DEBUG
# ===========================================

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
