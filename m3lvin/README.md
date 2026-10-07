# 🤖 M3LVin — chef d'orchestre de The Agency

M3LVin est un chatbot autonome et **auto-hébergé**, seul point d'entrée et de sortie humain de l'agence.
L'équipe lui parle en français naturel ; il cadre le besoin, propose un **PLAN de production**
qu'un humain habilité doit **VALIDER**, puis orchestre les agents de ce dépôt (compilés en
*skills lite*) pour produire les livrables, qu'il renvoie dans la conversation sous forme de documents.

Aucune plateforme tierce de messagerie : M3LVin embarque sa propre messagerie.

| Où | Comment |
|---|---|
| **Navigateur** (ordinateur, tablette, mobile) | `http://<serveur>:8080` — interface de chat, temps réel, thème clair/sombre |
| **Application mobile** | La même page s'installe comme une application (PWA) : « Ajouter à l'écran d'accueil » |
| **API HTTP** | `POST /api/send`, `GET /api/messages`, flux temps réel `GET /api/stream` — pour scripts, outils internes, autres bots |
| **Terminal** | `m3lvin chat` |

L'historique est stocké côté serveur : on retrouve la même conversation sur tous ses appareils.

```
 Équipe (web, FR)                            M3LVin                              Agents (EN, JSON compact)
 ────────────────              ───────────────────────────────────       ──────────────────────────────────
 "Il nous faut…"      ───▶  1. CADRAGE   brief roulant (EN, ~150 tok)
                     ◀───      questions ciblées (≤2 à la fois)
                            2. PLAN      routage BM25 local (0 token) → shortlist de 10 cartes
                                         planificateur → DAG JSON figé, versionné, haché
 📋 Plan P-7K2Q v1    ◀───      rendu FR par gabarit (0 token) + boutons ✅ ✏️ ❌
 [✅ Valider]         ───▶  3. GATE      approbateur autorisé + version exacte + audit
                            4. PRODUCTION niveaux du DAG en parallèle ─────────▶  skill lite (≤900 tok, en cache)
                                         budget surveillé, reprise possible ◀─────  livrable .md + §DIGEST§ 60 mots
 📦 Livraison + 📎 .md ◀───  5. LIVRAISON synthèse FR (modèle lite) + documents (aperçu / téléchargement)
 "ACCEPTER" / "REVOIR …" ──▶               REVOIR = nouvelle version du plan → re-validation
```

## Démarrage rapide

```bash
cd m3lvin
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # renseigner ANTHROPIC_API_KEY et M3_USERS
set -a; . ./.env; set +a

m3lvin serve                  # puis ouvrir http://localhost:8080
```

Autres commandes :

```bash
m3lvin chat --as alice                         # chat dans le terminal (même base de données)
m3lvin skills "landing page saas copywriting"  # compile les skills lite + teste le routage
pytest                                         # tests (LLM simulé, aucun appel payant)
```

### Comptes

`M3_USERS=nom:rôle:code,…` — par exemple `alice:approver:k8Qz…,bob:member:Xp2w…`.

* `approver` peut **VALIDER** un plan ; `member` peut cadrer, demander et modifier des plans.
* Le **code** sert de mot de passe dans l'interface web et de jeton `Bearer` pour l'API.
  Générez-en un par personne : `python -c "import secrets; print(secrets.token_urlsafe(18))"`.
* `M3_USERS` vide = **mode ouvert** : chacun choisit un prénom et peut tout faire. Réservé à un
  usage local ; le serveur n'écoute alors que sur `127.0.0.1` (sauf `HOST` explicite).

### Déployer (n'importe quel serveur, VPS, NAS, cloud)

```bash
docker build -f m3lvin/Dockerfile -t m3lvin .        # depuis la racine du dépôt
docker run -d -p 8080:8080 --env-file m3lvin/.env -v m3lvin-data:/data --name m3lvin m3lvin
```

Pour un accès hors du réseau local, placez-le derrière un reverse proxy HTTPS (Caddy,
Traefik, nginx…) : les cookies de session passent automatiquement en `Secure` en HTTPS.
Pour nginx, désactivez le buffering sur `/api/stream` (`proxy_buffering off;`) ; l'en-tête
`X-Accel-Buffering: no` est déjà envoyé.

### API HTTP

Authentification : cookie de session (interface web) ou `Authorization: Bearer <code>`.
Documentation interactive : `http://<serveur>:8080/api/docs`.

```bash
H="Authorization: Bearer $CODE"
curl -X POST localhost:8080/api/send -H "$H" -H 'Content-Type: application/json' \
     -d '{"text":"Il nous faut une landing page pour notre SaaS","id":"msg-001"}'
curl localhost:8080/api/messages?after=0 -H "$H"        # historique (JSON)
curl -N localhost:8080/api/stream -H "$H"               # flux temps réel (Server-Sent Events)
curl -OJ localhost:8080/api/files/42 -H "$H"            # télécharger un livrable
```

`id` est optionnel : s'il est fourni, un renvoi du même message n'est traité qu'une fois.

## Pourquoi c'est économe en tokens

