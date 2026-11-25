package club.netcraze.phototv

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory

class App : Application(), ImageLoaderFactory {

    lateinit var session: Session
        private set

    override fun onCreate() {
        super.onCreate()
        session = Session(this)
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            private var started=0
            override fun onActivityStarted(a:android.app.Activity){started++}
            override fun onActivityStopped(a:android.app.Activity){started--;if(started==0&&!a.isChangingConfigurations)session.lockVault()}
            override fun onActivityCreated(a:android.app.Activity,b:android.os.Bundle?){}
            override fun onActivityResumed(a:android.app.Activity){}
            override fun onActivityPaused(a:android.app.Activity){}
            override fun onActivitySaveInstanceState(a:android.app.Activity,b:android.os.Bundle){}
            override fun onActivityDestroyed(a:android.app.Activity){}
        })
    }

    // Coil использует тот же OkHttpClient с cookie-сессией, что и API/видеоплеер,
    // поэтому миниатюры и оригиналы загружаются с авторизацией.
    override fun newImageLoader(): ImageLoader =
        ImageLoader.Builder(this)
            .okHttpClient { session.client }
            .memoryCachePolicy(coil.request.CachePolicy.DISABLED)
            .diskCachePolicy(coil.request.CachePolicy.DISABLED)
            .crossfade(120)
            .build()
}
