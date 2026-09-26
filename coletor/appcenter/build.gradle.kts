plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// AppCenter: tela inicial em modo quiosque (só os apps liberados). Sem bibliotecas extras.
android {
    namespace = "br.curso.appcenter"
    compileSdk = 34

    defaultConfig {
        applicationId = "br.curso.appcenter"
        minSdk = 26
        targetSdk = 34
        versionCode = 12
        versionName = "2.1"
    }

    // Mesma chave fixa do app do coletor (atualiza por cima sem desinstalar)
    signingConfigs {
        getByName("debug") {
            storeFile = file("../app/coletor.p12")
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
