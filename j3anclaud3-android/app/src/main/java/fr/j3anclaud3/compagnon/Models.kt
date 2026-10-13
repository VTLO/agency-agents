package fr.j3anclaud3.compagnon

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** AI providers the phone can call directly, with the user's own key. */
enum class Provider(val label: String, val defaultModel: String, val defaultUrl: String, val presets: List<String>) {
    CLAUDE("Anthropic Claude", Prefs.MODEL_LITE, Prefs.DEFAULT_API_URL, listOf(Prefs.MODEL_LITE, Prefs.MODEL_STD)),
    OPENAI(
        "OpenAI (ou API compatible : Ollama, LM Studio, vLLM…)", "gpt-4o-mini", "https://api.openai.com/v1",
        listOf("gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-3.5-turbo"),
    ),
    GEMINI(
        "Google Gemini", "gemini-1.5-flash", "https://generativelanguage.googleapis.com/v1beta",
        listOf("gemini-1.5-flash", "gemini-1.5-pro"),
    ),
    CUSTOM("Serveur personnalisé (/generate/)", "custom-gpt-4o", "http://192.168.1.10:8000", listOf("custom-gpt-4o")),
}

/** One answer from a model, with token counts when the provider reports them. */
data class Completion(val text: String, val inputTokens: Long = 0, val outputTokens: Long = 0)

/** A chat model behind a provider API. `history` alternates user (me) / assistant turns, oldest first. */
interface ChatModel {
    val provider: Provider
    val model: String
    fun complete(system: String, history: List<Line>, user: String, maxTokens: Int): Completion
}

/** The provider rejected the key (HTTP 401/403). */
class AuthRejected(message: String) : IOException(message)

internal object Http {
    fun postJson(url: String, body: String, headers: Map<String, String>): String {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 90_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            headers.forEach { (k, v) -> setRequestProperty(k, v) }
        }
        try {
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code == 401 || code == 403) throw AuthRejected("Clé API refusée ($code)")
            if (code !in 200..299) throw IOException("HTTP $code : ${text.take(300)}")
            return text
        } finally {
            conn.disconnect()
        }
    }
}

/** OpenAI Chat Completions, and every server that speaks the same protocol (Ollama, LM Studio, vLLM, Mistral…). */
class OpenAIModel(private val apiKey: String, override val model: String, private val baseUrl: String) : ChatModel {
    override val provider = Provider.OPENAI

    override fun complete(system: String, history: List<Line>, user: String, maxTokens: Int): Completion {
        val messages = JSONArray().put(JSONObject().put("role", "system").put("content", system))
        history.forEach { messages.put(JSONObject().put("role", if (it.me) "user" else "assistant").put("content", it.text)) }
        messages.put(JSONObject().put("role", "user").put("content", user))
        val body = JSONObject().put("model", model).put("messages", messages).put("max_tokens", maxTokens)
        val headers = if (apiKey.isNotEmpty()) mapOf("Authorization" to "Bearer $apiKey") else emptyMap()
        val out = JSONObject(Http.postJson("${baseUrl.trimEnd('/')}/chat/completions", body.toString(), headers))
        val text = out.getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content", "")
        val usage = out.optJSONObject("usage")
        return Completion(text, usage?.optLong("prompt_tokens") ?: 0, usage?.optLong("completion_tokens") ?: 0)
    }
}

/** Google Gemini REST `generateContent`. The key travels in a header, not in the URL. */
class GeminiModel(private val apiKey: String, override val model: String, private val baseUrl: String) : ChatModel {
    override val provider = Provider.GEMINI

    override fun complete(system: String, history: List<Line>, user: String, maxTokens: Int): Completion {
        val contents = JSONArray()
        history.forEach {
            contents.put(JSONObject().put("role", if (it.me) "user" else "model")
                .put("parts", JSONArray().put(JSONObject().put("text", it.text))))
        }
        contents.put(JSONObject().put("role", "user").put("parts", JSONArray().put(JSONObject().put("text", user))))
        val body = JSONObject()
            .put("systemInstruction", JSONObject().put("parts", JSONArray().put(JSONObject().put("text", system))))
            .put("contents", contents)
            .put("generationConfig", JSONObject().put("maxOutputTokens", maxTokens))
        val out = JSONObject(
            Http.postJson("${baseUrl.trimEnd('/')}/models/$model:generateContent", body.toString(), mapOf("x-goog-api-key" to apiKey)),
        )
        val candidate = out.optJSONArray("candidates")?.optJSONObject(0)
        // A blocked or empty answer has no parts: treat it as "nothing to send".
        val text = candidate?.optJSONObject("content")?.optJSONArray("parts")?.let { parts ->
            (0 until parts.length()).joinToString("") { parts.getJSONObject(it).optString("text") }
        }.orEmpty()
        val usage = out.optJSONObject("usageMetadata")
        return Completion(text, usage?.optLong("promptTokenCount") ?: 0, usage?.optLong("candidatesTokenCount") ?: 0)
    }
}

