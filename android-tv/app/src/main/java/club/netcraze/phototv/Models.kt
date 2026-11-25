package club.netcraze.phototv

import org.json.JSONObject

data class MediaItem(
    val id: Int,
    val kind: String,
    val state: String,
    val favorite: Boolean,
    val takenAt: String?,
    val durationSec: Double?,
    val previewPath: String,
    val originalPath: String,
    val thumbnailPath: String = previewPath,
) {
    val isVideo: Boolean get() = kind == "video"
    val isHidden: Boolean get() = state == "hidden"
}

data class Album(
    val id: String,
    val name: String,
    val indices: List<Int>,
    val coverId: Int?,
    val ownerName: String?,
)

data class Person(
    val id: String,
    val name: String,
    val coverFace: String?,
    val indices: List<Int>,
)

data class Library(
    val items: List<MediaItem>,
    val albums: List<Album>,
    val accountName: String,
    val hasLockedHidden: Boolean,
    val concealHidden: Boolean = false,
)

val Library.regularItems: List<MediaItem> get() = items.filter { !it.isHidden }

object ViewerData {
    var items: List<MediaItem> = emptyList()
    var index: Int = 0
}

/**
 * Разбор ответа GET /api/library (vault.library + library_state в server.py/vault.py).
 * Показываем public, shared и hidden (после ввода кода-пароля); locked — это скрытые
 * под замком: их не показываем, но запоминаем, что раздел «Скрытые» существует.
 */
fun parseLibrary(json: JSONObject, accountName: String): Library {
    val items = mutableListOf<MediaItem>()
    var lockedHidden = false
    val array = json.optJSONArray("items")
    if (array != null) {
        for (i in 0 until array.length()) {
            val obj = array.optJSONObject(i) ?: continue
            val state = obj.optString("state", "")
            if (state == "locked") {
                lockedHidden = true
                continue
            }
            if (state != "public" && state != "shared" && state != "hidden") continue
            if (!obj.isNull("deletedAt")) continue
            val id = obj.optInt("id", -1)
            if (id < 0) continue
            val metadata = obj.optJSONObject("metadata")
            val takenAt = metadata?.optString("takenAt", "")?.takeIf { it.isNotEmpty() }
                ?: metadata?.optString("addedAt", "")?.takeIf { it.isNotEmpty() }
            val duration = metadata?.optDouble("duration", Double.NaN)
                ?.takeIf { it.isFinite() && it > 0 }
            val preview = obj.optString("preview", "").ifEmpty { "/media/$id/preview" }
            val original = obj.optString("original", "").ifEmpty { "/media/$id/original" }
            items += MediaItem(
                id = id,
                kind = obj.optString("kind", "photo"),
                state = state,
                favorite = obj.optBoolean("favorite", false),
                takenAt = takenAt,
                durationSec = duration,
                previewPath = preview,
                originalPath = original,
                thumbnailPath = if(state=="public") "/media/$id/thumbnail" else preview,
            )
        }
    }
    items.sortByDescending { it.takenAt ?: "" }

    val albums = mutableListOf<Album>()
    val albumsArray = json.optJSONArray("albums")
    if (albumsArray != null) {
        for (i in 0 until albumsArray.length()) {
            val obj = albumsArray.optJSONObject(i) ?: continue
            val indices = mutableListOf<Int>()
            val indicesArray = obj.optJSONArray("indices")
            if (indicesArray != null) {
                for (j in 0 until indicesArray.length()) indices += indicesArray.optInt(j)
            }
            if (indices.isEmpty()) continue
            val owner = obj.optString("ownerName", "").takeIf { obj.optBoolean("shared", false) && it.isNotEmpty() }
            val cover = if (obj.isNull("cover")) null else obj.optInt("cover")
            albums += Album(
                id = obj.optString("id", ""),
                name = obj.optString("name", "Альбом"),
                indices = indices,
                coverId = cover,
                ownerName = owner,
            )
        }
    }
    return Library(items = items, albums = albums, accountName = accountName, hasLockedHidden = lockedHidden, concealHidden = json.optJSONObject("vault")?.optBoolean("concealHidden",false) ?: false)
}

/** Разбор GET /api/people — карточки людей (people.py status()). */
fun parsePeople(json: JSONObject): List<Person> {
    if (!json.optBoolean("visible", true)) return emptyList()
    val result = mutableListOf<Person>()
    val array = json.optJSONArray("people") ?: return result
    for (i in 0 until array.length()) {
        val obj = array.optJSONObject(i) ?: continue
        val indices = mutableListOf<Int>()
        val indicesArray = obj.optJSONArray("indices")
        if (indicesArray != null) {
            for (j in 0 until indicesArray.length()) indices += indicesArray.optInt(j)
        }
        if (indices.isEmpty()) continue
        result += Person(
            id = obj.optString("id", ""),
            name = obj.optString("name", "").ifEmpty { "Без имени" },
            coverFace = obj.optString("cover", "").takeIf { it.isNotEmpty() && it != "null" },
            indices = indices,
        )
    }
    return result
}

fun personCoverUrl(person: Person): String? =
    person.coverFace?.let { "/media/people/$it/preview" }

fun formatDuration(totalSeconds: Double): String {
    val total = totalSeconds.toLong()
    val hours = total / 3600
    val minutes = (total % 3600) / 60
    val seconds = total % 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds)
    else "%d:%02d".format(minutes, seconds)
}

fun formatTakenAt(iso: String?): String {
    if (iso.isNullOrEmpty() || iso.length < 10) return ""
    return try {
        val instant = java.time.OffsetDateTime.parse(iso)
        val local = instant.atZoneSameInstant(java.time.ZoneId.systemDefault())
        val months = arrayOf("января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря")
        "%d %s %d, %02d:%02d".format(
            local.dayOfMonth, months[local.monthValue - 1], local.year, local.hour, local.minute
        )
    } catch (_: Exception) {
        iso.substring(0, 10)
    }
}

/** «май 2024» — для пузыря быстрой прокрутки. */
fun formatMonthYear(iso: String?): String {
    if (iso.isNullOrEmpty() || iso.length < 7) return ""
    return try {
        val instant = java.time.OffsetDateTime.parse(iso)
        val local = instant.atZoneSameInstant(java.time.ZoneId.systemDefault())
        val months = arrayOf("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
        "${months[local.monthValue - 1]} ${local.year}"
    } catch (_: Exception) {
        ""
    }
}
