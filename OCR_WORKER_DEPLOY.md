# OCR Worker externo

Este worker deve rodar em um serviço/container SEPARADO do Streamlit.

## Arquivos
- `ocr_worker.py`
- `requirements_ocr.txt`

## Comando de execução
```bash
python ocr_worker.py
```

## Variáveis de ambiente obrigatórias
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Opcional:
- `OCR_POLL_SECONDS=5`

## Importante
Execute apenas **1 réplica** do worker nesta versão.

O `app.py` do Streamlit apenas cria/reabre atividades `ocr_gads`.
O worker externo consulta essas atividades, processa `midias` com OCR pendente,
grava `ocr_texto`/`ocr_estruturado` e atualiza o progresso da atividade.

O EasyOCR/PyTorch nunca é carregado no container do Streamlit.
