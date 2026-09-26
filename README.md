# Mini WMS RFID — projeto didático

Controle de estoque simples com **leitor Zebra MC3390R / MC3330R** (Android, RFID + código de barras).

```
   COLETOR (Android)                          PC (servidor local)
 ┌──────────────────────┐   Wi-Fi / HTTP   ┌─────────────────────────────┐
 │ só lê e envia:       │ ───────────────► │ FastAPI (Python)            │
 │  - tags RFID (EPC)   │   JSON           │  - todas as regras          │
 │  - código de barras  │ ◄─────────────── │  - data/hora do movimento   │
 │ mostra a resposta    │                  │  - banco SQLite estoque.db  │
 └──────────────────────┘                  │  - tela web no navegador    │
                                           └─────────────────────────────┘
```

O coletor **não tem regra nem banco de dados**: ele só envia o que leu. Quem confere a etiqueta e o saldo,
decide o local e grava a data/hora é o servidor. Por isso o relógio do coletor não precisa estar certo.

## Componentes e tecnologias

O projeto tem quatro partes. As duas primeiras rodam no PC (no mesmo programa); as outras duas são apps
separados no coletor.

| Parte | O que é | Tecnologias |
|---|---|---|
| **Servidor** (`server/`) | O "cérebro": guarda o estoque, aplica todas as regras (entrada, baixa, locais, inventário, ordens de recebimento), grava cada movimento com data/hora e gera os relatórios. Serve as telas do PC e do coletor e a API que o coletor usa. | Python 3.11, **FastAPI** (API HTTP/JSON), **Uvicorn** (servidor web), **Pydantic** (validação dos dados), **SQLite** em modo WAL (banco em um arquivo), **fpdf2** (relatórios PDF), **PyInstaller** (gera o `WMS-Servidor.exe`), **pytest** (testes automáticos) |
| **Tela do PC** (`server/app/static/index.html`) | Sistema de estoque no navegador: Dashboard, Estoque (mover entre locais), Locais, Produtos, Ordens de recebimento, Baixa, Inventário e Histórico. Atualiza sozinha a cada 5 s (as leituras do coletor aparecem na hora). | HTML, CSS e **JavaScript puro** (sem framework), `fetch` para a API, tema claro/escuro automático |
| **Coletor WMS** (`ColetorWMS.apk`, `coletor/app/`) | App de estoque do coletor: Recebimento, Entrada, Baixa, Inventário, Consulta, Localizar etiqueta, Gravar etiqueta e Config. É uma "casca" que mostra as telas do servidor (`/m`) e cuida do hardware: **leitor RFID**, gatilho, código de barras, bipe e LED. Acha o servidor na rede Wi-Fi sozinho. | **Kotlin**, Android **WebView** com ponte JavaScript (`ColetorApp`), **Zebra RFID SDK API3** 2.0.2.82 (o mesmo do 123RFID), **DataWedge** (código de barras) com a API de Intent, Gradle 8 / Android Gradle Plugin 8.5, JDK 17 |
| **AppCenter** (`AppCenter.apk`, `coletor/appcenter/`) | Tela inicial do coletor em **modo quiosque** (como o AppCenter dos MC9090): fundo branco e só os apps liberados; área do administrador com 5 toques + PIN. Volta sozinho ao ligar o coletor. | **Kotlin**, só o Android (sem bibliotecas), **Device Owner** (`DevicePolicyManager`), modo **Lock Task** do Android, `activity-alias` de tela inicial (HOME), `BootReceiver` |

Os três arquivos prontos (`WMS-Servidor.exe`, `ColetorWMS.apk` e `AppCenter.apk`) são gerados pelo **GitHub Actions**
(`.github/workflows/build.yml`) a cada alteração no `main`: roda os testes, compila e publica na página **Releases**.

## Jeito fácil: baixar pronto

Os programas prontos estão na pasta **[`downloads/`](downloads/)** deste repositório (e também na página
**Releases**, lado direito → última versão):

- [**WMS-Servidor.exe**](downloads/WMS-Servidor.exe): servidor + telas, para o PC com Windows
- [**ColetorWMS.apk**](downloads/ColetorWMS.apk): app de estoque do coletor
- [**AppCenter.apk**](downloads/AppCenter.apk): tela inicial em modo quiosque do coletor

