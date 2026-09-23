# Plano — Mini WMS RFID (didático)

Premissas: projeto para curso, sem complexidade; servidor local no PC; coletor Zebra MC3390R/MC3330R
só como interface de leitura; **toda regra e toda data/hora ficam no servidor**.

## Escopo

1. **Cadastro de produtos**: SKU, descrição, EAN (código de barras), unidade, estoque mínimo.
2. **Lotes com validade**: cada lote guarda seu saldo. Posição de estoque = produto × lote × validade × quantidade.
3. **Entrada**: pelo PC (quantidade), pelo coletor via RFID (1 tag = 1 unidade) ou via código de barras + quantidade.
4. **Baixa**: pelo PC ou pelo coletor.
   - Por quantidade (PC ou código de barras): o servidor escolhe os lotes por **FEFO**.
   - Por RFID: a tag identifica o lote; o servidor avisa quando isso fura o FEFO.
5. **Inventário**: abrir no PC, contar item por item (PC manual, coletor RFID ou código de barras),
   confrontar contado × sistema e fechar aplicando os ajustes.
6. **Movimentos**: histórico de tudo que alterou o saldo, com origem (PC/COLETOR) e meio (MANUAL/BARRAS/RFID).

## Arquitetura

- **Servidor**: Python + FastAPI + SQLite, com tela web em HTML/JS puro na mesma porta (8000).
- **Coletor**: Kotlin, Android puro (sem bibliotecas extras) + Zebra RFID API3. Faz chamadas HTTP diretas
  ao servidor e não tem banco local.

## Modelo de dados

```
produtos(id, sku, descricao, ean, unidade, estoque_min, ativo)
enderecos(id, codigo, descricao, tipo, ativo)      -- RECEBIMENTO | ARMAZENAGEM | EXPEDICAO
lotes(id, produto_id, lote, validade, quantidade, endereco_id, status, criado_em)  -- LIBERADO | BLOQUEADO
tags(epc, lote_id, status)                        -- ATIVA | BAIXADA
movimentos(id, data_hora, tipo, lote_id, quantidade, epc, origem, meio, motivo, documento, endereco, saldo_apos)
inventarios(id, nome, status, aberto_em, fechado_em)  -- ABERTO | FECHADO | CANCELADO
contagens(id, inventario_id, lote_id, quantidade, epc, origem, meio, data_hora)
pedidos(id, numero, cliente, observacao, status, criado_em, liberado_em, expedido_em)
pedido_itens(id, pedido_id, produto_id, quantidade)
reservas(id, pedido_id, item_id, lote_id, quantidade)
```

## Etapas

| # | Etapa | Situação |
|---|---|---|
| 1 | Servidor: cadastros, entrada, baixa FEFO, inventário, testes | feito |
| 2 | Tela web do PC | feito |
| 3 | App do coletor: menu, RFID, código de barras, 4 operações | feito (falta compilar e testar no MC33) |
| 4 | Teste no aparelho: potência RFID, DataWedge, rede | a fazer |
| 4b | Endereçamento, bloqueio de lote, pedidos com reserva FEFO, painel, kardex com CSV, simulador do coletor | feito |
| 5 | Material do curso: roteiro de aulas e exercícios | opcional |
