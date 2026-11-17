plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "org.lifeline.field"
    compileSdk = 36
    defaultConfig { applicationId = "org.lifeline.field"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "0.1.0" }
}

dependencies {
    implementation("com.google.android.gms:play-services-nearby:19.3.0")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.bouncycastle:bcprov-jdk18on:1.83")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