No GitHub, abra o arquivo e clique em **Download raw file** (ícone ⬇ à direita).

| Arquivo | Onde | Como usar |
|---|---|---|
| `WMS-Servidor.exe` | PC com Windows (qualquer um, sem instalar nada) | Crie uma pasta (ex.: `C:\WMS`), coloque o `.exe` nela e dê dois cliques. Já vem com tudo (Python, servidor, telas do PC e do coletor). O navegador abre sozinho em http://localhost:8000 e a janela mostra o **endereço para o coletor**. O banco fica em **AppData\Local\MiniWMS\estoque.db** do usuário (pasta que a Proteção contra ransomware do Windows não bloqueia); o caminho aparece na janela. Para fazer backup, copie esse arquivo. Para desligar, feche a janela. |
| `ColetorWMS.apk` | Coletor Zebra | Copie para o coletor e instale. Talvez seja preciso permitir *instalar apps de fontes desconhecidas*. Na primeira vez, o app **procura o servidor na rede Wi-Fi sozinho**; se não achar, digite o endereço que aparece no topo da tela do PC ("📱 Coletor"). O menu **Config** tem "Procurar servidor na rede". O app configura o DataWedge sozinho. |
| `AppCenter.apk` | Coletor Zebra (opcional) | Tela inicial em modo quiosque. A ativação precisa do ADB uma vez (seção 2b). |

- Porta: o servidor usa a 8000. Se ela estiver ocupada, a janela avisa. Para usar outra, abra um Prompt na pasta e rode
  `set WMS_PORTA=8080` e depois `WMS-Servidor.exe` (no coletor, use o endereço com a porta nova).
- Para gerar o `.exe` no seu PC: `cd server`, `pip install -r requirements.txt pyinstaller` e
  `pyinstaller --onefile --name WMS-Servidor --icon icone.ico --add-data "app/static;app/static" --collect-submodules uvicorn wms_servidor.py`
  (o arquivo sai em `server\dist`).
- Na primeira execução, o Windows pode mostrar "O Windows protegeu o computador": clique em *Mais informações* e depois em *Executar assim mesmo*.
- Quando aparecer o aviso do Firewall, clique em **Permitir acesso**. Isso é necessário para o coletor alcançar o PC.
- O PC e o coletor precisam estar na mesma rede Wi-Fi.

## Funções

| Onde | O quê |
|---|---|
| PC | **Dashboard** (primeira tela): um card por local de estoque com a quantidade; clicar no card mostra os itens e quantidades. Botão **Relatório PDF** |
| PC | **Estoque**: cada item em cada local. Marque os itens, clique em **Mover** e escolha o local de destino (sempre pede confirmação). **Relatório PDF** com os itens de cada local |
| PC | **Locais**: cadastro dos locais de estoque (armazéns), com nome e descrição. O **Local-01** vem pronto e é o padrão |
| PC | **Produtos**: cadastro (SKU, descrição, EAN, unidade, mínimo) |
| PC | **Ordens de recebimento**: produto e quantidade esperada; acompanha as leituras do coletor ao vivo e finaliza |
| PC | **Baixa** (com o EPC ou por quantidade, escolhendo o local), **Inventário** e **Histórico** (com **Relatório PDF** dos movimentos filtrados) |
| Coletor | **Recebimento**: escolhe a ordem e o item, lê as etiquetas (cada uma vai na hora para o servidor) |
| Coletor | **Entrada** sem ordem: produto da lista, etiquetas RFID ou quantidade |
| Coletor | **Baixa**: escolhe o **motivo** (consumo...) e o **local de onde sai**; as etiquetas lidas entram em **Para baixar** (só as que estão em estoque naquele local; dá para tirar alguma) e a baixa só é feita ao tocar em **Confirmar baixa**; "desfazer" devolve ao estoque; produto sem etiqueta: código de barras + quantidade |
| Coletor | **Inventário**: inicia no coletor, lê as etiquetas; ao finalizar, etiqueta não lida sai e etiqueta achada volta |
| Coletor | **Consulta**: escolhe o local e toca em **Consultar**: aparecem os itens daquele local com a quantidade e as etiquetas RFID vinculadas (toque para ver os EPCs), como no PC |
| Coletor | **Localizar etiqueta**: escolhe o EPC e segura o gatilho; barra quente/frio e bipe mais rápido quanto mais perto |
| Coletor | **Gravar** (regravar etiqueta): bipe um código de barras (ou digite) e ele fica no campo; encoste o coletor na etiqueta e toque em **Gravar**: o código vira o novo EPC da etiqueta. Grava com o tamanho do código quando a etiqueta aceita (completando com 0 à esquerda até múltiplo de 4); senão, com 24 dígitos. Se a etiqueta estava cadastrada, o cadastro passa a usar o EPC novo |
| Coletor | **Config** (protegida pelo **PIN 1234**, mesmo popup do AppCenter): volume do bipe, **potência da antena separada** para Recebimento/Entrada, Baixa, Localizar e Gravar, e servidor (procurar na rede ou digitar) |

