package br.curso.wms

import android.content.Context
import com.zebra.rfid.api3.ENUM_TRANSPORT
import com.zebra.rfid.api3.ENUM_TRIGGER_MODE
import com.zebra.rfid.api3.HANDHELD_TRIGGER_EVENT_TYPE
import com.zebra.rfid.api3.INVENTORY_STATE
import com.zebra.rfid.api3.RFIDReader
import com.zebra.rfid.api3.Readers
import com.zebra.rfid.api3.RfidEventsListener
import com.zebra.rfid.api3.RfidReadEvents
import com.zebra.rfid.api3.RfidStatusEvents
import com.zebra.rfid.api3.SESSION
import com.zebra.rfid.api3.SL_FLAG
import com.zebra.rfid.api3.START_TRIGGER_TYPE
import com.zebra.rfid.api3.STATUS_EVENT_TYPE
import com.zebra.rfid.api3.STOP_TRIGGER_TYPE
import com.zebra.rfid.api3.TriggerInfo
import kotlin.concurrent.thread

/**
 * Leitor RFID integrado do MC3390R / MC3330R, usando o SDK Zebra API3.
 *
 * Fluxo:
 *  1. conectar()  -> encontra o leitor interno e configura
 *  2. Operador aperta o gatilho -> Inventory.perform() (começa a ler)
 *  3. Cada tag lida chama aoLerTag(epc)
 *  4. Operador solta o gatilho  -> Inventory.stop()
 *
 * É um "object" (uma única instância) para conectar uma vez só e
 * reaproveitar a conexão em todas as telas.
 *
 * Todo erro do SDK é tratado aqui (catch Throwable): um problema no RFID
 * nunca pode fechar o app, só aparecer como mensagem na tela.
 */
object Rfid : RfidEventsListener {

    private var readers: Readers? = null
    private var leitor: RFIDReader? = null

    /** A tela que está aberta define o que fazer com cada EPC lido. */
    var aoLerTag: ((String) -> Unit)? = null

    /** Gatilho apertado (true) / solto (false) em modo RFID. */
    var aoGatilho: ((Boolean) -> Unit)? = null

    /** Fim de cada leitura: quantas etiquetas o leitor viu (ajuda a achar problemas). */
    var aoTerminarLeitura: ((Int) -> Unit)? = null

    @Volatile
    private var lidasNaLeitura = 0

    /** Problemas do leitor viram mensagem na tela (em vez de sumir em silêncio). */
    var aoAvisar: ((String) -> Unit)? = null

    private fun avisar(oque: String, e: Throwable) = aoAvisar?.invoke("RFID: $oque (${e.javaClass.simpleName}: ${e.message})")

    val conectado get() = leitor?.isConnected == true

    /**
     * Conecta igual ao app de exemplo oficial da Zebra (mesmo SDK do 123RFID):
     * primeiro pelo serviço USB (leitor interno do MC3300x), depois pelo serial
     * (MC3300R mais antigo). A mensagem diz qual funcionou.
     */
    fun conectar(context: Context, aoTerminar: (String) -> Unit) {
        if (conectado) return aoTerminar("RFID conectado")
        thread {
            val falhas = mutableListOf<String>()
            for ((transporte, nome) in listOf(ENUM_TRANSPORT.SERVICE_USB to "USB", ENUM_TRANSPORT.SERVICE_SERIAL to "serial")) {
                try {
                    val r = Readers(context, transporte)
                    val dispositivos = r.GetAvailableRFIDReaderList()
                    if (dispositivos.isNullOrEmpty()) {
                        r.Dispose()
                        falhas.add("$nome: nenhum leitor")
                        continue
                    }
                    val l = dispositivos[0].rfidReader
                    if (!l.isConnected) l.connect()
                    readers = r
                    leitor = l
                    configurar(l)
                    return@thread aoTerminar("RFID conectado: ${dispositivos[0].name} ($nome)")
                } catch (e: Throwable) {
                    falhas.add("$nome: ${e.javaClass.simpleName} ${e.message ?: ""}".trim())
                    desconectar()
                }
            }
            aoTerminar("RFID indisponível (" + falhas.joinToString("; ") + ")")
        }
    }

