package br.curso.wms

import android.content.Context
import android.util.Log
import com.zebra.rfid.RfidServiceMgr
import com.zebra.rfid.api3.ENUM_TRANSPORT
import com.zebra.rfid.api3.ENUM_TRIGGER_MODE
import com.zebra.rfid.api3.HANDHELD_TRIGGER_EVENT_TYPE
import com.zebra.rfid.api3.INVENTORY_STATE
import com.zebra.rfid.api3.MEMORY_BANK
import com.zebra.rfid.api3.OperationFailureException
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
import com.zebra.rfid.api3.TagAccess
import com.zebra.rfid.api3.TriggerInfo
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * Leitor RFID integrado do MC33xxR, usando o SDK Zebra API3 (o mesmo do 123RFID).
 *
 * Fluxo:
 *  1. conectar()  -> encontra o leitor interno e configura
 *  2. Operador aperta o gatilho -> Inventory.perform() (começa a ler)
 *  3. Cada tag lida chama aoLerTag(epc)
 *  4. Operador solta o gatilho  -> Inventory.stop()
 *
 * Regras que evitam o leitor "travar":
 *  - Todo comando vai para uma FILA ÚNICA (um de cada vez). Trocar o modo do
 *    gatilho ou a potência no meio de uma leitura faz o SDK recusar
 *    (OperationFailureException) e às vezes o leitor para de responder.
 *  - Com o gatilho em modo CÓDIGO DE BARRAS, apertar o gatilho não liga o RFID.
 *
 * Localizar etiqueta: com um EPC escolhido (definirAlvo), o gatilho faz
 * TagLocationing.Perform(epc) e o leitor devolve a "distância relativa"
 * (0 = longe, 100 = colado), que a tela mostra como quente/frio.
 *
 * Todo erro do SDK é tratado aqui (catch Throwable): um problema no RFID
 * nunca pode fechar o app, só aparecer como mensagem na tela.
 */
object Rfid : RfidEventsListener {

    private const val TAG = "ColetorWMS"

    private var readers: Readers? = null
    private var leitor: RFIDReader? = null

    /** A tela que está aberta define o que fazer com cada EPC lido. */
    var aoLerTag: ((String) -> Unit)? = null

    /** Gatilho apertado (true) / solto (false) em modo RFID. */
    var aoGatilho: ((Boolean) -> Unit)? = null

    /** Fim de cada leitura: quantas etiquetas o leitor viu (ajuda a achar problemas). */
    var aoTerminarLeitura: ((Int) -> Unit)? = null

    /** Localizar: proximidade da etiqueta procurada, de 0 (longe) a 100 (colado). */
    var aoLocalizar: ((Int) -> Unit)? = null

    /** Gravar etiqueta: (gravou?, mensagem, EPC antigo, EPC novo). */
    var aoGravar: ((Boolean, String, String, String) -> Unit)? = null

    /** Problemas do leitor viram mensagem na tela (em vez de sumir em silêncio). */
    var aoAvisar: ((String) -> Unit)? = null

    /** Fila única de comandos para o leitor. */
    private val fila = Executors.newSingleThreadExecutor()

    @Volatile private var modoRfid = true           // o que a tela quer (chave RFID / Código)
    @Volatile private var lendo = false             // Inventory.perform() em andamento
    @Volatile private var lidasNaLeitura = 0
    @Volatile private var alvo: String? = null      // EPC procurado na tela Localizar
    @Volatile private var localizando = false
    private var modoNoLeitor: Boolean? = null       // o que já foi enviado ao leitor
    private var potenciaNoLeitor: Int? = null

    val conectado get() = leitor?.isConnected == true

    private fun log(texto: String) = Log.i(TAG, texto)

    private fun avisar(oque: String, e: Throwable) {
        val detalhe = (e as? OperationFailureException)?.vendorMessage ?: e.message
        Log.w(TAG, "RFID: $oque ($detalhe)", e)
        aoAvisar?.invoke("RFID: $oque (${e.javaClass.simpleName}: $detalhe)")
    }

    /** Põe um comando na fila; erro vira aviso na tela. */
    private fun naFila(oque: String, comando: () -> Unit) {
        fila.execute {
            try {
                comando()
            } catch (e: Throwable) {
                avisar(oque, e)
            }
        }
    }

