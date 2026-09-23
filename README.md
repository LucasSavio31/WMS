# Mini WMS RFID — projeto didático

Controle de estoque simples com **leitor Zebra MC3390R / MC3330R** (Android, RFID + código de barras).

```
   COLETOR (Android)                          PC (servidor local)
 ┌──────────────────────┐   Wi-Fi / HTTP   ┌─────────────────────────────┐
 │ só lê e envia:       │ ───────────────► │ FastAPI (Python)            │
 │  - tags RFID (EPC)   │   JSON           │  - todas as regras (FEFO…)  │
 │  - código de barras  │ ◄─────────────── │  - data/hora do movimento   │
 │ mostra a resposta    │                  │  - banco SQLite estoque.db  │
 └──────────────────────┘                  │  - tela web no navegador    │
                                           └─────────────────────────────┘
```

O coletor **não tem regra nem banco de dados**: ele só envia o que leu. Quem decide o lote (FEFO),
confere o saldo e grava a data/hora é o servidor. Por isso o relógio do coletor não precisa estar certo.

## Jeito fácil: baixar pronto

Na página **Releases** do repositório (lado direito, "Releases" → última versão), baixe:

| Arquivo | Onde | Como usar |
|---|---|---|
| `WMS-Servidor.exe` | PC com Windows | Coloque numa pasta (ex.: `C:\WMS`) e dê dois cliques. Não precisa instalar nada. O navegador abre sozinho em http://localhost:8000. O banco `estoque.db` é criado na mesma pasta. |
| `ColetorWMS.apk` | Coletor Zebra | Copie para o coletor e instale. Talvez seja preciso permitir *instalar apps de fontes desconhecidas*. Na primeira vez, o app pergunta o endereço do servidor: digite o que aparece na janela do servidor ("Usar no coletor"). Depois configure o DataWedge (seção 2). |

- Na primeira execução, o Windows pode mostrar "O Windows protegeu o computador": clique em *Mais informações* e depois em *Executar assim mesmo*.
- Quando aparecer o aviso do Firewall, clique em **Permitir acesso**. Isso é necessário para o coletor alcançar o PC.
- O PC e o coletor precisam estar na mesma rede Wi-Fi.

Os dois arquivos são gerados automaticamente pelo GitHub Actions (`.github/workflows/build.yml`) a cada alteração no `main`.

## Funções

| Onde | O quê |
|---|---|
| PC | **Produtos**: cadastro (SKU, descrição, EAN, unidade, mínimo) |
| PC | **Ordens de recebimento**: nota fiscal, fornecedor e itens esperados (lote e validade opcionais); acompanha as leituras do coletor ao vivo e finaliza |
| PC | **Estoque**, **Inventário** (resultado e fechamento) e **Histórico** (com CSV) |
| Coletor | **Recebimento**: escolhe a ordem e o item, lê as etiquetas (cada uma vai na hora para o servidor) |
| Coletor | **Entrada** sem ordem: produto, lote, etiquetas RFID ou quantidade |
| Coletor | **Baixa automática**: cada etiqueta lida é baixada na hora (potência 30%); "desfazer" devolve ao estoque; produto sem etiqueta: código de barras + quantidade (FEFO) |
| Coletor | **Inventário**: inicia no coletor, lê as etiquetas; ao finalizar, etiqueta não lida sai e etiqueta achada volta |
| Coletor | **Localizar etiqueta**: escolhe o EPC e segura o gatilho; barra quente/frio e bipe mais rápido quanto mais perto |

**FEFO** (*First Expired, First Out*): na baixa por quantidade e nos pedidos, o servidor tira primeiro do lote
que vence antes. Ficam de fora: lotes **vencidos** (a não ser que o motivo da baixa seja `VENCIMENTO`),
lotes **bloqueados**, unidades **com etiqueta RFID** (só saem lendo a tag) e o que já está **reservado** para pedidos.
Na baixa por RFID, a tag já indica o lote. Se existir outro lote que vence antes, o servidor devolve um aviso.

