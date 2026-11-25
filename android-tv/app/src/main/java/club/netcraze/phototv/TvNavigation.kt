package club.netcraze.phototv

import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId

enum class GridEdgeAction { NONE, HEADER, TIMELINE }

object TvGridNavigation {
    fun edgeAction(position: Int, spanIndex: Int, spanSize: Int, columns: Int, count: Int,
                   direction: Int, repeatCount: Int, media: Boolean): GridEdgeAction {
        if (repeatCount != 0 || position !in 0 until count || columns < 1) return GridEdgeAction.NONE
        if (direction < 0 && spanIndex == 0) return GridEdgeAction.HEADER
        if (direction > 0 && media && count > 1 && (spanIndex + spanSize >= columns || position == count - 1)) return GridEdgeAction.TIMELINE
        return GridEdgeAction.NONE
    }
}

data class TvDateStop(val day: LocalDate?, val firstPosition: Int, val count: Int)
data class TvTimelineIndex(val stops: List<TvDateStop>, val positionToStop: IntArray) {
    fun stopAt(position: Int): Int = if (positionToStop.isEmpty()) 0 else positionToStop[position.coerceIn(positionToStop.indices)]
    fun nextMonth(current: Int, direction: Int): Int {
        if (stops.isEmpty()) return 0
        val start=current.coerceIn(stops.indices)
        if(direction==0)return start
        val month=stops[start].day?.let { it.year * 12 + it.monthValue }
        var next=start+direction
        while(next in stops.indices){val day=stops[next].day;if(day?.let{it.year*12+it.monthValue}!=month)return next;next+=direction}
        return if(direction>0)stops.lastIndex else 0
    }
    companion object {
        fun build(items: List<MediaItem>, zone: ZoneId = ZoneId.systemDefault()): TvTimelineIndex {
            val keys=linkedMapOf<LocalDate?,Int>();val first=mutableListOf<Int>();val days=mutableListOf<LocalDate?>();val counts=mutableListOf<Int>();val mapping=IntArray(items.size)
            for((position,item) in items.withIndex()){
                val day=try { OffsetDateTime.parse(item.takenAt).atZoneSameInstant(zone).toLocalDate() } catch(_:Exception) { try{LocalDate.parse(item.takenAt?.take(10))}catch(_:Exception){null} }
                val group=keys.getOrPut(day){days.add(day);first.add(position);counts.add(0);days.lastIndex}
                counts[group]++;mapping[position]=group
            }
            return TvTimelineIndex(days.indices.map{TvDateStop(days[it],first[it],counts[it])},mapping)
        }
    }
}
