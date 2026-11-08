"""VulnTrack: projeto acadêmico de gestão de vulnerabilidades."""
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress

DB_PATH = Path(os.getenv('DATABASE_PATH', 'data/vulntrack.db'))
API_KEY = os.getenv('VULNTRACK_API_KEY', '')

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS ativos (
            id INTEGER PRIMARY KEY, nome TEXT NOT NULL, ip TEXT NOT NULL,
            tipo TEXT NOT NULL, responsavel TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vulnerabilidades (
            id INTEGER PRIMARY KEY, ativo_id INTEGER NOT NULL,
            titulo TEXT NOT NULL, descricao TEXT NOT NULL, cve TEXT,
            severidade TEXT NOT NULL CHECK(severidade IN ('baixa','media','alta','critica')),
            status TEXT NOT NULL CHECK(status IN ('aberta','em_tratamento','corrigida')),
            criada_em TEXT NOT NULL,
            FOREIGN KEY(ativo_id) REFERENCES ativos(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_vuln_ativo ON vulnerabilidades(ativo_id);
        ''')

@asynccontextmanager
async def lifespan(app):
    if len(API_KEY) < 32:
        raise RuntimeError('Defina VULNTRACK_API_KEY com pelo menos 32 caracteres.')
    initialize()
    yield

app = FastAPI(title='VulnTrack', version='1.0.0', lifespan=lifespan,
              description='API acadêmica para registrar ativos e acompanhar vulnerabilidades. Não executa varreduras.')
header_key = APIKeyHeader(name='X-API-Key', auto_error=False)

def authorize(key: str | None = Depends(header_key)):
    if not key or not secrets.compare_digest(key.encode(), API_KEY.encode()):
        raise HTTPException(401, 'Chave de acesso ausente ou inválida')

class Severidade(str, Enum):
    baixa = 'baixa'
    media = 'media'
    alta = 'alta'
    critica = 'critica'

class Status(str, Enum):
    aberta = 'aberta'
    em_tratamento = 'em_tratamento'
    corrigida = 'corrigida'

class Entrada(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class AtivoIn(Entrada):
    nome: str = Field(min_length=1, max_length=100)
    ip: IPvAnyAddress
    tipo: str = Field(min_length=1, max_length=50)
    responsavel: str = Field(min_length=1, max_length=100)

class AtivoOut(AtivoIn):
    id: int

class VulnIn(Entrada):
    ativo_id: int = Field(gt=0)
    titulo: str = Field(min_length=1, max_length=150)
    descricao: str = Field(min_length=1, max_length=3000)
    cve: str | None = Field(default=None, pattern=r'^CVE-\d{4}-\d{4,}$')
    severidade: Severidade
    status: Status = Status.aberta

class VulnOut(VulnIn):
    id: int
    criada_em: str

class ResumoOut(BaseModel):
    total_ativos: int
    total_vulnerabilidades: int
    abertas_por_severidade: dict[str, int]
    por_status: dict[str, int]

# Nomes de tabelas vêm apenas das chamadas internas; valores usam parâmetros SQL.
def obtain(conn, table, id):
    row = conn.execute(f'SELECT * FROM {table} WHERE id=?', (id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Registro não encontrado')
    return dict(row)

secured = [Depends(authorize)]

@app.get('/health', tags=['Saúde'])
def health():
    with db() as conn:
        conn.execute('SELECT COUNT(*) FROM ativos').fetchone()
    return {'status': 'ok'}

@app.post('/ativos', status_code=201, response_model=AtivoOut, dependencies=secured, tags=['Ativos'])
def create_asset(item: AtivoIn):
    with db() as conn:
        cur = conn.execute('INSERT INTO ativos(nome,ip,tipo,responsavel) VALUES (?,?,?,?)',
                           (item.nome, str(item.ip), item.tipo, item.responsavel))
        return obtain(conn, 'ativos', cur.lastrowid)

@app.get('/ativos', response_model=list[AtivoOut], dependencies=secured, tags=['Ativos'])
def list_assets(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with db() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM ativos ORDER BY id LIMIT ? OFFSET ?', (limit, offset))]

@app.get('/ativos/{id}', response_model=AtivoOut, dependencies=secured, tags=['Ativos'])
def get_asset(id: int):
    with db() as conn:
        return obtain(conn, 'ativos', id)

@app.put('/ativos/{id}', response_model=AtivoOut, dependencies=secured, tags=['Ativos'])
def update_asset(id: int, item: AtivoIn):
    with db() as conn:
        obtain(conn, 'ativos', id)
        conn.execute('UPDATE ativos SET nome=?,ip=?,tipo=?,responsavel=? WHERE id=?',
                     (item.nome, str(item.ip), item.tipo, item.responsavel, id))
        return obtain(conn, 'ativos', id)

@app.delete('/ativos/{id}', status_code=204, dependencies=secured, tags=['Ativos'])
def delete_asset(id: int):
    with db() as conn:
        obtain(conn, 'ativos', id)
        if conn.execute('SELECT 1 FROM vulnerabilidades WHERE ativo_id=?', (id,)).fetchone():
            raise HTTPException(409, 'Ativo possui vulnerabilidades vinculadas')
        conn.execute('DELETE FROM ativos WHERE id=?', (id,))

@app.post('/vulnerabilidades', status_code=201, response_model=VulnOut, dependencies=secured, tags=['Vulnerabilidades'])
def create_vuln(item: VulnIn):
    with db() as conn:
        obtain(conn, 'ativos', item.ativo_id)
        cur = conn.execute('''INSERT INTO vulnerabilidades
            (ativo_id,titulo,descricao,cve,severidade,status,criada_em) VALUES (?,?,?,?,?,?,?)''',
            (item.ativo_id,item.titulo,item.descricao,item.cve,item.severidade.value,item.status.value,
             datetime.now(timezone.utc).isoformat()))
        return obtain(conn, 'vulnerabilidades', cur.lastrowid)

@app.get('/vulnerabilidades', response_model=list[VulnOut], dependencies=secured, tags=['Vulnerabilidades'])
def list_vulns(severidade: Severidade | None = None, status: Status | None = None,
               ativo_id: int | None = Query(None, gt=0),
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    clauses, values = [], []
    for column, value in [('severidade',severidade),('status',status),('ativo_id',ativo_id)]:
        if value is not None:
            clauses.append(column + '=?')
            values.append(value.value if isinstance(value, Enum) else value)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with db() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM vulnerabilidades' + where +
                                             ' ORDER BY id LIMIT ? OFFSET ?', values + [limit, offset])]

@app.get('/vulnerabilidades/{id}', response_model=VulnOut, dependencies=secured, tags=['Vulnerabilidades'])
def get_vuln(id: int):
    with db() as conn:
        return obtain(conn, 'vulnerabilidades', id)

@app.put('/vulnerabilidades/{id}', response_model=VulnOut, dependencies=secured, tags=['Vulnerabilidades'])
def update_vuln(id: int, item: VulnIn):
    with db() as conn:
        obtain(conn, 'vulnerabilidades', id)
        obtain(conn, 'ativos', item.ativo_id)
        conn.execute('''UPDATE vulnerabilidades SET ativo_id=?,titulo=?,descricao=?,cve=?,severidade=?,status=?
                     WHERE id=?''', (item.ativo_id,item.titulo,item.descricao,item.cve,
                                    item.severidade.value,item.status.value,id))
        return obtain(conn, 'vulnerabilidades', id)

@app.delete('/vulnerabilidades/{id}', status_code=204, dependencies=secured, tags=['Vulnerabilidades'])
def delete_vuln(id: int):
    with db() as conn:
        obtain(conn, 'vulnerabilidades', id)
        conn.execute('DELETE FROM vulnerabilidades WHERE id=?', (id,))

@app.get('/resumo', response_model=ResumoOut, dependencies=secured, tags=['Resumo'])
def summary():
    with db() as conn:
        opened = {s.value: 0 for s in Severidade}
        for row in conn.execute("SELECT severidade, COUNT(*) n FROM vulnerabilidades WHERE status != 'corrigida' GROUP BY severidade"):
            opened[row['severidade']] = row['n']
        by_status = {s.value: 0 for s in Status}
        for row in conn.execute('SELECT status, COUNT(*) n FROM vulnerabilidades GROUP BY status'):
            by_status[row['status']] = row['n']
        return {'total_ativos': conn.execute('SELECT COUNT(*) FROM ativos').fetchone()[0],
                'total_vulnerabilidades': conn.execute('SELECT COUNT(*) FROM vulnerabilidades').fetchone()[0],
                'abertas_por_severidade': opened, 'por_status': by_status}
