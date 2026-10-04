# Sistema de Fluxo e Controle de Movimentação de Prontuários Físicos

Sistema web para controlar o fluxo de prontuários físicos dentro do hospital:

```
Unidade → SOP (Serviço de Organização de Prontuários) → Contas Médicas
        → Pronto para Faturamento → Auditoria → Finalizado
```

Um prontuário só avança para **Pronto para Faturamento** (e etapas seguintes)
se **não houver pendências abertas** vinculadas a ele — essa é a regra de
negócio central do sistema, garantida no backend (`app.py`).

## Stack

- **Backend:** Python + Flask
- **Banco:** PostgreSQL (já existente — as tabelas são criadas via `sql/schema.sql`)
- **Frontend:** HTML + CSS único (`static/css/style.css`) + JavaScript
- **Painel em tempo real:** React (via CDN, sem build step), com polling na API

## Estrutura de pastas

```
prontuarios_hm/
├── app.py                  # rotas de página + API JSON
├── db.py                   # pool de conexões PostgreSQL
├── config.py                # configurações via variáveis de ambiente
├── requirements.txt
├── .env.example
├── sql/
│   └── schema.sql          # criação das tabelas + dados iniciais
├── static/
│   ├── css/style.css       # CSS único, padroniza todas as páginas
│   ├── js/
│   │   ├── main.js         # sidebar, overlay de transição, utilitários
│   │   ├── sop.js
│   │   ├── contas_medicas.js
│   │   ├── pendencias.js
│   │   ├── unidade.js
│   │   ├── usuarios.js
│   │   └── painel.js       # componente React do painel em tempo real
│   └── img/
│       └── LEIA-ME_LOGOS.txt  # onde colocar os arquivos de logo
└── templates/
    ├── base.html            # layout com sidebar + cabeçalho
    ├── login.html
    ├── dashboard.html
    ├── sop.html
    ├── contas_medicas.html
    ├── unidade.html
    ├── usuarios.html
    ├── pendencias.html
    └── painel.html
```

## 1. Colocar as logos

Copie os dois arquivos de logo para `static/img/` com estes nomes exatos
(veja `static/img/LEIA-ME_LOGOS.txt`):

- `logo-hm-nova.png` — usada na animação de carregamento entre páginas
- `logo-hm-sesa-nova.png` — centralizada no login e no canto superior
  direito do cabeçalho nas demais páginas

Se o arquivo original tiver espaços/parênteses no nome, apenas renomeie
antes de copiar — não precisa editar HTML/CSS.

## 2. Banco de dados

O sistema usa um banco PostgreSQL **já existente**. Rode o script de schema
nele (ele só cria tabelas que ainda não existem e não apaga nada):

```bash
psql "postgresql://usuario:senha@host:5432/nome_do_banco" -f sql/schema.sql
```

Isso cria as tabelas `unidades`, `usuarios`, `tipos_pendencia`,
`prontuarios`, `movimentacoes` e `pendencias`, além de alguns dados
iniciais de exemplo (unidades e tipos de pendência).

## 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
# edite .env com a string de conexão real do seu Postgres
```

Variáveis principais:

| Variável | Descrição |
|---|---|
| `DATABASE_URL` | string de conexão do Postgres |
| `SECRET_KEY` | chave secreta do Flask (sessão de login) |
| `ADMIN_DEFAULT_LOGIN` / `ADMIN_DEFAULT_SENHA` | usuário admin criado automaticamente no primeiro start, se a tabela `usuarios` estiver vazia |
| `PAINEL_POLL_INTERVAL_MS` | intervalo (ms) de atualização do painel em tempo real |

## 4. Instalar dependências e rodar

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export $(cat .env | xargs)      # ou use python-dotenv
flask --app app run --debug
```

Acesse `http://localhost:5000`. No primeiro start, se não houver nenhum
usuário no banco, um usuário admin é criado automaticamente com o login/senha
definidos em `ADMIN_DEFAULT_LOGIN` / `ADMIN_DEFAULT_SENHA` — **troque essa
senha assim que possível pela própria tela de Usuários**.

Em produção, use `gunicorn`:

```bash
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

## Perfis de usuário

- `admin` — acesso total, incluindo cadastro de usuários e unidades
- `sop` / `contas_medicas` / `operador` — acesso operacional às páginas do fluxo

## Regras de negócio implementadas

- Todo prontuário nasce com status `unidade` ao ser cadastrado (feito na
  página SOP, informando a unidade de origem).
- Cada mudança de status gera um registro em `movimentacoes` (auditoria de
  quem moveu, quando e de onde para onde).
- Uma pendência é sempre vinculada a um prontuário e a um tipo de pendência
  (catálogo em `tipos_pendencia`, editável direto no banco).
- O backend **bloqueia** (HTTP 409) qualquer tentativa de mover um
  prontuário para `pronto_faturamento`, `auditoria` ou `finalizado` enquanto
  existir pendência com status diferente de `resolvida`.
- O Painel em Tempo Real consulta `/api/painel` a cada
  `PAINEL_POLL_INTERVAL_MS` milissegundos e mostra todos os prontuários que
  ainda não foram finalizados, organizados por etapa do fluxo.

## Personalização visual

Todas as cores estão centralizadas como variáveis CSS no topo de
`static/css/style.css` (`:root { --cor-teal: #00A1A2; ... }`), seguindo a
paleta fornecida. Para ajustar tons, edite apenas esse bloco — todas as
páginas herdam automaticamente.
