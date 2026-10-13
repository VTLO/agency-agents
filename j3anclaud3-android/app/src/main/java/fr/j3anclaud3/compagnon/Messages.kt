package fr.j3anclaud3.compagnon

import android.app.Notification
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import androidx.core.app.RemoteInput

/** Reads conversations out of other apps' notifications, and answers through their reply action. */
object Messages {

    /** Well-known messaging apps, offered in the settings list when installed. */
    val KNOWN_APPS = listOf(
        "com.whatsapp", "com.whatsapp.w4b", "org.telegram.messenger", "org.thoughtcrime.securesms",
        "com.google.android.apps.messaging", "com.samsung.android.messaging", "com.facebook.orca",
        "com.instagram.android", "com.discord", "com.Slack", "com.microsoft.teams", "com.viber.voip",
        "jp.naver.line.android", "com.snapchat.android", "com.google.android.gm",
    )

    private val KNOWN_LABELS = mapOf(
        "com.whatsapp" to "WhatsApp", "com.whatsapp.w4b" to "WhatsApp Business", "org.telegram.messenger" to "Telegram",
        "org.thoughtcrime.securesms" to "Signal", "com.google.android.apps.messaging" to "Messages",
        "com.samsung.android.messaging" to "Samsung Messages", "com.facebook.orca" to "Messenger",
        "com.instagram.android" to "Instagram", "com.discord" to "Discord", "com.Slack" to "Slack",
        "com.microsoft.teams" to "Teams", "com.viber.voip" to "Viber", "jp.naver.line.android" to "LINE",
        "com.snapchat.android" to "Snapchat", "com.google.android.gm" to "Gmail",
    )

    // One-time codes and security messages never leave the phone.
    private val SENSITIVE = Regex(
        "(code|otp|verification|vérification|validation|mot de passe|password|passcode|2fa|pin)\\D{0,40}\\d{4,8}" +
            "|\\d{4,8}\\D{0,40}(code|otp|verification|vérification)",
        RegexOption.IGNORE_CASE,
    )

    fun isSensitive(text: String) = SENSITIVE.containsMatchIn(text)

    fun appLabel(context: Context, pkg: String): String = try {
        val pm = context.packageManager
        pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
    } catch (e: PackageManager.NameNotFoundException) {
        KNOWN_LABELS[pkg] ?: pkg.substringAfterLast('.')
    }

    fun isInstalled(context: Context, pkg: String) = try {
        context.packageManager.getApplicationInfo(pkg, 0); true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    /** Does this notification look like a chat message (as opposed to media, downloads, alarms…)? */
    fun looksLikeMessage(n: Notification): Boolean =
        n.category == Notification.CATEGORY_MESSAGE ||
            NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n) != null ||
            replyAction(n) != null

    /** Rebuild the conversation shown in a notification. Null when it carries no readable message. */
    fun parse(context: Context, sbn: StatusBarNotification): Chat? {
        val n = sbn.notification
        val pkg = sbn.packageName
        val label = appLabel(context, pkg)
        val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n)
        if (style != null) {
            val me = style.user.name?.toString().orEmpty()
            val lines = style.messages.mapNotNull { m ->
                val text = m.text?.toString()?.trim().orEmpty()
                if (text.isEmpty()) return@mapNotNull null
                val sender = m.person?.name?.toString()
                val mine = m.person == null || (sender != null && sender == me && me.isNotEmpty())
                Line(if (mine) "Moi" else sender ?: "?", text, mine, m.timestamp)
            }
            if (lines.isEmpty()) return null
            val title = style.conversationTitle?.toString()
                ?: lines.lastOrNull { !it.me }?.sender
                ?: n.extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
            return Chat(chatKey(pkg, sbn, title), pkg, label, title, style.isGroupConversation, lines)
        }
        // Apps without MessagingStyle: title = sender (or chat), text = message.
        val extras = n.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim().orEmpty()
        val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT))
            ?.toString()?.trim().orEmpty()
        if (title.isEmpty() || text.isEmpty()) return null
        val line = Line(title, text, false, if (n.`when` > 0) n.`when` else sbn.postTime)
        return Chat(chatKey(pkg, sbn, title), pkg, label, title, false, listOf(line))
    }

    private fun chatKey(pkg: String, sbn: StatusBarNotification, title: String): String {
        val shortcut = sbn.notification.shortcutId
        return "$pkg|" + (shortcut ?: sbn.tag ?: title)
    }

    /** The messaging app's own "Reply" action (direct reply with free-form text), if any. */
    fun replyAction(n: Notification): NotificationCompat.Action? {
        val candidates = buildList {
            for (i in 0 until NotificationCompat.getActionCount(n)) NotificationCompat.getAction(n, i)?.let(::add)
            addAll(NotificationCompat.WearableExtender(n).actions)
        }
        val usable = candidates.filter { a -> a.remoteInputs?.any { it.allowFreeFormInput } == true }
        return usable.firstOrNull { it.semanticAction == NotificationCompat.Action.SEMANTIC_ACTION_REPLY } ?: usable.firstOrNull()
    }

    /** Send `text` through the app's reply action, exactly as if typed in the notification. */
    fun send(context: Context, action: NotificationCompat.Action, text: String) {
        val inputs = action.remoteInputs ?: return
        val intent = Intent().addFlags(Intent.FLAG_RECEIVER_FOREGROUND)
        val results = Bundle()
        inputs.filter { it.allowFreeFormInput }.forEach { results.putCharSequence(it.resultKey, text) }
        RemoteInput.addResultsToIntent(inputs, intent, results)
        action.actionIntent?.send(context, 0, intent)
    }
}
