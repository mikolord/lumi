package club.netcraze.phototv

import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.drawable.AdaptiveIconDrawable
import android.graphics.drawable.BitmapDrawable
import android.os.Build
import android.provider.MediaStore
import android.content.ContentValues
import android.webkit.CookieManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.WorkManager
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.RecordedRequest
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class UniversalDeviceTest {
 private lateinit var context:Context
 @Before fun emulatorOnly(){Assume.assumeTrue(Build.HARDWARE in setOf("ranchu","goldfish"));context=InstrumentationRegistry.getInstrumentation().targetContext}
 private fun waitFor(condition:()->Boolean){val until=System.currentTimeMillis()+45000;while(!condition()&&System.currentTimeMillis()<until)Thread.sleep(250);assertTrue("Timed out",condition())}
 @Test fun iconResourcesAdaptAndLauncherOpensMobile(){
  val phone=context.createConfigurationContext(Configuration(context.resources.configuration).apply{touchscreen=Configuration.TOUCHSCREEN_FINGER;uiMode=Configuration.UI_MODE_TYPE_NORMAL})
  assertTrue(phone.getDrawable(R.drawable.lumi_platform_icon) is AdaptiveIconDrawable)
  val tv=context.createConfigurationContext(Configuration(context.resources.configuration).apply{touchscreen=Configuration.TOUCHSCREEN_NOTOUCH;uiMode=Configuration.UI_MODE_TYPE_TELEVISION})
  val art=tv.getDrawable(R.drawable.lumi_platform_icon) as BitmapDrawable
  assertEquals(496,art.bitmap.width);assertEquals(280,art.bitmap.height)
  val intent=context.packageManager.getLaunchIntentForPackage(context.packageName)!!
  assertTrue(intent.component!!.className.endsWith("LauncherActivity"))
 }
 @Test fun clearingFinishedKeepsDedupeAndAccountsAreIsolated(){
  val name="lumi-test-${UUID.randomUUID()}.db"
  MobileUploadStore(context,name).use{db->
   assertTrue(db.enqueue("content://test/1","photo.jpg",10,"image/jpeg","owner-a","1"))
   assertEquals(0,db.list("owner-b").size)
   val job=db.list("owner-a").single();db.state(job.id,"done");db.clearFinished("owner-a")
   assertEquals(0,db.list("owner-a").size)
   assertFalse(db.enqueue("content://test/1","photo.jpg",10,"image/jpeg","owner-a","1"))
   assertTrue(db.enqueue("content://test/1","photo.jpg",10,"image/jpeg","owner-a","2"))
   assertTrue(db.enqueue("content://test/2","auto.jpg",10,"image/jpeg","owner-a","1","auto"))
   assertEquals(1,db.list("owner-a",pendingOnly=true,auto=false).size)
   assertEquals(2,db.list("owner-a",pendingOnly=true,auto=true).size)
  }
  context.deleteDatabase(name)
 }
 @Test fun concurrentFirstOpenDoesNotLoseQueueJobs(){
  val name="lumi-test-concurrent-${UUID.randomUUID()}.db"
  val gate=java.util.concurrent.CountDownLatch(1)
  val pool=java.util.concurrent.Executors.newFixedThreadPool(12)
  try{
   val results=(0 until 24).map{index->pool.submit<Boolean>{gate.await();MobileUploadStore(context,name).use{it.enqueue("content://fixture/$index","$index.jpg",10,"image/jpeg","owner","1")}}}
   gate.countDown();results.forEach{assertTrue(it.get())}
   MobileUploadStore(context,name).use{assertEquals(24,it.list("owner").size)}
  }finally{pool.shutdownNow();pool.awaitTermination(5,java.util.concurrent.TimeUnit.SECONDS);context.deleteDatabase(name)}
 }
 @Test fun mobileWebSessionAndDurableUploadUseTheSameVerifiedAccount(){
  val server=MockWebServer();val uploaded=AtomicReference<RecordedRequest?>();val owner="device-test-${UUID.randomUUID()}"
  server.dispatcher=object:Dispatcher(){override fun dispatch(request:RecordedRequest):MockResponse {
   return when {
    request.path=="/" -> MockResponse().setHeader("Content-Type","text/html").addHeader("Set-Cookie","photo_account=fixture; Path=/; HttpOnly").addHeader("Set-Cookie","photo_csrf=fixture; Path=/; HttpOnly").setBody("<html><body><div class='account-storage'>Test library</div><script>window.PhotoManage={open:function(){}};</script></body></html>")
    request.path=="/api/account/status" -> MockResponse().setHeader("Content-Type","application/json").setBody("{\"authenticated\":true,\"id\":\"$owner\",\"name\":\"Emulator\",\"csrf\":\"fixture\"}")
    request.path?.startsWith("/api/assets/upload-status")==true -> MockResponse().setBody("{\"complete\":false}")
    request.path=="/api/assets/check" -> MockResponse().setBody("{\"duplicate\":false}")
    request.path=="/api/assets/upload" -> {uploaded.set(request);MockResponse().setBody("{\"id\":1,\"duplicate\":false}")}
    else -> MockResponse().setResponseCode(404)
   }
  }}
  server.start()
  val origin=server.url("/").toString().trimEnd('/')
  val preferences=context.getSharedPreferences("lumi_mobile",Context.MODE_PRIVATE)
  preferences.edit().putString("server",origin).putBoolean("wifi",false).putBoolean("paused",false).putBoolean("auto",false).commit()
  val image=context.contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,ContentValues().apply{put(MediaStore.Images.Media.DISPLAY_NAME,"lumi-instrumentation.jpg");put(MediaStore.Images.Media.MIME_TYPE,"image/jpeg")})!!
  try{
   context.contentResolver.openOutputStream(image)!!.use{Bitmap.createBitmap(16,16,Bitmap.Config.ARGB_8888).apply{eraseColor(android.graphics.Color.BLUE)}.compress(Bitmap.CompressFormat.JPEG,95,it)}
   val activity=InstrumentationRegistry.getInstrumentation().startActivitySync(Intent(context,LauncherActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
   val accounts=MobileAccountStore(context)
   waitFor{accounts.read()?.owner==owner}
   val account=accounts.read()!!
   MobileUploadStore(context).use{db->assertTrue(db.add(context,image,account.queueKey))}
   MobileUploads.enqueue(context)
   waitFor{MobileUploadStore(context).use{it.list(account.queueKey).firstOrNull()?.state=="done"}}
   val request=uploaded.get()!!
   assertEquals("photo_account=fixture; photo_csrf=fixture",request.getHeader("Cookie"))
   assertEquals("fixture",request.getHeader("X-Photo-CSRF"));assertTrue(request.bodySize>0)
   InstrumentationRegistry.getInstrumentation().runOnMainSync{activity.finish()}
  }finally{
   InstrumentationRegistry.getInstrumentation().runOnMainSync{ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).filterIsInstance<MobileActivity>().forEach{it.finish()}}
   MobileAccountStore(context).clear();preferences.edit().remove("server").commit()
   WorkManager.getInstance(context).cancelUniqueWork("lumi-mobile-uploads").result.get()
   context.contentResolver.delete(image,null,null);server.shutdown()
  }
 }
}