**Fluxo de saída para cliente**: criar o pedido → *Liberar para separação* (o sistema reserva os lotes por FEFO e
monta a lista de separação em ordem de endereço) → separar e conferir cada linha → *Confirmar expedição* (baixa com
motivo VENDA e o número do pedido como documento). Cancelar devolve a reserva.

**Ordem de recebimento (pré-recebimento)**: no PC, *Ordens de recebimento* → nota fiscal, fornecedor e itens
esperados (produto, lote, validade, quantidade). No coletor, *Recebimento* → escolhe a ordem → toca no item (ou bipa
o código de barras do produto) → aperta o gatilho nas etiquetas. Cada etiqueta é gravada na hora e aparece no PC.
O sistema recusa etiqueta já em estoque, já lida em outra ordem e item que já completou a quantidade. *Finalizar*
(no PC ou no coletor) dá entrada de tudo que foi lido, com a NF como documento, e mostra as divergências.

**Endereçamento**: cada lote fica em um endereço. O lote novo entra na `DOCA-REC` e depois é *armazenado*
(transferido) para um endereço de estoque. A transferência fica registrada nos movimentos.

**Inventário**: cada contagem (do PC ou do coletor) é gravada. A tela mostra, lote a lote,
*Sistema × Contado × Diferença*. Ao **fechar**, o saldo do sistema passa a ser o contado
(lote não contado fica com zero), e cada ajuste fica registrado nos movimentos.

**Excluir produto** apaga também os lotes, as tags, os movimentos, as contagens e os itens de pedido dele.
Para só parar de usar, desmarque *Ativo*.

**Limpar tudo** (menu lateral, grupo *Sistema*): zera o banco para recomeçar uma aula. Opcionalmente mantém
o cadastro de produtos e endereços e apaga só a movimentação.

**Simulador do coletor**: http://localhost:8000/coletor mostra o app do coletor no navegador (as mesmas telas /m).
O gatilho é simulado por um botão (ou a tecla F8), com etiquetas RFID e códigos de barras "na frente do leitor"
num painel ao lado.

---|---|---|
| Cadastro de produtos (SKU, descrição, EAN, mínimo) | ✔ | — |
| Posição de estoque por produto e lote, com validade | ✔ | Consulta |
| Entrada | Quantidade digitada | RFID (cada tag = 1 unidade) ou código de barras + quantidade |
| Baixa | Quantidade (FEFO automático) ou EPC | RFID ou código de barras + quantidade (FEFO) |
| Inventário (contagem × sistema) | Abrir, contar item por item, ver diferenças e fechar | Contar por RFID ou por código de barras |
| Histórico de movimentos | ✔ | — |

**FEFO** (*First Expired, First Out*): na baixa por quantidade, o servidor tira primeiro do lote
que vence antes. Lotes vencidos ficam de fora, a não ser que o motivo da baixa seja `VENCIMENTO`.
Unidades com etiqueta RFID também ficam de fora: elas só saem lendo a tag.
Na baixa por RFID, a tag já indica o lote. Se existir outro lote que vence antes, o servidor devolve um aviso.

**Inventário**: cada contagem (do PC ou do coletor) é gravada. A tela mostra, lote a lote,
*Sistema × Contado × Diferença*. Ao **fechar**, o saldo do sistema passa a ser o contado,
e cada ajuste fica registrado nos movimentos.

---

## 1. Servidor no PC

Precisa do **Python 3.10+** (python.org; na instalação, marque *Add Python to PATH*).

```bat
cd server
iniciar.bat          (Windows)
./iniciar.sh         (Linux/macOS)
```

- Tela do PC: <http://localhost:8000>
- Documentação automática da API: <http://localhost:8000/docs>
- No coletor, use o **IP do PC** (comando `ipconfig`), por exemplo `http://192.168.0.10:8000`.
- O PC e o coletor precisam estar na **mesma rede Wi-Fi**. Na primeira execução, libere o Python no Firewall do Windows.

Testes automáticos: `pip install -r requirements-dev.txt` e depois `pytest`.

