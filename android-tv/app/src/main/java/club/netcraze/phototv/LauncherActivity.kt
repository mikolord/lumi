package club.netcraze.phototv

import android.app.Activity
import android.content.Intent
import android.content.res.Configuration
import android.content.pm.PackageManager
import android.os.Bundle

class LauncherActivity : Activity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val tv = resources.configuration.uiMode and Configuration.UI_MODE_TYPE_MASK == Configuration.UI_MODE_TYPE_TELEVISION ||
            packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK) || packageManager.hasSystemFeature(PackageManager.FEATURE_TELEVISION)
        val mode = MobilePolicy.device(tv, resources.configuration.smallestScreenWidthDp)
        startActivity(Intent(this, if (mode == LumiDevice.TV) MainActivity::class.java else MobileActivity::class.java))
        finish()
    }
}