**Locais de estoque**: tudo que entra (ordem de recebimento ou entrada) vai para o **Local-01**. Quem não usa
outros locais trabalha só com ele. Para usar mais locais, cadastre em *Locais* e leve os itens pela tela
*Estoque* → marcar → **Mover** (só no PC; as etiquetas RFID vão junto e o movimento fica no histórico como
TRANSFERENCIA). No coletor fica só a baixa, escolhendo o local de onde os itens saem.

**Baixa por quantidade** (produto sem etiqueta): o servidor tira do local escolhido, primeiro das unidades
**sem etiqueta** e depois, se precisar, escolhe etiquetas e as marca como baixadas. Na baixa por RFID, a própria
etiqueta diz qual unidade sai.

**Ordem de recebimento (pré-recebimento)**: no PC, *Ordens de recebimento* → produtos e quantidade esperada. No
coletor, *Recebimento* → escolhe a ordem → toca no item (ou bipa o código de barras do produto) → aperta o gatilho
nas etiquetas. Cada etiqueta é gravada na hora e aparece no PC. O sistema recusa etiqueta já em estoque, já lida em
outra ordem e item que já completou a quantidade. *Finalizar* (no PC ou no coletor) dá entrada de tudo que foi lido
no Local-01 e mostra as divergências. As ordens fechadas ficam listadas em acordeão (clique para abrir).

**Inventário**: inicia no coletor e lê as etiquetas; cada leitura vai na hora para o servidor. O PC mostra
*Em estoque × Lidas × Diferença* e a acuracidade, e a lista de etiquetas: as que faltam em vermelho e as que
sobram (etiqueta desconhecida pode ser incluída no estoque). Ao **fechar**, etiqueta não lida sai do estoque e
etiqueta achada volta; cada ajuste fica registrado nos movimentos.

**Excluir produto** apaga também os lotes, as tags, os movimentos, as contagens e os itens de pedido dele.
Para só parar de usar, desmarque *Ativo*.

**Limpar tudo** (menu lateral, grupo *Sistema*): zera o banco para recomeçar uma aula. Opcionalmente mantém
o cadastro de produtos e locais e apaga só a movimentação.


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
| `server/app/estoque.py` | **Regras**: entrada, baixa (por etiqueta e por quantidade), locais e mover itens, inventário, ordens de recebimento |
| `server/app/main.py` | Rotas da API (`/api/...`) usadas pelo PC e pelo coletor |
| `server/app/relatorios.py` | Relatórios em PDF (estoque por local e histórico) |
| `server/app/static/index.html` | Tela web (HTML + JavaScript puro) |
| `server/app/static/m.html` | Telas do coletor (abre em `/m`, dentro do app Coletor WMS) |
| `server/wms_servidor.py` | Inicia o servidor e abre o navegador (vira o `WMS-Servidor.exe`) |

---

## 2. App do coletor (recomendado)

O app **Coletor WMS** (`ColetorWMS.apk`) é uma "casca": ele mostra as telas do servidor (**/m**) e cuida do que
o navegador não faz sozinho:

- **RFID**: o app lê as etiquetas pelo SDK da Zebra (o mesmo do 123RFID) e entrega cada EPC para a tela.
- **Código de barras**: vem pelo **DataWedge**, que "digita" o código na tela.
- **Gatilho**: é um só para RFID e código de barras. Cada tela escolhe sozinha o que ele lê (ex.: no
  Recebimento começa em código para bipar o produto e passa para RFID depois).
