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
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.text.InputType
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import org.json.JSONObject

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

        // Primeira vez: pergunta o endereço do servidor
        if (prefs.contains("servidor")) abrirTela() else configurarServidor()

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
        fun servidor() = runOnUiThread { configurarServidor() }
    }

    // ============================================================ servidor

    /** Popup só com o endereço do servidor. Salvar fecha o popup e abre a tela. */
    private fun configurarServidor() {
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
            .setView(caixa)
            .setCancelable(false)
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

    companion object {
        private const val PEDIDO_BLUETOOTH = 1
    }
}
