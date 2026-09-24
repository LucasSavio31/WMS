package br.curso.appcenter

import android.app.Activity
import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import android.util.Log

/** Estado da sessão: administrador logado com o PIN (some ao reiniciar o app/aparelho). */
object Estado {
    @Volatile var admin = false
}

/**
 * Modo quiosque pelo Android "lock task" (precisa ser Device Owner):
 *  - só o AppCenter e os apps liberados abrem;
 *  - sem Home, Recentes e barra de notificações (hora, bateria e Wi-Fi continuam visíveis);
 *  - o AppCenter é a tela inicial fixa do aparelho.
 */
class Quiosque(private val ctx: Context) {

    companion object {
        const val TAG = "AppCenter"
        const val PIN = "1234"
        const val APP_ESTOQUE = "br.curso.wms"
    }

    private val dpm = ctx.getSystemService(DevicePolicyManager::class.java)
    private val admin = ComponentName(ctx, AdminReceiver::class.java)
    private val home = ComponentName(ctx.packageName, "br.curso.appcenter.Home")
    private val prefs = ctx.getSharedPreferences("appcenter", Context.MODE_PRIVATE)

    /** O AppCenter é o Device Owner (sem isso não há quiosque de verdade). */
    val dono get() = dpm.isDeviceOwnerApp(ctx.packageName)

    /** Apps que aparecem para o usuário (padrão: o app de estoque). */
    fun apps(): Set<String> = prefs.getStringSet("apps", null) ?: setOf(APP_ESTOQUE)

    fun salvarApps(apps: Set<String>) {
        prefs.edit().putStringSet("apps", HashSet(apps)).apply()
        liberar()
    }

    private fun liberar() {
        if (!dono) return
        dpm.setLockTaskPackages(admin, (apps() + ctx.packageName).toTypedArray())
        if (Build.VERSION.SDK_INT >= 28) {
            // Mostra hora/bateria/Wi-Fi e o menu de desligar; esconde Home, Recentes e notificações
            dpm.setLockTaskFeatures(admin,
                DevicePolicyManager.LOCK_TASK_FEATURE_SYSTEM_INFO or DevicePolicyManager.LOCK_TASK_FEATURE_GLOBAL_ACTIONS)
        }
    }

    /** Número do boot atual (muda a cada vez que o coletor liga). */
    private fun boot() = Settings.Global.getInt(ctx.contentResolver, Settings.Global.BOOT_COUNT, 0)

    /** O admin saiu do modo quiosque neste boot. Ao reiniciar, o número do boot muda e o quiosque volta. */
    val liberado get() = prefs.getInt("liberadoNoBoot", -1) == boot()

    /** Volta ao modo quiosque (ex.: admin abriu o ícone do AppCenter). */
    fun travarDeNovo() = prefs.edit().remove("liberadoNoBoot").apply()

    /** Launcher padrão do Android (o que não é o AppCenter). */
    fun launcherPadrao(): Intent? = ctx.packageManager
        .queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), 0)
        .filter { it.activityInfo.packageName != ctx.packageName && !it.activityInfo.name.contains("FallbackHome") }
        .maxByOrNull { if (it.activityInfo.packageName.contains("launcher")) 1 else 0 }   // Launcher3 do Android
        ?.let { Intent(Intent.ACTION_MAIN).setClassName(it.activityInfo.packageName, it.activityInfo.name)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }

    fun emQuiosque(): Boolean =
        ctx.getSystemService(ActivityManager::class.java).lockTaskModeState != ActivityManager.LOCK_TASK_MODE_NONE

    /** Liga o quiosque: AppCenter como tela inicial fixa + trava na tela (lock task). */
    fun ativar(tela: Activity?) {
        // Sem tela de desbloqueio (o deslizar): o coletor liga direto no AppCenter.
        // Fica gravado no aparelho; só funciona sem senha/PIN de tela.
        if (dono) try { dpm.setKeyguardDisabled(admin, true) } catch (e: Throwable) { Log.w(TAG, "tela de bloqueio: ${e.message}") }
        if (liberado) return   // admin saiu do quiosque neste boot
        ctx.packageManager.setComponentEnabledSetting(home,
            PackageManager.COMPONENT_ENABLED_STATE_ENABLED, PackageManager.DONT_KILL_APP)
        if (!dono) {
            Log.w(TAG, "não é Device Owner: sem quiosque")
            return
        }
        liberar()
        val filtro = IntentFilter(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_HOME)
            addCategory(Intent.CATEGORY_DEFAULT)
        }
        dpm.addPersistentPreferredActivity(admin, filtro, home)
        if (tela != null && !emQuiosque()) {
            try {
                tela.startLockTask()
                Log.i(TAG, "quiosque ligado")
            } catch (e: Throwable) {
                Log.w(TAG, "startLockTask: ${e.message}")
            }
        }
    }

    /** Admin: sai do modo quiosque e libera o Android completo até o coletor reiniciar.
     *  O AppCenter continua sendo a tela inicial: assim ele sobe na hora ao ligar, sem esperar
     *  o aviso de boot do Android (que neste coletor chega uns 40 s depois). */
    fun fechar(tela: Activity) {
        prefs.edit().putInt("liberadoNoBoot", boot()).commit()
        try { tela.stopLockTask() } catch (_: Throwable) {}
        Log.i(TAG, "quiosque liberado pelo admin até reiniciar (boot ${boot()})")
        launcherPadrao()?.let { tela.startActivity(it) }
    }

    /** Admin: desfaz o quiosque de vez (deixa de ser Device Owner). */
    fun removerQuiosque(tela: Activity) {
        try { tela.stopLockTask() } catch (_: Throwable) {}
        if (dono) {
            dpm.clearPackagePersistentPreferredActivities(admin, ctx.packageName)
            dpm.setLockTaskPackages(admin, emptyArray())
            @Suppress("DEPRECATION")
            dpm.clearDeviceOwnerApp(ctx.packageName)
        }
        ctx.packageManager.setComponentEnabledSetting(home,
            PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP)
        Log.i(TAG, "quiosque removido (não é mais Device Owner)")
        tela.startActivity(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        tela.finish()
    }
}
