package org.lifeline.field

import android.Manifest
import android.app.Activity
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.google.android.gms.nearby.Nearby
import com.google.android.gms.nearby.connection.*

class MainActivity : Activity() {
    private val serviceId = "org.lifeline.field.mesh"
    private lateinit var status: TextView
    private val ledger = RelayLedger()
    private val connections = mutableSetOf<String>()
    private val strategy = Strategy.P2P_CLUSTER
    private val payloadCallback = object : PayloadCallback() {
        override fun onPayloadReceived(endpointId: String, payload: Payload) {
            if (payload.type != Payload.Type.BYTES) return
            runCatching { MeshProtocol.decode(payload.asBytes()!!).let { frame ->
                val id = org.json.JSONObject(frame.event).getString("event_id")
                if (ledger.accept(id, frame.event.toByteArray().size)) frame.relay()?.let { relay ->
                    connections.filter { it != endpointId }.forEach { peer ->
                        Nearby.getConnectionsClient(this@MainActivity).sendPayload(peer, Payload.fromBytes(relay.encode()))
                    }
                }
            } }
        }
        override fun onPayloadTransferUpdate(endpointId: String, update: PayloadTransferUpdate) = Unit
    }
    private val connectionLifecycle = object : ConnectionLifecycleCallback() {
        override fun onConnectionInitiated(endpointId: String, info: ConnectionInfo) { Nearby.getConnectionsClient(this@MainActivity).acceptConnection(endpointId, payloadCallback) }
        override fun onConnectionResult(endpointId: String, result: ConnectionResolution) {
            if (result.status.isSuccess && connections.size < 4) { connections.add(endpointId); status.text = "Mesh connected · ${connections.size} peer(s)" }
            else if (result.status.isSuccess) Nearby.getConnectionsClient(this@MainActivity).disconnectFromEndpoint(endpointId)
        }
        override fun onDisconnected(endpointId: String) { connections.remove(endpointId); status.text = "Mesh active · ${connections.size} peer(s)" }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
        client.startDiscovery(serviceId, object : EndpointDiscoveryCallback() {
            override fun onEndpointFound(endpointId: String, info: DiscoveredEndpointInfo) { client.requestConnection("lifeline", endpointId, connectionLifecycle) }
            override fun onEndpointLost(endpointId: String) = Unit
        }, DiscoveryOptions.Builder().setStrategy(strategy).build())
        status.text = "Discovering nearby peers…"
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grants: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grants)
        if (requestCode == 73 && grants.isNotEmpty() && grants.all { it == android.content.pm.PackageManager.PERMISSION_GRANTED }) startMesh()
        else status.text = "Nearby permissions are required to join a mesh."
    }
    override fun onDestroy() { Nearby.getConnectionsClient(this).stopAllEndpoints(); super.onDestroy() }
}
