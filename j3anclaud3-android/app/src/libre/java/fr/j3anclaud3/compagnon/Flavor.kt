package fr.j3anclaud3.compagnon

/**
 * "libre" flavor: no Anthropic code and no J3anClaud3 server. The phone talks to OpenAI (or any
 * OpenAI-compatible API such as Ollama), Google Gemini, or a self-hosted /generate/ endpoint.
 */
object Flavor {
    const val SERVER_AVAILABLE = false
    val providers = listOf(Provider.OPENAI, Provider.GEMINI, Provider.CUSTOM)
    val defaultProvider = Provider.OPENAI

    fun createModel(prefs: Prefs): ChatModel = genericModel(prefs, prefs.provider)
}
