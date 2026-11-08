import importlib
import os
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

class ApiTests(unittest.TestCase):
    def test_complete_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['DATABASE_PATH'] = str(Path(tmp) / 'test.db')
            os.environ['VULNTRACK_API_KEY'] = 'test-key-' + 'x' * 40
            import main
            importlib.reload(main)
            with TestClient(main.app) as client:
                self.assertEqual(client.get('/health').status_code, 200)
                self.assertEqual(client.get('/ativos').status_code, 401)
                client.headers['X-API-Key'] = os.environ['VULNTRACK_API_KEY']
                asset = {'nome':'Servidor Web','ip':'10.0.0.10','tipo':'servidor','responsavel':'SOC'}
                self.assertEqual(client.post('/ativos', json={**asset, 'ip':'invalid'}).status_code, 422)
                r = client.post('/ativos', json=asset)
                self.assertEqual(r.status_code, 201)
                aid = r.json()['id']
                vuln = {'ativo_id':aid,'titulo':'Versão exposta','descricao':'Exemplo didático',
                        'severidade':'baixa','status':'aberta','cve':None}
                self.assertEqual(client.post('/vulnerabilidades',json={**vuln,'ativo_id':999}).status_code,404)
                r = client.post('/vulnerabilidades',json=vuln)
                self.assertEqual(r.status_code,201)
                vid = r.json()['id']
                self.assertEqual(client.delete(f'/ativos/{aid}').status_code,409)
                self.assertEqual(len(client.get('/vulnerabilidades?severidade=baixa').json()),1)
                self.assertEqual(client.get('/resumo').json()['abertas_por_severidade']['baixa'],1)
                self.assertEqual(client.put(f'/ativos/{aid}', json={**asset,'nome':'Servidor Atualizado'}).status_code,200)
                self.assertEqual(client.put(f'/vulnerabilidades/{vid}',json={**vuln,'status':'corrigida'}).status_code,200)
                self.assertEqual(client.get('/resumo').json()['abertas_por_severidade']['baixa'],0)
                with main.db() as conn:
                    self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0],1)
            # Reabrir a aplicação deve manter os dados no arquivo.
            with TestClient(main.app) as client:
                client.headers['X-API-Key'] = os.environ['VULNTRACK_API_KEY']
                self.assertEqual(client.get(f'/vulnerabilidades/{vid}').json()['status'],'corrigida')
                self.assertEqual(client.delete(f'/vulnerabilidades/{vid}').status_code,204)
                self.assertEqual(client.get(f'/vulnerabilidades/{vid}').status_code,404)
                self.assertEqual(client.delete(f'/ativos/{aid}').status_code,204)

if __name__ == '__main__':
    unittest.main()
