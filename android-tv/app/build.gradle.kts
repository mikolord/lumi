plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "club.netcraze.phototv"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "club.netcraze.lumi"
        minSdk = 26
        targetSdk = 34
        versionCode = 16
        versionName = "0.7.3"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    lint {
        // PlayerView/DefaultMediaSourceFactory из Media3 помечены @UnstableApi — это нормально для клиентского приложения.
        disable += "UnsafeOptInUsageError"
        abortOnError = false
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")

    implementation(libs.okhttp)
    implementation(libs.coil)
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.ui)
    implementation(libs.media3.datasource.okhttp)
    implementation(libs.zxing.core)
    implementation(libs.recyclerview)
}
