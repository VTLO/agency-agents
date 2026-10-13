package fr.j3anclaud3.compagnon

import android.content.Context
import android.content.SharedPreferences

/** What J3anClaud3 does with an incoming message. */
enum class ReplyMode { OFF, SUGGEST, AUTO }

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

    val isConnected: Boolean get() = serverUrl.isNotEmpty() && token.isNotEmpty()

    companion object {
        const val SIGNATURE = "\n— réponse rédigée par mon assistant J3anClaud3"
    }
}
