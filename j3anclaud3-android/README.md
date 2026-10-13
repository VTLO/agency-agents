# 📱 J3anClaud3 pour Android — l'assistant dans toutes vos messageries

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

* **Aucune clé d'API sur le téléphone** : l'IA est appelée par votre serveur J3anClaud3 (voir `../j3anclaud3`), qui garde le compte administrateur, le blocage et le suivi de consommation.
* **Rien n'est stocké** : les messages ne vivent qu'en mémoire, le temps de la session de l'application.
* **Codes de vérification, banque, sécurité** : détectés sur le téléphone, jamais envoyés au serveur. Le modèle répond aussi `NO_REPLY` pour les sujets sensibles, les messages automatiques, la publicité ou les urgences.
* Les messages reçus sont traités comme des **données** : le prompt interdit au modèle de suivre les instructions qu'ils contiennent.

## Installation

1. Récupérez l'APK :
   * depuis l'onglet **Actions** de GitHub (workflow *J3anClaud3 Android* → artefact `j3anclaud3-android-apk`), ou
   * en le compilant : `cd j3anclaud3-android && ./gradlew assembleDebug` → `app/build/outputs/apk/debug/j3anclaud3-0.1.0-debug.apk`.
2. Sur le téléphone, ouvrez l'APK. Android demande d'autoriser l'installation d'applications de cette source.
3. Dans J3anClaud3 :
   1. lisez et acceptez l'avertissement de confidentialité ;
   2. **Serveur** : adresse de votre serveur J3anClaud3 et votre prénom. Ajoutez le mot de passe seulement pour le compte administrateur ;
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
J3_KEYSTORE=$PWD/j3.jks J3_KEYSTORE_PASSWORD=… J3_KEY_ALIAS=j3 J3_KEY_PASSWORD=… ./gradlew assembleRelease
```

## Limites à connaître

* L'assistant ne voit que ce que l'application de messagerie met dans sa notification (en général les derniers messages de la conversation), et seulement si l'application a une notification de message active.
* Les réponses passent par le bouton « Répondre » des notifications : une application qui n'en propose pas (certains e-mails, Snapchat…) peut être résumée mais pas répondue.
* Une notification ignorée ou balayée avant la suggestion ne peut plus servir à répondre.
* Les médias (photos, vocaux) ne sont pas analysés.

## Développement

```bash
./gradlew testDebugUnitTest   # tests Robolectric du flux complet (vraies notifications Android)
./gradlew lintDebug
./gradlew assembleDebug
```

Les tests construisent de vraies notifications de type WhatsApp (MessagingStyle et action de réponse
directe) et vérifient le parcours complet face à un faux serveur J3anClaud3 local : brouillon demandé,
suggestion affichée, réponse remise au bouton « Répondre » de l'application, texte modifié, ignorer,
déduplication des notifications republiées, codes jamais envoyés, groupes, `NO_REPLY`, réponses
automatiques signées avec délai minimum entre deux envois, applications non cochées ignorées.
Options : `-ProbolectricRepo=<miroir Maven>` et `-Pj3Screenshots=<dossier>` (rendu PNG de l'écran de réglages).

| Fichier | Rôle |
|---|---|
| `J3NotificationListener.kt` | Reçoit les notifications, filtre, et `Processor` décide : rien, suggestion ou envoi automatique |
| `Messages.kt` | Lecture des conversations (MessagingStyle, sinon titre et texte), détection des codes, envoi via `RemoteInput` |
| `Model.kt` | État en mémoire : historique par conversation, déduplication, délai minimum entre envois, brouillons en attente |
| `Notifier.kt` / `ReplyReceiver.kt` | Notifications de suggestion (Envoyer · Modifier · Ignorer) et leurs actions |
| `Api.kt` | Client du serveur : connexion, `/api/assist/reply`, `/api/assist/digest` |
| `MainActivity.kt` / `ChatActivity.kt` | Réglages, et chat du serveur intégré (WebView déjà connectée) |
