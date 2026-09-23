plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "br.curso.wms"
    compileSdk = 34

    defaultConfig {
        applicationId = "br.curso.wms"
        minSdk = 26          // MC3300R/MC3390R: Android 8.1 ou superior
        targetSdk = 34
        versionCode = 9
        versionName = "2.7"
    }

    // Chave fixa: cada versão nova instala por cima da anterior (projeto didático,
    // por isso a chave fica no repositório; num app de verdade ela seria secreta).
    signingConfigs {
        getByName("debug") {
            storeFile = file("coletor.p12")
            storeType = "pkcs12"
            storePassword = "coletorwms"
            keyAlias = "coletor"
            keyPassword = "coletorwms"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    // SDK RFID da Zebra (API3). Copie o arquivo API3_LIB-release.aar para app/libs/
    // (vem no "Zebra RFID SDK for Android", baixado do site da Zebra).
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar", "*.jar"))))
    // O SDK RFID usa android.support.v4.content.LocalBroadcastManager (biblioteca de suporte antiga).
    // Sem ela, o leitor nunca conecta (NoClassDefFoundError).
    implementation("com.android.support:localbroadcastmanager:28.0.0")
}
