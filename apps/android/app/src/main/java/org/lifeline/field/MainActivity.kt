package org.lifeline.field

import android.Manifest
import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.BatteryManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.AtomicFile
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.google.android.gms.nearby.Nearby
import com.google.android.gms.nearby.connection.AdvertisingOptions
import com.google.android.gms.nearby.connection.ConnectionInfo
import com.google.android.gms.nearby.connection.ConnectionLifecycleCallback
import com.google.android.gms.nearby.connection.ConnectionResolution
import com.google.android.gms.nearby.connection.DiscoveredEndpointInfo
import com.google.android.gms.nearby.connection.DiscoveryOptions
import com.google.android.gms.nearby.connection.EndpointDiscoveryCallback
import com.google.android.gms.nearby.connection.Payload
import com.google.android.gms.nearby.connection.PayloadCallback
import com.google.android.gms.nearby.connection.PayloadTransferUpdate
import com.google.android.gms.nearby.connection.Strategy
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

private const val DEFAULT_API = "http://10.0.2.2:8000/api/v1"
private val categories = listOf("medical", "trapped", "food", "evacuation", "missing", "other")
private val needsOptions = listOf("elderly", "infant", "bedridden", "disabled", "pregnant")

class MainActivity : ComponentActivity() {
    private val ledger = RelayLedger()
    private val chunkAssembler = ChunkAssembler()
    private val rateLimiter = EventRateLimiter()
    private val handler = Handler(Looper.getMainLooper())
    private val storage by lazy { AtomicFile(File(filesDir, "lifeline-mesh-store.json")) }
    private val identity by lazy { LocalEventIdentity(this) }
    private val connections = linkedSetOf<String>()
    private val serviceId = "org.lifeline.mesh.v1"
    private val strategy = Strategy.P2P_CLUSTER
    private val deviceId by lazy { identity.deviceId }
    private var apiBase by mutableStateOf(getPreferences(MODE_PRIVATE).getString("api_base", DEFAULT_API) ?: DEFAULT_API)
    private var accessToken by mutableStateOf("")
    private var coordinatorPublicKey by mutableStateOf(getPreferences(MODE_PRIVATE).getString("coordinator_public_key", "") ?: "")
    private var connected by mutableStateOf(false)
    private var working by mutableStateOf(false)
    private var notice by mutableStateOf("")
    private var meshStatus by mutableStateOf("Mesh is stopped")
    private var assignments by mutableStateOf(listOf<JSONObject>())
    private var queuedCount by mutableIntStateOf(0)
    private var scanWindow: Runnable? = null
    private var scanCycle: Runnable? = null
    private var linkRotation: Runnable? = null
    private var meshActive = false
    private val pendingAssignments = AtomicFile(File(filesDir, "lifeline-assignment-updates.json"))
    private val cachedAssignments = AtomicFile(File(filesDir, "lifeline-assignments.json"))

