package club.netcraze.phototv

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class UpdateDownloadTest {
    private fun scenario(block: (MockWebServer, java.io.File) -> Unit) {
        val server = MockWebServer()
        val dir = Files.createTempDirectory("lumi-update").toFile()
        server.start()
        try { block(server, dir) } finally { server.shutdown(); dir.deleteRecursively() }
    }

    @Test fun validatesCompletedApkBeforeReportingSuccess() = scenario { server, dir ->
        val body = "apk fixture".toByteArray()
        server.enqueue(MockResponse().setBody(okio.Buffer().write(body)))
        val progress = mutableListOf<Int>()
        var validated = false
        val result = UpdateDownload.fetch(OkHttpClient(), dir, server.url("/update").toString(), 14,
            UpdateDownload.hash(body), { value -> if (value == 100) assertTrue(validated); progress += value }) { file ->
            assertEquals("apk", file.extension)
            assertArrayEquals(body, file.readBytes())
            validated = true
        }
        assertTrue(result.exists())
        assertEquals(100, progress.last())
        assertFalse(java.io.File(dir, "apk/rc-foto-14.apk.part").exists())
    }

    @Test fun corruptedDownloadNeverReachesPackageValidator() = scenario { server, dir ->
        server.enqueue(MockResponse().setBody("corrupted"))
        try {
            UpdateDownload.fetch(OkHttpClient(), dir, server.url("/update").toString(), 14,
                UpdateDownload.hash("expected".toByteArray()), {}) { fail("Checksum must be checked first") }
            fail("Expected failure")
        } catch (error: UpdateFailure) { assertTrue(error.message!!.contains("сумма")) }
        assertTrue(java.io.File(dir, "apk").listFiles()!!.isEmpty())
    }

    @Test fun archiveRejectionIsSpecificAndRetryStartsClean() = scenario { server, dir ->
        val data = "valid bytes"
        val digest = UpdateDownload.hash(data.toByteArray())
        server.enqueue(MockResponse().setBody(data))
        val progress = mutableListOf<Int>()
        try {
            UpdateDownload.fetch(OkHttpClient(), dir, server.url("/update").toString(), 14, digest, { progress += it }) {
                throw UpdateFailure("Signing certificate differs")
            }
            fail("Expected rejection")
        } catch (error: UpdateFailure) { assertEquals("Signing certificate differs", error.message) }
        assertFalse(progress.contains(100))
        assertTrue(java.io.File(dir, "apk").listFiles()!!.isEmpty())
        server.enqueue(MockResponse().setBody(data))
        assertTrue(UpdateDownload.fetch(OkHttpClient(), dir, server.url("/update").toString(), 14, digest, {}) {}.exists())
    }

    @Test fun httpFailureCannotBecomeReadyApk() = scenario { server, dir ->
        server.enqueue(MockResponse().setResponseCode(503))
        try {
            UpdateDownload.fetch(OkHttpClient(), dir, server.url("/update").toString(), 14, "a".repeat(64), {}) {}
            fail("Expected HTTP failure")
        } catch (error: UpdateFailure) { assertTrue(error.message!!.contains("503")) }
        assertTrue(java.io.File(dir, "apk").listFiles()!!.isEmpty())
    }
}
