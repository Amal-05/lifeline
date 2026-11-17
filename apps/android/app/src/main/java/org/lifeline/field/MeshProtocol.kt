package org.lifeline.field

import org.json.JSONObject
import java.security.MessageDigest
import java.util.Base64

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
    private val events = LinkedHashMap<String, Int>()
    val byteCount: Int get() = events.values.sum()
    fun accept(eventId: String, size: Int): Boolean {
        if (eventId in events || size !in 1..maximumBytes || events.size >= maximumEvents || byteCount + size > maximumBytes) return false
        events[eventId] = size
        return true
    }
}
