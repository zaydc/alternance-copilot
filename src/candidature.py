"""Candidature spontanée : recherche web sur l'entreprise, contacts publiés, email et note LinkedIn.

Lancement (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m src.candidature "nom de l'entreprise"
"""

import sys
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src import contacts, stockage
from src.llm_client import OUTILS_WEB, ErreurLLM, generer_json
from src.profil import DOSSIER_DATA, charger_profil, profil_complet

# Coordonnées ajoutées en fin d'email : jamais envoyées à Claude (minimisation), jamais dans Git (data/)
CHEMIN_SIGNATURE = DOSSIER_DATA / "signature.txt"


class EmailPublie(BaseModel):
    adresse: str
    usage: str = Field(description="recrutement, contact général, personne nommée...")
    source: str = Field(description="URL exacte de la page où l'adresse est écrite")
    verifiee: bool | None = Field(default=None, description="Ne pas remplir : vérifié ensuite par le programme")


class EmailSpontane(BaseModel):
    ce_que_fait: str = Field(description="Activité de l'entreprise en 1 à 2 phrases, d'après les sources consultées")
    personnalise: bool = Field(description="false si aucune information fiable n'a été trouvée sur cette entreprise")
    site_web: str | None = Field(description="Site officiel de l'entreprise, null si introuvable")
    page_carrieres: str | None = Field(description="Page carrières / recrutement / contact, null si introuvable")
    emails_publics: list[EmailPublie] = Field(description="Adresses écrites telles quelles sur une page consultée")
    sources: list[str] = Field(description="URL réellement consultées")
    objet: str = Field(description="Objet d'email précis, moins de 80 caractères")
    corps: str = Field(description="Corps de l'email, 120 à 170 mots, sans signature")
    note_linkedin: str = Field(max_length=300, description="Note d'invitation LinkedIn, 300 caractères maximum")


SYSTEME = """Tu aides un étudiant à écrire un email de candidature spontanée pour une alternance.

1. Recherche d'abord l'entreprise sur le web (site officiel, annuaire-entreprises.data.gouv.fr, actualités) :
   activité, produits ou clients, technologies si disponibles. Vérifie qu'il s'agit bien de la bonne entreprise
   (nom ET ville ou SIRET). Limite-toi à quelques recherches.
   Relève aussi les moyens de contact PUBLIÉS par l'entreprise : page carrières ou contact, adresses email
   (recrutement@, jobs@, contact@...). Ne reporte une adresse que si elle est écrite sur une page que tu as
   consultée, avec l'URL de cette page. Ne devine et ne construis JAMAIS d'adresse (ex. prenom.nom@domaine).
2. Écris ensuite l'email, en français, en vouvoyant le recruteur :
   - 120 à 170 mots, sans formule creuse (« je me permets », « votre entreprise dynamique »…) ;
   - une accroche liée à un fait précis et vérifié sur l'entreprise ;
   - 1 ou 2 preuves tirées du profil (expérience ou projet chiffré) reliées à leur activité ;
   - le rythme d'alternance et une disponibilité immédiate ;
   - une demande concrète : un court échange téléphonique ou en visio.
3. Écris une note d'invitation LinkedIn (300 caractères maximum) pour un recruteur ou un responsable technique
   de l'entreprise : même accroche, une preuve, la demande d'échange.
4. Exactitude, dans l'email comme dans la note :
   - reprends le rôle du candidat tel qu'il est écrit dans le profil, sans l'embellir
     (« tests et débogage de scripts » ne devient pas « j'ai développé des scripts ») ;
   - ne cite un chiffre ou une date sur l'entreprise que tel qu'il figure dans une source
     (ne confonds pas l'âge de l'entreprise avec l'expérience de ses fondateurs).
   N'invente jamais rien sur l'entreprise. Si tu n'as rien trouvé de fiable, mets personnalise à false
   et écris un email honnête basé sur le secteur, sans faux détails.
Ne mets ni signature ni coordonnées : elles seront ajoutées automatiquement."""


def generer_email(entreprise, profil_json: str) -> EmailSpontane:
    prompt = (
        f"## Entreprise ciblée\n"
        f"Nom : {entreprise['nom']}\n"
        f"SIRET : {entreprise['siret']}\n"
        f"Adresse : {entreprise['adresse']}\n"
        f"Secteur (code NAF) : {entreprise['secteur']}\n"
        f"Tranche d'effectif : {entreprise['taille']}\n\n"
        f"## Profil du candidat\n{profil_json}"
    )
    email = generer_json(prompt, SYSTEME, EmailSpontane, outils=OUTILS_WEB)
    # Garde-fou : on vérifie nous-mêmes que chaque adresse figure bien sur sa page source
    for publie in email.emails_publics:
        publie.verifiee = contacts.verifier_email_publie(publie.adresse, publie.source)
    return email


def rediger_email(connexion, entreprise) -> EmailSpontane:
    """Génère l'email pour cette entreprise et l'historise dans la table emails."""
    profil, _ = charger_profil()
    email = generer_email(entreprise, profil_complet(profil))
    stockage.enregistrer_email(
        connexion,
        {"entreprise_id": entreprise["id"], **email.model_dump(), "date": stockage.maintenant()},
    )
    return email


def lire_signature(chemin: Path = CHEMIN_SIGNATURE) -> str:
    return chemin.read_text(encoding="utf-8").strip() if chemin.exists() else "[Signature : créer data/signature.txt]"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")  # messages de sys.exit()
    load_dotenv()
    if len(sys.argv) != 2:
        sys.exit('Usage : python -m src.candidature "nom de l\'entreprise"')

    with closing(stockage.connecter()) as connexion:
        trouvees = stockage.chercher_entreprises(connexion, sys.argv[1])
        if not trouvees:
            sys.exit(f"Aucune entreprise ne correspond à « {sys.argv[1]} »")
        if len(trouvees) > 1:
            print(f"{len(trouvees)} entreprises correspondent, utilisation de la plus proche.")
        entreprise = trouvees[0]
        print(f"Recherche et rédaction pour {entreprise['nom']} ({entreprise['adresse']})...\n")

        try:
            email = rediger_email(connexion, entreprise)
        except ErreurLLM as erreur:
            sys.exit(f"❌ {erreur}")

    if not email.personnalise:
        print("⚠️  Aucune information fiable trouvée : email générique, à personnaliser à la main.\n")
    print(f"Ce que fait l'entreprise : {email.ce_que_fait}")
    print("Sources :", *email.sources, sep="\n  - ")
    print(f"\n{'-' * 60}\nObjet : {email.objet}\n\n{email.corps}\n\n{lire_signature()}\n{'-' * 60}")
    print(f"({len(email.corps.split())} mots)")


if __name__ == "__main__":
    main()
