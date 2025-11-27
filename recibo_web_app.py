"""
recibo_web_app.py
Aplicativo web local para gerar recibos em PDF e gerenciar clientes predefinidos.
Rodará localmente no navegador usando Flask e salvará clientes em um banco SQLite.

Dependências (instale com pip):
    pip install flask reportlab num2words

Como executar:
    python recibo_web_app.py
Acesse no navegador: http://127.0.0.1:5000

Funcionalidades:
- CRUD de clientes (adicionar, editar, remover)
- Formulário para gerar recibo preenchendo: cliente (ou campos livres), valor, data, referente, observações
- Gera PDF do recibo e retorna para download

Ajustes aplicados:
- Melhor alinhamento do PDF para ficar mais próximo do exemplo enviado
- Correção do texto por extenso: usa 'real/reais' corretamente (antes aparecia 'Realais')
- Após adicionar um cliente novo, o formulário de geração de recibo é pré-populado automaticamente com esse cliente
"""

from flask import Flask, g, render_template_string, request, redirect, url_for, send_file, flash
import sqlite3
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from num2words import num2words
import os

DB_PATH = 'clientes.db'

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ---------- banco de dados simples (SQLite) ----------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cpf_cnpj TEXT,
            observacao TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS recibos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            nome TEXT,
            cpf_cnpj TEXT,
            valor TEXT,
            data_recibo TEXT,
            referente TEXT,
            observacoes TEXT,
            arquivo TEXT,
            criado_em TEXT
        )
    ''')
    db.commit()

# criar DB na inicialização
with app.app_context():
    init_db()

# ---------- utilitários ----------

def valor_por_extenso(value):
    """Retorna valor por extenso em pt_BR com 'reais' e 'centavos'."""
    try:
        v = float(value)
    except:
        return ''
    inteiro = int(v)
    centavos = int(round((v - inteiro) * 100))
    partes = []
    if inteiro > 0:
        ext = num2words(inteiro, lang='pt_BR')
        moeda = 'real' if inteiro == 1 else 'reais'
        partes.append(f"{ext} {moeda}")
    if centavos > 0:
        extc = num2words(centavos, lang='pt_BR')
        cent = 'centavo' if centavos == 1 else 'centavos'
        partes.append(f"{extc} {cent}")
    if not partes:
        return 'zero reais'
    return ' e '.join(partes)

# ---------- geração de PDF (em memória) ----------

def gerar_recibo_pdf_memoria(d):
    buffer = BytesIO()
    width, height = A4
    c = canvas.Canvas(buffer, pagesize=A4)
    margin = 12 * mm

    # borda externa mais sutil
    c.setLineWidth(2)
    c.rect(margin, margin, width - 2*margin, height - 2*margin)

    # cabeçalho: empresa e dados
    empresa = d.get('empresa_nome', 'ESTILU CONTABILIDADE LTDA')
    empresa_cnpj = d.get('empresa_cnpj', 'CNPJ: 26.631.734/0001-62')
    empresa_end = d.get('empresa_end', 'Rua Oratório, 1683 - Parque das Nações - Santo André - SP')

    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(width/2, height - margin - 8, empresa)
    c.setFont('Helvetica', 8)
    c.drawCentredString(width/2, height - margin - 22, f"{empresa_cnpj}   {empresa_end}")

    # caixa do valor numérico no canto superior direito (com fundo amarelo claro)
    box_w = 55*mm
    box_h = 14*mm
    box_x = width - margin - box_w - 6*mm
    box_y = height - margin - box_h - 14*mm
    c.setFillColorRGB(1, 1, 0.6)  # amarelo claro
    c.rect(box_x, box_y, box_w, box_h, stroke=0, fill=1)
    c.setLineWidth(1)
    c.setFillColor(colors.black)
    c.rect(box_x, box_y, box_w, box_h, stroke=1, fill=0)
    c.setFont('Helvetica-Bold', 11)
    valor_formatado = f"R$ {float(d['valor']):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    c.drawRightString(box_x + box_w - 8, box_y + box_h/2 - 4, valor_formatado)

    # RECEBEMOS DE e campo grande (com destaque)
    recebemos_y = box_y - 18
    c.setFont('Helvetica', 9)
    c.drawString(margin + 10, recebemos_y + 12, 'RECEBEMOS DE:')
    nome_box_w = width - 2*margin - box_w - 24*mm
    nome_box_x = margin + 10
    nome_box_h = 26
    nome_box_y = recebemos_y - 8 - nome_box_h
    c.setFillColorRGB(1, 1, 0.9)
    c.rect(nome_box_x, nome_box_y, nome_box_w, nome_box_h, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setLineWidth(1)
    c.rect(nome_box_x, nome_box_y, nome_box_w, nome_box_h, stroke=1, fill=0)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(nome_box_x + 6, nome_box_y + 6, d['nome'])

    # valor por extenso em caixa grande
    extenso_y_top = nome_box_y - 10
    c.setFont('Helvetica', 9)
    c.drawString(margin + 10, extenso_y_top, 'LÍQUIDA DE:')
    ext_box_x = margin + 10
    ext_box_w = width - 2*margin - 20
    ext_box_h = 36
    ext_box_y = extenso_y_top - 8 - ext_box_h
    c.setFillColorRGB(1, 1, 0.9)
    c.rect(ext_box_x, ext_box_y, ext_box_w, ext_box_h, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.rect(ext_box_x, ext_box_y, ext_box_w, ext_box_h, stroke=1, fill=0)

    # quebrar o texto extenso em 2 linhas conforme exemplo
    extenso = d.get('valor_extenso', '')
    # espaço para indicar valor por extenso seguido de ' . ' conforme imagem
    if extenso and not extenso.endswith('.'):
        extenso = extenso + '.'
    # split approx
    max_chars_line = 90
    lines = []
    while extenso:
        if len(extenso) <= max_chars_line:
            lines.append(extenso)
            break
        part = extenso[:max_chars_line]
        last_space = part.rfind(' ')
        if last_space == -1:
            lines.append(part)
            extenso = extenso[max_chars_line:]
        else:
            lines.append(extenso[:last_space])
            extenso = extenso[last_space+1:]
    text_y = ext_box_y + ext_box_h - 12
    c.setFont('Helvetica', 9)
    for ln in lines[:2]:
        c.drawString(ext_box_x + 6, text_y, ln)
        text_y -= 12

    # REFERENTE
    ref_y = ext_box_y - 8
    c.setFont('Helvetica', 9)
    c.drawString(margin + 10, ref_y, 'REFERENTE:')
    c.setFont('Helvetica-Bold', 9)
    c.drawString(margin + 80, ref_y, d.get('referente', ''))

    # bloco discriminação (lado esquerdo)
    discr_x = margin + 10
    discr_y = ref_y - 26
    discr_w = 90*mm
    discr_h = 60*mm
    c.rect(discr_x, discr_y - discr_h, discr_w, discr_h, stroke=1, fill=0)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(discr_x + 8, discr_y - 12, 'DISCRIMINAÇÃO DOS VALORES')
    c.setFont('Helvetica', 9)
    c.drawString(discr_x + 10, discr_y - 30, 'MENSALIDADE')
    c.drawRightString(discr_x + discr_w - 10, discr_y - 30, valor_formatado)
    c.drawString(discr_x + 10, discr_y - 46, 'ALT. CONTRATO')
    c.drawRightString(discr_x + discr_w - 10, discr_y - 46, 'R$ -')
    c.drawString(discr_x + 10, discr_y - 62, 'REGULARIZAÇÃO')
    c.drawRightString(discr_x + discr_w - 10, discr_y - 62, 'R$ -')
    c.setFont('Helvetica-Bold', 9)
    c.drawString(discr_x + 10, discr_y - 86, 'VALOR TOTAL')
    c.drawRightString(discr_x + discr_w - 10, discr_y - 86, valor_formatado)

    # bloco assinatura (lado direito)
    assin_x = discr_x + discr_w + 12
    assin_y = discr_y - 10
    assin_w = width - margin - assin_x - 8
    assin_h = discr_h - 8
    c.rect(assin_x, assin_y - assin_h, assin_w, assin_h, stroke=1, fill=0)
    c.setFont('Helvetica', 9)
    c.drawString(assin_x + 8, assin_y - 16, 'NOME:')
    c.line(assin_x + 8, assin_y - 36, assin_x + assin_w - 8, assin_y - 36)
    c.drawString(assin_x + 8, assin_y - 58, 'CNPJ/CPF:')
    c.line(assin_x + 8, assin_y - 78, assin_x + assin_w - 8, assin_y - 78)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(assin_x + 10, assin_y - 28, d['nome'])
    c.drawString(assin_x + 10, assin_y - 70, d.get('cpf_cnpj', ''))

    # rodapé - local e data
    rodape_y = margin + 28
    c.setFont('Helvetica', 9)
    c.drawString(margin + 10, rodape_y + 6, f"Santo André, {d.get('data_recibo', '')}")
    c.setFont('Helvetica', 8)
    c.drawString(margin + 10, rodape_y - 8, f"Observações: {d.get('observacoes', '')}")

    # assinatura empresa no canto inferior direito
    c.setFont('Helvetica-Bold', 9)
    c.drawRightString(width - margin - 8, margin + 12, empresa)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# ---------- rotas web (HTML inline) ----------

INDEX_HTML = """
<!doctype html>
<html lang="pt-br">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Gerador de Recibos</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body{padding:20px}
      .card{margin-bottom:20px}
      textarea[readonly]{background:#f8f9fa}
    </style>
  </head>
  <body>
    <div class="container">
      <h2>Gerador de Recibos (local)</h2>

      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="alert alert-info">{{ messages[0] }}</div>
        {% endif %}
      {% endwith %}

      <div class="row">
        <div class="col-md-5">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Clientes cadastrados</h5>
              <form method="post" action="/select_client">
                <div class="mb-3">
                  <select class="form-select" name="client_id">
                    <option value="">-- Selecionar cliente (ou preencher manualmente) --</option>
                    {% for c in clientes %}
                      <option value="{{c['id']}}">{{c['nome']}} - {{c['cpf_cnpj']}}</option>
                    {% endfor %}
                  </select>
                </div>
                <div class="d-grid gap-2 d-md-flex justify-content-md-start">
                  <button class="btn btn-primary btn-sm" type="submit">Carregar cliente</button>
                  <a href="#clientes" class="btn btn-outline-secondary btn-sm" onclick="document.getElementById('form-add').scrollIntoView();">Adicionar novo</a>
                </div>
              </form>

              <hr>
              <h6>Gerenciar clientes</h6>
              <ul class="list-group">
                {% for c in clientes %}
                  <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                      <strong>{{c['nome']}}</strong><br><small>{{c['cpf_cnpj']}}</small>
                    </div>
                    <div>
                      <a href="/edit_client/{{c['id']}}" class="btn btn-sm btn-outline-primary">Editar</a>
                      <a href="/delete_client/{{c['id']}}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Remover cliente?');">Remover</a>
                    </div>
                  </li>
                {% endfor %}
              </ul>
            </div>
          </div>

          <div class="card" id="form-add">
            <div class="card-body">
              <h5 class="card-title">Adicionar cliente</h5>
              <form method="post" action="/add_client">
                <div class="mb-2">
                  <input class="form-control" name="nome" placeholder="Nome / Razão Social" required>
                </div>
                <div class="mb-2">
                  <input class="form-control" name="cpf_cnpj" placeholder="CPF / CNPJ">
                </div>
                <div class="mb-2">
                  <input class="form-control" name="observacao" placeholder="Observação (opcional)">
                </div>
                <button class="btn btn-success btn-sm">Adicionar</button>
              </form>
            </div>
          </div>

        </div>

        <div class="col-md-7">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Gerar Recibo</h5>
              <form method="post" action="/generate">
                <div class="row mb-2">
                  <div class="col-md-12">
                    <input class="form-control" name="nome" id="nome" placeholder="Nome / Razão Social" required value="{{ prepop.nome if prepop else '' }}">
                  </div>
                </div>
                <div class="row mb-2">
                  <div class="col-md-6">
                    <input class="form-control" name="cpf_cnpj" id="cpf_cnpj" placeholder="CPF / CNPJ" value="{{ prepop.cpf_cnpj if prepop else '' }}">
                  </div>
                  <div class="col-md-6">
                    <input class="form-control" name="valor" id="valor" placeholder="Valor (ex: 431.00)" required value="{{ prepop.valor if prepop else '' }}">
                  </div>
                </div>
                <div class="row mb-2">
                  <div class="col-md-6">
                    <input class="form-control" name="data_recibo" id="data_recibo" placeholder="Data (DD/MM/AAAA)" value="{{ prepop.data_recibo if prepop else hoje }}">
                  </div>
                  <div class="col-md-6">
                    <input class="form-control" name="referente" id="referente" placeholder="Referente" value="{{ prepop.referente if prepop else '' }}">
                  </div>
                </div>
                <div class="mb-2">
                  <input class="form-control" name="observacoes" id="observacoes" placeholder="Observações" value="{{ prepop.observacoes if prepop else '' }}">
                </div>

                <div class="d-flex gap-2">
                  <button class="btn btn-primary" type="submit">Gerar PDF</button>
                  <button class="btn btn-outline-secondary" type="button" onclick="document.getElementById('valor_ext').value='';">Limpar extenso</button>
                </div>

                <div class="mt-3">
                  <label class="form-label">Valor por extenso (gerado automaticamente)</label>
                  <textarea id="valor_ext" class="form-control" rows="2" readonly>{{ prepop.valor_extenso if prepop else '' }}</textarea>
                </div>
              </form>
            </div>
          </div>

          <div class="card">
            <div class="card-body">
              <h6>Ajuda rápida</h6>
              <ul>
                <li>Preencha os campos e clique em <strong>Gerar PDF</strong> para baixar o recibo.</li>
                <li>Use o painel à esquerda para inserir clientes frequentes e carregá-los no formulário.</li>
              </ul>
            </div>
          </div>

        </div>
      </div>

    </div>

    <script>
      function calcExt(){
        const v = document.getElementById('valor').value;
        if(!v) return;
        fetch('/extenso?valor='+encodeURIComponent(v))
          .then(r=>r.text()).then(t=>{document.getElementById('valor_ext').value=t});
      }
      // calcular extenso ao perder foco
      document.addEventListener('DOMContentLoaded', function(){
        const el = document.getElementById('valor');
        if(el){ el.addEventListener('blur', calcExt); }
      });
    </script>
  </body>
</html>
"""

@app.route('/')
def index():
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM clientes ORDER BY nome')
    clientes = cur.fetchall()
    hoje = datetime.now().strftime('%d/%m/%Y')
    return render_template_string(INDEX_HTML, clientes=clientes, prepop=None, hoje=hoje)

@app.route('/select_client', methods=['POST'])
def select_client():
    client_id = request.form.get('client_id')
    if not client_id:
        flash('Nenhum cliente selecionado.')
        return redirect(url_for('index'))
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM clientes WHERE id = ?', (client_id,))
    c = cur.fetchone()
    if not c:
        flash('Cliente não encontrado.')
        return redirect(url_for('index'))
    # prepopula o formulário com dados do cliente
    prepop = {
        'nome': c['nome'],
        'cpf_cnpj': c['cpf_cnpj'],
        'valor': '',
        'valor_extenso': '',
        'data_recibo': datetime.now().strftime('%d/%m/%Y'),
        'referente': '',
        'observacoes': c['observacao'] or ''
    }
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM clientes ORDER BY nome')
    clientes = cur.fetchall()
    hoje = datetime.now().strftime('%d/%m/%Y')
    return render_template_string(INDEX_HTML, clientes=clientes, prepop=prepop, hoje=hoje)

@app.route('/add_client', methods=['POST'])
def add_client():
    nome = request.form.get('nome')
    cpf = request.form.get('cpf_cnpj')
    obs = request.form.get('observacao')
    db = get_db()
    cur = db.cursor()
    cur.execute('INSERT INTO clientes (nome, cpf_cnpj, observacao) VALUES (?, ?, ?)', (nome, cpf, obs))
    db.commit()
    client_id = cur.lastrowid
    # buscar o cliente recém-criado e pré-popular o formulário
    cur.execute('SELECT * FROM clientes WHERE id = ?', (client_id,))
    c = cur.fetchone()
    prepop = {
        'nome': c['nome'],
        'cpf_cnpj': c['cpf_cnpj'],
        'valor': '',
        'valor_extenso': '',
        'data_recibo': datetime.now().strftime('%d/%m/%Y'),
        'referente': '',
        'observacoes': c['observacao'] or ''
    }
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM clientes ORDER BY nome')
    clientes = cur.fetchall()
    hoje = datetime.now().strftime('%d/%m/%Y')
    flash('Cliente adicionado e carregado no formulário.')
    return render_template_string(INDEX_HTML, clientes=clientes, prepop=prepop, hoje=hoje)

@app.route('/edit_client/<int:cid>', methods=['GET', 'POST'])
def edit_client(cid):
    db = get_db()
    cur = db.cursor()
    if request.method == 'GET':
        cur.execute('SELECT * FROM clientes WHERE id = ?', (cid,))
        c = cur.fetchone()
        if not c:
            flash('Cliente não encontrado.')
            return redirect(url_for('index'))
        # formulário simples de edição
        html = """
        <h3>Editar cliente</h3>
        <form method='post'>
          <div><label>Nome</label><input name='nome' value='{{c.nome}}'></div>
          <div><label>CPF/CNPJ</label><input name='cpf_cnpj' value='{{c.cpf_cnpj}}'></div>
          <div><label>Observação</label><input name='observacao' value='{{c.observacao}}'></div>
          <button>Salvar</button>
        </form>
        """
        return render_template_string(html, c=c)
    else:
        nome = request.form.get('nome')
        cpf = request.form.get('cpf_cnpj')
        obs = request.form.get('observacao')
        cur.execute('UPDATE clientes SET nome=?, cpf_cnpj=?, observacao=? WHERE id=?', (nome, cpf, obs, cid))
        db.commit()
        flash('Cliente atualizado.')
        return redirect(url_for('index'))

@app.route('/delete_client/<int:cid>')
def delete_client(cid):
    db = get_db()
    cur = db.cursor()
    cur.execute('DELETE FROM clientes WHERE id=?', (cid,))
    db.commit()
    flash('Cliente removido.')
    return redirect(url_for('index'))

@app.route('/extenso')
def extenso_api():
    v = request.args.get('valor', '')
    return valor_por_extenso(v)

@app.route('/generate', methods=['POST'])
def generate():
    nome = request.form.get('nome', '').strip()
    cpf = request.form.get('cpf_cnpj', '').strip()
    valor = request.form.get('valor', '').strip()
    data_recibo = request.form.get('data_recibo', '').strip() or datetime.now().strftime('%d/%m/%Y')
    referente = request.form.get('referente', '').strip()
    observacoes = request.form.get('observacoes', '').strip()

    if not nome or not valor:
        flash('Preencha pelo menos o Nome e o Valor.')
        return redirect(url_for('index'))
    try:
        float(valor)
    except:
        flash('Valor inválido. Use ponto como separador decimal (ex: 431.00)')
        return redirect(url_for('index'))

    valor_extenso = valor_por_extenso(valor)
    d = {
        'nome': nome,
        'cpf_cnpj': cpf,
        'valor': valor,
        'valor_extenso': valor_extenso,
        'data_recibo': data_recibo,
        'referente': referente,
        'observacoes': observacoes,
        'empresa_nome': 'ESTILU CONTABILIDADE LTDA',
        'empresa_cnpj': 'CNPJ: 26.631.734/0001-62',
        'empresa_end': 'Rua Oratório, 1683 - Parque das Nações - Santo André - SP'
    }

    # salvar metadados do recibo
    db = get_db()
    cur = db.cursor()
    cur.execute('INSERT INTO recibos (cliente_id,nome,cpf_cnpj,valor,data_recibo,referente,observacoes,arquivo,criado_em) VALUES (?,?,?,?,?,?,?,?,?)',
                (None, nome, cpf, valor, data_recibo, referente, observacoes, None, datetime.now().isoformat()))
    db.commit()

    pdf_io = gerar_recibo_pdf_memoria(d)
    filename = f"recibo_{nome[:20].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return send_file(pdf_io, as_attachment=True, download_name=filename, mimetype='application/pdf')

if __name__ == '__main__':
    host = '0.0.0.0'
    port = 5000
    print(f"INICIANDO APLICACAO - acesse http://127.0.0.1:{port} ou http://localhost:{port}")
    try:
        app.run(host=host, port=port, debug=True)
    except Exception as e:
        print('ERRO AO INICIAR SERVIDOR:', e)
