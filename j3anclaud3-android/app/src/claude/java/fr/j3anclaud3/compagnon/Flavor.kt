package fr.j3anclaud3.compagnon

/** "claude" flavor: J3anClaud3 server, or Claude / OpenAI / Gemini / custom straight from the phone. */
object Flavor {
    const val SERVER_AVAILABLE = true
    val providers = Provider.entries.toList()
    val defaultProvider = Provider.CLAUDE

    fun createModel(prefs: Prefs): ChatModel {
        val p = prefs.provider
        return when (p) {
            Provider.CLAUDE -> ClaudeModel(prefs.apiKeyFor(p), prefs.modelFor(p), prefs.urlFor(p))
            else -> genericModel(prefs, p)
        }
    }
}