- **Potência da antena**: em *Config*, uma para Recebimento/Entrada, uma para Baixa e uma para Localizar
  (padrão 100%). Inventário sempre a 100%.
- **Teclado ⌨** (no topo): liga/desliga o teclado. O MC3300 tem teclado físico, e por isso o Gboard esconde
  as teclas; o app usa um teclado próprio na tela (numérico nos campos de quantidade). Ligado, ele abre
  ao tocar em qualquer campo; desligado, não aparece.
- **LED verde**: pisca a cada etiqueta lida. No *Localizar etiqueta* pisca direto (estrobo), mais rápido quanto
  mais perto da etiqueta. Quem acende o LED é o serviço RFID do sistema (`RfidServiceMgr.ledBlink()`); a opção
  `setLedBlinkEnable` fica gravada nesse serviço e vale para todos os apps, por isso o app a religa ao conectar.
- **Rodapé**: servidor, data e hora do servidor no fim de todas as telas.
- **RFID com o cabo USB**: o leitor da Zebra não lê enquanto carrega ("Charging in Progress"). Use o
  coletor fora do cabo; para depurar sem cabo: `adb tcpip 5555` e `adb connect <ip-do-coletor>:5555`.
- Tela cheia do app; hora, Wi-Fi e bateria ficam na barra do próprio Android.
- Em segundo plano, o app solta o leitor RFID (assim o 123RFID e outros apps conseguem usar).

Telas: Recebimento, Entrada, Baixa, Inventário, Consulta, Localizar etiqueta, Gravar etiqueta e Config (com PIN 1234). Como as telas vêm do servidor,
qualquer melhoria chega ao coletor sem reinstalar o app.

### Como o RFID funciona no app

O leitor RFID do MC3300R fica **dentro do coletor** e é controlado pelo **Zebra RFID SDK API3** (arquivo
`API3_LIB-release.aar`, o mesmo SDK do app 123RFID). Todo o código está em `Rfid.kt`; a `MainActivity`
liga o RFID à tela.

**1. Ativação (conexão com o leitor)**

- Ao abrir o app, `Rfid.conectar()` procura o leitor como o app de exemplo da Zebra:
  `Readers(context, ENUM_TRANSPORT.SERVICE_USB)` e, se não achar, `ENUM_TRANSPORT.SERVICE_SERIAL`
  (no MC3300R é o **serial** que acha o leitor interno). `GetAvailableRFIDReaderList()` lista os leitores e
  `rfidReader.connect()` conecta ao primeiro.
- Depois de conectar, `configurar()` deixa o leitor pronto:
  - **eventos**: `addEventsListener`, `setHandheldEvent(true)` (gatilho) e `setTagReadEvent(true)` (tags lidas);
  - **gatilhos de leitura** `START/STOP_TRIGGER_TYPE_IMMEDIATE`: a leitura começa e para quando o app manda,
    não sozinha;
  - **antena**: potência máxima (`setTransmitPowerIndex` no último nível), modo de RF padrão;
  - **sessão S0** (`SESSION_S0`): toda etiqueta responde a cada rodada, bom para contar poucas dezenas de tags
    (na S1 a etiqueta lida fica alguns segundos "calada");
  - **LED**: `setLedBlinkEnable(true)`, o LED verde pisca a cada etiqueta lida.
- A tela recebe `statusRfid("RFID conectado: MC3300R... (serial)")`. Se nada funcionar, recebe o motivo.
- **Em segundo plano** (`onStop`) o app solta o leitor (`disconnect` + `Dispose`) e devolve o código de barras
  ao DataWedge: assim o 123RFID e outros apps conseguem usar o RFID. Ao voltar, conecta de novo.

**2. Gatilho: RFID ou código de barras**

O gatilho é **um só** para os dois leitores. Cada tela diz qual quer (`ColetorApp.gatilhoRfid(true/false)`):

- **RFID**: `Config.setTriggerMode(RFID_MODE)` e o app **desliga o scanner do DataWedge** por Intent
  (`com.symbol.datawedge.api.ACTION` → `SCANNER_INPUT_PLUGIN = DISABLE_PLUGIN`); senão o DataWedge "pega" o gatilho.
