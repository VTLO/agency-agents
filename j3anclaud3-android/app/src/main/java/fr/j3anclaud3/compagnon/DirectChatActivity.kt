package fr.j3anclaud3.compagnon

import android.app.Activity
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Chat with J3anClaud3 without a server: the phone talks to Claude with the user's key.
 * The thread lives in memory only, trimmed in blocks like the server's conversation mode.
 */
class DirectChatActivity : Activity() {

    private lateinit var feed: LinearLayout
    private lateinit var scroll: ScrollView
    private lateinit var input: EditText
    private lateinit var send: Button
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        title = getString(R.string.chat_title)
        feed = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(12), dp(12), dp(12), dp(12)) }
        scroll = ScrollView(this).apply { addView(feed); isFillViewport = true }
        input = EditText(this).apply {
            hint = "Écrivez votre message…"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            maxLines = 5
            imeOptions = EditorInfo.IME_ACTION_SEND
        }
        send = Button(this).apply { text = "Envoyer"; isAllCaps = false; setOnClickListener { submit() } }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(4), dp(8), dp(8))
            addView(input, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
            addView(send)
        }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(scroll, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
            addView(bar, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        })
        if (thread.isEmpty()) {
            bubble("👋 Bonjour ! Je suis J3anClaud3, directement sur votre téléphone. Posez-moi vos questions. " +
                "Tapez NOUVEAU pour effacer la discussion.", mine = false)
        } else {
            thread.forEach { bubble(it.text, it.me) }
        }
    }

    private fun submit() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        input.setText("")
        if (text.equals("nouveau", ignoreCase = true)) {
            thread.clear(); feed.removeAllViews()
            bubble("🆕 C'est noté, on repart de zéro.", mine = false)
            return
        }
        bubble(text, mine = true)
        val history = thread.toList()
        val waiting = bubble("…", mine = false)
        send.isEnabled = false
        Thread {
            val reply = runCatching { Brain.of(this, prefs).converse(history, text) }
            runOnUiThread {
                send.isEnabled = true
                reply.onSuccess { answer ->
                    val shown = answer.ifBlank { "Je ne peux pas répondre à cela, pouvez-vous reformuler ?" }
                    waiting.text = shown
                    thread += Line("Moi", text, true, System.currentTimeMillis())
                    thread += Line("J3anClaud3", shown, false, System.currentTimeMillis())
                    trim()
                }.onFailure { waiting.text = "⚠️ ${it.message ?: "Erreur réseau"}" }
                scroll.post { scroll.fullScroll(ScrollView.FOCUS_DOWN) }
            }
        }.start()
    }

    private fun bubble(text: String, mine: Boolean): TextView {
        val tv = TextView(this).apply {
            this.text = text
            textSize = 15f
            setTextIsSelectable(true)
            setPadding(dp(12), dp(8), dp(12), dp(8))
            setTextColor(if (mine) 0xFFFFFFFF.toInt() else resources.getColor(R.color.text, theme))
            background = GradientDrawable().apply {
                cornerRadius = dp(16).toFloat()
                setColor(if (mine) resources.getColor(R.color.launcher_bg, theme) else resources.getColor(R.color.surface, theme))
            }
            if (!mine) setTypeface(typeface, Typeface.NORMAL)
        }
        val lp = LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply {
            topMargin = dp(6)
            gravity = if (mine) Gravity.END else Gravity.START
            if (mine) leftMargin = dp(48) else rightMargin = dp(48)
        }
        feed.addView(tv, lp)
        scroll.post { scroll.fullScroll(ScrollView.FOCUS_DOWN) }
        return tv
    }

    private fun trim() {
        // Halve the thread at once when over the limit, so the request prefix stays stable for several turns.
        if (thread.size > MAX_HISTORY) {
            val keep = thread.takeLast(MAX_HISTORY / 2).dropWhile { !it.me }
            thread.clear(); thread.addAll(keep)
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val MAX_HISTORY = 20

        /** In-memory thread, kept across screen rotations, gone when the process ends. */
        private val thread = mutableListOf<Line>()
    }
}
