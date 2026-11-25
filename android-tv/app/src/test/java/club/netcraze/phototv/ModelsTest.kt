package club.netcraze.phototv
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
class ModelsTest {
 @Test fun thumbnailRouteIsOnlyForOwnPublicMedia(){
  val library=parseLibrary(JSONObject("""{"items":[{"id":0,"kind":"photo","state":"public"},{"id":1,"state":"hidden"},{"id":2,"state":"shared","preview":"/media/shared/fixture/preview"},{"id":3,"state":"locked"},{"id":4,"state":"public","deletedAt":"2026-01-01"}],"vault":{"concealHidden":true}}"""),"fixture")
  assertEquals(3,library.items.size);assertEquals("/media/0/thumbnail",library.items.first{it.id==0}.thumbnailPath)
  assertEquals("/media/1/preview",library.items.first{it.id==1}.thumbnailPath);assertEquals("/media/shared/fixture/preview",library.items.first{it.id==2}.thumbnailPath)
  assertEquals(setOf(0,2),library.regularItems.map{it.id}.toSet());assertTrue(library.hasLockedHidden);assertTrue(library.concealHidden)
 }
 @Test fun missingDatesAndVideoDurationDoNotBreakLibrary(){
  val library=parseLibrary(JSONObject("""{"items":[{"id":0,"state":"public","kind":"video","metadata":{"duration":12.5}},{"id":1,"state":"public"}]}"""),"fixture")
  assertEquals(2,library.regularItems.size);assertEquals("0:12",formatDuration(12.5));assertEquals("",formatTakenAt(null));assertFalse(library.concealHidden)
 }
}
