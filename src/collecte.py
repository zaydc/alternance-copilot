"""Collecte des offres d'alternance via l'API La bonne alternance.

Étape 1 : transformer une offre brute de l'API en dictionnaire propre et plat.
"""

import html
import math
import re

# Centre de la recherche : Vigneux-sur-Seine (91270)
LATITUDE_CENTRE = 48.7021
LONGITUDE_CENTRE = 2.4274


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
