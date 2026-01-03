-- Schema SQL pour le bot voitures
-- Version 2.0 - Production grade

-- Table principale des annonces
CREATE TABLE IF NOT EXISTS annonces (
    -- Identifiants
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_listing_id TEXT,
    url TEXT NOT NULL,
    url_canonique TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    fingerprint_soft TEXT,  -- Pour near-duplicate detection
    
    -- Véhicule
    marque TEXT,
    modele TEXT,
    version TEXT,
    motorisation TEXT,
    carburant TEXT,
    boite TEXT,
    puissance_ch INTEGER,
    annee INTEGER,
    kilometrage INTEGER,
    prix INTEGER,
    
    -- Localisation
    ville TEXT,
    code_postal TEXT,
    departement TEXT,
    latitude REAL,
    longitude REAL,
    
    -- Vendeur
    seller_type TEXT DEFAULT 'unknown',
    seller_name TEXT,
    seller_phone TEXT,
    
    -- Contenu
    titre TEXT,
    description TEXT,
    images_urls TEXT,  -- JSON array
    
    -- Dates (ISO 8601 UTC)
    published_at TEXT,
    scraped_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    
    -- Scoring
    score_total INTEGER DEFAULT 0,
    score_breakdown TEXT,  -- JSON object
    vehicule_cible_id TEXT,
    
    -- Mots-clés
    keywords_opportunite TEXT,  -- JSON array
    keywords_risque TEXT,       -- JSON array
    
    -- Estimations
    margin_estimate_min INTEGER DEFAULT 0,
    margin_estimate_max INTEGER DEFAULT 0,
    repair_cost_estimate INTEGER DEFAULT 0,
    prix_marche_estime INTEGER,
    
    -- Alerte et statut
    alert_level TEXT DEFAULT 'archive',
    status TEXT DEFAULT 'nouveau',
    ignore_reason TEXT,
    
    -- Notifications
    notified INTEGER DEFAULT 0,
    notified_at TEXT,
    notify_channels TEXT  -- JSON array
);

-- Index pour recherches rapides
CREATE INDEX IF NOT EXISTS idx_annonces_fingerprint ON annonces(fingerprint);
CREATE INDEX IF NOT EXISTS idx_annonces_fingerprint_soft ON annonces(fingerprint_soft);
CREATE INDEX IF NOT EXISTS idx_annonces_source ON annonces(source);
CREATE UNIQUE INDEX IF NOT EXISTS idx_annonces_source_listing ON annonces(source, source_listing_id) WHERE source_listing_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_annonces_url_canonique ON annonces(url_canonique);
CREATE INDEX IF NOT EXISTS idx_annonces_score ON annonces(score_total DESC);
CREATE INDEX IF NOT EXISTS idx_annonces_alert_level ON annonces(alert_level);
CREATE INDEX IF NOT EXISTS idx_annonces_status ON annonces(status);
CREATE INDEX IF NOT EXISTS idx_annonces_created_at ON annonces(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_annonces_marque_modele ON annonces(marque, modele);
CREATE INDEX IF NOT EXISTS idx_annonces_departement ON annonces(departement);
CREATE INDEX IF NOT EXISTS idx_annonces_notified ON annonces(notified);

-- Index composite pour recherches fréquentes
CREATE INDEX IF NOT EXISTS idx_annonces_source_status ON annonces(source, status);
CREATE INDEX IF NOT EXISTS idx_annonces_vehicule_cible ON annonces(vehicule_cible_id, score_total DESC);

-- Table pour agrégats prix marché (estimation)
CREATE TABLE IF NOT EXISTS prix_marche_aggregats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicule_cible_id TEXT NOT NULL,
    annee_bucket TEXT NOT NULL,  -- ex: "2010-2012"
    km_bucket TEXT NOT NULL,     -- ex: "100000-150000"
    departement_bucket TEXT,     -- ex: "75" ou "idf" ou null (national)
    
    count INTEGER DEFAULT 0,
    prix_min INTEGER,
    prix_max INTEGER,
    prix_median INTEGER,
    prix_moyenne INTEGER,
    
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    
    UNIQUE(vehicule_cible_id, annee_bucket, km_bucket, departement_bucket)
);

CREATE INDEX IF NOT EXISTS idx_prix_marche_vehicule ON prix_marche_aggregats(vehicule_cible_id);

-- Table historique des scans (observabilité)
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT DEFAULT 'running',  -- running, success, error
    
    -- Métriques
    listings_found INTEGER DEFAULT 0,
    listings_new INTEGER DEFAULT 0,
    listings_updated INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    
    -- Détails
    error_message TEXT,
    duration_seconds REAL,
    
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_scan_history_source ON scan_history(source);
CREATE INDEX IF NOT EXISTS idx_scan_history_created ON scan_history(created_at DESC);

-- Table notifications envoyées (audit)
CREATE TABLE IF NOT EXISTS notification_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    annonce_id TEXT NOT NULL,
    channel TEXT NOT NULL,  -- discord, telegram, email, sms
    status TEXT NOT NULL,   -- sent, failed, skipped
    
    sent_at TEXT,
    error_message TEXT,
    
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    
    FOREIGN KEY (annonce_id) REFERENCES annonces(id)
);

CREATE INDEX IF NOT EXISTS idx_notif_history_annonce ON notification_history(annonce_id);
CREATE INDEX IF NOT EXISTS idx_notif_history_channel ON notification_history(channel);

-- Vue pour statistiques rapides
CREATE VIEW IF NOT EXISTS v_stats AS
SELECT
    COUNT(*) as total_annonces,
    COUNT(CASE WHEN status = 'nouveau' THEN 1 END) as nouveaux,
    COUNT(CASE WHEN alert_level = 'urgent' THEN 1 END) as urgents,
    COUNT(CASE WHEN alert_level = 'interessant' THEN 1 END) as interessants,
    COUNT(CASE WHEN notified = 1 THEN 1 END) as notifiees,
    AVG(score_total) as score_moyen,
    AVG(prix) as prix_moyen,
    AVG(kilometrage) as km_moyen
FROM annonces
WHERE status NOT IN ('ignore', 'exclue');

-- Vue pour stats par source
CREATE VIEW IF NOT EXISTS v_stats_par_source AS
SELECT
    source,
    COUNT(*) as total,
    COUNT(CASE WHEN DATE(created_at) = DATE('now') THEN 1 END) as aujourdhui,
    AVG(score_total) as score_moyen,
    MAX(score_total) as score_max
FROM annonces
GROUP BY source;
