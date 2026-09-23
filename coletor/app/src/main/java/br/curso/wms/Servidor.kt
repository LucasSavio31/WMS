package br.curso.wms

/**
 * Endereço do servidor do PC (salvo nas preferências pela MainActivity).
 *
 * O app não tem regra de negócio nem banco de dados: as telas vêm do
 * servidor (/m) e toda regra fica lá.
 */
object Servidor {
    var url = "http://192.168.0.10:8000"
}