    /** Mesma configuração do exemplo da Zebra. */
    private fun configurar(r: RFIDReader) {
        // Receber eventos do gatilho e de tags lidas
        r.Events.addEventsListener(this)
        r.Events.setHandheldEvent(true)
        r.Events.setTagReadEvent(true)
        r.Events.setAttachTagDataWithReadEvent(false)

        // Gatilho do RFID (sem acender o leitor de código de barras)
        r.Config.setTriggerMode(ENUM_TRIGGER_MODE.RFID_MODE, true)

        // Leitura começa e para quando mandarmos (perform/stop), não sozinha
        val gatilho = TriggerInfo()
        gatilho.StartTrigger.setTriggerType(START_TRIGGER_TYPE.START_TRIGGER_TYPE_IMMEDIATE)
        gatilho.StopTrigger.setTriggerType(STOP_TRIGGER_TYPE.STOP_TRIGGER_TYPE_IMMEDIATE)
        r.Config.setStartTrigger(gatilho.StartTrigger)
        r.Config.setStopTrigger(gatilho.StopTrigger)

        try {
            // Antena: potência máxima e modo de RF padrão
            val config = r.Config.Antennas.getAntennaRfConfig(1)
            config.setTransmitPowerIndex(r.ReaderCapabilities.transmitPowerLevelValues.size - 1)
            config.setrfModeTableIndex(0)
            config.setTari(0)
            r.Config.Antennas.setAntennaRfConfig(1, config)

            // Sessão S1, estado A, todas as tags
            val singulacao = r.Config.Antennas.getSingulationControl(1)
            singulacao.setSession(SESSION.SESSION_S1)
            singulacao.Action.setInventoryState(INVENTORY_STATE.INVENTORY_STATE_A)
            singulacao.Action.setSLFlag(SL_FLAG.SL_ALL)
            r.Config.Antennas.setSingulationControl(1, singulacao)
        } catch (e: Throwable) {
            avisar("não foi possível configurar a antena", e)
        }

        // Tira filtros que outro app (ex.: 123RFID) tenha deixado gravados no leitor
        try {
            r.Actions.PreFilters.deleteAll()
        } catch (e: Throwable) {
            avisar("não foi possível limpar os filtros", e)
        }
    }

    /**
     * O gatilho do MC33xxR é compartilhado:
     *  RFID_MODE    -> gatilho lê tags RFID
     *  BARCODE_MODE -> gatilho aciona o leitor de código de barras
     */
    fun usarGatilhoParaRfid(rfid: Boolean) {
        val r = leitor ?: return
        thread {
            try {
                r.Config.setTriggerMode(
                    if (rfid) ENUM_TRIGGER_MODE.RFID_MODE else ENUM_TRIGGER_MODE.BARCODE_MODE, true
                )
            } catch (e: Throwable) {
                avisar("não foi possível trocar o gatilho", e)
            }
        }
    }

    /** Potência de 0 a 100%. Baixa = lê só o que está perto (útil na baixa). */
    fun potencia(percentual: Int) {
        val r = leitor ?: return
        thread {
            try {
                val niveis = r.ReaderCapabilities.transmitPowerLevelValues
                val config = r.Config.Antennas.getAntennaRfConfig(1)
                config.setTransmitPowerIndex((niveis.size - 1) * percentual / 100)
                r.Config.Antennas.setAntennaRfConfig(1, config)
            } catch (e: Throwable) {
                avisar("não foi possível ajustar a potência", e)
            }
        }
    }

    fun desconectar() {
        try {
            leitor?.Events?.removeEventsListener(this)
            leitor?.disconnect()
            readers?.Dispose()
        } catch (e: Throwable) {
        }
        leitor = null
        readers = null
    }

    // ------------------------------------------------ eventos do SDK

    /** Chegaram tags lidas: pega o EPC de cada uma e repassa para a tela. */
    override fun eventReadNotify(e: RfidReadEvents?) {
        try {
            val tags = leitor?.Actions?.getReadTags(100) ?: return
            lidasNaLeitura += tags.size
            for (tag in tags) aoLerTag?.invoke(tag.tagID)
        } catch (ex: Throwable) {
        }
    }

    /** Gatilho apertado -> começa a ler; solto -> para. */
    override fun eventStatusNotify(e: RfidStatusEvents?) {
        try {
            tratarGatilho(e)
        } catch (ex: Throwable) {
        }
    }

    private fun tratarGatilho(e: RfidStatusEvents?) {
        val dados = e?.StatusEventData ?: return
        if (dados.statusEventType != STATUS_EVENT_TYPE.HANDHELD_TRIGGER_EVENT) return
        val apertou = dados.HandheldTriggerEventData.handheldEvent ==
            HANDHELD_TRIGGER_EVENT_TYPE.HANDHELD_TRIGGER_PRESSED
        aoGatilho?.invoke(apertou)
        thread {
            try {
                if (apertou) iniciarLeitura() else pararLeitura()
            } catch (ex: Throwable) {
                avisar(if (apertou) "não começou a leitura" else "não parou a leitura", ex)
            }
        }
    }

    private fun iniciarLeitura() {
        lidasNaLeitura = 0
        leitor?.Actions?.Inventory?.perform()
    }

    private fun pararLeitura() {
        leitor?.Actions?.Inventory?.stop()
        Thread.sleep(300)   // últimas etiquetas ainda chegando
        aoTerminarLeitura?.invoke(lidasNaLeitura)
    }

    /** Lê por alguns segundos sem usar o gatilho (botão "Ler 3 s" da tela). */
    fun lerPor(ms: Long) {
        if (leitor == null) {
            aoAvisar?.invoke("RFID: leitor não conectado")
            return
        }
        thread {
            try {
                aoGatilho?.invoke(true)
                iniciarLeitura()
                Thread.sleep(ms)
                aoGatilho?.invoke(false)
                pararLeitura()
            } catch (ex: Throwable) {
                avisar("a leitura de teste falhou", ex)
            }
        }
    }
}
