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
3. Matching : Claude note + justifie toutes les offres (par lots de 10)
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
| Matching (révisé 2026-09-17) | **Claude note directement toutes les offres** (pas de présélection par embeddings) | ~18 offres seulement ; embeddings + Chroma réservés au chatbot (recherche sémantique) |
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
- **MVP** : API La bonne alternance, 1 CV, notation des offres par Claude, chatbot agent 3 outils, lettre de motivation, Streamlit local.
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
- [x] Donner les critères de matching prioritaires (ville/distance, rythme, stack, taille d'entreprise)
- [x] Setup partie 2 : `git init` (branche `main`), `.gitignore`, `.env.example` + `.env`, venv Python 3.12 (`.venv`)
- [x] Remplir `.env` avec les deux jetons
- [x] Configurer l'identité Git, puis premier commit
- [x] Dépendances minimales (`requirements.txt`) : `claude-agent-sdk`, `httpx`, `python-dotenv`
- [x] `scripts/test_connexions.py` : Claude répond « OK » ✅, La bonne alternance renvoie des offres ✅

### Critères de matching
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

## Étape 3 — Data ✅

- [x] `src/collecte.py` : `nettoyer_offre()` (champs utiles, HTML → texte, distance depuis Vigneux)
  - Test réel : 29 offres brutes → **18 uniques** (doublons = même `identifier.id`)
  - Entreprise souvent vide pour France Travail (offres anonymisées)
- [x] `rechercher()` : 2 appels API (départements + 30 km) → offres (6 codes ROME) et entreprises (M1827 seul)
  - Test : 18 offres + 150 entreprises, dont 141 ESN / éditeurs (avec les 6 codes : surtout banques et comptables)
- [x] `src/stockage.py` : SQLite `data/alternance.db`, tables `offres`, `entreprises`, `notations` (cache)
  - Upsert sur `id` ; `premiere_vue` / `derniere_vue` pour repérer les nouvelles offres et celles disparues
  - Collecte : `.venv\Scripts\python.exe -m src.collecte` (2e lancement : 0 nouvelle offre → pas de doublon ✅)

## Étape 4 — Profil ✅

- [x] `pypdf` + `pydantic` (sortie JSON validée : `output_format` du SDK → `ResultMessage.structured_output`)
- [x] Copier le CV dans `data/cv.pdf` (ignoré par Git)
- [x] Valider le schéma du profil (sans données de contact : minimisation RGPD)
- [x] `src/llm_client.py` : `generer_json(prompt, systeme, ModelePydantic)` — modèle `sonnet`, aucun outil
- [x] `src/profil.py` : lecture PDF + extraction par Claude → `data/profil.json`
  - Cache par empreinte SHA-256 du texte du CV : 1er lancement ~22 s, ensuite < 1 s
  - Le PDF en 2 colonnes mélange les lignes : Claude rattache correctement les puces
  - Lancement : `.venv\Scripts\python.exe -m src.profil`

## Étape 5 — Notation des offres ✅

- [x] `src/notation.py` : Claude note par lots de 10 (technique, niveau, rythme + justification, points forts, vigilance)
  - Distance et score global **calculés en Python** (déterministe, réglable) : technique 55 %, niveau 20 %, distance 15 %, rythme 10 %
  - Cache : table `notations` (clé offre + empreinte du CV) → 2e lancement instantané
  - 18 offres ≈ 3 min ; enregistrement après chaque lot
  - Lancement : `.venv\Scripts\python.exe -m src.notation`
- Constats :
  - Le champ niveau de l'API est parfois faux (Buun : « Bac+3 » dans l'API, « Bac+4/5 » dans la description) → consigne : la description prime
  - Tutoiement / vouvoiement variable selon les lots → consigne « tutoie toujours »
  - Aucune offre ne précise le rythme → critère rythme à 50 partout (peu utile pour l'instant)
  - Variabilité d'un lancement à l'autre : ±5 à 15 points sur le niveau ; le haut du classement reste stable
  - Piège SDK : ne pas faire `return` dans `async for message in query(...)` (générateur non fermé) → consommer tout le flux

## Étape 6 — Candidatures spontanées 🚧 (en cours)

- Choix : **email court personnalisé** (120–170 mots) plutôt que lettre classique
- [x] **Correctif sécurité** : `allowed_tools` n'empêche rien (il autorise sans confirmation) ; c'est `tools` qui fixe les outils disponibles.
  `tools=[]` → Claude n'a que `StructuredOutput`. Pour les emails : `tools=["WebSearch", "WebFetch"]` (lecture seule).
- [x] `src/candidature.py` : recherche web sur l'entreprise, puis email (objet, corps, ce que fait l'entreprise, sources, `personnalise`)
  - Signature ajoutée depuis `data/signature.txt` (jamais envoyée à Claude, jamais dans Git)
  - Emails historisés dans la table `emails`
  - Lancement : `.venv\Scripts\python.exe -m src.candidature "nom de l'entreprise"`
