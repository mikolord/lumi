package club.netcraze.phototv

import android.content.Context
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val statusCode: Int, message: String, val code: String? = null) : IOException(message)

class UnauthorizedException(message: String) : IOException(message)

/**
 * Сессия с сервером фотографий: base URL, cookie-аутентификация и CSRF-подпись POST-запросов.
 * Сервер (photo-design, server.py) выдаёт cookie photo_account на 30 дней и CSRF-токен,
 * привязанный к этой cookie; каждый POST требует заголовок X-Photo-CSRF, равный cookie photo_csrf.
 */
class Session(context: Context) {

    private val prefs = context.getSharedPreferences("photo_tv_session", Context.MODE_PRIVATE)

    var baseUrl: String = prefs.getString("baseUrl", "") ?: ""
        private set
    var accountName: String = prefs.getString("accountName", "") ?: ""
        private set
    private var savedLogin: String = prefs.getString("login", "") ?: ""
    private var savedPassword: String = ""
    @Volatile private var csrf: String = ""
    private val generation=java.util.concurrent.atomic.AtomicLong()
    private val requestEpoch=ThreadLocal<Long>()
    val thumbnails=ThumbnailCache(java.io.File(context.cacheDir,"lumi-thumbnails-v1"))
    private val secrets=SecretStore(context)
    private fun originUrl()=baseUrl.toHttpUrlOrNull()
    private val cookieJar=OriginCookieJar(::originUrl, restoreCookies(), { cookies ->
        secrets.write(org.json.JSONArray(cookies.filter{it.name!="photo_vault"}.map{it.toString()}).toString())
    }, {requestEpoch.get()?.let{it==generation.get()}?:true})
    val accessGeneration:Long get()=generation.get()
    val prefillServer: String get() = baseUrl
    val prefillLogin: String get() = savedLogin
    @Volatile var vaultProtectionEnabled:Boolean=true;private set
    val vaultUnlocked: Boolean get()=!vaultProtectionEnabled||cookieJar.has("photo_vault")
    @Volatile var vaultGeneration: Long=0;private set

