package club.netcraze.phototv

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Cookie
import okio.BufferedSink
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/** Raw-file upload protocol shared with PWA; credentials never follow redirects. */
internal class MobileUploadTransport(client: OkHttpClient = MobileApi.client, private val phase:(String)->Unit = {}) {
    private val client = client.newBuilder().followRedirects(false).followSslRedirects(false).readTimeout(2,TimeUnit.MINUTES).writeTimeout(2,TimeUnit.MINUTES).build()
    fun send(account: MobileAccount, job: MobileUpload, open: () -> InputStream,
             current: () -> Boolean, progress: (Int) -> Unit): Boolean {
        if(job.auth!=account.queueKey)throw ApiException(409,"Очередь принадлежит другому аккаунту")
        fun requireCurrent() { if(!current())throw IOException("Сессия изменилась") }
        var cookie=MobilePolicy.cookieHeader(account.cookie)
        var csrf=""
        fun execute(path: String, body: RequestBody?=null): JSONObject {
            requireCurrent()
            val builder=Request.Builder().url(account.origin+path).header("Cookie",cookie).header("X-Photo-App-Origin",account.origin)
            if(body!=null)builder.post(body).header("X-Photo-CSRF",csrf)
            client.newCall(builder.build()).execute().use { response ->
                requireCurrent()
                val json=try{JSONObject(response.body?.string().orEmpty())}catch(_:Exception){throw IOException("Некорректный ответ сервера")}
                if(!response.isSuccessful)throw ApiException(response.code,json.optString("error","Ошибка загрузки (${response.code})"))
                val cookies=MobilePolicy.cookies(cookie).toMutableMap()
                for(header in response.headers.values("Set-Cookie")) Cookie.parse(response.request.url,header)?.let { if(it.name in setOf("photo_account","photo_csrf"))cookies[it.name]=it.value }
                cookie=cookies.entries.joinToString("; "){"${it.key}=${it.value}"}
                return json
            }
        }
        val status=execute("/api/account/status")
        if(!status.optBoolean("authenticated")||status.optString("id")!=account.owner)throw ApiException(401,"Войди в свой аккаунт заново")
        csrf=status.optString("csrf")
        val receipt=execute("/api/assets/upload-status?key="+job.id)
        if(receipt.optBoolean("complete")){phase("Уже загружено");progress(100);return receipt.optBoolean("duplicate")}
        run {
            phase("Проверка повторов");progress(0)
            val digest=java.security.MessageDigest.getInstance("SHA-256")
            open().use { input -> val buffer=ByteArray(65536);var read=0L;while(true){requireCurrent();val n=input.read(buffer);if(n<0)break;digest.update(buffer,0,n);read+=n;progress((read*99/job.size).toInt().coerceIn(0,99))};if(read!=job.size)throw ApiException(409,"Файл изменился. Выбери его повторно") }
            val hash=digest.digest().joinToString(""){"%02x".format(it)}
            val check=JSONObject().put("size",job.size).put("sha256",hash)
            val checkBody=object:RequestBody(){private val bytes=check.toString().toByteArray();override fun contentType()="application/json".toMediaTypeOrNull();override fun contentLength()=bytes.size.toLong();override fun writeTo(sink:BufferedSink){sink.write(bytes)}}
            if(execute("/api/assets/check",checkBody).optBoolean("duplicate")){phase("Уже загружено");progress(100);return true}
        }
        phase("Передача");progress(0)
        val body=object:RequestBody(){
            override fun contentType()=job.mime.toMediaTypeOrNull()
            override fun contentLength()=job.size
            override fun writeTo(sink:BufferedSink){
                open().use { input -> val buffer=ByteArray(65536);var sent=0L;var last=-1
                    while(sent<job.size){requireCurrent();val n=input.read(buffer,0,minOf(buffer.size.toLong(),job.size-sent).toInt());if(n<0)throw ApiException(409,"Файл изменился. Выбери его повторно");sink.write(buffer,0,n);sent+=n
                        val value=(sent*99/job.size).toInt();if(value!=last){last=value;progress(value)} }
                    if(input.read()!=-1)throw ApiException(409,"Файл изменился во время загрузки")
                }
            }
        }
        requireCurrent()
        val request=Request.Builder().url(account.origin+"/api/assets/upload").header("Cookie",cookie).header("X-Photo-App-Origin",account.origin)
            .header("X-Photo-CSRF",csrf).header("X-Upload-ID",job.id).header("X-File-Name",URLEncoder.encode(job.name,"UTF-8").replace("+","%20")).post(body).build()
        client.newCall(request).execute().use { response ->
            requireCurrent()
            val data=try{JSONObject(response.body?.string().orEmpty())}catch(_:Exception){throw IOException("Не удалось подтвердить загрузку")}
            if(!response.isSuccessful)throw ApiException(response.code,data.optString("error","Не удалось загрузить файл"))
            phase("Готово");progress(100);return data.optBoolean("duplicate")
        }
    }
}
