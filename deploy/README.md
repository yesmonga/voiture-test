# Déploiement Production

## Systemd (Linux)

```bash
# Créer le répertoire logs
mkdir -p /Users/alex/CascadeProjects/VOITURES/voitures-bot/logs

# Copier le service
sudo cp deploy/voitures-bot.service /etc/systemd/system/

# Recharger systemd
sudo systemctl daemon-reload

# Activer au démarrage
sudo systemctl enable voitures-bot

# Démarrer
sudo systemctl start voitures-bot

# Vérifier le statut
sudo systemctl status voitures-bot

# Voir les logs
journalctl -u voitures-bot -f
# ou
tail -f logs/bot.log
```

## macOS (launchd)

Pour macOS, utiliser launchd au lieu de systemd :

```bash
# Copier le plist
cp deploy/com.voitures-bot.plist ~/Library/LaunchAgents/

# Charger
launchctl load ~/Library/LaunchAgents/com.voitures-bot.plist

# Vérifier
launchctl list | grep voitures

# Décharger
launchctl unload ~/Library/LaunchAgents/com.voitures-bot.plist
```

## Cron (alternative simple)

```cron
# Éditer crontab
crontab -e

# Ajouter (toutes les 15 min)
*/15 * * * * cd /Users/alex/CascadeProjects/VOITURES/voitures-bot && ./venv/bin/python scripts/run_prod.py >> logs/cron.log 2>&1
```

## Dashboard Web

```bash
# Lancer le dashboard
python -m dashboard.app

# Ou avec uvicorn
uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

Accès: http://localhost:8000
