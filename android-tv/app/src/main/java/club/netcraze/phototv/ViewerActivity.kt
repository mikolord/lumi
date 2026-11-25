package club.netcraze.phototv

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem as ExoMediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import coil.load

@OptIn(UnstableApi::class)
class ViewerActivity : Activity() {

    private lateinit var session: Session
    private lateinit var photo: ImageView
    private lateinit var video: PlayerView
    private lateinit var loading: ProgressBar
    private lateinit var overlay: LinearLayout
    private lateinit var title: TextView
    private lateinit var subtitle: TextView
    private lateinit var videoRow: LinearLayout
    private lateinit var timeCurrent: TextView
    private lateinit var timeTotal: TextView
    private lateinit var videoProgress: ProgressBar

    private var player: ExoPlayer? = null
    private var items: List<MediaItem> = emptyList()
    private var index = 0
    private var overlayVisible = true
    private var baseSubtitle = ""

    // Режим кадра видео: вписать / заполнить / растянуть
    private val resizeModes = intArrayOf(
        AspectRatioFrameLayout.RESIZE_MODE_FIT,
        AspectRatioFrameLayout.RESIZE_MODE_ZOOM,
        AspectRatioFrameLayout.RESIZE_MODE_FILL,
    )
    private val resizeNames = arrayOf("Вписать", "Заполнить", "Растянуть")
    private var resizeIndex = 0

    // Удержание ◀ ▶: ускоряющаяся перемотка видео
    private var seekDir = 0
    private var seekSpeedMs = 2_000L
    private var seeking = false

    private val handler = Handler(Looper.getMainLooper())
    private val hideOverlay = Runnable {
        overlay.animate().alpha(0f).setDuration(220).withEndAction {
            overlay.visibility = View.GONE
        }.start()
        overlayVisible = false
    }
    private val tick = object : Runnable {
        override fun run() {
            updateVideoProgress()
            handler.postDelayed(this, 500)
        }
    }
    private val holdSeek = object : Runnable {
        override fun run() {
            if (seekDir == 0 || !current().isVideo) return
            seeking = true
            seekBy(seekDir * seekSpeedMs)
            seekSpeedMs = (seekSpeedMs * 1.4f).toLong().coerceAtMost(30_000L)
            showOverlay()
            handler.postDelayed(this, 120)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_viewer)

        session = (application as App).session
        photo = findViewById(R.id.photo)
        video = findViewById(R.id.video)
        loading = findViewById(R.id.loading)
        overlay = findViewById(R.id.overlay)
        title = findViewById(R.id.title)
        subtitle = findViewById(R.id.subtitle)
        videoRow = findViewById(R.id.videoRow)
        timeCurrent = findViewById(R.id.timeCurrent)
        timeTotal = findViewById(R.id.timeTotal)
        videoProgress = findViewById(R.id.videoProgress)

        items = ViewerData.items
        index = ViewerData.index.coerceIn(0, (items.size - 1).coerceAtLeast(0))
        if (items.isEmpty()) {
            finish()
            return
        }
        showCurrent()
        showOverlay()
        handler.postDelayed(tick, 500)
    }

    override fun onStart(){super.onStart();if(items.getOrNull(index)?.isHidden==true&&::session.isInitialized&&!session.vaultUnlocked){photo.setImageDrawable(null);releasePlayback();finish()}}

    override fun onStop() {
        player?.pause()
        super.onStop()
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        player?.release()
        player = null
        super.onDestroy()
    }

    private fun current(): MediaItem = items[index]

    private fun showCurrent() {
        val item = current()
        if(item.isHidden)window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)else window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        title.text = formatTakenAt(item.takenAt).ifEmpty { if (item.isVideo) "Видео" else "Фото" }
        baseSubtitle = "${index + 1} / ${items.size}" + (if (item.favorite) " · ♥" else "")
        subtitle.text = baseSubtitle

