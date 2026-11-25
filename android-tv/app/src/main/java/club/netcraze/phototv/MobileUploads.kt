package club.netcraze.phototv

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.ContentUris
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.provider.MediaStore
import androidx.work.*
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock

internal object MobileUploads {
    fun constraints(context: Context, auto: Boolean=false): Constraints {
        val wifi=context.getSharedPreferences("lumi_mobile",Context.MODE_PRIVATE).getBoolean("wifi",true)
        return Constraints.Builder().setRequiredNetworkType(if(wifi)NetworkType.UNMETERED else NetworkType.CONNECTED)
            .setRequiresBatteryNotLow(auto).build()
    }
    fun enqueue(context: Context): androidx.work.Operation {
        return WorkManager.getInstance(context).enqueueUniqueWork("lumi-mobile-uploads",ExistingWorkPolicy.APPEND_OR_REPLACE,
            OneTimeWorkRequestBuilder<MobileUploadWorker>().setConstraints(constraints(context)).setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build())
    }
    fun periodic(context: Context, enable: Boolean) {
        val manager=WorkManager.getInstance(context)
        if(!enable){manager.cancelUniqueWork("lumi-mobile-auto");return}
        manager.enqueueUniquePeriodicWork("lumi-mobile-auto",ExistingPeriodicWorkPolicy.UPDATE,
            PeriodicWorkRequestBuilder<MobileUploadWorker>(15,TimeUnit.MINUTES).setConstraints(constraints(context,true)).build())
        enqueue(context)
    }
    fun mediaPermissions(): Array<String> = if(Build.VERSION.SDK_INT>=34)arrayOf(Manifest.permission.READ_MEDIA_IMAGES,Manifest.permission.READ_MEDIA_VIDEO,Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) else if(Build.VERSION.SDK_INT>=33)arrayOf(Manifest.permission.READ_MEDIA_IMAGES,Manifest.permission.READ_MEDIA_VIDEO)
        else arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
    fun hasMedia(context: Context) = mediaPermissions().any {context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED} ||
        (Build.VERSION.SDK_INT>=34&&context.checkSelfPermission(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)==PackageManager.PERMISSION_GRANTED)
    fun scan(context: Context, account: MobileAccount, current: () -> Boolean) {
        val prefs=context.getSharedPreferences("lumi_mobile",Context.MODE_PRIVATE)
        if(!prefs.getBoolean("auto",false)||prefs.getString("auto_owner","")!=account.queueKey||!hasMedia(context))return
        val since=prefs.getLong("auto_since",System.currentTimeMillis()/1000)
        val camera=prefs.getBoolean("camera_only",true)
        val collection=MediaStore.Files.getContentUri("external")
        val path=if(Build.VERSION.SDK_INT>=29)MediaStore.MediaColumns.RELATIVE_PATH else MediaStore.MediaColumns.DATA
        val where="(${MediaStore.Files.FileColumns.MEDIA_TYPE}=1 OR ${MediaStore.Files.FileColumns.MEDIA_TYPE}=3) AND ${MediaStore.MediaColumns.DATE_ADDED}>=?"+
            if(camera)" AND $path LIKE ?" else ""
        val args=if(camera)arrayOf(since.toString(),if(Build.VERSION.SDK_INT>=29)"DCIM/%" else "%/DCIM/%")else arrayOf(since.toString())
        val projection=arrayOf(MediaStore.MediaColumns._ID,MediaStore.MediaColumns.DISPLAY_NAME,MediaStore.MediaColumns.SIZE,MediaStore.MediaColumns.MIME_TYPE,MediaStore.MediaColumns.DATE_MODIFIED)
        MobileUploadStore(context).use { db ->
            context.contentResolver.query(collection,projection,where,args,"${MediaStore.MediaColumns.DATE_ADDED} DESC")?.use { c ->
                while(c.moveToNext()&&current())db.enqueue(ContentUris.withAppendedId(collection,c.getLong(0)).toString(),c.getString(1).orEmpty(),c.getLong(2),c.getString(3)?:"application/octet-stream",account.queueKey,c.getLong(4).toString(),"auto")
            }
        }
    }
}

