package fr.j3anclaud3.compagnon

import android.content.Context
import android.content.SharedPreferences

/** What J3anClaud3 does with an incoming message. */
enum class ReplyMode { OFF, SUGGEST, AUTO }

/** Where drafts, digests and chat answers come from. */
enum class Backend {
    /** Through a J3anClaud3 server (admin, blocking, accounting; no key on the phone). */
    SERVER,

    /** Serverless: the phone calls the Claude API with the user's own key. */
    DIRECT,
}

/** All user settings, stored locally in SharedPreferences (never synced, never backed up). */
class Prefs(context: Context) {
    private val sp: SharedPreferences = context.getSharedPreferences("j3", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server", "") ?: ""
        set(v) = sp.edit().putString("server", v.trim().trimEnd('/')).apply()

    var name: String
        get() = sp.getString("name", "") ?: ""
        set(v) = sp.edit().putString("name", v.trim()).apply()

    /** Session token returned by POST /api/login, sent as a Bearer token. */
    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v).apply()

    var mode: ReplyMode
        get() = runCatching { ReplyMode.valueOf(sp.getString("mode", "SUGGEST")!!) }.getOrDefault(ReplyMode.SUGGEST)
        set(v) = sp.edit().putString("mode", v.name).apply()

    /** Packages the user explicitly allowed. Nothing is read from other apps. */
    var enabledPackages: Set<String>
        get() = sp.getStringSet("packages", emptySet())!!.toSet()
        set(v) = sp.edit().putStringSet("packages", v).apply()

    /** Packages that posted message notifications, to offer them in the list. */
    var seenPackages: Set<String>
        get() = sp.getStringSet("seen", emptySet())!!.toSet()
        set(v) = sp.edit().putStringSet("seen", v).apply()

    var replyInGroups: Boolean
        get() = sp.getBoolean("groups", false)
        set(v) = sp.edit().putBoolean("groups", v).apply()

    /** Appended to automatic replies so contacts know an assistant answered. */
    var signAutoReplies: Boolean
        get() = sp.getBoolean("sign", true)
        set(v) = sp.edit().putBoolean("sign", v).apply()

    /** Standing instructions for drafts: tone, tutoiement, things to never say… */
    var style: String
        get() = sp.getString("style", "") ?: ""
        set(v) = sp.edit().putString("style", v.trim()).apply()

    /** Minimum delay between two automatic replies in the same conversation. */
    var autoCooldownMinutes: Int
        get() = sp.getInt("cooldown", 10)
        set(v) = sp.edit().putInt("cooldown", v.coerceIn(1, 1440)).apply()

    var privacyAccepted: Boolean
        get() = sp.getBoolean("privacy", false)
        set(v) = sp.edit().putBoolean("privacy", v).apply()

    var backend: Backend
        get() = if (!Flavor.SERVER_AVAILABLE) Backend.DIRECT
        else runCatching { Backend.valueOf(sp.getString("backend", "SERVER")!!) }.getOrDefault(Backend.SERVER)
        set(v) = sp.edit().putString("backend", v.name).apply()

    /** Provider used in serverless mode. */
    var provider: Provider
        get() = runCatching { Provider.valueOf(sp.getString("provider", null)!!) }.getOrNull()
            ?.takeIf { it in Flavor.providers } ?: Flavor.defaultProvider
        set(v) = sp.edit().putString("provider", v.name).apply()

    /** API key of a provider, stored encrypted with an Android Keystore key (see KeyVault). */
    fun apiKeyFor(p: Provider): String = sp.getString("key_${p.name}", null)?.let { KeyVault.decrypt(it) }.orEmpty()

    fun setApiKeyFor(p: Provider, value: String) {
        val key = value.trim()
        sp.edit().apply { if (key.isEmpty()) remove("key_${p.name}") else putString("key_${p.name}", KeyVault.encrypt(key)) }.apply()
    }

    fun hasApiKeyFor(p: Provider) = sp.contains("key_${p.name}")

    fun modelFor(p: Provider): String = sp.getString("model_${p.name}", null)?.takeIf { it.isNotBlank() } ?: p.defaultModel
    fun setModelFor(p: Provider, v: String) = sp.edit().putString("model_${p.name}", v.trim()).apply()

    /** Base URL of a provider: overridable for OpenAI-compatible servers, gateways and tests. */
    fun urlFor(p: Provider): String = sp.getString("url_${p.name}", null)?.takeIf { it.isNotBlank() } ?: p.defaultUrl
    fun setUrlFor(p: Provider, v: String) = sp.edit().putString("url_${p.name}", v.trim().trimEnd('/')).apply()

    // Shortcuts for the current provider.
    var apiKey: String
        get() = apiKeyFor(provider)
        set(v) = setApiKeyFor(provider, v)
    val hasApiKey: Boolean get() = hasApiKeyFor(provider)
    var directModel: String
        get() = modelFor(provider)
        set(v) = setModelFor(provider, v)
    var apiBaseUrl: String
        get() = urlFor(provider)
        set(v) = setUrlFor(provider, v)

    /** Local spend counter for the serverless mode (the server has its own ledger). */
    val usageTokens: Long get() = sp.getLong("usage_tokens", 0)
    val usageCostUsd: Double get() = Double.fromBits(sp.getLong("usage_cost_bits", 0.0.toBits()))

    @Synchronized
    fun addUsage(model: String, input: Long, output: Long) {
        // Cost is only estimated for models whose price is known here; tokens are always counted.
        val (pin, pout) = PRICES[model] ?: (0.0 to 0.0)
        val cost = usageCostUsd + (input * pin + output * pout) / 1_000_000.0
        sp.edit().putLong("usage_tokens", usageTokens + input + output).putLong("usage_cost_bits", cost.toBits()).apply()
    }

    fun resetUsage() = sp.edit().remove("usage_tokens").remove("usage_cost_bits").apply()

    /** Server mode: signed in. Serverless mode: a key is stored (or the endpoint needs none). */
    val isConnected: Boolean
        get() = when (backend) {
            Backend.SERVER -> serverUrl.isNotEmpty() && token.isNotEmpty()
            Backend.DIRECT -> hasApiKey || provider == Provider.CUSTOM ||
                (provider == Provider.OPENAI && urlFor(Provider.OPENAI) != Provider.OPENAI.defaultUrl)
        }

    companion object {
        const val SIGNATURE = "\n— réponse rédigée par mon assistant J3anClaud3"
        const val DEFAULT_API_URL = "https://api.anthropic.com"
        const val MODEL_LITE = "claude-haiku-4-5"
        const val MODEL_STD = "claude-sonnet-5-5"

        /** USD per million tokens (input, output), for the local estimate only (Claude models). */
        val PRICES = mapOf(MODEL_LITE to (1.0 to 5.0), MODEL_STD to (2.0 to 10.0))
    }
}
