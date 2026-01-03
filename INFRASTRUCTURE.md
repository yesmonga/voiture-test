# 🚗 BOT VOITURES - INFRASTRUCTURE COMPLÈTE

## 📁 Structure du Projet

```
voitures-bot/
│
├── 📄 main.py                    # Point d'entrée principal du bot
├── 📄 config.py                  # Configuration centralisée (véhicules, zones, seuils)
├── 📄 requirements.txt           # Dépendances Python
├── 📄 README.md                  # Documentation utilisateur
├── 📄 .env                       # Variables d'environnement (secrets)
├── 📄 .env.example               # Template des variables d'environnement
├── 📄 .gitignore                 # Fichiers ignorés par Git
│
├── 📂 scrapers/                  # Scrapers pour chaque site
│   ├── __init__.py
│   ├── base_scraper.py           # Classe de base pour tous les scrapers
│   ├── leboncoin.py              # Scraper LeBoncoin (httpx)
│   ├── leboncoin_playwright.py   # Scraper LeBoncoin (Playwright anti-bot)
│   ├── lacentrale.py             # Scraper LaCentrale
│   ├── paruvendu.py              # Scraper ParuVendu
│   └── autoscout.py              # Scraper AutoScout24 ✅ (fonctionne le mieux)
│
├── 📂 services/                  # Services métier
│   ├── __init__.py
│   ├── scorer.py                 # Système de scoring 0-100
│   ├── notifier.py               # Notifications multi-canaux
│   ├── deduplicator.py           # Déduplication des annonces
│   └── analyzer.py               # Analyse avancée (problèmes, mots-clés)
│
├── 📂 models/                    # Modèles de données
│   ├── __init__.py
│   ├── annonce.py                # Modèle Annonce (SQLAlchemy)
│   └── database.py               # Gestion base de données SQLite
│
├── 📂 utils/                     # Utilitaires
│   ├── __init__.py
│   ├── anti_bot.py               # Anti-détection (proxies, user-agents)
│   └── logger.py                 # Système de logs
│
├── 📂 data/                      # Données persistantes
│   └── annonces.db               # Base SQLite
│
├── 📂 logs/                      # Fichiers de logs
│   └── bot_YYYYMMDD.log
│
├── 📂 venv/                      # Environnement virtuel Python
│
└── 📄 Scripts de test/scraping
    ├── scan_all.py               # Scan complet LeBoncoin + AutoScout24
    ├── scrape_final.py           # Scraping rapide AutoScout24
    ├── scrape_now.py             # Scraping immédiat
    ├── test_discord.py           # Test notifications Discord
    └── test_full_pipeline.py     # Test pipeline complet
```

---

## 🔧 COMPOSANTS DÉTAILLÉS

### 1️⃣ `config.py` - Configuration Centralisée

**Rôle:** Contient TOUTE la configuration du bot.

```python
# Véhicules cibles avec critères
VEHICULES_CIBLES = {
    "peugeot_207_hdi": {
        "marque": "Peugeot",
        "modele": ["207"],
        "carburant": "diesel",
        "prix_min": 1500, "prix_max": 3000,
        "km_min": 80000, "km_max": 220000,
        "annee_min": 2006, "annee_max": 2014,
        "motorisation_exclude": ["sport", "gti", "rc"]
    },
    # ... autres véhicules
}

# Zones géographiques (Île-de-France prioritaire)
ZONES_PRIORITAIRES = ["75", "92", "93", "94", "77", "78", "91", "95"]

# Mots-clés opportunité (augmentent le score)
MOTS_CLES_OPPORTUNITE = ["urgent", "négociable", "en l'état", "à réparer", ...]

# Seuils d'alerte
SEUILS_ALERTE = {
    "urgent": 80,      # 🔴 Notification immédiate tous canaux
    "interessant": 60, # 🟠 Push + Discord
    "surveiller": 40,  # 🟡 Discord + Email
}
```

---

### 2️⃣ `models/annonce.py` - Modèle de Données

**Rôle:** Définit la structure d'une annonce.

```python
class Annonce:
    # Identifiants
    id: int
    url: str (unique)
    source: str  # leboncoin, autoscout24, lacentrale, paruvendu
    
    # Véhicule
    marque: str
    modele: str
    version: str
    carburant: str
    annee: int
    kilometrage: int
    prix: int
    
    # Localisation
    ville: str
    departement: str
    code_postal: str
    
    # Analyse
    score_rentabilite: int (0-100)
    niveau_alerte: str  # urgent/interessant/surveiller/archive
    mots_cles_detectes: List[str]
    marge_estimee_min: int
    marge_estimee_max: int
    
    # Statut
    notifie: bool
    date_creation: datetime
```

