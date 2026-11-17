package org.lifeline.field

import org.json.JSONObject

data class RelayFrame(val event: String, val hops: Int, val ttl: Int = 12) {
    fun encode(): ByteArray {
        require(hops in 0..12 && ttl in 0..12)
        return JSONObject().put("event", event).put("hops", hops).put("ttl", ttl).toString().toByteArray()
    }
    fun relay(): RelayFrame? = if (ttl <= 0 || hops >= 12) null else copy(hops = hops + 1, ttl = ttl - 1)
    companion object { fun decode(bytes: ByteArray) = JSONObject(bytes.decodeToString()).let { RelayFrame(it.getString("event"), it.getInt("hops"), it.optInt("ttl", 12)) } }
}

class RelayLedger(private val maximumEvents: Int = 5000, private val maximumBytes: Int = 20 * 1024 * 1024) {
    private val events = LinkedHashMap<String, Int>()
    val byteCount: Int get() = events.values.sum()
    fun accept(eventId: String, size: Int): Boolean {
        if (eventId in events || size !in 1..32768 || events.size >= maximumEvents || byteCount + size > maximumBytes) return false
        events[eventId] = size
        return true
    }
}
