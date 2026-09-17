"""Interface web locale d'Alternance Copilot.

Lancement : double-cliquer sur « Alternance Copilot.bat », ou depuis la racine du projet :
    .venv\\Scripts\\streamlit.exe run app.py
"""

import json
from contextlib import closing
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv

from src import candidature, collecte, notation, stockage
from src.llm_client import ErreurLLM
from src.profil import CHEMIN_CV, charger_profil, profil_en_cache

load_dotenv()
st.set_page_config(page_title="Alternance Copilot", page_icon="🎯", layout="wide")

TAILLES = {
    "0-0": "0 salarié", "1-2": "1 à 2", "3-5": "3 à 5", "6-9": "6 à 9", "10-19": "10 à 19",
    "20-49": "20 à 49", "50-99": "50 à 99", "100-199": "100 à 199", "200-249": "200 à 249",
    "250-499": "250 à 499", "500-999": "500 à 999", "1000-1999": "1 000 à 1 999",
}


def connexion():
    return closing(stockage.connecter())


def date_lisible(iso: str | None) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y à %H:%M") if iso else "jamais"


def anciennete(iso: str) -> str:
    jours = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    return "🆕 publiée aujourd'hui" if jours == 0 else "🆕 publiée hier" if jours == 1 else f"publiée il y a {jours} jours"


PERIODES = {"3 jours": 3, "1 semaine": 7, "2 semaines": stockage.AGE_MAX_JOURS}


def couleur_score(score: int) -> str:
    return "green" if score >= 60 else "orange" if score >= 40 else "red"


# ---------------------------------------------------------------- Barre latérale : actions globales

def barre_laterale() -> None:
    with st.sidebar:
        with connexion() as c:
            st.caption(f"Dernière collecte : {date_lisible(stockage.derniere_collecte(c))}")

        if st.button("🔄 Collecter les offres", width="stretch", help="API La bonne alternance (sans quota Claude)"):
            with st.spinner("Interrogation de l'API..."):
                try:
                    bilan = collecte.collecter()
                    st.toast(f"{bilan['offres']} offres ({bilan['nouvelles_offres']} nouvelles), "
                             f"{bilan['entreprises']} entreprises ({bilan['nouvelles_entreprises']} nouvelles)")
                except Exception as erreur:
                    st.error(f"Échec de la collecte : {erreur}")

        if st.button("⭐ Noter les nouvelles offres", width="stretch", help=f"Offres publiées depuis {stockage.AGE_MAX_JOURS} jours max · utilise le quota Claude (≈ 1 min 30 par lot de 10)"):
            if not profil_en_cache():
                st.error("Importe d'abord ton CV (page Profil).")
            else:
                with st.status("Notation par Claude...", expanded=True) as statut:
                    try:
                        total = notation.noter_offres(progression=st.write)
                        statut.update(label=f"{total} offres notées", state="complete")
                    except ErreurLLM as erreur:
                        statut.update(label="Échec de la notation", state="error")
                        st.error(str(erreur))


# ---------------------------------------------------------------- Page : offres classées

