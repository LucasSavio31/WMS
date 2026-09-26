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
        versionCode = 25
        versionName = "3.15"
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

    // Modo local: a tela do coletor (server/app/static/m.html) vai dentro do APK
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("telaLocal").get().asFile)

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

// Copia a tela do coletor do servidor para os assets do APK (uma fonte só: server/app/static/m.html)
val copiarTelaLocal by tasks.registering(Copy::class) {
    from(rootProject.file("../server/app/static/m.html"))
    into(layout.buildDirectory.dir("telaLocal").get().asFile)
}
tasks.named("preBuild") { dependsOn(copiarTelaLocal) }
