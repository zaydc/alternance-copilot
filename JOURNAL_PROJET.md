# Journal de projet — Alternance Copilot

> Récapitulatif de la session de cadrage avec Claude (Tech Lead / Mentor).
> Dernière mise à jour : 2026-09-17

## Contexte

- Étudiant en BUT Informatique, recherche d'alternance en **IA Générative & Automatisation Métiers**.
- Objectif : un projet portfolio technique, simple mais efficace, **utile pour sa propre recherche**.

## Règles de collaboration

1. Ne jamais générer tout le code d'un coup.
2. Avancer en petites étapes : Idéation > Setup > Data > LangChain > UI.
3. Chaque message se termine par une action, un choix ou une question.
4. Toujours expliquer brièvement le « pourquoi » technique.
5. Valider l'avancement avant de passer à l'étape suivante.

## Étape 1 — Cadrage ✅

### Idées écartées
Assistant RH (Code du travail), Copilote support client (Bitext), Veille appels d'offres (BOAMP).

### Idée retenue : Alternance Copilot
Logiciel local où l'on importe son CV, qui récupère les offres d'alternance via l'API
**La bonne alternance**, les classe par pertinence et propose un chatbot + la génération
de lettres de motivation.

### Architecture

```
CV.pdf ──▶ 1. Extraction (Claude, JSON validé) ──▶ Profil JSON
API La bonne alternance ──▶ 2. Collecte + nettoyage ──▶ SQLite + Chroma
3. Matching en 2 temps : embeddings locaux → top 30, puis Claude note + justifie (par lots)
4. Chatbot agent (outils : chercher_offres, detail_offre, mon_profil)
5. Génération : lettre de motivation / message recruteur
Interface : Streamlit (local)
```

### Décisions actées

| Sujet | Décision | Pourquoi |
|---|---|---|
| Accès LLM | `claude setup-token` (abonnement Pro) + **Claude Agent SDK** | 0 €, pas de clé API payante |
| Diffusion | **Usage local uniquement**, pas de publication | Jeton lié à l'abonnement : pas autorisé dans une app publiée |
| Embeddings | `sentence-transformers` multilingue, en local | Anthropic n'a pas d'embeddings ; gratuit |
| Base vectorielle | Chroma via LangChain | Local + LangChain demandé par les offres |
| Stockage | SQLite | Déduplication + cache des notations |
| Lecture CV | `pypdf` | Simple |
| UI | Streamlit | Rapide |
| Abstraction | Module `llm_client.py` | Changer de fournisseur (clé API) sans toucher au reste |

