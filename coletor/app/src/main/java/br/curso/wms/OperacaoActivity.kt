package br.curso.wms

import android.app.Activity
import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.RadioButton
import android.widget.Spinner
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import kotlin.concurrent.thread

/**
 * Tela das operações: ENTRADA, BAIXA, INVENTARIO e CONSULTA.
 *
 * Duas formas de ler:
 *  - RFID: aperta o gatilho, as tags vão para a lista, depois "Enviar".
 *  - Código de barras: o leitor digita o código no campo; informa a
 *    quantidade e "Enviar".
 *
 * Quem decide tudo (lote do FEFO, saldo, validade, data/hora) é o servidor.
 */
class OperacaoActivity : Activity() {

    private lateinit var operacao: String

    // Tags lidas: EPC -> texto mostrado na lista (LinkedHashMap mantém a ordem de leitura)
    private val tags = LinkedHashMap<String, String>()
    private lateinit var adaptadorLista: ArrayAdapter<String>

    // Listas carregadas do servidor para os Spinners (ids na mesma ordem dos textos)
    private val produtoIds = mutableListOf<Int>()
    private val inventarioIds = mutableListOf<Int>()
    private val loteIds = mutableListOf<Int>()

    private val v = object {
        lateinit var spProduto: Spinner; lateinit var edLote: EditText; lateinit var edValidade: EditText
        lateinit var spMotivo: Spinner; lateinit var spInventario: Spinner
        lateinit var rbRfid: RadioButton; lateinit var rbBarras: RadioButton
        lateinit var painelRfid: LinearLayout; lateinit var painelBarras: LinearLayout
        lateinit var txContador: TextView; lateinit var lista: ListView
        lateinit var edCodigo: EditText; lateinit var txProduto: TextView; lateinit var spLote: Spinner
        lateinit var edQtd: EditText; lateinit var txResultado: TextView
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_operacao)
        operacao = intent.getStringExtra("operacao") ?: "CONSULTA"
        title = operacao

        v.spProduto = findViewById(R.id.spProduto); v.edLote = findViewById(R.id.edLote)
        v.edValidade = findViewById(R.id.edValidade); v.spMotivo = findViewById(R.id.spMotivo)
        v.spInventario = findViewById(R.id.spInventario); v.rbRfid = findViewById(R.id.rbRfid)
        v.rbBarras = findViewById(R.id.rbBarras); v.painelRfid = findViewById(R.id.painelRfid)
        v.painelBarras = findViewById(R.id.painelBarras); v.txContador = findViewById(R.id.txContador)
        v.lista = findViewById(R.id.lista); v.edCodigo = findViewById(R.id.edCodigo)
        v.txProduto = findViewById(R.id.txProduto); v.spLote = findViewById(R.id.spLote)
        v.edQtd = findViewById(R.id.edQtd); v.txResultado = findViewById(R.id.txResultado)

        adaptadorLista = ArrayAdapter(this, android.R.layout.simple_list_item_1, mutableListOf())
        v.lista.adapter = adaptadorLista

        // Mostra só os campos que a operação usa
        findViewById<View>(R.id.painelEntrada).visibility = mostrarSe(operacao == "ENTRADA")
        v.spMotivo.visibility = mostrarSe(operacao == "BAIXA")
        v.spInventario.visibility = mostrarSe(operacao == "INVENTARIO")
        v.spLote.visibility = mostrarSe(operacao == "INVENTARIO")
        val consulta = operacao == "CONSULTA"
        v.edQtd.visibility = mostrarSe(!consulta)
        findViewById<View>(R.id.btEnviarBarras).visibility = mostrarSe(!consulta)
        findViewById<View>(R.id.btEnviarRfid).visibility = mostrarSe(!consulta)

        v.rbRfid.setOnClickListener { trocarMeio(rfid = true) }
        v.rbBarras.setOnClickListener { trocarMeio(rfid = false) }
        findViewById<Button>(R.id.btLimpar).setOnClickListener { limparTags() }
        findViewById<Button>(R.id.btEnviarRfid).setOnClickListener { enviarRfid() }
        findViewById<Button>(R.id.btEnviarBarras).setOnClickListener { enviarBarras() }

        // O leitor de código de barras (DataWedge, perfil padrão) digita o código e aperta ENTER
        v.edCodigo.setOnEditorActionListener { _, acao, _ ->
            if (acao == EditorInfo.IME_ACTION_DONE || acao == EditorInfo.IME_NULL) buscarCodigo()
            true
        }

