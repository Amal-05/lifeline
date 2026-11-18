# Lifeline Android field app

The Android app provides offline SOS capture, signed event storage and sync, cached volunteer assignments with queued status updates, and the Nearby Connections mesh relay. Once a gateway reaches the API, it uploads its complete event store and broadcasts server acknowledgements as mesh delivery receipts.

## Build and run

Open `apps/android` in Android Studio with Android SDK 36 installed, configure Gradle JDK 17, then run the `app` configuration on an emulator or Android device. A Gradle wrapper is not checked in yet. From an environment with Gradle 8.14.3 and Android SDK 36 installed, run:

```sh
gradle -p apps/android testDebugUnitTest assembleDebug
```

To use the API from the Android emulator, keep the default gateway `http://10.0.2.2:8000/api/v1` and start the repository's API service. For a physical device, set the gateway URL to the reachable API host. Debug builds allow HTTP for local development; release builds do not. Use HTTPS for deployments.

For mesh privacy, generate a coordinator sealed-box secret key and put it in the ignored `.env` file as `COORDINATOR_SECRET_KEY`. The API derives and publishes its matching public key from `/api/v1/config`, and the app caches it for offline SOS creation. Generate a key with:

```sh
python -c "import base64; from nacl.public import PrivateKey; print(base64.urlsafe_b64encode(bytes(PrivateKey.generate())).decode().rstrip('='))"
```

The private key must also be available to both the API and worker containers. Without a cached coordinator public key, the Android app still saves and syncs SOS over HTTPS, but does not relay that event over the mesh. Never use the synthetic demo defaults for real incidents.

On first launch, sign in to load assignments or choose **Continue to offline SOS**. SOS events are signed with a device-specific Ed25519 key. The seed is encrypted with an Android Keystore AES key and persisted locally. The mesh asks Android for nearby-device permissions only when joining.

## Current limits

This first native field UI supports manual coordinates. It does not yet include GPS acquisition, photo/voice capture, multilingual strings, or a release signing pipeline. Mesh discovery and relay require Android devices and Google Play Services; physical-device behavior has not been validated here.
