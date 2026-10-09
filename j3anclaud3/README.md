# 🤖 J3anClaud3 — assistant francophone et chef d'orchestre de The Agency

J3anClaud3 est un chatbot autonome et **auto-hébergé** qui parle un français naturel.
Il fonctionne selon l'un de deux **modes**, choisis au lancement :

| Mode | Ce qu'il fait | Lancement |
|---|---|---|
| **orchestre** *(défaut)* | Seul point d'entrée et de sortie humain de l'agence : il cadre le besoin, propose un **PLAN de production** qu'un humain doit **VALIDER**, puis orchestre les agents de ce dépôt (compilés en *skills lite*) et renvoie les livrables sous forme de documents. | `j3anclaud3 serve` |
| **conversation** | Simple chat conversationnel en langage naturel, **sans les skills** : pas de plan, pas de production, pas de livrables. Démarrage instantané (les agents ne sont pas chargés). | `j3anclaud3 serve --mode conversation` |

Le mode peut aussi être fixé par la variable `J3_MODE` (`orchestre` ou `conversation`) ; l'option `--mode` l'emporte.

Aucune plateforme tierce de messagerie : J3anClaud3 embarque sa propre messagerie. **Tout le monde
peut lui parler** : on indique simplement son prénom (un compte administrateur viendra plus tard).

| Où | Comment |
|---|---|
| **Navigateur** (ordinateur, tablette, mobile) | `http://<serveur>:8080` — interface de chat, temps réel, thème clair/sombre |
| **Application mobile** | La même page s'installe comme une application (PWA) : « Ajouter à l'écran d'accueil » |
| **API HTTP** | `POST /api/send`, `GET /api/messages`, flux temps réel `GET /api/stream` — pour scripts, outils internes, autres bots |
| **Terminal** | `j3anclaud3 chat [--mode conversation]` |

L'historique est stocké côté serveur : avec le même prénom, on retrouve la même conversation sur tous ses appareils.

Fonctionnement du mode **orchestre** :

```
 Équipe (web, FR)                            J3anClaud3                              Agents (EN, JSON compact)
 ────────────────              ───────────────────────────────────       ──────────────────────────────────
 "Il nous faut…"      ───▶  1. CADRAGE   brief roulant (EN, ~150 tok)
                     ◀───      questions ciblées (≤2 à la fois)
                            2. PLAN      routage BM25 local (0 token) → shortlist de 10 cartes
                                         planificateur → DAG JSON figé, versionné, haché
 📋 Plan P-7K2Q v1    ◀───      rendu FR par gabarit (0 token) + boutons ✅ ✏️ ❌
 [✅ Valider]         ───▶  3. GATE      validation humaine explicite + version exacte + audit
                            4. PRODUCTION niveaux du DAG en parallèle ─────────▶  skill lite (≤900 tok, en cache)
                                         budget surveillé, reprise possible ◀─────  livrable .md + §DIGEST§ 60 mots
 📦 Livraison + 📎 .md ◀───  5. LIVRAISON synthèse FR (modèle lite) + documents (aperçu / téléchargement)
 "ACCEPTER" / "REVOIR …" ──▶               REVOIR = nouvelle version du plan → re-validation
```

## Démarrage rapide

```bash
cd j3anclaud3
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # renseigner ANTHROPIC_API_KEY
set -a; . ./.env; set +a

j3anclaud3 serve                        # mode orchestre, puis ouvrir http://localhost:8080
j3anclaud3 serve --mode conversation    # mode conversation (chat libre, sans skills)
```

Autres commandes :

```bash
j3anclaud3 chat --as alice                         # chat dans le terminal (même base de données)
j3anclaud3 chat --mode conversation                # idem, en mode conversation
j3anclaud3 skills "landing page saas copywriting"  # compile les skills lite + teste le routage
pytest                                         # tests (LLM simulé, aucun appel payant)
```

### Déployer (n'importe quel serveur, VPS, NAS, cloud)

```bash
docker build -f j3anclaud3/Dockerfile -t j3anclaud3 .        # depuis la racine du dépôt
docker run -d -p 8080:8080 --env-file j3anclaud3/.env -v j3anclaud3-data:/data --name j3anclaud3 j3anclaud3
# mode conversation : ajouter  -e J3_MODE=conversation  (ou terminer par : j3anclaud3 serve --mode conversation)
```

