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
    }
}
