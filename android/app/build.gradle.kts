import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Written by build_apk.ps1 on the first run. Sideloaded apps still have to be signed,
// but nothing here goes near a store, so the key lives beside the project.
val keyProps = Properties().apply {
    val file = rootProject.file("keystore/keystore.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

android {
    namespace = "com.rigdeck.panel"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.rigdeck.panel"
        // 26 is where adaptive icons land, and nothing older is going to be sitting in a
        // truck cab in 2026.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    signingConfigs {
        if (keyProps.getProperty("storeFile") != null) {
            create("release") {
                storeFile = rootProject.file(keyProps.getProperty("storeFile"))
                storePassword = keyProps.getProperty("storePassword")
                keyAlias = keyProps.getProperty("keyAlias")
                keyPassword = keyProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

// No dependencies on purpose: the whole app is a WebView pointed at the panel, and every
// extra library is one more thing that can fail to resolve on a machine with no network.
