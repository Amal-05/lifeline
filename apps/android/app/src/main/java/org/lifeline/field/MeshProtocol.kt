package org.lifeline.field

import org.json.JSONObject
import java.security.MessageDigest
import java.util.Base64
import java.util.ArrayDeque

data class RelayFrame(val event: String, val hops: Int, val ttl: Int = 12) {
    fun encode(): ByteArray {
        require(hops in 0..12 && ttl in 0..12)
        return JSONObject().put("event", event).put("hops", hops).put("ttl", ttl).toString().toByteArray()
    }
    fun relay(): RelayFrame? = if (ttl <= 0 || hops >= 12) null else copy(hops = hops + 1, ttl = ttl - 1)
    companion object { fun decode(bytes: ByteArray) = JSONObject(bytes.decodeToString()).let { RelayFrame(it.getString("event"), it.getInt("hops"), it.optInt("ttl", 12)) } }
}

data class ChunkPart(val transferId: String, val index: Int, val total: Int, val sha256: String, val bytes: ByteArray) {
    fun encode(): ByteArray = JSONObject().put("kind", "chunk").put("transfer_id", transferId)
        .put("index", index).put("total", total).put("sha256", sha256)
        .put("data", Base64.getEncoder().encodeToString(bytes)).toString().toByteArray()
    companion object {
        fun decode(data: ByteArray) = JSONObject(data.decodeToString()).let {
            ChunkPart(it.getString("transfer_id"), it.getInt("index"), it.getInt("total"),
                it.getString("sha256"), Base64.getDecoder().decode(it.getString("data")))
        }
    }
}

object EventChunker {
    const val CHUNK_SIZE = 23 * 1024
    fun split(transferId: String, payload: ByteArray): List<ChunkPart> {
        require(payload.isNotEmpty() && payload.size <= 20 * 1024 * 1024)
        val hash = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        val chunks = payload.toList().chunked(CHUNK_SIZE).map { it.toByteArray() }
        return chunks.mapIndexed { index, bytes -> ChunkPart(transferId, index, chunks.size, hash, bytes) }
    }
}

class ChunkAssembler(private val maximumBytes: Int = 20 * 1024 * 1024) {
    private data class Partial(val total: Int, val hash: String, val chunks: MutableMap<Int, ByteArray>)
    private val transfers = mutableMapOf<String, Partial>()
    private var storedBytes = 0
    fun offer(part: ChunkPart): ByteArray? {
        if (part.transferId.length !in 1..64 || part.total !in 1..1024 || part.index !in 0 until part.total ||
            part.bytes.size !in 1..EventChunker.CHUNK_SIZE || !part.sha256.matches(Regex("[0-9a-f]{64}"))) return null
        val partial = transfers[part.transferId] ?: run {
            if (transfers.size >= 100) return null
            Partial(part.total, part.sha256, mutableMapOf()).also { transfers[part.transferId] = it }
        }
        if (partial.total != part.total || partial.hash != part.sha256) return null
        if (!partial.chunks.containsKey(part.index)) {
            if (storedBytes + part.bytes.size > maximumBytes) return null
            partial.chunks[part.index] = part.bytes
            storedBytes += part.bytes.size
        }
        if (partial.chunks.size != partial.total) return null
        val joined = (0 until partial.total).flatMap { partial.chunks.getValue(it).asIterable() }.toByteArray()
        transfers.remove(part.transferId)
        storedBytes -= partial.chunks.values.sumOf { it.size }
        val actual = MessageDigest.getInstance("SHA-256").digest(joined).joinToString("") { "%02x".format(it) }
        return joined.takeIf { actual == partial.hash }
    }
}