    private val payloadCallback = object : PayloadCallback() {
        override fun onPayloadReceived(endpointId: String, payload: Payload) {
            if (payload.type != Payload.Type.BYTES) return
            runCatching {
                val received = payload.asBytes() ?: return
                val complete = if (JSONObject(received.decodeToString()).optString("kind") == "chunk") {
                    chunkAssembler.offer(ChunkPart.decode(received))
                } else received
                if (complete == null) return
                val kind = JSONObject(complete.decodeToString()).optString("kind")
                if (kind == "delivered") {
                    DeliveredReceipt.decode(complete).eventIds.forEach(ledger::markDelivered)
                    persistLedger()
                    refreshQueuedCount()
                    connections.filter { it != endpointId }.forEach { sendEvent(it, complete) }
                    return
                }
                if (kind == "hello") {
                    val hello = PeerHello.decode(complete)
                    if (hello.protocolVersion != 1) return
                    val inventory = InventoryBloomFilter(encoded = hello.inventoryBloom)
                    ledger.stored().filter { !inventory.mightContain(it.eventId) && it.ttl > 0 && it.hops < 12 && isMeshSafe(it.signedEvent) }
                        .forEach { sendEvent(endpointId, RelayFrame(it.signedEvent, it.hops, it.ttl, it.priority.coerceAtMost(3)).encode()) }
                    return
                }
                val frame = MeshProtocol.decode(complete)
                val envelope = JSONObject(frame.event)
                if (!EventSignatureVerifier.verify(envelope) || !isMeshSafe(envelope)) return
                val origin = envelope.getString("device_id")
                if (!BatteryRelayPolicy.forBattery(batteryPercent()).mayRelay(origin == identityDeviceId())) return
                if (!rateLimiter.allow(origin, System.currentTimeMillis())) return
                val id = envelope.getString("event_id")
                val accepted = ledger.accept(id, frame.event.toByteArray().size, frame.priorityHint,
                    ownUndeliveredSos = false, signedEvent = frame.event, hops = frame.hops, ttl = frame.ttl)
                if (accepted) {
                    persistLedger()
                    frame.relay()?.let { relay -> connections.filter { it != endpointId }.forEach { sendEvent(it, relay.encode()) } }
                    refreshQueuedCount()
                }
            }
        }
        override fun onPayloadTransferUpdate(endpointId: String, update: PayloadTransferUpdate) = Unit
    }

    private val connectionLifecycle = object : ConnectionLifecycleCallback() {
        override fun onConnectionInitiated(endpointId: String, info: ConnectionInfo) {
            Nearby.getConnectionsClient(this@MainActivity).acceptConnection(endpointId, payloadCallback)
        }
        override fun onConnectionResult(endpointId: String, result: ConnectionResolution) {
            if (result.status.isSuccess && connections.size < 4) {
                connections.add(endpointId)
                meshStatus = "Mesh connected · ${connections.size} peer(s)"
                sendHello(endpointId)
                broadcastQueuedEvents()
            } else if (result.status.isSuccess) Nearby.getConnectionsClient(this@MainActivity).disconnectFromEndpoint(endpointId)
        }
        override fun onDisconnected(endpointId: String) {
            connections.remove(endpointId)
            meshStatus = if (connections.isEmpty()) "Looking for nearby peers" else "Mesh connected · ${connections.size} peer(s)"
        }
    }

