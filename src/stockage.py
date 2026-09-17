"""Stockage local SQLite : offres, entreprises et cache des notations de Claude."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ALTERNANCE_DB permet d'utiliser une autre base (tests, démo) sans toucher aux vraies données
CHEMIN_BASE = Path(os.environ.get("ALTERNANCE_DB") or Path(__file__).resolve().parent.parent / "data" / "alternance.db")

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
    exclusion              TEXT,  -- raison de masquer l'offre (organisme de formation), NULL sinon
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
    exclusion       TEXT,
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
    note_linkedin   TEXT,  -- note d'invitation LinkedIn (300 caractères max)
    ce_que_fait     TEXT,  -- résumé de l'activité trouvé sur le web
    personnalise    INTEGER NOT NULL,  -- 0 si aucune information fiable trouvée
    site_web        TEXT,
    page_carrieres  TEXT,
    emails_publics  TEXT,  -- liste JSON : adresses publiées par l'entreprise, avec leur source
    sources         TEXT,  -- liste JSON d'URL
    date            TEXT NOT NULL
);

-- Suivi : une ligne par candidature envoyée (spontanée ou sur offre)
CREATE TABLE IF NOT EXISTS candidatures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entreprise_id   TEXT REFERENCES entreprises(id),
    offre_id        TEXT REFERENCES offres(id),
    email_id        INTEGER REFERENCES emails(id),
    nom             TEXT NOT NULL,  -- entreprise ou intitulé de l'offre
    destinataire    TEXT,           -- adresse, nom du contact LinkedIn...
    canal           TEXT NOT NULL,  -- email, linkedin, formulaire, offre
    statut          TEXT NOT NULL DEFAULT 'envoyée',  -- envoyée, relancée, entretien, refus, sans suite
    nb_relances     INTEGER NOT NULL DEFAULT 0,
    date_envoi      TEXT NOT NULL,
    derniere_action TEXT NOT NULL,  -- date du dernier envoi (candidature ou relance)
    notes           TEXT
);

-- Historique des exécutions automatiques (tâche planifiée ou ouverture de l'application)
CREATE TABLE IF NOT EXISTS executions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    date              TEXT NOT NULL,
    origine           TEXT NOT NULL,  -- planifiée, application
    nouvelles_offres  INTEGER,
    offres_notees     INTEGER,        -- NULL si la notation n'était pas prévue ce jour-là
    erreur            TEXT
);

-- Compétences absentes du CV sur lesquelles l'utilisateur s'est prononcé (avec preuve éventuelle)
CREATE TABLE IF NOT EXISTS competences_declarees (
    cle          TEXT PRIMARY KEY,  -- nom normalisé
    nom          TEXT NOT NULL,
    statut       TEXT NOT NULL,     -- confirmée (preuve jugée convaincante), déclarée (sans preuve convaincante), absente
    description  TEXT,
    lien         TEXT,
    verdict      TEXT,              -- avis de Claude sur la preuve
    resume_cv    TEXT,              -- formulation courte utilisable dans un CV
    date         TEXT NOT NULL
);

-- Compétences demandées par une offre et absentes du profil (cache de l'analyse)
CREATE TABLE IF NOT EXISTS analyses_offres (
    offre_id     TEXT NOT NULL,
    profil_hash  TEXT NOT NULL,
    competences  TEXT NOT NULL,     -- liste JSON
    date         TEXT NOT NULL,
    PRIMARY KEY (offre_id, profil_hash)
);

CREATE TABLE IF NOT EXISTS cv_adaptes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    offre_id     TEXT NOT NULL,
    chemin_pdf   TEXT NOT NULL,
    changements  TEXT NOT NULL,     -- liste JSON : avant, après, pourquoi
    alertes      TEXT NOT NULL,     -- liste JSON
    conseil      TEXT,
    date         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    candidature_id  INTEGER NOT NULL REFERENCES candidatures(id),
    objet           TEXT NOT NULL,
    corps           TEXT NOT NULL,
    date_redaction  TEXT NOT NULL,
    date_envoi      TEXT  -- NULL tant que la relance n'est pas envoyée
);
"""

