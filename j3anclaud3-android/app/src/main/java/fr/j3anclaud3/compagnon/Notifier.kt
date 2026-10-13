package fr.j3anclaud3.compagnon

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.RemoteInput

/** J3anClaud3's own notifications: reply suggestions with Send / Edit / Ignore, and status. */
object Notifier {
    const val CHANNEL_SUGGEST = "suggestions"
    const val CHANNEL_STATUS = "status"
    const val EXTRA_ID = "pending_id"
    const val KEY_EDIT = "edited_text"
    private const val STATUS_ID = 1

    fun createChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_SUGGEST, context.getString(R.string.channel_suggestions), NotificationManager.IMPORTANCE_HIGH),
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_STATUS, context.getString(R.string.channel_status), NotificationManager.IMPORTANCE_LOW),
        )
    }

    fun suggest(context: Context, p: PendingReply) {
        createChannels(context)
        val last = p.chat.lines.lastOrNull { !it.me }
        val edit = NotificationCompat.Action.Builder(
            R.drawable.ic_stat_j3, "Modifier", broadcast(context, ReplyReceiver.ACTION_EDIT, p.id, mutable = true),
        ).addRemoteInput(RemoteInput.Builder(KEY_EDIT).setLabel("Votre réponse").build())
            .setAllowGeneratedReplies(false)
            .build()
        val n = NotificationCompat.Builder(context, CHANNEL_SUGGEST)
            .setSmallIcon(R.drawable.ic_stat_j3)
            .setContentTitle("${p.chat.title} · ${p.chat.appLabel}")
            .setContentText("Suggestion : ${p.text}")
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    (if (last != null) "« ${last.text.take(140)} »\n\n" else "") + "💬 ${p.text}",
                ),
            )
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setAutoCancel(true)
            .addAction(R.drawable.ic_stat_j3, "Envoyer", broadcast(context, ReplyReceiver.ACTION_SEND, p.id))
            .addAction(edit)
            .addAction(R.drawable.ic_stat_j3, "Ignorer", broadcast(context, ReplyReceiver.ACTION_DISMISS, p.id))
            .setDeleteIntent(broadcast(context, ReplyReceiver.ACTION_DISMISS, p.id))
            .build()
        notify(context, p.id, n)
    }

    fun sentAutomatically(context: Context, chat: Chat, text: String) {
        createChannels(context)
        val n = NotificationCompat.Builder(context, CHANNEL_STATUS)
            .setSmallIcon(R.drawable.ic_stat_j3)
            .setContentTitle("Réponse envoyée à ${chat.title}")
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .build()
        notify(context, chat.key.hashCode(), n)
    }

    fun status(context: Context, text: String) {
        createChannels(context)
        val n = NotificationCompat.Builder(context, CHANNEL_STATUS)
            .setSmallIcon(R.drawable.ic_stat_j3)
            .setContentTitle(context.getString(R.string.app_name))
            .setContentText(text)
            .setContentIntent(
                PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE),
            )
            .setAutoCancel(true)
            .build()
        notify(context, STATUS_ID, n)
    }

    fun cancel(context: Context, id: Int) = NotificationManagerCompat.from(context).cancel(id)

    private fun notify(context: Context, id: Int, n: android.app.Notification) {
        val nm = NotificationManagerCompat.from(context)
        if (nm.areNotificationsEnabled()) {
            try {
                nm.notify(id, n)
            } catch (e: SecurityException) {
                // POST_NOTIFICATIONS refused on Android 13+: nothing to show.
            }
        }
    }

    private fun broadcast(context: Context, action: String, id: Int, mutable: Boolean = false): PendingIntent {
        val intent = Intent(context, ReplyReceiver::class.java).setAction(action).putExtra(EXTRA_ID, id)
        // A RemoteInput needs a mutable PendingIntent; everything else stays immutable.
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (mutable) PendingIntent.FLAG_MUTABLE else PendingIntent.FLAG_IMMUTABLE)
        val slot = when (action) { ReplyReceiver.ACTION_SEND -> 0; ReplyReceiver.ACTION_EDIT -> 1; else -> 2 }
        return PendingIntent.getBroadcast(context, id * 3 + slot, intent, flags)
    }
}
