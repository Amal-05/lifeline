package org.lifeline.field

import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RelayLedgerTest {
    @Test fun deduplicatesAndEnforcesLimits() {
        val ledger = RelayLedger(maximumEvents = 2, maximumBytes = 64)
        assertTrue(ledger.accept("one", 32, priority = 4, createdAtMillis = 1, ownUndeliveredSos = true))
        assertFalse(ledger.accept("one", 32))
        assertTrue(ledger.accept("two", 32, delivered = true))
        assertTrue(ledger.accept("three", 1))
        assertTrue("own undelivered SOS must survive eviction", "one" in ledger.ids())
        assertFalse("delivered event should be evicted first", "two" in ledger.ids())
        assertTrue(ledger.accept("four", 32, ownUndeliveredSos = true))
        assertFalse(ledger.accept("five", 1, ownUndeliveredSos = true))
        assertFalse(ledger.accept("oversized", 32769))
        assertTrue(RelayLedger().accept("large-chunked-event", 40000))
    }

    @Test fun exchangesHelloInventoryAndHlcSummary() {
        val inventory = InventoryBloomFilter()
        inventory.add("event-1")
        val hello = PeerHello(1, "device", 64, true, inventory.encode(), mapOf("origin" to "2026-01-01T00:00:00Z-0001-origin"))
        val decoded = PeerHello.decode(hello.encode())
        assertEquals(1, decoded.protocolVersion)
        assertTrue(decoded.internet)
        assertEquals(64, decoded.batteryPct)
        assertTrue(InventoryBloomFilter(encoded = decoded.inventoryBloom).mightContain("event-1"))
        assertEquals("2026-01-01T00:00:00Z-0001-origin", decoded.highestHlcByOrigin["origin"])
    }

    @Test fun appliesBatteryRelayAndPerOriginRateLimits() {
        assertEquals(10_000, BatteryRelayPolicy.forBattery(29).scanWindowMillis)
        assertEquals(60_000, BatteryRelayPolicy.forBattery(29).scanIntervalMillis)
        assertFalse(BatteryRelayPolicy.forBattery(9).mayRelay(isOwnSos = false))
        assertTrue(BatteryRelayPolicy.forBattery(9).mayRelay(isOwnSos = true))
        val limiter = EventRateLimiter()
        repeat(10) { assertTrue(limiter.allow("device", 1000L)) }
        assertFalse(limiter.allow("device", 1000L))
        assertTrue(limiter.allow("device", 61_000L))
    }

    @Test fun persistentLedgerRoundTripsPriorityAndSignedEvents() {
        val ledger = RelayLedger()
        assertTrue(ledger.accept("event", 12, 4, 123, ownUndeliveredSos = true, signedEvent = "{signed}"))
        val restored = RelayLedger()
        restored.restore(ledger.encode())
        assertEquals("{signed}", restored.stored().single().signedEvent)
        assertTrue(restored.stored().single().ownUndeliveredSos)
        assertEquals(4, restored.stored().single().priority)
    }

    @Test fun gatewayDeliveryReceiptsArePortableAndMarkEventsDelivered() {
        val ledger = RelayLedger()
        assertTrue(ledger.accept("event-1", 12, ownUndeliveredSos = true, signedEvent = "{signed}"))
        val receipt = DeliveredReceipt.decode(DeliveredReceipt(setOf("event-1")).encode())
        receipt.eventIds.forEach(ledger::markDelivered)
        assertTrue(ledger.stored().single().delivered)
    }

    @Test fun oneHundredNodeKotlinMeshHarnessConvergesWithinHopLimit() {
        val nodes = List(100) { RelayLedger() }
        val neighbors = List(100) { index ->
            setOf((index + 1) % 100, (index + 99) % 100, (index + 10) % 100, (index + 90) % 100)
        }
        val eventId = "synthetic-sos"
        val signedEvent = "{synthetic-signed-event}"
        assertTrue(nodes[50].accept(eventId, signedEvent.length, priority = 4,
            ownUndeliveredSos = true, signedEvent = signedEvent))
        var frontier = mapOf(50 to RelayFrame(signedEvent, hops = 0))
        repeat(12) {
            val next = linkedMapOf<Int, RelayFrame>()
            frontier.forEach { (sender, frame) ->
                val relayed = frame.relay() ?: return@forEach
                neighbors[sender].forEach { receiver ->
                    if (eventId !in nodes[receiver].ids()) {
                        val accepted = nodes[receiver].accept(eventId, signedEvent.length, priority = 4,
                            signedEvent = signedEvent, hops = relayed.hops, ttl = relayed.ttl)
                        if (accepted) next[receiver] = relayed
                    }
                }
            }
            frontier = next
        }
        assertTrue("event must reach the gateway at node 0", eventId in nodes[0].ids())
        assertTrue("event must converge to all simulated devices", nodes.all { eventId in it.ids() })
        assertTrue(nodes[0].stored().single().hops in 3..12)
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
