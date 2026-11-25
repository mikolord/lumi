package club.netcraze.phototv
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId

class TvNavigationTest {
 @Test fun edgesWorkDeepInTheLibraryAtAllDensities(){
  for(columns in listOf(3,5,7,9)){
   val first=columns*100
   assertEquals(GridEdgeAction.HEADER,TvGridNavigation.edgeAction(first,0,1,columns,5000,-1,0,true))
   assertEquals(GridEdgeAction.TIMELINE,TvGridNavigation.edgeAction(first+columns-1,columns-1,1,columns,5000,1,0,true))
   assertEquals(GridEdgeAction.NONE,TvGridNavigation.edgeAction(first+1,1,1,columns,5000,-1,0,true))
  }
 }
 @Test fun partialLastRowAndRepeatDoNotJumpToAnUnexpectedScreen(){
  assertEquals(GridEdgeAction.TIMELINE,TvGridNavigation.edgeAction(16,1,1,5,17,1,0,true))
  assertEquals(GridEdgeAction.NONE,TvGridNavigation.edgeAction(16,1,1,5,17,1,5,true))
  assertEquals(GridEdgeAction.NONE,TvGridNavigation.edgeAction(10,0,1,5,17,-1,2,true))
  assertEquals(GridEdgeAction.NONE,TvGridNavigation.edgeAction(-1,0,1,5,17,-1,0,true))
  assertEquals(GridEdgeAction.NONE,TvGridNavigation.edgeAction(0,0,1,5,0,-1,0,true))
 }
 @Test fun collectionCardsHaveHeaderShortcutButNoPhotoTimeline(){
  assertEquals(GridEdgeAction.HEADER,TvGridNavigation.edgeAction(300,0,1,3,500,-1,0,false))
  assertEquals(GridEdgeAction.NONE,TvGridNavigation.edgeAction(302,2,1,3,500,1,0,false))
 }
 private fun media(id:Int,date:String?)=MediaItem(id,"photo","public",false,date,null,"/p/$id","/o/$id")
 @Test fun datesGroupTheSameDayAndKeepTheirActualAlbumPositions(){
  val items=listOf(media(12,"2025-02-03T01:00:00Z"),media(4,"2025-02-03T10:00:00Z"),media(8,"2025-01-15T12:00:00Z"),media(2,"2025-02-03T20:00:00Z"),media(9,null))
  val index=TvTimelineIndex.build(items,ZoneId.of("UTC"))
  assertEquals(3,index.stops.size);assertEquals(3,index.stops[0].count);assertEquals(0,index.stops[0].firstPosition);assertEquals(0,index.stopAt(3));assertEquals(1,index.stopAt(2));assertEquals(2,index.stopAt(4));assertNull(index.stops[2].day)
  assertEquals(1,index.nextMonth(0,1));assertEquals(0,index.nextMonth(1,-1))
 }
 @Test fun dateBoundaryUsesLocalTimeAndBadDatesRemainAccessible(){
  val index=TvTimelineIndex.build(listOf(media(0,"2025-02-01T23:30:00Z"),media(1,"2025-02-02T01:00:00Z"),media(2,"invalid")),ZoneId.of("Europe/Moscow"))
  assertEquals(2,index.stops.size);assertEquals(2,index.stops[0].count);assertEquals(2,index.stops[1].firstPosition)
  val empty=TvTimelineIndex.build(emptyList());assertEquals(0,empty.stopAt(99));assertEquals(0,empty.nextMonth(0,1))
 }
}
