package club.netcraze.phototv

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Cookie
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Test
import org.junit.Assert.*
import java.io.IOException
import java.nio.file.Files

class ThumbnailCacheTest {
    private fun permit(owner:String="one",tag:String="revision-a")=ThumbnailPermit(owner,tag,ByteArray(32){7})
    @Test fun persistsCiphertextButReauthorizesAndInvalidatesChanges(){
        val dir=Files.createTempDirectory("thumb-test").toFile();val server=MockWebServer();server.start()
        try{
            val origin=server.url("/").toString().trimEnd('/');var tag="a";var owner="one";var allowed=true;var checks=0
            fun client(cache:ThumbnailCache)=OkHttpClient.Builder().addInterceptor(ThumbnailInterceptor(cache,{origin},{0}){checks++;if(!allowed)throw IOException("revoked");permit(owner,tag)}).build()
            val url=server.url("/media/3/thumbnail");val request=Request.Builder().url(url).build()
            server.enqueue(MockResponse().setBody("private jpeg fixture"))
            client(ThumbnailCache(dir)).newCall(request).execute().use{assertEquals("private jpeg fixture",it.body!!.string())}
            assertFalse(String(dir.listFiles()!!.single().readBytes()).contains("private jpeg fixture"))
            // A new cache/client represents restarting the application.
            client(ThumbnailCache(dir)).newCall(request).execute().use{assertEquals("private jpeg fixture",it.body!!.string())}
            assertEquals(1,server.requestCount);assertEquals(3,checks)
            tag="b";server.enqueue(MockResponse().setBody("edited thumbnail"));client(ThumbnailCache(dir)).newCall(request).execute().use{assertEquals("edited thumbnail",it.body!!.string())};assertEquals(2,server.requestCount)
            owner="two";server.enqueue(MockResponse().setBody("other account"));client(ThumbnailCache(dir)).newCall(request).execute().use{assertEquals("other account",it.body!!.string())};assertEquals(3,server.requestCount)
            allowed=false
            try{client(ThumbnailCache(dir)).newCall(request).execute();fail("Revoked access must not return cached pixels")}catch(_:IOException){}
            assertEquals(3,server.requestCount)
        }finally{server.shutdown();dir.deleteRecursively()}
    }
    @Test fun logoutDuringDownloadDoesNotWriteOrReturnBytes(){
        val dir=Files.createTempDirectory("thumb-race").toFile();val server=MockWebServer();server.start()
        try{
            val cache=ThumbnailCache(dir);val origin=server.url("/").toString().trimEnd('/');var epoch=0L;var checks=0
            val client=OkHttpClient.Builder().addInterceptor(ThumbnailInterceptor(cache,{origin},{epoch}){checks++;if(checks==2)epoch++;permit()}).build()
            server.enqueue(MockResponse().setBody("must not escape"))
            try{client.newCall(Request.Builder().url(server.url("/media/1/thumbnail")).build()).execute();fail("Session changed")}catch(_:IOException){}
            assertEquals(0L,cache.sizeBytes())
        }finally{server.shutdown();dir.deleteRecursively()}
    }
    @Test fun corruptionClearAndBudget(){
        val dir=Files.createTempDirectory("thumb-budget").toFile()
        try{
            val cache=ThumbnailCache(dir,maxBytes=100,maxEntries=1);val p=permit();val origin="https://photos.example"
            cache.write(origin,1,p,ByteArray(30){1},cache.epoch);assertNotNull(cache.read(origin,1,p))
            dir.listFiles()!!.single().writeText("corrupt");assertNull(cache.read(origin,1,p))
            cache.write(origin,1,p,ByteArray(30),cache.epoch);cache.write(origin,2,p,ByteArray(30),cache.epoch);assertTrue(cache.sizeBytes()<=100);assertEquals(1,dir.listFiles()!!.size)
            val stale=cache.epoch;cache.clear();cache.write(origin,3,p,byteArrayOf(1),stale);assertEquals(0L,cache.sizeBytes())
        }finally{dir.deleteRecursively()}
    }
    @Test fun cookieJarHonorsOriginPathSecureExpiryAndVaultIsNotPersisted(){
        val origin="https://photos.example".toHttpUrl();var persisted=emptyList<Cookie>()
        val jar=OriginCookieJar({origin},emptyList(),{persisted=it})
        val account=Cookie.Builder().name("photo_account").value("fixture").hostOnlyDomain(origin.host).path("/media").secure().build()
        val vault=Cookie.Builder().name("photo_vault").value("fixture").hostOnlyDomain(origin.host).build()
        jar.saveFromResponse(origin,listOf(account,vault));assertEquals(listOf("photo_account"),persisted.map{it.name})
        assertEquals(2,jar.loadForRequest("https://photos.example/media/1".toHttpUrl()).size)
        assertEquals(listOf("photo_vault"),jar.loadForRequest("https://photos.example/api/status".toHttpUrl()).map{it.name})
        for(url in listOf("https://foreign.example/media/1","http://photos.example/media/1","https://photos.example:9999/media/1"))assertTrue(jar.loadForRequest(url.toHttpUrl()).isEmpty())
        val expired=Cookie.Builder().name("expired").value("fixture").hostOnlyDomain(origin.host).expiresAt(1).build()
        jar.saveFromResponse(origin,listOf(expired));assertFalse(jar.has("expired"))
        var accepting=true
        val scoped=OriginCookieJar({origin},emptyList(),{}, {accepting})
        accepting=false;scoped.saveFromResponse(origin,listOf(vault));accepting=true;assertFalse(scoped.has("photo_vault"))
        jar.clear();assertTrue(jar.loadForRequest(origin).isEmpty());assertTrue(persisted.isEmpty())
    }
}
