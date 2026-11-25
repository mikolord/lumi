package club.netcraze.phototv

import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

internal class OriginCookieJar(private val origin: () -> HttpUrl?, initial: List<Cookie>, private val persist: (List<Cookie>) -> Unit, private val accept: () -> Boolean = {true}) : CookieJar {
    private val cookies=initial.toMutableList()
    private fun sameServer(url:HttpUrl):Boolean {val server=origin()?:return false;return url.scheme==server.scheme&&url.host==server.host&&url.port==server.port}
    @Synchronized override fun saveFromResponse(url:HttpUrl, incoming:List<Cookie>){
        if(!sameServer(url)||!accept())return
        for(cookie in incoming){cookies.removeAll{it.name==cookie.name&&it.domain==cookie.domain&&it.path==cookie.path};if(cookie.expiresAt>System.currentTimeMillis()&&cookie.value.isNotEmpty())cookies.add(cookie)}
        persist(cookies.filter{it.name!="photo_vault"})
    }
    @Synchronized override fun loadForRequest(url:HttpUrl):List<Cookie> = if(!sameServer(url)||!accept())emptyList() else cookies.filter{it.expiresAt>System.currentTimeMillis()&&it.matches(url)}
    @Synchronized fun has(name:String):Boolean=origin()?.let{url->loadForRequest(url).any{it.name==name}}?:false
    @Synchronized fun removeVault(){cookies.removeAll{it.name=="photo_vault"};persist(cookies.toList())}
    @Synchronized fun clear(){cookies.clear();persist(emptyList())}
}
