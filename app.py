"""Interface web locale d'Alternance Copilot.

Lancement : double-cliquer sur « Alternance Copilot.bat », ou depuis la racine du projet :
    .venv\\Scripts\\streamlit.exe run app.py
"""

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from pypdf import PdfReader

from src import (assistant, automatisation, candidature, collecte, competences, contacts, cv_adapte, cv_modele,
                 hunter, notation, relance, stockage)
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

RATTRAPAGE_COLLECTE_HEURES = 12


def collecte_de_rattrapage() -> None:
    """Une fois par ouverture : si la tâche du matin n'a pas tourné (PC éteint), collecte sans notation (aucun token)."""
    if st.session_state.get("rattrapage_verifie"):
        return
    st.session_state.rattrapage_verifie = True
    with connexion() as c:
        derniere = stockage.derniere_collecte(c)
    if derniere is None or datetime.now(timezone.utc) - datetime.fromisoformat(derniere) > timedelta(hours=RATTRAPAGE_COLLECTE_HEURES):
        with st.spinner("Collecte des nouvelles offres..."):
            automatisation.executer(origine="application", avec_notation=False)


@st.cache_data(ttl=300, show_spinner=False)
def tache_active() -> bool:
    return automatisation.tache_planifiee_active()


def etat_automatisation() -> None:
    with connexion() as c:
        execution = stockage.derniere_execution(c)
    if tache_active():
        jours = ", ".join(automatisation.JOURS_NOTATION.values())
        st.caption(f"⏰ Automatique : collecte chaque matin, notation le {jours}")
    else:
        st.caption("⏰ Automatique : inactif · double-clique sur « Activer la collecte automatique.bat »")
    if execution:
        notation_faite = (f"{execution['offres_notees']} notée(s)" if execution["offres_notees"] is not None
                          else "pas de notation")
        st.caption(f"Dernier passage ({execution['origine']}) : {date_lisible(execution['date'])} · "
                   f"{execution['nouvelles_offres'] or 0} nouvelle(s) offre(s) · {notation_faite}")
        if execution["erreur"]:
            st.warning(execution["erreur"][:150])


def barre_laterale() -> None:
    collecte_de_rattrapage()
    with st.sidebar:
        etat_automatisation()
        with connexion() as c:
            st.caption(f"Dernière collecte : {date_lisible(stockage.derniere_collecte(c))}")
            nb_relances = len(stockage.candidatures_a_relancer(c))
        if nb_relances:
            st.warning(f"🔔 {nb_relances} relance{'s' if nb_relances > 1 else ''} à faire (page Suivi)")

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
        exclues = stockage.offres_exclues(c, PERIODES[periode])

    if exclues:
        with st.expander(f"🚫 {len(exclues)} offre{'s' if len(exclues) > 1 else ''} d'écoles / CFA masquée{'s' if len(exclues) > 1 else ''}"):
            for offre in exclues:
                st.markdown(f"- [{offre['titre']}]({offre['url_candidature']}) · {offre['entreprise'] or '?'} · *{offre['exclusion']}*")

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
            boutons = st.columns([1, 1, 3])
            boutons[0].link_button("Voir l'offre et postuler ↗", ligne["url_candidature"])
            with connexion() as c:
                deja = stockage.candidatures(c, offre_id=ligne["offre_id"])
            if deja:
                boutons[2].success(f"📬 Postulé le {date_lisible(deja[0]['date_envoi'])} · {deja[0]['statut']}")
            elif boutons[1].button("📤 J'ai postulé", key=f"postule-{ligne['offre_id']}"):
                with connexion() as c:
                    stockage.enregistrer_candidature(c, {
                        "offre_id": ligne["offre_id"], "nom": f"{ligne['titre']} ({ligne['entreprise'] or 'offre'})",
                        "destinataire": "plateforme de l'offre", "canal": "offre",
                    })
                st.rerun()


# ---------------------------------------------------------------- Page : entreprises (candidatures spontanées)

