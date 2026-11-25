package club.netcraze.phototv

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import coil.load
import java.io.IOException

class MainActivity : Activity() {

    private enum class Screen { LIBRARY, COLLECTIONS, ITEMS, PEOPLE, PROFILE }

    private lateinit var session: Session
    private lateinit var tabs: RecyclerView
    private lateinit var grid: RecyclerView
    private lateinit var progress: ProgressBar
    private lateinit var emptyText: TextView
    private lateinit var updateBanner: TextView
    private lateinit var headerRow: View
    private lateinit var headerBack: Button
    private lateinit var headerTitle: TextView
    private lateinit var profileView: View
    private lateinit var profileInfo: TextView
    private lateinit var gridSizeButton: TextView
    private lateinit var scrollBubble: TextView
    private lateinit var dateTimeline: TvTimelinePanel
    private var returnPosition=0
    private var returnAdapter: RecyclerView.Adapter<*>?=null

    private fun rememberGridPosition(position:Int){returnPosition=position;returnAdapter=grid.adapter}
    private fun restoreGridFocus(){
        val count=grid.adapter?.itemCount?:0;if(count==0){tabs.requestFocus();return}
        val position=(if(returnAdapter===grid.adapter)returnPosition else (grid.layoutManager as? GridLayoutManager)?.findFirstVisibleItemPosition()?:0).coerceIn(0,count-1)
        val attached=grid.findViewHolderForAdapterPosition(position)
        if(attached!=null){attached.itemView.requestFocus();return}
        (grid.layoutManager as? GridLayoutManager)?.scrollToPositionWithOffset(position,grid.paddingTop)
        grid.post{val holder=grid.findViewHolderForAdapterPosition(position);if(holder!=null)holder.itemView.requestFocus()else grid.post{grid.findViewHolderForAdapterPosition(position)?.itemView?.requestFocus()}}
    }
    private fun focusNavigation(position:Int){
        rememberGridPosition(position)
        val selected=tabsAdapter.selected;tabs.scrollToPosition(selected)
        val target=tabs.findViewHolderForAdapterPosition(selected)?.itemView
        if(target!=null)target.requestFocus()else tabs.post{(tabs.findViewHolderForAdapterPosition(selected)?.itemView?:gridSizeButton.takeIf{it.isShown})?.requestFocus()}
    }
    private fun openDateTimeline(position:Int){
        rememberGridPosition(position)
        bubbleHandler.removeCallbacks(hideBubble);scrollBubble.visibility=View.GONE
        dateTimeline.show(mediaAdapter.currentList.toList(),position)
    }

    private val bubbleHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val hideBubble = Runnable { scrollBubble.visibility = View.GONE }

    private lateinit var mediaAdapter: MediaAdapter
    private lateinit var cardAdapter: CardAdapter
    private lateinit var tabsAdapter: TabsAdapter

    private var library: Library? = null
    private var people: List<Person> = emptyList()
    private var screen = Screen.LIBRARY
    private var fromPeople = false
    private var loading = false
    private var updateDownloading = false
    private var openedCard: Card? = null
    private var pendingScrollState: android.os.Parcelable? = null
    private var knownVaultGeneration=0L
    private fun regularItems()=library?.regularItems.orEmpty()
    override fun onStart(){super.onStart();if(::session.isInitialized&&::grid.isInitialized&&knownVaultGeneration!=session.vaultGeneration){knownVaultGeneration=session.vaultGeneration;library=library?.let{it.copy(items=it.items.filter{item->!item.isHidden},hasLockedHidden=it.hasLockedHidden||it.items.any{item->item.isHidden})};if(screen==Screen.ITEMS&&openedCard?.id=="hidden")showCollections();loadLibrary()}}
    override fun onStop(){if(::dateTimeline.isInitialized)dateTimeline.dismiss(false);super.onStop()}
    override fun onDestroy(){if(::dateTimeline.isInitialized)dateTimeline.dismiss(false);bubbleHandler.removeCallbacksAndMessages(null);super.onDestroy()}
    private fun updateProfileInfo(){
        profileInfo.text="Аккаунт: ${session.accountName}\nСервер: ${session.baseUrl}\nВерсия приложения: ${BuildConfig.VERSION_NAME}"
        Thread{val megabytes=session.thumbnails.sizeBytes()/1048576.0;runOnUiThread{if(!isDestroyed&&screen==Screen.PROFILE)findViewById<TextView>(R.id.cacheInfo).text="Кэш миниатюр: %.1f МБ из 256 МБ\nСохраняется на телевизоре при просмотре".format(megabytes)}}.start()
    }

