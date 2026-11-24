import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
}

// Signed with the same upload key as the customer app (its gitignored key.properties),
// so an update installs over the previous build. Without that file: debug key.
val customerAndroid = rootProject.file("../customer/android")
val keystorePropertiesFile = File(customerAndroid, "key.properties")
val keystoreProperties = Properties()
if (keystorePropertiesFile.exists()) {
    FileInputStream(keystorePropertiesFile).use { keystoreProperties.load(it) }
}

android {
    namespace = "com.greeneatfood.babdaeri.counter"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.greeneatfood.babdaeri.counter"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                // Absolute, or relative to the customer app module like there.
                val keystore = File(keystoreProperties["storeFile"] as String)
                storeFile = if (keystore.isAbsolute) keystore else File(File(customerAndroid, "app"), keystore.path)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (keystorePropertiesFile.exists()) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}