- **Código de barras**: `setTriggerMode(BARCODE_MODE)` e religa o DataWedge (`ENABLE_PLUGIN`), que "digita" o
  código na tela.

**3. Leitura**

- Apertar o gatilho gera `eventStatusNotify` com `HANDHELD_TRIGGER_PRESSED` → `Actions.Inventory.perform()`
  (começa a ler). Soltar (`HANDHELD_TRIGGER_RELEASED`) → `Actions.Inventory.stop()`.
- Cada grupo de etiquetas lidas gera `eventReadNotify` → `Actions.getReadTags(100)` → o **EPC** de cada tag
  (`tag.tagID`) vai para a tela com `leituraRfid(epc)` (função JavaScript chamada pelo `evaluateJavascript`).
- A **tela** (`m.html`) decide o que fazer com o EPC: ignora repetidos na mesma tela e junta as leituras em grupos
  de 250 ms. No Recebimento, cada leitura vai na hora para o servidor; na Baixa, a tela só confere cada etiqueta
  (`GET /api/tags/{epc}`) e mostra em *Para baixar*; a baixa (`POST /api/baixas`) só vai ao tocar em *Confirmar*. Leitura inválida é ignorada em silêncio;
  só a falta de conexão aparece como erro.
- **Potência** (`ColetorApp.potencia(%)`): `setTransmitPowerIndex` proporcional; menos potência lê só o que
  está perto. Em *Config* há uma para Recebimento/Entrada, uma para Baixa e uma para Localizar.

**4. Localizar etiqueta (quente/frio)**

Com um EPC escolhido (`ColetorApp.localizar(epc)`), o gatilho faz `Actions.TagLocationing.Perform(epc)` em vez
do inventário. O leitor devolve em `eventReadNotify` a **distância relativa** (`LocationInfo.relativeDistance`,
0 = longe, 100 = colado), que vai para a tela com `proximidadeRfid(n)`: barra quente/frio e bipe mais rápido.
O LED verde pisca em estrobo (`RfidServiceMgr.getInstance().ledBlink()`), mais rápido quanto mais perto.

**5. Gravar etiqueta (regravar o EPC)**

`ColetorApp.gravarEtiqueta(código, potência)` → `Rfid.gravar()`:

1. Lê por 0,7 s na **potência de gravação** (Config, padrão 30%) e escolhe a etiqueta: tem que haver uma só
   perto (ou uma bem mais forte, 10 dB acima das outras), para não gravar a etiqueta vizinha.
2. Grava pelo **Tag ID**: `Actions.TagAccess.writeTagIDWait(epcAtual, WriteSpecificFieldAccessParams, null)`, que
   escreve o EPC e ajusta o tamanho dele na etiqueta. O EPC é gravado em palavras de 16 bits (4 dígitos), por isso
   o código é completado com 0 à esquerda até múltiplo de 4. Se a etiqueta não aceitar mudar o tamanho, grava com
   24 dígitos (96 bits).
3. Último recurso: `writeWait` direto no banco de memória EPC (`MEMORY_BANK_EPC`, palavra 2 em diante).
4. O resultado volta para a tela com `resultadoGravacao(json)`; a tela avisa o servidor (`POST /api/tags/regravar`)
   para o cadastro da etiqueta passar a usar o EPC novo.

**6. Cuidados que evitam o leitor travar**

- **Fila única**: todo comando ao leitor vai para uma fila de uma thread só (`Executors.newSingleThreadExecutor`).
  Trocar o gatilho ou a potência no meio de uma leitura faz o SDK recusar e às vezes o leitor para de responder.
- Se `perform()` for recusado (leitor ainda ocupado), o app para, espera 150 ms e tenta de novo.
- Todo erro do SDK é tratado (`catch Throwable`): um problema no RFID nunca fecha o app.
- **Carregando no cabo USB o leitor não lê** (o SDK responde "Charging in Progress"): use o coletor fora do cabo.
- `setLedBlinkEnable` fica gravado no serviço RFID do sistema e vale para todos os apps: **nunca** mandar `false`,
  senão o LED para de acender em qualquer leitura (inclusive no 123RFID).

