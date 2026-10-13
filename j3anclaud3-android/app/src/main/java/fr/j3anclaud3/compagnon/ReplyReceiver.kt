package fr.j3anclaud3.compagnon

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.RemoteInput

/** Handles the Send / Edit / Ignore buttons of a suggestion notification. */
class ReplyReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getIntExtra(Notifier.EXTRA_ID, -1)
        when (intent.action) {
            ACTION_DISMISS -> {
                Store.takePending(id)
                Notifier.cancel(context, id)
            }
            ACTION_SEND, ACTION_EDIT -> {
                val p = Store.takePending(id)
                Notifier.cancel(context, id)
                if (p == null) {
                    Notifier.status(context, "Cette suggestion a expiré. Répondez directement dans l'application de messagerie.")
                    return
                }
                val edited = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(Notifier.KEY_EDIT)?.toString()?.trim()
                val text = if (intent.action == ACTION_EDIT) edited.orEmpty() else p.text
                if (text.isEmpty()) return
                try {
                    Messages.send(context, p.action, text)
                    Store.addMine(p.chat.key, text)
                } catch (e: Exception) {
                    Notifier.status(context, "Envoi impossible (${p.chat.appLabel}) : répondez depuis l'application.")
                }
            }
        }
    }

    companion object {
        const val ACTION_SEND = "fr.j3anclaud3.compagnon.SEND"
        const val ACTION_EDIT = "fr.j3anclaud3.compagnon.EDIT"
        const val ACTION_DISMISS = "fr.j3anclaud3.compagnon.DISMISS"
    }
}
