package fr.j3anclaud3.compagnon

import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import androidx.test.core.app.ApplicationProvider
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/** Renders the settings screen to PNG (opt-in: -Dj3.screenshots=<dir>) for a visual check without a device. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w411dp-h891dp-xxhdpi")
class ScreenshotTest {
    @Test
    fun settingsScreen() = render("android-settings-${BuildConfig.FLAVOR}-server.png") {
        Prefs(ApplicationProvider.getApplicationContext()).apply {
            privacyAccepted = true
            serverUrl = "https://j3anclaud3.exemple.fr"; name = "guillaume"; token = "t"
            enabledPackages = setOf("com.whatsapp"); seenPackages = setOf("com.whatsapp", "org.telegram.messenger")
        }
    }

    @Test
    fun serverlessSettingsScreen() = render("android-settings-${BuildConfig.FLAVOR}-direct.png") {
        Prefs(ApplicationProvider.getApplicationContext()).apply {
            privacyAccepted = true
            backend = Backend.DIRECT
            provider = Flavor.defaultProvider
            seenPackages = setOf("com.whatsapp")
        }
    }

    private fun render(name: String, setup: () -> Unit) {
        val dir = System.getProperty("j3.screenshots")
        assumeTrue(dir != null)
        setup()
        val activity = Robolectric.buildActivity(MainActivity::class.java).setup().get()
        val root = activity.window.decorView
        val w = 1233
        root.measure(View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        val scroll = (activity.findViewById<View>(android.R.id.content) as android.view.ViewGroup).getChildAt(0)
        scroll.measure(View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        val content = (scroll as android.view.ViewGroup).getChildAt(0)
        content.measure(View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        content.layout(0, 0, content.measuredWidth, content.measuredHeight)
        val bmp = Bitmap.createBitmap(content.measuredWidth, content.measuredHeight, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        canvas.drawColor(activity.resources.getColor(R.color.bg, activity.theme))
        content.draw(canvas)
        File(dir!!).mkdirs()
        File(dir, name).outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }
}
