package club.netcraze.phototv

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Account cookies are encrypted with a non-exportable Android Keystore key. */
internal class SecretStore(context: Context, name: String = "session") {
    private val prefs=context.getSharedPreferences(if(name=="session")"lumi_secrets" else "lumi_secrets_$name",Context.MODE_PRIVATE)
    private val alias="lumi.$name.v1"
    @Synchronized private fun key(): SecretKey {
        val store=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
        (store.getKey(alias,null) as? SecretKey)?.let{return it}
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply{
            init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    @Synchronized fun read(): String? = try {
        prefs.getString("cookies",null)?.let { encoded ->
            val data=Base64.getDecoder().decode(encoded);require(data.size>28)
            Cipher.getInstance("AES/GCM/NoPadding").run{init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,data.copyOfRange(0,12)));String(doFinal(data.copyOfRange(12,data.size)),Charsets.UTF_8)}
        }
    }catch(_:Exception){prefs.edit().clear().commit();null}
    @Synchronized fun write(text: String) {
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key())
        prefs.edit().putString("cookies",Base64.getEncoder().encodeToString(cipher.iv+cipher.doFinal(text.toByteArray()))).commit()
    }
    fun clear(){prefs.edit().clear().commit()}
}