### Points de vigilance
- **Limites Pro partagées** avec claude.ai → cache SQLite + notation par lots de 10 offres.
- **Moindre privilège** : l'agent n'a accès qu'à nos outils (`allowed_tools`), pas à Bash/Edit.
- **RGPD** : CV réel et `.env` jamais dans Git (`.gitignore`) ; CV fictif pour les démos.
- **Dossier du projet** : `C:\Users\zaydc\Documents\chatbot` (hors OneDrive, vérifier que Documents n'est pas synchronisé).

### Périmètre
- **MVP** : API La bonne alternance, 1 CV, matching 2 temps, chatbot agent 3 outils, lettre de motivation, Streamlit local.
- **V2** : API France Travail, plusieurs CV, pondération réglable, mémoire du chat, suivi des candidatures.

## Étape 2 — Setup ✅

### Vérifié
- Python **3.12.10** ✅ (3.14 aussi présente → utiliser explicitement la 3.12)
- Git **2.55.0** ✅
- CLI `claude` : **2.1.274** ✅

### À faire
- [x] Installer la CLI
- [x] Vérifier : `claude --version`
- [x] Générer le jeton : `claude setup-token` (le garder secret)
- [x] Créer un compte sur l'espace développeurs La bonne alternance (jeton API)
- [ ] Donner les critères de matching prioritaires (ville/distance, rythme, stack, taille d'entreprise)
- [x] Setup partie 2 : `git init` (branche `main`), `.gitignore`, `.env.example` + `.env`, venv Python 3.12 (`.venv`)
- [x] Remplir `.env` avec les deux jetons
- [x] Configurer l'identité Git, puis premier commit
- [x] Dépendances minimales (`requirements.txt`) : `claude-agent-sdk`, `httpx`, `python-dotenv`
- [x] `scripts/test_connexions.py` : Claude répond « OK » ✅, La bonne alternance renvoie des offres ✅

### Critères de matching (en cours)
- **Zone** : départements **75, 91, 92, 93, 94** (pas au-delà de La Défense) → filtre `departements` + rayon **30 km** autour de Vigneux-sur-Seine (91270)
  - Test : 20 km = 15 offres ; 30 km = 29 offres (dont doublons) + 150 entreprises
- **Profil** : BUT Informatique 3e année (niveau 6), développeur full stack + IA/data (LangChain, RAG, ETL)
- **Rythme** : 1 sem. école / 1 sem. entreprise
- **Taille d'entreprise** : sans importance (recherche urgente)

### Codes ROME (2026-09-17)
- L'API utilise le **ROME 4.0** : M1805 (ancien « Études et développement informatique ») ne renvoie plus rien.
- Scan M1801–M1849, 20 km autour de Vigneux : **~35 offres informatiques seulement** au total.
  Codes utiles : M1827 (dev fullstack), M1821 (dev logiciel), M1811 (data), M1806 (chef de projet IT),
  M1802 (support / systèmes), M1822, M1830, M1838, M1846 (cyber / réseaux).
- Nettoyage nécessaire : **doublons** (même offre renvoyée plusieurs fois) et **entités HTML** dans les titres (`&amp;`).
- Des offres hors profil passent le filtre ROME (RH, communication) → c'est la notation par Claude qui les écartera.
- Les `recruiters` (entreprises susceptibles de recruter sans offre publiée) sont une piste pour les candidatures spontanées.

### Notes API La bonne alternance
- Base : `https://api.apprentissage.beta.gouv.fr/api`, en-tête `Authorization: Bearer <jeton>`
- Spécification OpenAPI : `https://api.apprentissage.beta.gouv.fr/api/documentation/json`
- `GET /geographie/v1/commune/search?code=91270` → centre GPS de la commune (`[longitude, latitude]`)
- `GET /job/v1/search?latitude=&longitude=&radius=` (+ `romes`, `rncp`, `target_diploma_level`) → `jobs`, `recruiters`, `warnings`
- Limite : **60 appels/min** ; 150 résultats max par source (450 au total)
- Le type de clé (**sandbox** ou **production**) détermine l'environnement : une clé sandbox renvoie des offres de test
- Clé **production** en place ✅ (la sandbox renvoyait des offres fictives mal localisées)
- Sans filtre métier, 20 km autour de Vigneux = **450 offres** (plafond atteint) → il faudra filtrer par codes ROME (métiers informatique/data)

## Étape 3 — Data 🚧 (en cours)

- [x] `src/collecte.py` : `nettoyer_offre()` (champs utiles, HTML → texte, distance depuis Vigneux)
  - Test réel : 29 offres brutes → **18 uniques** (doublons = même `identifier.id`)
  - Entreprise souvent vide pour France Travail (offres anonymisées)
- [ ] Appel API avec les filtres (départements, 30 km, codes ROME)
- [ ] Stockage SQLite (dédup sur `id`) + entreprises (`recruiters`)

## Sources
- https://api.apprentissage.beta.gouv.fr/fr
- https://code.claude.com/docs/en/authentication
- https://code.claude.com/docs/en/agent-sdk/overview
- https://code.claude.com/docs/en/agent-sdk/structured-outputs
- https://code.claude.com/docs/en/setup
