"""Hunter.io : trouver l'adresse professionnelle d'un contact quand l'entreprise n'en publie aucune.

Chaque recherche coûte un crédit (50 par mois sur le plan gratuit) : tout résultat est donc mis en cache.
L'adresse d'une personne nommée est une donnée personnelle obtenue sans elle : le premier message doit
indiquer d'où elle vient et permettre de refuser d'être recontacté (RGPD, article 14).
"""

import json
import os
import re
import unicodedata
from contextlib import closing
from urllib.parse import urlparse

import httpx

from src import stockage

API_HUNTER = "https://api.hunter.io/v2"
MENTION_RGPD = ("J'ai trouvé votre adresse professionnelle via un annuaire en ligne. "
                "Dites-moi si vous préférez ne pas être recontacté.")


class ErreurHunter(RuntimeError):
    pass


def _appel(chemin: str, parametres: dict) -> dict:
    cle = os.environ.get("HUNTER_API_KEY")
    if not cle:
        raise ErreurHunter("Aucune clé Hunter : ajoute HUNTER_API_KEY dans .env")
    reponse = httpx.get(f"{API_HUNTER}/{chemin}", params={**parametres, "api_key": cle}, timeout=30)
    corps = reponse.json()
    if reponse.status_code != 200:
        details = corps.get("errors", [{}])[0].get("details", reponse.text[:200])
        raise ErreurHunter(f"Hunter ({reponse.status_code}) : {details}")
    return corps["data"]


def _en_cache(cle: str, chemin: str, parametres: dict) -> dict:
    """Appelle Hunter une seule fois par recherche : le résultat est conservé en base."""
    with closing(stockage.connecter()) as connexion:
        garde = stockage.hunter_en_cache(connexion, cle)
        if garde is not None:
            return garde
        resultat = _appel(chemin, parametres)
        stockage.enregistrer_hunter(connexion, cle, resultat)
    return resultat


def quota() -> dict:
    """Crédits restants (gratuit, non décompté)."""
    requetes = _appel("account", {})["requests"]
    return {"recherches": requetes["searches"]["remaining"], "verifications": requetes["verifications"]["remaining"]}


def domaine(site_web: str | None, adresses: list[str] | None = None) -> str | None:
    """Domaine de l'entreprise, depuis son site ou une adresse déjà connue."""
    if site_web:
        hote = urlparse(site_web if "//" in site_web else f"https://{site_web}").hostname or ""
        if hote:
            return hote.removeprefix("www.")
    for adresse in adresses or []:
        if "@" in adresse:
            return adresse.split("@")[1]
    return None


def trouver_email(entreprise_id: str, domaine_entreprise: str, prenom: str, nom: str) -> dict | None:
    """Adresse la plus probable pour cette personne (1 crédit si trouvée)."""
    resultat = _en_cache(f"{entreprise_id}|email-finder|{domaine_entreprise}|{prenom}|{nom}".lower(),
                         "email-finder", {"domain": domaine_entreprise, "first_name": prenom, "last_name": nom})
    return resultat if resultat.get("email") else None


def adresses_du_domaine(entreprise_id: str, domaine_entreprise: str) -> dict:
    """Adresses connues pour ce domaine et format habituel (1 crédit)."""
    return _en_cache(f"{entreprise_id}|domain-search|{domaine_entreprise}", "domain-search",
                     {"domain": domaine_entreprise, "limit": 10})


def verifier(email: str) -> dict:
    """État de délivrabilité (compté sur le quota de vérifications, séparé des recherches)."""
    return _en_cache(f"verifier|{email}".lower(), "email-verifier", {"email": email})


def resultats_connus(entreprise_id: str) -> list[dict]:
    """Adresses déjà trouvées pour cette entreprise, sans nouvel appel : [{email, score, poste, statut}]."""
    with closing(stockage.connecter()) as connexion:
        recherches = stockage.hunter_par_entreprise(connexion, entreprise_id)
    adresses: dict[str, dict] = {}
    for recherche in recherches:
        donnees = json.loads(recherche["resultat"])
        trouvees = [donnees] if donnees.get("email") else donnees.get("emails", [])
        for trouvee in trouvees:
            adresse = trouvee.get("email") or trouvee.get("value")
            if not adresse:
                continue
            poste = trouvee.get("position") or ""
            if prenom := (trouvee.get("first_name") or ""):
                poste = f"{prenom} {trouvee.get('last_name') or ''} · {poste}".strip(" ·")
            adresses[adresse] = {
                "email": adresse,
                "score": trouvee.get("score") or trouvee.get("confidence") or 0,
                "poste": poste,
                "statut": (trouvee.get("verification") or {}).get("status") or "inconnu",
                "sources": len(trouvee.get("sources") or []),
            }
    return sorted(adresses.values(), key=lambda a: -a["score"])


def format_lisible(pattern: str | None) -> str:
    """« {first}.{last} » → « prenom.nom »."""
    if not pattern:
        return "inconnu"
    return re.sub(r"\{(\w+)\}", lambda m: {"first": "prenom", "last": "nom", "f": "p", "l": "n"}.get(m.group(1), m.group(1)), pattern)


def format_connu(entreprise_id: str) -> str | None:
    """Format des adresses de l'entreprise (ex. « {first}.{last} »), s'il a déjà été trouvé."""
    with closing(stockage.connecter()) as connexion:
        for recherche in stockage.hunter_par_entreprise(connexion, entreprise_id):
            if "domain-search" in recherche["cle"] and (motif := json.loads(recherche["resultat"]).get("pattern")):
                return motif
    return None


def construire_adresse(motif: str, prenom: str, nom: str, domaine_entreprise: str) -> str:
    """Applique le format de l'entreprise à un nom : « {first}.{last} » + Olivier Martin → olivier.martin@…"""
    def sans_accents(valeur: str) -> str:
        plat = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z]", "", plat.lower())

    prenom, nom = sans_accents(prenom), sans_accents(nom)
    parties = {"first": prenom, "last": nom, "f": prenom[:1], "l": nom[:1]}
    return re.sub(r"\{(\w+)\}", lambda m: parties.get(m.group(1), ""), motif) + f"@{domaine_entreprise}"


def verifier_et_retenir(entreprise_id: str, adresse: str, prenom: str, nom: str) -> dict:
    """Vérifie une adresse déduite et la conserve : elle apparaîtra ensuite comme les autres."""
    verification = verifier(adresse)
    resultat = {"email": adresse, "score": verification.get("score") or 0, "first_name": prenom, "last_name": nom,
                "position": "adresse déduite du format de l'entreprise",
                "verification": {"status": verification.get("status")}, "sources": verification.get("sources") or []}
    with closing(stockage.connecter()) as connexion:
        stockage.enregistrer_hunter(connexion, f"{entreprise_id}|deduite|{adresse}".lower(), resultat)
    return resultat
