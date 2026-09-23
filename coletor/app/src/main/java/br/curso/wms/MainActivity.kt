package br.curso.wms

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import kotlin.concurrent.thread

/** Menu principal: configura o endereço do servidor e abre as operações. */
class MainActivity : Activity() {

    private lateinit var edServidor: EditText
    private lateinit var txStatus: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        edServidor = findViewById(R.id.edServidor)
        txStatus = findViewById(R.id.txStatus)

        // Endereço salvo da última vez
        val prefs = getSharedPreferences("config", MODE_PRIVATE)
        Servidor.url = prefs.getString("servidor", Servidor.url)!!
        edServidor.setText(Servidor.url)

        findViewById<Button>(R.id.btTestar).setOnClickListener {
            Servidor.url = edServidor.text.toString().trim()
            prefs.edit().putString("servidor", Servidor.url).apply()
            testarServidor()
        }

        findViewById<Button>(R.id.btEntrada).setOnClickListener { abrir("ENTRADA") }
        findViewById<Button>(R.id.btBaixa).setOnClickListener { abrir("BAIXA") }
        findViewById<Button>(R.id.btInventario).setOnClickListener { abrir("INVENTARIO") }
        findViewById<Button>(R.id.btConsulta).setOnClickListener { abrir("CONSULTA") }

        testarServidor()
        Rfid.conectar(applicationContext) { msg -> runOnUiThread { txStatus.append("\n" + msg) } }
    }

    private fun testarServidor() {
        txStatus.text = "Testando servidor..."
        thread {
            val msg = try {
                val status = Servidor.getObjeto("/api/status")
                "Servidor OK — hora do servidor: " + status.getString("data_hora")
            } catch (e: Exception) {
                "Sem conexão com o servidor: ${e.message}"
            }
            runOnUiThread { txStatus.text = msg + if (Rfid.conectado) "\nRFID conectado" else "" }
        }
    }

    private fun abrir(operacao: String) {
        startActivity(Intent(this, OperacaoActivity::class.java).putExtra("operacao", operacao))
    }

    override fun onDestroy() {
        if (isFinishing) Rfid.desconectar()
        super.onDestroy()
    }
}
