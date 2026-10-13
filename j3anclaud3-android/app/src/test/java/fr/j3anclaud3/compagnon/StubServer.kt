package fr.j3anclaud3.compagnon

import java.net.ServerSocket
import kotlin.concurrent.thread

/** Minimal HTTP/1.1 server (one request per connection), enough to stand in for J3anClaud3. */
class StubServer(
    private val statusFor: () -> Int = { 200 },
    private val handle: (path: String, headers: Map<String, String>, body: String) -> String,
) {
    private val socket = ServerSocket(0, 50, java.net.InetAddress.getByName("127.0.0.1"))
    val port: Int get() = socket.localPort

    init {
        thread(isDaemon = true) {
            while (!socket.isClosed) {
                val conn = runCatching { socket.accept() }.getOrNull() ?: break
                conn.use { c ->
                    val input = c.getInputStream().buffered()
                    fun line(): String {
                        val sb = StringBuilder()
                        while (true) {
                            val b = input.read()
                            if (b == -1 || b == '\n'.code) break
                            if (b != '\r'.code) sb.append(b.toChar())
                        }
                        return sb.toString()
                    }
                    val path = line().split(" ").getOrElse(1) { "/" }
                    val headers = HashMap<String, String>()
                    while (true) {
                        val h = line()
                        if (h.isEmpty()) break
                        val (k, v) = h.split(":", limit = 2).let { it[0].trim().lowercase() to it.getOrElse(1) { "" }.trim() }
                        headers[k] = v
                    }
                    val len = headers["content-length"]?.toIntOrNull() ?: 0
                    val body = ByteArray(len).also { var o = 0; while (o < len) { val r = input.read(it, o, len - o); if (r < 0) break; o += r } }
                    val out = handle(path, headers, body.toString(Charsets.UTF_8)).toByteArray(Charsets.UTF_8)
                    val code = statusFor()
                    c.getOutputStream().apply {
                        write("HTTP/1.1 $code ${if (code == 200) "OK" else "Error"}\r\nContent-Type: application/json\r\nContent-Length: ${out.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        write(out); flush()
                    }
                }
            }
        }
    }

    fun stop() = socket.close()
}