def page_offres() -> None:
    st.title("🏆 Offres classées")
    en_cache = profil_en_cache()
    if not en_cache:
        st.info("Commence par importer ton CV dans la page **Profil**.")
        return
    _, hash_cv = en_cache

    filtres = st.columns([2, 3])
    periode = filtres[0].segmented_control("Publiées depuis", list(PERIODES), default="2 semaines") or "2 semaines"
    score_min = filtres[1].slider("Score minimum", 0, 100, 0, step=5)

    with connexion() as c:
        total = stockage.nombre_offres_actives(c, PERIODES[periode])
        lignes = stockage.classement(c, hash_cv, PERIODES[periode])

    if not lignes:
        if total:
            st.info(f"{total} offres publiées depuis {periode}, aucune notée : clique sur **⭐ Noter les nouvelles offres**.")
        else:
            st.info(f"Aucune offre publiée depuis {periode} : élargis la période ou relance une collecte.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric(f"Offres depuis {periode}", total)
    col2.metric("Offres notées", len(lignes))
    col3.metric("Meilleur score", f"{lignes[0]['score']} / 100")

    for ligne in (l for l in lignes if l["score"] >= score_min):
        with st.container(border=True):
            gauche, droite = st.columns([5, 1])
            gauche.markdown(f"#### {ligne['titre']}")
            gauche.caption(f"{ligne['entreprise'] or 'Entreprise non communiquée'} · {ligne['adresse']} · "
                           f"{ligne['distance_km']} km · {anciennete(ligne['date_publication'])}")
            droite.markdown(f"## :{couleur_score(ligne['score'])}[{ligne['score']}]")

            st.write(ligne["justification"])
            criteres = st.columns(4)
            for colonne, (nom, cle) in zip(criteres, [("Technique", "score_technique"), ("Niveau", "score_niveau"),
                                                      ("Distance", "score_distance"), ("Rythme", "score_rythme")]):
                colonne.progress(ligne[cle] / 100, text=f"{nom} : {ligne[cle]}")

            with st.expander("Détails"):
                forts, vigilance = st.columns(2)
                forts.markdown("**✅ Points forts**\n" + "".join(f"\n- {p}" for p in json.loads(ligne["points_forts"])))
                vigilance.markdown("**⚠️ Points de vigilance**\n" + "".join(f"\n- {p}" for p in json.loads(ligne["points_vigilance"])))
            st.link_button("Voir l'offre et postuler ↗", ligne["url_candidature"])


# ---------------------------------------------------------------- Page : entreprises (candidatures spontanées)

def afficher_email(objet: str, corps: str, cle: str) -> None:
    texte = st.text_area("Email (modifiable)", f"{corps}\n\n{candidature.lire_signature()}", height=380, key=cle)
    st.caption(f"Objet : **{objet}** · {len(corps.split())} mots")
    st.code(f"Objet : {objet}\n\n{texte}", language=None, wrap_lines=True)  # bouton « copier » intégré


def page_entreprises() -> None:
    st.title("🏢 Candidatures spontanées")
    st.caption("Entreprises du numérique susceptibles de recruter un alternant, sans offre publiée.")

    filtres = st.columns([2, 3])
    avec_salaries = filtres[0].toggle("Masquer les entreprises sans salarié", value=True)
    recherche = filtres[1].text_input("Rechercher", placeholder="Nom de l'entreprise", label_visibility="collapsed")

    with connexion() as c:
        entreprises = [e for e in stockage.lister_entreprises(c, avec_salaries) if recherche.lower() in e["nom"].lower()]
    if not entreprises:
        st.info("Aucune entreprise : lance une collecte ou change les filtres.")
        return

    tableau = [
        {"Entreprise": e["nom"], "Secteur": e["secteur"], "Effectif": TAILLES.get(e["taille"], e["taille"] or "?"),
         "Distance (km)": e["distance_km"], "Email": "✉️" if e["nb_emails"] else ""}
        for e in entreprises
    ]
    selection = st.dataframe(tableau, hide_index=True, width="stretch", height=320,
                             on_select="rerun", selection_mode="single-row")
    lignes = selection.selection.rows
    if not lignes:
        st.caption(f"{len(entreprises)} entreprises · clique sur une ligne pour préparer un email")
        return

    entreprise = entreprises[lignes[0]]
    with st.container(border=True):
        st.subheader(entreprise["nom"])
        st.caption(f"{entreprise['secteur']} · {TAILLES.get(entreprise['taille'], '?')} salariés · "
                   f"{entreprise['adresse']} · {entreprise['distance_km']} km")
        liens = st.columns(3)
        liens[0].link_button("Fiche La bonne alternance ↗", entreprise["url_candidature"])
        if entreprise["siret"]:
            liens[1].link_button("Annuaire des entreprises ↗", f"https://annuaire-entreprises.data.gouv.fr/etablissement/{entreprise['siret']}")
        if entreprise["telephone"]:
            liens[2].markdown(f"📞 {entreprise['telephone']}")

        with connexion() as c:
            precedents = stockage.emails_entreprise(c, entreprise["id"])

        libelle = "🔁 Générer un nouvel email" if precedents else "✨ Générer l'email"
        if st.button(libelle, type="primary", help="Recherche web + rédaction par Claude (≈ 1 min, utilise le quota)"):
            with st.spinner("Claude se renseigne sur l'entreprise puis rédige l'email..."):
                try:
                    with connexion() as c:
                        candidature.rediger_email(c, entreprise)
                    st.rerun()
                except ErreurLLM as erreur:
                    st.error(str(erreur))

        if precedents:
            email = precedents[0]
            if not email["personnalise"]:
                st.warning("Aucune information fiable trouvée sur cette entreprise : email générique, à personnaliser.")
            st.markdown(f"**Ce que fait l'entreprise :** {email['ce_que_fait']}")
            with st.expander(f"Sources ({len(json.loads(email['sources']))})"):
                for url in json.loads(email["sources"]):
                    st.markdown(f"- {url}")
            afficher_email(email["objet"], email["corps"], cle=f"email-{email['id']}")
            st.caption(f"Généré le {date_lisible(email['date'])}"
                       + (f" · {len(precedents)} versions" if len(precedents) > 1 else ""))


# ---------------------------------------------------------------- Page : profil

def page_profil() -> None:
    st.title("👤 Mon profil")

    fichier = st.file_uploader("CV (PDF)", type="pdf", help="Stocké uniquement sur ton ordinateur, dans data/")
    if fichier is not None and st.button("Importer ce CV et extraire le profil", type="primary"):
        CHEMIN_CV.parent.mkdir(parents=True, exist_ok=True)
        CHEMIN_CV.write_bytes(fichier.getvalue())
        with st.spinner("Claude lit ton CV..."):
            try:
                charger_profil()
                st.success("Profil extrait. Pense à relancer la notation : les offres seront renotées pour ce CV.")
            except ErreurLLM as erreur:
                st.error(str(erreur))

    en_cache = profil_en_cache()
    if not en_cache:
        if CHEMIN_CV.exists():
            st.warning("Le CV a changé depuis la dernière extraction.")
            if st.button("Extraire le profil du CV actuel"):
                with st.spinner("Claude lit ton CV..."):
                    try:
                        charger_profil()
                        st.rerun()
                    except ErreurLLM as erreur:
                        st.error(str(erreur))
        return

    profil, _ = en_cache
    st.subheader(profil.titre_recherche)
    st.write(f"🎓 {profil.formation}")
    st.write(f"📅 Rythme : {profil.rythme_alternance or 'non précisé'} · Niveau visé : {profil.niveau_diplome}")

    gauche, droite = st.columns(2)
    with gauche:
        st.markdown("##### Compétences")
        for categorie, competences in profil.competences.items():
            st.markdown(f"**{categorie}** : " + " ".join(f":blue-badge[{c}]" for c in competences))
        st.markdown("##### Points forts")
        st.markdown("".join(f"\n- {p}" for p in profil.points_forts))
    with droite:
        st.markdown("##### Expériences")
        for experience in profil.experiences:
            st.markdown(f"**{experience.poste}**, {experience.entreprise} · *{experience.periode}*"
                        + "".join(f"\n- {r}" for r in experience.realisations))
        st.markdown("##### Projets")
        for projet in profil.projets:
            st.markdown(f"**{projet.nom}** ({projet.contexte}) · {', '.join(projet.technologies)}\n- {projet.resultat}")

    st.divider()
    st.markdown("##### Signature des emails")
    st.caption("Ajoutée en fin d'email, jamais envoyée à Claude.")
    signature = st.text_area("Signature", candidature.lire_signature(), height=110, label_visibility="collapsed")
    if st.button("Enregistrer la signature"):
        candidature.CHEMIN_SIGNATURE.write_text(signature.strip() + "\n", encoding="utf-8")
        st.toast("Signature enregistrée")


barre_laterale()
st.navigation([
    st.Page(page_offres, title="Offres", icon="🏆", default=True),
    st.Page(page_entreprises, title="Candidatures spontanées", icon="🏢"),
    st.Page(page_profil, title="Profil", icon="👤"),
]).run()
