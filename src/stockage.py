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
    offre_id          TEXT NOT NULL REFERENCES offres(id),
    profil_hash       TEXT NOT NULL,
    score             INTEGER NOT NULL,  -- score global pondéré, calculé en Python
    score_technique   INTEGER NOT NULL,
    score_niveau      INTEGER NOT NULL,
    score_rythme      INTEGER NOT NULL,
    score_distance    INTEGER NOT NULL,
    justification     TEXT,
    points_forts      TEXT,  -- liste JSON
    points_vigilance  TEXT,  -- liste JSON
    date              TEXT NOT NULL,
    PRIMARY KEY (offre_id, profil_hash)
);

CREATE TABLE IF NOT EXISTS emails (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entreprise_id   TEXT NOT NULL REFERENCES entreprises(id),
    objet           TEXT NOT NULL,
    corps           TEXT NOT NULL,
    ce_que_fait     TEXT,  -- résumé de l'activité trouvé sur le web
    personnalise    INTEGER NOT NULL,  -- 0 si aucune information fiable trouvée
    sources         TEXT,  -- liste JSON d'URL
    date            TEXT NOT NULL
);
"""

COLONNES_JSON = {"codes_rome", "types_contrat", "points_forts", "points_vigilance", "sources"}


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


def offres_a_noter(connexion: sqlite3.Connection, profil_hash: str) -> list[sqlite3.Row]:
    """Offres vues lors de la dernière collecte et pas encore notées pour ce profil (cache)."""
    return connexion.execute(
        """
        SELECT o.* FROM offres o
        LEFT JOIN notations n ON n.offre_id = o.id AND n.profil_hash = ?
        WHERE n.offre_id IS NULL
          AND o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres)
        ORDER BY o.distance_km
        """,
        (profil_hash,),
    ).fetchall()


def enregistrer_notations(connexion: sqlite3.Connection, notations: list[dict]) -> None:
    if not notations:
        return
    colonnes = list(notations[0])
    requete = f"INSERT OR REPLACE INTO notations ({', '.join(colonnes)}) VALUES ({', '.join('?' for _ in colonnes)})"
    lignes = [
        [json.dumps(v, ensure_ascii=False) if c in COLONNES_JSON else v for c, v in notation.items()]
        for notation in notations
    ]
    with connexion:
        connexion.executemany(requete, lignes)


def classement(connexion: sqlite3.Connection, profil_hash: str) -> list[sqlite3.Row]:
    """Offres actives (dernière collecte) notées pour ce profil, de la meilleure à la moins bonne."""
    return connexion.execute(
        """
        SELECT o.titre, o.entreprise, o.adresse, o.distance_km, o.url_candidature, n.*
        FROM notations n JOIN offres o ON o.id = n.offre_id
        WHERE n.profil_hash = ? AND o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres)
        ORDER BY n.score DESC
        """,
        (profil_hash,),
    ).fetchall()


def chercher_entreprises(connexion: sqlite3.Connection, nom: str) -> list[sqlite3.Row]:
    return connexion.execute(
        "SELECT * FROM entreprises WHERE nom LIKE ? ORDER BY distance_km", (f"%{nom}%",)
    ).fetchall()


def enregistrer_email(connexion: sqlite3.Connection, email: dict) -> None:
    colonnes = list(email)
    valeurs = [json.dumps(v, ensure_ascii=False) if c in COLONNES_JSON else v for c, v in email.items()]
    with connexion:
        connexion.execute(
            f"INSERT INTO emails ({', '.join(colonnes)}) VALUES ({', '.join('?' for _ in colonnes)})", valeurs
        )


def derniere_collecte(connexion: sqlite3.Connection) -> str | None:
    return connexion.execute("SELECT MAX(derniere_vue) FROM offres").fetchone()[0]


def nombre_offres_actives(connexion: sqlite3.Connection) -> int:
    return connexion.execute(
        "SELECT COUNT(*) FROM offres WHERE derniere_vue = (SELECT MAX(derniere_vue) FROM offres)"
    ).fetchone()[0]


def lister_entreprises(connexion: sqlite3.Connection, avec_salaries: bool) -> list[sqlite3.Row]:
    """Entreprises de la dernière collecte, avec le nombre d'emails déjà générés pour chacune."""
    return connexion.execute(
        """
        SELECT e.*, COUNT(m.id) AS nb_emails
        FROM entreprises e LEFT JOIN emails m ON m.entreprise_id = e.id
        WHERE e.derniere_vue = (SELECT MAX(derniere_vue) FROM entreprises)
          AND (? = 0 OR COALESCE(e.taille, '') NOT IN ('', '0-0'))
        GROUP BY e.id
        ORDER BY e.distance_km
        """,
        (int(avec_salaries),),
    ).fetchall()


def emails_entreprise(connexion: sqlite3.Connection, entreprise_id: str) -> list[sqlite3.Row]:
    return connexion.execute(
        "SELECT * FROM emails WHERE entreprise_id = ? ORDER BY date DESC", (entreprise_id,)
    ).fetchall()