### Arquivos

| Arquivo | O que tem |
|---|---|
| `server/app/db.py` | Tabelas do banco e migração automática de bancos antigos |
| `server/app/estoque.py` | **Regras**: entrada, baixa FEFO, baixa por tag, endereços, bloqueio, pedidos, inventário |
| `server/app/main.py` | Rotas da API (`/api/...`) usadas pelo PC e pelo coletor |
| `server/app/static/index.html` | Tela web (HTML + JavaScript puro) |
| `server/app/static/m.html` | Telas do coletor (abre em `/m`; dentro do app ou no Chrome) |
| `server/app/static/coletor.html` | Simulador do app do coletor no PC (abre em `/coletor`) |
| `server/wms_servidor.py` | Inicia o servidor e abre o navegador (vira o `WMS-Servidor.exe`) |

---

## 2. App do coletor (recomendado)

O app **Coletor WMS** (`ColetorWMS.apk`) é uma "casca": ele mostra as telas do servidor (**/m**) e cuida do que
o navegador não faz sozinho:

- **RFID**: o app lê as etiquetas pelo SDK da Zebra (o mesmo do 123RFID) e entrega cada EPC para a tela.
- **Código de barras**: vem pelo **DataWedge**, que "digita" o código na tela.
- **Gatilho**: é um só para RFID e código de barras. A chave **📡 RFID / ▮▮ Código**, ao lado do campo
  *Leitura*, mostra o que ele lê. Cada tela escolhe sozinha o modo mais provável (ex.: no Recebimento começa
  em código para bipar o produto e passa para RFID depois), e um toque na chave troca.
- **Potência da antena**: 30% na Baixa (lê só o que está bem perto) e 100% nas outras telas.
- Sem barra do Chrome; hora, Wi-Fi e bateria ficam na barra do próprio Android.
- Em segundo plano, o app solta o leitor RFID (assim o 123RFID e outros apps conseguem usar).

Telas: Recebimento (RFID ou quantidade), Armazenar (tag/produto e depois a etiqueta do endereço), Baixa
(RFID ou FEFO por quantidade), Separação de pedidos (confere bipando o produto), Inventário e Consulta
(tag, produto ou endereço). O botão ⚙ troca o endereço do servidor. Como as telas vêm do servidor,
qualquer melhoria chega ao coletor sem reinstalar o app.

**Como a tela entende cada leitura:** EPC (hexadecimal com 16+ caracteres) = RFID; código igual a um endereço
cadastrado = endereço; o resto = produto (EAN ou SKU). Por isso vale imprimir etiquetas com o código dos endereços.

### Configurar o DataWedge (uma vez, no coletor)

O DataWedge fica só com o **código de barras**; o RFID é do app. Os nomes podem variar com a versão.

1. **DataWedge** → menu ⋮ → **New profile** → nome `WMS` (se já criou para o Chrome, use o mesmo).
2. **Associated apps** → ⋮ → **New app/activity** → **br.curso.wms** (Coletor WMS) → `*`.
   Se o perfil estava associado ao `com.android.chrome`, pode remover essa associação.
3. **Barcode input**: **ativado**. Em modo 📡 RFID o próprio app desliga o leitor de código de barras do
   DataWedge (pela API de Intent), senão o DataWedge "pega" o gatilho; em modo ▮▮ Código, religa.
4. **RFID input**: **desativado** (se ficar ligado, o DataWedge disputa o leitor com o app).
5. **Keystroke output**: ativado → *Basic data formatting*: **Send data** e **Send ENTER key** ativados.
   Intent output: desativado.
6. Se aparecerem caracteres faltando, aumente o *inter character delay* do Keystroke output.

### Testar sem o coletor

- **http://localhost:8000/coletor**: simulador do app. A tela /m roda dentro do desenho do aparelho, e um
  painel ao lado faz o papel do gatilho (etiquetas RFID "ao alcance da antena" e códigos de barras).