| Levier | Mise en œuvre | Gain typique |
|---|---|---|
| **Skills lite** | Chaque agent (~3 400 tokens) est compilé en un prompt de ≤900 tokens (règles, mission, workflow ; sans exemples de code, emojis ni sections décoratives) et une *carte* d'~60 tokens. | ~75 % par étape |
| **Routage local** | BM25 en Python pur sur les cartes : le planificateur ne voit que 10 cartes, jamais les 160 agents. | ~9 000 tokens/plan |
| **Protocole machine** | Entre composants : JSON compact anglais à clés courtes (`g`, `s`, `do`, `in`, `m`, `b`…). Le français n'existe qu'aux frontières humaines. | 20–30 % vs FR verbeux |
| **Digests de passation** | Chaque étape termine par `§DIGEST§ {"s":…,"k":[…]}` ; seuls ces 60 mots passent aux étapes suivantes (texte complet uniquement si `ctx:"f"`). | contexte ÷10 |
| **Brief roulant** | La conversation n'est pas renvoyée en entier : brief structuré + 6 derniers tours tronqués. | coût du chat constant |
| **Niveaux de modèle** | Chaque appel nomme un tier : `L` Haiku 4.5, `S` Sonnet 5.5 (effort `low`), `M` Opus 5.5 (effort `medium`). Le planificateur choisit le tier par étape. | 2–4× sur les étapes simples |
| **Cache de prompt** | Prompts système figés, `cache_control` sur le dernier bloc stable (skill + protocole) ; données volatiles en fin de requête. | ~90 % sur les relectures |
| **Zéro-token** | Commandes (`VALIDER`, `STATUT`…), boutons, rendu du plan, authentification, déduplication : code déterministe. | — |
| **Garde-fou budget** | Estimation affichée avant validation ; suspension automatique au-delà de ×1,5 ; reprise sans repayer les étapes faites. | pas de dérive |

## Gouvernance : rien ne tourne sans validation humaine

* Un plan proposé est **figé** (hash SHA-256, version `vN`). Toute modification crée `vN+1` et invalide les validations précédentes.
* `VALIDER` exige l'identifiant **et**, dès qu'il existe plusieurs versions, la version exacte. Les formulations ambiguës (« valide mais change X », « go ») ne valent **jamais** validation. Un bouton « Valider » d'une version périmée est refusé.
* Seuls les comptes `approver` valident ; `M3_ALLOW_SELF_APPROVAL=0` impose le principe des quatre yeux ; `M3_REQUIRED_APPROVALS` permet plusieurs signatures. Les approbateurs reçoivent la demande de validation directement dans leur fil.
* Comptes inconnus refusés sans consommer de token ; 5 échecs de connexion par minute maximum ; sessions signées (HMAC) ; chacun ne voit que son fil et ses fichiers.
* Journal d'audit (`audit`) et registre de consommation (`ledger`) dans SQLite.
* Au redémarrage, une production en cours est **suspendue**, jamais relancée en silence.

## Commandes

| Commande | Effet |
|---|---|
| *(texte libre)* | Cadrage / discussion avec M3LVin |
| `PLAN` | Générer le plan depuis le brief courant |
| `VALIDER P-XXXX v1` | Lancer la production (approbateurs) — aussi via le bouton ✅ |
| `MODIFIER …` | Demander un changement → nouvelle version du plan |
| `ANNULER` | Abandonner le plan |
| `STATUT` / `BUDGET` | Avancement des étapes et consommation |
| `STOP` | Suspendre une production (reprise via `VALIDER`) |
| `ACCEPTER` / `REVOIR …` | Clôturer ou itérer après livraison |
| `PROJETS` | Plans actifs de l'équipe |
| `NOUVEAU` / `AIDE` | Repartir de zéro / aide |

Les plus courantes sont aussi des raccourcis cliquables sous la zone de saisie.

## Architecture du code

| Module | Rôle |
|---|---|
| `skills.py` | Compilation des agents en skills lite + cartes, cache JSON, routeur BM25 |
| `protocol.py` | Schéma du plan, validation (skills connus, DAG acyclique, budgets), digests, commandes FR |
| `llm.py` | Passerelle Claude unique : tiers, effort, cache, fallbacks serveur, mesure d'usage |
| `orchestrator.py` | M3LVin : machine à états, gate de validation, rendu FR, notifications |
| `executor.py` | Exécution du DAG (parallèle), passation par digests, budget, reprise |
| `store.py` | SQLite : conversations, historique des messages, versions de plan, validations, étapes, ledger, audit |
| `web.py` | Messagerie intégrée : diffusion temps réel, sessions signées, comptes, anti-bruteforce |
| `app.py` | Serveur FastAPI : interface web, API JSON, flux SSE, téléchargement des livrables |
| `static/` | Interface de chat (HTML/CSS/JS sans dépendance), manifest PWA, service worker |
| `prompts.py` | Prompts système figés (compatibles cache) |

M3LVin parle à ses clients à travers une interface `Outbox` (`send_text`, `send_buttons`,
`send_document`) : brancher un autre canal (e-mail, Slack, Matrix…) revient à écrire une
classe de ce type, sans toucher à l'orchestration.

Le plan (JSON) échangé entre composants :

```json
{"g":"SaaS launch kit","fr":"Créer le kit de lancement","lang":"fr","h":["Cible : PME"],
 "s":[{"i":"s1","k":"ux-architect","t":"Structure de page","do":"Design landing structure…","in":[],"ctx":"d","m":"S","b":1500,"dl":false,"out":"structure.md"},
      {"i":"s2","k":"content-creator","t":"Rédaction","do":"Write landing copy…","in":["s1"],"ctx":"d","m":"S","b":2000,"dl":true,"out":"landing-copy.md"}]}
```

Ajouter ou modifier un agent dans le dépôt suffit : le cache des skills est recompilé automatiquement au démarrage suivant.
