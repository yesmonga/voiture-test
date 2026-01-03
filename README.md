# 🚗 Bot de Détection de Véhicules d'Occasion

Bot Python pour surveiller en temps réel les annonces de véhicules d'occasion sur les principales plateformes françaises et recevoir des **notifications instantanées** pour les meilleures opportunités.

## 🎯 Objectif

Être le **PREMIER** à contacter le vendeur pour maximiser les chances d'achat et réaliser une marge de **500€ à 1000€** par véhicule.

## ✨ Fonctionnalités

- 🔍 **Scraping multi-plateformes** : LeBoncoin, LaCentrale, ParuVendu, AutoScout24
- 📊 **Scoring intelligent** : Calcul automatique de la rentabilité (0-100)
- 📱 **Notifications multi-canaux** : Telegram, Pushover, SMS (Twilio), Email
- 🎯 **Critères personnalisés** : 7 modèles de véhicules cibles préconfigurés
- 🛡️ **Anti-détection** : Rotation User-Agent, délais aléatoires, gestion des sessions
- 💾 **Base de données** : Historique complet des annonces (SQLite)
- 📈 **Analyse avancée** : Détection des mots-clés opportunité, estimation des coûts de réparation

## 🚙 Véhicules Cibles

| Modèle | Priorité | Prix Cible | Kilométrage | Marge Estimée |
|--------|----------|------------|-------------|---------------|
| Peugeot 207 1.4 HDi | ⭐⭐⭐ | 2000-3000€ | 140k-220k km | 800-1500€ |
| Renault Clio III dCi | ⭐⭐ | 2000-3000€ | 120k-200k km | 700-1300€ |
| Renault Clio III 1.2 | ⭐⭐ | 2000-3200€ | 100k-180k km | 600-1200€ |
| Dacia Sandero | ⭐⭐ | 2500-3800€ | 100k-180k km | 700-1200€ |
| Renault Twingo II | ⭐ | 2000-3200€ | 80k-160k km | 600-1100€ |
| Ford Fiesta VI | ⭐ | 2800-4000€ | 100k-180k km | 600-1000€ |
| Toyota Yaris II | ⭐ | 2800-4000€ | 100k-180k km | 600-1000€ |

## 📍 Zones Géographiques

**Zone prioritaire** : Île-de-France (75, 77, 78, 91, 92, 93, 94, 95)
**Zone secondaire** : Hauts-de-France (02, 59, 60, 62, 80)

## 🚀 Installation

### Prérequis

- Python 3.11+
- pip

### Étapes

```bash
# 1. Cloner ou copier le projet
cd voitures-bot

# 2. Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Installer Playwright
playwright install chromium

# 5. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés API
```

## ⚙️ Configuration

### Fichier `.env`

```env
# Telegram (Recommandé)
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id

# Pushover (Optionnel)
PUSHOVER_USER_KEY=votre_user_key
PUSHOVER_API_TOKEN=votre_api_token

# SMS Twilio (Optionnel - alertes urgentes)
TWILIO_SID=votre_sid
TWILIO_AUTH_TOKEN=votre_auth_token
TWILIO_PHONE_FROM=+1234567890
PHONE_TO=+33612345678

# Email (Optionnel)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=votre_email@gmail.com
SMTP_PASSWORD=votre_app_password
EMAIL_TO=votre_email@gmail.com
```

### Créer un bot Telegram