- [ ] Tester la qualité des emails (bloqué : **limite de session Pro atteinte** le 2026-09-17, reset 15h20)
- Constat : beaucoup d'entreprises ont un effectif « 0-0 » (sans salarié) → cibles peu probables, à filtrer

## Étape 7 — Interface web (Streamlit) 🚧 (en cours)

- Demande : ne plus utiliser le projet en ligne de commande
- [x] Modules découplés de l'affichage : `collecte.collecter()`, `notation.noter_offres(progression=...)`,
  `profil.profil_en_cache()` (jamais d'appel à Claude au simple affichage), `candidature.rediger_email()`
- [x] `app.py` (3 pages + barre latérale) :
  - **Offres** : classement, score coloré, jauges par critère, points forts / vigilance, filtre par score, lien pour postuler
  - **Candidatures spontanées** : tableau filtrable (sans salarié masqué : 107 / 150), sélection → email (recherche web), historique, copie
  - **Profil** : import du CV, profil extrait, édition de la signature
  - Barre latérale : « Collecter les offres » (API, sans quota) et « Noter les nouvelles offres » (quota Claude)
- [x] Lanceur double-clic `Alternance Copilot.bat` ; `.streamlit/config.toml` (localhost uniquement, pas de statistiques d'usage)
- [x] Tests sans navigateur avec `streamlit.testing.v1.AppTest` : 3 pages sans exception
- [x] **Filtre d'ancienneté** : offres publiées depuis **14 jours maximum** (`stockage.AGE_MAX_JOURS`)
  - Page Offres : choix « 3 jours / 1 semaine / 2 semaines » + « publiée il y a N jours » sur chaque offre
  - La notation ignore aussi les offres plus anciennes (économie de quota)
  - Au 17/09 : 6 offres sur 18 ; la meilleure (Buun, fullstack, 60) est exclue (publiée il y a 15 jours)
- [ ] Tester la génération d'email depuis l'interface (après le reset du quota)
- Constats :
  - **Smart App Control** (Windows) a bloqué une fois une DLL de pandas au premier chargement, puis l'a autorisée
  - Des comités sociaux et économiques (secteur « syndicats de salariés ») figurent parmi les entreprises → à filtrer

## Étape 8 — Contacts, suivi et relances ✅

- Demande : relance automatique + « scraper LinkedIn pour trouver des salariés et leur email »
- **Scraper LinkedIn refusé** : interdit par les conditions de LinkedIn (risque de bannissement du compte) et
  sanctionné par la CNIL (KASPR, 240 000 €, 5 décembre 2024). Remplacé par des sources légitimes :
  - [x] `src/contacts.py` : dirigeants via l'API officielle Recherche d'entreprises (sans date de naissance ni nationalité)
  - [x] Emails **publiés** par l'entreprise, trouvés par Claude puis **vérifiés** par le programme sur la page source
    (`adresse_dans_texte` : gère « [at] », « (arobase) », refuse `x@site.fr.autre.com` ; 9 cas testés)
  - [x] Liens de recherche LinkedIn préremplis (ouverts par l'utilisateur) + note d'invitation ≤ 300 caractères
- [x] Une seule recherche web par entreprise : contacts + email + note LinkedIn (économie de quota)
- **Relances semi-automatiques** (envoi validé par l'utilisateur) :
  - [x] Tables `candidatures` et `relances` ; relance proposée à J+7, 2 relances max, arrêt si statut entretien/refus
  - [x] `src/relance.py` : rédaction par Claude (sans outil) à partir du message initial
  - [x] Page « Suivi et relances » + rappel dans la barre latérale ; « J'ai postulé » sur les offres ;
    « Marquer comme envoyé » (email / LinkedIn) sur les entreprises
- [x] `ALTERNANCE_DB` : base alternative pour les tests et la démo ; tests AppTest sur une copie de la base
- Test réel CALIXYS (1 min 20) : `contact@calixys.com` vérifiée ✅, email personnalisé (XREC, Qonto, Spendesk)
  - Défauts relevés : rôle embelli (« développé » au lieu de « tests et débogage »), âge de l'entreprise approximatif
    → consignes d'exactitude ajoutées au prompt

## Étape 9 — Exclusion des écoles et CFA ✅

- Demande : bloquer les offres d'écoles (ISCOD, CFA...) qui recrutent des étudiants pour leurs formations
- Analyse de 387 offres réelles (30 km) :
  - Les écoles publient **au nom d'entreprises clientes** : le code NAF est celui du client → filtre par secteur inutile
  - **`is_delegated = true`** (champ de l'API) = 98 offres, **toutes** d'organismes de formation (AUREIS FORMATION,
    SCHOLIA, INATEC, E2M FORMATION, IFCV, GOTOLEARN) : signal fiable
  - « CFA » dans la **description** : 7 cas sur 7 sont de vraies entreprises (Carrefour, Elior...) → non utilisé
- [x] `collecte.motif_exclusion()` : (1) `is_delegated`, (2) nom d'organisme (CFA, ISCOD, IFCV, école, school,
  formation, academy...), (3) titre « rejoins / intégrez notre école / formation »
  - Échantillon : 100 / 387 offres exclues ; pas de faux positif sur Institut Gustave Roussy ni « école 42 » dans un titre
- [x] Colonne `exclusion` (offres, entreprises) + **migration** `stockage.migrer()` (ALTER TABLE sur les bases existantes)
- [x] Offres et entreprises exclues : ni notées, ni affichées ; liste des offres masquées consultable sur la page Offres
- Sur la base réelle : IFCV APPRENTISSAGE masquée ; cas limite côté entreprises : « HN SERVICES - HN FORMATION -
  HN RECRUTEMENT » (ESN avec une activité de formation) masquée par le mot « formation »

## Étape 10 — Chatbot de préparation d'entretien ✅

- Demande : un chatbot pour discuter et préparer les entretiens
- **LangChain écarté** : ses modèles Claude exigent une clé API payante, incompatible avec le jeton de l'abonnement Pro.
  Agent construit avec le **Claude Agent SDK** (même principe : un LLM qui décide d'appeler des outils).
- [x] `llm_client.discuter()` : conversation multi-tours (`resume` = id de session), texte en flux
  (`include_partial_messages`), outils Python exposés via un serveur MCP interne (`create_sdk_mcp_server`)
  - Générateur synchrone pour Streamlit : la boucle asyncio tourne dans un fil séparé, les événements passent par une file
  - Outils intégrés limités au web en lecture seule ; sessions rangées dans `data/sessions`
  - `OutilPerso` : outils décrits sans dépendre du SDK (l'abstraction `llm_client` reste la seule à l'importer)
- [x] `src/assistant.py` : 5 outils en lecture seule (`mon_profil`, `chercher_offres`, `detail_offre`,
  `infos_entreprise`, `mes_candidatures`) + 2 modes :
  - **Coach** : fiche entreprise, questions probables, pitch, questions à poser au recruteur
  - **Simulation d'entretien** : Claude joue le recruteur, 1 question à la fois, retour [✅ ⚠️ 💡] après chaque réponse,
    bilan noté sur 4 axes ; consigne de ne jamais aider à embellir le parcours
- [x] Page « Préparation d'entretien » : choix du mode et de la cible (candidatures, offres, entreprises recherchées),
  suggestions, bouton « Démarrer la simulation » / « Bilan », activité des outils affichée pendant la réponse
- Test réel (simulation Buun) : tour 1 en 25 s (l'agent appelle seul profil, offre, entreprise, 2 recherches web),
  tour 2 en 8 s avec reprise du contexte ; retour pertinent (« pourquoi Buun ? » manquant) et question technique
  tirée de l'offre (idempotence des webhooks)
- Tests AppTest avec un assistant simulé (sans quota) : coach, simulation, changement de mode, effacement
- Limite : la conversation est perdue si on recharge la page (historique en mémoire de session Streamlit)

## Étape 11 — Automatisation en arrière-plan ✅

- Demande : automatiser la collecte et Claude, mais **Claude seulement quelques fois par semaine** (tokens),
  **sans notification**, en tâche de fond
- Options écartées : cloud (GitHub Actions, tâches planifiées distantes) → base et CV locaux, jeton Pro réservé au PC
- [x] `src/automatisation.py` : collecte **chaque jour** (API gratuite), notation **lundi, mercredi, vendredi**
  (+ rattrapage si la dernière notation a plus de 3 jours) ; limite de quota → notation reportée, pas d'échec
  - Historique dans la table `executions` ; journal `data/logs/automatisation.log`
- [x] Planificateur de tâches Windows : `scripts/planifier_tache.ps1` (installer / retirer / état),
  lanceurs `Activer la collecte automatique.bat` et `Desactiver la collecte automatique.bat`
  - Tous les jours à 10h (au départ 7h30, décalé pour être connecté), `pythonw` (aucune fenêtre), rattrapage au démarrage si le PC était éteint, réseau requis
  - Testé avec une tâche temporaire lancée par le Planificateur (code 0), puis supprimée
- [x] Application : état de la tâche et dernier passage dans la barre latérale ; à l'ouverture, collecte de
  rattrapage **sans notation** si la dernière collecte a plus de 12 h
- Notifications Windows essayées (PowerShell, sans dépendance) puis **retirées** à la demande

## Étape 12 — CV adapté à une offre ✅

- Demande : faire correspondre le CV à l'offre visée, Claude ne touchant qu'au **contenu**, jamais au design, avec PDF téléchargeable
- Le CV vient de **Claude Design** (export « empaqueté » : HTML + polices + photo en base64, déballé par du JavaScript)
  - Mise en page **fixe** : A4 794 x 1123 px, blocs en absolu, cartes à hauteur fixe, retours à la ligne manuels
  - `src/cv_modele.py` : déballage en HTML statique autonome, impression PDF via **Edge** (`--headless --print-to-pdf`,
    aucune dépendance à installer), contrôle de mise en page (`--dump-dom` + mesures après `document.fonts.ready`)
  - Vérifié : PDF rendu **identique** au CV d'origine (le HTML fourni est la version violette ; le PDF du CV était la verte)
- `src/cv_segments.py` : découpage en 55 segments (21 modifiables), gras en `**…**`, réinjection sans toucher au HTML/CSS
  - Protégés : nom, coordonnées, dates, formation, langues, référence, intitulés de poste et de projet, chiffres clés, étiquettes
- `src/competences.py` : compétences demandées par l'offre et **absentes du CV** → l'utilisateur répond oui/non,
  avec preuve facultative (description, lien GitHub consulté par Claude, fichier) ; verdict → statut confirmée / déclarée / absente
- `src/cv_adapte.py` : réécriture par Claude puis **garde-fous en Python** (testés unitairement) :
  zone protégée, `**` déséquilibré, chiffre absent du parcours, compétence non confirmée (« Java » ≠ « JavaScript »),
  élément de liste hors profil → refus + alerte ; puis contrôle de mise en page, **raccourcissement** (2 essais), PDF 1 page
- Page « CV adapté » : analyse de l'offre, confirmation des compétences, génération, différences avant/après, historique, téléchargement
- Test réel (offre Buun, Java/Spring non confirmé) : 3 min 50 ; Claude n'a mentionné ni Java ni Spring, a réorienté
  l'accroche vers l'entreprise, réordonné les compétences, et signalé les limites à préparer à l'oral

## Étape 13 — CV mis à jour et regénéré ✅

- Le CV a été refait (3 projets dont « Copilote de recherche d'alternance », nouvelle mise en page) :
  **nouveau format d'export** Claude Design (`<doc-page>` + `<section class="page">`) au lieu d'un simple `div`
  - `doc-page:not(:defined) { visibility:hidden }` → le moteur JavaScript de l'export est désormais **conservé**
    (sans lui la page reste invisible) ; le découpage cherche `section.page` puis, à défaut, le premier `div`
- Modifications appliquées **sans Claude** (édition directe des segments), puis PDF régénéré à l'identique :
  - « 387 offres collectées, filtrées et **notées** » → « collectées et filtrées » (seules les offres récentes sont notées)
  - + `SQLite` (bases de données), + `Tâches planifiées` (outils), `Sorties JSON validées` → `Agents LLM (outils)`
  - Cas particulier : le chiffre clé est une liste de 2 étiquettes de styles différents → seule la description est modifiée
- Contrôles : aucun débordement ni chevauchement, 1 page ; `data/cv_precedent.pdf` garde l'ancienne version
- Profil ré-extrait (3 projets, 35 compétences) → les 6 offres récentes ont été **renotées** pour ce nouveau profil

## Étape 14 — README et Hunter.io ✅

- [x] `README.md` : problème, fonctionnalités, architecture, installation, **choix techniques expliqués**,
  garde-fous, vie privée, tests, limites et ce que le projet m'a appris (mention du binôme avec Claude Code)
- [x] `src/hunter.py` : adresse nominative quand l'entreprise n'en publie aucune
  - Plan gratuit : **50 recherches + 100 vérifications / mois** → **cache en base** (table `recherches_hunter`),
    recherche **sur clic** uniquement, quota affiché dans l'interface
  - Le nom du dirigeant vient du registre officiel, Hunter ne fournit que le format de l'adresse
  - Test réel (CALIXYS) : adresse du gérant trouvée, confiance **99/100**, statut **valid**
  - **RGPD article 14** : l'email indique la provenance de l'adresse et propose de ne plus être recontacté
    (phrase ajoutée automatiquement dès qu'une adresse Hunter existe)

## Étape 15 — Offres collées à la main ✅

- Demande : coller une offre trouvée ailleurs (LinkedIn, site d'entreprise) et obtenir le CV adapté
- Table **séparée** `offres_externes` (id « ext-<empreinte> ») : insérer ces offres dans `offres` aurait faussé
  `MAX(derniere_vue)`, donc la notion d'offre active de toutes les autres requêtes
- `assistant.detail_offre()` reconnaît le préfixe `ext-` → analyse des compétences, CV adapté **et**
  simulation d'entretien fonctionnent sur une offre collée sans autre changement
- Page CV adapté : formulaire repliable (intitulé, entreprise, lien, texte), l'offre enregistrée est
  sélectionnée automatiquement ; refus si le texte fait moins de 100 caractères

## Sources
- https://api.apprentissage.beta.gouv.fr/fr
- https://code.claude.com/docs/en/authentication
- https://code.claude.com/docs/en/agent-sdk/overview
- https://code.claude.com/docs/en/agent-sdk/structured-outputs
- https://code.claude.com/docs/en/setup