    // Размер сетки фото: 0 — очень мелкий, 1 — мелкий, 2 — средний, 3 — крупный.
    // Карточки альбомов всегда стандартного размера (CARD_SPAN / CARD_HEIGHT_DP).
    private val gridSpans = intArrayOf(9, 7, 5, 3)
    private val gridHeights = intArrayOf(88, 120, 170, 230)
    private val gridLabels = intArrayOf(
        R.string.grid_view_tiny,
        R.string.grid_view_small,
        R.string.grid_view_medium,
        R.string.grid_view_large,
    )
    private val cardSpan = 3
    private val cardHeightDp = 170
    private var gridSize = 2

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = (application as App).session
        if (!session.hasSession()) {
            startActivity(Intent(this, ConnectActivity::class.java))
            finish()
            return
        }
        setContentView(R.layout.activity_main)

        tabs = findViewById(R.id.tabs)
        grid = findViewById(R.id.grid)
        progress = findViewById(R.id.progress)
        emptyText = findViewById(R.id.emptyText)
        updateBanner = findViewById(R.id.updateBanner)
        headerRow = findViewById(R.id.headerRow)
        headerBack = findViewById(R.id.headerBack)
        headerTitle = findViewById(R.id.headerTitle)
        profileView = findViewById(R.id.profileView)
        profileInfo = findViewById(R.id.profileInfo)
        gridSizeButton = findViewById(R.id.gridSizeButton)
        scrollBubble = findViewById(R.id.scrollBubble)
        dateTimeline=TvTimelinePanel(this,grid.parent as android.widget.FrameLayout,{position->
            rememberGridPosition(position)
            (grid.layoutManager as? GridLayoutManager)?.scrollToPositionWithOffset(position,grid.paddingTop)
            grid.post{restoreGridFocus();updateScrollBubble()}
        },::restoreGridFocus)

        grid.addOnScrollListener(object : RecyclerView.OnScrollListener() {
            override fun onScrolled(rv: RecyclerView, dx: Int, dy: Int) {
                if (dy != 0) updateScrollBubble()
            }
        })

        val uiPrefs = getSharedPreferences("photo_tv_ui", MODE_PRIVATE)
        gridSize = if (uiPrefs.contains("gridSize4")) {
            uiPrefs.getInt("gridSize4", 2).coerceIn(0, 3)
        } else {
            // Миграция со старой трёхрежимной шкалы (мелкий/средний/крупный).
            (uiPrefs.getInt("gridSize", 1) + 1).coerceIn(0, 3).also {
                uiPrefs.edit().putInt("gridSize4", it).apply()
            }
        }
        grid.layoutManager = GridLayoutManager(this, gridSpans[gridSize])

        mediaAdapter = MediaAdapter { item -> openViewer(item) }
        cardAdapter = CardAdapter(session) { card -> openCard(card) }
        grid.adapter = mediaAdapter

        gridSizeButton.setOnClickListener {
            gridSize = (gridSize + 1) % 4
            uiPrefs.edit().putInt("gridSize4", gridSize).apply()
            applyGridSize()
        }
        applyGridSize()

        tabs.layoutManager = LinearLayoutManager(this, LinearLayoutManager.HORIZONTAL, false)
        tabsAdapter = TabsAdapter { position -> onTab(position) }
        tabs.adapter = tabsAdapter
        tabsAdapter.submit(
            listOf(
                getString(R.string.tab_library),
                getString(R.string.tab_collections),
                getString(R.string.tab_profile),
            )
        )

        headerBack.setOnClickListener { goBack() }
        findViewById<Button>(R.id.profileRefresh).setOnClickListener {
            loadLibrary()
            checkUpdates()
        }
        findViewById<Button>(R.id.profileUpdate).setOnClickListener { checkUpdates(showFeedback = true) }
        findViewById<Button>(R.id.profileLogout).setOnClickListener { logout() }