class MobileUploadWorker(context: Context, params: WorkerParameters) : Worker(context,params) {
    companion object { private val lock=ReentrantLock(); private const val CHANNEL="lumi-uploads";private const val NOTIFICATION=2104 }
    private fun foreground(text:String,progress:Int=0):ForegroundInfo {
        val manager=applicationContext.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL,"Загрузка фотографий",NotificationManager.IMPORTANCE_LOW))
        val intent=PendingIntent.getActivity(applicationContext,0,Intent(applicationContext,LauncherActivity::class.java),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification=Notification.Builder(applicationContext,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("lumi · загрузка").setContentText(text).setContentIntent(intent).setOnlyAlertOnce(true).setOngoing(true)
            .setProgress(100,progress.coerceIn(0,100),progress==0).build()
        return if(Build.VERSION.SDK_INT>=29)ForegroundInfo(NOTIFICATION,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)else ForegroundInfo(NOTIFICATION,notification)
    }
    override fun doWork():Result {
        if(!lock.tryLock())return Result.retry()
        val auth=MobileAccountStore(applicationContext)
        val account=auth.read()?:run{lock.unlock();return Result.success()}
        val prefs=applicationContext.getSharedPreferences("lumi_mobile",Context.MODE_PRIVATE)
        fun current()=!isStopped&&auth.current(account.fingerprint)&&!prefs.getBoolean("paused",false)
        val db=MobileUploadStore(applicationContext)
        try {
            if(!current())return Result.success()
            if(prefs.getBoolean("auto",false)&&!MobileUploads.hasMedia(applicationContext))prefs.edit().putBoolean("auto",false).apply()
            if(!prefs.getBoolean("auto",false)&&db.list(account.queueKey,true,false).isEmpty())return Result.success()
            setForegroundAsync(foreground("Проверяем очередь…")).get()
            val status=MobileApi.get(account,"/api/account/status")
            if(!status.optBoolean("authenticated")||status.optString("id")!=account.owner){
                for(job in db.list(account.queueKey,true))db.state(job.id,"error","Войди в аккаунт заново")
                auth.clear();return Result.success()
            }
            try {MobileUploads.scan(applicationContext,account,::current)}catch(_:SecurityException){applicationContext.getSharedPreferences("lumi_mobile",Context.MODE_PRIVATE).edit().putBoolean("auto",false).apply()}
            var lastNotice=0L
            val started=System.currentTimeMillis()
            while(current()) {
                val pending=db.list(account.queueKey,true,prefs.getBoolean("auto",false))
                if(pending.isEmpty())return Result.success()
                for(job in pending){
                    if(!current())return Result.success()
                    if(job.source=="auto"&&!prefs.getBoolean("auto",false))continue
                    if(System.currentTimeMillis()-started>8*60*1000){MobileUploads.enqueue(applicationContext).result.get();return Result.success()}
                    try {
                        var last=-1
                        val duplicate=MobileUploadTransport(phase={value->last=-1;prefs.edit().putString("upload_phase",value).apply()}).send(account,job,
                            {applicationContext.contentResolver.openInputStream(android.net.Uri.parse(job.uri))?:throw java.io.IOException("Файл недоступен")},{current()&&(job.source!="auto"||prefs.getBoolean("auto",false))}) { percent ->
                            if(percent/5!=last){last=percent/5;prefs.edit().putString("active_owner",account.queueKey).putString("upload_file",job.name).putInt("upload_percent",percent).apply();if(System.currentTimeMillis()-lastNotice>500){lastNotice=System.currentTimeMillis();setForegroundAsync(foreground("${prefs.getString("upload_phase","")} · ${job.name}",percent))}}
                        }
                        db.state(job.id,if(duplicate)"duplicate" else "done")
                    }catch(error:ApiException){
                        db.state(job.id,"error",error.message?:"Ошибка сервера")
                        if(error.statusCode==401||error.statusCode==403)return Result.success()
                        if(error.statusCode>=500||error.statusCode==429){db.state(job.id,"pending",error.message.orEmpty());return Result.retry()}
                    }catch(_:SecurityException){db.state(job.id,"error","Нет доступа к файлу. Выбери его повторно или разреши доступ к медиатеке")}
                    catch(error:java.io.FileNotFoundException){db.state(job.id,"error","Файл удалён или перемещён")}
                    catch(error:java.io.IOException){if(!current())return Result.success();if(job.source=="auto"&&!prefs.getBoolean("auto",false))continue;db.state(job.id,"pending","Нет соединения. Android повторит загрузку");return Result.retry()}
                }
            }
            return Result.success()
        }catch(_:Exception){return if(isStopped)Result.success()else Result.retry()}
        finally{prefs.edit().remove("active_owner").remove("upload_file").remove("upload_percent").remove("upload_phase").apply();db.close();lock.unlock()}
    }
}
