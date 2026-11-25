package club.netcraze.phototv

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import java.io.IOException
import java.net.URLEncoder

class ConnectActivity : Activity() {

    private lateinit var session: Session
    private lateinit var inputServer: EditText
    private lateinit var inputLogin: EditText
    private lateinit var inputPassword: EditText
    private lateinit var buttonConnect: Button
    private lateinit var buttonScan: Button
    private lateinit var buttonQr: Button
    private lateinit var buttonManual: Button
    private lateinit var manualBlock: View
    private lateinit var statusText: TextView
    private lateinit var foundList: LinearLayout
    private lateinit var qrImage: ImageView
    private lateinit var pairCode: TextView
    private lateinit var pairHint: TextView

    private var cancelScan: (() -> Unit)? = null
    private var busy = false
    private var serverTouched = false
    private var programmaticEdit = false

    @Volatile
    private var pairingActive = false
    private val pairGeneration=java.util.concurrent.atomic.AtomicInteger()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_connect)

        session = (application as App).session
        inputServer = findViewById(R.id.inputServer)
        inputLogin = findViewById(R.id.inputLogin)
        inputPassword = findViewById(R.id.inputPassword)
        buttonConnect = findViewById(R.id.buttonConnect)
        buttonScan = findViewById(R.id.buttonScan)
        buttonQr = findViewById(R.id.buttonQr)
        buttonManual = findViewById(R.id.buttonManual)
        manualBlock = findViewById(R.id.manualBlock)
        statusText = findViewById(R.id.statusText)
        foundList = findViewById(R.id.foundList)
        qrImage = findViewById(R.id.qrImage)
        pairCode = findViewById(R.id.pairCode)
        pairHint = findViewById(R.id.pairHint)

        inputServer.setText(session.prefillServer)
        inputLogin.setText(session.prefillLogin)

        inputServer.addTextChangedListener(object : TextWatcher {
            override fun afterTextChanged(s: Editable?) {
                if (!programmaticEdit) serverTouched = true
            }
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        })

        inputPassword.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE) connect()
            true
        }

        buttonConnect.setOnClickListener { connect() }
        buttonScan.setOnClickListener { startScan() }
        buttonQr.setOnClickListener { startPairing() }
        buttonManual.setOnClickListener { showManual() }

        // Если логин и пароль уже сохранены — сразу показываем ручную форму.
        if (session.prefillLogin.isNotEmpty()) showManual()
    }

    override fun onStop(){
        stopPairingUi();cancelScan?.invoke();setBusy(false)
        super.onStop()
    }

    override fun onDestroy() {
        pairingActive = false
        pairGeneration.incrementAndGet()
        session.cancelPairing()
        cancelScan?.invoke()
        super.onDestroy()
    }

    private fun showManual() {
        manualBlock.visibility = View.VISIBLE
        inputLogin.requestFocus()
    }

    private fun normalizedServer(): String {
        var url = inputServer.text.toString().trim()
        if (url.isNotEmpty() && !url.startsWith("http://") && !url.startsWith("https://")) url = "http://$url"
        return url.trimEnd('/')
    }

    private fun setBusy(value: Boolean) {
        busy = value
        buttonConnect.isEnabled = !value
        buttonScan.isEnabled = !value
        buttonQr.isEnabled = !value
        buttonManual.isEnabled = !value
    }

    private fun showStatus(text: String, isError: Boolean = true) {
        statusText.text = text
        statusText.setTextColor(getColor(if (isError) R.color.error else R.color.text_dim))
        statusText.visibility = View.VISIBLE
    }

    private fun connect() {
        if (busy) return
        stopPairingUi()
        val server = inputServer.text.toString().trim()
        val login = inputLogin.text.toString().trim()
        val password = inputPassword.text.toString()
        if (server.isEmpty()) {
            showStatus("Укажи адрес сервера")
            inputServer.requestFocus()
            return
        }
        if (login.isEmpty() || password.isEmpty()) {
            showStatus("Введи логин и пароль от аккаунта")
            (if (login.isEmpty()) inputLogin else inputPassword).requestFocus()
            return
        }
        setBusy(true)
        showStatus(getString(R.string.connecting), isError = false)
        try{session.configure(server,login,password)}catch(error:IllegalArgumentException){setBusy(false);showStatus(error.message?:"Неверный адрес");return}
        Thread {
            try {
                session.fetchStatus() // выдаёт CSRF-токен до первого POST
                session.login()
                runOnUiThread {
                    setBusy(false)
                    startActivity(Intent(this, MainActivity::class.java))
                    finish()
                }
            } catch (error: UnauthorizedException) {
                fail(getString(R.string.error_prefix) + (error.message ?: "неверный логин или пароль"))
            } catch (error: ApiException) {
                fail(getString(R.string.error_prefix) + error.message)
            } catch (error: IOException) {
                fail("Сервер недоступен. Проверь адрес и что сервер запущен.")
            }
        }.start()
    }

    // ---------- Вход по QR (пара устройства с телефоном) ----------

    private fun startPairing() {
        if (busy) return
        val server = normalizedServer()
        if (server.isEmpty()) {
            showStatus(getString(R.string.pair_need_server))
            inputServer.requestFocus()
            return
        }
        pairingActive = false
        val generation=pairGeneration.incrementAndGet()
        session.cancelPairing()
        setBusy(true)
        showStatus(getString(R.string.pair_starting), isError = false)
        try{session.configureServer(server)}catch(error:IllegalArgumentException){setBusy(false);showStatus(error.message?:"Неверный адрес");return}
        Thread {
            try {
                session.fetchStatus() // выдаёт CSRF-токен до первого POST
                val pair = session.pairStart()
                val id = pair.getString("id")
                val approve = pair.getString("approve")
                val poll = pair.getString("poll")
                val code = pair.optString("code", "")
                val expires = pair.optLong("expires", 0L)
                val qr = "mira-photos://pair?server=" + URLEncoder.encode(session.baseUrl, "UTF-8") +
                    "&id=" + URLEncoder.encode(id, "UTF-8") +
                    "&secret=" + URLEncoder.encode(approve, "UTF-8")
                if(generation!=pairGeneration.get()||isDestroyed)return@Thread
                pairingActive = true
                runOnUiThread {
                    if(generation!=pairGeneration.get()||isDestroyed)return@runOnUiThread
                    setBusy(false)
                    showPairing(qr, code)
                }
                pollPairing(id, poll, expires,generation)
            } catch (error: ApiException) {
                if(generation!=pairGeneration.get())return@Thread
                pairingActive = false
                fail(getString(R.string.error_prefix) + error.message)
            } catch (error: IOException) {
                if(generation!=pairGeneration.get())return@Thread
                pairingActive = false
                fail("Сервер недоступен. Проверь адрес и что сервер запущен.")
            }
        }.start()
    }

    private fun showPairing(qrContent: String, code: String) {
        val size = (180 * resources.displayMetrics.density).toInt()
        val bitmap = QrCode.render(qrContent, size)
        if (bitmap != null) {
            qrImage.setImageBitmap(bitmap)
            qrImage.visibility = View.VISIBLE
        }
        pairCode.text = code
        pairCode.visibility = if (code.isEmpty()) View.GONE else View.VISIBLE
        pairHint.visibility = View.VISIBLE
        showStatus(getString(R.string.pair_waiting), isError = false)
    }

    private fun stopPairingUi() {
        pairGeneration.incrementAndGet()
        session.cancelPairing()
        pairingActive = false
        qrImage.visibility = View.GONE
        pairCode.visibility = View.GONE
        pairHint.visibility = View.GONE
    }

    private fun pollPairing(id: String, secret: String, expires: Long,generation:Int) {
        while (pairingActive&&generation==pairGeneration.get()&&!isDestroyed) {
            if (expires > 0 && System.currentTimeMillis() / 1000 >= expires) {
                pairingActive = false
                runOnUiThread { showStatus(getString(R.string.pair_expired)) }
                return
            }
            try {
                val result = session.pairPoll(id, secret)
                if(generation!=pairGeneration.get()||isDestroyed)return
                if (result.optBoolean("approved", false)) {
                    // Сервер уже поставил cookie photo_account — проверяем статус и входим.
                    val status = session.fetchStatus()
                    if (!status.optBoolean("authenticated", false)) throw IOException("not authenticated")
                    session.saveAccountName(status.optString("name", ""))
                    pairingActive = false
                    runOnUiThread {
                        startActivity(Intent(this, MainActivity::class.java))
                        finish()
                    }
                    return
                }
            } catch (error: ApiException) {
                if(generation!=pairGeneration.get())return
                if (error.statusCode == 404) {
                    pairingActive = false
                    runOnUiThread { showStatus(getString(R.string.pair_expired)) }
                    return
                }
                // Прочие ошибки сервера — пробуем дальше, пока QR не истёк.
            } catch (error: IOException) {
                // Сеть моргнула — продолжаем опрос до истечения QR.
            }
            try {
                Thread.sleep(2500)
            } catch (_: InterruptedException) {
                return
            }
        }
    }

    private fun fail(message: String) {
        runOnUiThread {
            if(isDestroyed||isFinishing)return@runOnUiThread
            setBusy(false)
            showStatus(message)
        }
    }

    private fun startScan() {
        if (busy) return
        setBusy(true)
        foundList.removeAllViews()
        showStatus(getString(R.string.scanning), isError = false)
        cancelScan = Discovery.scan(
            context = this,
            onResult = { url ->
                runOnUiThread { addFoundServer(url) }
            },
            onDone = { count ->
                runOnUiThread {
                    setBusy(false)
                    if (count == 0 && foundList.childCount == 0) {
                        showStatus(getString(R.string.scan_none))
                    } else {
                        statusText.visibility = View.GONE
                    }
                }
            }
        )
    }

    private fun addFoundServer(url: String) {
        statusText.visibility = View.GONE
        // Найденный сервер сразу подставляем в поле, чтобы не вводить вручную.
        if (!serverTouched) {
            programmaticEdit = true
            inputServer.setText(url.removePrefix("http://").removePrefix("https://"))
            programmaticEdit = false
        }
        val button = Button(this).apply {
            text = "Сервер найден: $url — использовать"
            setOnClickListener {
                programmaticEdit = true
                inputServer.setText(url.removePrefix("http://").removePrefix("https://"))
                programmaticEdit = false
                buttonQr.requestFocus()
            }
        }
        foundList.addView(button)
    }
}
