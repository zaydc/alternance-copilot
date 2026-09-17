"""Assistant conversationnel : coach de candidature et simulation d'entretien.

C'est un agent : Claude décide lui-même d'appeler les outils ci-dessous (données locales, en lecture seule)
ou la recherche web pour répondre.
"""

import json
from contextlib import closing

from src import stockage
from src.llm_client import OutilPerso, discuter
from src.profil import profil_en_cache

MAX_RESULTATS = 10


# ---------------------------------------------------------------- Outils (lecture seule sur les données locales)

def mon_profil() -> str:
    en_cache = profil_en_cache()
    if not en_cache:
        return "Aucun profil : le CV n'a pas encore été importé."
    texte = en_cache[0].model_dump_json(indent=1)
    with closing(stockage.connecter()) as c:
        declarees = stockage.competences_declarees(c)
    if confirmees := [d for d in declarees if d["statut"] in ("confirmée", "déclarée")]:
        texte += "\n\nCompétences confirmées en plus du CV :\n" + "\n".join(
            f"- {d['nom']} : {d['resume_cv']} ({d['description'] or ''})" for d in confirmees)
    return texte


def chercher_offres(mots_cles: str) -> str:
    mots = [m for m in mots_cles.lower().split() if len(m) > 1]
    # Un « LIKE » par mot-clé : tous doivent apparaître dans le titre, la description ou le nom de l'entreprise
    conditions = "".join(" AND lower(o.titre || ' ' || o.description || ' ' || COALESCE(o.entreprise, '')) LIKE ?" for _ in mots)
    with closing(stockage.connecter()) as c:
        trouvees = c.execute(
            f"""
            SELECT o.id, o.titre, o.entreprise, o.distance_km, o.date_publication, MAX(n.score) AS score
            FROM offres o LEFT JOIN notations n ON n.offre_id = o.id
            WHERE o.derniere_vue = (SELECT MAX(derniere_vue) FROM offres) AND o.exclusion IS NULL {conditions}
            GROUP BY o.id ORDER BY score DESC LIMIT ?
            """,
            (*[f"%{m}%" for m in mots], MAX_RESULTATS),
        ).fetchall()
    if not trouvees:
        return f"Aucune offre active ne contient : {mots_cles}"
    return "\n".join(
        f"- id={o['id']} | {o['titre']} | {o['entreprise'] or 'entreprise non communiquée'} | {o['distance_km']} km | "
        f"publiée le {o['date_publication'][:10]} | score {o['score'] if o['score'] is not None else 'non noté'}"
        for o in trouvees
    )


def detail_offre(offre_id: str) -> str:
    with closing(stockage.connecter()) as c:
        offre = c.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
        notation = c.execute("SELECT * FROM notations WHERE offre_id = ? ORDER BY date DESC LIMIT 1", (offre_id,)).fetchone()
    if offre is None:
        return f"Aucune offre avec l'id {offre_id} (utilise chercher_offres pour trouver l'id)."
    texte = (
        f"Titre : {offre['titre']}\nEntreprise : {offre['entreprise'] or 'non communiquée'}\n"
        f"Présentation de l'entreprise : {offre['description_entreprise'] or '-'}\n"
        f"Lieu : {offre['adresse']} ({offre['distance_km']} km)\nNiveau visé : {offre['niveau_diplome']}\n"
        f"Contrat : {', '.join(json.loads(offre['types_contrat']))}, {offre['duree_mois'] or '?'} mois, "
        f"télétravail : {offre['teletravail'] or 'non précisé'}\nLien : {offre['url_candidature']}\n\n"
        f"Description :\n{offre['description']}"
    )
    if notation:
        texte += (
            f"\n\nAnalyse de l'adéquation (score {notation['score']}/100) : {notation['justification']}\n"
            f"Points forts : {'; '.join(json.loads(notation['points_forts']))}\n"
            f"Points de vigilance : {'; '.join(json.loads(notation['points_vigilance']))}"
        )
    return texte


