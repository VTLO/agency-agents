package fr.j3anclaud3.compagnon

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/**
 * Drives the real flow with genuine Android notification objects: a WhatsApp-style
 * MessagingStyle notification with a direct-reply action comes in, J3anClaud3 asks a
 * (stub) server for a draft, shows a suggestion, and the "Envoyer" button answers
 * through WhatsApp's own reply action.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class CompanionFlowTest {

    private val ctx: Context = ApplicationProvider.getApplicationContext()
    private lateinit var server: StubServer
    private val authHeaders = mutableListOf<String?>()
    private val requests = mutableListOf<JSONObject>()
    private var draft = "Oui, dimanche midi ça marche 🙂"

    /** What the messaging app received through its reply action (text typed "in the notification"). */
    private val sentReplies: List<String>
        get() = shadowOf(ctx as android.app.Application).broadcastIntents
            .filter { it.action == REPLY_ACTION }
            .mapNotNull { RemoteInput.getResultsFromIntent(it)?.getCharSequence(KEY)?.toString() }
    private lateinit var prefs: Prefs

    @Before
    fun setUp() {
        server = StubServer { path, headers, body ->
            assertEquals("/api/assist/reply", path)
            authHeaders += headers["authorization"]
            requests += JSONObject(body)
            JSONObject().put("reply", draft).toString()
        }
        prefs = Prefs(ctx).apply {
            serverUrl = "http://127.0.0.1:${server.port}"
            token = "tok"
            mode = ReplyMode.SUGGEST
            enabledPackages = setOf(WHATSAPP)
        }
        Store.reset()
    }

    @After
    fun tearDown() = server.stop()

    // --- helpers ------------------------------------------------------------------

    private val now = System.currentTimeMillis()

    private fun whatsapp(
        chat: String,
        vararg msgs: Pair<String?, String>,
        group: Boolean = false,
        t0: Long = now - 60_000,
        times: List<Long>? = null,
    ): StatusBarNotification {
        val reply = PendingIntent.getBroadcast(
            ctx, 7, Intent(REPLY_ACTION).setPackage(ctx.packageName), PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val action = NotificationCompat.Action.Builder(0, "Répondre", reply)
            .addRemoteInput(RemoteInput.Builder(KEY).setLabel("Répondre").build())
            .setSemanticAction(NotificationCompat.Action.SEMANTIC_ACTION_REPLY)
            .build()
        val style = NotificationCompat.MessagingStyle(Person.Builder().setName("Moi").build())
            .setConversationTitle(if (group) chat else null)
            .setGroupConversation(group)
        msgs.forEachIndexed { i, (from, text) ->
            style.addMessage(text, times?.get(i) ?: (t0 + i), from?.let { Person.Builder().setName(it).build() })
        }
        val n = NotificationCompat.Builder(ctx, "x")
            .setSmallIcon(android.R.drawable.ic_dialog_email)
            .setStyle(style)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .addAction(action)
            .setShortcutId("chat-$chat")
            .build()
        @Suppress("DEPRECATION")
        return StatusBarNotification(WHATSAPP, WHATSAPP, 1, null, 0, 0, 0, n, Process.myUserHandle(), 0L)
    }

    private fun deliver(sbn: StatusBarNotification) {
        val chat = Messages.parse(ctx, sbn)
        assertNotNull("notification should parse", chat)
        Processor.run(ctx, prefs, chat!!, Messages.replyAction(sbn.notification))
        shadowOf(Looper.getMainLooper()).idle()
    }

    /**
     * Tap a button of one of our notifications. Robolectric only routes broadcasts through
     * intent filters, so the explicit (filter-less) intent is handed to ReplyReceiver directly,
     * merged with the fill-in a real tap produces (the typed text, for "Modifier").
     */
    private fun tap(action: Notification.Action, fillIn: Intent? = null) {
        val intent = Intent(shadowOf(action.actionIntent).savedIntent)
        if (fillIn != null) intent.fillIn(fillIn, Intent.FILL_IN_CLIP_DATA)
        ReplyReceiver().onReceive(ctx, intent)
        shadowOf(Looper.getMainLooper()).idle()
    }

    private fun suggestions(): List<Notification> =
        shadowOf(ctx.getSystemService(NotificationManager::class.java)).allNotifications
            .filter { it.channelId == Notifier.CHANNEL_SUGGEST }

    // --- tests ----------------------------------------------------------------------

    @Test
    fun suggestionThenSendGoesThroughTheAppsOwnReplyAction() {
        deliver(whatsapp("Maman", "Maman" to "Coucou", null to "Salut maman", "Maman" to "Tu viens dimanche ?"))

        assertEquals(listOf("Bearer tok"), authHeaders)
        val req = requests.single()
        assertEquals("Maman", req.getString("chat"))
        val sent = req.getJSONArray("messages")
        assertEquals(3, sent.length())
        assertTrue(sent.getJSONObject(1).getBoolean("me"))  // my own earlier message is marked as mine
        assertEquals("Tu viens dimanche ?", sent.getJSONObject(2).getString("text"))

        val s = suggestions().single()
        assertEquals(listOf("Envoyer", "Modifier", "Ignorer"), s.actions.map { it.title.toString() })
        assertTrue(s.extras.getCharSequence(Notification.EXTRA_TITLE).toString().startsWith("Maman"))

        tap(s.actions[0])  // "Envoyer"
        assertEquals(listOf(draft), sentReplies)
        assertTrue(suggestions().isEmpty())  // the suggestion is dismissed once used
    }

    @Test
    fun editButtonSendsTheEditedText() {
        deliver(whatsapp("Léo", "Léo" to "On se voit ce soir ?"))
        val edit = suggestions().single().actions[1]
        val fill = Intent()
        android.app.RemoteInput.addResultsToIntent(edit.remoteInputs, fill, android.os.Bundle().apply {
            putCharSequence(Notifier.KEY_EDIT, "Oui, 20h chez moi")
        })
        tap(edit, fill)
        assertEquals(listOf("Oui, 20h chez moi"), sentReplies)
    }

    @Test
    fun sameMessageRepostedIsHandledOnce() {
        val sbn = whatsapp("Maman", "Maman" to "Tu viens dimanche ?")
        deliver(sbn)
        deliver(sbn)  // apps re-post the same notification on every update
        assertEquals(1, requests.size)
    }

    @Test
    fun codesNeverLeaveThePhone() {
        deliver(whatsapp("Banque", "Banque" to "Votre code de vérification est 482913"))
        assertTrue(requests.isEmpty())
        assertTrue(suggestions().isEmpty())
    }

    @Test
    fun groupsAreSkippedUnlessEnabled() {
        deliver(whatsapp("Famille", "Paul" to "Qui ramène le dessert ?", group = true))
        assertTrue(requests.isEmpty())
        prefs.replyInGroups = true
        deliver(whatsapp("Famille", "Paul" to "Alors, le dessert ?", group = true, t0 = now))
        assertEquals(1, requests.size)
        assertTrue(requests.single().getBoolean("group"))
    }

    @Test
    fun serverNoReplyMeansNothingHappens() {
        draft = ""
        deliver(whatsapp("Promo", "Promo" to "-50% ce week-end !"))
        assertEquals(1, requests.size)
        assertTrue(suggestions().isEmpty())
        assertTrue(sentReplies.isEmpty())
    }

    @Test
    fun autoModeSignsRespectsCooldownThenFallsBackToSuggestion() {
        prefs.mode = ReplyMode.AUTO
        prefs.autoCooldownMinutes = 10
        deliver(whatsapp("Julie", "Julie" to "Tu es dispo demain ?", t0 = now - 30_000))
        assertEquals(listOf(draft + Prefs.SIGNATURE), sentReplies)
        assertTrue(suggestions().isEmpty())

        deliver(whatsapp("Julie", "Julie" to "Et après-demain ?", t0 = now + 1_000))  // within the cooldown
        assertEquals(1, sentReplies.size)
        assertEquals(1, suggestions().size)  // asked instead of sending
    }

    @Test
    fun appsNotEnabledAreIgnoredByTheListener() {
        prefs.enabledPackages = emptySet()
        val sbn = whatsapp("Maman", "Maman" to "Coucou")
        org.robolectric.Robolectric.setupService(J3NotificationListener::class.java).onNotificationPosted(sbn)
        assertTrue(requests.isEmpty())
        assertTrue(WHATSAPP in prefs.seenPackages)  // offered in the settings list, but not read
    }

    @Test
    fun ignoreDismissesWithoutSending() {
        deliver(whatsapp("Léo", "Léo" to "Dispo ?"))
        tap(suggestions().single().actions[2])  // "Ignorer"
        assertTrue(sentReplies.isEmpty())
        assertTrue(suggestions().isEmpty())
    }

    @Test
    fun echoOfMyOwnReplyIsNotDuplicatedInTheContext() {
        prefs.mode = ReplyMode.AUTO
        deliver(whatsapp("Julie", "Julie" to "Tu es dispo demain ?", t0 = now - 30_000))
        val sent = sentReplies.single()
        // WhatsApp re-posts the conversation including my reply (its own timestamp), then Julie answers.
        val later = System.currentTimeMillis() + 5_000
        deliver(whatsapp(
            "Julie", "Julie" to "Tu es dispo demain ?", null to sent, "Julie" to "Super !",
            times = listOf(now - 30_000, later - 2_000, later),
        ))
        assertEquals(2, requests.size)
        val context = requests.last().getJSONArray("messages")
        val mine = (0 until context.length()).map { context.getJSONObject(it) }.filter { it.getBoolean("me") }
        assertEquals(1, mine.size)
    }

    @Test
    fun sensitivePatterns() {
        assertTrue(Messages.isSensitive("Your verification code: 123456"))
        assertTrue(Messages.isSensitive("123456 est votre code Instagram"))
        assertFalse(Messages.isSensitive("On se retrouve à 18h30 ?"))
        assertFalse(Messages.isSensitive("J'ai 2 codes promo pour le ciné"))
    }

    companion object {
        const val WHATSAPP = "com.whatsapp"
        const val KEY = "reply_text"
        const val REPLY_ACTION = "test.whatsapp.REPLY"
    }
}
