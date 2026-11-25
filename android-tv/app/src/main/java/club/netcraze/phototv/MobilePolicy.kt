package club.netcraze.phototv

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.security.MessageDigest

enum class LumiDevice { PHONE, TABLET, TV }
object MobilePolicy {
    fun device(television: Boolean, smallestWidth: Int) = if (television) LumiDevice.TV else if (smallestWidth >= 600) LumiDevice.TABLET else LumiDevice.PHONE
    fun origin(input: String): String {
        val text = input.trim().let {
            if (it.startsWith("https://") || it.startsWith("http://")) it else {
                val host=("http://"+it).toHttpUrlOrNull()?.host.orEmpty()
                val privateHost=host=="localhost"||host=="::1"||host.endsWith(".local")||host.startsWith("192.168.")||host.startsWith("10.")||host.startsWith("127.")||host.startsWith("169.254.")||(host.startsWith("172.")&&(host.split('.').getOrNull(1)?.toIntOrNull()?:0) in 16..31)
                (if(privateHost)"http://"else "https://")+it
            }
        }
        val url = text.toHttpUrlOrNull() ?: throw IllegalArgumentException("Проверь адрес сервера")
        require(url.username.isEmpty() && url.password.isEmpty() && url.encodedPath == "/" && url.query == null && url.fragment == null) { "Нужен адрес сервера без пути, логина и пароля" }
        return url.toString().trimEnd('/')
    }
    fun sameOrigin(origin: String, target: String): Boolean {
        val a = origin.toHttpUrlOrNull() ?: return false
        val b = target.toHttpUrlOrNull() ?: return false
        return a.scheme == b.scheme && a.host == b.host && a.port == b.port && b.username.isEmpty() && b.password.isEmpty()
    }
    fun cookies(header: String): Map<String, String> = header.split(';').mapNotNull {
        val parts = it.trim().split('=', limit=2)
        if (parts.size == 2 && parts[0] in setOf("photo_account", "photo_csrf") && !parts[1].contains('\r') && !parts[1].contains('\n')) parts[0] to parts[1] else null
    }.toMap()
    fun cookieHeader(header: String) = cookies(header).entries.joinToString("; ") { "${it.key}=${it.value}" }
    fun fingerprint(origin: String, header: String): String {
        val token = cookies(header)["photo_account"].orEmpty()
        if (token.isEmpty()) return ""
        return MessageDigest.getInstance("SHA-256").digest("$origin|$token".toByteArray()).joinToString("") { "%02x".format(it) }
    }
}
