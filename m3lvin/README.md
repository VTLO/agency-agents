# 🤖 M3LVin — chef d'orchestre WhatsApp de The Agency

M3LVin est un chatbot WhatsApp autonome, **seul point d'entrée et de sortie humain** de l'agence.
L'équipe lui parle en français naturel ; il cadre le besoin, propose un **PLAN de production**
qu'un humain habilité doit **VALIDER**, puis orchestre les agents de ce dépôt (compilés en
*skills lite*) pour produire les livrables, qu'il renvoie sur WhatsApp sous forme de documents.

```
 Équipe (WhatsApp, FR)                       M3LVin                              Agents (EN, JSON compact)
 ─────────────────────        ───────────────────────────────────       ──────────────────────────────────
 "Il nous faut…"      ───▶  1. CADRAGE   brief roulant (EN, ~150 tok)
                     ◀───      questions ciblées (≤2 à la fois)
                            2. PLAN      routage BM25 local (0 token) → shortlist de 10 cartes
                                         planificateur → DAG JSON figé, versionné, haché
 📋 Plan P-7K2Q v1    ◀───      rendu FR par gabarit (0 token) + boutons ✅ ✏️ ❌
 "VALIDER P-7K2Q v1"  ───▶  3. GATE      approbateur autorisé + version exacte + audit
                            4. PRODUCTION niveaux du DAG en parallèle ─────────▶  skill lite (≤900 tok, en cache)
                                         budget surveillé, reprise possible ◀─────  livrable .md + §DIGEST§ 60 mots
 📦 Livraison + 📎 .md ◀───  5. LIVRAISON synthèse FR (modèle lite) + documents
 "ACCEPTER" / "REVOIR …" ──▶               REVOIR = nouvelle version du plan → re-validation
```

## Pourquoi c'est économe en tokens

| Levier | Mise en œuvre | Gain typique |
|---|---|---|
| **Skills lite** | Chaque agent (~3 400 tokens) est compilé en un prompt de ≤900 tokens (règles, mission, workflow ; sans exemples de code, emojis ni sections décoratives) et une *carte* d'~60 tokens. | ~75 % par étape |
| **Routage local** | BM25 en Python pur sur les cartes : le planificateur ne voit que 10 cartes, jamais les 160 agents. | ~9 000 tokens/plan |
| **Protocole machine** | Entre composants : JSON compact anglais à clés courtes (`g`, `s`, `do`, `in`, `m`, `b`…). Le français n'existe qu'aux frontières humaines. | 20–30 % vs FR verbeux |
| **Digests de passation** | Chaque étape termine par `§DIGEST§ {"s":…,"k":[…]}` ; seules ces 60 mots passent aux étapes suivantes (texte complet uniquement si `ctx:"f"`). | contexte ÷10 |
| **Brief roulant** | La conversation n'est pas renvoyée en entier : brief structuré + 6 derniers tours tronqués. | coût du chat constant |
| **Niveaux de modèle** | Chaque appel nomme un tier : `L` Haiku 4.5, `S` Sonnet 5.5 (effort `low`), `M` Opus 5.5 (effort `medium`). Le planificateur choisit le tier par étape. | 2–4× sur les étapes simples |
| **Cache de prompt** | Prompts système figés, `cache_control` sur le dernier bloc stable (skill + protocole) ; données volatiles en fin de requête. | ~90 % sur les relectures |
| **Zéro-token** | Commandes (`VALIDER`, `STATUT`…), rendu du plan, contrôle d'accès, déduplication : code déterministe. | — |
| **Garde-fou budget** | Estimation affichée avant validation ; suspension automatique au-delà de ×1,5 ; reprise sans repayer les étapes faites. | pas de dérive |

## Gouvernance : rien ne tourne sans validation humaine