def afficher_email(objet: str, corps: str, cle: str, mention_rgpd: bool = False) -> None:
    if mention_rgpd:  # adresse trouvée via un annuaire : on dit d'où elle vient (RGPD, article 14)
        corps = f"{corps}\n\n{hunter.MENTION_RGPD}"
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
        st.caption(f"{len(entreprises)} entreprises (écoles et CFA exclus) · clique sur une ligne pour préparer un email")
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
            envoyees = stockage.candidatures(c, entreprise_id=entreprise["id"])
        for envoyee in envoyees:
            st.success(f"📬 Candidature envoyée le {date_lisible(envoyee['date_envoi'])} "
                       f"({envoyee['canal']} : {envoyee['destinataire']}) · statut : **{envoyee['statut']}**")

        libelle = "🔁 Relancer la recherche et la rédaction" if precedents else "✨ Trouver les contacts et rédiger"
        if st.button(libelle, type="primary", help="Recherche web + rédaction par Claude (≈ 1 à 2 min, utilise le quota)"):
            with st.spinner("Claude se renseigne sur l'entreprise, relève ses contacts publiés et rédige..."):
                try:
                    with connexion() as c:
                        candidature.rediger_email(c, entreprise)
                    st.rerun()
                except ErreurLLM as erreur:
                    st.error(str(erreur))

        email = precedents[0] if precedents else None
        onglet_contacts, onglet_email, onglet_linkedin = st.tabs(["👥 Qui contacter", "✉️ Email", "💼 LinkedIn"])
        with onglet_contacts:
            afficher_contacts(entreprise, email)
        with onglet_email:
            if not email:
                st.info("Clique sur **✨ Trouver les contacts et rédiger**.")
            else:
                if not email["personnalise"]:
                    st.warning("Aucune information fiable trouvée sur cette entreprise : email générique, à personnaliser.")
                st.markdown(f"**Ce que fait l'entreprise :** {email['ce_que_fait']}")
                with st.expander(f"Sources ({len(json.loads(email['sources']))})"):
                    for url in json.loads(email["sources"]):
                        st.markdown(f"- {url}")
                trouvees = hunter.resultats_connus(entreprise["id"])
                afficher_email(email["objet"], email["corps"], cle=f"email-{email['id']}", mention_rgpd=bool(trouvees))
                st.caption(f"Généré le {date_lisible(email['date'])}"
                           + (f" · {len(precedents)} versions" if len(precedents) > 1 else ""))
                adresses = [p["adresse"] for p in json.loads(email["emails_publics"]) if p["verifiee"] is not False]
                adresses += [a["email"] for a in trouvees if a["statut"] != "invalid"]
                marquer_envoye(entreprise, email, "email", adresses)
        with onglet_linkedin:
            afficher_linkedin(entreprise, email)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def dirigeants_en_cache(siret: str | None) -> list[dict]:
    try:
        return contacts.dirigeants(siret)
    except Exception:
        return []


def afficher_contacts(entreprise, email) -> None:
    personnes = dirigeants_en_cache(entreprise["siret"])
    st.markdown("**Dirigeants** · registre national des entreprises")
    if personnes:
        for personne in personnes:
            st.markdown(f"- {personne['prenoms']} {personne['nom']} — {personne['qualite'] or 'dirigeant'}")
        st.caption("Dans une PME, le dirigeant décide souvent lui-même de recruter un alternant.")
    else:
        st.caption("Aucun dirigeant personne physique trouvé.")

    st.markdown("**Contacts publiés par l'entreprise** · trouvés par Claude, vérifiés sur la page source")
    if not email:
        st.caption("Clique sur **✨ Trouver les contacts et rédiger** pour les chercher.")
    else:
        if email["site_web"]:
            st.markdown(f"- 🌐 Site : {email['site_web']}")
        if email["page_carrieres"]:
            st.markdown(f"- 📄 Carrières / contact : {email['page_carrieres']}")
        publies = json.loads(email["emails_publics"])
        for publie in publies:
            etat = {True: "✅ vérifiée sur la page", False: "⚠️ absente de la page : ne pas utiliser", None: "❔ page inaccessible : à vérifier"}[publie["verifiee"]]
            st.markdown(f"- ✉️ `{publie['adresse']}` ({publie['usage']}) · {etat} · [source]({publie['source']})")
        if not publies:
            st.caption("Aucune adresse publiée : passe par le formulaire du site ou par LinkedIn.")

    st.divider()
    afficher_hunter(entreprise, personnes, email)


