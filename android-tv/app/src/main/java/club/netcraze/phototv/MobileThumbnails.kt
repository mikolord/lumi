package club.netcraze.phototv

import android.content.Context
import android.webkit.WebResourceResponse
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayInputStream
import java.util.Base64

internal class MobileThumbnails(context:Context) {
    private val auth=MobileAccountStore(context)
    val cache=ThumbnailCache(java.io.File(context.cacheDir,"lumi-mobile-thumbnails"))
    fun response(url:String):WebResourceResponse? {
        val account=auth.read()?:return null
        fun current()=auth.current(account.fingerprint) && MobilePolicy.fingerprint(account.origin,android.webkit.CookieManager.getInstance().getCookie(account.origin).orEmpty())==account.fingerprint
        if(!MobilePolicy.sameOrigin(account.origin,url)||!current())return null
        val path=android.net.Uri.parse(url).path.orEmpty()
        if(!Regex("/media/[0-9]+/thumbnail").matches(path))return null
        return try {
            val client=MobileApi.client.newBuilder().addInterceptor(ThumbnailInterceptor(cache,{account.origin},{if(current())0L else 1L}) { index ->
                val permit=MobileApi.get(account,"/api/thumbnails/verify?index=$index")
                if(!current())throw java.io.IOException("Session changed")
                ThumbnailPermit(permit.getString("owner"),permit.getString("tag"),Base64.getDecoder().decode(permit.getString("key")))
            }).build()
            client.newCall(Request.Builder().url(url).header("Cookie",account.cookie).build()).execute().use { response ->
                if(!response.isSuccessful||!current())return null
                val bytes=response.body?.bytes()?:return null
                WebResourceResponse(response.header("Content-Type")?.substringBefore(';')?:"image/jpeg",null,200,"OK",mapOf("Cache-Control" to "no-store"),ByteArrayInputStream(bytes))
            }
        }catch(_:Exception){null}
    }
}