1. Parler à [@BotFather](https://t.me/BotFather) sur Telegram
2. Envoyer `/newbot` et suivre les instructions
3. Copier le token dans `TELEGRAM_BOT_TOKEN`
4. Parler à votre bot, puis aller sur `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Copier votre `chat_id` dans `TELEGRAM_CHAT_ID`

## 📖 Utilisation

### Mode continu (recommandé)

```bash
python main.py
```

Le bot va :
- Scraper LeBoncoin toutes les 2 minutes
- Scraper LaCentrale toutes les 3 minutes
- Scraper ParuVendu toutes les 5 minutes
- Scraper AutoScout24 toutes les 10 minutes

### Exécution unique

```bash
python main.py --once
```

### Mode test (sans notifications)

```bash
python main.py --test
```

### Scraper une source spécifique

```bash
python main.py --source leboncoin
```

### Afficher les statistiques

```bash
python main.py --stats
```

## 📊 Système de Scoring

Le score de rentabilité est calculé sur 100 points :

| Critère | Points Max |
|---------|------------|
| Prix | 40 |
| Kilométrage | 30 |
| Mots-clés opportunité | 20 |
| Fraîcheur annonce | 10 |

### Niveaux d'Alerte

| Score | Niveau | Action |
|-------|--------|--------|
| 80-100 | 🔴 URGENT | Push + SMS + Email |
| 60-79 | 🟠 INTÉRESSANT | Push + Email |
| 40-59 | 🟡 À SURVEILLER | Email |
| < 40 | ⚪ ARCHIVE | Stockage uniquement |

## 🔑 Mots-clés Opportunité

Le bot détecte automatiquement ces mots-clés qui indiquent une opportunité de négociation :

- "à réparer", "en l'état", "bricoleur"
- "voyant", "panne", "défaut"
- "urgent", "négociable", "faire offre"
- "ct à faire", "distribution à faire"
- etc.

## 📁 Structure du Projet

```
voitures-bot/
├── main.py                 # Point d'entrée
├── config.py               # Configuration
├── requirements.txt        # Dépendances
├── .env                    # Variables d'environnement
│
├── scrapers/
│   ├── base_scraper.py     # Classe abstraite
│   ├── leboncoin.py        # LeBoncoin
│   ├── lacentrale.py       # LaCentrale
│   ├── paruvendu.py        # ParuVendu
│   └── autoscout.py        # AutoScout24
│
├── models/
│   ├── annonce.py          # Modèle Annonce
│   └── database.py         # SQLite
│
├── services/
│   ├── scorer.py           # Scoring
│   ├── notifier.py         # Notifications
│   ├── deduplicator.py     # Déduplication
│   └── analyzer.py         # Analyse
│
├── utils/
│   ├── anti_bot.py         # Anti-détection
│   └── logger.py           # Logging
│
├── data/
│   └── annonces.db         # Base SQLite
│
└── logs/
    └── bot_YYYYMMDD.log    # Logs quotidiens
```

## 🛡️ Anti-Détection

Le bot implémente plusieurs techniques pour éviter d'être bloqué :

- **Rotation User-Agent** : Différents navigateurs simulés
- **Délais aléatoires** : 1.5-3s entre chaque requête
- **Rate limiting** : Respect des limites par site
- **Sessions persistantes** : Cookies gérés automatiquement

### Limites Recommandées

| Site | Requêtes/heure | Intervalle Min |
|------|----------------|----------------|
| LeBoncoin | 30 | 2 min |
| LaCentrale | 40 | 1.5 min |
| ParuVendu | 60 | 1 min |
| AutoScout24 | 30 | 2 min |

## 📱 Format des Notifications

```
🚗 ALERTE VÉHICULE - Score: 85/100 🔴

📌 PEUGEOT 207 1.4 HDi 70
💰 Prix: 2 300€
📍 Lieu: Créteil (94)
🛣️ Km: 165 000 km
📅 Année: 2010
⏱️ Publié il y a: 3 minutes

🔑 Mots-clés: "ventilation hs", "négociable"

🔗 https://leboncoin.fr/...

💵 Marge potentielle: 1 200€ - 1 600€
```

## 🔧 Personnalisation

### Ajouter un nouveau véhicule cible

Éditer `config.py` et ajouter une entrée dans `VEHICULES_CIBLES` :

```python
"nouveau_vehicule": {
    "marque": "Marque",
    "modele": ["Modele1", "Modele2"],
    "motorisation_include": ["1.6", "2.0"],
    "motorisation_exclude": ["sport", "rs"],
    "carburant": "essence",
    "km_min": 100000,
    "km_max": 200000,
    "prix_min": 2000,
    "prix_max": 4000,
    "annee_min": 2010,
    "annee_max": 2020,
    "priorite": 2,
}
```

### Modifier les intervalles de scraping

Éditer `SCRAPING_INTERVALS` dans `config.py` :

```python
SCRAPING_INTERVALS = {
    "leboncoin": 120,      # 2 minutes
    "lacentrale": 180,     # 3 minutes
    ...
}
```

## ⚠️ Avertissements

- **Usage personnel uniquement**
- Respecter les CGU des sites scrapés
- Ne pas surcharger les serveurs
- Ne pas stocker de données personnelles inutilement

## 📈 Métriques de Succès

| Métrique | Objectif |
|----------|----------|
| Temps de détection | < 5 min |
| Précision scoring | > 80% |
| Temps de contact | < 15 min |
| Véhicules/mois | 2-4 |
| Marge moyenne | 700€+ |

## 🐛 Dépannage

### Le bot ne trouve pas d'annonces

1. Vérifier la connexion Internet
2. Vérifier que les critères ne sont pas trop restrictifs
3. Augmenter les intervalles de scraping (anti-bot)

### Notifications non reçues

1. Vérifier les tokens dans `.env`
2. Tester avec `python main.py --test --once`
3. Vérifier les logs dans `logs/`

### Erreur "blocked" ou "captcha"

1. Augmenter les délais dans `config.py`
2. Utiliser un proxy (optionnel)
3. Attendre quelques heures avant de relancer

## 📄 Licence

Usage personnel uniquement. Non destiné à un usage commercial.

---

**Bon hunting ! 🚗💰**
