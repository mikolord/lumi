package club.netcraze.phototv

import android.graphics.Bitmap
import android.graphics.Color
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter

object QrCode {
    fun render(content: String, size: Int): android.graphics.Bitmap? {
        return try {
            val matrix = QRCodeWriter().encode(
                content, BarcodeFormat.QR_CODE, size, size,
                mapOf(EncodeHintType.MARGIN to 1)
            )
            val bitmap = android.graphics.Bitmap.createBitmap(size, size, Bitmap.Config.RGB_565)
            for (x in 0 until size) {
                for (y in 0 until size) {
                    bitmap.setPixel(x, y, if (matrix[x, y]) Color.BLACK else Color.WHITE)
                }
            }
            bitmap
        } catch (_: Exception) {
            null
        }
    }
}
