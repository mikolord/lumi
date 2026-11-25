package club.netcraze.phototv

import okhttp3.Interceptor
import okhttp3.Response
import okhttp3.Protocol
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

internal data class ThumbnailPermit(val owner: String, val tag: String, val key: ByteArray)

/** Only ciphertext is persisted; the server supplies a key after checking current access. */
class ThumbnailCache(private val directory: File, private val maxBytes: Long = 256L * 1024 * 1024, private val maxEntries: Int = 20000) {
    private val lock = Any()
    @Volatile var epoch: Long = 0; private set
    private fun file(origin: String, id: Int, permit: ThumbnailPermit): File {
        val input = "$origin|${permit.owner}|$id|${permit.tag}".toByteArray()
        val name = MessageDigest.getInstance("SHA-256").digest(input).joinToString("") { "%02x".format(it) }
        return File(directory, "$name.enc")
    }
    internal fun read(origin: String, id: Int, permit: ThumbnailPermit): ByteArray? = synchronized(lock) {
        val file = file(origin, id, permit)
        if (!file.isFile) return@synchronized null
        try {
            val bytes = file.readBytes()
            require(bytes.size in 29..(512 * 1024))
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(permit.key, "AES"), GCMParameterSpec(128, bytes.copyOfRange(0,12)))
            cipher.updateAAD("${permit.owner}|$id|${permit.tag}".toByteArray())
            cipher.doFinal(bytes.copyOfRange(12,bytes.size)).also { file.setLastModified(System.currentTimeMillis()) }
        } catch (_: Exception) { file.delete(); null }
    }
    internal fun write(origin: String, id: Int, permit: ThumbnailPermit, data: ByteArray, expectedEpoch: Long) = synchronized(lock) {
        if (epoch != expectedEpoch || data.size > 400 * 1024) return@synchronized
        try {
            directory.mkdirs()
            val iv = ByteArray(12).also { SecureRandom().nextBytes(it) }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(permit.key, "AES"), GCMParameterSpec(128, iv))
            cipher.updateAAD("${permit.owner}|$id|${permit.tag}".toByteArray())
            val file = file(origin,id,permit)
            val temporary = File.createTempFile("thumb-", ".tmp", directory)
            try { temporary.writeBytes(iv + cipher.doFinal(data)); if (!temporary.renameTo(file)) temporary.delete() } finally { temporary.delete() }
            var total = directory.listFiles()?.sumOf { it.length() } ?: 0L
            val entries = directory.listFiles()?.sortedBy { it.lastModified() }.orEmpty()
            var count = entries.size
            for (entry in entries) { if(total <= maxBytes && count <= maxEntries) break; val size=entry.length();if(entry.delete()){total-=size;count--} }
        } catch (_: Exception) { /* A full disk must not prevent viewing an image. */ }
    }
    fun clear() = synchronized(lock) { epoch++;directory.listFiles()?.forEach { it.delete() };Unit }
    fun sizeBytes(): Long = synchronized(lock) { directory.listFiles()?.sumOf { it.length() } ?: 0L }
}

internal class ThumbnailInterceptor(
    private val cache: ThumbnailCache,
    private val origin: () -> String,
    private val sessionEpoch: () -> Long,
    private val verify: (Int) -> ThumbnailPermit,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request=chain.request();val server=origin()
        val match=Regex("^/media/(\\d+)/thumbnail$").matchEntire(request.url.encodedPath)
        if (request.method!="GET" || match==null || request.url.resolve("/")?.toString()?.trimEnd('/') != server) return chain.proceed(request)
        val id=match.groupValues[1].toInt();val generation=sessionEpoch();val cacheEpoch=cache.epoch
        val permit=verify(id)
        fun current() = sessionEpoch()==generation && origin()==server
        if(!current()) throw IOException("Сессия изменилась")
        val hit=cache.read(server,id,permit)
        if(hit!=null){if(!current())throw IOException("Сессия изменилась");return Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("OK").header("Cache-Control","no-store").body(hit.toResponseBody("image/jpeg".toMediaType())).build()}
        val response=chain.proceed(request)
        if(!response.isSuccessful)return response
        val bytes=response.use { val body=it.body?:throw IOException("Пустая миниатюра");body.source().request(400L*1024+1);if(body.source().buffer.size>400L*1024)throw IOException("Слишком большая миниатюра");body.bytes() }
        // A concurrent edit, hide, removal or logout may invalidate the first verification.
        val fresh=verify(id)
        if(!current() || fresh.owner!=permit.owner || fresh.tag!=permit.tag)throw IOException("Фотография изменилась, обнови медиатеку")
        cache.write(server,id,permit,bytes,cacheEpoch)
        if(!current())throw IOException("Сессия изменилась")
        return response.newBuilder().header("Cache-Control","no-store").removeHeader("Content-Length").removeHeader("Content-Encoding").body(bytes.toResponseBody("image/jpeg".toMediaType())).build()
    }
}
