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
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import javax.crypto.KeyGenerator

/**
 * Serverless mode: the phone calls the Claude Messages API itself (official Java SDK),
 * here pointed at a local stub that records the requests and answers like the real API.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class DirectModeTest {

    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private lateinit var api: StubServer
    private val bodies = mutableListOf<JSONObject>()
    private val headers = mutableListOf<Map<String, String>>()
    private var answer = "Avec plaisir, à dimanche !"
    private var stopReason = "end_turn"
    private var status = 200
    private lateinit var prefs: Prefs

    @Before
    fun setUp() {
        KeyVault.keyOverride = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        api = StubServer(statusFor = { status }) { path, h, body ->
            assertEquals("/v1/messages", path)
            headers += h
            bodies += JSONObject(body)
            if (status != 200) {
                """{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}"""
            } else {
                JSONObject()
                    .put("id", "msg_1").put("type", "message").put("role", "assistant").put("model", JSONObject(body).getString("model"))
                    .put("content", org.json.JSONArray().put(JSONObject().put("type", "text").put("text", answer)))
                    .put("stop_reason", stopReason).put("stop_sequence", JSONObject.NULL)
                    .put("usage", JSONObject().put("input_tokens", 120).put("output_tokens", 30))
                    .toString()
            }
        }
        prefs = Prefs(ctx).apply {
            backend = Backend.DIRECT
            apiKey = "sk-ant-test-123"
            apiBaseUrl = "http://127.0.0.1:${api.port}"
            mode = ReplyMode.SUGGEST
            enabledPackages = setOf("com.whatsapp")
            resetUsage()
        }
        Store.reset()
    }

    @After
    fun tearDown() {
        api.stop()
        KeyVault.keyOverride = null
    }

    @Test
    fun apiKeyIsStoredEncrypted() {
        val raw = ctx.getSharedPreferences("j3", Context.MODE_PRIVATE).getString("key_CLAUDE", null)!!
        assertFalse(raw.contains("sk-ant"))
        assertEquals("sk-ant-test-123", prefs.apiKey)
        assertNotEquals(KeyVault.encrypt("x"), KeyVault.encrypt("x"))  // fresh IV every time
        prefs.apiKey = ""
        assertFalse(prefs.hasApiKey)
        assertFalse(prefs.isConnected)
    }

    @Test
    fun draftUsesTheReplyPromptAndCheapModel() {
        val chat = Chat("k", "com.whatsapp", "WhatsApp", "Maman", false, listOf(
            Line("Maman", "Tu viens dimanche ?" + "x".repeat(900), false, 1),
        ))
        val draft = Brain.of(ctx, prefs).draftReply(chat, "tutoie")
        assertEquals(answer, draft)

        val req = bodies.single()
        assertEquals("sk-ant-test-123", headers.single()["x-api-key"])
        assertTrue(headers.single().containsKey("anthropic-version"))
        assertEquals("claude-haiku-4-5", req.getString("model"))
        assertFalse(req.has("output_config"))  // Haiku takes no effort setting
        assertTrue(req.toString().contains("DATA written by other people"))
        val payload = JSONObject(req.getJSONArray("messages").getJSONObject(0).get("content").let {
            if (it is String) it else (it as org.json.JSONArray).getJSONObject(0).getString("text")
        })
        assertEquals("tutoie", payload.getString("style"))
        assertEquals(500, payload.getJSONArray("messages").getJSONObject(0).getString("text").length)
        assertEquals(150L, prefs.usageTokens)
        assertTrue(prefs.usageCostUsd > 0)
    }

    @Test
    fun noReplyAndRefusalMeanNothingToSend() {
        val chat = Chat("k", "com.whatsapp", "WhatsApp", "Promo", false, listOf(Line("Promo", "-50% !", false, 1)))
        answer = "NO_REPLY"
        assertEquals("", Brain.of(ctx, prefs).draftReply(chat, ""))
        answer = "Désolé"; stopReason = "refusal"
        assertEquals("", Brain.of(ctx, prefs).draftReply(chat, ""))
    }

    @Test
    fun sonnetGetsLowEffort() {
        prefs.directModel = Prefs.MODEL_STD
        Brain.of(ctx, prefs).converse(emptyList(), "Bonjour")
        val req = bodies.single()
        assertEquals("claude-sonnet-5-5", req.getString("model"))
        assertEquals("low", req.getJSONObject("output_config").getString("effort"))
    }

    @Test
    fun conversationHistoryAlternatesRoles() {
        val history = listOf(Line("Moi", "Je m'appelle Léa", true, 1), Line("J3anClaud3", "Enchanté Léa !", false, 2))
        Brain.of(ctx, prefs).converse(history, "Comment je m'appelle ?")
        val msgs = bodies.single().getJSONArray("messages")
        assertEquals(listOf("user", "assistant", "user"), (0 until msgs.length()).map { msgs.getJSONObject(it).getString("role") })
        assertTrue(bodies.single().toString().contains("assistant conversationnel francophone"))
    }

    @Test
    fun rejectedKeyIsReportedClearly() {
        status = 401
        val e = runCatching { Brain.of(ctx, prefs).converse(emptyList(), "?") }.exceptionOrNull()
        assertTrue(e is BrainAuthException)
    }

    @Test
    fun fullNotificationFlowWithoutAnyServer() {
        val reply = android.app.PendingIntent.getBroadcast(
            ctx, 3, Intent("test.REPLY").setPackage(ctx.packageName),
            android.app.PendingIntent.FLAG_MUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val action = NotificationCompat.Action.Builder(0, "Répondre", reply)
            .addRemoteInput(RemoteInput.Builder("reply_text").build()).build()
        val style = NotificationCompat.MessagingStyle(Person.Builder().setName("Moi").build())
            .addMessage("Tu viens dimanche ?", System.currentTimeMillis(), Person.Builder().setName("Maman").build())
        val n = NotificationCompat.Builder(ctx, "x").setSmallIcon(android.R.drawable.ic_dialog_email)
            .setStyle(style).addAction(action).setShortcutId("maman").build()
        @Suppress("DEPRECATION")
        val sbn = StatusBarNotification("com.whatsapp", "com.whatsapp", 1, null, 0, 0, 0, n, Process.myUserHandle(), 0L)

        Processor.run(ctx, prefs, Messages.parse(ctx, sbn)!!, Messages.replyAction(n))
        shadowOf(Looper.getMainLooper()).idle()

        assertEquals(1, bodies.size)
        val suggestion = shadowOf(ctx.getSystemService(NotificationManager::class.java)).allNotifications
            .single { it.channelId == Notifier.CHANNEL_SUGGEST }
        assertTrue(suggestion.extras.getCharSequence(Notification.EXTRA_TEXT).toString().contains(answer))
    }
}
