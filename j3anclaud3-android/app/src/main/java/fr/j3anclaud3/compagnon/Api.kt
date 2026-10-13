package fr.j3anclaud3.compagnon

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

class ApiException(val status: Int, message: String) : IOException(message)

/**
 * Minimal client for the J3anClaud3 server. The model and its API key stay on the server:
 * the phone only sends the few message lines needed and gets back a draft or a digest.
 * Blocking calls: always run them off the main thread.
 */
class Api(private val baseUrl: String, private val token: String = "") {

    data class Login(val user: String, val token: String, val admin: Boolean, val mode: String)

    fun login(name: String, password: String = ""): Login {
        val out = post("/api/login", JSONObject().put("name", name).put("password", password), auth = false)
        return Login(out.getString("user"), out.getString("token"), out.optBoolean("admin"), out.optString("mode"))
    }

    /** Returns the text to send, or "" when the server judges no reply should be sent. */
    fun draftReply(chat: Chat, style: String): String {
        val messages = JSONArray()
        chat.lines.forEach { messages.put(JSONObject().put("from", it.sender).put("me", it.me).put("text", it.text)) }
        val body = JSONObject()
            .put("app", chat.appLabel)
            .put("chat", chat.title)
            .put("group", chat.isGroup)
            .put("style", style)
            .put("messages", messages)
        return post("/api/assist/reply", body).optString("reply", "")
    }

    fun digest(items: List<Captured>): String {
        val arr = JSONArray()
        items.forEach {
            arr.put(JSONObject().put("app", it.appLabel).put("chat", it.chat).put("from", it.sender).put("text", it.text).put("at", it.at))
        }
        return post("/api/assist/digest", JSONObject().put("items", arr)).optString("summary", "")
    }

    private fun post(path: String, body: JSONObject, auth: Boolean = true): JSONObject {
        val conn = (URL(baseUrl + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
            if (auth && token.isNotEmpty()) setRequestProperty("Authorization", "Bearer $token")
        }
        try {
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull().orEmpty()
                throw ApiException(code, detail.ifEmpty { "HTTP $code" })
            }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }
}
