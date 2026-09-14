package com.rigdeck.panel

import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Finds the panel on the local network so nobody has to read an IP address off a screen
 * and type it into a tablet with cold hands.
 *
 * Every host on each of the tablet's own /24 networks is asked for /api/status. The
 * server answers that in well under a millisecond, so the whole sweep is over in a couple
 * of seconds even though it is 254 requests per subnet.
 */
object Discovery {

    const val DEFAULT_PORT = 8384

    private const val CONNECT_MS = 400
    private const val READ_MS = 700
    private const val THREADS = 64

    /** True if a Rig Deck server -- and not some other web server -- answers here. */
    fun probe(host: String, port: Int): Boolean {
        return try {
            val conn = URL("http://$host:$port/api/status").openConnection() as HttpURLConnection
            conn.connectTimeout = CONNECT_MS
            conn.readTimeout = READ_MS
            conn.useCaches = false
            try {
                if (conn.responseCode != 200) return false
                val body = conn.inputStream.bufferedReader().use { it.readText() }
                body.contains("\"vjoy\"") && body.contains("\"addresses\"")
            } finally {
                conn.disconnect()
            }
        } catch (_: Exception) {
            false
        }
    }

    /** The /24 prefixes the tablet itself sits on, e.g. "192.168.0". */
    private fun prefixes(): List<String> {
        val out = mutableListOf<String>()
        for (nif in NetworkInterface.getNetworkInterfaces()) {
            if (!nif.isUp || nif.isLoopback) continue
            for (addr in nif.inetAddresses) {
                val ip = addr as? Inet4Address ?: continue
                if (ip.isLoopbackAddress) continue
                out += ip.hostAddress!!.substringBeforeLast('.')
            }
        }
        return out.distinct()
    }

    /**
     * Sweeps every local subnet and returns the first server that answers, or null.
     * Blocking -- call it off the main thread.
     */
    fun scan(port: Int): String? {
        val pool = Executors.newFixedThreadPool(THREADS)
        try {
            for (prefix in prefixes()) {
                val hits = pool.invokeAll((1..254).map { last ->
                    java.util.concurrent.Callable {
                        val host = "$prefix.$last"
                        if (probe(host, port)) host else null
                    }
                }, 25, TimeUnit.SECONDS)
                for (hit in hits) {
                    val host = try { hit.get() } catch (_: Exception) { null }
                    if (host != null) return "$host:$port"
                }
            }
            return null
        } finally {
            pool.shutdownNow()
        }
    }

    /** Accepts "192.168.0.56", "192.168.0.56:8384" or a full URL, and returns a URL. */
    fun normalise(raw: String): String {
        var text = raw.trim().removeSuffix("/")
        if (text.isEmpty()) return ""
        text = text.removePrefix("http://").removePrefix("https://")
        if (!text.contains(':')) text = "$text:$DEFAULT_PORT"
        return "http://$text/"
    }
}