@st.cache_data(ttl=600, show_spinner=False)
def quota_hunter() -> dict | None:
    try:
        return hunter.quota()
    except hunter.ErreurHunter:
        return None


def afficher_hunter(entreprise, personnes: list[dict], email) -> None:
    """Recherche d'une adresse nominative, à la demande : chaque recherche coûte un crédit."""
    st.markdown("**Contact nominatif** · Hunter.io")
    quota = quota_hunter()
    if quota is None:
        st.caption("Pas de clé Hunter : ajoute `HUNTER_API_KEY` dans `.env` pour activer cette recherche.")
        return
    adresses_publiees = [p["adresse"] for p in json.loads(email["emails_publics"])] if email else []
    domaine = hunter.domaine(email["site_web"] if email else None, adresses_publiees)

    for adresse in hunter.resultats_connus(entreprise["id"]):
        fiabilite = {"valid": "✅ valide", "accept_all": "⚠️ serveur qui accepte tout : risque de rebond",
                     "invalid": "❌ invalide", "webmail": "⚠️ adresse personnelle"}.get(adresse["statut"], "❔ inconnu")
        st.markdown(f"- ✉️ `{adresse['email']}` · {adresse['poste'] or 'poste inconnu'} · "
                    f"confiance {adresse['score']}/100 · {fiabilite}")
    if hunter.resultats_connus(entreprise["id"]):
        st.caption(f"⚖️ RGPD : ces adresses ne viennent pas de la personne. La phrase « {hunter.MENTION_RGPD} » "
                   "est ajoutée à la fin de l'email.")

    # Sans recherche préalable, le domaine est inconnu : on le demande (gratuit tant qu'on ne cherche pas)
    domaine = st.text_input("Domaine de l'entreprise", value=domaine or "", key=f"hunter-domaine-saisi-{entreprise['id']}",
                            placeholder="exemple.fr", help="Rempli automatiquement après « Trouver les contacts »")
    if not domaine:
        st.caption("Indique le domaine du site de l'entreprise, ou lance **✨ Trouver les contacts et rédiger**.")
        return
    colonnes = st.columns([3, 2])
    noms = {f"{p['prenoms'].split(' ')[0]} {p['nom']}": p for p in personnes}
    choix = colonnes[0].selectbox("Chercher l'adresse de", list(noms), key=f"hunter-nom-{entreprise['id']}",
                                  index=None, placeholder="Un dirigeant" if noms else "Aucun dirigeant connu")
    actions = colonnes[1].columns(2)
    if actions[0].button("🔎 Cette personne", key=f"hunter-personne-{entreprise['id']}", disabled=not choix,
                         help="1 crédit si une adresse est trouvée"):
        with st.spinner(f"Recherche sur {domaine}..."):
            try:
                personne = noms[choix]
                if hunter.trouver_email(entreprise["id"], domaine, personne["prenoms"].split(" ")[0], personne["nom"]):
                    quota_hunter.clear()
                    st.rerun()
                st.warning("Aucune adresse trouvée pour cette personne (aucun crédit consommé).")
            except hunter.ErreurHunter as erreur:
                st.error(str(erreur))
    if actions[1].button("🔎 Le domaine", key=f"hunter-domaine-{entreprise['id']}",
                         help=f"Toutes les adresses connues de {domaine} · 1 crédit"):
        with st.spinner(f"Recherche sur {domaine}..."):
            try:
                resultat = hunter.adresses_du_domaine(entreprise["id"], domaine)
                quota_hunter.clear()
                st.toast(f"Format des adresses : {hunter.format_lisible(resultat.get('pattern'))}")
                st.rerun()
            except hunter.ErreurHunter as erreur:
                st.error(str(erreur))
    st.caption(f"Crédits restants ce mois : {quota['recherches']} recherches · {quota['verifications']} vérifications")