- **http://localhost:8000/m** no navegador: digite o código ou o EPC no campo *Leitura* e tecle Enter.

## 3. Alternativa: só o Chrome, sem app

A tela **/m** também funciona direto no Chrome do coletor, com o DataWedge "digitando" as leituras. Em alguns
aparelhos/versões o **RFID input** do DataWedge não funciona (o gatilho só lê código de barras). Nesse caso use o app.

- No perfil `WMS` do DataWedge, associe `com.android.chrome` e ative **Barcode input** e **RFID input**
  (*Hardware trigger* e *Filter duplicate tags* ligados), além do Keystroke output com ENTER.
- **Tela cheia**: no primeiro toque a página esconde a barra de endereços (dá para desligar no ⚙). Se o Chrome
  sair da tela cheia, aparece o botão ⛶ e o próximo toque volta.
- **Teclado virtual**: fica escondido enquanto se lê com o gatilho; abre nos campos de digitação e no ⌨.
- **Barra de status** (em tela cheia): hora do servidor, Wi-Fi (qualidade da conexão com o servidor, pelo
  tempo de resposta) e bateria.
- **Abrir sem a barra do Chrome e com bateria**: no Chrome do coletor, `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
  → coloque `http://IP-DO-PC:8000` → ative → **Relaunch**. Depois abra `/m` → ⋮ → **Instalar app**.
  (Necessário porque o servidor usa `http://` na rede local, sem certificado.)

### Dá para usar o VS Code?

Sim. O projeto é Gradle puro, sem nada que dependa do Android Studio. O VS Code serve para editar,
e a compilação e a instalação são feitas pelo terminal. O Android Studio só facilita a depuração
(Logcat) e o editor visual de telas, mas é opcional.

**Instalação (uma vez):**

1. **JDK 17** (ex.: Temurin 17).
2. **Android SDK Command-line Tools** (developer.android.com/studio, seção *Command line tools only*).
   Descompacte em `C:\Android\cmdline-tools\latest` e instale os pacotes:
   ```bat
   sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
   ```
3. Crie `coletor/local.properties` com o caminho do SDK:
   ```
   sdk.dir=C\:\\Android
   ```
4. Baixe o SDK RFID da Zebra (API3) para `coletor/app/libs/API3_LIB-release.aar`. É o mesmo arquivo que o build automático usa:
   `https://raw.githubusercontent.com/ZebraDevs/RFID-Android-Inventory-Sample/master/RFIDAPI3Library/API3_LIB-release-2.0.2.82.aar`
5. VS Code: extensões *Kotlin* (fwcd.kotlin) e *Gradle for Java*.

**Compilar e instalar** (coletor ligado no USB, com *Depuração USB* ativada nas *Opções do desenvolvedor*):

```bat
cd coletor
gradlew assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

### Arquivos

| Arquivo | O que tem |
|---|---|
| `MainActivity.kt` | WebView com a tela /m, ponte JavaScript (`ColetorApp`), endereço do servidor |
| `Rfid.kt` | Leitor RFID Zebra (API3): conectar, gatilho, potência, tags lidas |
| `Servidor.kt` | Endereço do servidor |

### Ponte entre o app e a tela

| Quem chama | O quê | Para quê |
|---|---|---|
| App → tela | `leituraRfid(epc)` | cada etiqueta lida pelo RFID |
| App → tela | `statusRfid(mensagem)` | leitor RFID conectou (ou não) |
| Tela → app | `ColetorApp.gatilhoRfid(true/false)` | gatilho lê RFID ou código de barras (`setTriggerMode`) |
| Tela → app | `ColetorApp.potencia(%)` | potência da antena |
| Tela → app | `ColetorApp.servidor()` | abre o popup do endereço do servidor |

---

## Simplificações (de propósito, por ser didático)

- Sem login nem senha, e sem HTTPS: é para uso em rede local.
- Endereçamento por lote: o lote inteiro fica em um endereço (a transferência move o lote todo).
- Se a rede cair, o coletor mostra o erro e o operador envia de novo. Não existe fila offline.