def infos_entreprise(nom: str) -> str:
    with closing(stockage.connecter()) as c:
        entreprises = stockage.chercher_entreprises(c, nom)
        offres = c.execute("SELECT id, titre FROM offres WHERE entreprise LIKE ? AND exclusion IS NULL", (f"%{nom}%",)).fetchall()
        blocs = []
        for e in entreprises[:3]:
            bloc = (f"Entreprise : {e['nom']} | secteur : {e['secteur']} | effectif : {e['taille']} | "
                    f"{e['adresse']} ({e['distance_km']} km) | SIRET {e['siret']}")
            if emails := stockage.emails_entreprise(c, e["id"]):
                recherche = emails[0]
                bloc += (f"\nRecherche déjà faite : {recherche['ce_que_fait']}\nSite : {recherche['site_web'] or '-'}"
                         f"\nSources : {', '.join(json.loads(recherche['sources']))}")
            for cand in stockage.candidatures(c, entreprise_id=e["id"]):
                bloc += f"\nCandidature envoyée le {cand['date_envoi'][:10]} ({cand['canal']}), statut : {cand['statut']}"
            blocs.append(bloc)
    blocs += [f"Offre publiée par cette entreprise : id={o['id']} | {o['titre']}" for o in offres]
    return "\n\n".join(blocs) if blocs else f"Rien en base sur « {nom} » : fais une recherche web."


def mes_candidatures() -> str:
    with closing(stockage.connecter()) as c:
        toutes = stockage.candidatures(c)
    if not toutes:
        return "Aucune candidature enregistrée."
    return "\n".join(
        f"- {x['nom']} | {x['canal']} : {x['destinataire']} | envoyée le {x['date_envoi'][:10]} | "
        f"statut : {x['statut']} | relances : {x['nb_relances']}"
        + (f" | offre id={x['offre_id']}" if x["offre_id"] else "")
        for x in toutes
    )


OUTILS = [
    OutilPerso("mon_profil", "Profil du candidat extrait de son CV : formation, compétences, expériences, projets.", {}, mon_profil),
    OutilPerso("chercher_offres", "Recherche dans les offres d'alternance collectées (mots-clés, tous doivent apparaître). "
               "Renvoie les id à passer à detail_offre.", {"mots_cles": str}, chercher_offres),
    OutilPerso("detail_offre", "Texte complet d'une offre et analyse de son adéquation avec le profil.", {"offre_id": str}, detail_offre),
    OutilPerso("infos_entreprise", "Ce que l'application sait d'une entreprise : fiche, recherche déjà faite, "
               "candidatures envoyées, offres publiées.", {"nom": str}, infos_entreprise),
    OutilPerso("mes_candidatures", "Liste des candidatures envoyées et leur statut.", {}, mes_candidatures),
]


# ---------------------------------------------------------------- Modes

COMMUN = """Tu es le coach de candidature d'un étudiant en 3e année de BUT Informatique qui cherche une alternance
de développeur full stack. Tu le tutoies, en français, avec un ton direct, bienveillant et exigeant.

Règles :
- Appuie-toi sur les outils : mon_profil pour son parcours réel, detail_offre / infos_entreprise pour la cible,
  la recherche web pour compléter sur l'entreprise (actualité, produits, stack). Cite tes sources web.
- N'invente rien sur l'entreprise ni sur le parcours du candidat.
- Ne l'aide jamais à mentir ou à embellir son expérience : aide-le à valoriser ce qu'il a vraiment fait.
- Réponses courtes et structurées (listes, gras), adaptées à une lecture à l'écran."""

MODES = {
    "coach": COMMUN + """

Mode coach : réponds à ses questions sur ses candidatures et la préparation de ses entretiens
(fiche entreprise, questions probables, pitch de présentation, questions à poser au recruteur, négociation du rythme...).""",
    "simulation": COMMUN + """

Mode simulation d'entretien : tu joues le recruteur de l'entreprise ciblée.
1. Au début, renseigne-toi (outils + web) sans l'afficher, puis présente-toi en une phrase (rôle fictif) et pose
   la première question.
2. Pose UNE seule question à la fois et attends sa réponse. Enchaîne 6 à 8 questions variées :
   présentation et motivation pour CETTE entreprise, question technique liée à la stack de l'offre,
   un projet de son CV en profondeur, question comportementale (méthode STAR), gestion du rythme école / entreprise,
   « avez-vous des questions ? ».
3. Après chaque réponse, avant la question suivante, donne un retour bref entre crochets :
   [✅ ce qui fonctionne · ⚠️ à améliorer · 💡 une meilleure formulation en une phrase].
4. Quand il écrit « bilan » ou après la dernière question : sors du rôle et fais un bilan
   (note sur 10 pour : clarté, motivation, technique, connaissance de l'entreprise) et 3 axes de travail prioritaires.""",
}


def systeme(mode: str, cible: str | None) -> str:
    return MODES[mode] + (f"\n\nCible de la préparation : {cible}" if cible else "\n\nAucune cible précise : discussion générale.")


def envoyer(message: str, mode: str, cible: str | None, session: str | None):
    """Événements de la réponse de l'assistant (voir llm_client.discuter)."""
    return discuter(message, systeme(mode, cible), OUTILS, session)