def afficher_linkedin(entreprise, email) -> None:
    st.caption("Ouvre une recherche, choisis la personne, puis envoie une invitation avec la note ci-dessous.")
    liens = contacts.liens_linkedin(entreprise["nom"], dirigeants_en_cache(entreprise["siret"]))
    colonnes = st.columns(2)
    for i, (libelle, url) in enumerate(liens):
        colonnes[i % 2].link_button(f"🔎 {libelle}", url, width="stretch")
    if email and email["note_linkedin"]:
        st.markdown("**Note d'invitation**")
        st.code(email["note_linkedin"], language=None, wrap_lines=True)
        st.caption(f"{len(email['note_linkedin'])} / 300 caractères")
        marquer_envoye(entreprise, email, "linkedin", [])


def marquer_envoye(entreprise, email, canal: str, suggestions: list[str]) -> None:
    """Enregistre l'envoi dans le suivi : c'est ce qui déclenche les rappels de relance."""
    with st.form(f"envoi-{canal}-{email['id']}", border=False):
        etiquette = "Adresse du destinataire" if canal == "email" else "Personne contactée sur LinkedIn"
        destinataire = st.selectbox(etiquette, suggestions, index=None, accept_new_options=True,
                                    placeholder="Choisis ou saisis")
        if st.form_submit_button(f"📤 Marquer comme envoyé ({canal})"):
            if not destinataire:
                st.error("Indique le destinataire.")
                return
            with connexion() as c:
                stockage.enregistrer_candidature(c, {
                    "entreprise_id": entreprise["id"], "email_id": email["id"], "nom": entreprise["nom"],
                    "destinataire": destinataire, "canal": canal,
                })
            st.toast(f"Candidature enregistrée : relance proposée dans {stockage.DELAI_RELANCE_JOURS} jours")
            st.rerun()


# ---------------------------------------------------------------- Page : suivi et relances

STATUTS = ["envoyée", "relancée", "entretien", "refus", "sans suite"]


def afficher_relance(cand) -> None:
    with st.container(border=True):
        st.markdown(f"**{cand['nom']}** · {cand['canal']} : {cand['destinataire']}")
        st.caption(f"Envoyée le {date_lisible(cand['date_envoi'])} · sans réponse depuis {cand['jours_sans_reponse']} jours · "
                   f"relance {cand['nb_relances'] + 1} sur {stockage.MAX_RELANCES}")
        with connexion() as c:
            brouillon = stockage.relance_en_attente(c, cand["id"])

        if brouillon is None:
            gauche, droite = st.columns(2)
            if gauche.button("✍️ Rédiger la relance", key=f"rediger-{cand['id']}", type="primary"):
                with st.spinner("Claude rédige la relance..."):
                    try:
                        with connexion() as c:
                            relance.rediger_relance(c, cand)
                        st.rerun()
                    except ErreurLLM as erreur:
                        st.error(str(erreur))
        else:
            texte = st.text_area("Relance (modifiable)", f"{brouillon['corps']}\n\n{candidature.lire_signature()}",
                                 height=220, key=f"relance-{brouillon['id']}")
            st.code(f"Objet : {brouillon['objet']}\n\n{texte}", language=None, wrap_lines=True)
            gauche, droite = st.columns(2)
            if gauche.button("✅ Relance envoyée", key=f"envoyee-{brouillon['id']}", type="primary"):
                with connexion() as c:
                    stockage.marquer_relance_envoyee(c, brouillon["id"], cand["id"])
                st.rerun()
            if droite.button("🔁 Réécrire", key=f"reecrire-{brouillon['id']}"):
                with st.spinner("Claude réécrit la relance..."):
                    try:
                        with connexion() as c:
                            relance.rediger_relance(c, cand)
                        st.rerun()
                    except ErreurLLM as erreur:
                        st.error(str(erreur))
        if droite.button("💬 Ils ont répondu", key=f"repondu-{cand['id']}",
                         help="Passe la candidature en « entretien » : plus de relance"):
            with connexion() as c:
                stockage.changer_statut(c, cand["id"], "entretien")
            st.rerun()


