package br.curso.wms

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.SharedPreferences
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.text.InputType
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
        Servidor.url = prefs.getString("servidor", Servidor.url)!!

        web = WebView(this)
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
    }

    private fun abrirTela() {
        web.loadUrl(Servidor.url.trimEnd('/') + "/m")
    }

    // ============================================================ RFID (liga só com o app na frente)

    override fun onStart() {
        super.onStart()
        Rfid.aoLerTag = { epc -> chamarTela("leituraRfid", epc) }
        Rfid.conectar(applicationContext) { msg -> chamarTela("statusRfid", msg) }
    }

    /** Em segundo plano o app solta o leitor (assim o 123RFID e outros apps conseguem usar). */
    override fun onStop() {
        Rfid.aoLerTag = null
        Rfid.desconectar()
        super.onStop()
    }

    /** Chama uma função JavaScript da página com um texto (ex.: leituraRfid("E280...")). */
    private fun chamarTela(funcao: String, texto: String) {
        val js = "window.$funcao && window.$funcao(${JSONObject.quote(texto)})"
        runOnUiThread { web.evaluateJavascript(js, null) }
    }

    /** Métodos que a página chama: ColetorApp.gatilhoRfid(true), ColetorApp.potencia(30)... */
    inner class Ponte {
        @JavascriptInterface
        fun gatilhoRfid(rfid: Boolean) = Rfid.usarGatilhoParaRfid(rfid)

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
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        web.destroy()
        super.onDestroy()
    }
}
