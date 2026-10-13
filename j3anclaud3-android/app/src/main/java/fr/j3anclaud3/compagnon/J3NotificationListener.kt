package fr.j3anclaud3.compagnon

import android.app.Notification
import android.content.Context
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.core.app.NotificationCompat
import java.util.concurrent.Executors

/**
 * Receives every notification once the user grants "Notification access" in Android settings,
 * but only acts on messaging apps the user explicitly enabled in J3anClaud3.
 */
class J3NotificationListener : NotificationListenerService() {

    private val worker = Executors.newSingleThreadExecutor()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName == packageName) return
        val n = sbn.notification
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0 || n.flags and Notification.FLAG_ONGOING_EVENT != 0) return
        if (!Messages.looksLikeMessage(n)) return

        val prefs = Prefs(this)
        if (sbn.packageName !in prefs.seenPackages) prefs.seenPackages = prefs.seenPackages + sbn.packageName
        if (sbn.packageName !in prefs.enabledPackages) return

        val chat = Messages.parse(this, sbn) ?: return
        val action = Messages.replyAction(n)
        worker.execute { Processor.run(this, prefs, chat, action) }
    }

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }
}

/** Decides what to do with one incoming message. Blocking (calls the server): run off the main thread. */
internal object Processor {
    private const val TAG = "J3Processor"

    fun run(ctx: Context, prefs: Prefs, parsed: Chat, action: NotificationCompat.Action?) {
        val lines = Store.merge(parsed.key, parsed.lines)
        val chat = parsed.copy(lines = lines)
        val newest = lines.lastOrNull() ?: return
        if (newest.me) return  // our own message echoed back by the app
        if (!Store.isNew(chat.key, newest.time)) return  // same message, notification merely updated
        Store.capture(chat, newest)

        if (prefs.mode == ReplyMode.OFF || action == null || !prefs.isConnected) return
        if (chat.isGroup && !prefs.replyInGroups) return
        if (Messages.isSensitive(newest.text)) return  // codes & security messages never leave the phone

        val draft = try {
            Brain.of(ctx, prefs).draftReply(chat, prefs.style)
        } catch (e: BrainAuthException) {
            Notifier.status(ctx, e.message ?: "Connexion refusée : vérifiez les réglages.")
            return
        } catch (e: Exception) {
            Log.w(TAG, "draft failed: ${e.message}")
            return
        }
        if (draft.isBlank()) return  // the server judged that no reply should be sent

        when (prefs.mode) {
            ReplyMode.SUGGEST -> Notifier.suggest(ctx, Store.addPending(chat, draft, action))
            ReplyMode.AUTO -> {
                if (!Store.autoAllowed(chat.key, prefs.autoCooldownMinutes)) {
                    Notifier.suggest(ctx, Store.addPending(chat, draft, action))  // over the limit: ask instead
                    return
                }
                val text = if (prefs.signAutoReplies) draft + Prefs.SIGNATURE else draft
                try {
                    Messages.send(ctx, action, text)
                    Store.addMine(chat.key, text)
                    Store.markAuto(chat.key)
                    Notifier.sentAutomatically(ctx, chat, text)
                } catch (e: Exception) {
                    Log.w(TAG, "auto send failed: ${e.message}")
                    Notifier.suggest(ctx, Store.addPending(chat, draft, action))
                }
            }
            ReplyMode.OFF -> Unit
        }
    }
}
