package fr.j3anclaud3.compagnon

import android.annotation.SuppressLint
import android.app.Activity
import android.net.Uri
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.content.Intent

/** The J3anClaud3 chat itself: the server's web app, already signed in with the app's session. */
class ChatActivity : Activity() {

    private lateinit var web: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs(this)
        val base = prefs.serverUrl
        val secure = base.startsWith("https://")
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setCookie(base, "j3s=${prefs.token}; Path=/" + if (secure) "; Secure" else "")
            flush()
        }
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val host = Uri.parse(base).host
                    if (request.url.host == host) return false
                    startActivity(Intent(Intent.ACTION_VIEW, request.url))  // external links open in the browser
                    return true
                }
            }
        }
        setContentView(web)
        if (savedInstanceState != null) web.restoreState(savedInstanceState) else web.loadUrl("$base/")
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    @Deprecated("Activity.onBackPressed is fine for a minSdk 26 plain Activity")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