/**
 * A self-hosted model behind `POST {base}/generate/` with `{"model", "prompt"}` (e.g. a small
 * proxy in front of Ollama or vLLM). Accepts a plain-text answer or JSON with a usual text field.
 */
class CustomModel(private val apiKey: String, override val model: String, private val baseUrl: String) : ChatModel {
    override val provider = Provider.CUSTOM

    override fun complete(system: String, history: List<Line>, user: String, maxTokens: Int): Completion {
        val prompt = buildString {
            append(system).append("\n\n")
            history.forEach { append(if (it.me) "User: " else "Assistant: ").append(it.text).append('\n') }
            append("User: ").append(user).append("\nAssistant:")
        }
        val body = JSONObject().put("model", model).put("prompt", prompt).put("max_tokens", maxTokens)
        val headers = if (apiKey.isNotEmpty()) mapOf("Authorization" to "Bearer $apiKey") else emptyMap()
        return Completion(extractText(Http.postJson("${baseUrl.trimEnd('/')}/generate/", body.toString(), headers)))
    }

    companion object {
        fun extractText(raw: String): String {
            val trimmed = raw.trim()
            if (!trimmed.startsWith("{")) return trimmed
            val json = runCatching { JSONObject(trimmed) }.getOrNull() ?: return trimmed
            for (k in listOf("response", "text", "reply", "content", "output", "generated_text")) {
                if (json.has(k) && json.get(k) is String) return json.getString(k)
            }
            json.optJSONArray("choices")?.optJSONObject(0)?.let { c ->
                c.optJSONObject("message")?.optString("content")?.let { return it }
                c.optString("text").takeIf { it.isNotEmpty() }?.let { return it }
            }
            return trimmed
        }
    }
}

/**
 * Serverless brain: the phone calls the chosen provider itself. Same prompts, same trimming
 * and same NO_REPLY rule as the J3anClaud3 server, whichever model answers.
 */
class DirectBrain(
    private val chatModel: ChatModel,
    private val onUsage: (input: Long, output: Long) -> Unit = { _, _ -> },
) : Brain {

    override fun draftReply(chat: Chat, style: String): String {
        val lines = JSONArray()
        chat.lines.takeLast(MAX_LINES).forEach {
            lines.put(JSONObject().put("from", it.sender).put("me", it.me).put("text", it.text.take(MAX_CHARS)))
        }
        val payload = JSONObject().put("app", chat.appLabel).put("chat", chat.title).put("group", chat.isGroup)
            .put("style", style).put("messages", lines).toString()
        val text = ask(Prompts.REPLY, emptyList(), payload, 400).trim().trim('"').trim()
        return if (text.isEmpty() || Prompts.NO_REPLY in text) "" else text
    }

    override fun digest(items: List<Captured>): String {
        val arr = JSONArray()
        items.takeLast(80).forEach {
            arr.put(JSONObject().put("app", it.appLabel).put("chat", it.chat).put("from", it.sender)
                .put("text", it.text.take(MAX_CHARS)).put("at", it.at))
        }
        return ask(Prompts.DIGEST, emptyList(), JSONObject().put("items", arr).toString(), 900).trim()
    }

    override fun converse(history: List<Line>, text: String): String = ask(Prompts.CONVERSATION, history, text, 2000).trim()

    private fun ask(system: String, history: List<Line>, user: String, maxTokens: Int): String {
        val c = try {
            chatModel.complete(system, history, user, maxTokens)
        } catch (e: AuthRejected) {
            throw BrainAuthException("Clé API ${chatModel.provider.label} refusée : vérifiez-la dans les réglages.")
        }
        onUsage(c.inputTokens, c.outputTokens)
        return c.text
    }

    companion object {
        const val MAX_LINES = 12
        const val MAX_CHARS = 500
    }
}

/** Providers available in every flavor. */
internal fun genericModel(prefs: Prefs, p: Provider): ChatModel = when (p) {
    Provider.OPENAI -> OpenAIModel(prefs.apiKeyFor(p), prefs.modelFor(p), prefs.urlFor(p))
    Provider.GEMINI -> GeminiModel(prefs.apiKeyFor(p), prefs.modelFor(p), prefs.urlFor(p))
    Provider.CUSTOM -> CustomModel(prefs.apiKeyFor(p), prefs.modelFor(p), prefs.urlFor(p))
    Provider.CLAUDE -> error("Claude is not part of this build")
}