def page_suivi() -> None:
    st.title("📬 Suivi des candidatures")
    with connexion() as c:
        toutes = stockage.candidatures(c)
        a_relancer = stockage.candidatures_a_relancer(c)

    if not toutes:
        st.info("Aucune candidature enregistrée. Utilise **📤 Marquer comme envoyé** (Candidatures spontanées) "
                "ou **📤 J'ai postulé** (Offres) : les relances seront proposées automatiquement.")
        return

    colonnes = st.columns(4)
    colonnes[0].metric("Candidatures", len(toutes))
    colonnes[1].metric("En attente de réponse", sum(c["statut"] in stockage.STATUTS_EN_COURS for c in toutes))
    colonnes[2].metric("Entretiens", sum(c["statut"] == "entretien" for c in toutes))
    colonnes[3].metric("À relancer", len(a_relancer))

    st.subheader(f"🔔 À relancer aujourd'hui ({len(a_relancer)})")
    st.caption(f"Relance proposée {stockage.DELAI_RELANCE_JOURS} jours après l'envoi, "
               f"{stockage.MAX_RELANCES} fois au maximum, tant que le statut est « envoyée » ou « relancée ».")
    if a_relancer:
        for cand in a_relancer:
            afficher_relance(cand)
    else:
        st.success("Rien à relancer aujourd'hui.")

    st.subheader("Toutes les candidatures")
    tableau = [
        {"Candidature": c["nom"], "Canal": c["canal"], "Destinataire": c["destinataire"],
         "Envoyée le": date_lisible(c["date_envoi"]), "Relances": c["nb_relances"], "Statut": c["statut"]}
        for c in toutes
    ]
    st.data_editor(
        tableau, key="suivi", hide_index=True, width="stretch",
        disabled=["Candidature", "Canal", "Destinataire", "Envoyée le", "Relances"],
        column_config={"Statut": st.column_config.SelectboxColumn("Statut", options=STATUTS, required=True)},
    )
    # Changements de statut faits dans le tableau : { index de ligne : { colonne : nouvelle valeur } }
    modifications = st.session_state.get("suivi", {}).get("edited_rows", {})
    with connexion() as c:
        for index, changement in modifications.items():
            if "Statut" in changement and toutes[int(index)]["statut"] != changement["Statut"]:
                stockage.changer_statut(c, toutes[int(index)]["id"], changement["Statut"])


# ---------------------------------------------------------------- Page : préparation d'entretien (chatbot)

LIBELLES_OUTILS = {
    "mon_profil": "📄 Lecture de ton profil", "chercher_offres": "🔎 Recherche dans les offres",
    "detail_offre": "📋 Lecture de l'offre", "infos_entreprise": "🏢 Fiche de l'entreprise",
    "mes_candidatures": "📬 Lecture de tes candidatures", "WebSearch": "🌐 Recherche web", "WebFetch": "🌐 Lecture d'une page web",
}
MODES_CHAT = {"💬 Coach": "coach", "🎭 Simulation d'entretien": "simulation"}
SUGGESTIONS = [
    "Fais-moi une fiche de préparation sur cette entreprise",
    "Quelles questions techniques risque-t-on de me poser ?",
    "Aide-moi à préparer mon pitch de présentation en 1 minute",
    "Quelles questions poser au recruteur ?",
]


