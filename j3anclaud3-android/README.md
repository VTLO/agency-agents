# 📱 J3anClaud3 pour Android — l'assistant dans toutes vos messageries

Deux applications, construites à partir du même code :

| APK | Intelligence | Taille |
|---|---|---|
| **J3anClaud3** (`claude`) | Votre serveur J3anClaud3, **ou sans serveur** : Claude, OpenAI, Gemini ou votre propre serveur, avec votre clé API sur le téléphone | ~7,8 Mo (release) |
| **J3anClaud3 Libre** (`libre`) | **Sans Claude et sans serveur** : OpenAI (ou toute API compatible : Ollama, LM Studio, vLLM…), Google Gemini, ou un serveur personnel `/generate/` | ~0,2 Mo (release) |

Les deux s'installent côte à côte (identifiants `fr.j3anclaud3.compagnon` et `fr.j3anclaud3.compagnon.libre`).

Application Android (APK universel, Android 8 et plus) qui met J3anClaud3 au cœur de vos
messageries **sans aucune API WhatsApp, Meta ou autre** : elle lit les notifications des
applications que vous choisissez et répond par leur bouton « Répondre » intégré, exactement
comme vous le feriez depuis la notification.

| Fonction | Comment |
|---|---|
| **Suggestions de réponse** | Un message arrive (WhatsApp, SMS, Telegram, Signal, Messenger, Instagram, Slack, Teams…) → J3anClaud3 vous propose une réponse dans une notification : **Envoyer**, **Modifier** (saisie directe) ou **Ignorer**. |
| **Réponse automatique** *(optionnelle)* | J3anClaud3 répond seul, avec une limite par conversation (10 min par défaut) et 20 envois par heure au maximum. Chaque envoi vous est notifié, et les réponses sont signées « rédigée par mon assistant » par défaut. |
| **Résumé de mes messages** | Un bouton résume tout ce qui est arrivé : d'abord ce qui demande une action, puis le reste par conversation. |
| **Chat avec J3anClaud3** | L'interface de chat du serveur, intégrée et déjà connectée (mode orchestre ou conversation). |

## Comment ça marche

```
 WhatsApp / SMS / Telegram…           Téléphone (J3anClaud3)                     Votre serveur J3anClaud3
 ──────────────────────────   ─────────────────────────────────────────   ───────────────────────────────
 notification "Tu viens         NotificationListenerService
 dimanche ?"  ───────────────▶  · application cochée ? groupe autorisé ?
                                · code / banque / sécurité ? → stop (rien ne sort)
                                · 12 derniers messages de la conversation ──▶ POST /api/assist/reply
                                                                              modèle « lite », consignes anti-injection,
                                                                              NO_REPLY si rien ne doit être envoyé
                                ◀────────────────────────────────── brouillon
 ◀── bouton « Répondre » de     notification : Envoyer · Modifier · Ignorer
     l'application (RemoteInput)   (ou envoi automatique, limité)
```

* **Avec serveur** : aucune clé d'API sur le téléphone, l'IA est appelée par votre serveur J3anClaud3 (voir `../j3anclaud3`), qui garde le compte administrateur, le blocage et le suivi de consommation.
* **Sans serveur** : le téléphone appelle directement le fournisseur choisi avec **votre** clé, chiffrée par le coffre-fort Android (Keystore, AES-256-GCM) et jamais réaffichée. La consommation de tokens est comptée sur le téléphone. Le chat devient un écran natif.
* **Rien n'est stocké** : les messages ne vivent qu'en mémoire, le temps de la session de l'application.
* **Codes de vérification, banque, sécurité** : détectés sur le téléphone, jamais envoyés au serveur. Le modèle répond aussi `NO_REPLY` pour les sujets sensibles, les messages automatiques, la publicité ou les urgences.
* Les messages reçus sont traités comme des **données** : le prompt interdit au modèle de suivre les instructions qu'ils contiennent.

## Fournisseurs en mode sans serveur

| Fournisseur | Appel | Modèle par défaut | Remarques |
|---|---|---|---|
| Anthropic Claude *(APK `claude` uniquement)* | SDK Java officiel | `claude-haiku-4-5` (ou `claude-sonnet-5-5`) | |
| OpenAI | `POST {adresse}/chat/completions` | `gpt-4o-mini` | Adresse modifiable : tout serveur compatible OpenAI (Ollama `http://IP:11434/v1`, LM Studio, vLLM, Mistral…). Clé facultative pour un serveur local. |
| Google Gemini | `POST {adresse}/models/{modèle}:generateContent` | `gemini-1.5-flash` | Clé envoyée dans l'en-tête `x-goog-api-key`, jamais dans l'URL. |
| Serveur personnalisé | `POST {adresse}/generate/` `{model, prompt}` | `custom-gpt-4o` | Réponse en texte brut, ou JSON avec `response`, `text`, `reply` ou `choices`. |

Le modèle est un champ libre. Les suggestions (`gpt-4o`, `gpt-4`, `gpt-3.5-turbo`, `gemini-1.5-pro`) reprennent une liste
existante : certaines sont peut-être retirées par leur fournisseur, vérifiez avant de les utiliser.

Quel que soit le modèle, J3anClaud3 garde ses consignes. Les messages reçus sont traités comme des données,
`NO_REPLY` est renvoyé pour les codes, la banque et les sujets sensibles, et l'assistant **répond honnêtement**
si on lui demande s'il est une IA. Il ne se fait jamais passer pour un humain.

