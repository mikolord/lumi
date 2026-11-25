package club.netcraze.phototv

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Обновления напрямую из публичного GitHub.
 * APK проверяется по SHA-256, package ID, версии и подписи.
 * ТВ сравнивает versionCode со своим и при наличии новой версии скачивает и ставит её.
 */
object Updater {

    private const val PREFS = "photo_tv_updates"
    private const val DEFAULT_FEED = "https://raw.githubusercontent.com/mikolord/lumi/tv-updates"
    private const val LEGACY_NAS_FEED = "http://192.168.1.3:8100"
    private const val LEGACY_FEED = "http://192.168.1.10:8099"

    data class Info(val versionCode: Int, val versionName: String, val url: String, val notes: String, val sha256:String)

    fun feedBase(context: Context): String {
        val preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val stored = preferences.getString("feed", DEFAULT_FEED)?.trimEnd('/')
        return if (stored.isNullOrBlank() || stored == LEGACY_FEED || stored == LEGACY_NAS_FEED) DEFAULT_FEED else stored
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    /** Возвращает описание новой версии или null, если обновления нет/сервер недоступен. */
    fun check(context: Context): Info? {
        return try {
            val request = Request.Builder().url(feedBase(context) + "/tv/version.json").build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) throw IOException("Сервер обновлений ответил HTTP ${response.code}")
                val body = response.body?.string() ?: throw IOException("Пустой ответ сервера обновлений")
                val json = JSONObject(body)
                val code = json.optInt("versionCode", 0)
                val url = json.optString("url", "")
                if (code <= BuildConfig.VERSION_CODE || url.isEmpty()) return null
                Info(
                    versionCode = code,
                    versionName = json.optString("versionName", ""),
                    url = if (url.startsWith("http")) url else feedBase(context) + url,
                    notes = json.optString("notes", ""),
                    sha256 = json.optString("sha256", ""),
                )
            }
        } catch (error: Exception) {
            throw IOException("Не удалось проверить обновления",error)
        }
    }

    /** Скачивает APK в кеш, вызывая onProgress с процентами 0..100. */
    @Throws(IOException::class)
    fun download(context: Context, info: Info, onProgress: (Int) -> Unit): File {
        return UpdateDownload.fetch(client, context.cacheDir, info.url, info.versionCode, info.sha256, onProgress) { file ->
            validateArchive(context, info, file)
        }
    }

    @Suppress("DEPRECATION")
    private fun validateArchive(context: Context, info: Info, file: File) {
        val manager = context.packageManager
        // Read both forms: some TV firmware exposes only the legacy signatures array.
        val flags = android.content.pm.PackageManager.GET_SIGNATURES or
            (if (android.os.Build.VERSION.SDK_INT >= 28) android.content.pm.PackageManager.GET_SIGNING_CERTIFICATES else 0)
        val installed = manager.getPackageInfo(context.packageName, flags)
        val archive = manager.getPackageArchiveInfo(file.absolutePath, flags)
            ?: throw UpdateFailure("Телевизор не смог прочитать APK обновления")
        if (archive.packageName != context.packageName)
            throw UpdateFailure("APK предназначен для другого приложения")
        val code = if (android.os.Build.VERSION.SDK_INT >= 28) archive.longVersionCode else archive.versionCode.toLong()
        if (code != info.versionCode.toLong())
            throw UpdateFailure("Версия APK не совпадает с описанием обновления")
        fun signatures(value: android.content.pm.PackageInfo): Set<String> {
            val modern = if (android.os.Build.VERSION.SDK_INT >= 28) value.signingInfo?.apkContentsSigners.orEmpty() else emptyArray()
            val certs = modern.ifEmpty { value.signatures.orEmpty() }
            return certs.map { UpdateDownload.hash(it.toByteArray()) }.toSet()
        }
        val current = signatures(installed)
        val incoming = signatures(archive)
        if (current.isEmpty() || incoming.isEmpty())
            throw UpdateFailure("Телевизор не смог проверить подпись обновления")
        if (current != incoming)
            throw UpdateFailure("Подпись обновления отличается от установленной версии")
    }
}
