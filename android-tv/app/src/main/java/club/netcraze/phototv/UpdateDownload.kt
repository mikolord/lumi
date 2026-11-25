package club.netcraze.phototv

import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** Safe text for the TV. Transport exception messages may contain server URLs. */
class UpdateFailure(message: String, cause: Throwable? = null) : IOException(message, cause)

object UpdateDownload {
    fun hash(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }

    fun fetch(client: OkHttpClient, cache: File, url: String, code: Int, expectedHash: String,
              onProgress: (Int) -> Unit, validate: (File) -> Unit): File {
        if (!Regex("[0-9a-fA-F]{64}").matches(expectedHash))
            throw UpdateFailure("В описании обновления отсутствует контрольная сумма")
        val directory = File(cache, "apk")
        if (!directory.isDirectory && !directory.mkdirs())
            throw UpdateFailure("Не удалось создать папку для обновления")
        val partial = File(directory, "rc-foto-$code.apk.part")
        val ready = File(directory, "rc-foto-$code.apk")
        try {
            client.newBuilder().readTimeout(2, TimeUnit.MINUTES).build()
                .newCall(Request.Builder().url(url).build()).execute().use { response ->
                    if (!response.isSuccessful) throw UpdateFailure("Сервер обновлений: HTTP ${response.code}")
                    val body = response.body ?: throw UpdateFailure("Сервер прислал пустой файл")
                    val total = body.contentLength()
                    if (total > 0 && directory.usableSpace < total + 2L * 1024 * 1024)
                        throw UpdateFailure("На телевизоре недостаточно места для обновления")
                    val digest = MessageDigest.getInstance("SHA-256")
                    var received = 0L
                    var last = -1
                    body.byteStream().use { input -> partial.outputStream().use { output ->
                        val buffer = ByteArray(65536)
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            output.write(buffer, 0, n)
                            digest.update(buffer, 0, n)
                            received += n
                            if (total > 0) {
                                val percent = (received * 100 / total).toInt().coerceIn(0, 99)
                                if (percent != last) { last = percent; onProgress(percent) }
                            }
                        }
                    } }
                    if (received == 0L || (total >= 0 && received != total))
                        throw UpdateFailure("APK загрузился не полностью. Повтори загрузку")
                    val actual = digest.digest().joinToString("") { "%02x".format(it) }
                    if (!actual.equals(expectedHash, true))
                        throw UpdateFailure("Контрольная сумма APK не совпала. Повтори загрузку")
                }
            // PackageManager must receive an APK filename, never the transport .part file.
            if (ready.exists() && !ready.delete()) throw UpdateFailure("Не удалось заменить старый APK")
            if (!partial.renameTo(ready)) throw UpdateFailure("Не удалось подготовить APK к проверке")
            validate(ready)
            onProgress(100)
            return ready
        } catch (error: Exception) {
            partial.delete()
            ready.delete()
            if (error is UpdateFailure) throw error
            throw UpdateFailure("Загрузка или проверка APK прервалась. Проверь сеть и свободное место", error)
        }
    }
}
