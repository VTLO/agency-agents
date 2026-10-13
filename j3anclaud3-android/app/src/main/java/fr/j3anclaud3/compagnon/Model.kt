package fr.j3anclaud3.compagnon

import androidx.core.app.NotificationCompat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger

data class Line(val sender: String, val text: String, val me: Boolean, val time: Long)

/** One conversation inside one messaging app, as reconstructed from its notifications. */
data class Chat(
    val key: String,
    val pkg: String,
    val appLabel: String,
    val title: String,
    val isGroup: Boolean,
    val lines: List<Line>,
)

/** A message captured for the on-demand digest. */
data class Captured(val appLabel: String, val chat: String, val sender: String, val text: String, val at: String)

/** A draft waiting for the user's decision, with the messaging app's own reply action. */
data class PendingReply(
    val id: Int,
    val chat: Chat,
    val text: String,
    val action: NotificationCompat.Action,
)

/**
 * Process-wide, in-memory state. Nothing here is written to disk: message contents only live
 * as long as the app process, and are forgotten when Android reclaims it.
 */
object Store {
    private const val MAX_LINES = 12
    private const val MAX_CAPTURED = 300
    private const val MAX_AUTO_PER_HOUR = 20

    private val history = HashMap<String, ArrayDeque<Line>>()
    private val lastHandled = HashMap<String, Long>()
    private val lastAuto = HashMap<String, Long>()
    private val autoTimes = ArrayDeque<Long>()
    private val captured = ArrayDeque<Captured>()
    private val pending = HashMap<Int, PendingReply>()
    private val ids = AtomicInteger(1000)
    private val clock = SimpleDateFormat("HH:mm", Locale.FRANCE)

    /** Merge lines seen in a notification into the conversation history (deduplicated). */
    @Synchronized
    fun merge(key: String, lines: List<Line>): List<Line> {
        val h = history.getOrPut(key) { ArrayDeque() }
        for (l in lines) {
            val dup = h.any { it.time == l.time && it.text == l.text && it.sender == l.sender } ||
                // the app echoes back a reply we sent ourselves, with its own timestamp
                (l.me && h.any { it.me && it.text == l.text })
            if (!dup) h.addLast(l)
        }
        val sorted = h.sortedBy { it.time }.takeLast(MAX_LINES)
        h.clear(); h.addAll(sorted)
        return sorted
    }

    @Synchronized
    fun addMine(key: String, text: String) {
        history.getOrPut(key) { ArrayDeque() }.addLast(Line("Moi", text, true, System.currentTimeMillis()))
    }

    /** True the first time a given incoming message (by timestamp) is seen for a conversation. */
    @Synchronized
    fun isNew(key: String, newestIncoming: Long): Boolean {
        val prev = lastHandled[key] ?: 0L
        if (newestIncoming <= prev) return false
        lastHandled[key] = newestIncoming
        return true
    }

    @Synchronized
    fun autoAllowed(key: String, cooldownMinutes: Int, now: Long = System.currentTimeMillis()): Boolean {
        while (autoTimes.isNotEmpty() && now - autoTimes.first() > 3_600_000) autoTimes.removeFirst()
        if (autoTimes.size >= MAX_AUTO_PER_HOUR) return false
        val last = lastAuto[key] ?: return true
        return now - last >= cooldownMinutes * 60_000L
    }

    @Synchronized
    fun markAuto(key: String, now: Long = System.currentTimeMillis()) {
        lastAuto[key] = now
        autoTimes.addLast(now)
    }

    @Synchronized
    fun capture(chat: Chat, line: Line) {
        captured.addLast(Captured(chat.appLabel, chat.title, line.sender, line.text, clock.format(Date(line.time))))
        while (captured.size > MAX_CAPTURED) captured.removeFirst()
    }

    @Synchronized
    fun capturedSnapshot(): List<Captured> = captured.toList()

    @Synchronized
    fun clearCaptured() = captured.clear()

    @Synchronized
    fun addPending(chat: Chat, text: String, action: NotificationCompat.Action): PendingReply {
        val p = PendingReply(ids.incrementAndGet(), chat, text, action)
        pending[p.id] = p
        return p
    }

    @Synchronized
    fun takePending(id: Int): PendingReply? = pending.remove(id)

    @Synchronized
    fun peekPending(id: Int): PendingReply? = pending[id]

    /** Tests only: the object outlives a single test in the same JVM. */
    @Synchronized
    internal fun reset() {
        history.clear(); lastHandled.clear(); lastAuto.clear(); autoTimes.clear(); captured.clear(); pending.clear()
    }
}