    init {
        // Upgrade old installations in place, then remove plaintext secrets and legacy Coil files.
        secrets.write(org.json.JSONArray(cookieJar.loadForRequest(originUrl()?:"http://localhost".toHttpUrl()).filter{it.name!="photo_vault"}.map{it.toString()}).toString())
        prefs.edit().remove("password").remove("vaultPin").remove("cookies").apply()
        java.io.File(context.cacheDir,"image_cache").takeIf{it.isDirectory}?.deleteRecursively()
    }
    private fun restoreCookies():List<Cookie>{
        val url=originUrl()?:return emptyList()
        val encrypted=secrets.read()
        if(encrypted!=null)return try{val array=org.json.JSONArray(encrypted);(0 until array.length()).mapNotNull{Cookie.parse(url,array.getString(it))}.filter{it.name!="photo_vault"}}catch(_:Exception){emptyList()}
        return try{
            val old=JSONObject(prefs.getString("cookies","{}")?:"{}")
            listOf("photo_account","photo_csrf").mapNotNull{name->old.optString(name,"").takeIf{it.isNotEmpty()}?.let{value->Cookie.Builder().name(name).value(value).hostOnlyDomain(url.host).path("/").expiresAt(System.currentTimeMillis()+30L*86400000).apply{if(url.isHttps)secure()}.build()}}
        }catch(_:Exception){emptyList()}
    }
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS).readTimeout(45, TimeUnit.SECONDS)
        .cookieJar(cookieJar)
        .addInterceptor { chain ->
            val previous=requestEpoch.get();requestEpoch.set(generation.get())
            try{chain.proceed(chain.request())}finally{if(previous==null)requestEpoch.remove()else requestEpoch.set(previous)}
        }
        .addInterceptor(ThumbnailInterceptor(thumbnails,{baseUrl},{generation.get()},::verifyThumbnail))
        .build()
    private fun verifyThumbnail(index:Int):ThumbnailPermit {
        val result=get("/api/thumbnails/verify?index=$index")
        return ThumbnailPermit(result.getString("owner"),result.getString("tag"),java.util.Base64.getDecoder().decode(result.getString("key")))
    }
    fun hasSession():Boolean=baseUrl.isNotEmpty()&&cookieJar.has("photo_account")
    fun configureServer(server:String){
        val text=server.trim().let{if(it.startsWith("http://")||it.startsWith("https://"))it else "http://$it"}
        val url=text.toHttpUrlOrNull()?:throw IllegalArgumentException("Неверный адрес сервера")
        require(url.username.isEmpty()&&url.password.isEmpty()&&url.encodedPath=="/"&&url.query==null&&url.fragment==null){"Укажи адрес сервера без пути и пароля"}
        val next=url.toString().trimEnd('/')
        if(next!=baseUrl){generation.incrementAndGet();cookieJar.clear();thumbnails.clear();savedPassword="";savedLogin="";accountName="";csrf="";vaultProtectionEnabled=true;vaultGeneration++;prefs.edit().remove("login").remove("accountName").apply()}
        baseUrl=next;prefs.edit().putString("baseUrl",baseUrl).apply()
    }
    fun configure(server:String,login:String,password:String){
        configureServer(server)
        if(savedLogin!=login.trim()){generation.incrementAndGet();cookieJar.clear();thumbnails.clear()}
        savedLogin=login.trim();savedPassword=password;prefs.edit().putString("login",savedLogin).apply()
    }
    fun saveAccountName(name:String){generation.incrementAndGet();accountName=name;prefs.edit().putString("accountName",name).apply()}
    fun clearSession(){generation.incrementAndGet();cookieJar.clear();thumbnails.clear();savedPassword="";accountName="";csrf="";vaultProtectionEnabled=true;vaultGeneration++;prefs.edit().remove("accountName").remove("password").remove("vaultPin").apply()}
    fun logout(){try{post("/api/account/logout",JSONObject())}finally{clearSession()}}
    fun lockVault(){cookieJar.removeVault();vaultGeneration++}
    fun cancelPairing(){for(call in client.dispatcher.runningCalls()+client.dispatcher.queuedCalls())if(call.request().url.encodedPath.startsWith("/api/tv/pair/"))call.cancel()}

    @Throws(IOException::class)
    fun fetchStatus(): JSONObject = get("/api/account/status")

    @Throws(IOException::class)
    fun login(): JSONObject {
        if(savedPassword.isEmpty())throw UnauthorizedException("Сессия истекла. Войди по QR или паролю заново.")
        generation.incrementAndGet()
        val result = try{post("/api/account/login",JSONObject().put("login",savedLogin).put("password",savedPassword))}finally{savedPassword=""}
        accountName = result.optString("name", savedLogin)
        prefs.edit().putString("accountName", accountName).apply()
        return result
    }

    @Throws(IOException::class)
    fun library(): JSONObject = get("/api/library")

    @Throws(IOException::class)
    fun people(): JSONObject = get("/api/people")

    /** Разблокировка скрытого раздела кодом-паролем; сервер ставит cookie photo_vault. */
    @Throws(IOException::class)
    fun unlockVault(pin: String): JSONObject {
        val result = post("/api/vault/unlock", JSONObject().put("pin", pin))
        return result
    }

    fun clearVaultPin() {
        lockVault()
    }

    // ---------- Вход по QR (пара устройства) ----------

    @Throws(IOException::class)
    fun pairStart(): JSONObject = post(
        "/api/tv/pair/start",
        JSONObject().put("device", "Android TV · " + (android.os.Build.MODEL ?: "TV")),
        appOrigin = true,
    )

    @Throws(IOException::class)
    fun pairPoll(id: String, secret: String): JSONObject = post(
        "/api/tv/pair/poll",
        JSONObject().put("id", id).put("secret", secret),
        appOrigin = true,
    )

    fun mediaUrl(path:String):String {
        val base=originUrl()?:throw IllegalStateException("Сервер не выбран")
        val url=base.resolve(path)?:throw IllegalArgumentException("Неверный адрес фотографии")
        require(url.scheme==base.scheme&&url.host==base.host&&url.port==base.port){"Фотография находится на другом сервере"}
        return url.toString()
    }

    @Throws(IOException::class)
    private fun get(path: String): JSONObject {
        val request = Request.Builder().url(baseUrl + path).get().build()
        return execute(request)
    }

    @Throws(IOException::class)
    private fun post(path: String, body: JSONObject, retryOnCsrf: Boolean = true, appOrigin: Boolean = false): JSONObject {
        val builder = Request.Builder().url(baseUrl + path)
            .header("X-Photo-CSRF", csrf)
        if (appOrigin) builder.header("X-Photo-App-Origin", baseUrl)
        val request = builder
            .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()
        return try {
            execute(request)
        } catch (error: ApiException) {
            if (retryOnCsrf && error.code == "csrf") {
                try {
                    fetchStatus()
                } catch (_: Exception) {
                }
                return post(path, body, retryOnCsrf = false, appOrigin = appOrigin)
            }
            throw error
        }
    }

    @Throws(IOException::class)
    private fun execute(request: Request): JSONObject {
        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            val json = try {
                JSONObject(text.ifEmpty { "{}" })
            } catch (error: Exception) {
                throw IOException("Некорректный ответ сервера (${response.code})")
            }
            json.optJSONObject("vault")?.let{vaultProtectionEnabled=it.optBoolean("protectionEnabled",true)}
            val freshCsrf = json.optString("csrf", "")
            if (freshCsrf.isNotEmpty()) csrf = freshCsrf
            if (response.code == 401) {
                throw UnauthorizedException(json.optString("error", "Требуется вход"))
            }
            if (!response.isSuccessful) {
                throw ApiException(
                    response.code,
                    json.optString("error", "Ошибка сервера (${response.code})"),
                    json.optString("code", "").takeIf{it.isNotEmpty()}
                )
            }
            return json
        }
    }
}
