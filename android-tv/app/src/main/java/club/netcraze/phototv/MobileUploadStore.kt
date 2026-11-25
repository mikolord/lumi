package club.netcraze.phototv

import android.content.Context
import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.net.Uri
import android.provider.OpenableColumns
import android.provider.DocumentsContract
import java.util.UUID

internal data class MobileUpload(val id: String, val uri: String, val name: String, val size: Long, val mime: String, val auth: String, val state: String, val error: String, val source: String="manual")
internal class MobileUploadStore(context: Context, name:String="lumi-mobile-uploads.db") : SQLiteOpenHelper(context.applicationContext, name, null, 1) {
    init { setWriteAheadLoggingEnabled(true) }
    override fun onCreate(db: SQLiteDatabase) { db.execSQL("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,uri TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,mime TEXT NOT NULL,auth TEXT NOT NULL,revision TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT 'manual',visible INTEGER NOT NULL DEFAULT 1,UNIQUE(auth,uri,revision))");db.execSQL("CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(auth,state)") }
    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) = Unit
    @Synchronized fun add(context: Context, uri: Uri, auth: String, revision: String = ""): Boolean {
        require(uri.scheme == "content" && uri.toString().length<16384 && auth.isNotEmpty())
        var name = ""; var size = -1L; var modified = revision
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) { name = cursor.getString(0).orEmpty(); size = cursor.getLong(1) }
        }
        if (size <= 0) context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { size = it.length }
        if (modified.isEmpty()) try { context.contentResolver.query(uri, arrayOf(DocumentsContract.Document.COLUMN_LAST_MODIFIED), null, null, null)?.use { if(it.moveToFirst()) modified=it.getLong(0).toString() } } catch (_: Exception) { }
        require(size in 1..(10L*1024*1024*1024)) { "Файл пустой, недоступен или больше 10 ГБ" }
        require(name.substringAfterLast('.', "").lowercase() in setOf("jpg","jpeg","png","webp","heic","heif","tif","tiff","bmp","gif","mp4","mov","m4v","webm","mkv","avi")) { "Этот формат пока не поддерживается" }
        return enqueue(uri.toString(), name, size, context.contentResolver.getType(uri) ?: "application/octet-stream", auth, modified+":selection:"+UUID.randomUUID())
    }
    @Synchronized fun enqueue(uri: String, name: String, size: Long, mime: String, auth: String, revision: String, source: String="manual"): Boolean {
        if (size <= 0 || size > 10L*1024*1024*1024) return false
        if (name.substringAfterLast('.', "").lowercase() !in setOf("jpg","jpeg","png","webp","heic","heif","tif","tiff","bmp","gif","mp4","mov","m4v","webm","mkv","avi")) return false
        val value = ContentValues().apply {
            put("id", UUID.randomUUID().toString()); put("uri",uri); put("name",name.take(255)); put("size",size)
            put("mime",mime); put("auth",auth); put("revision", "$size:$revision"); put("state","pending"); put("error", ""); put("source",source)
        }
        return writableDatabase.insertWithOnConflict("jobs", null, value, SQLiteDatabase.CONFLICT_IGNORE) != -1L
    }
    @Synchronized fun list(auth: String, pendingOnly: Boolean=false, auto: Boolean=true, errorsOnly:Boolean=false): List<MobileUpload> {
        val result= mutableListOf<MobileUpload>()
        readableDatabase.query("jobs",arrayOf("id","uri","name","size","mime","auth","state","error","source"),"auth=? AND visible=1"+(if(pendingOnly)" AND state='pending'" else if(errorsOnly)" AND state='error'" else "")+(if(pendingOnly&&!auto)" AND source='manual'" else ""),arrayOf(auth),null,null,if(pendingOnly)"rowid ASC" else "rowid DESC","100").use { c ->
            while(c.moveToNext()) result += MobileUpload(c.getString(0),c.getString(1),c.getString(2),c.getLong(3),c.getString(4),c.getString(5),c.getString(6),c.getString(7),c.getString(8))
        }
        return result
    }
    @Synchronized fun counts(auth: String): Map<String, Int> {
        val counts= mutableMapOf<String,Int>()
        readableDatabase.rawQuery("SELECT state,COUNT(*) FROM jobs WHERE auth=? AND visible=1 GROUP BY state",arrayOf(auth)).use { while(it.moveToNext())counts[it.getString(0)]=it.getInt(1) }
        return counts
    }
    @Synchronized fun state(id: String, state: String, error: String="") { writableDatabase.update("jobs",ContentValues().apply {put("state",state);put("error",error.take(400))},"id=?",arrayOf(id)) }
    @Synchronized fun failure(uri:String,auth:String,message:String){
        if(!uri.startsWith("content://")||uri.length>16384)return
        writableDatabase.insert("jobs",null,ContentValues().apply{put("id",UUID.randomUUID().toString());put("uri",uri);put("name",uri.substringAfterLast('/').take(100).ifBlank{"Файл"});put("size",0);put("mime","application/octet-stream");put("auth",auth);put("revision",UUID.randomUUID().toString());put("state","error");put("error",message.take(400))})
    }
    @Synchronized fun clearErrors(auth:String){writableDatabase.delete("jobs","auth=? AND state='error'",arrayOf(auth))}
    @Synchronized fun retry(auth: String) { writableDatabase.update("jobs",ContentValues().apply {put("state","pending");put("error","")},"auth=? AND state='error' AND size>0",arrayOf(auth)) }
    @Synchronized fun clearFinished(auth: String) { writableDatabase.update("jobs",ContentValues().apply{put("visible",0)},"auth=? AND state IN ('done','duplicate')",arrayOf(auth)) }
}
