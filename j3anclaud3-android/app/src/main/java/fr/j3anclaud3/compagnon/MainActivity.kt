package fr.j3anclaud3.compagnon

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.core.app.NotificationManagerCompat

/**
 * Settings and control panel: server connection, Android permissions, reply mode,
 * per-app opt-in, and the entry points to the chat and the message digest.
 */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var root: LinearLayout
    private lateinit var accessStatus: TextView
    private lateinit var notifStatus: TextView
    private lateinit var connectStatus: TextView
    private lateinit var appsBox: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        Notifier.createChannels(this)
        title = getString(R.string.app_name)
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(12), dp(16), dp(32))
        }
        setContentView(ScrollView(this).apply { addView(root) })
        build()
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
        refreshApps()
    }

    // ------------------------------------------------------------------ layout
    private fun build() {
        text("Votre assistant IA, partout où vous recevez des messages.", 15f, muted = true)

        if (!prefs.privacyAccepted) {
            val box = card()
            box.addView(label("🔒 Confidentialité", bold = true))
            box.addView(label(
                "J3anClaud3 ne lit que les notifications des applications que vous cochez ci-dessous. " +
                    "Pour rédiger une réponse ou un résumé, les derniers messages de la conversation concernée " +
                    "(12 au plus) sont envoyés à VOTRE serveur J3anClaud3, qui interroge l'IA. " +
                    "Rien n'est enregistré sur le téléphone ; les codes de vérification et messages de sécurité " +
                    "ne quittent jamais l'appareil. Prévenez vos contacts si l'assistant répond pour vous.",
                muted = true,
            ))
            box.addView(button("J'ai compris") { prefs.privacyAccepted = true; recreate() })
            return
        }

        // --- server
        section("Serveur J3anClaud3")
        val url = field("Adresse du serveur", prefs.serverUrl, InputType.TYPE_TEXT_VARIATION_URI, "https://j3anclaud3.mon-domaine.fr")
        val name = field("Votre prénom", prefs.name, InputType.TYPE_TEXT_VARIATION_PERSON_NAME)
        val password = field("Mot de passe (compte administrateur uniquement)", "", InputType.TYPE_TEXT_VARIATION_PASSWORD)
        connectStatus = label("", muted = true)
        root.addView(button("Se connecter") { connect(url.text.toString(), name.text.toString(), password.text.toString()) })
        root.addView(connectStatus)

        // --- permissions
        section("Autorisations")
        accessStatus = label("")
        root.addView(accessStatus)
        root.addView(button("Accès aux notifications…") {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        })
        notifStatus = label("")
        root.addView(notifStatus)
        if (Build.VERSION.SDK_INT >= 33) {
            root.addView(button("Autoriser les suggestions à s'afficher") {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
            })
        }

        // --- mode
        section("Quand un message arrive")
        val modes = RadioGroup(this)
        val options = listOf(
            ReplyMode.SUGGEST to "Suggérer une réponse — vous choisissez Envoyer, Modifier ou Ignorer (recommandé)",
            ReplyMode.AUTO to "Répondre automatiquement — avec une limite par conversation, sinon suggestion",
            ReplyMode.OFF to "Ne rien faire — seulement le résumé à la demande",
        )
        options.forEachIndexed { i, (mode, text) ->
            modes.addView(RadioButton(this).apply {
                id = View.generateViewId()
                this.text = text
                isChecked = prefs.mode == mode
                setPadding(dp(4), dp(6), 0, dp(6))
                setOnClickListener {
                    if (mode == ReplyMode.AUTO) confirmAuto { prefs.mode = mode } else prefs.mode = mode
                }
            })
        }
        root.addView(modes)

        // --- options
        section("Réglages des réponses")
        root.addView(check("Répondre aussi dans les conversations de groupe", prefs.replyInGroups) { prefs.replyInGroups = it })
        root.addView(check("Signaler les réponses automatiques (« rédigée par mon assistant »)", prefs.signAutoReplies) {
            prefs.signAutoReplies = it
        })
        val cooldown = field("Délai minimum entre deux réponses automatiques (minutes)", prefs.autoCooldownMinutes.toString(), InputType.TYPE_CLASS_NUMBER)
        val style = field("Consignes de style", prefs.style, InputType.TYPE_TEXT_FLAG_MULTI_LINE, "ex. « tutoie mes amis, reste bref, pas d'emoji »")
        root.addView(button("Enregistrer les réglages") {
            prefs.style = style.text.toString()
            cooldown.text.toString().toIntOrNull()?.let { prefs.autoCooldownMinutes = it }
            toast("Réglages enregistrés")
        })

        // --- apps
        section("Applications surveillées")
        text("Seules les applications cochées sont lues. Les autres apparaissent ici dès qu'elles affichent un message.", 13f, muted = true)
        appsBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(appsBox)

        // --- actions
        section("J3anClaud3")
        root.addView(button("💬 Discuter avec J3anClaud3") {
            if (!prefs.isConnected) toast("Connectez-vous d'abord au serveur") else startActivity(Intent(this, ChatActivity::class.java))
        })
        root.addView(button("📋 Résumé de mes messages") { digest() })
        root.addView(button("🧹 Oublier les messages lus") { Store.clearCaptured(); toast("Messages oubliés") })
    }

    // ------------------------------------------------------------------ actions
    private fun connect(url: String, name: String, password: String) {
        val base = url.trim().trimEnd('/')
        if (!base.startsWith("http://") && !base.startsWith("https://")) {
            connectStatus.text = "L'adresse doit commencer par https:// (ou http:// sur votre réseau local)."
            return
        }
        connectStatus.text = "Connexion…"
        Thread {
            val result = runCatching { Api(base).login(name, password) }
            runOnUiThread {
                result.onSuccess {
                    prefs.serverUrl = base; prefs.name = it.user; prefs.token = it.token
                    connectStatus.text = "✅ Connecté en tant que ${it.user}" + (if (it.admin) " (administrateur)" else "") +
                        (if (base.startsWith("http://")) "\n⚠️ Connexion non chiffrée : à réserver à votre réseau local." else "")
                }.onFailure { connectStatus.text = "❌ ${it.message}" }
            }
        }.start()
    }

    private fun digest() {
        if (!prefs.isConnected) return toast("Connectez-vous d'abord au serveur")
        val items = Store.capturedSnapshot().filterNot { Messages.isSensitive(it.text) }
        if (items.isEmpty()) return toast("Aucun message reçu depuis le démarrage de J3anClaud3")
        toast("Résumé en cours…")
        Thread {
            val result = runCatching { Api(prefs.serverUrl, prefs.token).digest(items) }
            runOnUiThread {
                AlertDialog.Builder(this)
                    .setTitle("Résumé de vos messages")
                    .setMessage(result.getOrElse { "Impossible d'obtenir le résumé : ${it.message}" })
                    .setPositiveButton("OK", null)
                    .show()
            }
        }.start()
    }

    private fun confirmAuto(onYes: () -> Unit) {
        AlertDialog.Builder(this)
            .setTitle("Réponses automatiques")
            .setMessage(
                "J3anClaud3 enverra des messages en votre nom, sans vous demander, dans les applications cochées. " +
                    "Il s'abstient sur les codes, la banque, les sujets sensibles et les messages automatiques, " +
                    "limite le rythme (${prefs.autoCooldownMinutes} min par conversation, 20 par heure) et " +
                    "vous montre chaque envoi. Vous restez responsable de ce qui est envoyé.",
            )
            .setPositiveButton("Activer") { _, _ -> onYes() }
            .setNegativeButton("Annuler") { _, _ -> recreate() }
            .show()
    }

    private fun refreshStatus() {
        if (!::accessStatus.isInitialized) return
        val access = NotificationManagerCompat.getEnabledListenerPackages(this).contains(packageName)
        accessStatus.text = if (access) "✅ Accès aux notifications accordé" else "⚠️ Accès aux notifications à accorder (Réglages › J3anClaud3)"
        val canPost = Build.VERSION.SDK_INT < 33 ||
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        notifStatus.text = if (canPost) "✅ Les suggestions peuvent s'afficher" else "⚠️ Autorisez l'affichage des suggestions"
        if (prefs.isConnected && connectStatus.text.isEmpty()) connectStatus.text = "✅ Connecté en tant que ${prefs.name}"
    }

    private fun refreshApps() {
        if (!::appsBox.isInitialized) return
        appsBox.removeAllViews()
        val pkgs = (Messages.KNOWN_APPS.filter { Messages.isInstalled(this, it) } + prefs.seenPackages + prefs.enabledPackages)
            .distinct()
            .sortedBy { Messages.appLabel(this, it).lowercase() }
        if (pkgs.isEmpty()) appsBox.addView(label("Aucune application de messagerie détectée pour l'instant.", muted = true))
        for (pkg in pkgs) {
            appsBox.addView(check(Messages.appLabel(this, pkg), pkg in prefs.enabledPackages) { on ->
                prefs.enabledPackages = if (on) prefs.enabledPackages + pkg else prefs.enabledPackages - pkg
            })
        }
    }

    // ------------------------------------------------------------------ view helpers
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun color(id: Int) = resources.getColor(id, theme)

    private fun label(s: String, bold: Boolean = false, muted: Boolean = false, size: Float = 14f) = TextView(this).apply {
        text = s
        textSize = size
        setTextColor(color(if (muted) R.color.muted else R.color.text))
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(4), 0, dp(4))
    }

    private fun text(s: String, size: Float, muted: Boolean = false) = root.addView(label(s, muted = muted, size = size))

    private fun section(title: String) = root.addView(label(title, bold = true, size = 17f).apply { setPadding(0, dp(22), 0, dp(6)) })

    private fun card(): LinearLayout {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(12), dp(14), dp(12))
            background = GradientDrawable().apply { setColor(color(R.color.surface)); cornerRadius = dp(14).toFloat() }
        }
        root.addView(box, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(16) })
        return box
    }

    private fun field(title: String, value: String, type: Int, example: String = ""): EditText {
        val e = EditText(this).apply {
            hint = example
            setText(value)
            inputType = if (type == InputType.TYPE_CLASS_NUMBER) type else InputType.TYPE_CLASS_TEXT or type
            typeface = Typeface.DEFAULT  // password fields would otherwise switch to monospace
            textSize = 15f
        }
        root.addView(label(title, muted = true, size = 12f))
        root.addView(e, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        return e
    }

    private fun button(s: String, onClick: () -> Unit) = Button(this).apply {
        text = s
        isAllCaps = false
        gravity = Gravity.CENTER
        setOnClickListener { onClick() }
    }

    private fun check(s: String, value: Boolean, onChange: (Boolean) -> Unit) = CheckBox(this).apply {
        text = s
        isChecked = value
        setTextColor(color(R.color.text))
        setPadding(dp(4), dp(6), 0, dp(6))
        setOnCheckedChangeListener { _, on -> onChange(on) }
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