        findViewById<Button>(R.id.profileClearCache).setOnClickListener{button->
            button.isEnabled=false;findViewById<TextView>(R.id.cacheInfo).text="Очищаем кэш…"
            Thread{session.thumbnails.clear();runOnUiThread{if(!isDestroyed){button.isEnabled=true;updateProfileInfo()}}}.start()
        }
        loadLibrary()
        checkUpdates()
    }

    override fun onBackPressed() {
        if(::dateTimeline.isInitialized&&dateTimeline.isOpen){dateTimeline.dismiss(true);return}
        if (screen == Screen.LIBRARY) super.onBackPressed() else goBack()
    }

    // ---------- Быстрая прокрутка ----------

    override fun dispatchKeyEvent(event: android.view.KeyEvent): Boolean {
        if(!::grid.isInitialized)return super.dispatchKeyEvent(event)
        if(::dateTimeline.isInitialized&&dateTimeline.isOpen)return super.dispatchKeyEvent(event)
        if(event.action==KeyEvent.ACTION_DOWN&&event.keyCode==KeyEvent.KEYCODE_DPAD_DOWN&&event.repeatCount==0&&grid.visibility==View.VISIBLE&&(tabs.hasFocus()||gridSizeButton.hasFocus())){restoreGridFocus();return true}
        val focused=currentFocus
        val child=focused?.let{grid.findContainingItemView(it)}
        if(event.action==KeyEvent.ACTION_DOWN&&child!=null&&grid.visibility==View.VISIBLE&&(event.keyCode==KeyEvent.KEYCODE_DPAD_LEFT||event.keyCode==KeyEvent.KEYCODE_DPAD_RIGHT)){
            val lm=grid.layoutManager as? GridLayoutManager
            val position=grid.getChildAdapterPosition(child)
            if(lm!=null&&position!=RecyclerView.NO_POSITION){
                val column=lm.spanSizeLookup.getSpanIndex(position,lm.spanCount);val span=lm.spanSizeLookup.getSpanSize(position);val direction=if(event.keyCode==KeyEvent.KEYCODE_DPAD_LEFT)-1 else 1
                val action=TvGridNavigation.edgeAction(position,column,span,lm.spanCount,grid.adapter?.itemCount?:0,direction,event.repeatCount,grid.adapter===mediaAdapter)
                when(action){GridEdgeAction.HEADER->{focusNavigation(position);return true};GridEdgeAction.TIMELINE->{openDateTimeline(position);return true};GridEdgeAction.NONE->Unit}
                if(event.repeatCount>0&&(direction<0&&column==0||direction>0&&grid.adapter===mediaAdapter&&(column+span>=lm.spanCount||position==(grid.adapter?.itemCount?:0)-1)))return true
            }
        }
        if (event.action == android.view.KeyEvent.ACTION_DOWN && grid.visibility == View.VISIBLE && grid.hasFocus()) {
            val direction = when (event.keyCode) {
                android.view.KeyEvent.KEYCODE_PAGE_DOWN,
                android.view.KeyEvent.KEYCODE_CHANNEL_DOWN -> 1
                android.view.KeyEvent.KEYCODE_PAGE_UP,
                android.view.KeyEvent.KEYCODE_CHANNEL_UP -> -1
                // Удержание ▲/▼ на пульте: после короткой серии обычных шагов — прыжки на экран.
                android.view.KeyEvent.KEYCODE_DPAD_DOWN -> if (event.repeatCount >= 4) 1 else 0
                android.view.KeyEvent.KEYCODE_DPAD_UP -> if (event.repeatCount >= 4) -1 else 0
                else -> 0
            }
            if (direction != 0 && fastScroll(direction)) return true
        }
        return super.dispatchKeyEvent(event)
    }

    private fun fastScroll(direction: Int): Boolean {
        val lm = grid.layoutManager as? GridLayoutManager ?: return false
        val count = grid.adapter?.itemCount ?: 0
        if (count == 0) return false
        val first = lm.findFirstVisibleItemPosition().coerceAtLeast(0)
        val last = lm.findLastVisibleItemPosition()
        val step = maxOf(lm.spanCount, last - first + 1) // примерно один экран
        val target = (first + direction * step).coerceIn(0, count - 1)
        if (target == first) return true
        grid.scrollToPosition(target)
        updateScrollBubble()
        grid.post {
            val holder = grid.findViewHolderForAdapterPosition(target)
            (holder?.itemView ?: grid.getChildAt(0))?.requestFocus()
        }
        return true
    }

    /** Пузырь с месяцем/годом и процентом — чтобы пультом было видно, куда листаем. */
    private fun updateScrollBubble() {
        if(::dateTimeline.isInitialized&&dateTimeline.isOpen)return
        val lm = grid.layoutManager as? GridLayoutManager ?: return
        val adapter = grid.adapter ?: return
        val count = adapter.itemCount
        if (count == 0) return
        val first = lm.findFirstVisibleItemPosition().coerceAtLeast(0)
        val last = lm.findLastVisibleItemPosition().coerceAtLeast(first)
        val percent = ((last + 1) * 100 / count).coerceIn(1, 100)
        var text = ""
        if (adapter === mediaAdapter) {
            val item = mediaAdapter.currentList.getOrNull(first)
            text = formatMonthYear(item?.takenAt)
        }
        scrollBubble.text = if (text.isNotEmpty()) "$text  ·  $percent%" else "$percent%"
        scrollBubble.visibility = View.VISIBLE
        bubbleHandler.removeCallbacks(hideBubble)
        bubbleHandler.postDelayed(hideBubble, 1500)
    }

    // ---------- Верхние вкладки ----------

    private fun onTab(position: Int) {
        pendingScrollState=null
        tabsAdapter.selected = position
        tabsAdapter.notifyDataSetChanged()
        tabs.scrollToPosition(position)
        when (position) {
            0 -> showLibrary()
            1 -> showCollections()
            2 -> showProfile()
        }
    }

    private fun selectTab(position: Int) = onTab(position)

    // ---------- Экраны ----------

    private fun applyGridSize() {
        mediaAdapter.tileHeightDp = gridHeights[gridSize]
        mediaAdapter.notifyDataSetChanged()
        gridSizeButton.text = getString(gridLabels[gridSize])
        applySpanForScreen()
    }

    private fun applySpanForScreen() {
        val lm = grid.layoutManager as? GridLayoutManager ?: return
        val span = when (screen) {
            Screen.COLLECTIONS, Screen.PEOPLE -> cardSpan
            else -> gridSpans[gridSize]
        }
        if (lm.spanCount != span) lm.spanCount = span
    }

    private fun showLibrary() {
        if(::dateTimeline.isInitialized)dateTimeline.dismiss(false)
        screen = Screen.LIBRARY
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        profileView.visibility = View.GONE
        grid.visibility = View.VISIBLE
        headerRow.visibility = View.GONE
        gridSizeButton.visibility = View.VISIBLE
        grid.adapter = mediaAdapter
        applySpanForScreen()
        val items = regularItems()
        showMedia(items)
        if (library == null) loadLibrary()
    }

    private fun showCollections() {
        if(::dateTimeline.isInitialized)dateTimeline.dismiss(false)
        screen = Screen.COLLECTIONS
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        profileView.visibility = View.GONE
        grid.visibility = View.VISIBLE
        headerRow.visibility = View.GONE
        gridSizeButton.visibility = View.GONE
        grid.adapter = cardAdapter
        cardAdapter.tileHeightDp = cardHeightDp
        applySpanForScreen()
        val cards = buildCards()
        cardAdapter.submitList(cards)
        emptyText.visibility = if (cards.isEmpty()) View.VISIBLE else View.GONE
        emptyText.text = getString(R.string.empty_library)
        if (library == null) loadLibrary()
    }

    private fun showItems(title: String, items: List<MediaItem>) {
        if(::dateTimeline.isInitialized)dateTimeline.dismiss(false)
        screen = Screen.ITEMS
        if(items.any{it.isHidden})window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)else window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        profileView.visibility = View.GONE
        grid.visibility = View.VISIBLE
        headerRow.visibility = View.VISIBLE
        gridSizeButton.visibility = View.VISIBLE
        headerTitle.text = title
        grid.adapter = mediaAdapter
        applySpanForScreen()
        showMedia(items)
    }

    private fun showPeople() {
        if(::dateTimeline.isInitialized)dateTimeline.dismiss(false)
        screen = Screen.PEOPLE
        profileView.visibility = View.GONE
        grid.visibility = View.VISIBLE
        headerRow.visibility = View.VISIBLE
        gridSizeButton.visibility = View.GONE
        headerTitle.text = getString(R.string.card_people)
        grid.adapter = cardAdapter
        cardAdapter.tileHeightDp = cardHeightDp
        applySpanForScreen()
        val cards = people.map { person ->
            Card(
                id = "person:" + person.id,
                title = person.name,
                subtitle = photoCount(person.indices.size),
                coverPath = personCoverUrl(person),
                locked = false,
            )
        }
        cardAdapter.submitList(cards)
        emptyText.visibility = if (cards.isEmpty()) View.VISIBLE else View.GONE
        emptyText.text = getString(R.string.empty_library)
    }

    private fun showProfile() {
        if(::dateTimeline.isInitialized)dateTimeline.dismiss(false)
        screen = Screen.PROFILE
        headerRow.visibility = View.GONE
        grid.visibility = View.GONE
        emptyText.visibility = View.GONE
        gridSizeButton.visibility = View.GONE
        profileView.visibility = View.VISIBLE
        updateProfileInfo()
    }

    private fun goBack() {
        when (screen) {
            Screen.ITEMS -> if (fromPeople) showPeople() else showCollections()
            Screen.PEOPLE -> showCollections()
            Screen.COLLECTIONS, Screen.PROFILE -> selectTab(0)
            Screen.LIBRARY -> {}
        }
    }

    // ---------- Данные ----------

    private fun showMedia(items: List<MediaItem>) {
        mediaAdapter.submitList(items) {
            if(pendingScrollState!=null){grid.layoutManager?.onRestoreInstanceState(pendingScrollState);pendingScrollState=null}else if(items.isNotEmpty())grid.scrollToPosition(0)
        }
        emptyText.visibility = if (items.isEmpty()) View.VISIBLE else View.GONE
        emptyText.text = getString(R.string.empty_library)
    }

    private fun photoCount(count: Int): String {
        val mod100 = count % 100
        val mod10 = count % 10
        val word = when {
            mod100 in 11..14 -> "фотографий"
            mod10 == 1 -> "фотография"
            mod10 in 2..4 -> "фотографии"
            else -> "фотографий"
        }
        return "$count $word"
    }

    private fun buildCards(): List<Card> {
        val lib = library ?: return emptyList()
        val cards = mutableListOf<Card>()
        val regular=lib.items.filter{!it.isHidden}
        if (regular.isNotEmpty()) {
            cards += Card("recent", getString(R.string.card_recent), photoCount(regular.size), regular.first().thumbnailPath, locked = false)
        }
        val favorites = regular.filter { it.favorite }
        if (favorites.isNotEmpty()) {
            cards += Card("fav", getString(R.string.card_favorites), photoCount(favorites.size), favorites.first().thumbnailPath, locked = false)
        }
        val videos = regular.filter { it.isVideo }
        if (videos.isNotEmpty()) {
            cards += Card("video", getString(R.string.card_videos), photoCount(videos.size), videos.first().thumbnailPath, locked = false)
        }
        val byId = lib.items.associateBy { it.id }
        for (album in lib.albums) {
            val title = album.name + (album.ownerName?.let { " · $it" } ?: "")
            val cover = (album.coverId?.let { byId[it] } ?: album.indices.asSequence().mapNotNull { byId[it] }.firstOrNull())
            cards += Card("album:" + album.id, title, photoCount(album.indices.size), cover?.thumbnailPath, locked = false)
        }
        val hidden = lib.items.filter { it.isHidden }
        if (!lib.concealHidden && (hidden.isNotEmpty() || lib.hasLockedHidden)) {
            val locked = hidden.isEmpty() && lib.hasLockedHidden
            cards += Card(
                "hidden", getString(R.string.card_hidden),
                if (locked) "Закрыто кодом-паролем" else photoCount(hidden.size),
                if (locked) null else hidden.first().previewPath,
                locked = locked,
            )
        }
        if (people.isNotEmpty()) {
            cards += Card("people", getString(R.string.card_people), photoCount(people.size), null, locked = false)
        }
        return cards
    }

    private fun openCard(card: Card,restore:Boolean=false) {
        if(!restore)pendingScrollState=null
        openedCard=card
        val lib = library ?: return
        val byId = lib.items.associateBy { it.id }
        when {
            card.id == "people" -> showPeople()
            card.id == "hidden" -> openHidden(lib)
            card.id == "recent" -> {
                fromPeople = false
                showItems(card.title, regularItems())
            }
            card.id == "fav" -> {
                fromPeople = false
                showItems(card.title, regularItems().filter { it.favorite })
            }
            card.id == "video" -> {
                fromPeople = false
                showItems(card.title, regularItems().filter { it.isVideo })
            }
            card.id.startsWith("album:") -> {
                val album = lib.albums.firstOrNull { "album:" + it.id == card.id } ?: return
                fromPeople = false
                showItems(album.name, album.indices.mapNotNull { byId[it] })
            }
            card.id.startsWith("person:") -> {
                val person = people.firstOrNull { "person:" + it.id == card.id } ?: return
                fromPeople = true
                showItems(person.name, person.indices.mapNotNull { byId[it] })
            }
        }
    }

    private fun openHidden(lib: Library) {
        val hidden = lib.items.filter { it.isHidden }
        if (hidden.isNotEmpty() && session.vaultUnlocked) {
            fromPeople = false
            showItems(getString(R.string.card_hidden), hidden)
            return
        }
        if(!session.vaultProtectionEnabled){loadLibrary();return}
        askPin { pin -> unlockHidden(pin) }
    }

    private fun askPin(onOk: (String) -> Unit) {
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
            hint = getString(R.string.pin_hint)
        }
        val pad = (24 * resources.displayMetrics.density).toInt()
        val container = android.widget.FrameLayout(this).apply {
            setPadding(pad, pad / 2, pad, 0)
            addView(input)
        }
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.pin_title))
            .setMessage(getString(R.string.pin_message))
            .setView(container)
            .setPositiveButton(getString(R.string.pin_open)) { _, _ -> onOk(input.text.toString()) }
            .setNegativeButton(getString(R.string.cancel), null)
            .show()
    }

    private fun unlockHidden(pin: String) {
        if (pin.isEmpty()) return
        progress.visibility = View.VISIBLE
        Thread {
            try {
                val json = session.unlockVault(pin)
                val parsed = parseLibrary(json, session.accountName)
                runOnUiThread {
                    progress.visibility = View.GONE
                    library = parsed
                    val hidden = parsed.items.filter { it.isHidden }
                    if (hidden.isEmpty()) {
                        Toast.makeText(this, "Скрытых фото нет", Toast.LENGTH_SHORT).show()
                    } else {
                        fromPeople = false
                        showItems(getString(R.string.card_hidden), hidden)
                    }
                }
            } catch (error: ApiException) {
                session.clearVaultPin()
                runOnUiThread {
                    progress.visibility = View.GONE
                    Toast.makeText(this, error.message, Toast.LENGTH_LONG).show()
                }
            } catch (error: IOException) {
                runOnUiThread {
                    progress.visibility = View.GONE
                    Toast.makeText(this, "Сервер недоступен", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    private fun openViewer(item: MediaItem) {
        ViewerData.items = mediaAdapter.currentList
        ViewerData.index = mediaAdapter.currentList.indexOfFirst { it.id == item.id && it.kind == item.kind }
        startActivity(Intent(this, ViewerActivity::class.java))
    }

    // ---------- Загрузка ----------

    private fun loadLibrary() {
        if (loading) return
        loading = true
        progress.visibility = View.VISIBLE
        emptyText.visibility = View.GONE
        Thread {
            val loadEpoch=session.accessGeneration
            try {
                val parsed = parseLibrary(session.library(), session.accountName)
                val parsedPeople = try {
                    parsePeople(session.people())
                } catch (_: Exception) {
                    emptyList()
                }
                if(loadEpoch==session.accessGeneration)onLoaded(parsed, parsedPeople)
            } catch (error: UnauthorizedException) {
                if(loadEpoch!=session.accessGeneration||isDestroyed||isFinishing)return@Thread
                session.clearSession()
                runOnUiThread {if(!isDestroyed){startActivity(Intent(this,ConnectActivity::class.java));finish()}}
            } catch (error: IOException) {
                runOnUiThread {
                    if(isDestroyed||isFinishing)return@runOnUiThread
                    loading = false
                    progress.visibility = View.GONE
                    emptyText.visibility = View.VISIBLE
                    emptyText.text = getString(R.string.error_prefix) + (error.message ?: "нет связи") +
                        "\n\nОткрой «Профиль» и нажми «Обновить медиатеку», когда сервер будет доступен."
                }
            }
        }.start()
    }

    private fun onLoaded(parsed: Library, parsedPeople: List<Person>) {
        runOnUiThread {
            if(isDestroyed||isFinishing)return@runOnUiThread
            pendingScrollState=if(screen==Screen.LIBRARY||screen==Screen.ITEMS)grid.layoutManager?.onSaveInstanceState()else null
            knownVaultGeneration=session.vaultGeneration
            loading = false
            progress.visibility = View.GONE
            library = parsed
            people = parsedPeople
            when (screen) {
                Screen.COLLECTIONS -> showCollections()
                Screen.PEOPLE -> showPeople()
                Screen.LIBRARY -> showLibrary()
                Screen.ITEMS -> {val card=openedCard;if(card==null||card.id.startsWith("album:")&&parsed.albums.none{"album:"+it.id==card.id})showCollections()else openCard(card,restore=true)}
                Screen.PROFILE -> updateProfileInfo()
            }
        }
    }

    private fun logout() {
        progress.visibility=View.VISIBLE
        Thread {
            try{session.logout()}catch(_:IOException){}
            runOnUiThread {
                startActivity(Intent(this, ConnectActivity::class.java))
                finish()
            }
        }.start()
    }

    // ---------- Обновления приложения ----------

    private fun checkUpdates(showFeedback: Boolean = false) {
        if (showFeedback) Toast.makeText(this, getString(R.string.update_checking), Toast.LENGTH_SHORT).show()
        Thread {
            val info = try{Updater.check(this)}catch(error:IOException){if(showFeedback)runOnUiThread{if(!isDestroyed)Toast.makeText(this,"Сервер обновлений недоступен. Повтори позже.",Toast.LENGTH_LONG).show()};return@Thread}
            runOnUiThread {
                if(isDestroyed||isFinishing)return@runOnUiThread
                if (info != null) {
                    updateBanner.visibility = View.VISIBLE
                    updateBanner.text = getString(R.string.update_available, info.versionName)
                    updateBanner.setOnClickListener { startUpdate(info) }
                } else if (showFeedback) {
                    Toast.makeText(this, getString(R.string.update_none), Toast.LENGTH_SHORT).show()
                }
            }
        }.start()
    }

    private fun startUpdate(info: Updater.Info) {
        if (updateDownloading) return
        updateDownloading = true
        updateBanner.text = "Скачиваем обновление ${info.versionName}…"
        Thread {
            try {
                val apk = Updater.download(this, info) { percent ->
                    runOnUiThread { if (!isDestroyed) updateBanner.text = if (percent >= 99) "Проверяем обновление ${info.versionName}…" else "Скачиваем обновление ${info.versionName}… $percent%" }
                }
                runOnUiThread {
                    updateDownloading = false
                    if (!isDestroyed && !isFinishing) installUpdate(apk, info)
                }
            } catch (error: Exception) {
                runOnUiThread {
                    if (isDestroyed || isFinishing) return@runOnUiThread
                    val reason = (error as? UpdateFailure)?.message ?: "Не удалось подготовить обновление"
                    updateBanner.text = "$reason. Нажми, чтобы повторить"
                    updateBanner.setOnClickListener { startUpdate(info) }
                    updateDownloading = false
                }
            }
        }.start()
    }

    private fun installUpdate(apk: java.io.File, info: Updater.Info) {
        try {
            if (!packageManager.canRequestPackageInstalls()) {
                updateBanner.text = "Разреши установку обновлений для lumi. Затем нажми здесь ещё раз"
                updateBanner.setOnClickListener { installUpdate(apk, info) }
                startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    android.net.Uri.parse("package:$packageName")))
                return
            }
            val uri = androidx.core.content.FileProvider.getUriForFile(
                this, "${BuildConfig.APPLICATION_ID}.fileprovider", apk)
            val intent = Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            intent.clipData = android.content.ClipData.newRawUri("lumi update", uri)
            startActivity(intent)
            updateBanner.text = "Обновление ${info.versionName} скачано. Нажми, чтобы открыть установку"
            updateBanner.setOnClickListener { installUpdate(apk, info) }
        } catch (_: Exception) {
            updateBanner.text = "Не удалось открыть установщик Android. Нажми, чтобы повторить"
            updateBanner.setOnClickListener { installUpdate(apk, info) }
        }
    }

}

// ---------- Адаптеры ----------

private class TabsAdapter(val onClick: (Int) -> Unit) :
    RecyclerView.Adapter<TabsAdapter.TabHolder>() {

    private var labels: List<String> = emptyList()
    var selected: Int = 0

    fun submit(newLabels: List<String>) {
        labels = newLabels
        notifyDataSetChanged()
    }

    class TabHolder(val text: TextView) : RecyclerView.ViewHolder(text)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): TabHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_tab, parent, false) as TextView
        return TabHolder(view)
    }

    override fun getItemCount(): Int = labels.size

    override fun onBindViewHolder(holder: TabHolder, position: Int) {
        holder.text.text = labels[position]
        val active = position == selected
        holder.text.setTextColor(
            if (active) holder.text.context.getColor(R.color.text)
            else holder.text.context.getColor(R.color.text_dim)
        )
        holder.text.setTypeface(null, if (active) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
        holder.text.setOnClickListener { onClick(holder.bindingAdapterPosition) }
    }
}