**Como a tela entende cada leitura:** EPC (hexadecimal com 16+ caracteres) = RFID; código igual a um endereço
cadastrado = endereço; o resto = produto (EAN ou SKU). Por isso vale imprimir etiquetas com o código dos endereços.

### DataWedge (código de barras): configurado pelo app

O **código de barras** é lido pelo **DataWedge** (app da Zebra que já vem no coletor), que "digita" o código na
tela. O RFID é do próprio app. **Não é preciso configurar nada à mão**: ao abrir, o app cria/atualiza sozinho o
perfil `WMS` do DataWedge pela API de Intent (`com.symbol.datawedge.api.SET_CONFIG`):

| No perfil `WMS` | Valor |
|---|---|
| App associado | `br.curso.wms` (Coletor WMS), todas as telas |
| Barcode input | ligado (scanner automático) |
| RFID input | desligado (se ficar ligado, o DataWedge disputa o leitor RFID com o app) |
| Keystroke output | ligado, com **Send data** e **Send ENTER key** |
| Intent output | desligado |

Durante o uso, o app ainda liga e desliga o scanner conforme a tela (`SCANNER_INPUT_PLUGIN`): em modo RFID ele
desliga o scanner, senão o DataWedge "pega" o gatilho; em modo código, religa. Ao ir para segundo plano, devolve
o scanner ligado para os outros apps.

### Testar sem o coletor

Abra **http://localhost:8000/m** no navegador e use o ⌨ do topo para digitar um código ou EPC.

## 2b. AppCenter: modo quiosque no coletor

O **AppCenter** (`AppCenter.apk`, código em `coletor/appcenter`) é a **tela inicial do coletor em modo quiosque**,
como o AppCenter dos coletores Zebra MC9090: fundo branco e só os ícones dos apps que o operador pode usar
(por padrão, o app de estoque). É um app separado do WMS: pode ser instalado ou atualizado sem mexer no outro.

### Por que ele é importante

- **O coletor vira uma ferramenta de trabalho, não um celular**: o operador só vê e só abre o que precisa.
  Nada de Configurações, Play Store, câmera, navegador ou jogos.
- **Menos erro e menos suporte**: sem acesso ao Android, ninguém muda Wi-Fi, idioma, data ou configurações do
  DataWedge/RFID por engano, nem desinstala o app de estoque.
- **Segurança e padronização**: todos os coletores da operação ficam iguais, e só o administrador (com PIN)
  mexe no aparelho.
- **Pronto para usar ao ligar**: o coletor liga direto no AppCenter, sem tela de desbloqueio, qualquer que tenha
  sido o último estado (mesmo que o administrador tenha liberado o Android antes de desligar).

### Recursos

| Recurso | Como funciona |
|---|---|
| **Só os apps liberados** | Tela branca com a grade de ícones dos apps permitidos. Tocar abre o app; o Voltar na primeira tela do app volta ao AppCenter. |
| **Travamento de verdade** | Modo *lock task* do Android: sem Home, sem Recentes, sem barra de notificações e sem a seta Voltar na tela do AppCenter. Um app fora da lista não abre nem por atalho. Hora, bateria e Wi-Fi continuam visíveis, e o menu de desligar funciona. |
| **Área do administrador** | **5 toques** na tela (em até 3 s) abrem o popup do **PIN 1234**, com teclado numérico na tela (o teclado físico também digita). Cancelar fecha o popup. |
| **Escolher os apps** | Na área do administrador, a lista de todos os apps instalados com caixinhas: marcar/desmarcar define o que aparece no AppCenter (e o que pode abrir). |
| **← Sair do admin** | Volta à tela inicial do AppCenter (deslogar). |
| **Sair do modo quiosque** | Libera o Android completo para o administrador (a Home leva ao launcher normal). O quiosque volta ao **reiniciar** o coletor ou ao tocar no ícone **AppCenter** no launcher do Android. |
| **Liga direto no AppCenter** | Ele é a tela inicial fixa do aparelho e desliga a tela de desbloqueio (o "deslizar"). |
| **Remover AppCenter do aparelho** | Desfaz o quiosque de vez (deixa de ser administrador do aparelho) para poder desinstalar. |

