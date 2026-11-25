package club.netcraze.phototv

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.*
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.*
import android.provider.Settings
import android.view.*
import android.webkit.*
import android.widget.*
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject
import java.util.concurrent.Executors

/** Mobile uses Lumi's full touch UI plus native Android I/O and durable background work. */
class MobileActivity : Activity() {
    private lateinit var root: android.widget.FrameLayout
    private lateinit var web: WebView
    private lateinit var loading: ProgressBar
    private lateinit var fallback: Button
    private lateinit var auth: MobileAccountStore
    private lateinit var thumbnails: MobileThumbnails
    private lateinit var exports: MobileExport
    private val io=Executors.newSingleThreadExecutor()
    private val main=Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("lumi_mobile",MODE_PRIVATE) }
    private var origin=""
    private var pendingChooser:ValueCallback<Array<Uri>>?=null
    private var permissionRequest:PermissionRequest?=null
    private var fullscreen:View?=null
    private var fullscreenCallback:WebChromeClient.CustomViewCallback?=null
    private var queueDialog:AlertDialog?=null
    private var queueStatus:TextView?=null
    private var lastFinished=-1
    private var syncBusy=false
    private var lastValidated=0L
    private var lastFingerprint=""
    private var pickerAuth=""
    private var chooserAuth=""
    private var chooserOrigin=""
    private var autoInclude=false
    private var observed=false
    private var clearWebHistory=false
    private var rendererDead=false
    private val observer=object:android.database.ContentObserver(main){override fun onChange(selfChange:Boolean){main.removeCallbacks(mediaChanged);main.postDelayed(mediaChanged,5000)}}
    private val mediaChanged=Runnable { if(prefs.getBoolean("auto",false))MobileUploads.enqueue(this) }
    private val poll=object:Runnable{override fun run(){if(isDestroyed)return;synchronizeAccount();refreshQueue();main.postDelayed(this,3000)}}
    override fun onCreate(state:Bundle?) {
        super.onCreate(state)
        pickerAuth=state?.getString("picker_auth").orEmpty()
        auth=MobileAccountStore(this);thumbnails=MobileThumbnails(this);exports=MobileExport(this)
        root=FrameLayout(this).apply{setBackgroundColor(Color.BLACK)}
        web=WebView(this);root.addView(web,FrameLayout.LayoutParams(-1,-1))
        loading=ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal)
        root.addView(loading,FrameLayout.LayoutParams(-1,dp(3),Gravity.TOP))
        fallback=Button(this).apply{text="⋯";textSize=24f;setTextColor(Color.WHITE);background=android.graphics.drawable.GradientDrawable().apply{setColor(0xaa303036.toInt());cornerRadius=dp(24).toFloat()};contentDescription="Настройки Android-приложения";setOnClickListener{showAppSettings()}}
        root.addView(fallback,FrameLayout.LayoutParams(dp(48),dp(48),Gravity.TOP or Gravity.END).apply{topMargin=dp(10);marginEnd=dp(12)})
        setContentView(root)
        with(web.settings){javaScriptEnabled=true;domStorageEnabled=true;allowFileAccess=false;allowContentAccess=true
            @Suppress("DEPRECATION") setAllowFileAccessFromFileURLs(false)
            @Suppress("DEPRECATION") setAllowUniversalAccessFromFileURLs(false)
            mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW;mediaPlaybackRequiresUserGesture=true;setSupportMultipleWindows(false)
            builtInZoomControls=false;displayZoomControls=false;useWideViewPort=true;loadWithOverviewMode=true
            userAgentString=userAgentString+" LumiAndroid/"+BuildConfig.VERSION_NAME
        }
        CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(web,false)
        web.webViewClient=object:WebViewClient(){
            override fun shouldOverrideUrlLoading(view:WebView,request:WebResourceRequest):Boolean {
                if(!request.isForMainFrame)return !MobilePolicy.sameOrigin(origin,request.url.toString())
                if(MobilePolicy.sameOrigin(origin,request.url.toString()))return false
                if(request.hasGesture()&&request.url.scheme in setOf("https","http","mailto"))try{startActivity(Intent(Intent.ACTION_VIEW,request.url))}catch(_:Exception){}
                return true
            }
            override fun onPageStarted(view:WebView,url:String,icon:android.graphics.Bitmap?){loading.visibility=View.VISIBLE;fallback.visibility=View.VISIBLE}
            override fun onPageFinished(view:WebView,url:String){
                loading.visibility=View.GONE
                if(!MobilePolicy.sameOrigin(origin,url))return
                if(WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)){
                    view.evaluateJavascript(assets.open("mobile-native.js").bufferedReader().use{it.readText()},null)
                }
                if(clearWebHistory){view.clearHistory();clearWebHistory=false}
                synchronizeAccount()
            }
            override fun onReceivedError(view:WebView,request:WebResourceRequest,error:WebResourceError){if(request.isForMainFrame&&MobilePolicy.sameOrigin(origin,request.url.toString())){loading.visibility=View.GONE;showServerForm();onboardingError?.text="Не удалось подключиться. Проверь адрес и соединение с сервером."}}
            override fun onReceivedSslError(view:WebView,handler:android.webkit.SslErrorHandler,error:android.net.http.SslError){handler.cancel();if(MobilePolicy.sameOrigin(origin,error.url.orEmpty()))showServerForm();onboardingError?.text="Не удалось проверить сертификат HTTPS. Установи доверенный сертификат на сервере."}
            override fun onRenderProcessGone(view:WebView,detail:RenderProcessGoneDetail):Boolean{rendererDead=true;root.removeView(view);view.destroy();main.post{if(!isDestroyed)recreate()};return true}
            override fun shouldInterceptRequest(view:WebView,request:WebResourceRequest):WebResourceResponse? {
                if(!MobilePolicy.sameOrigin(origin,request.url.toString()))return null
                if(request.method=="POST"&&request.url.path=="/api/account/logout"){auth.clear();thumbnails.cache.clear();MobileUploads.periodic(this@MobileActivity,false)}
                return if(request.method=="GET")thumbnails.response(request.url.toString())else null
            }
        }
        web.webChromeClient=object:WebChromeClient(){
            override fun onProgressChanged(view:WebView,value:Int){loading.progress=value}
            override fun onShowFileChooser(view:WebView,callback:ValueCallback<Array<Uri>>,params:FileChooserParams):Boolean {
                pendingChooser?.onReceiveValue(null);pendingChooser=callback;chooserOrigin=origin;chooserAuth=MobilePolicy.fingerprint(origin,CookieManager.getInstance().getCookie(origin).orEmpty())
                val types=params.acceptTypes.filter{it.isNotBlank()}.toTypedArray()
                val intent=Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(if(types.size==1)types[0]else "*/*")
                    .putExtra(Intent.EXTRA_ALLOW_MULTIPLE,params.mode==FileChooserParams.MODE_OPEN_MULTIPLE)
                if(types.size>1)intent.putExtra(Intent.EXTRA_MIME_TYPES,types)
                return try{startActivityForResult(intent,100);true}catch(_:Exception){pendingChooser=null;callback.onReceiveValue(null);true}
            }
            override fun onPermissionRequest(request:PermissionRequest){main.post{
                if(request.origin.toString().trimEnd('/')!=origin||PermissionRequest.RESOURCE_VIDEO_CAPTURE !in request.resources||!hasWindowFocus()){request.deny();return@post}
                permissionRequest?.deny();permissionRequest=request
                if(checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED){request.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE));permissionRequest=null}
                else requestPermissions(arrayOf(Manifest.permission.CAMERA),103)
            }}
            override fun onPermissionRequestCanceled(request:PermissionRequest){if(permissionRequest===request)permissionRequest=null}
            override fun onShowCustomView(view:View,callback:CustomViewCallback){if(fullscreen!=null){callback.onCustomViewHidden();return};fullscreen=view;fullscreenCallback=callback;root.addView(view,FrameLayout.LayoutParams(-1,-1));fallback.visibility=View.GONE;window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)}
            override fun onHideCustomView(){closeFullscreen()}
        }
        web.setDownloadListener { url,_,disposition,mime,_ ->
            if(MobilePolicy.sameOrigin(origin,url)){
                val name=URLUtil.guessFileName(url,disposition,mime)
                web.evaluateJavascript("window.__lumiSaveUrl?.(${JSONObject.quote(url)},${JSONObject.quote(name)})",null)
            }
        }
        origin=prefs.getString("server","").orEmpty()
        if(origin.isEmpty())showServerForm()else CookieManager.getInstance().setCookie(origin,"photo_vault=; Path=/; Max-Age=0; HttpOnly"+(if(origin.startsWith("https://"))"; Secure"else "")){if(!isDestroyed)loadServer(origin)}
    }
    private fun dp(value:Int)=(value*resources.displayMetrics.density).toInt()
    private fun toast(text:String){Toast.makeText(this,text,Toast.LENGTH_LONG).show()}
    override fun onStart(){super.onStart();main.post(poll);registerMediaObserver()}
    override fun onStop(){
        main.removeCallbacks(poll);permissionRequest?.deny();permissionRequest=null
        if(observed){contentResolver.unregisterContentObserver(observer);observed=false}
        if(!rendererDead){web.evaluateJavascript("window.PhotoVault?.lock?.()",null);if(window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE!=0)web.visibility=View.INVISIBLE};if(origin.isNotEmpty())CookieManager.getInstance().setCookie(origin,"photo_vault=; Path=/; Max-Age=0; HttpOnly"+(if(origin.startsWith("https://"))"; Secure"else ""));CookieManager.getInstance().flush();super.onStop()
    }
    override fun onDestroy(){main.removeCallbacksAndMessages(null);pendingChooser?.onReceiveValue(null);exports.close();if(!rendererDead)web.destroy();io.shutdownNow();super.onDestroy()}
    override fun onResume(){super.onResume();if(!rendererDead){web.onResume();if(web.visibility==View.INVISIBLE)web.evaluateJavascript("window.PhotoVault?.lock?.()",{if(!isDestroyed)web.visibility=View.VISIBLE})}}
    override fun onPause(){if(!rendererDead)web.onPause();super.onPause()}
    private fun registerMediaObserver(){if(!observed&&MobileUploads.hasMedia(this)){contentResolver.registerContentObserver(android.provider.MediaStore.Files.getContentUri("external"),true,observer);observed=true}}
    private fun loadServer(server:String){
        clearWebHistory=true;origin=server;prefs.edit().putString("server",server).apply()
        if(WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)){
            WebViewCompat.removeWebMessageListener(web,"LumiNative")
            WebViewCompat.addWebMessageListener(web,"LumiNative",setOf(server)){_,message,source,isMainFrame,reply ->
                if(!isMainFrame||source.toString().trimEnd('/')!=origin)return@addWebMessageListener
                try{
                    val payload=message.data?:return@addWebMessageListener;if(payload.length>100000)return@addWebMessageListener;val json=JSONObject(payload);val id=json.optString("id");val op=json.optString("op")
                    fun answer(value:JSONObject=JSONObject()){if(!isDestroyed)reply.postMessage(value.put("id",id).toString())}
                    when(op){
                        "ready"->{fallback.visibility=View.GONE;synchronizeAccount();answer()}
                        "settings"->{showAppSettings();answer()}
                        "queue"->{showQueue();answer()}
                        "scan-tv"->{
                            val intent=com.google.zxing.integration.android.IntentIntegrator(this@MobileActivity).setDesiredBarcodeFormats(listOf(com.google.zxing.integration.android.IntentIntegrator.QR_CODE)).setOrientationLocked(false).setBeepEnabled(false).setPrompt("Наведи камеру на QR-код телевизора").createScanIntent()
                            startActivityForResult(intent,106);answer()
                        }
                        "secure"->{if(json.optBoolean("value"))window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE);answer()}
                        "theme"->{val light=json.optBoolean("light");prefs.edit().putBoolean("light",light).apply();window.statusBarColor=if(light)Color.WHITE else Color.BLACK;window.navigationBarColor=window.statusBarColor;window.decorView.systemUiVisibility=if(light)View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or (if(Build.VERSION.SDK_INT>=26)View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR else 0)else 0;answer()}
                        else->if(op.startsWith("export-")||op=="share-text")exports.handle(json){ result->main.post{answer(result)} }
                    }
                }catch(_:Exception){}
            }
        }
        web.loadUrl(server+"/")
    }
    private var onboarding:View?=null
    private var onboardingError:TextView?=null
    private fun showServerForm(){
        onboarding?.let{root.removeView(it)}
        val container=FrameLayout(this).apply{
            background=android.graphics.drawable.GradientDrawable(android.graphics.drawable.GradientDrawable.Orientation.TL_BR,intArrayOf(0xff090d19.toInt(),0xff15294b.toInt(),0xff092f3d.toInt()))
        }
        val scroll=ScrollView(this).apply{isFillViewport=true}
        val center=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;gravity=Gravity.CENTER;setPadding(dp(28),dp(32),dp(28),dp(32))}
        val content=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;gravity=Gravity.CENTER_HORIZONTAL}
        val width=minOf(resources.displayMetrics.widthPixels-dp(56),dp(500))
        content.addView(ImageView(this).apply{setImageResource(R.drawable.lumi_logo_art);contentDescription="lumi";scaleType=ImageView.ScaleType.FIT_CENTER;clipToOutline=true;background=android.graphics.drawable.GradientDrawable().apply{setColor(Color.WHITE);cornerRadius=dp(24).toFloat()}},LinearLayout.LayoutParams(dp(116),dp(116)).apply{bottomMargin=dp(22)})
        content.addView(TextView(this).apply{text="Твоя фототека.\nВсегда рядом.";textSize=32f;gravity=Gravity.CENTER;setTextColor(Color.WHITE);typeface=android.graphics.Typeface.create("sans-serif-medium",android.graphics.Typeface.NORMAL)},LinearLayout.LayoutParams(-1,-2))
        content.addView(TextView(this).apply{text="Подключись к своему серверу Lumi";textSize=16f;gravity=Gravity.CENTER;setTextColor(0xffb8c9df.toInt());setPadding(0,dp(16),0,dp(28))})
        val input=EditText(this).apply{
            hint="https://photos.example.com";inputType=android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI;setText(origin);isSingleLine=true;textSize=16f
            setTextColor(Color.WHITE);setHintTextColor(0xff90a3ba.toInt());setPadding(dp(18),0,dp(18),0)
            background=android.graphics.drawable.GradientDrawable().apply{setColor(0x552b4163);cornerRadius=dp(18).toFloat();setStroke(dp(1),0x667a96b8)}
        }
        content.addView(input,LinearLayout.LayoutParams(-1,dp(60)))
        val error=TextView(this).apply{setTextColor(0xffffa3ac.toInt());setPadding(0,dp(10),0,dp(10));textSize=14f}
        onboardingError=error
        content.addView(error,LinearLayout.LayoutParams(-1,-2))
        val connect=Button(this).apply{
            text="Подключиться";isAllCaps=false;textSize=17f;setTextColor(Color.WHITE)
            background=android.graphics.drawable.GradientDrawable().apply{setColor(0xff168cff.toInt());cornerRadius=dp(18).toFloat()}
        }
        content.addView(connect,LinearLayout.LayoutParams(-1,dp(56)))
        fun submit(){try{val next=MobilePolicy.origin(input.text.toString());if(next!=origin){auth.clear();thumbnails.cache.clear();MobileUploads.periodic(this,false);web.clearHistory()};root.removeView(container);onboarding=null;loadServer(next)}catch(e:Exception){error.text=e.message}}
        connect.setOnClickListener{submit()}
        input.imeOptions=android.view.inputmethod.EditorInfo.IME_ACTION_GO;input.setOnEditorActionListener{_,action,_->if(action==android.view.inputmethod.EditorInfo.IME_ACTION_GO){submit();true}else false}
        if(origin.isNotEmpty())content.addView(Button(this).apply{text="Вернуться в медиатеку";isAllCaps=false;setTextColor(Color.WHITE);background=null;setOnClickListener{root.removeView(container);onboarding=null}})
        content.addView(TextView(this).apply{text="lumi ${BuildConfig.VERSION_NAME} · Android";textSize=13f;setTextColor(0xff8ba1bb.toInt());setPadding(0,dp(30),0,0)})
        center.addView(content,LinearLayout.LayoutParams(width,-2));scroll.addView(center,FrameLayout.LayoutParams(-1,-1));container.addView(scroll)
        onboarding=container;root.addView(container,FrameLayout.LayoutParams(-1,-1));fallback.visibility=View.GONE
    }
    private fun synchronizeAccount(force:Boolean=false){
        if(origin.isEmpty()||syncBusy)return
        val server=origin;val cookie=MobilePolicy.cookieHeader(CookieManager.getInstance().getCookie(server).orEmpty())
        val fingerprint=MobilePolicy.fingerprint(server,cookie)
        if(fingerprint.isEmpty()){if(auth.read()!=null){auth.clear();thumbnails.cache.clear();MobileUploads.periodic(this,false)};return}
        if(!force&&fingerprint==lastFingerprint&&SystemClock.elapsedRealtime()-lastValidated<60000)return
        lastFingerprint=fingerprint;lastValidated=SystemClock.elapsedRealtime()
        syncBusy=true
        io.execute{
            try{
                val state=MobileApi.get(MobileAccount(server,cookie,"",""),"/api/account/status")
                if(state.optBoolean("authenticated")){
                    val account=MobileAccount(server,cookie,state.getString("id"),state.optString("name"))
                    main.post{if(!isDestroyed&&origin==server&&MobilePolicy.fingerprint(server,CookieManager.getInstance().getCookie(server).orEmpty())==fingerprint){
                        val previous=auth.read();if(previous?.queueKey!=account.queueKey){prefs.edit().putBoolean("auto",false).apply();MobileUploads.periodic(this,false);thumbnails.cache.clear()}
                        auth.write(account);MobileUploads.enqueue(this)
                    }}
                }else main.post{if(!isDestroyed&&origin==server&&auth.read()!=null&&MobilePolicy.fingerprint(server,CookieManager.getInstance().getCookie(server).orEmpty())==fingerprint){auth.clear();thumbnails.cache.clear();MobileUploads.periodic(this,false);queueDialog?.dismiss();web.reload()}}
            }catch(_:Exception){}finally{main.post{syncBusy=false}}
        }
    }
    private val uiContext:Context get()=android.view.ContextThemeWrapper(this,if(prefs.getBoolean("light",false))R.style.Theme_Lumi_Mobile else R.style.Theme_Lumi_Mobile_Dark)
    private fun showAppSettings(){
        val labels=arrayOf("Загрузка и автозагрузка","Проверить обновление приложения","Очистить кэш миниатюр","Сменить сервер")
        AlertDialog.Builder(uiContext).setTitle("lumi ${BuildConfig.VERSION_NAME}").setItems(labels){_,which ->when(which){
            0->showQueue();1->checkUpdate();2->{io.execute{thumbnails.cache.clear();main.post{toast("Кэш миниатюр очищен")}}};3->showServerForm()
        }}.setNegativeButton("Закрыть",null).show()
    }
    private fun activeAccount():MobileAccount?=auth.read()?.takeIf{it.origin==origin&&it.fingerprint==MobilePolicy.fingerprint(origin,CookieManager.getInstance().getCookie(origin).orEmpty())}
    private fun showQueue(){
        val account=activeAccount();if(account==null){
            val expected=MobilePolicy.fingerprint(origin,CookieManager.getInstance().getCookie(origin).orEmpty())
            if(expected.isEmpty()){toast("Сначала войди в аккаунт Lumi");return}
            synchronizeAccount(true)
            val wait=AlertDialog.Builder(uiContext).setMessage("Подключаем очередь к аккаунту…").setCancelable(true).show()
            var count=0
            main.postDelayed(object:Runnable{override fun run(){if(isDestroyed||!wait.isShowing)return;if(expected!=MobilePolicy.fingerprint(origin,CookieManager.getInstance().getCookie(origin).orEmpty())){wait.dismiss();toast("Аккаунт изменился");return};if(activeAccount()!=null){wait.dismiss();showQueue()}else if(++count>=40){wait.dismiss();toast("Не удалось подключить очередь. Повтори позже")}else main.postDelayed(this,250)}},250)
            return
        }
        queueDialog?.dismiss()
        val box=LinearLayout(uiContext).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(22),0,dp(22),dp(12))}
        queueStatus=TextView(uiContext).apply{textSize=15f;setPadding(0,dp(8),0,dp(16))};box.addView(queueStatus)
        fun button(label:String,action:()->Unit){box.addView(Button(uiContext).apply{text=label;isAllCaps=false;setOnClickListener{action()}})}
        button("Добавить фотографии и видео"){pickUploads()}
        val wifi=Switch(uiContext).apply{text="Только Wi‑Fi";isChecked=prefs.getBoolean("wifi",true);setPadding(0,dp(12),0,dp(12));setOnCheckedChangeListener{_,value->prefs.edit().putBoolean("wifi",value).apply();MobileUploads.periodic(this@MobileActivity,prefs.getBoolean("auto",false));MobileUploads.enqueue(this@MobileActivity)}}
        box.addView(wifi)
        val camera=Switch(uiContext).apply{text="Автозагрузка: только Камера";isChecked=prefs.getBoolean("camera_only",true);setPadding(0,dp(12),0,dp(12));setOnCheckedChangeListener{_,value->prefs.edit().putBoolean("camera_only",value).apply();if(prefs.getBoolean("auto",false))MobileUploads.enqueue(this@MobileActivity)}};box.addView(camera)
        val auto=Switch(uiContext).apply{text="Автозагрузка";isChecked=prefs.getBoolean("auto",false);setPadding(0,dp(12),0,dp(12))}
        auto.setOnCheckedChangeListener{_,value->
            if(!value){prefs.edit().putBoolean("auto",false).apply();MobileUploads.periodic(this,false)}
            else{auto.isChecked=false;queueDialog?.dismiss();AlertDialog.Builder(uiContext).setTitle("Автозагрузка фотографий").setMessage("Загружать только новые снимки или также существующую медиатеку?")
                .setPositiveButton("Только новые"){_,_->enableAuto(false)}.setNeutralButton("Все существующие"){_,_->enableAuto(true)}.setNegativeButton("Отмена",null).show()}
        };box.addView(auto)
        box.addView(TextView(uiContext).apply{text="Android выбирает время фоновой проверки. При ограниченном доступе загружаются только разрешённые фотографии и видео.";textSize=13f;setPadding(0,dp(8),0,dp(10))})
        button(if(prefs.getBoolean("paused",false))"Продолжить загрузку"else "Приостановить загрузку"){
            prefs.edit().putBoolean("paused",!prefs.getBoolean("paused",false)).apply();if(!prefs.getBoolean("paused",false))MobileUploads.enqueue(this);showQueue()
        }
        button("Повторить ошибки"){MobileUploadStore(this).use{it.retry(account.queueKey)};MobileUploads.enqueue(this);refreshQueue()}
        button("Убрать ошибки"){MobileUploadStore(this).use{it.clearErrors(account.queueKey)};refreshQueue()}
        button("Убрать завершённые"){MobileUploadStore(this).use{it.clearFinished(account.queueKey)};refreshQueue()}
        queueDialog=AlertDialog.Builder(uiContext).setTitle("Загрузка · ${account.name}").setView(ScrollView(this).apply{addView(box)}).setNegativeButton("Закрыть",null).create()
        queueDialog?.setOnDismissListener{queueDialog=null;queueStatus=null};queueDialog?.show();refreshQueue()
    }
    private fun refreshQueue(){
        val account=activeAccount()?:run{queueDialog?.dismiss();return}
        MobileUploadStore(this).use{db->
            val counts=db.counts(account.queueKey);val done=(counts["done"]?:0)+(counts["duplicate"]?:0)
            if(lastFinished>=0&&done!=lastFinished&&MobilePolicy.sameOrigin(origin,web.url.orEmpty()))web.evaluateJavascript("window.PhotoVault?.refresh?.()",null)
            lastFinished=done
            if(queueStatus!=null){val errors=db.list(account.queueKey,errorsOnly=true).take(4).joinToString("\n"){it.name+": "+it.error}
                val active=if(prefs.getBoolean("paused",false))"Приостановлено\n\n"else if(prefs.getString("active_owner","")==account.queueKey)"${prefs.getString("upload_phase","")}\n${prefs.getString("upload_file","")} · ${prefs.getInt("upload_percent",0)}%\n\n"else ""
                queueStatus?.text=active+"Загружено: $done · повторов: ${counts["duplicate"]?:0}\nВ очереди: ${counts["pending"]?:0} · ошибок: ${counts["error"]?:0}"+if(errors.isEmpty())""else "\n\n$errors"}
        }
    }
    private fun pickUploads(){
        pickerAuth=activeAccount()?.fingerprint.orEmpty();if(pickerAuth.isEmpty()){toast("Войди в аккаунт");return}
        val intent=Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,arrayOf("image/*","video/*"))
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        startActivityForResult(intent,101)
    }
    private fun enableAuto(include:Boolean){
        autoInclude=include
        if(MobileUploads.hasMedia(this))finishEnableAuto()else requestPermissions(MobileUploads.mediaPermissions(),102)
    }
    private fun finishEnableAuto(){
        val account=activeAccount()?:return
        if(!MobileUploads.hasMedia(this)){toast("Нужен доступ к фотографиям и видео");return}
        prefs.edit().putBoolean("auto",true).putString("auto_owner",account.queueKey).putLong("auto_since",if(autoInclude)0 else System.currentTimeMillis()/1000).apply()
        requestNotifications();registerMediaObserver();MobileUploads.periodic(this,true);showQueue()
    }
    private fun requestNotifications(){if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),104)}
    @Deprecated("Android compatibility") override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==100){
            val same=chooserOrigin==origin&&chooserAuth==MobilePolicy.fingerprint(origin,CookieManager.getInstance().getCookie(origin).orEmpty())
            pendingChooser?.onReceiveValue(if(resultCode==RESULT_OK&&same)data?.let{uris(it).filter{uri->uri.scheme=="content"}.toTypedArray()}else null);pendingChooser=null
            if(resultCode==RESULT_OK&&!same)toast("Аккаунт изменился. Выбери файл повторно")
        }
        if(requestCode==101&&resultCode==RESULT_OK&&data!=null){
            val account=activeAccount()?:return;if(account.fingerprint!=pickerAuth){toast("Аккаунт изменился. Выбери файлы повторно");return};pickerAuth="";val selected=uris(data).distinct();requestNotifications()
            io.execute{var added=0;var failed=0;MobileUploadStore(this).use{db->for(uri in selected)try{
                contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION)
                if(db.add(this,uri,account.queueKey))added++
            }catch(error:Exception){failed++;db.failure(uri.toString(),account.queueKey,error.message?:"Файл недоступен. Выбери его повторно")}}
                main.post{if(!isDestroyed&&auth.current(account.fingerprint)){MobileUploads.enqueue(this);toast("Добавлено: $added"+if(failed>0)". Недоступно: $failed" else "");showQueue()}}
            }
        }
        if(requestCode==106&&resultCode==RESULT_OK){
            val code=data?.getStringExtra("SCAN_RESULT")?.takeIf{it.length<16000}
            if(code!=null&&MobilePolicy.sameOrigin(origin,web.url.orEmpty()))web.evaluateJavascript("""(()=>{const form=document.querySelector('#pairManual');if(!form)return;const input=form.querySelector('[name=qr]');input.value=${JSONObject.quote(code)};form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));})()""",null)
        }
        exports.activityResult(requestCode,resultCode,data)
    }
    private fun uris(data:Intent):List<Uri> = data.clipData?.let { clip->(0 until clip.itemCount).map{clip.getItemAt(it).uri} }?:listOfNotNull(data.data)
    override fun onSaveInstanceState(state:Bundle){state.putString("picker_auth",pickerAuth);super.onSaveInstanceState(state)}
    override fun onRequestPermissionsResult(code:Int,permissions:Array<out String>,grants:IntArray){
        super.onRequestPermissionsResult(code,permissions,grants)
        if(code==102)finishEnableAuto()
        if(code==103){val request=permissionRequest;permissionRequest=null;if(request!=null){if(grants.firstOrNull()==PackageManager.PERMISSION_GRANTED&&hasWindowFocus())request.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))else request.deny()}}
    }
    private fun checkUpdate(){
        toast("Проверяем обновления…")
        io.execute{try{val info=Updater.check(this);main.post{if(isDestroyed)return@post;if(info==null)toast("Установлена последняя версия")else AlertDialog.Builder(uiContext).setTitle("lumi ${info.versionName}").setMessage(info.notes).setPositiveButton("Скачать"){_,_->downloadUpdate(info)}.setNegativeButton("Позже",null).show()}}
        catch(_:Exception){main.post{toast("Не удалось проверить обновления. Повтори позже")}}}
    }
    private fun downloadUpdate(info:Updater.Info){
        val progress=ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal).apply{max=100}
        val dialog=AlertDialog.Builder(uiContext).setTitle("Обновление ${info.versionName}").setView(progress).setCancelable(false).show()
        io.execute{try{val file=Updater.download(this,info){value->main.post{progress.progress=value}}
            main.post{dialog.dismiss();if(!isDestroyed)installUpdate(file)}
        }catch(e:Exception){main.post{dialog.dismiss();toast((e as? UpdateFailure)?.message?:"Не удалось скачать обновление")}}}
    }
    private fun installUpdate(file:java.io.File){
        if(!packageManager.canRequestPackageInstalls()){
            AlertDialog.Builder(uiContext).setTitle("Разрешение на установку").setMessage("Разреши Lumi устанавливать обновления в настройках Android. Затем нажми «Установить».")
                .setPositiveButton("Настройки"){_,_->try{startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:$packageName")))}catch(_:Exception){toast("Открой разрешение в настройках Android")}}
                .setNeutralButton("Установить"){_,_->installUpdate(file)}.setNegativeButton("Позже",null).show();return
        }
        try{val uri=androidx.core.content.FileProvider.getUriForFile(this,"${BuildConfig.APPLICATION_ID}.fileprovider",file)
            startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).apply{clipData=ClipData.newRawUri("lumi",uri)})
        }catch(_:Exception){toast("Не удалось открыть установщик Android")}
    }
    private fun closeFullscreen(){fullscreen?.let{root.removeView(it)};fullscreen=null;fullscreenCallback?.onCustomViewHidden();fullscreenCallback=null;window.clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)}
    @Deprecated("Android compatibility") override fun onBackPressed(){
        if(onboarding!=null&&origin.isNotEmpty()){root.removeView(onboarding);onboarding=null;return}
        if(fullscreen!=null){closeFullscreen();return}
        web.evaluateJavascript("""(()=>{const modal=[...document.querySelectorAll('[role=dialog],[role=menu]')].some(el=>el.getClientRects().length>0);const viewer=document.querySelector('#viewer:not(.hidden)');if(modal||viewer){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;}if(typeof screen!=='undefined'&&screen==='collectionScreen'&&typeof closeAlbum==='function'){closeAlbum();return true;}return false;})()"""){value->if(value!="true"){if(web.canGoBack())web.goBack()else AlertDialog.Builder(uiContext).setMessage("Закрыть Lumi?").setPositiveButton("Закрыть"){_,_->finish()}.setNegativeButton("Остаться",null).show()}}
    }
}
