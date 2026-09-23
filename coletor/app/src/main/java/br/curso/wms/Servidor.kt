package br.curso.wms

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Comunicação com o servidor do PC (API HTTP + JSON).
 *
 * O coletor NÃO tem regra de negócio nem banco de dados: ele só envia
 * o que foi lido e mostra a resposta. Data/hora de cada movimento é
 * gravada pelo servidor.
 *
 * Atenção: rede não pode ser usada na thread da tela (main thread).
 * Chame estas funções dentro de thread { ... }.
 */
object Servidor {
    var url = "http://192.168.0.10:8000"

    fun get(caminho: String): String = chamar("GET", caminho, null)

    fun post(caminho: String, corpo: JSONObject): JSONObject = JSONObject(chamar("POST", caminho, corpo))

    fun getObjeto(caminho: String) = JSONObject(get(caminho))

    fun getLista(caminho: String) = JSONArray(get(caminho))

    private fun chamar(metodo: String, caminho: String, corpo: JSONObject?): String {
        val conexao = URL(url.trimEnd('/') + caminho).openConnection() as HttpURLConnection
        conexao.requestMethod = metodo
        conexao.connectTimeout = 5000
        conexao.readTimeout = 10000
        if (corpo != null) {
            conexao.doOutput = true
            conexao.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conexao.outputStream.use { it.write(corpo.toString().toByteArray()) }
        }
        val codigo = conexao.responseCode
        val texto = (if (codigo < 400) conexao.inputStream else conexao.errorStream)
            ?.bufferedReader()?.use { it.readText() } ?: ""
        conexao.disconnect()
        if (codigo >= 400) throw Exception(mensagemDeErro(texto))
        return texto
    }

    /** O servidor devolve erros como {"detail": "mensagem"}. */
    private fun mensagemDeErro(texto: String): String = try {
        val detalhe = JSONObject(texto).get("detail")
        if (detalhe is JSONArray) "Dados inválidos: " + detalhe.getJSONObject(0).optString("msg") else detalhe.toString()
    } catch (e: Exception) {
        "Erro no servidor"
    }
}
