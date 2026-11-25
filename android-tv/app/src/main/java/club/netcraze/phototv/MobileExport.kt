package club.netcraze.phototv

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.Base64
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.concurrent.Executors

/** Only explicit page-selected bytes enter app-private temporary files; no arbitrary file API. */
internal class MobileExport(private val activity:Activity) {
    private val io=Executors.newSingleThreadExecutor()
    private val directory=File(activity.cacheDir,"shares").apply{mkdirs()}
    private data class Pending(val file:File,val output:FileOutputStream,val size:Long,val mime:String,val name:String,var received:Long=0)
    private val pending=mutableMapOf<String,Pending>()
    private val completed=mutableMapOf<String,Triple<File,String,String>>()
    private var saveFile:Triple<File,String,String>?=null
    init {directory.listFiles()?.filter{it.isFile&&System.currentTimeMillis()-it.lastModified()>24L*3600000}?.forEach{it.delete()}}
    fun handle(message:JSONObject,reply:(JSONObject)->Unit){
        io.execute{
            try{
                val result=when(message.optString("op")){
                    "export-begin"->{
                        require(pending.isEmpty()){ "Дождись завершения предыдущего файла" }
                        val name=message.optString("name","photo.jpg").replace('\\','/').substringAfterLast('/').replace(Regex("[\r\n]")," ").take(150).ifBlank{"photo.jpg"}
                        val size=message.optLong("size");require(size in 1..(10L*1024*1024*1024)&&directory.usableSpace>size+64L*1024*1024){"Недостаточно места для подготовки файла"}
                        val mime=message.optString("mime","application/octet-stream").take(100)
                        val id=UUID.randomUUID().toString();val file=File(directory,"$id-$name")
                        pending[id]=Pending(file,FileOutputStream(file),size,mime,name)
                        JSONObject().put("token",id)
                    }
                    "export-chunk"->{
                        val value=pending[message.getString("token")]?:error("Файл уже закрыт")
                        require(message.optLong("offset",-1)==value.received){"Нарушен порядок передачи"}
                        val encoded=message.getString("bytes");require(encoded.length<=88000)
                        val data=Base64.decode(encoded,Base64.DEFAULT);require(value.received+data.size<=value.size)
                        value.output.write(data);value.received+=data.size;JSONObject()
                    }
                    "export-finish"->{
                        val token=message.getString("token");val value=pending.remove(token)?:error("Файл не найден")
                        value.output.close()
                        if(value.received!=value.size){value.file.delete();error("Передача файла прервалась")}
                        completed[token]=Triple(value.file,value.mime,value.name)
                        if(message.optString("mode")=="save")save(completed.getValue(token))
                        JSONObject().put("token",token)
                    }
                    "export-abort"->{val token=message.getString("token");pending.remove(token)?.let{it.output.close();it.file.delete()};JSONObject()}
                    "export-share"->{
                        val ids=message.getJSONArray("tokens");require(ids.length() in 1..100)
                        val files=(0 until ids.length()).map{completed[ids.getString(it)]?:error("Файл не подготовлен")}
                        activity.runOnUiThread{
                            val uris=ArrayList(files.map{FileProvider.getUriForFile(activity,"${BuildConfig.APPLICATION_ID}.fileprovider",it.first)})
                            val intent=Intent(if(uris.size==1)Intent.ACTION_SEND else Intent.ACTION_SEND_MULTIPLE).setType(if(files.all{it.second.startsWith("image/")})"image/*"else if(files.all{it.second.startsWith("video/")})"video/*"else "*/*")
                            if(uris.size==1)intent.putExtra(Intent.EXTRA_STREAM,uris[0])else intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM,uris)
                            intent.clipData=ClipData.newRawUri("lumi",uris[0]).apply{uris.drop(1).forEach{addItem(ClipData.Item(it))}}
                            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            try{activity.startActivity(Intent.createChooser(intent,"Поделиться"))}catch(_:Exception){}
                        }
                        JSONObject()
                    }
                    "share-text"->{
                        val text=listOf(message.optString("title"),message.optString("text"),message.optString("url")).filter{it.isNotBlank()}.joinToString("\n").take(20000)
                        activity.runOnUiThread{try{activity.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,text),"Поделиться"))}catch(_:Exception){}}
                        JSONObject()
                    }
                    else->error("Неизвестная операция")
                }
                reply(result)
            }catch(error:Exception){
                pending.values.forEach{try{it.output.close()}catch(_:Exception){};it.file.delete()};pending.clear()
                reply(JSONObject().put("error",error.message?:"Не удалось подготовить файл"))
            }
        }
    }
    private fun save(value:Triple<File,String,String>){
        if(Build.VERSION.SDK_INT>=29){
            val resolver=activity.contentResolver
            val uri=resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,ContentValues().apply{
                put(MediaStore.MediaColumns.DISPLAY_NAME,value.third);put(MediaStore.MediaColumns.MIME_TYPE,value.second);put(MediaStore.MediaColumns.IS_PENDING,1)
            })?:error("Не удалось создать файл")
            try{resolver.openOutputStream(uri)?.use{out->value.first.inputStream().use{it.copyTo(out)}}?:error("Файл недоступен")
                resolver.update(uri,ContentValues().apply{put(MediaStore.MediaColumns.IS_PENDING,0)},null,null)
            }catch(error:Exception){resolver.delete(uri,null,null);throw error}
            activity.runOnUiThread{android.widget.Toast.makeText(activity,"Сохранено в Загрузки",android.widget.Toast.LENGTH_LONG).show()}
        }else{
            saveFile=value
            activity.runOnUiThread{activity.startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(value.second).putExtra(Intent.EXTRA_TITLE,value.third),105)}
        }
    }
    fun activityResult(code:Int,result:Int,data:Intent?){
        if(code!=105)return
        val value=saveFile;saveFile=null
        if(result==Activity.RESULT_OK&&value!=null&&data?.data!=null)io.execute{
            try{activity.contentResolver.openOutputStream(data.data!!)?.use{out->value.first.inputStream().use{it.copyTo(out)}}}catch(_:Exception){}
        }
    }
    fun close(){io.execute{pending.values.forEach{try{it.output.close()}catch(_:Exception){};it.file.delete()};pending.clear()};io.shutdown()}
}