class RelayLedger(private val maximumEvents: Int = 5000, private val maximumBytes: Int = 20 * 1024 * 1024) {
    data class Stored(val eventId: String, val size: Int, val priority: Int, val createdAtMillis: Long,
                      val delivered: Boolean, val ownUndeliveredSos: Boolean, val signedEvent: String,
                      val hops: Int, val ttl: Int)
    private val events = LinkedHashMap<String, Stored>()
    val byteCount: Int get() = events.values.sumOf { it.size }
    fun accept(eventId: String, size: Int, priority: Int = 0, createdAtMillis: Long = System.currentTimeMillis(),
               delivered: Boolean = false, ownUndeliveredSos: Boolean = false, signedEvent: String = "",
               hops: Int = 0, ttl: Int = 12): Boolean {
        if (eventId in events || size !in 1..maximumBytes || priority !in 0..4 || hops !in 0..12 || ttl !in 0..12) return false
        while (events.size >= maximumEvents || byteCount + size > maximumBytes) {
            val victim = events.values.filterNot { it.ownUndeliveredSos }
                .minWithOrNull(compareBy<Stored> { if (it.delivered) 0 else 1 }.thenBy { it.priority }.thenBy { it.createdAtMillis })
                ?: return false
            events.remove(victim.eventId)
        }
        events[eventId] = Stored(eventId, size, priority, createdAtMillis, delivered, ownUndeliveredSos, signedEvent, hops, ttl)
        return true
    }
    fun ids(): Set<String> = events.keys.toSet()
    fun stored(): List<Stored> = events.values.toList()
    fun markDelivered(eventId: String) { events[eventId]?.let { events[eventId] = it.copy(delivered = true) } }
    fun encode(): String = org.json.JSONArray().also { json -> events.values.forEach { event ->
        json.put(JSONObject().put("event_id", event.eventId).put("size", event.size)
            .put("priority", event.priority).put("created_at", event.createdAtMillis)
            .put("delivered", event.delivered).put("own_undelivered_sos", event.ownUndeliveredSos)
            .put("signed_event", event.signedEvent).put("hops", event.hops).put("ttl", event.ttl))
    } }.toString()
    fun restore(encoded: String) {
        runCatching {
            val rows = org.json.JSONArray(encoded)
            for (index in 0 until rows.length()) {
                val row = rows.getJSONObject(index)
                accept(row.getString("event_id"), row.getInt("size"), row.getInt("priority"),
                    row.getLong("created_at"), row.getBoolean("delivered"),
                    row.getBoolean("own_undelivered_sos"), row.getString("signed_event"),
                    row.optInt("hops", 0), row.optInt("ttl", 12))
            }
        }
    }
}

data class PeerHello(
    val protocolVersion: Int,
    val deviceId: String,
    val batteryPct: Int,
    val internet: Boolean,
    val inventoryBloom: String,
    val highestHlcByOrigin: Map<String, String>,
) {
    fun encode(): ByteArray = JSONObject().put("kind", "hello").put("protocol_version", protocolVersion)
        .put("device_id", deviceId).put("battery_pct", batteryPct).put("internet", internet)
        .put("inventory_bloom", inventoryBloom).put("highest_hlc_by_origin", JSONObject(highestHlcByOrigin))
        .toString().toByteArray()

    companion object {
        fun decode(bytes: ByteArray): PeerHello = JSONObject(bytes.decodeToString()).let { json ->
            require(json.getString("kind") == "hello")
            val hlc = mutableMapOf<String, String>()
            val input = json.getJSONObject("highest_hlc_by_origin")
            input.keys().forEach { key -> hlc[key] = input.getString(key) }
            PeerHello(json.getInt("protocol_version"), json.getString("device_id"),
                json.getInt("battery_pct"), json.getBoolean("internet"), json.getString("inventory_bloom"), hlc)
        }
    }
}

class InventoryBloomFilter(private val bitCount: Int = 2048, private val hashCount: Int = 4, encoded: String? = null) {
    private val bits = if (encoded == null) ByteArray((bitCount + 7) / 8) else Base64.getUrlDecoder().decode(encoded)
    init { require(bitCount >= 64 && hashCount in 1..8 && bits.size == (bitCount + 7) / 8) }
    private fun indexes(value: String): List<Int> {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray())
        val first = java.nio.ByteBuffer.wrap(digest).getLong(0)
        val second = java.nio.ByteBuffer.wrap(digest).getLong(8) or 1L
        return (0 until hashCount).map { Math.floorMod(first + it * second, bitCount.toLong()).toInt() }
    }
    fun add(value: String) { indexes(value).forEach { bits[it / 8] = (bits[it / 8].toInt() or (1 shl (it % 8))).toByte() } }
    fun mightContain(value: String): Boolean = indexes(value).all { (bits[it / 8].toInt() and (1 shl (it % 8))) != 0 }
    fun encode(): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bits)
}

data class BatteryRelayPolicy(val scanWindowMillis: Long?, val scanIntervalMillis: Long?, val relayOtherEvents: Boolean) {
    fun mayRelay(isOwnSos: Boolean): Boolean = relayOtherEvents || isOwnSos
    companion object {
        fun forBattery(percent: Int): BatteryRelayPolicy {
            require(percent in 0..100)
            return when {
                percent < 10 -> BatteryRelayPolicy(null, null, false)
                percent < 30 -> BatteryRelayPolicy(10_000, 60_000, true)
                else -> BatteryRelayPolicy(null, null, true)
            }
        }
    }
}

class EventRateLimiter(private val maximum: Int = 10, private val windowMillis: Long = 60_000) {
    private val arrivals = mutableMapOf<String, ArrayDeque<Long>>()
    fun allow(origin: String, nowMillis: Long): Boolean {
        val times = arrivals.getOrPut(origin) { ArrayDeque() }
        while (times.isNotEmpty() && nowMillis - times.first() >= windowMillis) times.removeFirst()
        if (times.size >= maximum) return false
        times.addLast(nowMillis)
        return true
    }
}
