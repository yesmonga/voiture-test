#!/bin/bash
# git_autopush.sh - Commit et push automatique après tests réussis
# Usage: ./scripts/git_autopush.sh "feat: description du commit"

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Vérifier le message de commit
if [ -z "$1" ]; then
    echo -e "${RED}❌ Erreur: Message de commit requis${NC}"
    echo "Usage: ./scripts/git_autopush.sh \"feat: description\""
    exit 1
fi

COMMIT_MSG="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=================================================="
echo "🔧 VOITURES BOT - Git Autopush"
echo "=================================================="
echo ""

# 1. Vérifier qu'on n'a pas de secrets exposés
echo -e "${YELLOW}🔍 Vérification des secrets...${NC}"

# Vérifier .env n'est pas staged
if git diff --cached --name-only | grep -q "^\.env"; then
    echo -e "${RED}❌ ERREUR: .env est staged! Ne jamais commiter de secrets.${NC}"
    exit 1
fi

# Vérifier pas de tokens dans les fichiers
if grep -r "DISCORD_WEBHOOK_URL=" --include="*.py" --include="*.yaml" --include="*.yml" . 2>/dev/null | grep -v ".env" | grep -v "os.getenv" | grep -v "get(" | head -1; then
    echo -e "${RED}❌ ERREUR: Possible secret hardcodé détecté!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Pas de secrets exposés${NC}"
echo ""

# 2. Lancer les tests
echo -e "${YELLOW}🧪 Exécution des tests...${NC}"

if ! python -m pytest tests/ -q --tb=short 2>&1; then
    echo -e "${RED}❌ Tests échoués! Commit annulé.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Tests passés${NC}"
echo ""

# 3. Lancer le smoke test
echo -e "${YELLOW}🔥 Smoke test...${NC}"

if ! python scripts/smoke_test.py 2>&1; then
    echo -e "${RED}❌ Smoke test échoué! Commit annulé.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Smoke test passé${NC}"
echo ""

# 4. Git add (seulement les fichiers trackés modifiés + nouveaux fichiers Python/YAML)
echo -e "${YELLOW}📦 Staging des modifications...${NC}"

git add -u  # Fichiers modifiés déjà trackés
git add "*.py" "*.yaml" "*.yml" "*.sh" "*.md" "*.txt" 2>/dev/null || true

# Vérifier qu'il y a des changements
if git diff --cached --quiet; then
    echo -e "${YELLOW}⚠️ Aucun changement à commiter${NC}"
    exit 0
fi

# Afficher les fichiers qui seront commités
echo "Fichiers à commiter:"
git diff --cached --name-only | head -20

echo ""

# 5. Commit
echo -e "${YELLOW}💾 Commit...${NC}"
git commit -m "$COMMIT_MSG"

echo -e "${GREEN}✅ Commit créé${NC}"
echo ""

# 6. Push
echo -e "${YELLOW}🚀 Push...${NC}"

# Vérifier si on a un remote configuré
if git remote -v | grep -q origin; then
    git push origin HEAD
    echo -e "${GREEN}✅ Push réussi${NC}"
else
    echo -e "${YELLOW}⚠️ Pas de remote 'origin' configuré, push ignoré${NC}"
fi

echo ""
echo "=================================================="
echo -e "${GREEN}🎉 Autopush terminé avec succès!${NC}"
echo "=================================================="
