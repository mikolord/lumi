package club.netcraze.phototv
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.MockResponse
import org.junit.Test
import org.junit.Assert.*
import java.io.ByteArrayInputStream
import java.util.concurrent.TimeUnit

class MobileUploadTransportTest {
 private fun scenario(block:(MockWebServer,MobileAccount,MobileUpload)->Unit){val server=MockWebServer();server.start();try{val a=MobileAccount(server.url("/").toString().trimEnd('/'),"photo_account=account; photo_csrf=old; photo_vault=private","owner","");block(server,a,MobileUpload("0123456789abcdef", "content://fixture/photo", "My photo.jpg",4,"image/jpeg",a.queueKey,"pending",""))}finally{server.shutdown()}}
 private fun status(server:MockWebServer,owner:String="owner"){server.enqueue(MockResponse().setBody("{\"authenticated\":true,\"id\":\"$owner\",\"csrf\":\"fresh\"}").addHeader("Set-Cookie","photo_csrf=fresh; Path=/; HttpOnly"))}
 @Test fun uploadsRawBytesWithRotatedCsrfAndNoVaultCookie()=scenario{server,a,job->
  status(server);server.enqueue(MockResponse().setBody("{\"complete\":false}"));server.enqueue(MockResponse().setBody("{\"duplicate\":false}"));server.enqueue(MockResponse().setBody("{\"id\":1,\"duplicate\":false}"))
  assertFalse(MobileUploadTransport(OkHttpClient()).send(a,job,{ByteArrayInputStream(byteArrayOf(1,2,3,4))},{true},{}))
  repeat(3){server.takeRequest()};val upload=server.takeRequest();assertEquals("/api/assets/upload",upload.path);assertArrayEquals(byteArrayOf(1,2,3,4),upload.body.readByteArray());assertEquals("4",upload.getHeader("Content-Length"));assertEquals("fresh",upload.getHeader("X-Photo-CSRF"));assertEquals("My%20photo.jpg",upload.getHeader("X-File-Name"));assertFalse(upload.getHeader("Cookie")!!.contains("photo_vault"));assertTrue(upload.getHeader("Cookie")!!.contains("photo_csrf=fresh"))
 }
 @Test fun resumesCompletedReceiptWithoutReadingOrSendingFile()=scenario{server,a,job->status(server);server.enqueue(MockResponse().setBody("{\"complete\":true,\"duplicate\":true}"));assertTrue(MobileUploadTransport().send(a,job,{error("Must not reread completed original")},{true},{}));assertEquals(2,server.requestCount)}
 @Test fun duplicateCheckAvoidsUpload()=scenario{server,a,job->status(server);server.enqueue(MockResponse().setBody("{\"complete\":false}"));server.enqueue(MockResponse().setBody("{\"duplicate\":true}"));assertTrue(MobileUploadTransport().send(a,job,{ByteArrayInputStream(byteArrayOf(1,2,3,4))},{true},{}));assertEquals(3,server.requestCount)}
 @Test fun rejectsAnotherOwnerBeforeOpeningOriginal()=scenario{server,a,job->status(server,"other");try{MobileUploadTransport().send(a,job,{error("Must not read another owner's file")},{true},{});fail()}catch(e:ApiException){assertEquals(401,e.statusCode)};assertEquals(1,server.requestCount)}
 @Test fun credentialsNeverFollowRedirects()=scenario{server,a,job->val other=MockWebServer();other.start();try{server.enqueue(MockResponse().setResponseCode(302).addHeader("Location",other.url("/stolen")));try{MobileUploadTransport().send(a,job,{error("No file read")},{true},{});fail()}catch(_:java.io.IOException){};assertEquals(0,other.requestCount)}finally{other.shutdown()}}
 @Test fun cancelledSessionDoesNotEvenContactServer()=scenario{server,a,job->try{MobileUploadTransport().send(a,job,{error("No file read")},{false},{});fail()}catch(_:java.io.IOException){};assertEquals(0,server.requestCount)}
 @Test fun largeVideoUsesHashPreflightInsteadOfSendingDuplicateBytes()=scenario{server,a,job->
  status(server);server.enqueue(MockResponse().setBody("{\"complete\":false}"));server.enqueue(MockResponse().setBody("{\"duplicate\":true}"))
  val size=17L*1024*1024
  val open={object:java.io.InputStream(){var remaining=size;override fun read():Int=if(remaining-->0)7 else -1;override fun read(buffer:ByteArray,offset:Int,length:Int):Int{if(remaining<=0)return -1;val n=minOf(remaining,length.toLong()).toInt();java.util.Arrays.fill(buffer,offset,offset+n,7.toByte());remaining-=n;return n}}}
  assertTrue(MobileUploadTransport().send(a,job.copy(size=size,mime="video/mp4"),open,{true},{}))
  server.takeRequest();server.takeRequest();val check=server.takeRequest();assertEquals("/api/assets/check",check.path);assertTrue(check.bodySize<200);assertEquals(size,org.json.JSONObject(check.body.readUtf8()).getLong("size"))
 }
 @Test fun refusesJobsBoundToAnotherAccountWithoutNetworkOrFileAccess()=scenario{server,a,job->try{MobileUploadTransport().send(a,job.copy(auth="other-owner"),{error("No file access")},{true},{});fail()}catch(e:ApiException){assertEquals(409,e.statusCode)};assertEquals(0,server.requestCount)}

}
