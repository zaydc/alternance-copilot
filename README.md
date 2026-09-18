# Alternance Copilot

Une application locale qui m'aide à trouver mon alternance : elle récupère les offres, les note par rapport à
mon CV, m'aide à écrire mes candidatures, suit mes relances, adapte mon CV à chaque offre et me fait passer
des entretiens blancs.

Je l'ai construite parce que chercher une alternance en développement mi-septembre, c'est fastidieux : il reste
peu d'offres, beaucoup viennent en réalité d'écoles qui cherchent à remplir leurs formations, et on perd un temps
fou à retrouver qui on a relancé et quand.

> **Projet personnel, usage local.** Le jeton Claude vient de mon abonnement personnel : l'application n'est pas
> faite pour être déployée en ligne. Mon CV, mes candidatures et mes clés restent sur mon PC.

---

## Ce que ça fait

| Page | À quoi ça sert |
|---|---|
| 🏆 **Offres** | Les offres collectées, notées sur 100 et classées, avec la justification de la note et les points de vigilance |
| 🏢 **Candidatures spontanées** | Les entreprises du numérique susceptibles de recruter : qui contacter, un email personnalisé, une note LinkedIn |
| 📬 **Suivi et relances** | L'état de chaque candidature, et la relance rédigée automatiquement 7 jours après l'envoi |
| 🎤 **Préparation d'entretien** | Un chatbot qui joue le recruteur de l'entreprise visée, avec un retour après chaque réponse |
| 📄 **CV adapté** | Mon CV réécrit pour une cible précise — offre collectée, offre collée depuis LinkedIn ou **entreprise visée en candidature spontanée** — dans le même design, exporté en PDF |
| 👤 **Profil** | Import du CV, profil extrait, signature des emails |

Chaque matin, une tâche planifiée Windows collecte les nouvelles offres. La notation par Claude, elle, ne tourne
que le lundi, le mercredi et le vendredi, pour ménager mon quota.

## Comment ça marche

```
        CV (PDF)                    API La bonne alternance
           │                                  │
           ▼                                  ▼
   extraction du profil            collecte + nettoyage + filtres
   (Claude → JSON validé)          (doublons, écoles/CFA, distance)
           │                                  │
           └──────────────┬───────────────────┘
                          ▼
                     SQLite (10 tables)
                          │
     ┌────────────────────┼─────────────────────┬────────────────────┐
     ▼                    ▼                     ▼                    ▼
  notation           emails +               agent de              CV adapté
  des offres         contacts               préparation           (HTML → PDF)
  (Claude, par      (Claude + web)          d'entretien           (Claude + Edge)
   lots de 10)                              (Claude + 5 outils)
     └────────────────────┴─────────────────────┴────────────────────┘
                          ▼
                   interface Streamlit (locale)
```

**Les modules** (`src/`, 15 fichiers, environ 3 000 lignes de Python) :

| Module | Rôle |
|---|---|
| `collecte.py` | Appels à l'API, nettoyage du HTML, distance à vol d'oiseau, exclusion des écoles |
| `stockage.py` | SQLite : schéma, migrations, toutes les requêtes |
| `profil.py` | Lecture du CV (pypdf) et extraction du profil par Claude, avec cache |
| `notation.py` | Notation des offres par lots, score global pondéré |
| `candidature.py` / `contacts.py` | Emails spontanés, contacts publiés, dirigeants, liens LinkedIn |
| `relance.py` | Relances des candidatures sans réponse |
| `hunter.py` | Recherche d'une adresse nominative (Hunter.io), avec cache et quota |
| `assistant.py` | L'agent de préparation d'entretien et ses 5 outils |
| `competences.py` | Compétences demandées par l'offre et absentes du CV |
| `cv_modele.py` / `cv_segments.py` / `cv_adapte.py` | Modèle HTML du CV, découpage en segments, réécriture contrôlée |
| `automatisation.py` | Tâche quotidienne (collecte, notation, journal) |
| `llm_client.py` | **Le seul module qui connaît le SDK de Claude** |

## Installation

