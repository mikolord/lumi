package club.netcraze.phototv

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

internal data class MobileAccount(val origin: String, val cookie: String, val owner: String, val name: String) {
    val queueKey: String get() = UpdateDownload.hash("$origin|owner:$owner".toByteArray())
    val fingerprint: String get() = MobilePolicy.fingerprint(origin, cookie)
}
internal class MobileAccountStore(context: Context) {
    companion object { @Volatile private var memory: MobileAccount? = null }
    private val prefs = context.getSharedPreferences("lumi_mobile", Context.MODE_PRIVATE)
    private val secrets = SecretStore(context, "mobile")
    @Synchronized fun read(): MobileAccount? {
        memory?.takeIf { current(it.fingerprint) }?.let { return it }
        return try {
        val value = JSONObject(secrets.read() ?: "{}")
        MobileAccount(value.getString("origin"), value.getString("cookie"), value.getString("owner"), value.optString("name"))
            .takeIf { it.fingerprint.isNotEmpty() && current(it.fingerprint) }
            .also { memory = it }
    } catch (_: Exception) { null }
    }
    @Synchronized fun write(account: MobileAccount) {
        require(account.fingerprint.isNotEmpty())
        secrets.write(JSONObject().put("origin", account.origin).put("cookie", MobilePolicy.cookieHeader(account.cookie)).put("owner", account.owner).put("name", account.name).toString())
        prefs.edit().putString("auth", account.fingerprint).commit()
        memory=account
    }
    fun current(fingerprint: String) = fingerprint.isNotEmpty() && prefs.getString("auth", "") == fingerprint
    @Synchronized fun clear() { prefs.edit().remove("auth").putBoolean("auto", false).commit(); secrets.clear(); memory=null }
}
internal object MobileApi {
    val client: OkHttpClient = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()
    fun get(account: MobileAccount, path: String): JSONObject {
        require(path.startsWith('/') && !path.startsWith("//"))
        val request = Request.Builder().url(account.origin + path).header("Cookie", MobilePolicy.cookieHeader(account.cookie)).header("X-Photo-App-Origin", account.origin).build()
        client.newCall(request).execute().use { response ->
            val json = try { JSONObject(response.body?.string().orEmpty()) } catch (_: Exception) { throw IOException("Сервер вернул некорректный ответ") }
            if (!response.isSuccessful) throw ApiException(response.code, json.optString("error", "Не удалось подключиться"))
            return json
        }
    }
}
