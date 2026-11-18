package org.lifeline.field

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import com.goterl.lazysodium.LazySodiumAndroid
import com.goterl.lazysodium.SodiumAndroid
import com.goterl.lazysodium.interfaces.Box
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.math.BigInteger
import java.security.KeyStore
import java.security.SecureRandom
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class LocalEventIdentity(context: Context) {
    private val seedFile = AtomicFile(File(context.filesDir, "lifeline-device-seed.bin"))
    private val seed = loadSeed()
    private val signingKey = Ed25519PrivateKeyParameters(seed, 0)
    val deviceId = Base64.getUrlEncoder().withoutPadding().encodeToString(signingKey.generatePublicKey().encoded)
    private var previousMillis = 0L
    private var counter = 0

    @Synchronized
    fun createSos(
        peopleCount: Int,
        category: String,
        needs: List<String>,
        note: String,
        latitude: Double?,
        longitude: Double?,
        coordinatorPublicKey: String?,
    ): JSONObject {
        require(peopleCount in 1..100)
        require(category in setOf("medical", "trapped", "food", "evacuation", "missing", "other"))
        require((latitude == null) == (longitude == null))
        require(latitude == null || latitude in -90.0..90.0)
        require(longitude == null || longitude in -180.0..180.0)
        val requestId = newUlid()
        val hlc = nextHlc()
        val location = JSONObject()
            .put("latitude", latitude ?: JSONObject.NULL)
            .put("longitude", longitude ?: JSONObject.NULL)
            .put("accuracy_m", JSONObject.NULL)
            .put("source", if (latitude == null) "unavailable" else "manual")
        val payload = JSONObject().put("people_count", peopleCount).put("categories", JSONArray().put(category))
            .put("special_needs", JSONArray(needs)).put("text_original", note.trim()).put("language", "en")
            .put("location", location)
        val fields = JSONObject().put("protocol_version", 1).put("event_id", newUlid()).put("device_id", deviceId)
            .put("hlc", hlc).put("type", "sos.created").put("request_id", requestId)
            .put("payload", coordinatorPublicKey?.let { sealPayload(payload, it) } ?: payload).put("hops", 0)
        val signer = Ed25519Signer()
        signer.init(true, signingKey)
        val canonical = canonicalJson(fields).toByteArray(Charsets.UTF_8)
        signer.update(canonical, 0, canonical.size)
        val signature = Base64.getUrlEncoder().withoutPadding().encodeToString(signer.generateSignature())
        fields.put("signature", signature)
        return fields
    }

    private fun sealPayload(payload: JSONObject, encodedPublicKey: String): JSONObject {
        val publicKey = Base64.getUrlDecoder().decode(encodedPublicKey)
        require(publicKey.size == Box.PUBLICKEYBYTES) { "Coordinator public key must be 32 bytes" }
        val plaintext = payload.toString().toByteArray(Charsets.UTF_8)
        val ciphertext = ByteArray(plaintext.size + Box.SEALBYTES)
        check(LazySodiumAndroid(SodiumAndroid()).cryptoBoxSeal(ciphertext, plaintext, plaintext.size.toLong(), publicKey)) {
            "Could not encrypt SOS payload for the coordinator"
        }
        return JSONObject().put("_sealed_payload", JSONObject().put("version", 1)
            .put("algorithm", "libsodium-sealed-box-v1")
            .put("ciphertext", Base64.getUrlEncoder().withoutPadding().encodeToString(ciphertext)))
    }

    private fun nextHlc(): String {
        val now = System.currentTimeMillis()
        if (now > previousMillis) {
            previousMillis = now
            counter = 0
        } else counter += 1
        val stamp = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'")
            .withZone(ZoneOffset.UTC).format(Instant.ofEpochMilli(previousMillis))
        return "$stamp-${counter.toString().padStart(4, '0')}-${deviceId.take(8)}"
    }

    private fun loadSeed(): ByteArray {
        if (seedFile.baseFile.exists()) {
            val encrypted = seedFile.openRead().use { it.readBytes() }
            require(encrypted.size > 12) { "Stored signing identity is damaged" }
            val nonce = encrypted.copyOfRange(0, 12)
            val ciphertext = encrypted.copyOfRange(12, encrypted.size)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, nonce))
            return cipher.doFinal(ciphertext).also { require(it.size == 32) { "Stored signing identity is invalid" } }
        }
        val random = ByteArray(32).also(SecureRandom()::nextBytes)
        val nonce = ByteArray(12).also(SecureRandom()::nextBytes)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key(), GCMParameterSpec(128, nonce))
        val encrypted = nonce + cipher.doFinal(random)
        val output = seedFile.startWrite()
        try { output.write(encrypted); seedFile.finishWrite(output) }
        catch (failure: Exception) { seedFile.failWrite(output); throw failure }
        return random
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).build())
        return generator.generateKey()
    }

    companion object {
        private const val KEY_ALIAS = "lifeline.event-signing-seed"
        private const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
        private fun newUlid(): String {
            val timestamp = System.currentTimeMillis()
            val bytes = ByteArray(16)
            for (index in 5 downTo 0) bytes[5 - index] = (timestamp ushr (index * 8)).toByte()
            val random = ByteArray(10).also(SecureRandom()::nextBytes)
            random.copyInto(bytes, 6)
            var value = BigInteger(1, bytes)
            return buildString(26) { repeat(26) { append(ALPHABET[value.and(BigInteger.valueOf(31)).toInt()]); value = value.shiftRight(5) } }.reversed()
        }

        private fun canonicalJson(value: Any): String = when (value) {
            is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") {
                JSONObject.quote(it) + ":" + canonicalJson(value.get(it))
            }
            is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonicalJson(value.get(it)) }
            JSONObject.NULL -> "null"
            is String -> JSONObject.quote(value)
            is Number, is Boolean -> value.toString()
            else -> error("Unsupported JSON value")
        }
    }
}