        if (item.isVideo) {
            photo.visibility = View.GONE
            video.visibility = View.VISIBLE
            videoRow.visibility = View.VISIBLE
            loading.visibility = View.VISIBLE
            play(item)
        } else {
            releasePlayback()
            video.visibility = View.GONE
            videoRow.visibility = View.GONE
            photo.visibility = View.VISIBLE
            loading.visibility = View.VISIBLE
            photo.alpha = 0f
            photo.load(session.mediaUrl(item.previewPath)) {
                listener(
                    onSuccess = { _, _ ->
                        loading.visibility = View.GONE
                        photo.animate().alpha(1f).setDuration(180).start()
                    },
                    onError = { _, _ ->
                        loading.visibility = View.GONE
                        Toast.makeText(this@ViewerActivity, "Не удалось загрузить фото", Toast.LENGTH_SHORT).show()
                    }
                )
            }

        }
    }

    private fun play(item: MediaItem) {
        val instance = player ?: ExoPlayer.Builder(this)
            .setMediaSourceFactory(
                DefaultMediaSourceFactory(this)
                    .setDataSourceFactory(OkHttpDataSource.Factory(session.client))
            )
            .build()
            .also { created ->
                created.addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(playbackState: Int) {
                        if (playbackState == Player.STATE_READY || playbackState == Player.STATE_ENDED) {
                            loading.visibility = View.GONE
                        }
                        if (playbackState == Player.STATE_ENDED) {
                            showOverlay()
                        }
                    }

                    override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                        loading.visibility = View.GONE
                        Toast.makeText(
                            this@ViewerActivity,
                            "Не удалось воспроизвести видео",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                })
                video.player = created
                player = created
            }
        instance.setMediaItem(ExoMediaItem.fromUri(session.mediaUrl(item.originalPath)))
        instance.prepare()
        instance.playWhenReady = true
    }

    private fun releasePlayback() {
        player?.let {
            it.stop()
            it.clearMediaItems()
        }
    }

    private fun next() {
        if (index < items.size - 1) {
            index++
            showCurrent()
        }
    }

    private fun previous() {
        if (index > 0) {
            index--
            showCurrent()
        }
    }

    private fun seekBy(deltaMs: Long) {
        val instance = player ?: return
        val target = (instance.currentPosition + deltaMs).coerceIn(0, instance.duration.coerceAtLeast(0))
        instance.seekTo(target)
        updateVideoProgress()
    }

    private fun togglePlay() {
        val instance = player ?: return
        if (instance.isPlaying) instance.pause() else instance.play()
    }

    private fun cycleResizeMode() {
        if (!current().isVideo) return
        resizeIndex = (resizeIndex + 1) % resizeModes.size
        video.resizeMode = resizeModes[resizeIndex]
        subtitle.text = baseSubtitle + " · Кадр: " + resizeNames[resizeIndex]
        showOverlay()
    }

    private fun updateVideoProgress() {
        val instance = player ?: return
        if (!current().isVideo) return
        val duration = instance.duration
        if (duration > 0) {
            videoProgress.progress = (instance.currentPosition * 1000 / duration).toInt()
            timeCurrent.text = formatDuration(instance.currentPosition / 1000.0)
            timeTotal.text = formatDuration(duration / 1000.0)
        }
    }

    private fun showOverlay() {
        handler.removeCallbacks(hideOverlay)
        overlay.visibility = View.VISIBLE
        overlay.animate().alpha(1f).setDuration(160).start()
        overlayVisible = true
        scheduleHide()
    }

    private fun scheduleHide() {
        handler.removeCallbacks(hideOverlay)
        handler.postDelayed(hideOverlay, 4000)
    }

    private fun toggleOverlay() {
        if (overlayVisible) hideOverlay.run() else showOverlay()
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        when (event.keyCode) {
            KeyEvent.KEYCODE_BACK -> {
                if (event.action == KeyEvent.ACTION_DOWN) finish()
                return true
            }
            KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_DPAD_LEFT -> {
                val dir = if (event.keyCode == KeyEvent.KEYCODE_DPAD_RIGHT) 1 else -1
                when (event.action) {
                    KeyEvent.ACTION_DOWN -> {
                        showOverlay()
                        if (event.repeatCount == 0) {
                            // Короткое нажатие решится на ACTION_UP; удержание запустит перемотку.
                            seekDir = dir
                            seekSpeedMs = 2_000L
                            seeking = false
                            handler.postDelayed(holdSeek, 450)
                        }
                        return true
                    }
                    KeyEvent.ACTION_UP -> {
                        handler.removeCallbacks(holdSeek)
                        val wasSeeking = seeking
                        seekDir = 0
                        seeking = false
                        if (!wasSeeking) {
                            // Быстрое нажатие — листаем к следующему/предыдущему элементу.
                            if (dir > 0) next() else previous()
                        }
                        return true
                    }
                }
                return super.dispatchKeyEvent(event)
            }
            KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER -> {
                if (event.action == KeyEvent.ACTION_DOWN) {
                    showOverlay()
                    if (current().isVideo) togglePlay() else toggleOverlay()
                }
                return true
            }
            KeyEvent.KEYCODE_DPAD_DOWN -> {
                if (event.action == KeyEvent.ACTION_DOWN) cycleResizeMode()
                return true
            }
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> {
                if (event.action == KeyEvent.ACTION_DOWN && current().isVideo) togglePlay()
                return true
            }
        }
        return super.dispatchKeyEvent(event)
    }
}
