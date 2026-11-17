package org.lifeline.field

import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.json.JSONArray
import org.json.JSONObject
import java.util.Base64

object EventSignatureVerifier {
    fun verify(event: JSONObject): Boolean = runCatching {
        if (event.optInt("protocol_version") != 1) return false
        val deviceId = event.getString("device_id")
        val decoder = Base64.getUrlDecoder()
        val publicKey = decoder.decode(deviceId)
        val signature = decoder.decode(event.getString("signature"))
        val fields = JSONObject()
        val keys = event.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            if (key != "signature") fields.put(key, event.get(key))
        }
        val verifier = Ed25519Signer()
        verifier.init(false, Ed25519PublicKeyParameters(publicKey, 0))
        val canonical = canonical(fields).toByteArray(Charsets.UTF_8)
        verifier.update(canonical, 0, canonical.size)
        verifier.verifySignature(signature)
    }.getOrDefault(false)

    private fun canonical(value: Any): String = when (value) {
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") {
            JSONObject.quote(it) + ":" + canonical(value.get(it))
        }
        is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonical(value.get(it)) }
        JSONObject.NULL -> "null"
        is String -> JSONObject.quote(value)
        is Number, is Boolean -> value.toString()
        else -> error("Unsupported JSON value")
    }
}
