package org.lifeline.field

import java.util.Base64
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EventSignatureVerifierTest {
    @Test fun verifiesProtocolCanonicalEventAndRejectsMutation() {
        val privateKey = Ed25519PrivateKeyParameters(ByteArray(32) { it.toByte() }, 0)
        val publicKey = Base64.getUrlEncoder().withoutPadding().encodeToString(privateKey.generatePublicKey().encoded)
        val canonical = """{"device_id":"$publicKey","event_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","hops":0,"hlc":"2026-01-01T00:00:00.000Z-0000-device","payload":{},"protocol_version":1,"request_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV","type":"sos.created"}"""
        val signer = Ed25519Signer()
        signer.init(true, privateKey)
        val data = canonical.toByteArray(Charsets.UTF_8)
        signer.update(data, 0, data.size)
        val signature = Base64.getUrlEncoder().withoutPadding().encodeToString(signer.generateSignature())
        val fields = JSONObject(canonical)
        val event = JSONObject(fields.toString()).put("signature", signature)
        assertTrue(EventSignatureVerifier.verify(event))
        assertFalse(EventSignatureVerifier.verify(event.put("type", "sos.ping")))
    }
}
