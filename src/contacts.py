"""Trouver qui contacter dans une entreprise, uniquement à partir de sources légitimes.

- Dirigeants : API officielle « Recherche d'entreprises » (data.gouv.fr, gratuite, sans clé).
- Adresses email : seulement celles PUBLIÉES par l'entreprise (trouvées par Claude, puis vérifiées ici).
- LinkedIn : liens de recherche préremplis que l'utilisateur ouvre lui-même. Pas de scraping : c'est interdit
  par les conditions de LinkedIn et sanctionné par la CNIL (KASPR, 240 000 €, décembre 2024).
"""

import re
from urllib.parse import quote

import httpx

API_ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"


def dirigeants(siret: str | None) -> list[dict]:
    """Dirigeants déclarés au registre national des entreprises (nom, prénoms, qualité)."""
    if not siret:
        return []
    reponse = httpx.get(API_ENTREPRISES, params={"q": siret[:9]}, timeout=15)  # SIREN = 9 premiers chiffres du SIRET
    reponse.raise_for_status()
    resultats = reponse.json()["results"]
    if not resultats:
        return []
    return [
        # Minimisation : ni date de naissance ni nationalité, inutiles pour prendre contact
        {
            "nom": (d.get("nom") or d.get("denomination") or "").title(),
            "prenoms": (d.get("prenoms") or "").title(),
            "qualite": d.get("qualite") or "",
        }
        for d in resultats[0].get("dirigeants", [])
    ]


def liens_linkedin(nom_entreprise: str, personnes: list[dict]) -> list[tuple[str, str]]:
    """Recherches LinkedIn à ouvrir manuellement : (libellé, URL)."""
    def recherche(mots_cles: str) -> str:
        return f"https://www.linkedin.com/search/results/people/?keywords={quote(mots_cles)}"

    liens = [
        ("Recrutement / RH", recherche(f"{nom_entreprise} recrutement RH talent")),
        ("Tech (CTO, lead dev)", recherche(f"{nom_entreprise} CTO lead developer")),
        ("Tous les salariés", recherche(nom_entreprise)),
    ]
    for personne in personnes[:2]:
        nom_complet = f"{personne['prenoms'].split(' ')[0]} {personne['nom']}".strip()
        liens.append((f"{nom_complet} ({personne['qualite'] or 'dirigeant'})", recherche(f"{nom_complet} {nom_entreprise}")))
    return liens


def adresse_dans_texte(adresse: str, texte: str) -> bool:
    """Cherche l'adresse, y compris masquée contre les robots : « contact [at] domaine.fr », « contact(arobase)domaine.fr »."""
    utilisateur, _, domaine = adresse.lower().strip().partition("@")
    arobase = r"(?:@|\s*[\[(]\s*(?:at|arobase|@)\s*[\])]\s*|\s+(?:at|arobase)\s+)"
    # Limites : pas de caractère d'adresse juste avant, ni de suite du domaine juste après (évite « x@site.fr.autre.com »)
    motif = rf"(?<![\w.+-]){re.escape(utilisateur)}{arobase}{re.escape(domaine)}(?![\w-]|\.\w)"
    return re.search(motif, texte.lower()) is not None


def verifier_email_publie(adresse: str, url_source: str) -> bool | None:
    """True si l'adresse figure bien sur la page source, False sinon, None si la page est inaccessible.

    Garde-fou contre une adresse inventée par le LLM.
    """
    try:
        page = httpx.get(url_source, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        page.raise_for_status()
    except httpx.HTTPError:
        return None
    return adresse_dans_texte(adresse, page.text)