> ⚠️ Sans compte, toute personne qui atteint le serveur peut discuter avec le bot, et donc consommer
> votre crédit API. Tant que le compte administrateur n'existe pas, gardez-le sur un réseau privé
> (VPN, réseau d'entreprise) ou derrière un reverse proxy avec authentification, ou lancez-le avec
> `HOST=127.0.0.1` pour un usage uniquement local.

Pour un accès hors du réseau local, placez-le derrière un reverse proxy HTTPS (Caddy,
Traefik, nginx…) : les cookies de session passent automatiquement en `Secure` en HTTPS.
Pour nginx, désactivez le buffering sur `/api/stream` (`proxy_buffering off;`) ; l'en-tête
`X-Accel-Buffering: no` est déjà envoyé.

### API HTTP

Identification : `POST /api/login {"name": "alice"}` renvoie un `token` à utiliser en
`Authorization: Bearer <token>` (l'interface web utilise le cookie de session). `GET /api/config`
indique le mode actif. Documentation interactive : `http://<serveur>:8080/api/docs`.

```bash
TOKEN=$(curl -s -X POST localhost:8080/api/login -H 'Content-Type: application/json' -d '{"name":"alice"}' | jq -r .token)
H="Authorization: Bearer $TOKEN"
curl -X POST localhost:8080/api/send -H "$H" -H 'Content-Type: application/json' \
     -d '{"text":"Il nous faut une landing page pour notre SaaS","id":"msg-001"}'
curl localhost:8080/api/messages?after=0 -H "$H"        # historique (JSON)
curl -N localhost:8080/api/stream -H "$H"               # flux temps réel (Server-Sent Events)
curl -OJ localhost:8080/api/files/42 -H "$H"            # télécharger un livrable (mode orchestre)
```

`id` est optionnel : s'il est fourni, un renvoi du même message n'est traité qu'une fois.

## Pourquoi c'est économe en tokens

En mode **conversation** : prompt système figé et mis en cache, historique borné
(`J3_CHAT_HISTORY`, 20 messages) et réduit **par blocs** (de moitié d'un coup) pour que le
préfixe en cache reste stable plusieurs tours de suite, préfixe de conversation lui aussi mis en
cache, modèle `S` à effort `low`, commandes `NOUVEAU` / `AIDE` à zéro token.

En mode **orchestre** :

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

## Gouvernance (mode orchestre) : rien ne tourne sans validation humaine

* Un plan proposé est **figé** (hash SHA-256, version `vN`). Toute modification crée `vN+1` et invalide les validations précédentes.
* `VALIDER` exige l'identifiant **et**, dès qu'il existe plusieurs versions, la version exacte. Les formulations ambiguës (« valide mais change X », « go ») ne valent **jamais** validation. Un bouton « Valider » d'une version périmée est refusé.
* Tout le monde peut valider en attendant le compte administrateur ; `J3_ALLOW_SELF_APPROVAL=0` impose le principe des quatre yeux (un autre prénom doit valider) ; `J3_REQUIRED_APPROVALS` permet plusieurs signatures.
* Sessions signées (HMAC) ; chacun ne voit que son fil et ses fichiers.
* Journal d'audit (`audit`) et registre de consommation (`ledger`) dans SQLite.
* Au redémarrage, une production en cours est **suspendue**, jamais relancée en silence.

## Commandes

En mode **conversation**, seules `NOUVEAU` (effacer le fil) et `AIDE` existent ; tout le reste
est envoyé au modèle comme message. En mode **orchestre** :

| Commande | Effet |
|---|---|
| *(texte libre)* | Cadrage / discussion avec J3anClaud3 |
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
| `base.py` | Socle commun aux deux modes : réception, déduplication, verrou par personne, tâches de fond |
| `orchestrator.py` | Mode orchestre : machine à états, gate de validation, rendu FR |
| `conversation.py` | Mode conversation : chat multi-tours sans skills, historique borné par blocs |
| `executor.py` | Exécution du DAG (parallèle), passation par digests, budget, reprise |
| `store.py` | SQLite : conversations, historique des messages, versions de plan, validations, étapes, ledger, audit |
| `web.py` | Messagerie intégrée : diffusion temps réel, sessions signées |
| `app.py` | Serveur FastAPI : choix du mode, interface web, API JSON, flux SSE, téléchargement des livrables |
| `static/` | Interface de chat (HTML/CSS/JS sans dépendance), manifest PWA, service worker |
| `prompts.py` | Prompts système figés (compatibles cache) |

Les deux modes parlent à leurs clients à travers une interface `Outbox` (`send_text`, `send_buttons`,
`send_document`) : brancher un autre canal (e-mail, Slack, Matrix…) revient à écrire une
classe de ce type, sans toucher à l'orchestration.

Le plan (JSON) échangé entre composants :

```json
{"g":"SaaS launch kit","fr":"Créer le kit de lancement","lang":"fr","h":["Cible : PME"],
 "s":[{"i":"s1","k":"ux-architect","t":"Structure de page","do":"Design landing structure…","in":[],"ctx":"d","m":"S","b":1500,"dl":false,"out":"structure.md"},
      {"i":"s2","k":"content-creator","t":"Rédaction","do":"Write landing copy…","in":["s1"],"ctx":"d","m":"S","b":2000,"dl":true,"out":"landing-copy.md"}]}
```

Ajouter ou modifier un agent dans le dépôt suffit : le cache des skills est recompilé automatiquement au démarrage suivant.
