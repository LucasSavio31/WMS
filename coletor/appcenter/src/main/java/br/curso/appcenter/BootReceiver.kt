package br.curso.appcenter

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/** Reforço ao ligar o coletor (ou atualizar o AppCenter). O principal é o AppCenter ser a tela
 *  inicial: ele já sobe no boot; este aviso do Android chega bem depois (uns 40 s no MC3300). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        Log.i(Quiosque.TAG, "boot: ${intent.action}")
        Estado.admin = false
        Quiosque(ctx).ativar(null)
        try {
            ctx.startActivity(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Throwable) {
            Log.w(Quiosque.TAG, "boot: não abriu o AppCenter (${e.message})")
        }
    }
}
