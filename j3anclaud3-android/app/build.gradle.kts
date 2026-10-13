plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "fr.j3anclaud3.compagnon"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.j3anclaud3.compagnon"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    // Two products from one code base:
    //  - claude: J3anClaud3 server, or Claude / OpenAI / Gemini / custom straight from the phone;
    //  - libre:  no Anthropic code and no server: OpenAI(-compatible), Gemini or a custom /generate/ endpoint.
    flavorDimensions += "ai"
    productFlavors {
        create("claude") {
            dimension = "ai"
        }
        create("libre") {
            dimension = "ai"
            applicationIdSuffix = ".libre"  // installs side by side with the claude build
            versionNameSuffix = "-libre"
        }
    }

    // Optional release signing: set J3_KEYSTORE, J3_KEYSTORE_PASSWORD, J3_KEY_ALIAS, J3_KEY_PASSWORD.
    val keystore = System.getenv("J3_KEYSTORE")
    signingConfigs {
        if (keystore != null) {
            create("release") {
                storeFile = file(keystore)
                storePassword = System.getenv("J3_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("J3_KEY_ALIAS")
                keyPassword = System.getenv("J3_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystore != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    // One universal APK: no native code, no ABI or density splits.

    packaging {
        resources.excludes += setOf("META-INF/DEPENDENCIES", "META-INF/LICENSE*", "META-INF/NOTICE*", "META-INF/*.kotlin_module", "META-INF/versions/**")
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
        unitTests.all { test ->
            // Optional mirror for Robolectric's Android runtime download: -ProbolectricRepo=https://…/maven2/
            (project.findProperty("robolectricRepo") as String?)?.let {
                test.systemProperty("robolectric.dependency.repo.url", it)
            }
            // Optional: render screens to PNG for a visual check, -Pj3Screenshots=<dir>
            (project.findProperty("j3Screenshots") as String?)?.let { test.systemProperty("j3.screenshots", it) }
        }
    }
}

// APK file name: j3anclaud3-<version>-<buildType>.apk
base.archivesName.set("j3anclaud3-${android.defaultConfig.versionName}")

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    // Official Anthropic SDK, for Claude straight from the phone ("claude" flavor only).
    "claudeImplementation"("com.anthropic:anthropic-java:2.71.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.test:core:1.6.1")
}
