package br.curso.appcenter

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.Button
import android.widget.CheckBox
import android.widget.GridLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * AppCenter: tela inicial do coletor em modo quiosque.
 *  - Usuário: fundo branco e só os ícones dos apps liberados.
 *  - 5 toques na tela (em até 3 s): popup do PIN do administrador (1234).
 *  - Administrador: escolhe os apps, sai do admin, fecha o AppCenter (Android completo)
 *    ou remove o modo quiosque.
 */
class MainActivity : Activity() {

    private lateinit var quiosque: Quiosque
    private val toques = ArrayList<Long>()
    private var dialogoPin: AlertDialog? = null

    private val azul = Color.parseColor("#1F6FEB")
    private val cinza = Color.parseColor("#5C6778")
    private val texto = Color.parseColor("#17202B")

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        quiosque = Quiosque(this)
        // Fundo branco também nas barras do Android (ícones escuros)
        window.statusBarColor = Color.WHITE
        window.navigationBarColor = Color.WHITE
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
    }

    override fun onResume() {
        super.onResume()
        if (quiosque.liberado) {
            // Admin saiu do quiosque neste boot: a tela inicial é o Android completo até reiniciar
            if (quiosque.emQuiosque()) try { stopLockTask() } catch (_: Throwable) {}
            quiosque.launcherPadrao()?.let { startActivity(it); return }
        }
        quiosque.ativar(this)
        desenhar()
        esconderVoltar()
    }

    override fun onWindowFocusChanged(temFoco: Boolean) {
        super.onWindowFocusChanged(temFoco)
        if (temFoco) esconderVoltar()
    }

    /** Esconde a barra de navegação (seta Voltar) no AppCenter; a barra de cima (hora, bateria) fica. */
    private fun esconderVoltar() {
        if (Build.VERSION.SDK_INT >= 30) {
            window.insetsController?.let {
                it.hide(WindowInsets.Type.navigationBars())
                it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        }
    }

    /** Voltar não sai do AppCenter. */
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {}

    private fun desenhar() = if (Estado.admin) telaAdmin() else telaUsuario()

    // ------------------------------------------------------------------ tela do usuário
    private fun telaUsuario() {
        val raiz = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            setPadding(dp(12), dp(16), dp(12), dp(12))
        }
        raiz.addView(TextView(this).apply {
            text = "AppCenter"
            setTextColor(cinza)
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, dp(16))
        })
        val apps = quiosque.apps().mapNotNull { pkg -> infoApp(pkg) }.sortedBy { it.nome.lowercase() }
        if (apps.isEmpty()) {
            raiz.addView(TextView(this).apply {
                text = "Nenhum aplicativo liberado"
                setTextColor(cinza)
                gravity = Gravity.CENTER
                setPadding(0, dp(40), 0, 0)
            })
        } else {
            val grade = GridLayout(this).apply { columnCount = 3 }
            val largura = (resources.displayMetrics.widthPixels - dp(24)) / 3
            for (app in apps) {
                grade.addView(LinearLayout(this).apply {
                    orientation = LinearLayout.VERTICAL
                    gravity = Gravity.CENTER_HORIZONTAL
                    setPadding(dp(4), dp(10), dp(4), dp(10))
                    layoutParams = GridLayout.LayoutParams().apply { width = largura }
                    addView(ImageView(context).apply {
                        setImageDrawable(app.icone)
                        layoutParams = LinearLayout.LayoutParams(dp(64), dp(64))
                    })
                    addView(TextView(context).apply {
                        text = app.nome
                        setTextColor(texto)
                        textSize = 14f
                        gravity = Gravity.CENTER
                        maxLines = 2
                        setPadding(0, dp(6), 0, 0)
                    })
                    isClickable = true
                    setBackgroundResource(android.R.drawable.list_selector_background)
                    setOnClickListener { abrirApp(app.pacote) }
                })
            }
            raiz.addView(grade)
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            isFillViewport = true
            addView(raiz)
        })
    }

    private class App(val pacote: String, val nome: String, val icone: android.graphics.drawable.Drawable)

    private fun infoApp(pacote: String): App? = try {
        val info = packageManager.getApplicationInfo(pacote, 0)
        if (packageManager.getLaunchIntentForPackage(pacote) == null) null
        else App(pacote, packageManager.getApplicationLabel(info).toString(), packageManager.getApplicationIcon(info))
    } catch (e: PackageManager.NameNotFoundException) {
        null
    }

    private fun abrirApp(pacote: String) {
        val intent = packageManager.getLaunchIntentForPackage(pacote) ?: return
        try {
            startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Throwable) {
            Toast.makeText(this, "Não abriu: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    // ------------------------------------------------------------------ 5 toques → PIN
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (!Estado.admin && ev.actionMasked == MotionEvent.ACTION_DOWN && dialogoPin?.isShowing != true) {
            val agora = System.currentTimeMillis()
            toques.add(agora)
            toques.removeAll { agora - it > 3000 }
            Log.i(Quiosque.TAG, "toque ${toques.size}/5")
            if (toques.size >= 5) {
                toques.clear()
                pedirPin()
                return true
            }
        }
        return super.dispatchTouchEvent(ev)
    }

    /** Popup do PIN com teclado numérico próprio (o Gboard não aparece no MC3300). */
    private fun pedirPin() {
        var pin = ""
        val visor = TextView(this).apply {
            textSize = 28f
            gravity = Gravity.CENTER
            setTextColor(texto)
            letterSpacing = 0.3f
            setPadding(0, dp(4), 0, dp(12))
            text = "—"
        }
        fun mostrar() { visor.text = if (pin.isEmpty()) "—" else "•".repeat(pin.length) }
        lateinit var conferir: () -> Unit
        fun tecla(t: String) {
            when (t) {
                "⌫" -> pin = pin.dropLast(1)
                "OK" -> { conferir(); return }
                else -> if (pin.length < 8) pin += t
            }
            mostrar()
        }
        val teclado = GridLayout(this).apply { columnCount = 3 }
        for (t in listOf("1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK")) {
            teclado.addView(Button(this).apply {
                text = t
                textSize = 20f
                isAllCaps = false
                if (t == "OK") { setTextColor(Color.WHITE); background = fundo(azul) }
                layoutParams = GridLayout.LayoutParams().apply {
                    width = dp(76); height = dp(58); setMargins(dp(4), dp(4), dp(4), dp(4))
                }
                setOnClickListener { tecla(t) }
            })
        }
        val corpo = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(16), dp(8), dp(16), 0)
            addView(visor)
            addView(teclado)
        }
        val d = AlertDialog.Builder(this)
            .setTitle("PIN do administrador")
            .setView(corpo)
            .setNegativeButton("Cancelar", null)
            .create()
        d.setCanceledOnTouchOutside(false)   // só fecha no Cancelar
        conferir = {
            if (pin == Quiosque.PIN) {
                d.dismiss()
                Estado.admin = true
                desenhar()
            } else {
                pin = ""
                mostrar()
                Toast.makeText(this, "PIN incorreto", Toast.LENGTH_SHORT).show()
            }
        }
        // Teclado físico do coletor também digita o PIN
        d.setOnKeyListener { _, codigo, ev ->
            Log.i(Quiosque.TAG, "PIN: tecla $codigo ${KeyEvent.keyCodeToString(codigo)} ${if (ev.action == KeyEvent.ACTION_DOWN) "apertada" else "solta"}")
            if (ev.action != KeyEvent.ACTION_DOWN) return@setOnKeyListener false
            when (codigo) {
                in KeyEvent.KEYCODE_0..KeyEvent.KEYCODE_9 -> { tecla((codigo - KeyEvent.KEYCODE_0).toString()); true }
                in KeyEvent.KEYCODE_NUMPAD_0..KeyEvent.KEYCODE_NUMPAD_9 -> { tecla((codigo - KeyEvent.KEYCODE_NUMPAD_0).toString()); true }
                KeyEvent.KEYCODE_DEL -> { tecla("⌫"); true }
                // Enter do teclado físico do coletor confirma (o código varia: ENTER, NUMPAD_ENTER ou DPAD_CENTER)
                KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER, KeyEvent.KEYCODE_DPAD_CENTER -> { tecla("OK"); true }
                else -> false
            }
        }
        dialogoPin = d
        try {
            d.show()
            Log.i(Quiosque.TAG, "PIN: popup aberto")
        } catch (e: Throwable) {
            Log.w(Quiosque.TAG, "PIN: não abriu (${e.message})")
        }
    }

    private fun fundo(cor: Int) = GradientDrawable().apply { setColor(cor); cornerRadius = dp(8).toFloat() }

    // ------------------------------------------------------------------ área do administrador
    private fun telaAdmin() {
        val raiz = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            setPadding(dp(16), dp(16), dp(16), dp(24))
        }
        raiz.addView(TextView(this).apply {
            text = "Administração"
            textSize = 22f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(texto)
        })
        raiz.addView(TextView(this).apply {
            text = if (quiosque.dono) "Modo quiosque ativo (AppCenter é o administrador do aparelho)."
            else "ATENÇÃO: o AppCenter não é Device Owner, o quiosque não trava o aparelho. Veja o README."
            setTextColor(if (quiosque.dono) cinza else Color.parseColor("#C62828"))
            setPadding(0, dp(4), 0, dp(12))
        })

        raiz.addView(botao("← Sair do admin", azul, Color.WHITE) {
            Estado.admin = false
            desenhar()
        })

        raiz.addView(TextView(this).apply {
            text = "APLICATIVOS NO APPCENTER"
            textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(cinza)
            setPadding(0, dp(20), 0, dp(4))
        })
        val liberados = quiosque.apps().toMutableSet()
        val principal = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val instalados = packageManager.queryIntentActivities(principal, 0)
            .map { it.activityInfo.packageName }
            .distinct()
            .filter { it != packageName }
            .mapNotNull { infoApp(it) }
            .sortedWith(compareBy<App>({ it.pacote !in liberados }, { it.nome.lowercase() }))
        for (app in instalados) {
            raiz.addView(CheckBox(this).apply {
                text = "  ${app.nome}"
                textSize = 16f
                setTextColor(texto)
                isChecked = app.pacote in liberados
                val icone = app.icone.constantState?.newDrawable()?.mutate() ?: app.icone
                icone.setBounds(0, 0, dp(32), dp(32))
                setCompoundDrawables(null, null, icone, null)
                setPadding(dp(4), dp(8), dp(4), dp(8))
                setOnCheckedChangeListener { _, marcado ->
                    if (marcado) liberados.add(app.pacote) else liberados.remove(app.pacote)
                    quiosque.salvarApps(liberados)
                }
            })
        }

        raiz.addView(TextView(this).apply {
            text = "MODO QUIOSQUE"
            textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(cinza)
            setPadding(0, dp(20), 0, dp(4))
        })
        raiz.addView(botao("Sair do modo quiosque", Color.parseColor("#EEF1F5"), texto) {
            Estado.admin = false
            quiosque.fechar(this)
        })
        raiz.addView(TextView(this).apply {
            text = "Libera o Android completo. O quiosque volta ao reiniciar o coletor ou ao tocar no ícone AppCenter."
            setTextColor(cinza)
            textSize = 13f
            setPadding(0, dp(4), 0, dp(20))
        })
        raiz.addView(TextView(this).apply {
            text = "DESINSTALAR"
            textSize = 13f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(cinza)
            setPadding(0, dp(12), 0, dp(4))
        })
        raiz.addView(botao("Remover AppCenter do aparelho", Color.WHITE, Color.parseColor("#C62828")) {
            AlertDialog.Builder(this)
                .setTitle("Remover AppCenter do aparelho")
                .setMessage("O AppCenter deixa de controlar o aparelho: NÃO volta mais ao reiniciar e pode ser " +
                    "desinstalado. Para ativar de novo é preciso o ADB (veja o README).")
                .setNegativeButton("Voltar", null)
                .setPositiveButton("Remover") { _, _ ->
                    Estado.admin = false
                    quiosque.removerQuiosque(this)
                }
                .show()
        })

        setContentView(ScrollView(this).apply {
            setBackgroundColor(Color.WHITE)
            addView(raiz)
        })
    }

    private fun botao(rotulo: String, fundoCor: Int, textoCor: Int, acao: () -> Unit) = Button(this).apply {
        text = rotulo
        isAllCaps = false
        textSize = 16f
        setTextColor(textoCor)
        background = fundo(fundoCor).apply {
            if (fundoCor == Color.WHITE) setStroke(dp(1), textoCor)
        }
        // Altura acompanha o texto (texto longo quebra em duas linhas sem cortar)
        minHeight = dp(52)
        minimumHeight = dp(52)
        setPadding(dp(12), dp(10), dp(12), dp(10))
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(8)
        }
        setOnClickListener { acao() }
    }
}