---

### 3️⃣ `models/database.py` - Base de Données

**Rôle:** Gère la persistance SQLite.

**Fonctions principales:**
- `save_annonce(annonce)` - Sauvegarde une annonce
- `exists(url)` - Vérifie si l'annonce existe déjà
- `get_annonces(limit, source, score_min)` - Récupère les annonces
- `mark_notified(id)` - Marque comme notifiée
- `get_stats()` - Statistiques globales

**Base:** `data/annonces.db` (SQLite)

---

### 4️⃣ `scrapers/base_scraper.py` - Scraper de Base

**Rôle:** Classe parente pour tous les scrapers.

**Fonctionnalités:**
- Gestion des sessions HTTP (httpx)
- Rotation des proxies
- Retry automatique (3 tentatives)
- Parsing HTML (BeautifulSoup)
- Méthodes utilitaires (clean_price, clean_km, etc.)

---

### 5️⃣ `scrapers/autoscout.py` - Scraper AutoScout24 ✅

**Rôle:** Scrape AutoScout24.fr (le plus fiable).

**Statut:** ✅ FONCTIONNE avec proxies résidentiels

**Méthode:**
1. Construit l'URL de recherche avec filtres
2. Récupère le HTML via httpx + proxy
3. Parse les articles avec BeautifulSoup
4. Extrait: titre, prix, km, année, carburant

---

### 6️⃣ `scrapers/leboncoin_playwright.py` - Scraper LeBoncoin

**Rôle:** Scrape LeBoncoin avec Playwright (navigateur headless).

**Statut:** ⚠️ Difficile (protection anti-bot forte)

**Méthode:**
1. Lance Chromium headless avec proxy
2. Navigue sur LeBoncoin
3. Accepte les cookies
4. Scroll pour charger le contenu
5. Parse le HTML

---

### 7️⃣ `services/scorer.py` - Système de Scoring

**Rôle:** Calcule un score de rentabilité 0-100.

**Algorithme:**
```
Score = Prix (40pts) + Km (30pts) + Mots-clés (20pts) + Fraîcheur (10pts)

BONUS:
+15 pts: "urgent", "négociable"
+10 pts: "en l'état", "à réparer"
+5 pts:  "faire offre", "départ"

MALUS:
-20 pts: professionnel (vs particulier)
-10 pts: hors zone prioritaire
```

**Niveaux:**
- 🔴 **URGENT** (≥80): Affaire exceptionnelle
- 🟠 **INTÉRESSANT** (≥60): Bonne opportunité
- 🟡 **À SURVEILLER** (≥40): Potentiel
- ⚪ **ARCHIVE** (<40): Standard

---

### 8️⃣ `services/notifier.py` - Notifications Multi-Canaux

**Rôle:** Envoie les alertes sur différents canaux.

**Canaux supportés:**
| Canal | Statut | Usage |
|-------|--------|-------|
| **Discord** | ✅ Actif | Webhook avec embeds riches |
| Telegram | Configuré | Bot API |
| Pushover | Configuré | Push notifications |
| SMS (Twilio) | Configuré | Alertes urgentes |
| Email | Configuré | Récapitulatifs |

**Format Discord:**
```
🔴 Peugeot 207 1.4 HDi - Score: 85/100
💰 Prix: 2,200€
🛣️ Km: 158,000 km
📅 Année: 2009
📍 Créteil (94)
💵 Marge potentielle: 900€ - 2,100€
🔑 Mots-clés: urgent, négociable
```

---

### 9️⃣ `services/deduplicator.py` - Déduplication

**Rôle:** Évite les doublons.

**Méthode:**
- Cache mémoire des URLs vues
- Vérification en base de données
- Hash du contenu pour détecter les republications

---

### 🔟 `services/analyzer.py` - Analyse Avancée

**Rôle:** Analyse approfondie des annonces.

**Fonctions:**
- Détection de problèmes (CT, panne, accident)
- Estimation des réparations
- Extraction des contacts (téléphone)
- Évaluation de la qualité de l'annonce

---

### 1️⃣1️⃣ `utils/anti_bot.py` - Anti-Détection

**Rôle:** Évite le blocage par les sites.

**Techniques:**
```python
# 20 Proxies résidentiels FR intégrés
RESIDENTIAL_PROXIES = [
    "http://user:pass@resi.thexyzstore.com:8000",
    # ... 19 autres
]

# Rotation User-Agents réalistes
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0...) Chrome/120.0...",
    # ... variations
]

# Headers HTTP réalistes
# Délais aléatoires entre requêtes
# Options Playwright anti-détection
```