def cibles_possibles() -> dict[str, str | None]:
    """Libellé affiché → description de la cible transmise à l'assistant."""
    options: dict[str, str | None] = {"Aucune cible (discussion libre)": None}
    with connexion() as c:
        for cand in stockage.candidatures(c):
            reference = f"offre id={cand['offre_id']}" if cand["offre_id"] else "candidature spontanée"
            options[f"📬 {cand['nom']}"] = f"{cand['nom']} ({reference}, envoyée le {cand['date_envoi'][:10]}, statut {cand['statut']})"
        for offre in stockage.offres_actives(c):
            score = f" · {offre['score']}/100" if offre["score"] is not None else ""
            options.setdefault(f"📋 {offre['titre'][:70]}{score}",
                               f"Offre id={offre['id']} : {offre['titre']} ({offre['entreprise'] or 'entreprise non communiquée'})")
        for entreprise in stockage.entreprises_recherchees(c):
            options.setdefault(f"🏢 {entreprise['nom']}", f"Entreprise {entreprise['nom']} (candidature spontanée)")
    return options


def nouvelle_conversation() -> None:
    st.session_state.chat_messages = []
    st.session_state.chat_session = None
    st.session_state.pop("chat_suggestion", None)  # sinon la suggestion restée sélectionnée serait renvoyée


def repondre(message: str, mode: str, cible: str | None) -> None:
    st.session_state.chat_messages.append({"role": "user", "content": message})
    with st.chat_message("user"):
        st.markdown(message)
    with st.chat_message("assistant"):
        activite = st.empty()
        activite.caption("💭 Réflexion…")

        def texte_seul():
            for type_, valeur in assistant.envoyer(message, mode, cible, st.session_state.chat_session):
                if type_ == "texte":
                    activite.empty()
                    yield valeur
                elif type_ == "outil":
                    activite.caption(f"{LIBELLES_OUTILS.get(valeur, '🔧 ' + valeur)}…")
                elif type_ == "session":
                    st.session_state.chat_session = valeur

        try:
            reponse = st.write_stream(texte_seul())
            st.session_state.chat_messages.append({"role": "assistant", "content": reponse})
        except ErreurLLM as erreur:
            activite.empty()
            st.session_state.chat_messages.pop()  # le message n'a pas été traité : on le retire de l'historique
            st.error(str(erreur))
            return
    st.rerun()  # réaffiche proprement : l'historique à jour, sans le bouton ou la suggestion qui vient de servir


def page_entretien() -> None:
    st.title("🎤 Préparation d'entretien")
    if not profil_en_cache():
        st.info("Commence par importer ton CV dans la page **Profil**.")
        return

    reglages = st.columns([2, 4, 1])
    mode = MODES_CHAT[reglages[0].segmented_control("Mode", list(MODES_CHAT), default="💬 Coach") or "💬 Coach"]
    options = cibles_possibles()
    libelle = reglages[1].selectbox("Préparer un entretien pour", list(options))
    cible = options[libelle]
    reglages[2].button("🗑️ Effacer", on_click=nouvelle_conversation, help="Nouvelle conversation", width="stretch")

    # Changer de mode ou de cible démarre une nouvelle conversation
    if "chat_messages" not in st.session_state or st.session_state.get("chat_contexte") != (mode, cible):
        st.session_state.chat_contexte = (mode, cible)
        nouvelle_conversation()

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    a_envoyer = None
    if not st.session_state.chat_messages:
        if mode == "simulation":
            st.caption("Claude joue le recruteur : une question à la fois, un retour après chaque réponse, "
                       "puis un bilan noté (écris « bilan » pour l'obtenir à tout moment).")
            if st.button("🎬 Démarrer la simulation", type="primary", disabled=cible is None,
                         help=None if cible else "Choisis d'abord une offre ou une entreprise"):
                a_envoyer = "Commence la simulation."
        else:
            a_envoyer = st.pills("Suggestions", SUGGESTIONS, key="chat_suggestion", label_visibility="collapsed")
    elif mode == "simulation" and st.button("📊 Bilan de la simulation"):
        a_envoyer = "bilan"

    saisie = st.chat_input("Ta réponse…" if mode == "simulation" else "Pose ta question…")
    if message := saisie or a_envoyer:
        repondre(message, mode, cible)


# ---------------------------------------------------------------- Page : CV adapté à une offre