**Como é feito**: o AppCenter é o **Device Owner** do coletor (`DevicePolicyManager`). Com isso ele define a lista
de apps permitidos (`setLockTaskPackages`), liga o modo quiosque (`startLockTask`), fixa a tela inicial
(`addPersistentPreferredActivity`) e desliga a tela de desbloqueio (`setKeyguardDisabled`). "Sair do modo
quiosque" grava o número do boot atual (`Settings.Global.BOOT_COUNT`): quando o coletor reinicia, o número muda
e o quiosque volta sozinho, sem depender do aviso de boot do Android (que no MC3300 chega uns 40 s depois).

### Instalar (uma vez, com o cabo e o ADB)

O quiosque de verdade usa o modo *lock task* do Android, que exige que o AppCenter seja o **Device Owner**
(administrador do aparelho). O Android só aceita isso **sem nenhuma conta** no aparelho: remova as contas
(Configurações → Contas) antes; depois de ativado, dá para adicionar de novo.

```
adb install -r AppCenter.apk
adb shell dpm set-device-owner br.curso.appcenter/.AdminReceiver
adb shell am start -n br.curso.appcenter/.AbrirAppCenter
```

O AppCenter desliga a tela de desbloqueio (o "deslizar"); isso só funciona se o coletor não tiver senha/PIN de tela.
Um app que é Device Owner não pode ser desinstalado: use antes **Remover AppCenter do aparelho** na área do admin.

## 3. Compilar os apps do coletor

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
adb install -r appcenter\build\outputs\apk\debug\appcenter-debug.apk
```

O `gradlew assembleDebug` compila os dois apps (Coletor WMS e AppCenter).

### Arquivos

| Arquivo | O que tem |
|---|---|
| `coletor/app/.../MainActivity.kt` | WebView com a tela /m, ponte JavaScript (`ColetorApp`), DataWedge, volume, teclado |
| `coletor/app/.../Rfid.kt` | Leitor RFID Zebra (API3): conectar, gatilho, potência, leitura, localizar, LED |
| `coletor/app/.../Descoberta.kt` | Procura o servidor na rede Wi-Fi |
| `coletor/app/.../Servidor.kt` | Endereço do servidor (guardado no aparelho) |
| `coletor/appcenter/.../MainActivity.kt` | AppCenter: grade de apps, 5 toques + PIN, área do administrador |
| `coletor/appcenter/.../Quiosque.kt` | Device Owner, lock task, tela inicial fixa, sair do quiosque até reiniciar |

### Ponte entre o app e a tela

| Quem chama | O quê | Para quê |
|---|---|---|
| App → tela | `leituraRfid(epc)` | cada etiqueta lida pelo RFID |
| App → tela | `statusRfid(mensagem)` | leitor RFID conectou (ou não) |
| App → tela | `gatilhoRfidEvento(1/0)` | gatilho apertado / solto |
| App → tela | `fimLeituraRfid(n)` | fim da leitura: quantas etiquetas o leitor viu |
| App → tela | `proximidadeRfid(0..100)` | Localizar: distância da etiqueta procurada |
| Tela → app | `ColetorApp.gatilhoRfid(true/false)` | gatilho lê RFID ou código de barras (`setTriggerMode`) |
| Tela → app | `ColetorApp.potencia(%)` | potência da antena |
| Tela → app | `ColetorApp.localizar(epc)` / `procurar(true/false)` | Localizar: escolhe a etiqueta / procura sem o gatilho |
| Tela → app | `ColetorApp.gravarEtiqueta(código, potência)` | Gravar: regrava o EPC da etiqueta perto da antena |
| App → tela | `resultadoGravacao(json)` | Gravar: gravou ou não, EPC antigo e novo |
| Tela → app | `ColetorApp.servidor()` | abre o popup do endereço do servidor |

---

## Simplificações (de propósito, por ser didático)

- Sem login nem senha, e sem HTTPS: é para uso em rede local.
- Sem lote e sem validade nas telas: cada item fica em um local, e **Mover** leva toda a quantidade do item
  naquele local para o outro.
- Se a rede cair, o coletor mostra o erro e o operador envia de novo. Não existe fila offline.
