# Validação local do pacote

Data: 08/11/2026. Ambiente do autor do pacote, separado da futura VM Azure.

- Python: 3.12.14
- FastAPI: 0.141.1
- Uvicorn: 0.52.1
- Pydantic: 2.13.4
- HTTPX: 0.28.1
- SQLite: 3.53.1

Comando: `python -m unittest discover -s vulntrack -v`.
Resultado: OK. Um teste de integração cobre CRUD, autenticação, validação, integridade referencial, filtros, resumo e reabertura do banco. Compilação dos arquivos Python também concluída.

A biblioteca de testes emitiu aviso de depreciação sobre uso de HTTPX pelo TestClient; o teste passou. As dependências são declaradas por faixa e devem ser registradas com versões exatas na implantação final.

Não foram executados testes de implantação, rede pública, TLS ou reinício de VM Azure neste ambiente. Essas verificações constam do roteiro para execução na conta do aluno. O pacote não constitui evidência de implantação na nuvem.
