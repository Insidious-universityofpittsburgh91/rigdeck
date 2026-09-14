package com.rigdeck.panel

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import java.util.concurrent.Executors

/**
 * The panel, full screen, with nothing of the browser showing.
 *
 * This exists because Chrome will only install a page as a real full-screen app from a
 * secure origin, and the server is plain HTTP on the local network. A WebView has no such
 * rule -- and it also lets the screen stay awake and the orientation stay put, which a
 * tab could not do either.
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private lateinit var setup: View
    private lateinit var address: EditText
    private lateinit var status: TextView
    private lateinit var scanButton: Button

    private val ui = Handler(Looper.getMainLooper())
    private val work = Executors.newSingleThreadExecutor()
    private var retry: Runnable? = null
    private var lastBack = 0L

    private val prefs by lazy { getSharedPreferences("rigdeck", Context.MODE_PRIVATE) }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(R.layout.main)

        // A dashboard that blanks out mid-corner is worse than no dashboard.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        immersive()

        web = findViewById(R.id.web)
        setup = findViewById(R.id.setup)
        address = findViewById(R.id.address)
        status = findViewById(R.id.status)
        scanButton = findViewById(R.id.scan)

        configureWeb()

        findViewById<Button>(R.id.connect).setOnClickListener {
            val url = Discovery.normalise(address.text.toString())
            if (url.isEmpty()) startScan() else open(url)
        }
        scanButton.setOnClickListener { startScan() }

        val saved = prefs.getString("url", null)
        address.setText(saved?.removePrefix("http://")?.removeSuffix("/") ?: "")
        if (saved != null) open(saved) else startScan()
    }

    /* ── the web view ──────────────────────────────────────────────────────── */

    @SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
    private fun configureWeb() {
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            // The panel is a fixed 1600px layout scaled to the screen, so the system font
            // size must not get a say -- it would push the dials out of their boxes.
            textZoom = 100
            useWideViewPort = true
            loadWithOverviewMode = false
            builtInZoomControls = false
            displayZoomControls = false
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
        }
        web.setBackgroundColor(0xFF100E0B.toInt())
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.isVerticalScrollBarEnabled = false
        web.isHorizontalScrollBarEnabled = false
        // No text-selection handles popping up when a glove brushes a label.
        web.setOnLongClickListener { true }
        web.isLongClickable = false

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                return false   // everything the panel links to is the panel
            }

            override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
                if (req.isForMainFrame) trouble(err.description?.toString() ?: "")
            }

            override fun onPageFinished(view: WebView, url: String) {
                if (url.startsWith("http")) {
                    cancelRetry()
                    setup.visibility = View.GONE
                    immersive()
                }
            }
        }
    }

    private fun open(url: String) {
        prefs.edit().putString("url", url).apply()
        hideKeyboard()
        status.text = ""
        web.loadUrl(url)
    }

    /** The panel is unreachable: say so, keep the address in reach, and keep trying. */
    private fun trouble(detail: String) {
        setup.visibility = View.VISIBLE
        findViewById<TextView>(R.id.title).setText(R.string.offline_title)
        status.text = detail
        if (retry == null) {
            retry = object : Runnable {
                override fun run() {
                    val url = prefs.getString("url", null)
                    if (url != null && setup.visibility == View.VISIBLE) web.loadUrl(url)
                    ui.postDelayed(this, 5000)
                }
            }.also { ui.postDelayed(it, 5000) }
        }
    }

    private fun cancelRetry() {
        retry?.let { ui.removeCallbacks(it) }
        retry = null
    }

    /* ── finding the PC ────────────────────────────────────────────────────── */

    private fun startScan() {
        cancelRetry()
        setup.visibility = View.VISIBLE
        scanButton.isEnabled = false
        status.setText(R.string.scanning)
        val port = portFromField()
        work.execute {
            val found = Discovery.scan(port)
            ui.post {
                scanButton.isEnabled = true
                if (found == null) {
                    status.setText(R.string.not_found)
                } else {
                    address.setText(found)
                    open(Discovery.normalise(found))
                }
            }
        }
    }

    private fun portFromField(): Int {
        val text = address.text.toString().substringAfterLast(':', "")
        return text.toIntOrNull() ?: Discovery.DEFAULT_PORT
    }

    /* ── system chrome ─────────────────────────────────────────────────────── */

    @Suppress("DEPRECATION")
    private fun immersive() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            window.insetsController?.let {
                it.hide(WindowInsets.Type.systemBars())
                it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) immersive()
    }

    private fun hideKeyboard() {
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(address.windowToken, 0)
    }

    /**
     * There is nowhere to go back to -- the panel is one screen by design. A single press
     * is swallowed so a stray thumb never drops the driver onto the launcher; two presses
     * inside two seconds bring the address back up.
     */
    @Deprecated("replaced by predictive back, which this app does not opt into")
    override fun onBackPressed() {
        val now = System.currentTimeMillis()
        if (now - lastBack < 2000) {
            findViewById<TextView>(R.id.title).setText(R.string.setup_title)
            status.text = ""
            setup.visibility = View.VISIBLE
        }
        lastBack = now
    }

    override fun onDestroy() {
        cancelRetry()
        work.shutdownNow()
        super.onDestroy()
    }
}
