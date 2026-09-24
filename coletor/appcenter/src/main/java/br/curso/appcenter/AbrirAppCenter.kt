package br.curso.appcenter

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.util.Log

/** Ícone "AppCenter" no launcher do Android: depois que o admin saiu do quiosque,
 *  tocar nele volta ao AppCenter travado. Só religa e some (nunca é recriada). */
class AbrirAppCenter : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(Quiosque.TAG, "ícone AppCenter: quiosque de volta")
        Estado.admin = false
        Quiosque(this).travarDeNovo()
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        finish()
    }
}