    // ------------------------------------------------ conexão

    /**
     * Conecta igual ao app de exemplo oficial da Zebra: primeiro pelo serviço
     * USB (MC3300x), depois pelo serial (MC3300R). A mensagem diz qual funcionou.
     */
    fun conectar(context: Context, aoTerminar: (String) -> Unit) {
        fila.execute {
            if (conectado) {
                aoTerminar("RFID conectado")
                return@execute
            }
            val falhas = mutableListOf<String>()
            for ((transporte, nome) in listOf(ENUM_TRANSPORT.SERVICE_USB to "USB", ENUM_TRANSPORT.SERVICE_SERIAL to "serial")) {
                try {
                    log("conectar: tentando $nome")
                    val r = Readers(context, transporte)
                    val dispositivos = r.GetAvailableRFIDReaderList()
                    log("conectar: $nome achou ${dispositivos?.size ?: 0} leitor(es)")
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
                    log("conectar: OK ${dispositivos[0].name} ($nome)")
                    aoTerminar("RFID conectado: ${dispositivos[0].name} ($nome)")
                    return@execute
                } catch (e: Throwable) {
                    Log.w(TAG, "conectar: falhou $nome", e)
                    falhas.add("$nome: ${e.javaClass.simpleName} ${e.message ?: ""}".trim())
                    soltarLeitor()
                }
            }
            log("conectar: nenhum transporte funcionou $falhas")
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

        // Leitura começa e para quando mandarmos (perform/stop), não sozinha
        val gatilho = TriggerInfo()
        gatilho.StartTrigger.setTriggerType(START_TRIGGER_TYPE.START_TRIGGER_TYPE_IMMEDIATE)
        gatilho.StopTrigger.setTriggerType(STOP_TRIGGER_TYPE.STOP_TRIGGER_TYPE_IMMEDIATE)
        r.Config.setStartTrigger(gatilho.StartTrigger)
        r.Config.setStopTrigger(gatilho.StopTrigger)

        // LED verde piscando a cada leitura (fica gravado no serviço RFID do sistema e vale
        // para todos os apps; religa sempre ao conectar, caso tenha ficado desligado)
        try {
            r.Config.setLedBlinkEnable(true)
            log("LED: piscar a cada leitura ligado")
        } catch (e: Throwable) {
            Log.w(TAG, "LED: não ligou a piscada (${e.message})")
        }

        try {
            // Antena: potência máxima e modo de RF padrão
            val config = r.Config.Antennas.getAntennaRfConfig(1)
            config.setTransmitPowerIndex(r.ReaderCapabilities.transmitPowerLevelValues.size - 1)
            config.setrfModeTableIndex(0)
            config.setTari(0)
            r.Config.Antennas.setAntennaRfConfig(1, config)
            potenciaNoLeitor = 100

            // Sessão S0: toda etiqueta responde a cada rodada (na S1 a etiqueta já lida fica
            // alguns segundos "calada"; boa para milhares de tags, ruim para contar poucas dezenas)
            val singulacao = r.Config.Antennas.getSingulationControl(1)
            singulacao.setSession(SESSION.SESSION_S0)
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

        // Gatilho no modo que a tela pediu
        modoNoLeitor = null
        aplicarModo(r)
    }

    /** Solta o leitor (app em segundo plano): o 123RFID e outros apps podem usar. */
    fun desconectar() {
        fila.execute { soltarLeitor() }
    }

    private fun soltarLeitor() {
        try {
            if (localizando) leitor?.Actions?.TagLocationing?.Stop()
            if (lendo) leitor?.Actions?.Inventory?.stop()
        } catch (e: Throwable) {
        }
        localizando = false
        try {
            leitor?.Events?.removeEventsListener(this)
            leitor?.disconnect()
        } catch (e: Throwable) {
        }
        try {
            readers?.Dispose()
        } catch (e: Throwable) {
        }
        lendo = false
        leitor = null
        readers = null
        modoNoLeitor = null
        potenciaNoLeitor = null
    }

    // ------------------------------------------------ modo do gatilho e potência

    /**
     * O gatilho do MC33xxR é compartilhado:
     *  RFID_MODE    -> gatilho lê tags RFID
     *  BARCODE_MODE -> gatilho aciona o leitor de código de barras
     */
    fun usarGatilhoParaRfid(rfid: Boolean) {
        modoRfid = rfid
        log("gatilho para ${if (rfid) "RFID" else "código de barras"}")
        naFila("não foi possível trocar o gatilho") {
            val r = leitor ?: return@naFila
            if (!rfid && lendo) parar(r)   // saiu do RFID no meio de uma leitura
            aplicarModo(r)
        }
    }

    /** Só manda ao leitor se mudou (a tela pede o modo a cada troca de tela). */
    private fun aplicarModo(r: RFIDReader) {
        if (modoNoLeitor == modoRfid) return
        if (lendo) parar(r)
        pararLocalizar(r)
        r.Config.setTriggerMode(if (modoRfid) ENUM_TRIGGER_MODE.RFID_MODE else ENUM_TRIGGER_MODE.BARCODE_MODE, true)
        modoNoLeitor = modoRfid
    }

    /** Potência de 0 a 100%. Baixa = lê só o que está perto (útil na baixa). */
    fun potencia(percentual: Int) {
        naFila("não foi possível ajustar a potência") {
            val r = leitor ?: return@naFila
            if (potenciaNoLeitor == percentual) return@naFila
            if (lendo) parar(r)
            pararLocalizar(r)
            aplicarPotencia(r, percentual)
        }
    }

    private fun aplicarPotencia(r: RFIDReader, percentual: Int) {
        val niveis = r.ReaderCapabilities.transmitPowerLevelValues
        val config = r.Config.Antennas.getAntennaRfConfig(1)
        config.setTransmitPowerIndex((niveis.size - 1) * percentual.coerceIn(1, 100) / 100)
        r.Config.Antennas.setAntennaRfConfig(1, config)
        potenciaNoLeitor = percentual
        log("potência $percentual%")
    }

    // ------------------------------------------------ gravar etiqueta (regravar o EPC)

    @Volatile private var coletando = false
    private val achadas = ConcurrentHashMap<String, Short>()   // EPC -> RSSI mais forte

    /**
     * Grava [texto] (hexadecimal) como o novo EPC da etiqueta que está perto da antena.
     *  1. Lê por 0,7 s na potência de gravação e escolhe a etiqueta: tem que haver uma só
     *     (ou uma bem mais forte que as outras), para não gravar a etiqueta vizinha.
     *  2. Grava pelo Tag ID (writeTagIDWait, que também ajusta o tamanho do EPC):
     *     primeiro com o tamanho exato (completado com 0 à esquerda até múltiplo de 4, pois o EPC
     *     é gravado em palavras de 16 bits); se a etiqueta não aceitar, com 24 dígitos (96 bits).
     *  3. Último recurso: escreve direto no banco EPC (palavra 2 em diante) os 24 dígitos.
     */
    fun gravar(texto: String, potenciaGravacao: Int) {
        naFila("não gravou a etiqueta") {
            val r = leitor
            if (r == null) {
                aoGravar?.invoke(false, "Leitor RFID não conectado", "", "")
                return@naFila
            }
            val hex = texto.trim().uppercase()
            if (hex.isEmpty() || hex.length > 24 || !hex.all { it in "0123456789ABCDEF" }) {
                aoGravar?.invoke(false, "O código tem que ter até 24 caracteres, só números e letras de A a F", "", "")
                return@naFila
            }
            if (lendo) parar(r)
            pararLocalizar(r)

            // 1) acha a etiqueta perto da antena
            val potenciaAntes = potenciaNoLeitor ?: 100
            achadas.clear()
            try {
                aplicarPotencia(r, potenciaGravacao)
                coletando = true
                r.Actions.Inventory.perform()
                Thread.sleep(700)
                r.Actions.Inventory.stop()
                Thread.sleep(250)
            } finally {
                coletando = false
                aplicarPotencia(r, potenciaAntes)
            }
            val ordem = achadas.entries.sortedByDescending { it.value }
            log("gravar: ${ordem.size} etiqueta(s) perto ${ordem.take(3).map { "${it.key}(${it.value})" }}")
            if (ordem.isEmpty()) {
                aoGravar?.invoke(false, "Nenhuma etiqueta perto: encoste o coletor na etiqueta", "", "")
                return@naFila
            }
            if (ordem.size > 1 && ordem[0].value - ordem[1].value < 10) {
                aoGravar?.invoke(false, "Mais de uma etiqueta perto: deixe só a que vai gravar (ou baixe a potência de gravação)", "", "")
                return@naFila
            }
            val antiga = ordem[0].key

            // 2) grava: tamanho exato; se não der, 24 dígitos
            val exato = hex.padStart((hex.length + 3) / 4 * 4, '0')
            val cheio = hex.padStart(24, '0')
            var erro = ""
            for (dado in listOf(exato, cheio).distinct()) {
                try {
                    val p = TagAccess().WriteSpecificFieldAccessParams()
                    p.setAccessPassword(0)
                    p.setWriteData(dado)
                    p.setWriteDataLength(dado.length / 4)
                    r.Actions.TagAccess.writeTagIDWait(antiga, p, null)
                    log("gravar: $antiga -> $dado")
                    aoGravar?.invoke(true, "Gravado", antiga, dado)
                    return@naFila
                } catch (e: Throwable) {
                    erro = (e as? OperationFailureException)?.vendorMessage ?: e.message ?: e.javaClass.simpleName
                    Log.w(TAG, "gravar: writeTagIDWait $dado falhou ($erro)")
                }
            }
            // 3) último recurso: banco EPC a partir da palavra 2 (depois do CRC e do PC)
            try {
                val p = TagAccess().WriteAccessParams()
                p.setAccessPassword(0)
                p.setMemoryBank(MEMORY_BANK.MEMORY_BANK_EPC)
                p.setOffset(2)
                p.setWriteData(cheio)
                p.setWriteDataLength(cheio.length / 4)
                r.Actions.TagAccess.writeWait(antiga, p, null, null, true, false)
                log("gravar (banco EPC): $antiga -> $cheio")
                aoGravar?.invoke(true, "Gravado", antiga, cheio)
            } catch (e: Throwable) {
                val detalhe = (e as? OperationFailureException)?.vendorMessage ?: e.message ?: erro
                Log.w(TAG, "gravar: writeWait falhou ($detalhe)")
                aoGravar?.invoke(false, "A etiqueta não aceitou a gravação ($detalhe)", antiga, "")
            }
        }
    }

    // ------------------------------------------------ leitura

    private fun iniciar(r: RFIDReader) {
        if (lendo) return
        lidasNaLeitura = 0
        log("iniciar leitura (perform)")
        try {
            r.Actions.Inventory.perform()
        } catch (e: OperationFailureException) {
            // Leitor ainda ocupado com a leitura anterior: para e tenta de novo uma vez
            Log.w(TAG, "perform recusado (${e.vendorMessage}); parando e tentando de novo")
            try {
                r.Actions.Inventory.stop()
            } catch (x: Throwable) {
            }
            Thread.sleep(150)
            r.Actions.Inventory.perform()
        }
        lendo = true
    }

    private fun parar(r: RFIDReader) {
        if (!lendo) return
        lendo = false
        r.Actions.Inventory.stop()
        Thread.sleep(300)   // últimas etiquetas ainda chegando
        log("parar leitura: $lidasNaLeitura tag(s)")
        aoTerminarLeitura?.invoke(lidasNaLeitura)
    }

    // ------------------------------------------------ localizar etiqueta

    /** Escolhe a etiqueta procurada (null = sai do modo localizar). */
    fun definirAlvo(epc: String?) {
        alvo = epc?.trim()?.uppercase()?.ifEmpty { null }
        log("localizar: alvo ${alvo ?: "nenhum"}")
        if (alvo == null) naFila("não parou a localização") { leitor?.let { pararLocalizar(it) } }
        else ligarEstrobo()
    }

    // LED verde em estrobo no modo localizar. Quem acende o LED é o serviço RFID do sistema
    // (o mesmo que pisca o LED a cada leitura no 123RFID): ledBlink() dá uma piscada.
    // Procurando, pisca mais rápido quanto mais perto da etiqueta.
    @Volatile private var proximidade = 0
    private var estrobo: Thread? = null

    private fun ligarEstrobo() {
        if (estrobo?.isAlive == true) return
        estrobo = thread(name = "estrobo") {
            val servico = try { RfidServiceMgr.getInstance() } catch (e: Throwable) { null }
            if (servico == null) {
                Log.w(TAG, "LED: serviço RFID não encontrado")
                return@thread
            }
            log("LED: estrobo ligado")
            while (alvo != null) {
                try {
                    servico.ledBlink()
                } catch (e: Throwable) {
                    Log.w(TAG, "LED: sem suporte (${e.message})")   // segue sem piscar, sem erro na tela
                    return@thread
                }
                Thread.sleep(if (localizando) 60L + (100 - proximidade.coerceIn(0, 100)) * 3L else 150L)
            }
            log("LED: estrobo desligado")
        }
    }

    /** Liga/desliga a procura sem usar o gatilho (botão da tela). */
    fun procurar(ligar: Boolean) {
        naFila(if (ligar) "não começou a localização" else "não parou a localização") {
            val r = leitor ?: return@naFila
            if (ligar) iniciarLocalizar(r) else pararLocalizar(r)
        }
    }

    private fun iniciarLocalizar(r: RFIDReader) {
        val epc = alvo ?: return
        if (localizando) return
        if (lendo) parar(r)
        log("localizar: procurando $epc")
        r.Actions.TagLocationing.Perform(epc, null, null)
        localizando = true
    }

    private fun pararLocalizar(r: RFIDReader) {
        if (!localizando) return
        localizando = false
        try {
            r.Actions.TagLocationing.Stop()
        } catch (e: Throwable) {
            r.Actions.Inventory.stop()
        }
        log("localizar: parou")
        aoLocalizar?.invoke(-1)   // -1 = procura parada
    }

    /** Lê por alguns segundos sem usar o gatilho (botão "Ler 3 s" da tela). */
    fun lerPor(ms: Long) {
        log("ler por $ms ms (leitor ${if (leitor == null) "NÃO conectado" else "conectado"})")
        if (leitor == null) {
            aoAvisar?.invoke("RFID: leitor não conectado")
            return
        }
        aoGatilho?.invoke(true)
        naFila("a leitura de teste falhou") { leitor?.let { iniciar(it) } }
        thread {
            Thread.sleep(ms)
            aoGatilho?.invoke(false)
            naFila("a leitura de teste não parou") { leitor?.let { parar(it) } }
        }
    }

    // ------------------------------------------------ eventos do SDK

    /** Chegaram tags lidas: pega o EPC de cada uma e repassa para a tela. */
    override fun eventReadNotify(e: RfidReadEvents?) {
        try {
            val tags = leitor?.Actions?.getReadTags(100) ?: return
            if (coletando) {
                for (tag in tags) achadas.merge(tag.tagID, tag.peakRSSI) { a, b -> if (b > a) b else a }
                return
            }
            if (localizando) {
                for (tag in tags) if (tag.isContainsLocationInfo) {
                    proximidade = tag.LocationInfo.relativeDistance.toInt()
                    aoLocalizar?.invoke(proximidade)
                }
                return
            }
            lidasNaLeitura += tags.size
            for (tag in tags) aoLerTag?.invoke(tag.tagID)
        } catch (ex: Throwable) {
        }
    }

    /** Gatilho apertado -> começa a ler; solto -> para. Só em modo RFID. */
    override fun eventStatusNotify(e: RfidStatusEvents?) {
        try {
            val dados = e?.StatusEventData ?: return
            if (dados.statusEventType != STATUS_EVENT_TYPE.HANDHELD_TRIGGER_EVENT) return
            val apertou = dados.HandheldTriggerEventData.handheldEvent ==
                HANDHELD_TRIGGER_EVENT_TYPE.HANDHELD_TRIGGER_PRESSED
            if (!modoRfid) {
                log("gatilho ${if (apertou) "apertado" else "solto"} em modo código de barras: RFID não liga")
                if (!apertou && lendo) naFila("não parou a leitura") { leitor?.let { parar(it) } }
                return
            }
            aoGatilho?.invoke(apertou)
            if (alvo != null) {   // tela Localizar: o gatilho procura a etiqueta escolhida
                naFila(if (apertou) "não começou a localização" else "não parou a localização") {
                    val r = leitor ?: return@naFila
                    if (apertou) iniciarLocalizar(r) else pararLocalizar(r)
                }
                return
            }
            naFila(if (apertou) "não começou a leitura" else "não parou a leitura") {
                val r = leitor ?: return@naFila
                if (apertou) iniciar(r) else parar(r)
            }
        } catch (ex: Throwable) {
        }
    }
}