def lire_preuve(fichier) -> str:
    if fichier is None:
        return ""
    if fichier.name.lower().endswith(".pdf"):
        return "\n".join(page.extract_text() for page in PdfReader(fichier).pages)
    return fichier.getvalue().decode("utf-8", errors="replace")


def confirmer_competences(analyse: list[dict]) -> None:
    """Pour chaque compétence demandée par l'offre et absente du CV : l'as-tu déjà utilisée ?"""
    st.caption("Ton CV ne dit pas tout : confirme ce que tu sais vraiment faire. Rien n'est ajouté au CV sans ta réponse.")
    for competence in analyse:
        nom, declaration = competence["nom"], competence["declaration"]
        with st.container(border=True):
            st.markdown(f"**{nom}** · *{competence['importance']}* — l'offre dit : « {competence['extrait'][:120]} »")
            if declaration and not st.session_state.get(f"revoir-{nom}"):
                if declaration["statut"] == "absente":
                    st.info("Tu as indiqué ne pas l'avoir. Elle ne sera pas ajoutée au CV.")
                else:
                    st.success(f"{declaration['statut'].capitalize()} : {declaration['resume_cv']}")
                    if declaration["verdict"]:
                        st.caption(declaration["verdict"])
                st.button("Modifier ma réponse", key=f"modif-{nom}", on_click=lambda n=nom: st.session_state.update({f"revoir-{n}": True}))
                continue

            reponse = st.radio(f"As-tu déjà utilisé {nom} ?", ["Oui", "Non"], key=f"reponse-{nom}", horizontal=True, index=None)
            if reponse == "Non":
                if st.button("Enregistrer", key=f"non-{nom}"):
                    competences.declarer_absente(nom)
                    st.session_state.pop(f"revoir-{nom}", None)
                    st.rerun()
            elif reponse == "Oui":
                with st.form(f"preuve-{nom}", border=False):
                    description = st.text_area("Où et comment ? (projet, contexte, ce que tu as fait)", key=f"desc-{nom}",
                                               placeholder="Ex. : projet perso d'API REST en Spring Boot, 3 entités, tests JUnit…")
                    lien = st.text_input("Lien (GitHub, démo…) — facultatif", key=f"lien-{nom}")
                    fichier = st.file_uploader("Fichier de preuve — facultatif", key=f"fichier-{nom}",
                                               type=["pdf", "md", "txt", "py", "java", "js", "ts", "json", "xml", "yml"])
                    if st.form_submit_button("Vérifier et enregistrer", type="primary"):
                        if len((description or "").strip()) < 20:
                            st.error("Décris un peu plus précisément (au moins une phrase).")
                        else:
                            with st.spinner("Claude examine ta preuve..."):
                                try:
                                    verdict = competences.confirmer(nom, description, lien, lire_preuve(fichier))
                                    st.session_state.pop(f"revoir-{nom}", None)
                                    (st.success if verdict.convaincant else st.warning)(verdict.remarque)
                                    st.rerun()
                                except ErreurLLM as erreur:
                                    st.error(str(erreur))


def afficher_cv_adapte(resultat, chemin_pdf: str) -> None:
    for alerte in resultat.get("alertes", []):
        st.warning(alerte)
    if resultat.get("conseil"):
        st.info(f"💡 {resultat['conseil']}")
    if mots := resultat.get("mots_cles"):
        st.markdown("**Mots-clés de l'offre repris :** " + " ".join(f":blue-badge[{m}]" for m in mots))
    with open(chemin_pdf, "rb") as pdf:
        st.download_button("⬇️ Télécharger le CV en PDF", pdf.read(), file_name=Path(chemin_pdf).name,
                           mime="application/pdf", type="primary")
    st.markdown("##### Ce qui a changé")
    for changement in resultat["changements"]:
        with st.container(border=True):
            st.caption(changement["section"])
            st.markdown(f":red[− {changement['avant']}]")
            st.markdown(f":green[+ {changement['apres']}]")
            st.caption(f"→ {changement['pourquoi']}")


