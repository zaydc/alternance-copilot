"""Collecte des offres d'alternance via l'API La bonne alternance.

1. rechercher() appelle l'API avec les filtres de recherche.
2. nettoyer_offre() / nettoyer_entreprise() transforment les résultats bruts en dictionnaires plats.
3. collecter() enregistre le tout dans SQLite.

Lancement (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m src.collecte
"""

import html
import math
import os
import re
import sys
from contextlib import closing

import httpx
from dotenv import load_dotenv

from src import stockage

API_LBA = "https://api.apprentissage.beta.gouv.fr/api"

# Centre de la recherche : Vigneux-sur-Seine (91270)
LATITUDE_CENTRE = 48.7021
LONGITUDE_CENTRE = 2.4274
RAYON_KM = 30
DEPARTEMENTS = ["75", "91", "92", "93", "94"]
# ROME 4.0 : dev fullstack, dev logiciel, data, chef de projet IT, support/systèmes, admin SI
CODES_ROME_OFFRES = ["M1827", "M1821", "M1811", "M1806", "M1802", "M1822"]
# Pour les entreprises, le code dev seul ramène des ESN / éditeurs (les autres codes ramènent banques et comptables)
CODES_ROME_ENTREPRISES = ["M1827"]


def texte_propre(valeur: str | None) -> str:
    """Convertit un texte HTML de l'API en texte brut lisible."""
    if not valeur:
        return ""
    # Les fins de blocs HTML deviennent des retours à la ligne, pour garder la structure
    texte = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", valeur, flags=re.IGNORECASE)
    texte = re.sub(r"<li[^>]*>", "- ", texte, flags=re.IGNORECASE)
    texte = re.sub(r"<[^>]+>", "", texte)  # supprime les balises restantes
    texte = html.unescape(texte)  # &amp; -> &, &eacute; -> é
    lignes = (re.sub(r"\s+", " ", ligne).strip() for ligne in texte.splitlines())
    return "\n".join(ligne for ligne in lignes if ligne)  # espaces normalisés, lignes vides retirées


def distance_km(latitude: float, longitude: float) -> float:
    """Distance à vol d'oiseau depuis le centre de recherche (formule de Haversine)."""
    rayon_terre = 6371
    phi1, phi2 = math.radians(LATITUDE_CENTRE), math.radians(latitude)
    delta_phi = math.radians(latitude - LATITUDE_CENTRE)
    delta_lambda = math.radians(longitude - LONGITUDE_CENTRE)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return round(2 * rayon_terre * math.asin(math.sqrt(a)), 1)


def nettoyer_offre(brute: dict) -> dict:
    """Ne garde que les champs utiles au matching, à l'affichage et à la candidature."""
    lieu = brute["workplace"]["location"]
    longitude, latitude = lieu["geopoint"]["coordinates"]
    offre = brute["offer"]
    contrat = brute["contract"]
    diplome = offre.get("target_diploma") or {}

    return {
        "id": brute["identifier"]["id"],
        "source": brute["identifier"]["partner_label"],
        "titre": texte_propre(offre["title"]),
        "entreprise": texte_propre(brute["workplace"]["name"]),
        "description_entreprise": texte_propre(brute["workplace"]["description"]),
        "adresse": lieu.get("address") or "",
        "latitude": latitude,
        "longitude": longitude,
        "distance_km": distance_km(latitude, longitude),
        "description": texte_propre(offre["description"]),
        "codes_rome": offre["rome_codes"],
        "niveau_diplome": diplome.get("label", ""),
        "types_contrat": contrat["type"],
        "debut_contrat": contrat["start"],
        "duree_mois": contrat["duration"],
        "teletravail": contrat["remote"],
        "date_publication": offre["publication"]["creation"],
        "date_expiration": offre["publication"]["expiration"],
        "url_candidature": brute["apply"]["url"],
    }


def nettoyer_entreprise(brute: dict) -> dict:
    """Entreprise susceptible de recruter sans offre publiée (piste de candidature spontanée)."""
    lieu = brute["workplace"]["location"]
    longitude, latitude = lieu["geopoint"]["coordinates"]
    naf = brute["workplace"]["domain"].get("naf") or {}

    return {
        "id": brute["identifier"]["id"],
        "siret": brute["workplace"]["siret"],
        "nom": texte_propre(brute["workplace"]["name"]),
        "adresse": lieu.get("address") or "",
        "latitude": latitude,
        "longitude": longitude,
        "distance_km": distance_km(latitude, longitude),
        "taille": brute["workplace"]["size"],
        "secteur": naf.get("label", ""),
        "telephone": brute["apply"]["phone"],
        "url_candidature": brute["apply"]["url"],
    }


def appeler_api(codes_rome: list[str]) -> dict:
    """Appelle la recherche de l'API avec la zone de recherche et les codes ROME donnés."""
    parametres = {
        "latitude": LATITUDE_CENTRE,
        "longitude": LONGITUDE_CENTRE,
        "radius": RAYON_KM,
        "romes": ",".join(codes_rome),
        "departements": DEPARTEMENTS,  # httpx répète le paramètre : departements=75&departements=91...
    }
    entetes = {"Authorization": f"Bearer {os.environ['LBA_API_TOKEN']}"}
    reponse = httpx.get(f"{API_LBA}/job/v1/search", params=parametres, headers=entetes, timeout=60)
    reponse.raise_for_status()
    resultats = reponse.json()
    for alerte in resultats["warnings"]:
        print(f"Avertissement API : {alerte['message']}")
    return resultats


def rechercher() -> tuple[list[dict], list[dict]]:
    """Renvoie (offres, entreprises), nettoyées et sans doublons, via deux appels ciblés."""
    jobs = appeler_api(CODES_ROME_OFFRES)["jobs"]
    recruteurs = appeler_api(CODES_ROME_ENTREPRISES)["recruiters"]

    # Un dictionnaire indexé par id élimine les doublons (même offre renvoyée par plusieurs sources)
    offres = {o["id"]: o for o in map(nettoyer_offre, jobs)}
    entreprises = {e["id"]: e for e in map(nettoyer_entreprise, recruteurs)}
    return list(offres.values()), list(entreprises.values())


def collecter() -> dict[str, int]:
    """Collecte les offres et entreprises, les enregistre dans SQLite et renvoie les compteurs."""
    offres, entreprises = rechercher()
    date_collecte = stockage.maintenant()
    # closing() ferme la connexion ; un simple « with connexion » ne ferait que valider la transaction
    with closing(stockage.connecter()) as connexion:
        nouvelles_offres = stockage.enregistrer(connexion, "offres", offres, date_collecte)
        nouvelles_entreprises = stockage.enregistrer(connexion, "entreprises", entreprises, date_collecte)
    return {
        "offres": len(offres),
        "nouvelles_offres": nouvelles_offres,
        "entreprises": len(entreprises),
        "nouvelles_entreprises": nouvelles_entreprises,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    bilan = collecter()
    print(f"{bilan['offres']} offres collectées, dont {bilan['nouvelles_offres']} nouvelles")
    print(f"{bilan['entreprises']} entreprises collectées, dont {bilan['nouvelles_entreprises']} nouvelles")


if __name__ == "__main__":
    main()