* Un plan proposé est **figé** (hash SHA-256, version `vN`). Toute modification crée `vN+1` et invalide les validations précédentes.
* `VALIDER` exige l'identifiant **et**, dès qu'il existe plusieurs versions, la version exacte. Les formulations ambiguës (« valide mais change X », « go ») ne valent **jamais** validation.
* `M3_APPROVERS` restreint qui peut valider ; `M3_ALLOW_SELF_APPROVAL=0` impose le principe des quatre yeux ; `M3_REQUIRED_APPROVALS` permet plusieurs signatures.
* Numéros hors `M3_TEAM` refusés sans consommer de token. Webhooks signés (`X-Hub-Signature-256`), idempotents (Meta re-livre).
* Journal d'audit (`audit`) et registre de consommation (`ledger`) dans SQLite.
* Au redémarrage, une production en cours est **suspendue**, jamais relancée en silence.

## Commandes WhatsApp

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

## Démarrage

```bash
cd m3lvin
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # puis renseigner les clés, et: set -a; . ./.env; set +a

m3lvin skills "landing page saas copywriting"   # compile les skills lite + teste le routage
m3lvin chat                                     # simulateur terminal (même cerveau, sans WhatsApp)
m3lvin serve                                    # serveur webhook (port 8080)
pytest                                          # tests (LLM simulé, aucun appel payant)
```

### Brancher WhatsApp (Cloud API Meta)

1. Créer une app Meta *Business* → produit **WhatsApp** → récupérer `WHATSAPP_PHONE_NUMBER_ID` et un **token permanent** d'utilisateur système (`WHATSAPP_TOKEN`).
2. Exposer `https://<votre-domaine>/webhook` (HTTPS obligatoire), configurer le webhook avec `WHATSAPP_VERIFY_TOKEN`, s'abonner au champ **messages**.
3. Renseigner `WHATSAPP_APP_SECRET` pour vérifier les signatures.
4. Déployer :

```bash
docker build -f m3lvin/Dockerfile -t m3lvin .        # depuis la racine du dépôt
docker run -p 8080:8080 --env-file m3lvin/.env -v m3lvin-data:/data m3lvin
```

> ⚠️ Fenêtre de 24 h WhatsApp : M3LVin ne peut écrire librement qu'aux personnes qui lui ont écrit
> dans les dernières 24 h. Pour notifier un approbateur « à froid » ou livrer après une très longue
> production, créez un *message template* approuvé par Meta (les échecs d'envoi sont journalisés).

## Architecture du code

| Module | Rôle |
|---|---|
| `skills.py` | Compilation des agents en skills lite + cartes, cache JSON, routeur BM25 |
| `protocol.py` | Schéma du plan, validation (skills connus, DAG acyclique, budgets), digests, commandes FR |
| `llm.py` | Passerelle Claude unique : tiers, effort, cache, fallbacks serveur, mesure d'usage |
| `orchestrator.py` | M3LVin : machine à états, gate de validation, rendu FR, notifications |
| `executor.py` | Exécution du DAG (parallèle), passation par digests, budget, reprise |
| `store.py` | SQLite : conversations, versions de plan, validations, étapes, ledger, audit |
| `whatsapp.py` / `app.py` | Cloud API (texte, boutons, documents), webhook FastAPI signé |
| `prompts.py` | Prompts système figés (compatibles cache) |

Le plan (JSON) échangé entre composants :

```json
{"g":"SaaS launch kit","fr":"Créer le kit de lancement","lang":"fr","h":["Cible : PME"],
 "s":[{"i":"s1","k":"ux-architect","t":"Structure de page","do":"Design landing structure…","in":[],"ctx":"d","m":"S","b":1500,"dl":false,"out":"structure.md"},
      {"i":"s2","k":"content-creator","t":"Rédaction","do":"Write landing copy…","in":["s1"],"ctx":"d","m":"S","b":2000,"dl":true,"out":"landing-copy.md"}]}
```

Ajouter ou modifier un agent dans le dépôt suffit : le cache des skills est recompilé automatiquement au démarrage suivant.