def page_cv() -> None:
    st.title("📄 CV adapté à une offre")
    if not profil_en_cache():
        st.info("Commence par importer ton CV dans la page **Profil**.")
        return
    if not cv_modele.CHEMIN_MODELE.exists():
        st.warning("Il manque le **modèle HTML** de ton CV (l'export de ton outil de design). Va dans la page **Profil**.")
        return

    with connexion() as c:
        offres = {f"{o['titre'][:70]}" + (f" · {o['score']}/100" if o["score"] is not None else ""): o["id"]
                  for o in stockage.offres_actives(c)}
    if not offres:
        st.info("Aucune offre en base : lance une collecte.")
        return
    libelle = st.selectbox("Offre visée", list(offres))
    offre_id = offres[libelle]

    with connexion() as c:
        precedents = stockage.cv_adaptes(c, offre_id)

    st.subheader("1. Compétences demandées et absentes de ton CV")
    if st.button("🔍 Analyser l'offre", help="Compare l'offre à ton profil (utilise le quota Claude)"):
        with st.spinner("Claude compare l'offre à ton profil..."):
            try:
                st.session_state[f"analyse-{offre_id}"] = competences.analyser_offre(offre_id)
            except ErreurLLM as erreur:
                st.error(str(erreur))
    if analyse := st.session_state.get(f"analyse-{offre_id}"):
        analyse = competences.analyser_offre(offre_id)  # relit les déclarations à jour (mise en cache)
        confirmer_competences(analyse)

    st.subheader("2. Générer le CV")
    st.caption("Claude ne modifie que les textes : le design, tes coordonnées, tes dates et tes chiffres restent intacts.")
    if st.button("✨ Générer le CV adapté", type="primary", help="1 à 4 min : réécriture, contrôle de la mise en page, PDF"):
        with st.status("Adaptation du CV...", expanded=True) as statut:
            try:
                resultat = cv_adapte.adapter(offre_id, progression=st.write)
                statut.update(label="CV adapté prêt", state="complete")
                st.rerun()
            except (ErreurLLM, cv_modele.ErreurModele) as erreur:
                statut.update(label="Échec", state="error")
                st.error(str(erreur))

    if precedents:
        st.subheader("Versions générées")
        for version in precedents:
            with st.expander(f"{date_lisible(version['date'])}" + (" · dernière" if version is precedents[0] else ""),
                             expanded=version is precedents[0]):
                if not Path(version["chemin_pdf"]).exists():
                    st.warning("Le fichier PDF a été supprimé.")
                    continue
                afficher_cv_adapte({"changements": json.loads(version["changements"]),
                                    "alertes": json.loads(version["alertes"]), "conseil": version["conseil"]},
                                   version["chemin_pdf"])


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
    st.markdown("##### Modèle de CV (pour le CV adapté)")
    if cv_modele.CHEMIN_MODELE.exists():
        st.success("Modèle en place : le CV adapté reprendra exactement ce design.")
    else:
        st.caption("Exporte ton CV en HTML depuis l'outil où tu l'as créé, puis importe-le ici.")
    export = st.file_uploader("Export HTML du CV", type="html", help="Le design est conservé tel quel ; seuls les textes seront adaptés")
    if export is not None and st.button("Importer ce modèle"):
        chemin_temporaire = cv_modele.CHEMIN_MODELE.with_suffix(".export.html")
        chemin_temporaire.write_bytes(export.getvalue())
        try:
            cv_modele.importer_export(chemin_temporaire)
            st.success("Modèle importé.")
        except cv_modele.ErreurModele as erreur:
            st.error(str(erreur))
        finally:
            chemin_temporaire.unlink(missing_ok=True)

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
    st.Page(page_suivi, title="Suivi et relances", icon="📬"),
    st.Page(page_entretien, title="Préparation d'entretien", icon="🎤"),
    st.Page(page_cv, title="CV adapté", icon="📄"),
    st.Page(page_profil, title="Profil", icon="👤"),
]).run()
