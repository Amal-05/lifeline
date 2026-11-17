package org.lifeline.field

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RelayLedgerTest {
    @Test fun deduplicatesAndEnforcesLimits() {
        val ledger = RelayLedger(maximumEvents = 2, maximumBytes = 64)
        assertTrue(ledger.accept("one", 32))
        assertFalse(ledger.accept("one", 32))
        assertTrue(ledger.accept("two", 32))
        assertFalse(ledger.accept("three", 1))
        assertFalse(ledger.accept("oversized", 32769))
        assertTrue(RelayLedger().accept("large-chunked-event", 40000))
    }

    @Test fun chunksReassembleOutOfOrderAndCheckHash() {
        val original = ByteArray(EventChunker.CHUNK_SIZE * 2 + 10) { (it % 251).toByte() }
        val pieces = EventChunker.split("transfer", original)
        val assembler = ChunkAssembler()
        var assembled: ByteArray? = null
        pieces.reversed().forEach { assembled = assembler.offer(it) ?: assembled }
        assertTrue(original.contentEquals(assembled))
        val corrupted = ChunkAssembler()
        val bad = pieces.mapIndexed { index, part -> if (index == 0) part.copy(bytes = part.bytes.copyOf().also { it[0] = (it[0] + 1).toByte() }) else part }
        var rejected: ByteArray? = null
        bad.forEach { rejected = corrupted.offer(it) ?: rejected }
        assertFalse(rejected != null)
    }
}
