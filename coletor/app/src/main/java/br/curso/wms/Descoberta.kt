package br.curso.wms

import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Acha o servidor do Mini WMS na rede Wi-Fi, sem precisar digitar o IP.
 *
 * Testa http://<rede>.1 até .254 na porta 8000 (vários de uma vez) e fica com
 * o primeiro que responde /api/status com "servidor":"Mini WMS".
 * Leva poucos segundos numa rede comum (/24, ex.: 192.168.0.x).
 */
object Descoberta {

    fun procurar(porta: Int = 8000): String? {
        val ip = ipDoColetor() ?: return null
        val rede = ip.substringBeforeLast('.')
        val achado = AtomicReference<String?>(null)
        val grupo = Executors.newFixedThreadPool(48)
        for (n in 1..254) {
            grupo.execute {
                if (achado.get() == null) {
                    val url = "http://$rede.$n:$porta"
                    if (ehServidor(url)) achado.compareAndSet(null, url)
                }
            }
        }
        grupo.shutdown()
        grupo.awaitTermination(20, TimeUnit.SECONDS)
        return achado.get()
    }

    /** IP do coletor na rede local (ex.: 192.168.0.57). */
    fun ipDoColetor(): String? = try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }
            .firstOrNull { it is Inet4Address && it.isSiteLocalAddress }
            ?.hostAddress
    } catch (e: Throwable) {
        null
    }

    private fun ehServidor(url: String): Boolean = try {
        val c = URL("$url/api/status").openConnection() as HttpURLConnection
        c.connectTimeout = 500
        c.readTimeout = 1000
        val ok = c.responseCode == 200 && c.inputStream.bufferedReader().use { it.readText() }.contains("\"servidor\":\"Mini WMS\"")
        c.disconnect()
        ok
    } catch (e: Throwable) {
        false
    }
}
