package fr.j3anclaud3.compagnon

import android.content.Context

/** The key or session was refused: the user must fix the settings. */
class BrainAuthException(message: String) : Exception(message)

/** Where the intelligence comes from. All calls are blocking: never on the main thread. */
interface Brain {
    /** Text to send, or "" when no reply should be sent. */
    fun draftReply(chat: Chat, style: String): String
    fun digest(items: List<Captured>): String
    /** Free conversation (serverless chat screen). `history` alternates user/assistant, oldest first. */
    fun converse(history: List<Line>, text: String): String

    companion object {
        fun of(context: Context, prefs: Prefs): Brain = when (prefs.backend) {
            Backend.DIRECT -> {
                val model = Flavor.createModel(prefs)
                DirectBrain(model) { i, o -> prefs.addUsage(model.model, i, o) }
            }
            Backend.SERVER -> ServerBrain(Api(prefs.serverUrl, prefs.token))
        }
    }
}

/** Through the J3anClaud3 server: admin, blocking and accounting stay central, no key on the phone. */
class ServerBrain(private val api: Api) : Brain {
    override fun draftReply(chat: Chat, style: String) = wrap { api.draftReply(chat, style) }
    override fun digest(items: List<Captured>) = wrap { api.digest(items) }
    override fun converse(history: List<Line>, text: String): String =
        throw UnsupportedOperationException("server mode uses the server's web chat")

    private fun <T> wrap(call: () -> T): T = try {
        call()
    } catch (e: ApiException) {
        if (e.status == 401) throw BrainAuthException("Session J3anClaud3 expirée : reconnectez-vous dans l'application.")
        throw e
    }
}
