# Lifeline Android field app

The Android app provides offline SOS capture, signed event storage and sync, cached volunteer assignments with queued status updates, and the Nearby Connections mesh relay. Once a gateway reaches the API, it uploads its complete event store and broadcasts server acknowledgements as mesh delivery receipts.

## Build and run

Open `apps/android` in Android Studio with Android SDK 36 installed, then run the `app` configuration on an emulator or Android device. The project uses Gradle Kotlin DSL; Android Studio can create the local Gradle wrapper on first open. From an environment with Gradle installed, run:

```sh
gradle -p apps/android testDebugUnitTest assembleDebug
```

To use the API from the Android emulator, keep the default gateway `http://10.0.2.2:8000/api/v1` and start the repository's API service. For a physical device, set the gateway URL to the reachable API host. Debug builds allow HTTP for local development; release builds do not. Use HTTPS for deployments.

On first launch, sign in to load assignments or choose **Continue to offline SOS**. SOS events are signed with a device-specific Ed25519 key. The seed is encrypted with an Android Keystore AES key and persisted locally. The mesh asks Android for nearby-device permissions only when joining.

## Current limits

This first native field UI supports manual coordinates. It does not yet include GPS acquisition, photo/voice capture, multilingual strings, or a release signing pipeline. Mesh discovery and relay require Android devices and Google Play Services; physical-device behavior has not been validated here. Mesh payloads are signed but are not sealed to a coordinator key because the API does not yet publish a public key or accept ciphertext. Do not use this build for sensitive real-world incidents.