    private val connectivityCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) { runOnUiThread { connected = true; refreshCoordinatorKey(); syncAndRefresh() } }
        override fun onLost(network: Network) { runOnUiThread { connected = internetAvailable() } }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        runCatching { storage.openRead().bufferedReader().use { ledger.restore(it.readText()) } }
        connected = internetAvailable()
        assignments = readJsonArray(cachedAssignments).toList()
        refreshQueuedCount()
        val connectivity = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        connectivity.registerNetworkCallback(NetworkRequest.Builder().addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build(), connectivityCallback)
        setContent {
            MaterialTheme {
                LifelineApp(
                    apiBase = apiBase, accessToken = accessToken, online = connected, busy = working,
                    message = notice, meshStatus = meshStatus, queuedEvents = queuedCount, assignments = assignments,
                    onApiBaseChange = { apiBase = it.trimEnd('/'); getPreferences(MODE_PRIVATE).edit().putString("api_base", apiBase).apply() },
                    onLogin = ::login, onLogout = ::logout, onSaveSos = ::saveSos,
                    onSync = ::syncAndRefresh, onJoinMesh = ::startMesh, onStopMesh = ::stopMesh,
                    onAssignmentStatus = ::updateAssignment,
                )
            }
        }
        if (connected) { refreshCoordinatorKey(); syncAndRefresh() }
    }

    private fun identityDeviceId(): String = identity.deviceId

    private fun refreshCoordinatorKey() {
        if (!connected) return
        lifecycleScope.launch {
            runCatching { JSONObject(apiRequest("/config", "GET", null, false)).optString("coordinator_public_key") }
                .onSuccess { value ->
                    coordinatorPublicKey = value.takeUnless { it.isBlank() || it == "null" }.orEmpty()
                    getPreferences(MODE_PRIVATE).edit().putString("coordinator_public_key", coordinatorPublicKey).apply()
                }
                .onFailure { notice = "Coordinator encryption key could not be refreshed; mesh relay is unavailable until it is cached." }
        }
    }

    private fun login(email: String, password: String) {
        lifecycleScope.launch {
            working = true
            runCatching {
                val result = JSONObject(apiRequest("/auth/login", "POST", JSONObject().put("email", email).put("password", password).toString(), false))
                accessToken = result.getString("access_token")
                notice = "Signed in. Refreshing assignments."
                syncAndRefresh()
            }.onFailure { notice = "Sign in failed: ${it.message ?: "Check your connection and account."}" }
            working = false
        }
    }

    private fun logout() {
        accessToken = ""
        notice = "Signed out. Your saved SOS events remain on this device."
    }

    private fun saveSos(people: Int, category: String, needs: List<String>, note: String, latitude: Double?, longitude: Double?) {
        runCatching {
            val event = identity.createSos(people, category, needs, note, latitude, longitude,
                coordinatorPublicKey.takeIf { it.isNotBlank() })
            val text = event.toString()
            val id = event.getString("event_id")
            val urgent = category in setOf("medical", "trapped") || needs.any { it in setOf("bedridden", "infant", "disabled") }
            check(ledger.accept(id, text.toByteArray().size, if (urgent) 4 else 3,
                ownUndeliveredSos = true, signedEvent = text)) { "Local SOS store is full" }
            persistLedger()
            broadcastQueuedEvents()
            refreshQueuedCount()
            notice = if (isMeshSafe(event)) "SOS encrypted for the coordinator and saved on this phone."
                else "SOS saved on this phone; mesh relay needs a cached coordinator key."
            if (connected) syncAndRefresh()
        }.onFailure { notice = "Could not save SOS: ${it.message ?: "Please retry."}" }
    }

    private fun syncAndRefresh() {
        if (!connected) { notice = "Offline. SOS and assignment updates remain saved on this device."; return }
        lifecycleScope.launch {
            working = true
            runCatching {
                if (accessToken.isNotBlank()) flushAssignmentUpdates()
                val stored = ledger.stored()
                val events = JSONArray()
                stored.forEach { events.put(JSONObject(it.signedEvent)) }
                val highest = highestHlcByDevice(stored)
                val bundle = JSONObject().put("protocol_version", 1).put("events", events)
                    .put("known_event_ids", JSONArray(ledger.ids().toList())).put("highest_hlc_by_device", JSONObject(highest))
                val response = JSONObject(apiRequest("/sync", "POST", bundle.toString(), false))
                val accepted = response.optJSONArray("accepted_ids") ?: JSONArray()
                val rejected = response.optJSONArray("rejected") ?: JSONArray()
                for (i in 0 until accepted.length()) ledger.markDelivered(accepted.getString(i))
                if (accepted.length() > 0) {
                    persistLedger()
                    val receipt = DeliveredReceipt((0 until accepted.length()).map { accepted.getString(it) }.toSet()).encode()
                    connections.forEach { sendEvent(it, receipt) }
                }
                val missing = response.optJSONArray("missing_events") ?: JSONArray()
                for (i in 0 until missing.length()) {
                    val item = missing.getJSONObject(i)
                    if (!EventSignatureVerifier.verify(item)) continue
                    val encoded = item.toString()
                    ledger.accept(item.getString("event_id"), encoded.toByteArray().size, eventPriority(item),
                        delivered = true, signedEvent = encoded, hops = item.optInt("hops", 0))
                }
                persistLedger()
                refreshQueuedCount()
                if (accessToken.isNotBlank()) refreshAssignments()
                notice = if (rejected.length() == 0) "Sync complete · ${accepted.length()} event(s) acknowledged."
                    else "${accepted.length()} event(s) acknowledged; ${rejected.length()} rejected: ${rejected.optJSONObject(0)?.optString("reason") ?: "check protocol version"}"
            }.onFailure { notice = if (it is java.net.UnknownHostException || it is java.net.ConnectException) "Gateway unavailable. Saved events will sync when the network returns." else "Sync failed: ${it.message ?: "Please retry."}" }
            working = false
        }
    }

    private suspend fun refreshAssignments() {
        val data = JSONArray(apiRequest("/assignments/mine", "GET", null, true))
        assignments = data.toList()
        writeJsonArray(cachedAssignments, data)
    }

    private fun updateAssignment(id: String, status: String) {
        val current = assignments.map { item -> if (item.optString("assignment_id") == id) JSONObject(item.toString()).put("status", status) else item }
        assignments = current
        writeJsonArray(cachedAssignments, JSONArray(current))
        if (!connected) {
            queueAssignmentUpdate(id, status)
            notice = "Status saved offline. It will sync when a connection returns."
        } else lifecycleScope.launch {
            runCatching {
                apiRequest("/assignments/$id", "PATCH", JSONObject().put("status", status).toString(), true)
                refreshAssignments()
                notice = "Assignment updated."
            }.onFailure {
                queueAssignmentUpdate(id, status)
                notice = "Status saved locally; server update failed and is queued: ${it.message}"
            }
        }
    }

    private fun queueAssignmentUpdate(id: String, status: String) {
        val old = readJsonArray(pendingAssignments).toList().filterNot { it.optString("assignment_id") == id }
        writeJsonArray(pendingAssignments, old + JSONObject().put("assignment_id", id).put("status", status))
    }

    private suspend fun flushAssignmentUpdates() {
        val pending = readJsonArray(pendingAssignments)
        if (pending.length() == 0) return
        for (i in 0 until pending.length()) {
            val item = pending.getJSONObject(i)
            apiRequest("/assignments/${item.getString("assignment_id")}", "PATCH",
                JSONObject().put("status", item.getString("status")).toString(), true)
        }
        writeJsonArray(pendingAssignments, JSONArray())
    }

    private suspend fun apiRequest(path: String, method: String, body: String?, authenticated: Boolean): String = withContext(Dispatchers.IO) {
        val connection = (URL("${apiBase.trimEnd('/')}$path").openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 20_000
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
            if (authenticated && accessToken.isNotBlank()) setRequestProperty("Authorization", "Bearer $accessToken")
        }
        try {
            body?.let { connection.outputStream.use { stream -> stream.write(it.toByteArray(Charsets.UTF_8)) } }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (status !in 200..299) throw IllegalStateException("HTTP $status: ${runCatching { JSONObject(text).optString("detail", text) }.getOrDefault(text)}")
            text
        } finally { connection.disconnect() }
    }

    private fun highestHlcByDevice(events: List<RelayLedger.Stored>): Map<String, String> = events.mapNotNull { item -> runCatching {
        val event = JSONObject(item.signedEvent)
        event.getString("device_id") to event.getString("hlc")
    }.getOrNull() }.groupBy({ it.first }, { it.second }).mapValues { (_, values) -> values.maxOrNull().orEmpty() }

    private fun readJsonArray(file: AtomicFile): JSONArray = runCatching { file.openRead().bufferedReader().use { JSONArray(it.readText()) } }.getOrDefault(JSONArray())
    private fun writeJsonArray(file: AtomicFile, data: JSONArray) {
        val output = file.startWrite()
        try { output.write(data.toString().toByteArray()); file.finishWrite(output) }
        catch (failure: Exception) { file.failWrite(output); throw failure }
    }
    private fun writeJsonArray(file: AtomicFile, data: List<JSONObject>) = writeJsonArray(file, JSONArray(data))
    private fun refreshQueuedCount() { queuedCount = ledger.stored().count { !it.delivered } }
    private fun persistLedger() {
        val snapshot = ledger.encode().toByteArray(Charsets.UTF_8)
        var output: java.io.FileOutputStream? = null
        try { val stream = storage.startWrite(); output = stream; stream.write(snapshot); storage.finishWrite(stream) }
        catch (failure: Exception) { output?.let(storage::failWrite); throw failure }
    }

    private fun startMesh() {
        if (meshActive) return
        val required = if (android.os.Build.VERSION.SDK_INT >= 33) arrayOf(
            Manifest.permission.BLUETOOTH_ADVERTISE, Manifest.permission.BLUETOOTH_CONNECT,
            Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.NEARBY_WIFI_DEVICES,
        ) else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        val missing = required.filter { checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) { requestPermissions(missing.toTypedArray(), 73); return }
        val client = Nearby.getConnectionsClient(this)
        client.startAdvertising("L1-${deviceId.take(8)}", serviceId, connectionLifecycle, AdvertisingOptions.Builder().setStrategy(strategy).build())
        meshActive = true
        startDiscovery()
        scheduleLinkRotation()
        meshStatus = "Discovering nearby peers"
    }
    private fun stopMesh() {
        meshActive = false
        scanWindow?.let(handler::removeCallbacks); scanCycle?.let(handler::removeCallbacks); linkRotation?.let(handler::removeCallbacks)
        Nearby.getConnectionsClient(this).stopAdvertising(); Nearby.getConnectionsClient(this).stopDiscovery()
        Nearby.getConnectionsClient(this).stopAllEndpoints(); connections.clear(); meshStatus = "Mesh is stopped"
    }
    private fun startDiscovery() {
        val client = Nearby.getConnectionsClient(this)
        client.startDiscovery(serviceId, object : EndpointDiscoveryCallback() {
            override fun onEndpointFound(endpointId: String, info: DiscoveredEndpointInfo) { client.requestConnection("L1-${deviceId.take(8)}", endpointId, connectionLifecycle) }
            override fun onEndpointLost(endpointId: String) = Unit
        }, DiscoveryOptions.Builder().setStrategy(strategy).build())
        scheduleBatteryScan()
    }
    private fun scheduleBatteryScan() {
        scanCycle?.let(handler::removeCallbacks); scanWindow?.let(handler::removeCallbacks)
        val policy = BatteryRelayPolicy.forBattery(batteryPercent())
        if (policy.scanWindowMillis == null || policy.scanIntervalMillis == null) return
        val stop = Runnable { Nearby.getConnectionsClient(this).stopDiscovery() }
        scanWindow = stop; handler.postDelayed(stop, policy.scanWindowMillis)
        val repeat = Runnable { startDiscovery() }
        scanCycle = repeat; handler.postDelayed(repeat, policy.scanIntervalMillis)
    }
    private fun batteryPercent(): Int = (getSystemService(Context.BATTERY_SERVICE) as BatteryManager)
        .getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).coerceIn(0, 100)
    private fun internetAvailable(): Boolean {
        val manager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = manager.activeNetwork ?: return false
        return manager.getNetworkCapabilities(network)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
    }
    private fun sendHello(endpointId: String) {
        val inventory = InventoryBloomFilter(); ledger.ids().forEach(inventory::add)
        val high = highestHlcByDevice(ledger.stored())
        sendEvent(endpointId, PeerHello(1, deviceId, batteryPercent(), internetAvailable(), inventory.encode(), high).encode())
    }
    private fun sendEvent(endpointId: String, bytes: ByteArray) {
        val client = Nearby.getConnectionsClient(this)
        if (bytes.size <= 32768) client.sendPayload(endpointId, Payload.fromBytes(bytes))
        else EventChunker.split(java.util.UUID.randomUUID().toString(), bytes).forEach { client.sendPayload(endpointId, Payload.fromBytes(it.encode())) }
    }
    private fun broadcastQueuedEvents() {
        ledger.stored().filter { !it.delivered && isMeshSafe(it.signedEvent) }.forEach { stored ->
            val frame = RelayFrame(stored.signedEvent, stored.hops, stored.ttl, stored.priority.coerceAtMost(3)).encode()
            connections.forEach { endpoint -> sendEvent(endpoint, frame) }
        }
    }
    private fun eventPriority(event: JSONObject): Int {
        val payload = event.optJSONObject("payload") ?: return 1
        val type = event.optString("type")
        if (type == "sos.ping") return 4
        if (type != "sos.created") return 1
        val cats = payload.optJSONArray("categories")
        val needs = payload.optJSONArray("special_needs")
        val urgent = (0 until (cats?.length() ?: 0)).any { cats?.optString(it) in listOf("medical", "trapped") } ||
            (0 until (needs?.length() ?: 0)).any { needs?.optString(it) in listOf("bedridden", "infant", "disabled") }
        return if (urgent) 4 else 3
    }

    private fun isMeshSafe(signedEvent: String): Boolean = runCatching { isMeshSafe(JSONObject(signedEvent)) }.getOrDefault(false)
    private fun isMeshSafe(event: JSONObject): Boolean = event.optJSONObject("payload")?.optJSONObject("_sealed_payload")
        ?.optString("algorithm") == "libsodium-sealed-box-v1"

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grants: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grants)
        if (requestCode == 73 && grants.isNotEmpty() && grants.all { it == android.content.pm.PackageManager.PERMISSION_GRANTED }) startMesh()
        else meshStatus = "Nearby permissions are needed for mesh relay."
    }
    override fun onDestroy() {
        runCatching { writeJsonArray(cachedAssignments, assignments) }
        persistLedger()
        val connectivity = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        runCatching { connectivity.unregisterNetworkCallback(connectivityCallback) }
        stopMesh()
        super.onDestroy()
    }

    private fun scheduleLinkRotation() {
        linkRotation?.let(handler::removeCallbacks)
        val rotate = Runnable {
            if (meshActive) {
                Nearby.getConnectionsClient(this).stopDiscovery()
                connections.toList().forEach { Nearby.getConnectionsClient(this).disconnectFromEndpoint(it) }
                connections.clear()
                startDiscovery()
                scheduleLinkRotation()
            }
        }
        linkRotation = rotate
        handler.postDelayed(rotate, 60_000)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LifelineApp(
    apiBase: String, accessToken: String, online: Boolean, busy: Boolean, message: String,
    meshStatus: String, queuedEvents: Int, assignments: List<JSONObject>,
    onApiBaseChange: (String) -> Unit, onLogin: (String, String) -> Unit, onLogout: () -> Unit,
    onSaveSos: (Int, String, List<String>, String, Double?, Double?) -> Unit,
    onSync: () -> Unit, onJoinMesh: () -> Unit, onStopMesh: () -> Unit,
    onAssignmentStatus: (String, String) -> Unit,
) {
    var tab by remember { mutableIntStateOf(0) }
    var offlineMode by remember { mutableStateOf(false) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(message) { if (message.isNotBlank()) snackbar.showSnackbar(message) }
    if (accessToken.isBlank() && !offlineMode) {
        LoginScreen(apiBase, busy, message, onApiBaseChange, onLogin, onContinueOffline = { offlineMode = true })
        return
    }
    Scaffold(
        topBar = { TopAppBar(title = { Column { Text("Lifeline", fontWeight = FontWeight.Bold); Text(if (online) "Connected" else "Offline · saved data is available") } }) },
        bottomBar = { NavigationBar {
            listOf("SOS", "Assignments", "Mesh", "Settings").forEachIndexed { index, label ->
                NavigationBarItem(selected = tab == index, onClick = { tab = index }, icon = { Text(listOf("!", "✓", "◉", "⚙")[index]) }, label = { Text(label) })
            }
        } }, snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        when (tab) {
            0 -> SosScreen(queuedEvents, busy, Modifier.padding(padding), onSaveSos, onSync)
            1 -> if (accessToken.isBlank()) Column(Modifier.padding(padding).padding(20.dp)) { Text("Sign in to view and update team assignments.") } else AssignmentsScreen(assignments, online, Modifier.padding(padding), onAssignmentStatus, onSync)
            2 -> MeshScreen(meshStatus, Modifier.padding(padding), onJoinMesh, onStopMesh)
            else -> SettingsScreen(apiBase, online, accessToken.isNotBlank(), Modifier.padding(padding), onApiBaseChange, onSync, onLogout, onSignIn = { offlineMode = false })
        }
    }
}

@Composable
private fun LoginScreen(apiBase: String, busy: Boolean, message: String, onApiBase: (String) -> Unit, onLogin: (String, String) -> Unit, onContinueOffline: () -> Unit) {
    var email by remember { mutableStateOf("") }; var password by remember { mutableStateOf("") }
    Surface(Modifier.fillMaxSize()) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Spacer(Modifier.height(18.dp)); Text("Lifeline field app", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
            Text("Save SOS requests offline, sync them when a gateway returns, and update team assignments in the field.")
            OutlinedTextField(apiBase, onApiBase, Modifier.fillMaxWidth(), label = { Text("API address") }, singleLine = true)
            OutlinedTextField(email, { email = it }, Modifier.fillMaxWidth(), label = { Text("Email") }, singleLine = true)
            OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Password") }, singleLine = true)
            Button(onClick = { onLogin(email.trim(), password) }, enabled = !busy && email.isNotBlank() && password.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
                if (busy) CircularProgressIndicator(Modifier.size(20.dp)) else Text("Sign in")
            }
            OutlinedButton(onClick = onContinueOffline, modifier = Modifier.fillMaxWidth()) { Text("Continue to offline SOS") }
            Text("Sign in to load assignments. SOS capture works offline without an account.", style = MaterialTheme.typography.bodySmall)
            if (message.isNotBlank()) Text(message, color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun SosScreen(queued: Int, busy: Boolean, modifier: Modifier, onSave: (Int, String, List<String>, String, Double?, Double?) -> Unit, onSync: () -> Unit) {
    var people by remember { mutableStateOf("1") }; var category by remember { mutableStateOf("medical") }
    var selectedNeeds by remember { mutableStateOf(setOf<String>()) }; var note by remember { mutableStateOf("") }
    var latitude by remember { mutableStateOf("") }; var longitude by remember { mutableStateOf("") }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Emergency SOS", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        Text("Lifeline supports rescue coordination and does not replace official emergency services.", style = MaterialTheme.typography.bodyMedium)
        Text("The request is signed and saved on this phone before network sync.")
        OutlinedTextField(people, { people = it.filter(Char::isDigit).take(3) }, Modifier.fillMaxWidth(), label = { Text("People needing help") }, singleLine = true)
        Text("Situation", style = MaterialTheme.typography.titleMedium)
        FlowChips(categories, category, { category = it })
        Text("Special needs", style = MaterialTheme.typography.titleMedium)
        needsOptions.chunked(3).forEach { row -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            row.forEach { item -> FilterChip(item in selectedNeeds, { selectedNeeds = if (item in selectedNeeds) selectedNeeds - item else selectedNeeds + item }, label = { Text(item) }) }
        } }
        OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), label = { Text("Short description (optional)") }, minLines = 2)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(latitude, { latitude = it }, Modifier.weight(1f), label = { Text("Latitude") }, singleLine = true)
            OutlinedTextField(longitude, { longitude = it }, Modifier.weight(1f), label = { Text("Longitude") }, singleLine = true)
        }
        Text("Coordinates are optional. Enter them if you know the location.", style = MaterialTheme.typography.bodySmall)
        Button(onClick = { onSave((people.toIntOrNull() ?: 1).coerceIn(1, 100), category, selectedNeeds.toList(), note,
            latitude.toDoubleOrNull(), longitude.toDoubleOrNull()) }, enabled = !busy && (latitude.isBlank() == longitude.isBlank()), modifier = Modifier.fillMaxWidth()) { Text("Save SOS on this phone") }
        OutlinedButton(onClick = onSync, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("Sync now · $queued waiting") }
    }
}