        carregarListas()
        // Na baixa, potência baixa: lê só o que está bem perto do coletor
        Rfid.potencia(if (operacao == "BAIXA") 30 else 100)
        if (!Rfid.conectado) v.rbBarras.isChecked = true
        trocarMeio(rfid = v.rbRfid.isChecked)
    }

    override fun onResume() {
        super.onResume()
        Rfid.aoLerTag = { epc -> runOnUiThread { tagLida(epc) } }
    }

    override fun onPause() {
        Rfid.aoLerTag = null
        super.onPause()
    }

    private fun mostrarSe(condicao: Boolean) = if (condicao) View.VISIBLE else View.GONE

    private fun trocarMeio(rfid: Boolean) {
        v.painelRfid.visibility = mostrarSe(rfid)
        v.painelBarras.visibility = mostrarSe(!rfid)
        Rfid.usarGatilhoParaRfid(rfid)
        if (!rfid) v.edCodigo.requestFocus()
    }

    // ============================================================ servidor (em segundo plano)

    /** Executa `tarefa` fora da tela e mostra o texto devolvido (ou o erro). */
    private fun noServidor(tarefa: () -> String) {
        v.txResultado.text = "Enviando..."
        thread {
            val texto = try { tarefa() } catch (e: Exception) { "ERRO: ${e.message}" }
            runOnUiThread { v.txResultado.text = texto }
        }
    }

    private fun carregarListas() = thread {
        try {
            when (operacao) {
                "ENTRADA" -> {
                    val lista = Servidor.getLista("/api/produtos")
                    val textos = (0 until lista.length()).map { lista.getJSONObject(it) }.map {
                        produtoIds.add(it.getInt("id")); it.getString("sku") + " - " + it.getString("descricao")
                    }
                    runOnUiThread { v.spProduto.adapter = spinner(textos) }
                }
                "BAIXA" -> {
                    val motivos = Servidor.getObjeto("/api/status").getJSONArray("motivos")
                    val textos = (0 until motivos.length()).map { motivos.getString(it) }
                    runOnUiThread { v.spMotivo.adapter = spinner(textos) }
                }
                "INVENTARIO" -> {
                    val lista = Servidor.getLista("/api/inventarios")
                    val abertos = (0 until lista.length()).map { lista.getJSONObject(it) }
                        .filter { it.getString("status") == "ABERTO" }
                    val textos = abertos.map { inventarioIds.add(it.getInt("id")); "#${it.getInt("id")} " + it.getString("nome") }
                    runOnUiThread {
                        v.spInventario.adapter = spinner(textos)
                        if (textos.isEmpty()) v.txResultado.text = "Nenhum inventário aberto. Abra um no PC."
                    }
                }
            }
        } catch (e: Exception) {
            runOnUiThread { v.txResultado.text = "ERRO ao carregar dados: ${e.message}" }
        }
    }

    private fun spinner(textos: List<String>) =
        ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, textos)

    // ============================================================ RFID

    /** Cada EPC entra uma vez só na lista; a descrição vem do servidor. */
    private fun tagLida(epc: String) {
        if (tags.containsKey(epc)) return
        tags[epc] = epc
        atualizarLista()
        thread {
            val texto = try {
                val t = Servidor.getObjeto("/api/tags/$epc")
                "${t.getString("sku")}  lote ${t.getString("lote")}  ${t.getString("status")}\n$epc"
            } catch (e: Exception) {
                (if (operacao == "ENTRADA") "NOVA" else "NÃO CADASTRADA") + "\n$epc"
            }
            runOnUiThread { if (tags.containsKey(epc)) { tags[epc] = texto; atualizarLista() } }
        }
    }

    private fun atualizarLista() {
        adaptadorLista.clear()
        adaptadorLista.addAll(tags.values.reversed())   // última lida no topo
        v.txContador.text = "${tags.size} tags lidas"
    }

    private fun limparTags() {
        tags.clear()
        atualizarLista()
    }

    private fun enviarRfid() {
        if (tags.isEmpty()) { v.txResultado.text = "Nenhuma tag lida"; return }
        val corpo = JSONObject()
            .put("epcs", JSONArray(tags.keys.toList()))
            .put("origem", "COLETOR").put("meio", "RFID")
        val caminho = when (operacao) {
            "ENTRADA" -> {
                if (produtoIds.isEmpty()) { v.txResultado.text = "Escolha o produto"; return }
                corpo.put("produto_id", produtoIds[v.spProduto.selectedItemPosition])
                    .put("lote", v.edLote.text.toString())
                    .put("validade", v.edValidade.text.toString().ifBlank { JSONObject.NULL })
                "/api/entradas"
            }
            "BAIXA" -> { corpo.put("motivo", v.spMotivo.selectedItem as String); "/api/baixas" }
            else -> caminhoInventario() ?: return
        }
        noServidor {
            val resposta = Servidor.post(caminho, corpo)
            runOnUiThread { limparTags() }
            resumirTags(resposta)
        }
    }

    /** Resposta com várias tags: conta os OKs e lista os erros. */
    private fun resumirTags(resposta: JSONObject): String {
        if (!resposta.has("tags")) return "OK: entrada de ${resposta.get("quantidade")} un. no lote ${resposta.getString("lote")}"
        val lista = resposta.getJSONArray("tags")
        val itens = (0 until lista.length()).map { lista.getJSONObject(it) }
        val ok = itens.count { it.getBoolean("ok") }
        val erros = itens.filter { !it.getBoolean("ok") }.joinToString("\n") { "${it.getString("epc")}: ${it.getString("erro")}" }
        val avisos = itens.flatMap { t -> t.optJSONArray("avisos")?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList() }
        return "OK: $ok de ${itens.size} tags" +
            (if (erros.isNotEmpty()) "\n$erros" else "") +
            (if (avisos.isNotEmpty()) "\nAVISO: " + avisos.distinct().joinToString("\n") else "")
    }

    private fun caminhoInventario(): String? {
        if (inventarioIds.isEmpty()) { v.txResultado.text = "Nenhum inventário aberto"; return null }
        return "/api/inventarios/${inventarioIds[v.spInventario.selectedItemPosition]}/contagens"
    }

    // ============================================================ código de barras

    /** Mostra o produto do código lido e seus lotes (em ordem de validade). */
    private fun buscarCodigo() {
        val codigo = v.edCodigo.text.toString().trim()
        if (codigo.isEmpty()) return
        noServidor {
            val p = Servidor.getObjeto("/api/produtos/busca?codigo=" + URLEncoder.encode(codigo, "UTF-8"))
            val lotes = p.getJSONArray("lotes")
            val textos = mutableListOf<String>()
            loteIds.clear()
            for (i in 0 until lotes.length()) {
                val l = lotes.getJSONObject(i)
                loteIds.add(l.getInt("id"))
                val validade = if (l.isNull("validade")) "-" else l.getString("validade")
                textos.add("Lote ${l.getString("lote")}  val. $validade  saldo ${l.get("quantidade")}")
            }
            runOnUiThread {
                v.txProduto.text = p.getString("sku") + " - " + p.getString("descricao")
                v.spLote.adapter = spinner(textos)
                val pos = produtoIds.indexOf(p.getInt("id"))
                if (pos >= 0) v.spProduto.setSelection(pos)
                v.edQtd.requestFocus()
            }
            if (operacao == "CONSULTA") textos.joinToString("\n").ifEmpty { "Sem lotes" } else "Informe a quantidade"
        }
    }

    private fun enviarBarras() {
        val codigo = v.edCodigo.text.toString().trim()
        val qtd = v.edQtd.text.toString().toDoubleOrNull()
        if (codigo.isEmpty() || qtd == null) { v.txResultado.text = "Leia o código e informe a quantidade"; return }
        val corpo = JSONObject().put("origem", "COLETOR").put("meio", "BARRAS").put("quantidade", qtd)
        val caminho = when (operacao) {
            "ENTRADA" -> {
                corpo.put("codigo", codigo).put("lote", v.edLote.text.toString())
                    .put("validade", v.edValidade.text.toString().ifBlank { JSONObject.NULL })
                "/api/entradas"
            }
            "BAIXA" -> {
                corpo.put("codigo", codigo).put("motivo", v.spMotivo.selectedItem as String)
                "/api/baixas"
            }
            else -> {
                if (loteIds.isEmpty()) { v.txResultado.text = "Produto sem lote cadastrado"; return }
                corpo.put("lote_id", loteIds[v.spLote.selectedItemPosition])
                caminhoInventario() ?: return
            }
        }
        noServidor {
            val r = Servidor.post(caminho, corpo)
            runOnUiThread { v.edCodigo.setText(""); v.edQtd.setText(""); v.txProduto.text = ""; v.edCodigo.requestFocus() }
            when (operacao) {
                "BAIXA" -> {
                    val lotes = r.getJSONArray("lotes")
                    "OK: baixa por FEFO\n" + (0 until lotes.length()).map { lotes.getJSONObject(it) }
                        .joinToString("\n") { "lote ${it.getString("lote")}: ${it.get("quantidade")}" }
                }
                "ENTRADA" -> "OK: entrada de ${r.get("quantidade")} no lote ${r.getString("lote")}"
                else -> "OK: contado ${r.get("quantidade")} no lote ${r.getString("lote")}"
            }
        }
    }
}
