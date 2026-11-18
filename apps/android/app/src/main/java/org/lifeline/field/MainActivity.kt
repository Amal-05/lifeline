package org.lifeline.field

import android.Manifest
import android.app.Activity
import android.os.Bundle
import android.os.BatteryManager
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.AtomicFile
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.google.android.gms.nearby.Nearby
import com.google.android.gms.nearby.connection.*
import java.io.File
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val serviceId = "org.lifeline.mesh.v1"
    private lateinit var status: TextView
    private val ledger = RelayLedger()
    private val chunks = ChunkAssembler()
    private val rateLimiter = EventRateLimiter()
    private val handler = Handler(Looper.getMainLooper())
    private val storage by lazy { AtomicFile(File(filesDir, "lifeline-mesh-store.json")) }
    private val storageExecutor = Executors.newSingleThreadExecutor()
    private val connections = mutableSetOf<String>()
    private val strategy = Strategy.P2P_CLUSTER
    private val deviceId by lazy { Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown-device" }
    private var scanWindow: Runnable? = null
    private var scanCycle: Runnable? = null
    private val payloadCallback = object : PayloadCallback() {
        override fun onPayloadReceived(endpointId: String, payload: Payload) {
            if (payload.type != Payload.Type.BYTES) return
            runCatching {
                val received = payload.asBytes()!!
                val complete = if (org.json.JSONObject(received.decodeToString()).optString("kind") == "chunk") chunks.offer(ChunkPart.decode(received)) else received
                if (complete == null) return
                if (org.json.JSONObject(complete.decodeToString()).optString("kind") == "hello") {
                    val hello = PeerHello.decode(complete)
                    if (hello.protocolVersion != 1) return
                    val inventory = InventoryBloomFilter(encoded = hello.inventoryBloom)
                    ledger.stored().filter { !inventory.mightContain(it.eventId) && it.ttl > 0 && it.hops < 12 }.forEach { stored ->
                        sendEvent(endpointId, RelayFrame(stored.signedEvent, stored.hops, stored.ttl).encode())
                    }
                    return
                }
                MeshProtocol.decode(complete).let { frame ->
                val envelope = org.json.JSONObject(frame.event)
                if (!EventSignatureVerifier.verify(envelope)) return
                val id = envelope.getString("event_id")
                val origin = envelope.getString("device_id")
                if (!BatteryRelayPolicy.forBattery(batteryPercent()).mayRelay(origin == deviceId)) return
                if (!rateLimiter.allow(origin, System.currentTimeMillis())) return
                val priority = eventPriority(envelope)
                if (ledger.accept(id, frame.event.toByteArray().size, priority, signedEvent = frame.event,
                        hops = frame.hops, ttl = frame.ttl)) {
                    persistLedger()
                    frame.relay()?.let { relay -> connections.filter { it != endpointId }.forEach { peer -> sendEvent(peer, relay.encode()) } }
                }
            } }
        }
        override fun onPayloadTransferUpdate(endpointId: String, update: PayloadTransferUpdate) = Unit
    }
    private val connectionLifecycle = object : ConnectionLifecycleCallback() {
        override fun onConnectionInitiated(endpointId: String, info: ConnectionInfo) { Nearby.getConnectionsClient(this@MainActivity).acceptConnection(endpointId, payloadCallback) }
        override fun onConnectionResult(endpointId: String, result: ConnectionResolution) {
            if (result.status.isSuccess && connections.size < 4) { connections.add(endpointId); status.text = "Mesh connected · ${connections.size} peer(s)"; sendHello(endpointId) }
            else if (result.status.isSuccess) Nearby.getConnectionsClient(this@MainActivity).disconnectFromEndpoint(endpointId)
        }
        override fun onDisconnected(endpointId: String) { connections.remove(endpointId); status.text = "Mesh active · ${connections.size} peer(s)" }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        runCatching { storage.openRead().bufferedReader().use { ledger.restore(it.readText()) } }
        status = TextView(this).apply { text = "Offline field relay ready"; textSize = 20f }
        val start = Button(this).apply { text = "Join nearby mesh"; setOnClickListener { startMesh() } }
        setContentView(LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 64, 32, 32); addView(status); addView(start) })
    }
    private fun startMesh() {
        val required = if (android.os.Build.VERSION.SDK_INT >= 33) arrayOf(
            Manifest.permission.BLUETOOTH_ADVERTISE, Manifest.permission.BLUETOOTH_CONNECT,
            Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.NEARBY_WIFI_DEVICES,
        ) else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        val missing = required.filter { checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) { requestPermissions(missing.toTypedArray(), 73); return }
        val client = Nearby.getConnectionsClient(this)
        client.startAdvertising("lifeline", serviceId, connectionLifecycle, AdvertisingOptions.Builder().setStrategy(strategy).build())
        startDiscovery()
        status.text = "Discovering nearby peers…"
    }
    private fun startDiscovery() {
        val client = Nearby.getConnectionsClient(this)
        client.startDiscovery(serviceId, object : EndpointDiscoveryCallback() {
            override fun onEndpointFound(endpointId: String, info: DiscoveredEndpointInfo) { client.requestConnection("lifeline", endpointId, connectionLifecycle) }
            override fun onEndpointLost(endpointId: String) = Unit
        }, DiscoveryOptions.Builder().setStrategy(strategy).build())
        scheduleBatteryScan()
    }
    private fun scheduleBatteryScan() {
        scanCycle?.let(handler::removeCallbacks)
        scanWindow?.let(handler::removeCallbacks)
        val policy = BatteryRelayPolicy.forBattery(batteryPercent())
        if (policy.scanWindowMillis == null || policy.scanIntervalMillis == null) return
        val stop = Runnable { Nearby.getConnectionsClient(this).stopDiscovery() }
        scanWindow = stop
        handler.postDelayed(stop, policy.scanWindowMillis)
        val repeat = Runnable { startDiscovery() }
        scanCycle = repeat
        handler.postDelayed(repeat, policy.scanIntervalMillis)
    }
    private fun batteryPercent(): Int {
        val manager = getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        return manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).coerceIn(0, 100)
    }
    private fun internetAvailable(): Boolean {
        val manager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = manager.activeNetwork ?: return false
        return manager.getNetworkCapabilities(network)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
    }
    private fun sendHello(endpointId: String) {
        val inventory = InventoryBloomFilter()
        ledger.ids().forEach(inventory::add)
        val hlc = ledger.stored().mapNotNull { stored -> runCatching {
            val event = org.json.JSONObject(stored.signedEvent)
            event.getString("device_id") to event.getString("hlc")
        }.getOrNull() }.groupBy({ it.first }, { it.second }).mapValues { (_, values) -> values.maxOrNull() ?: "" }
        sendEvent(endpointId, PeerHello(1, deviceId, batteryPercent(), internetAvailable(), inventory.encode(), hlc).encode())
    }
    private fun persistLedger() {
        val snapshot = ledger.encode().toByteArray(Charsets.UTF_8)
        storageExecutor.execute {
            var output: java.io.FileOutputStream? = null
            try { val stream = storage.startWrite(); output = stream; stream.write(snapshot); storage.finishWrite(stream) }
            catch (_: Exception) { output?.let(storage::failWrite) }
        }
    }
    private fun eventPriority(envelope: org.json.JSONObject): Int {
        val type = envelope.optString("type")
        val payload = envelope.optJSONObject("payload") ?: return 1
        if (type == "sos.ping") return 4
        if (type != "sos.created") return 1
        val categories = payload.optJSONArray("categories")
        val needs = payload.optJSONArray("special_needs")
        val urgentCategory = (0 until (categories?.length() ?: 0)).any { categories?.optString(it) in listOf("medical", "trapped") }
        val urgentNeed = (0 until (needs?.length() ?: 0)).any { needs?.optString(it) in listOf("bedridden", "infant", "disabled") }
        return if (urgentCategory || urgentNeed) 4 else 3
    }
    private fun sendEvent(endpointId: String, bytes: ByteArray) {
        val client = Nearby.getConnectionsClient(this)
        if (bytes.size <= 32768) client.sendPayload(endpointId, Payload.fromBytes(bytes))
        else EventChunker.split(java.util.UUID.randomUUID().toString(), bytes).forEach { part ->
            client.sendPayload(endpointId, Payload.fromBytes(part.encode()))
        }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grants: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grants)
        if (requestCode == 73 && grants.isNotEmpty() && grants.all { it == android.content.pm.PackageManager.PERMISSION_GRANTED }) startMesh()
        else status.text = "Nearby permissions are required to join a mesh."
    }
    override fun onDestroy() { persistLedger(); scanWindow?.let(handler::removeCallbacks); scanCycle?.let(handler::removeCallbacks); Nearby.getConnectionsClient(this).stopAllEndpoints(); storageExecutor.shutdown(); super.onDestroy() }
}
