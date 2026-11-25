package club.netcraze.phototv
import org.junit.Test
import org.junit.Assert.*

class MobilePolicyTest {
 @Test fun routesTvIndependentlyOfScreenSize(){assertEquals(LumiDevice.TV,MobilePolicy.device(true,320));assertEquals(LumiDevice.PHONE,MobilePolicy.device(false,599));assertEquals(LumiDevice.TABLET,MobilePolicy.device(false,600))}
 @Test fun acceptsOnlyServerOrigins(){assertEquals("http://192.168.1.3:8098",MobilePolicy.origin("192.168.1.3:8098"));assertEquals("https://photos.example.com",MobilePolicy.origin("photos.example.com"));for(value in listOf("https://user:pass@example.com","https://example.com/path","https://example.com/?token=x","file:///etc/passwd")){try{MobilePolicy.origin(value);fail(value)}catch(_:IllegalArgumentException){}}}
 @Test fun sameOriginChecksProtocolPortCredentialsAndHost(){assertTrue(MobilePolicy.sameOrigin("https://a.example","https://a.example/media/1"));assertFalse(MobilePolicy.sameOrigin("https://a.example","http://a.example"));assertFalse(MobilePolicy.sameOrigin("https://a.example","https://a.example:444"));assertFalse(MobilePolicy.sameOrigin("https://a.example","https://a.example.evil.test"));assertFalse(MobilePolicy.sameOrigin("https://a.example","https://user@a.example"))}
 @Test fun vaultCookiesNeverLeaveTheWebVault(){val header=MobilePolicy.cookieHeader("photo_account=one; photo_csrf=two; photo_vault=private; unrelated=secret");assertEquals("photo_account=one; photo_csrf=two",header);assertEquals(MobilePolicy.fingerprint("https://a",header),MobilePolicy.fingerprint("https://a",header+"; photo_vault=changed"));assertNotEquals(MobilePolicy.fingerprint("https://a",header),MobilePolicy.fingerprint("https://b",header))}
 @Test fun queueOwnershipSurvivesReauthenticationButNotAccountOrServerSwitch(){val a=MobileAccount("https://a","photo_account=first","one","");val renewed=a.copy(cookie="photo_account=renewed");assertEquals(a.queueKey,renewed.queueKey);assertNotEquals(a.fingerprint,renewed.fingerprint);assertNotEquals(a.queueKey,a.copy(owner="two").queueKey);assertNotEquals(a.queueKey,a.copy(origin="https://b").queueKey)}
}
