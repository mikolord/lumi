package club.netcraze.phototv

import android.content.Context
import android.net.ConnectivityManager
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.Inet4Address
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Поиск сервера фотографий в локальной сети: сканирует свою подсеть /24 по порту 8098
 * и отклик /api/account/status. Сервер сам себя не анонсирует (mDNS нет), поэтому — короткий опрос.
 */
object Discovery {

    private fun localAddress(context: Context): String? {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = manager.activeNetwork ?: return null
        val properties = manager.getLinkProperties(network) ?: return null
        for (linkAddress in properties.linkAddresses) {
            val address = linkAddress.address
            if (address is Inet4Address && !address.isLoopbackAddress) return address.hostAddress
        }
        return null
    }

    /**
     * Запускает сканирование. onResult и onDone вызываются в фоновых потоках —
     * вызывающая сторона сама переключается на UI-поток.
     * Возвращает функцию отмены.
     */
    fun scan(
        context: Context,
        port: Int = 8098,
        onResult: (String) -> Unit,
        onDone: (Int) -> Unit,
    ): () -> Unit {
        val own = localAddress(context)
        if (own == null) {
            Thread { onDone(0) }.start()
            return {}
        }
        val prefix = own.substringBeforeLast('.')
        val cancelled = AtomicBoolean(false)
        val executor = Executors.newFixedThreadPool(48)
        val found = AtomicInteger(0)
        val probe = OkHttpClient.Builder()
            .connectTimeout(600, TimeUnit.MILLISECONDS)
            .readTimeout(600, TimeUnit.MILLISECONDS)
            .build()
        for (i in 1..254) {
            val host = "$prefix.$i"
            if (host == own) continue
            executor.execute {
                if (cancelled.get()) return@execute
                try {
                    val request = Request.Builder()
                        .url("http://$host:$port/api/account/status")
                        .build()
                    probe.newCall(request).execute().use { response ->
                        val body = response.body?.string() ?: ""
                        if (response.isSuccessful && body.contains("\"configured\"")) {
                            found.incrementAndGet()
                            if (!cancelled.get()) onResult("http://$host:$port")
                        }
                    }
                } catch (_: Exception) {
                }
            }
        }
        executor.shutdown()
        Thread {
            try {
                executor.awaitTermination(15, TimeUnit.SECONDS)
            } catch (_: InterruptedException) {
            }
            if (!cancelled.get()) onDone(found.get())
        }.start()
        return {
            cancelled.set(true)
            executor.shutdownNow()
        }
    }
}
