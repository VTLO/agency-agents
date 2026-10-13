package fr.j3anclaud3.compagnon

import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Looper
import android.os.Process
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import androidx.core.app.Person
import androidx.core.app.RemoteInput
import androidx.test.core.app.ApplicationProvider
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import javax.crypto.KeyGenerator

/** OpenAI(-compatible), Gemini and custom /generate/ providers, in every flavor (including "libre"). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ProvidersTest {

    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private lateinit var server: StubServer
    private val calls = mutableListOf<Triple<String, Map<String, String>, String>>()
    private var response: (String) -> String = { "" }
    private var status = 200
    private lateinit var prefs: Prefs
    private val base get() = "http://127.0.0.1:${server.port}"

    @Before
    fun setUp() {
        KeyVault.keyOverride = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        server = StubServer(statusFor = { status }) { path, headers, body ->
            calls += Triple(path, headers, body)
            response(path)
        }
        prefs = Prefs(ctx).apply { backend = Backend.DIRECT; resetUsage() }
        Store.reset()
    }

    @After
    fun tearDown() {
        server.stop()
        KeyVault.keyOverride = null
    }

    private fun use(p: Provider, key: String = "k-123", model: String = p.defaultModel) {
        prefs.provider = p
        prefs.setApiKeyFor(p, key)
        prefs.setModelFor(p, model)
        prefs.setUrlFor(p, if (p == Provider.GEMINI) "$base/v1beta" else if (p == Provider.OPENAI) "$base/v1" else base)
    }

    private val chat = Chat("k", "com.whatsapp", "WhatsApp", "Maman", false, listOf(
        Line("Maman", "Coucou", false, 1), Line("Moi", "Salut", true, 2), Line("Maman", "Tu viens dimanche ?", false, 3),
    ))

    @Test
    fun openAiChatCompletions() {
        use(Provider.OPENAI)
        response = {
            """{"choices":[{"message":{"role":"assistant","content":"Oui, avec plaisir !"}}],"usage":{"prompt_tokens":90,"completion_tokens":7}}"""
        }
        assertEquals("Oui, avec plaisir !", Brain.of(ctx, prefs).draftReply(chat, "tutoie"))
        val (path, headers, body) = calls.single()
        assertEquals("/v1/chat/completions", path)
        assertEquals("Bearer k-123", headers["authorization"])
        val req = JSONObject(body)
        assertEquals("gpt-4o-mini", req.getString("model"))
        val msgs = req.getJSONArray("messages")
        assertEquals("system", msgs.getJSONObject(0).getString("role"))
        assertTrue(msgs.getJSONObject(0).getString("content").contains("answer honestly"))  // never pretends to be human
        assertEquals("tutoie", JSONObject(msgs.getJSONObject(1).getString("content")).getString("style"))
        assertEquals(97L, prefs.usageTokens)
    }

    @Test
    fun openAiCompatibleLocalServerNeedsNoKey() {
        prefs.provider = Provider.OPENAI
        prefs.setUrlFor(Provider.OPENAI, "$base/v1")  // e.g. Ollama on the local network
        prefs.setModelFor(Provider.OPENAI, "llama3.2")
        assertTrue(prefs.isConnected)
        response = { """{"choices":[{"message":{"content":"Salut !"}}]}""" }
        assertEquals("Salut !", Brain.of(ctx, prefs).converse(emptyList(), "Bonjour"))
        assertFalse(calls.single().second.containsKey("authorization"))
    }

    @Test
    fun geminiGenerateContent() {
        use(Provider.GEMINI)
        response = {
            """{"candidates":[{"content":{"role":"model","parts":[{"text":"Bien sûr, "},{"text":"à dimanche !"}]}}],
               "usageMetadata":{"promptTokenCount":80,"candidatesTokenCount":6}}"""
        }
        val history = listOf(Line("Moi", "Je m'appelle Léa", true, 1), Line("J3", "Enchanté !", false, 2))
        assertEquals("Bien sûr, à dimanche !", Brain.of(ctx, prefs).converse(history, "Tu te souviens ?"))
        val (path, headers, body) = calls.single()
        assertEquals("/v1beta/models/gemini-1.5-flash:generateContent", path)
        assertEquals("k-123", headers["x-goog-api-key"])  // key in a header, never in the URL
        val req = JSONObject(body)
        assertTrue(req.getJSONObject("systemInstruction").toString().contains("francophone"))
        val roles = req.getJSONArray("contents").let { a -> (0 until a.length()).map { a.getJSONObject(it).getString("role") } }
        assertEquals(listOf("user", "model", "user"), roles)
        assertEquals(86L, prefs.usageTokens)
    }

    @Test
    fun geminiBlockedAnswerMeansNoReply() {
        use(Provider.GEMINI)
        response = { """{"candidates":[{"finishReason":"SAFETY"}]}""" }
        assertEquals("", Brain.of(ctx, prefs).draftReply(chat, ""))
    }

    @Test
    fun customGenerateEndpoint() {
        use(Provider.CUSTOM, key = "")
        response = { "Hey ! Je te réponds vite." }
        assertTrue(prefs.isConnected)
        assertEquals("Hey ! Je te réponds vite.", Brain.of(ctx, prefs).draftReply(chat, ""))
        val (path, headers, body) = calls.single()
        assertEquals("/generate/", path)
        assertFalse(headers.containsKey("authorization"))
        val req = JSONObject(body)
        assertEquals("custom-gpt-4o", req.getString("model"))
        assertTrue(req.getString("prompt").contains("Tu viens dimanche ?"))
        assertTrue(req.getString("prompt").trimEnd().endsWith("Assistant:"))
    }

    @Test
    fun customResponseFormats() {
        assertEquals("ok", CustomModel.extractText("""{"response":"ok"}"""))
        assertEquals("ok", CustomModel.extractText("""{"choices":[{"message":{"content":"ok"}}]}"""))
        assertEquals("ok", CustomModel.extractText("  ok  "))
    }

    @Test
    fun noReplyIsHonouredWhateverTheProvider() {
        use(Provider.OPENAI)
        response = { """{"choices":[{"message":{"content":"NO_REPLY"}}]}""" }
        assertEquals("", Brain.of(ctx, prefs).draftReply(chat, ""))
    }

    @Test
    fun rejectedKey() {
        use(Provider.OPENAI)
        status = 401
        response = { """{"error":{"message":"Incorrect API key"}}""" }
        val e = runCatching { Brain.of(ctx, prefs).draftReply(chat, "") }.exceptionOrNull()
        assertTrue(e is BrainAuthException)
    }

    @Test
    fun fullNotificationFlowWithOpenAi() {
        use(Provider.OPENAI)
        prefs.mode = ReplyMode.SUGGEST
        prefs.enabledPackages = setOf("com.whatsapp")
        response = { """{"choices":[{"message":{"content":"Oui, dimanche midi ça marche"}}]}""" }
        val reply = android.app.PendingIntent.getBroadcast(
            ctx, 5, Intent("test.REPLY").setPackage(ctx.packageName),
            android.app.PendingIntent.FLAG_MUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val action = NotificationCompat.Action.Builder(0, "Répondre", reply).addRemoteInput(RemoteInput.Builder("r").build()).build()
        val style = NotificationCompat.MessagingStyle(Person.Builder().setName("Moi").build())
            .addMessage("Tu viens dimanche ?", System.currentTimeMillis(), Person.Builder().setName("Maman").build())
        val n = NotificationCompat.Builder(ctx, "x").setSmallIcon(android.R.drawable.ic_dialog_email)
            .setStyle(style).addAction(action).setShortcutId("maman").build()
        @Suppress("DEPRECATION")
        val sbn = StatusBarNotification("com.whatsapp", "com.whatsapp", 1, null, 0, 0, 0, n, Process.myUserHandle(), 0L)

        Processor.run(ctx, prefs, Messages.parse(ctx, sbn)!!, Messages.replyAction(n))
        shadowOf(Looper.getMainLooper()).idle()

        val suggestion = shadowOf(ctx.getSystemService(NotificationManager::class.java)).allNotifications
            .single { it.channelId == Notifier.CHANNEL_SUGGEST }
        assertTrue(suggestion.extras.getCharSequence(Notification.EXTRA_TEXT).toString().contains("dimanche midi"))
        // only the conversation went out, as JSON data inside the user turn
        val sent = JSONObject(JSONObject(calls.single().third).getJSONArray("messages").getJSONObject(1).getString("content"))
        assertEquals("Tu viens dimanche ?", (sent.getJSONArray("messages") as JSONArray).getJSONObject(0).getString("text"))
    }
}