## Installation

1. Récupérez l'APK :
   * depuis l'onglet **Actions** de GitHub (workflow *J3anClaud3 Android* → artefact `j3anclaud3-android-apk`), ou
   * en le compilant : `cd j3anclaud3-android && ./gradlew assembleClaudeDebug assembleLibreDebug`, ce qui produit
     `app/build/outputs/apk/claude/debug/j3anclaud3-0.1.0-claude-debug.apk` et `app/build/outputs/apk/libre/debug/j3anclaud3-0.1.0-libre-debug.apk`.
2. Sur le téléphone, ouvrez l'APK. Android demande d'autoriser l'installation d'applications de cette source.
3. Dans J3anClaud3 :
   1. lisez et acceptez l'avertissement de confidentialité ;
   2. **Fonctionnement** : soit votre serveur J3anClaud3 (adresse et prénom, plus le mot de passe pour le compte administrateur), soit
      **sans serveur** : choisissez le fournisseur, collez votre clé, puis Enregistrer et Tester. L'APK Libre est toujours sans serveur ;
   3. **Accès aux notifications** : activez J3anClaud3 dans les réglages Android qui s'ouvrent ;
   4. **Autoriser les suggestions à s'afficher** (Android 13 et plus) ;
   5. cochez les **applications** à surveiller. Aucune ne l'est par défaut.

> Certains fabricants (Xiaomi, Huawei, Oppo…) arrêtent les applications en arrière-plan : excluez
> J3anClaud3 de l'optimisation de batterie pour que les suggestions arrivent toujours.

### Version signée pour la diffusion

L'APK `debug` s'installe directement mais n'est pas destiné au Play Store. Pour une version
`release` signée et optimisée :

```bash
keytool -genkey -v -keystore j3.jks -alias j3 -keyalg RSA -keysize 4096 -validity 10000
J3_KEYSTORE=$PWD/j3.jks J3_KEYSTORE_PASSWORD=… J3_KEY_ALIAS=j3 J3_KEY_PASSWORD=… ./gradlew assembleClaudeRelease assembleLibreRelease
```

## Limites à connaître

* L'assistant ne voit que ce que l'application de messagerie met dans sa notification (en général les derniers messages de la conversation), et seulement si l'application a une notification de message active.
* Les réponses passent par le bouton « Répondre » des notifications : une application qui n'en propose pas (certains e-mails, Snapchat…) peut être résumée mais pas répondue.
* Une notification ignorée ou balayée avant la suggestion ne peut plus servir à répondre.
* Les médias (photos, vocaux) ne sont pas analysés.

## Développement

```bash
./gradlew testClaudeDebugUnitTest testLibreDebugUnitTest   # tests Robolectric (vraies notifications Android)
./gradlew lintClaudeDebug lintLibreDebug
./gradlew assembleClaudeDebug assembleLibreDebug
```

Les tests construisent de vraies notifications de type WhatsApp (MessagingStyle et action de réponse
directe) et vérifient le parcours complet face à un faux serveur J3anClaud3 local : brouillon demandé,
suggestion affichée, réponse remise au bouton « Répondre » de l'application, texte modifié, ignorer,
déduplication des notifications republiées, codes jamais envoyés, groupes, `NO_REPLY`, réponses
automatiques signées avec délai minimum entre deux envois, applications non cochées ignorées.
En mode sans serveur, ils vérifient aussi le format exact des requêtes de chaque fournisseur (Claude via le SDK,
OpenAI, Gemini, `/generate/`) face à des faux fournisseurs locaux, le chiffrement des clés, les clés refusées,
les réponses bloquées et le parcours complet sans aucun serveur.
Options : `-ProbolectricRepo=<miroir Maven>` et `-Pj3Screenshots=<dossier>` (rendu PNG de l'écran de réglages).

| Fichier | Rôle |
|---|---|
| `J3NotificationListener.kt` | Reçoit les notifications, filtre, et `Processor` décide : rien, suggestion ou envoi automatique |
| `Messages.kt` | Lecture des conversations (MessagingStyle, sinon titre et texte), détection des codes, envoi via `RemoteInput` |
| `Model.kt` | État en mémoire : historique par conversation, déduplication, délai minimum entre envois, brouillons en attente |
| `Notifier.kt` / `ReplyReceiver.kt` | Notifications de suggestion (Envoyer · Modifier · Ignorer) et leurs actions |
| `Api.kt` | Client du serveur : connexion, `/api/assist/reply`, `/api/assist/digest` |
| `Brain.kt` / `Models.kt` | D'où vient l'intelligence : serveur, ou fournisseur direct (OpenAI, Gemini, personnalisé) avec les mêmes consignes |
| `src/claude/…/ClaudeModel.kt` | Claude via le SDK Java officiel d'Anthropic (APK `claude` seulement) |
| `src/{claude,libre}/…/Flavor.kt` | Ce que chaque APK propose (serveur, fournisseurs) |
| `KeyVault.kt` | Chiffrement des clés API par le Keystore Android |
| `DirectChatActivity.kt` | Chat natif en mode sans serveur |
| `MainActivity.kt` / `ChatActivity.kt` | Réglages, et chat du serveur intégré (WebView déjà connectée) |