private data class Card(
    val id: String,
    val title: String,
    val subtitle: String,
    val coverPath: String?,
    val locked: Boolean,
)

private class CardAdapter(val session: Session, val onClick: (Card) -> Unit) :
    ListAdapter<Card, CardAdapter.CardHolder>(Diff) {

    var tileHeightDp = 170

    object Diff : DiffUtil.ItemCallback<Card>() {
        override fun areItemsTheSame(a: Card, b: Card) = a.id == b.id
        override fun areContentsTheSame(a: Card, b: Card) = a == b
    }

    class CardHolder(view: View) : RecyclerView.ViewHolder(view) {
        val cover: ImageView = view.findViewById(R.id.cardCover)
        val lock: TextView = view.findViewById(R.id.cardLock)
        val title: TextView = view.findViewById(R.id.cardTitle)
        val subtitle: TextView = view.findViewById(R.id.cardSubtitle)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): CardHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_card, parent, false)
        view.onFocusChangeListener = View.OnFocusChangeListener { v, focused ->
            v.animate()
                .scaleX(if (focused) 1.06f else 1f)
                .scaleY(if (focused) 1.06f else 1f)
                .translationZ(if (focused) 8f else 0f)
                .setDuration(150)
                .start()
        }
        return CardHolder(view)
    }

    private fun applyTileHeight(view: View) {
        val px = (tileHeightDp * view.resources.displayMetrics.density).toInt()
        val lp = view.layoutParams
        if (lp == null) {
            view.layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px)
        } else if (lp.height != px) {
            lp.height = px
            view.layoutParams = lp
        }
    }

    override fun onBindViewHolder(holder: CardHolder, position: Int) {
        applyTileHeight(holder.itemView)
        val card = getItem(position)
        if (card.coverPath != null && !card.locked) {
            holder.cover.visibility = View.VISIBLE
            holder.cover.load(session.mediaUrl(card.coverPath)) { crossfade(160) }
        } else {
            holder.cover.setImageDrawable(null)
        }
        holder.lock.visibility = if (card.locked) View.VISIBLE else View.GONE
        holder.title.text = card.title
        holder.subtitle.text = card.subtitle
        holder.itemView.setOnClickListener { onClick(card) }
        holder.itemView.contentDescription = card.title
    }
}