# Ancienneté maximale d'une offre (date de publication) : au-delà, elle n'est ni notée ni affichée
AGE_MAX_JOURS = 14

COLONNES_JSON = {"codes_rome", "types_contrat", "points_forts", "points_vigilance", "sources", "emails_publics",
                 "competences", "changements", "alertes"}

# Relances : première à J+7 après l'envoi, seconde à J+7 après la première, puis on arrête
DELAI_RELANCE_JOURS = 7
MAX_RELANCES = 2
STATUTS_EN_COURS = ("envoyée", "relancée")


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connecter(chemin: Path = CHEMIN_BASE) -> sqlite3.Connection:
    """Ouvre la base (la crée si besoin) et s'assure que les tables existent."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    connexion = sqlite3.connect(chemin)
    connexion.row_factory = sqlite3.Row  # accès aux colonnes par nom : ligne["titre"]
    connexion.execute("PRAGMA foreign_keys = ON")
    connexion.executescript(SCHEMA)
    migrer(connexion)
    return connexion


# Colonnes ajoutées après la création de la base : (table, colonne, type)
COLONNES_AJOUTEES = [("offres", "exclusion", "TEXT"), ("entreprises", "exclusion", "TEXT")]


def migrer(connexion: sqlite3.Connection) -> None:
    """Ajoute aux bases existantes les colonnes apparues depuis (CREATE TABLE IF NOT EXISTS ne le fait pas)."""
    for table, colonne, type_sql in COLONNES_AJOUTEES:
        existantes = {ligne[1] for ligne in connexion.execute(f"PRAGMA table_info({table})")}
        if colonne not in existantes:
            connexion.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {type_sql}")
    connexion.commit()


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


def filtre_age(age_max_jours: int) -> tuple[str, str]:
    """Condition SQL « publiée depuis au plus N jours » (julianday comprend le format ISO de l'API) et son paramètre."""
    return "julianday(o.date_publication) >= julianday('now', ?)", f"-{min(age_max_jours, AGE_MAX_JOURS)} days"


def offres_a_noter(connexion: sqlite3.Connection, profil_hash: str) -> list[sqlite3.Row]:
    """Offres récentes de la dernière collecte, pas encore notées pour ce profil (cache)."""
    condition_age, age = filtre_age(AGE_MAX_JOURS)
    return connexion.execute(
        f"""
        SELECT o.* FROM offres o
        LEFT JOIN notations n ON n.offre_id = o.id AND n.profil_hash = ?
        WHERE n.offre_id IS NULL
          AND o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres)
          AND o.exclusion IS NULL
          AND {condition_age}
        ORDER BY o.distance_km
        """,
        (profil_hash, age),
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


def classement(connexion: sqlite3.Connection, profil_hash: str, age_max_jours: int = AGE_MAX_JOURS) -> list[sqlite3.Row]:
    """Offres actives et récentes notées pour ce profil, de la meilleure à la moins bonne."""
    condition_age, age = filtre_age(age_max_jours)
    return connexion.execute(
        f"""
        SELECT o.titre, o.entreprise, o.adresse, o.distance_km, o.url_candidature, o.date_publication, n.*
        FROM notations n JOIN offres o ON o.id = n.offre_id
        WHERE n.profil_hash = ? AND o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres)
          AND o.exclusion IS NULL
          AND {condition_age}
        ORDER BY n.score DESC
        """,
        (profil_hash, age),
    ).fetchall()


def chercher_entreprises(connexion: sqlite3.Connection, nom: str) -> list[sqlite3.Row]:
    return connexion.execute(
        "SELECT * FROM entreprises WHERE nom LIKE ? ORDER BY distance_km", (f"%{nom}%",)
    ).fetchall()


def inserer(connexion: sqlite3.Connection, table: str, ligne: dict) -> int:
    """Insère une ligne (listes converties en JSON) et renvoie son id."""
    colonnes = list(ligne)
    valeurs = [json.dumps(v, ensure_ascii=False) if c in COLONNES_JSON else v for c, v in ligne.items()]
    with connexion:
        curseur = connexion.execute(
            f"INSERT INTO {table} ({', '.join(colonnes)}) VALUES ({', '.join('?' for _ in colonnes)})", valeurs
        )
    return curseur.lastrowid


def enregistrer_email(connexion: sqlite3.Connection, email: dict) -> int:
    return inserer(connexion, "emails", email)


def derniere_collecte(connexion: sqlite3.Connection) -> str | None:
    return connexion.execute("SELECT MAX(derniere_vue) FROM offres").fetchone()[0]


def nombre_offres_actives(connexion: sqlite3.Connection, age_max_jours: int = AGE_MAX_JOURS) -> int:
    condition_age, age = filtre_age(age_max_jours)
    return connexion.execute(
        f"""SELECT COUNT(*) FROM offres o
            WHERE o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres) AND o.exclusion IS NULL AND {condition_age}""",
        (age,),
    ).fetchone()[0]


def offres_exclues(connexion: sqlite3.Connection, age_max_jours: int = AGE_MAX_JOURS) -> list[sqlite3.Row]:
    """Offres récentes masquées (organismes de formation), pour pouvoir vérifier le filtre."""
    condition_age, age = filtre_age(age_max_jours)
    return connexion.execute(
        f"""SELECT o.titre, o.entreprise, o.exclusion, o.url_candidature FROM offres o
            WHERE o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres) AND o.exclusion IS NOT NULL AND {condition_age}
            ORDER BY o.entreprise""",
        (age,),
    ).fetchall()


def lister_entreprises(connexion: sqlite3.Connection, avec_salaries: bool) -> list[sqlite3.Row]:
    """Entreprises de la dernière collecte, avec le nombre d'emails déjà générés pour chacune."""
    return connexion.execute(
        """
        SELECT e.*, COUNT(m.id) AS nb_emails
        FROM entreprises e LEFT JOIN emails m ON m.entreprise_id = e.id
        WHERE e.derniere_vue = (SELECT MAX(derniere_vue) FROM entreprises)
          AND e.exclusion IS NULL
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


# ---------------------------------------------------------------- Suivi des candidatures et relances

def enregistrer_candidature(connexion: sqlite3.Connection, candidature: dict) -> int:
    date = maintenant()
    return inserer(connexion, "candidatures", {**candidature, "date_envoi": date, "derniere_action": date})


def candidatures(connexion: sqlite3.Connection, entreprise_id: str | None = None, offre_id: str | None = None) -> list[sqlite3.Row]:
    """Toutes les candidatures (les plus récentes d'abord), éventuellement pour une entreprise ou une offre."""
    return connexion.execute(
        """
        SELECT * FROM candidatures
        WHERE (? IS NULL OR entreprise_id = ?) AND (? IS NULL OR offre_id = ?)
        ORDER BY date_envoi DESC
        """,
        (entreprise_id, entreprise_id, offre_id, offre_id),
    ).fetchall()


def candidatures_a_relancer(connexion: sqlite3.Connection) -> list[sqlite3.Row]:
    """Candidatures sans réponse dont la dernière action date d'au moins DELAI_RELANCE_JOURS jours."""
    return connexion.execute(
        f"""
        SELECT c.*, CAST(julianday('now') - julianday(c.derniere_action) AS INTEGER) AS jours_sans_reponse
        FROM candidatures c
        WHERE c.statut IN ({', '.join('?' for _ in STATUTS_EN_COURS)})
          AND c.nb_relances < ?
          AND julianday('now') - julianday(c.derniere_action) >= ?
        ORDER BY c.derniere_action
        """,
        (*STATUTS_EN_COURS, MAX_RELANCES, DELAI_RELANCE_JOURS),
    ).fetchall()


def changer_statut(connexion: sqlite3.Connection, candidature_id: int, statut: str) -> None:
    with connexion:
        connexion.execute("UPDATE candidatures SET statut = ? WHERE id = ?", (statut, candidature_id))


def relance_en_attente(connexion: sqlite3.Connection, candidature_id: int) -> sqlite3.Row | None:
    """Dernière relance rédigée mais pas encore envoyée pour cette candidature."""
    return connexion.execute(
        "SELECT * FROM relances WHERE candidature_id = ? AND date_envoi IS NULL ORDER BY id DESC LIMIT 1",
        (candidature_id,),
    ).fetchone()


def marquer_relance_envoyee(connexion: sqlite3.Connection, relance_id: int, candidature_id: int) -> None:
    date = maintenant()
    with connexion:  # les deux mises à jour ensemble, ou aucune
        connexion.execute("UPDATE relances SET date_envoi = ? WHERE id = ?", (date, relance_id))
        connexion.execute(
            "UPDATE candidatures SET nb_relances = nb_relances + 1, statut = 'relancée', derniere_action = ? WHERE id = ?",
            (date, candidature_id),
        )


def email_par_id(connexion: sqlite3.Connection, email_id: int | None) -> sqlite3.Row | None:
    if email_id is None:
        return None
    return connexion.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()


def offres_actives(connexion: sqlite3.Connection) -> list[sqlite3.Row]:
    """Offres de la dernière collecte (hors écoles), les mieux notées d'abord, quelle que soit leur ancienneté."""
    return connexion.execute(
        """
        SELECT o.id, o.titre, o.entreprise, MAX(n.score) AS score
        FROM offres o LEFT JOIN notations n ON n.offre_id = o.id
        WHERE o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres) AND o.exclusion IS NULL
        GROUP BY o.id ORDER BY score DESC
        """
    ).fetchall()


def entreprises_recherchees(connexion: sqlite3.Connection) -> list[sqlite3.Row]:
    """Entreprises sur lesquelles une recherche (email) a déjà été faite."""
    return connexion.execute(
        "SELECT DISTINCT e.id, e.nom FROM entreprises e JOIN emails m ON m.entreprise_id = e.id ORDER BY e.nom"
    ).fetchall()


# ---------------------------------------------------------------- Automatisation

def enregistrer_execution(connexion: sqlite3.Connection, execution: dict) -> int:
    return inserer(connexion, "executions", {"date": maintenant(), **execution})


def derniere_execution(connexion: sqlite3.Connection) -> sqlite3.Row | None:
    return connexion.execute("SELECT * FROM executions ORDER BY id DESC LIMIT 1").fetchone()


def derniere_notation(connexion: sqlite3.Connection) -> str | None:
    return connexion.execute("SELECT MAX(date) FROM notations").fetchone()[0]


def nouvelles_offres_visibles(connexion: sqlite3.Connection, date_collecte: str) -> int:
    """Offres apparues lors de cette collecte, hors écoles et CFA."""
    return connexion.execute(
        "SELECT COUNT(*) FROM offres WHERE premiere_vue = ? AND exclusion IS NULL", (date_collecte,)
    ).fetchone()[0]


# ---------------------------------------------------------------- Compétences déclarées et CV adaptés

def competences_declarees(connexion: sqlite3.Connection) -> list[sqlite3.Row]:
    return connexion.execute("SELECT * FROM competences_declarees ORDER BY nom").fetchall()


def declarer_competence(connexion: sqlite3.Connection, competence: dict) -> None:
    colonnes = list(competence) + ["date"]
    with connexion:
        connexion.execute(
            f"INSERT OR REPLACE INTO competences_declarees ({', '.join(colonnes)}) VALUES ({', '.join('?' for _ in colonnes)})",
            [*competence.values(), maintenant()],
        )


def analyse_offre(connexion: sqlite3.Connection, offre_id: str, profil_hash: str) -> list[dict] | None:
    ligne = connexion.execute(
        "SELECT competences FROM analyses_offres WHERE offre_id = ? AND profil_hash = ?", (offre_id, profil_hash)
    ).fetchone()
    return json.loads(ligne["competences"]) if ligne else None


def enregistrer_analyse(connexion: sqlite3.Connection, offre_id: str, profil_hash: str, competences: list[dict]) -> None:
    with connexion:
        connexion.execute(
            "INSERT OR REPLACE INTO analyses_offres (offre_id, profil_hash, competences, date) VALUES (?, ?, ?, ?)",
            (offre_id, profil_hash, json.dumps(competences, ensure_ascii=False), maintenant()),
        )


def cv_adaptes(connexion: sqlite3.Connection, offre_id: str) -> list[sqlite3.Row]:
    return connexion.execute("SELECT * FROM cv_adaptes WHERE offre_id = ? ORDER BY id DESC", (offre_id,)).fetchall()