@Composable
private fun FlowChips(values: List<String>, selected: String, onSelect: (String) -> Unit) {
    values.chunked(3).forEach { row -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        row.forEach { value -> FilterChip(selected == value, { onSelect(value) }, label = { Text(value) }) }
    } }
}

@Composable
private fun AssignmentsScreen(assignments: List<JSONObject>, online: Boolean, modifier: Modifier,
                              onStatus: (String, String) -> Unit, onRefresh: () -> Unit) {
    Column(modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("My assignments", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            OutlinedButton(onClick = onRefresh, enabled = online) { Text("Refresh") }
        }
        if (assignments.isEmpty()) Text("No assignments cached. Connect and refresh to load your team's tasks.", Modifier.padding(8.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(assignments, key = { it.optString("assignment_id") }) { item ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Urgency ${item.optInt("urgency")} · ${item.optString("status")}", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                        Text("${item.optInt("people_count", 1)} people · ${jsonArrayText(item.optJSONArray("categories"))}")
                        Text("Needs: ${jsonArrayText(item.optJSONArray("special_needs"))}")
                        val location = item.optJSONArray("location")
                        if (location != null && location.length() == 2) Text("Coordinates: ${location.optDouble(1)}, ${location.optDouble(0)}")
                        Text("ETA: ${item.optInt("eta_s").takeIf { it > 0 }?.let { "${(it + 59) / 60} min" } ?: "not available"}")
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            listOf("en_route", "on_site", "rescued", "unreachable").forEach { status ->
                                OutlinedButton(onClick = { onStatus(item.optString("assignment_id"), status) }) { Text(status.replace('_', ' ')) }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun MeshScreen(status: String, modifier: Modifier, onJoin: () -> Unit, onStop: () -> Unit) {
    Column(modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Nearby mesh", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("$status · up to four peers · signed and encrypted SOS only")
        Text("Connect to the gateway once to cache its public encryption key. A device with Internet can upload the shared SOS pool and return delivery receipts to peers.")
        Button(onClick = onJoin, modifier = Modifier.fillMaxWidth()) { Text("Join nearby mesh") }
        OutlinedButton(onClick = onStop, modifier = Modifier.fillMaxWidth()) { Text("Stop mesh") }
    }
}

@Composable
private fun SettingsScreen(apiBase: String, online: Boolean, signedIn: Boolean, modifier: Modifier, onApiBase: (String) -> Unit,
                           onSync: () -> Unit, onLogout: () -> Unit, onSignIn: () -> Unit) {
    var value by remember(apiBase) { mutableStateOf(apiBase) }
    Column(modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Device settings", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(if (online) "Gateway reachable" else "Offline mode")
        OutlinedTextField(value, { value = it }, Modifier.fillMaxWidth(), label = { Text("Gateway API URL") }, singleLine = true)
        Button(onClick = { onApiBase(value) }, modifier = Modifier.fillMaxWidth()) { Text("Save gateway") }
        OutlinedButton(onClick = onSync, enabled = online, modifier = Modifier.fillMaxWidth()) { Text("Sync saved events") }
        if (signedIn) OutlinedButton(onClick = onLogout, modifier = Modifier.fillMaxWidth()) { Text("Sign out") }
        else OutlinedButton(onClick = onSignIn, modifier = Modifier.fillMaxWidth()) { Text("Sign in for assignments") }
    }
}

private fun JSONArray.toList(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
private fun jsonArrayText(array: JSONArray?): String = array?.let { (0 until it.length()).map { i -> it.optString(i) }.joinToString(", ") }?.ifBlank { "none listed" } ?: "none listed"