private class MediaAdapter(val onClick: (MediaItem) -> Unit) :
    ListAdapter<MediaItem, MediaAdapter.MediaHolder>(Diff) {

    var tileHeightDp = 170

    object Diff : DiffUtil.ItemCallback<MediaItem>() {
        override fun areItemsTheSame(a: MediaItem, b: MediaItem) = a.id == b.id
        override fun areContentsTheSame(a: MediaItem, b: MediaItem) = a == b
    }

    class MediaHolder(view: View) : RecyclerView.ViewHolder(view) {
        val thumb: ImageView = view.findViewById(R.id.thumb)
        val videoBadge: TextView = view.findViewById(R.id.videoBadge)
        val favBadge: TextView = view.findViewById(R.id.favBadge)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): MediaHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_media, parent, false)
        view.onFocusChangeListener = View.OnFocusChangeListener { v, focused ->
            v.animate()
                .scaleX(if (focused) 1.06f else 1f)
                .scaleY(if (focused) 1.06f else 1f)
                .translationZ(if (focused) 8f else 0f)
                .setDuration(150)
                .start()
        }
        return MediaHolder(view)
    }

    private fun applyTileHeight(view: View) {
        val px = (tileHeightDp * view.resources.displayMetrics.density).toInt()
        val lp = view.layoutParams
        if (lp == null) {
            view.layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px)
        } else if (lp.height != px) {
            lp.height = px
            view.layoutParams = lp
        }
    }

    override fun onBindViewHolder(holder: MediaHolder, position: Int) {
        applyTileHeight(holder.itemView)
        val item = getItem(position)
        val app = holder.itemView.context.applicationContext as App
        holder.thumb.load(app.session.mediaUrl(item.thumbnailPath)) {
            crossfade(160)
        }
        if (item.isVideo) {
            holder.videoBadge.visibility = View.VISIBLE
            holder.videoBadge.text = "▶ " + (item.durationSec?.let { formatDuration(it) } ?: "")
        } else {
            holder.videoBadge.visibility = View.GONE
        }
        holder.favBadge.visibility = if (item.favorite) View.VISIBLE else View.GONE
        holder.itemView.setOnClickListener { onClick(item) }
        holder.itemView.contentDescription =
            (if (item.isVideo) "Видео" else "Фото") + " " + formatTakenAt(item.takenAt)
    }
}
