# 🚗 Voitures Bot - Production Ready (Multi-Sources)

Bot de détection d'opportunités de véhicules d'occasion, optimisé pour la stratégie **"flipping light"** : 
achat à bas prix → detailing + petites réparations → revente avec **500€+ de marge**.

## 🌐 Sources Supportées

| Source | Status | Notes |
|--------|--------|-------|
| **AutoScout24** | ✅ Production | Extraction __NEXT_DATA__ |
| **La Centrale** | ✅ Production | JSON + HTML fallback |
| **ParuVendu** | ✅ Production | HTML parsing |
| **LeBoncoin** | ⚠️ Skeleton | Anti-bot DataDome (nécessite Playwright) |
| **Marketplace** | ⚠️ Skeleton | Nécessite login Facebook |

## 🎯 Cible Principale

**Peugeot 207 1.4 HDi 70ch**
- Prix : 0 - 2000€
- Kilométrage : 150 000 - 180 000 km
- Année : 2006-2014
- France entière

*Moteur DV4 très fiable, pièces pas chères, forte demande sur le marché.*

## 🚀 Démarrage Rapide

### 1. Installation

```bash
cd voitures-bot

# Créer environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer dépendances
pip install -r requirements_v2.txt
```

### 2. Configuration

```bash
# Copier le fichier d'exemple
cp .env.example .env

# Éditer avec votre webhook Discord
nano .env
```

Contenu minimal de `.env` :
```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_ENABLED=true
```

### 3. Lancer les tests

```bash
# Tests unitaires
python3 -m pytest tests/ -q

# Smoke test E2E
PYTHONPATH=. python3 scripts/smoke_test.py
```

### 4. Lancer en production

```bash
# Run unique (dry-run, pas de notifs) - MULTI-SOURCES
PYTHONPATH=. python3 scripts/run_prod_v2.py --dry-run

# Run en boucle (toutes les 60s avec jitter)
PYTHONPATH=. python3 scripts/run_prod_v2.py --loop

# Run en boucle avec intervalle custom
PYTHONPATH=. python3 scripts/run_prod_v2.py --loop --interval 120
```

## 🐳 Docker

```bash
# Build
docker build -t voitures-bot .

# Run
docker run -d \
  --name voitures-bot \
  -e DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
  -v $(pwd)/data:/app/data \
  voitures-bot --loop
```

## 📁 Structure

```
voitures-bot/
├── config/
│   ├── searches.yaml      # Recherches multi-sources
│   ├── vehicles.yaml      # Véhicules cibles + scoring
│   └── keywords.yaml      # Mots-clés opportunité/risque
├── scrapers/
│   ├── autoscout24_v2.py  # ✅ AutoScout24 (__NEXT_DATA__)
│   ├── lacentrale_v1.py   # ✅ La Centrale (JSON + HTML)
│   ├── paruvendu_v1.py    # ✅ ParuVendu (HTML)
│   ├── leboncoin_v1.py    # ⚠️ Skeleton
│   ├── marketplace_v1.py  # ⚠️ Skeleton
│   └── rate_limiter.py    # Circuit breaker + rate limiting
├── services/
│   ├── orchestrator.py    # Pipeline 2 passes
│   ├── scoring_v2.py      # Scoring V3 avec marge
│   └── notifier/discord.py
├── scripts/
│   ├── run_prod_v2.py     # Runner multi-source
│   ├── smoke_test_multi.py # Test E2E multi-source
│   └── git_autopush.sh    # Commit après tests
├── tests/                  # 139 tests unitaires
└── data/
    └── annonces.db        # SQLite
```

## ⚙️ Configuration des Recherches (Multi-Sources)

Fichier `config/searches.yaml` :

```yaml
defaults:
  scan_interval_sec: 60    # Intervalle de base
  jitter_sec: 10           # ±10s aléatoire
  backoff_multiplier: 2    # x2 en cas de blocage
  backoff_max_sec: 300     # Max 5 min

searches:
  - name: "peugeot_207_14_hdi_70"
    enabled: true
    # MULTI-SOURCES: liste des sources à scanner
    sources:
      - autoscout24
      - lacentrale
      - paruvendu
    marque: "Peugeot"
    modele: "207"
    prix_min: 0
    prix_max: 2000
    km_min: 150000
    km_max: 180000
    carburant: "diesel"
    particulier_only: true
    detail_threshold: 30
    notify_threshold: 60
```

### Activer/Désactiver des sources

```yaml
# Une seule source
sources:
  - autoscout24

# Plusieurs sources
sources:
  - autoscout24
  - lacentrale
  - paruvendu

# Ancien format (compatibilité)
source: "autoscout24"
```

## 📊 Scoring (0-100)

| Critère | Points | Description |
|---------|--------|-------------|
| Prix | 35 | Plus c'est bas, mieux c'est |
| Kilométrage | 25 | 150k-170k = idéal |
| Mots-clés | 15 | "urgent", "négociable", "CT ok" |
| Fraîcheur | 10 | < 1h = bonus max |
| Bonus | 10 | Département, particulier, photos |
| Marge | 5 | Bonus si marge nette > 1000€ |

### Niveaux d'Alerte

| Score | Niveau | Notification |
|-------|--------|--------------|
| 80+ | 🔴 URGENT | ✅ Immédiate |
| 60-79 | 🟠 INTÉRESSANT | ✅ |
| 40-59 | 🟡 SURVEILLER | ❌ |
| < 40 | ⚪ ARCHIVE | ❌ |

## 🔑 Mots-clés

### Opportunités (bonus)
- `urgent`, `vente rapide`, `déménagement`
- `négociable`, `à débattre`, `faire offre`
- `CT ok`, `CT vierge`, `CT récent`
- `entretien suivi`, `carnet`, `factures`

### Risques (pénalité)
- `moteur HS`, `boîte HS` → **critique** (score ~0)
- `CT refusé`, `contre-visite` → -20 pts
- `CT à faire`, `sans CT` → -8 pts
- `à réparer`, `pour bricoleur` → -15 pts

### Exclusions (score = 0)
- `épave`, `non roulant`, `carcasse`
- `export`, `marchand`

## 🛡️ Anti-Blocage & Circuit Breaker

### Rate Limiting par source
| Source | Délai min | Jitter |
|--------|-----------|--------|
| AutoScout24 | 1.5s | ±0.5s |
| La Centrale | 2.0s | ±0.8s |
| ParuVendu | 1.5s | ±0.5s |
| LeBoncoin | 3.0s | ±1.0s |

### Circuit Breaker
- **3 échecs consécutifs** → source en pause
- **Backoff exponentiel** : 2min → 4min → 8min (max 10min)
- **Half-open** : test de reprise après timeout
- **Les autres sources continuent** pendant qu'une est bloquée

### Autres protections
- User-Agent rotation
- Jitter aléatoire ±10s
- Backoff automatique si 0 résultats

## 🔧 Commandes Utiles

```bash
# Tests (139 tests)
python3 -m pytest tests/ -q

# Smoke test mono-source
PYTHONPATH=. python3 scripts/smoke_test.py

# Smoke test MULTI-SOURCE
PYTHONPATH=. python3 scripts/smoke_test_multi.py

# Run multi-source
PYTHONPATH=. python3 scripts/run_prod_v2.py --dry-run
PYTHONPATH=. python3 scripts/run_prod_v2.py --loop

# Git autopush (après tests OK)
./scripts/git_autopush.sh "feat: description"
```

## ⚠️ Important

- **Ne JAMAIS commiter `.env`** (secrets)
- Respecter les CGU des sites
- Usage personnel uniquement

---

**Bon hunting ! 🚗💰**
