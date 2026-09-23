package br.curso.wms

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.text.InputType
import android.util.Log
import android.view.KeyEvent
import android.view.inputmethod.InputMethodManager
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.Toast
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * App do coletor = "casca" da tela web do servidor (http://PC:8000/m).
 *
 *  - As telas são as da web: melhorou no servidor, o coletor vê na hora.
 *  - Código de barras: o DataWedge "digita" o código na página (perfil do app).
 *  - RFID: este app lê pelo SDK da Zebra (Rfid.kt) e entrega cada EPC para a
 *    página chamando a função JavaScript leituraRfid(epc).
 *  - A página conversa com o app pelo objeto JavaScript "ColetorApp" (classe Ponte):
 *    escolhe se o gatilho lê RFID ou código de barras e a potência da antena.
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private lateinit var prefs: SharedPreferences
    private var avisouErro = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.BLACK   // hora, Wi-Fi e bateria do Android em branco
        volumeControlStream = AudioManager.STREAM_MUSIC   // botões de volume ajustam o volume dos bipes

        prefs = getSharedPreferences("config", MODE_PRIVATE)
        registrarErros()
        Servidor.url = prefs.getString("servidor", Servidor.url)!!

        web = try {
            WebView(this)
        } catch (e: Throwable) {
            // Aparelho sem o componente "Android System WebView" (ou desativado)
            mostrarErro("Não foi possível abrir a tela (WebView)", textoDoErro(e))
            return
        }
        setContentView(web)
        // Permite inspecionar a tela pelo PC (chrome://inspect) com o coletor no USB
        WebView.setWebContentsDebuggingEnabled(true)
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                Log.i(TAG, "tela: ${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                return true
            }
        }
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false   // bipes da página
        web.settings.setSupportZoom(false)
        web.addJavascriptInterface(Ponte(), "ColetorApp")
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) {
                avisouErro = false
                // O botão ⚙ da página pode trocar de servidor: guarda o último que abriu
                val uri = Uri.parse(url)
                if (uri.path == "/m" && uri.scheme != null && uri.host != null) {
                    val origem = "${uri.scheme}://${uri.host}" + if (uri.port > 0) ":${uri.port}" else ""
                    if (origem != Servidor.url) {
                        Servidor.url = origem
                        prefs.edit().putString("servidor", origem).apply()
                    }
                }
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame && !avisouErro) {
                    avisouErro = true
                    semConexao(error.description.toString())
                }
            }
        }

        // Primeira vez: procura o servidor na rede sozinho (se não achar, pergunta o endereço)
        if (prefs.contains("servidor")) abrirTela() else procurarServidor()

        // O app fechou da última vez? Mostra o motivo (para corrigir)
        prefs.getString("ultimoErro", null)?.let { erro ->
            prefs.edit().remove("ultimoErro").apply()
            mostrarErro("O app fechou da última vez", erro)
        }
    }

    // ============================================================ erros

    /**
     * Qualquer erro não tratado fica gravado e aparece na próxima abertura.
     * Erro em segundo plano (ex.: dentro do SDK RFID) não fecha o app: vira mensagem na tela.
     */
    private fun registrarErros() {
        val padrao = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            val texto = "[${t.name}] " + textoDoErro(e)
            try { prefs.edit().putString("ultimoErro", texto).commit() } catch (x: Throwable) {}
            if (t === Looper.getMainLooper().thread) padrao?.uncaughtException(t, e)
            else chamarTela("statusRfid", "Erro: ${e.javaClass.simpleName}: ${e.message}")
        }
    }

    private fun textoDoErro(e: Throwable) =
        Log.getStackTraceString(e).lines().take(30).joinToString("\n")

    private fun mostrarErro(titulo: String, texto: String) {
        AlertDialog.Builder(this)
            .setTitle(titulo)
            .setMessage(texto)
            .setPositiveButton("OK", null)
            .setNeutralButton("Copiar") { _, _ ->
                val area = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
                area.setPrimaryClip(ClipData.newPlainText("erro", texto))
            }
            .show()
    }

    private fun abrirTela() {
        if (!::web.isInitialized) return
        web.loadUrl(Servidor.url.trimEnd('/') + "/m")
    }

    // ============================================================ RFID (liga só com o app na frente)

    override fun onStart() {
        super.onStart()
        conectarRfid()
    }

    private fun conectarRfid() {
        // Android 12+: o SDK da Zebra precisa da permissão de Bluetooth (igual ao app de exemplo da Zebra)
        if (Build.VERSION.SDK_INT >= 31 &&
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.BLUETOOTH_CONNECT), PEDIDO_BLUETOOTH)
            return
        }
        Rfid.aoLerTag = { epc -> chamarTela("leituraRfid", epc) }
        Rfid.aoGatilho = { apertou -> chamarTela("gatilhoRfidEvento", if (apertou) "1" else "0") }
        Rfid.aoAvisar = { msg -> chamarTela("statusRfid", msg) }
        Rfid.aoTerminarLeitura = { n -> chamarTela("fimLeituraRfid", n.toString()) }
        Rfid.aoLocalizar = { distancia -> chamarTela("proximidadeRfid", distancia.toString()) }
        Rfid.conectar(applicationContext) { msg -> chamarTela("statusRfid", msg) }
    }

    override fun onRequestPermissionsResult(codigo: Int, permissoes: Array<out String>, resultados: IntArray) {
        super.onRequestPermissionsResult(codigo, permissoes, resultados)
        if (codigo != PEDIDO_BLUETOOTH) return
        if (resultados.firstOrNull() == PackageManager.PERMISSION_GRANTED) conectarRfid()
        else chamarTela("statusRfid", "RFID indisponível: permissão de Bluetooth negada")
    }

    /** Em segundo plano o app solta o leitor (assim o 123RFID e outros apps conseguem usar). */
    override fun onStop() {
        Rfid.aoLerTag = null
        Rfid.aoGatilho = null
        Rfid.aoAvisar = null
        Rfid.aoTerminarLeitura = null
        Rfid.aoLocalizar = null
        Rfid.definirAlvo(null)
        Rfid.desconectar()
        leitorDataWedge(true)   // devolve o leitor de código de barras para os outros apps
        super.onStop()
    }

    /**
     * Liga/desliga o leitor de código de barras do DataWedge (API por Intent).
     * Com ele ligado, o DataWedge "pega" o gatilho e o RFID não lê; por isso,
     * em modo RFID o app desliga o leitor de código de barras.
     */
    private fun leitorDataWedge(ligado: Boolean) {
        try {
            sendBroadcast(
                Intent("com.symbol.datawedge.api.ACTION")
                    .putExtra("com.symbol.datawedge.api.SCANNER_INPUT_PLUGIN", if (ligado) "ENABLE_PLUGIN" else "DISABLE_PLUGIN")
            )
        } catch (e: Throwable) {
        }
    }

    /** Chama uma função JavaScript da página com um texto (ex.: leituraRfid("E280...")). */
    private fun chamarTela(funcao: String, texto: String) {
        if (funcao != "proximidadeRfid") Log.i(TAG, "para a tela: $funcao($texto)")
        val js = "window.$funcao && window.$funcao(${JSONObject.quote(texto)})"
        runOnUiThread { if (::web.isInitialized) web.evaluateJavascript(js, null) }
    }

    /** Métodos que a página chama: ColetorApp.gatilhoRfid(true), ColetorApp.potencia(30)... */
    inner class Ponte {
        @JavascriptInterface
        fun gatilhoRfid(rfid: Boolean) {
            leitorDataWedge(!rfid)   // gatilho só para o RFID ou só para o código de barras
            Rfid.usarGatilhoParaRfid(rfid)
        }

        @JavascriptInterface
        fun potencia(percentual: Int) = Rfid.potencia(percentual)

        @JavascriptInterface
        fun rfidConectado(): Boolean = Rfid.conectado

        @JavascriptInterface
        fun lerRfid(ms: Int) = Rfid.lerPor(ms.toLong())

        /** Tela Localizar: etiqueta procurada ("" = sair) e procurar sem o gatilho. */
        @JavascriptInterface
        fun localizar(epc: String) = Rfid.definirAlvo(epc)

        @JavascriptInterface
        fun procurar(ligar: Boolean) = Rfid.procurar(ligar)

        @JavascriptInterface
        fun servidor() = runOnUiThread { configurarServidor() }

        /** ⌨ do cabeçalho: força o teclado virtual do Android a aparecer. */
        @JavascriptInterface
        fun mostrarTeclado() = runOnUiThread {
            web.requestFocus()
            val teclado = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
            @Suppress("DEPRECATION")
            teclado.showSoftInput(web, InputMethodManager.SHOW_FORCED)
        }

        /** Tela Config: procurar o servidor na rede Wi-Fi. */
        @JavascriptInterface
        fun procurarServidor() = runOnUiThread { this@MainActivity.procurarServidor() }

        /** Tela Config: volume de mídia do coletor (é o volume dos bipes), de 0 a 100%. */
        @JavascriptInterface
        fun volume(percentual: Int) {
            val audio = getSystemService(AUDIO_SERVICE) as AudioManager
            val maximo = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
            audio.setStreamVolume(AudioManager.STREAM_MUSIC, (maximo * percentual.coerceIn(0, 100) + 50) / 100, 0)
        }

        @JavascriptInterface
        fun volumeAtual(): Int {
            val audio = getSystemService(AUDIO_SERVICE) as AudioManager
            val maximo = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1)
            return audio.getStreamVolume(AudioManager.STREAM_MUSIC) * 100 / maximo
        }
    }

    // ============================================================ servidor

    /** Acha o servidor na rede Wi-Fi (ver Descoberta.kt) e já abre a tela. */
    private fun procurarServidor() {
        val aviso = AlertDialog.Builder(this)
            .setTitle("Procurando o servidor…")
            .setMessage("Procurando o Mini WMS na rede Wi-Fi. Leva alguns segundos.")
            .setCancelable(false)
            .show()
        thread {
            val url = try { Descoberta.procurar() } catch (e: Throwable) { null }
            runOnUiThread {
                aviso.dismiss()
                if (url != null) {
                    Servidor.url = url
                    prefs.edit().putString("servidor", url).apply()
                    Toast.makeText(this, "Servidor encontrado: $url", Toast.LENGTH_LONG).show()
                    abrirTela()
                } else {
                    configurarServidor("Não achei o servidor na rede. Confira se ele está aberto no PC e se o coletor " +
                        "está no mesmo Wi-Fi, ou digite o endereço que aparece na tela do PC.")
                }
            }
        }
    }

    /** Popup só com o endereço do servidor. Salvar fecha o popup e abre a tela. */
    private fun configurarServidor(mensagem: String? = null) {
        val campo = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            hint = "http://192.168.0.10:8000"
            setText(Servidor.url)
            setSelection(text.length)
        }
        val margem = (20 * resources.displayMetrics.density).toInt()
        val caixa = FrameLayout(this).apply {
            setPadding(margem, margem / 2, margem, 0)
            addView(campo)
        }
        AlertDialog.Builder(this)
            .setTitle("Endereço do servidor (PC)")
            .apply { if (mensagem != null) setMessage(mensagem) }
            .setView(caixa)
            .setCancelable(false)
            .setNeutralButton("Procurar na rede") { _, _ -> procurarServidor() }
            .setNegativeButton("Cancelar") { _, _ -> abrirTela() }
            .setPositiveButton("Salvar") { _, _ ->
                var url = campo.text.toString().trim().trimEnd('/')
                if (url.isNotEmpty() && !url.startsWith("http")) url = "http://$url"
                if (url.isNotEmpty()) {
                    Servidor.url = url
                    prefs.edit().putString("servidor", url).apply()
                }
                abrirTela()
            }
            .show()
    }

    private fun semConexao(detalhe: String) {
        AlertDialog.Builder(this)
            .setTitle("Sem conexão com o servidor")
            .setMessage("${Servidor.url}\n($detalhe)\n\nConfira o Wi-Fi e se o servidor está ligado no PC.")
            .setCancelable(false)
            .setPositiveButton("Tentar de novo") { _, _ -> abrirTela() }
            .setNegativeButton("Mudar servidor") { _, _ -> configurarServidor() }
            .setNeutralButton("Procurar na rede") { _, _ -> procurarServidor() }
            .show()
    }

    /** Voltar do Android: volta de tela dentro da página; no menu, sai do app. */
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        if (::web.isInitialized) web.destroy()
        super.onDestroy()
    }

    /** Registra as teclas (gatilho, SCAN...) para descobrir os códigos do aparelho. */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.repeatCount == 0) Log.i(TAG, "tecla ${event.keyCode} ${KeyEvent.keyCodeToString(event.keyCode)} " +
            if (event.action == KeyEvent.ACTION_DOWN) "apertada" else "solta")
        return super.dispatchKeyEvent(event)
    }

    companion object {
        private const val PEDIDO_BLUETOOTH = 1
        private const val TAG = "ColetorWMS"
    }
}
