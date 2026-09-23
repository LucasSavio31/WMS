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

## Funções

| Função | PC (navegador) | Coletor |
|---|---|---|
| Cadastro de produtos (SKU, descrição, EAN, mínimo) | ✔ | — |
| Posição de estoque por produto e lote, com validade | ✔ | Consulta |
| Entrada | Quantidade digitada | RFID (cada tag = 1 unidade) ou código de barras + quantidade |
| Baixa | Quantidade (FEFO automático) ou EPC | RFID ou código de barras + quantidade (FEFO) |
| Inventário (contagem × sistema) | Abrir, contar item por item, ver diferenças e fechar | Contar por RFID ou por código de barras |
| Histórico de movimentos | ✔ | — |

**FEFO** (*First Expired, First Out*): na baixa por quantidade, o servidor tira primeiro do lote
que vence antes. Lotes vencidos ficam de fora, a não ser que o motivo da baixa seja `VENCIMENTO`.
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
| `server/app/db.py` | Tabelas do banco (produtos, lotes, tags, movimentos, inventários, contagens) |
| `server/app/estoque.py` | **Regras**: entrada, baixa FEFO, baixa por tag, inventário |
| `server/app/main.py` | Rotas da API (`/api/...`) usadas pelo PC e pelo coletor |
| `server/app/static/index.html` | Tela web (HTML + JavaScript puro) |

---

## 2. App do coletor (Android / Kotlin)

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
4. Baixe o **Zebra RFID SDK for Android** no site da Zebra e copie o `API3_LIB-release.aar` para `coletor/app/libs/`.
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
| `MainActivity.kt` | Menu, endereço do servidor e teste de conexão |
| `OperacaoActivity.kt` | Tela única de Entrada, Baixa, Inventário e Consulta |
| `Rfid.kt` | Leitor RFID Zebra (API3): conectar, gatilho, potência, tags lidas |
| `Servidor.kt` | Chamadas HTTP/JSON para o servidor |

### Código de barras

O app usa o **DataWedge** com o perfil padrão: o leitor "digita" o código no campo e aperta ENTER.
O gatilho do MC33 é compartilhado. Na tela, a opção **RFID / Código de barras** muda o que o gatilho faz
(`setTriggerMode`).

---

## Simplificações (de propósito, por ser didático)

- Sem login nem senha, e sem HTTPS: é para uso em rede local.
- Sem endereçamento (rua, prateleira): o estoque é controlado por produto e lote.
- Se a rede cair, o coletor mostra o erro e o operador envia de novo. Não existe fila offline.
- Tags RFID e código de barras no **mesmo lote**: a baixa por código de barras reduz o saldo, mas não
  sabe qual tag saiu, e essa tag continua ATIVA. O ideal é controlar cada produto por um meio só.