Il faut Python 3.12, un abonnement Claude Pro, un compte sur l'API La bonne alternance, et Microsoft Edge
(déjà présent sur Windows, il sert à produire les PDF).

```bash
git clone https://github.com/zaydc/alternance-copilot.git
cd alternance-copilot
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Installer la CLI Claude, puis générer le jeton :

```powershell
irm https://claude.ai/install.ps1 | iex
claude setup-token
```

Copier `.env.example` en `.env` et remplir les deux jetons :

```
CLAUDE_CODE_OAUTH_TOKEN=...   # donné par claude setup-token
LBA_API_TOKEN=...             # https://api.apprentissage.beta.gouv.fr
HUNTER_API_KEY=...            # facultatif : trouver une adresse quand l'entreprise n'en publie aucune
```

Vérifier que tout répond, puis lancer l'application :

```powershell
.venv\Scripts\python.exe scripts\test_connexions.py
.venv\Scripts\streamlit.exe run app.py      # ou double-clic sur « Alternance Copilot.bat »
```

Pour activer la collecte automatique : double-clic sur `Activer la collecte automatique.bat`.

## Les choix que j'ai faits, et pourquoi

**Le score n'est pas calculé par le LLM.** Claude note trois critères qu'il faut comprendre pour évaluer
(adéquation technique, niveau de diplôme, rythme) ; la distance et le score global pondéré
(technique 55 %, niveau 20 %, distance 15 %, rythme 10 %) sont calculés en Python. C'est déterministe, gratuit,
et les poids se règlent dans une seule constante.

**Chaque appel au LLM renvoie du JSON validé.** Je décris la réponse attendue avec Pydantic, j'envoie le schéma
à Claude, et je revalide la réponse à l'arrivée. Une réponse mal formée est détectée tout de suite.

**L'effort de réflexion est réglé tâche par tâche.** Le SDK expose un paramètre `effort` : je le mets à `low` pour
les tâches guidées par un schéma (notation, raccourcissement, extraction du CV) et à `medium` pour la réécriture du CV
et les emails. Résultat mesuré : un CV adapté passe de 3 min 50 à 46 s, sans perte de qualité. J'ai aussi comparé
Haiku à Sonnet sur la notation : Haiku est plus lent (32 s contre 9 s), produit 3,7 fois plus de jetons en sortie et
note moins justement, donc je suis resté sur Sonnet.

**Tout est mis en cache dans SQLite.** Une offre déjà notée pour le même CV n'est jamais renvoyée à Claude.
Les limites de l'abonnement Pro sont partagées avec claude.ai, donc chaque appel compte.

**Les outils de l'agent sont vraiment restreints.** Dans le SDK, `allowed_tools` autorise sans confirmation,
mais ne restreint rien : c'est `tools` qui fixe les outils disponibles. Avec `tools=[]`, Claude n'a aucun accès aux
fichiers ni au shell. Pour les recherches d'entreprise, je n'ouvre que `WebSearch` et `WebFetch`, en lecture seule.

**Pas de LangChain.** Ses modèles Claude demandent une clé API payante, incompatible avec le jeton d'abonnement.
L'agent est donc écrit avec le Claude Agent SDK, avec des outils Python exposés en interne.

**Une adresse nominative plutôt qu'une boîte générique.** Quand l'entreprise ne publie aucune adresse, l'application
peut interroger Hunter.io (facultatif) pour l'adresse du dirigeant, dont le nom vient du registre officiel. Chaque
recherche coûte un crédit, donc les résultats sont mis en cache, la recherche se lance sur clic, et le score de
confiance et l'état de délivrabilité sont affichés. L'email indique alors d'où vient l'adresse et comment refuser
d'être recontacté, comme l'exige l'article 14 du RGPD.

**Pas de scraping LinkedIn**, alors que j'en avais envie au départ. C'est interdit par les conditions de LinkedIn,
et la CNIL a sanctionné la société KASPR de 240 000 € en décembre 2024 pour avoir aspiré des coordonnées sur ce
réseau. À la place : les dirigeants via l'API officielle « Recherche d'entreprises », les adresses **publiées**
par l'entreprise (vérifiées sur leur page source), et des liens de recherche LinkedIn que j'ouvre moi-même.

**Les offres d'écoles sont filtrées automatiquement.** En analysant 387 offres réelles, j'ai vu que les
organismes de formation publient au nom d'entreprises clientes : le secteur affiché est celui du client, donc un
filtre par secteur ne sert à rien. Le champ `is_delegated` de l'API, lui, marquait 98 offres, toutes d'écoles.

**Le CV est adapté sans toucher au design.** Mon CV est une page HTML à mise en page fixe. Le programme la découpe
en 56 segments, n'envoie à Claude que les 26 textes modifiables, puis réinjecte les réponses. Le design, mes
coordonnées, mes dates et mes chiffres ne sont jamais transmis pour modification.

## Les garde-fous du CV adapté

Claude peut reformuler et mettre en avant ; il ne peut pas inventer. Le programme refuse et signale :

- toute modification d'une **zone protégée** (nom, coordonnées, dates, formation, intitulés, chiffres clés) ;
- tout **chiffre absent de mon parcours** (« 80 sources » alors que mon CV dit 47) ;
- toute **compétence non confirmée** par moi (« Java » est bloqué, « JavaScript » reste autorisé) ;
- tout **élément de liste** qui ne vient ni de mon profil ni d'une compétence confirmée.

Si une offre demande une compétence absente de mon CV, l'application me pose la question avant d'écrire quoi que
ce soit. Je peux joindre une preuve (description, lien GitHub, fichier) que Claude examine.

Enfin, la mise en page est **mesurée dans le navigateur** avant l'export : si un texte déborde d'une carte ou
pousse un bloc, il est raccourci, et à défaut l'original est conservé. Le PDF doit tenir sur une page.

## Vie privée

- `.env`, le CV, la base de données et les CV générés sont dans `data/`, **exclu de Git**.
- Le profil extrait du CV **ne contient ni nom, ni email, ni téléphone** : ces informations ne servent pas à noter
  une offre. La signature des emails est ajoutée localement, après la génération.
- Le serveur Streamlit n'écoute que sur `localhost`.

## Tests

Les modules sont testés là où une erreur coûterait cher :

- les **garde-fous** du CV adapté (zone protégée, chiffre inventé, compétence non confirmée, gras cassé) ;
- le **détecteur d'adresses email** publiées, y compris masquées (`contact [at] exemple.fr`), sur 9 cas ;
- la **logique de relance** (J+7, deux relances maximum, arrêt si réponse) sur une base temporaire ;
- les **pages Streamlit**, sans navigateur, avec `streamlit.testing.v1.AppTest` et un assistant simulé,
  pour ne pas consommer de quota.

## Limites connues

- **Windows uniquement** : tâche planifiée et Edge pour les PDF.
- **Une seule source d'offres** (La bonne alternance, qui agrège déjà France Travail).
- **Le quota Claude Pro est la vraie contrainte** : une notation de 10 offres prend environ 1 min 30, un CV adapté
  3 à 4 minutes.
- **La conversation d'entretien est perdue** si je recharge la page.
- Un seul CV à la fois, et pas de pondération réglable depuis l'interface.

## Ce que ce projet m'a appris

- Faire confiance à un LLM **avec des garde-fous** : sortie typée, vérifications côté programme, et le calcul
  déterministe fait en Python plutôt que par le modèle.
- Lire la documentation d'une option de sécurité au lieu de se fier à son nom : `allowed_tools` ne restreint rien.
- Regarder les vraies données avant d'écrire une règle : le filtre des écoles vient de l'analyse de 387 offres,
  pas d'une intuition.
- Dire non à une fonctionnalité (le scraping LinkedIn) et proposer une alternative légale.

Ce projet a été développé en binôme avec Claude Code, en gardant la main sur l'architecture, les choix techniques
et les garde-fous. Le journal de bord complet, avec les décisions et les impasses, est dans
[JOURNAL_PROJET.md](JOURNAL_PROJET.md).
