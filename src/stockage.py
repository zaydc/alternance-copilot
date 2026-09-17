"""Stockage local SQLite : offres, entreprises et cache des notations de Claude."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

CHEMIN_BASE = Path(__file__).resolve().parent.parent / "data" / "alternance.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS offres (
    id                     TEXT PRIMARY KEY,
    source                 TEXT,
    titre                  TEXT NOT NULL,
    entreprise             TEXT,
    description_entreprise TEXT,
    adresse                TEXT,
    latitude               REAL,
    longitude              REAL,
    distance_km            REAL,
    description            TEXT,
    codes_rome             TEXT,  -- liste JSON
    niveau_diplome         TEXT,
    types_contrat          TEXT,  -- liste JSON
    debut_contrat          TEXT,
    duree_mois             INTEGER,
    teletravail            TEXT,
    date_publication       TEXT,
    date_expiration        TEXT,
    url_candidature        TEXT,
    premiere_vue           TEXT NOT NULL,
    derniere_vue           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entreprises (
    id              TEXT PRIMARY KEY,
    siret           TEXT,
    nom             TEXT,
    adresse         TEXT,
    latitude        REAL,
    longitude       REAL,
    distance_km     REAL,
    taille          TEXT,
    secteur         TEXT,
    telephone       TEXT,
    url_candidature TEXT,
    premiere_vue    TEXT NOT NULL,
    derniere_vue    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notations (
    offre_id      TEXT NOT NULL REFERENCES offres(id),
    profil_hash   TEXT NOT NULL,
    score         INTEGER NOT NULL,
    justification TEXT,
    date          TEXT NOT NULL,
    PRIMARY KEY (offre_id, profil_hash)
);
"""

COLONNES_JSON = {"codes_rome", "types_contrat"}


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connecter(chemin: Path = CHEMIN_BASE) -> sqlite3.Connection:
    """Ouvre la base (la crée si besoin) et s'assure que les tables existent."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    connexion = sqlite3.connect(chemin)
    connexion.row_factory = sqlite3.Row  # accès aux colonnes par nom : ligne["titre"]
    connexion.execute("PRAGMA foreign_keys = ON")
    connexion.executescript(SCHEMA)
    return connexion


def enregistrer(connexion: sqlite3.Connection, table: str, elements: list[dict], date_collecte: str) -> int:
    """Insère ou met à jour les éléments (upsert sur id). Renvoie le nombre de nouveaux éléments."""
    if not elements:
        return 0
    colonnes = list(elements[0]) + ["premiere_vue", "derniere_vue"]
    # Mise à jour de tout sauf id et premiere_vue : on garde la date de première apparition
    maj = ", ".join(f"{c} = excluded.{c}" for c in colonnes if c not in ("id", "premiere_vue"))
    requete = (
        f"INSERT INTO {table} ({', '.join(colonnes)}) "
        f"VALUES ({', '.join('?' for _ in colonnes)}) "
        f"ON CONFLICT(id) DO UPDATE SET {maj}"
    )
    lignes = [
        [json.dumps(v, ensure_ascii=False) if c in COLONNES_JSON else v for c, v in element.items()]
        + [date_collecte, date_collecte]
        for element in elements
    ]
    with connexion:  # transaction : tout est enregistré, ou rien en cas d'erreur
        connexion.executemany(requete, lignes)
    nouveaux = connexion.execute(f"SELECT COUNT(*) FROM {table} WHERE premiere_vue = ?", (date_collecte,))
    return nouveaux.fetchone()[0]