---

### 1️⃣2️⃣ `utils/logger.py` - Système de Logs

**Rôle:** Journalisation des événements.

**Niveaux:** DEBUG, INFO, WARNING, ERROR
**Sortie:** Console (Rich) + Fichiers (`logs/bot_YYYYMMDD.log`)

---

### 1️⃣3️⃣ `main.py` - Point d'Entrée

**Rôle:** Orchestre tout le bot.

**Modes:**
```bash
python main.py           # Mode continu (scheduler)
python main.py --once    # Un seul cycle
python main.py --test    # Mode test (pas de notifications)
python main.py --stats   # Affiche les statistiques
```

**Cycle:**
1. Scrape chaque source (LeBoncoin, AutoScout24, etc.)
2. Déduplique les annonces
3. Score chaque annonce
4. Analyse les opportunités
5. Envoie les notifications
6. Sauvegarde en base

---

## 🔄 FLUX DE DONNÉES

```
┌─────────────────────────────────────────────────────────────────┐
│                        SOURCES WEB                              │
│  LeBoncoin | AutoScout24 | LaCentrale | ParuVendu              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         SCRAPERS                                │
│  • Proxies résidentiels FR (rotation)                          │
│  • User-Agents aléatoires                                       │
│  • Retry automatique                                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DÉDUPLICATION                              │
│  • Vérification URL en cache                                    │
│  • Vérification en base SQLite                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         SCORING                                 │
│  • Prix vs marché (40 pts)                                      │
│  • Kilométrage (30 pts)                                         │
│  • Mots-clés opportunité (20 pts)                               │
│  • Fraîcheur (10 pts)                                           │
│  → Score 0-100 + Niveau d'alerte                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BASE DE DONNÉES                              │
│  SQLite: data/annonces.db                                       │
│  • Historique complet                                           │
│  • Statistiques                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NOTIFICATIONS                              │
│  Score ≥80 → 🔴 Discord + Telegram + SMS                       │
│  Score ≥60 → 🟠 Discord + Telegram                             │
│  Score ≥40 → 🟡 Discord + Email                                │
│  Score <40 → ⚪ Archive seulement                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 CONFIGURATION ACTUELLE

### Véhicules Cibles
| Priorité | Véhicule | Prix Max | Km Max |
|----------|----------|----------|--------|
| 1 | Peugeot 207 HDi | 3000€ | 220k |
| 2 | Renault Clio III | 3000€ | 200k |
| 3 | Dacia Sandero | 3800€ | 180k |
| 3 | Renault Twingo II | 3200€ | 160k |
| 4 | Ford Fiesta | 4000€ | 180k |
| 4 | Toyota Yaris | 4000€ | 180k |

### Zones Prioritaires
- **Île-de-France:** 75, 92, 93, 94, 77, 78, 91, 95
- **Proximité:** 60, 02, 51, 10, 89, 45, 28, 27, 76, 80

### Discord Webhook
✅ **Actif:** Configuré avec ton webhook

---

## 🚀 COMMANDES UTILES

```bash
cd /Users/alex/CascadeProjects/VOITURES/voitures-bot
source venv/bin/activate

# Scan complet immédiat
python scan_all.py

# Scraping rapide AutoScout24
python scrape_final.py

# Mode continu (scheduler)
python main.py

# Test notifications Discord
python test_discord.py

# Voir les stats
python main.py --stats
```

---

## 📈 RÉSULTATS OBTENUS

| Métrique | Valeur |
|----------|--------|
| Annonces scrapées | 36+ |
| Envoyées sur Discord | 25+ |
| Meilleur score | 48/100 |
| Meilleur prix | 1990€ (Twingo) |

### Top Affaires Trouvées
1. **Renault Twingo - 1990€** (174k km) - Score 43
2. **Dacia Sandero - 2750€** (159k km) - Score 48
3. **VW Polo - 2490€** (175k km)
4. **Ford Focus - 2500€** (120k km)

---

## ⚠️ LIMITATIONS CONNUES

| Site | Statut | Raison |
|------|--------|--------|
| AutoScout24 | ✅ OK | Fonctionne avec proxies |
| LeBoncoin | ⚠️ Difficile | Protection anti-bot forte |
| LaCentrale | ❌ Bloqué | Cloudflare protection |
| ParuVendu | ⚠️ Variable | Structure HTML changeante |

---

## 🔐 SÉCURITÉ

- **Secrets** dans `.env` (jamais commité)
- **Proxies** dans `utils/anti_bot.py`
- **Base de données** locale (pas de cloud)
- **Logs** locaux avec rotation

---

*Documentation générée le 3 janvier 2026*
