# -*- coding: utf-8 -*-
"""
OCR worker — processo independente do Streamlit.

Worker isolado do núcleo OCR. Não importa Streamlit, Supabase,
Playwright nem a interface do app. O objetivo é carregar EasyOCR/PyTorch
em um processo pequeno e descartável, reduzindo o pico total de RAM.
"""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import sys
import json
import re
import time
import threading
import gc
import unicodedata
import traceback
from contextlib import contextmanager

import requests
import cv2

class _SecretsV126(dict):
    def get(self, key, default=None):
        # Worker independente: usa sempre defaults seguros definidos no app.
        return super().get(key, default)

class _StV126:
    secrets = _SecretsV126()

st = _StV126()


def _mem_snapshot_ocr(etapa: str):
    """Log detalhado de memória do worker, incluindo filhos quando possível."""
    import os as _os_mem
    import gc as _gc_mem
    rss_mb = -1.0
    vms_mb = -1.0
    filhos_rss_mb = 0.0
    try:
        import psutil as _ps_mem
        _p = _ps_mem.Process(_os_mem.getpid())
        _mi = _p.memory_info()
        rss_mb = _mi.rss / (1024 * 1024)
        vms_mb = _mi.vms / (1024 * 1024)
        try:
            for _c in _p.children(recursive=True):
                try:
                    filhos_rss_mb += _c.memory_info().rss / (1024 * 1024)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        try:
            rss_mb = _rss_processo_mb()
        except Exception:
            pass

    print(
        f"[OCR-MEM] etapa={etapa!r} pid={_os_mem.getpid()} "
        f"RSS={rss_mb:.1f} MB VMS={vms_mb:.1f} MB "
        f"filhos_RSS={filhos_rss_mb:.1f} MB "
        f"GC={_gc_mem.get_count()}",
        flush=True,
    )


def _limitar_threads_cpu_ocr_apos_import():
    try:
        import torch
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
    except Exception as e:
        print(f'[OCR-DEBUG] não consegui limitar threads do torch: {e!r}', flush=True)
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception as e:
        print(f'[OCR-DEBUG] não consegui limitar threads do cv2: {e!r}', flush=True)

_MAX_CPU_PESADA = int(st.secrets.get('MAX_CPU_PESADA_CONCORRENTE', 1))

_semaforo_cpu_pesada = threading.BoundedSemaphore(max(1, _MAX_CPU_PESADA))

@contextmanager
def _recurso_cpu_pesada(nome: str):
    """Serializa tarefas pesadas locais (OCR/ffmpeg/Whisper).

    O nome é só para debug. O semáforo é global ao processo, então um OCR
    não roda ao mesmo tempo que uma compressão de vídeo/thumbnail/Whisper.
    """
    _semaforo_cpu_pesada.acquire()
    try:
        yield
    finally:
        _semaforo_cpu_pesada.release()

_http_local = threading.local()

def _http_session() -> requests.Session:
    sess = getattr(_http_local, 'session', None)
    if sess is None:
        sess = requests.Session()
        try:
            from requests.adapters import HTTPAdapter
            adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
            sess.mount('https://', adapter)
            sess.mount('http://', adapter)
        except Exception:
            pass
        _http_local.session = sess
    return sess

def _http_get(*args, **kwargs):
    return _http_session().get(*args, **kwargs)

_lock_easyocr_init = threading.Lock()

_easyocr_instancia = [None]

_lock_easyocr_execucao = threading.Lock()

_MIN_INTERVALO_OCR_SEG = 15.0

_ultima_chamada_ocr = [0.0]

_easyocr_init_falhou_em = [0.0]

_EASYOCR_INIT_COOLDOWN_SEG = 300.0

def _rss_processo_mb() -> float:
    """RSS real do processo no Linux/Streamlit Cloud."""
    try:
        with open('/proc/self/status', 'r', encoding='utf-8') as _f:
            for _linha in _f:
                if _linha.startswith('VmRSS:'):
                    return float(_linha.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0

def _liberar_memoria_ocr(contexto: str='') -> float:
    """Limpa objetos Python e tenta devolver heap livre à libc."""
    try:
        gc.collect()
    except Exception:
        pass
    try:
        import ctypes as _ctypes_mem
        _ctypes_mem.CDLL('libc.so.6').malloc_trim(0)
    except Exception:
        pass
    _rss = _rss_processo_mb()
    if contexto:
        print(f'[MEM-DEBUG] {contexto}: RSS={_rss:.1f} MB', flush=True)
    return _rss

def _get_easyocr():
    """Inicializa o EasyOCR uma única vez, de forma serializada e protegida.

    A inicialização também entra no semáforo global de CPU pesada. Antes,
    somente a inferência estava protegida; duas filas podiam chegar juntas
    ao primeiro uso e uma delas ficava esperando enquanto o processo ainda
    carregava PyTorch/modelos. Agora o pico de inicialização não concorre com
    ffmpeg/Whisper e uma falha não dispara novas tentativas por 5 minutos.
    """
    if _easyocr_instancia[0] is not None:
        return _easyocr_instancia[0]
    agora = time.monotonic()
    if _easyocr_init_falhou_em[0] and agora - _easyocr_init_falhou_em[0] < _EASYOCR_INIT_COOLDOWN_SEG:
        raise RuntimeError('EasyOCR em cooldown após falha recente de inicialização')
    with _lock_easyocr_init:
        if _easyocr_instancia[0] is not None:
            return _easyocr_instancia[0]
        try:
            with _recurso_cpu_pesada('easyocr-init'):
                _rss_antes_easyocr = _liberar_memoria_ocr('antes EasyOCR init')
                _LIMITE_RSS_ANTES_IMPORT_MB = int(st.secrets.get('OCR_MAX_RSS_ANTES_IMPORT_EASYOCR_MB', 650))
                if _rss_antes_easyocr > _LIMITE_RSS_ANTES_IMPORT_MB:
                    raise RuntimeError(f'Memória base alta demais para iniciar EasyOCR com segurança (RSS={_rss_antes_easyocr:.0f} MB antes do import; limite={_LIMITE_RSS_ANTES_IMPORT_MB} MB)')
                print('[OCR-DEBUG] inicializando EasyOCR (única instância global)...', flush=True)
                _mem_snapshot_ocr('antes import easyocr')
                import easyocr
                _mem_snapshot_ocr('depois import easyocr/torch')
                _limitar_threads_cpu_ocr_apos_import()
                _liberar_memoria_ocr('apos import EasyOCR/torch, antes Reader')
                _mem_snapshot_ocr('antes EasyOCR.Reader')
                _easyocr_instancia[0] = easyocr.Reader(['pt'], gpu=False, verbose=False)
                _mem_snapshot_ocr('depois EasyOCR.Reader')
                _liberar_memoria_ocr('depois EasyOCR init')
                print('[OCR-DEBUG] EasyOCR inicializado com sucesso', flush=True)
        except BaseException:
            _easyocr_init_falhou_em[0] = time.monotonic()
            gc.collect()
            raise
    return _easyocr_instancia[0]

def _baixar_imagem_cv2(url_imagem: str):
    """Baixa a imagem (já no nosso R2) e devolve o array BGR decodificado
    (formato que o OpenCV/EasyOCR esperam), ou None se o download ou a
    decodificação falharem."""
    _mem_snapshot_ocr('antes baixar imagem')
    import numpy as _np_ocr
    import cv2 as _cv2_ocr
    r = _http_get(url_imagem, timeout=20)
    r.raise_for_status()
    _arr = _np_ocr.frombuffer(r.content, dtype=_np_ocr.uint8)
    _img = _cv2_ocr.imdecode(_arr, _cv2_ocr.IMREAD_COLOR)
    if _img is None:
        return None
    _h, _w = _img.shape[:2]
    _maior = max(_h, _w)
    if _maior > 2200:
        _escala = 2200.0 / float(_maior)
        _img = _cv2_ocr.resize(_img, (max(1, int(_w * _escala)), max(1, int(_h * _escala))), interpolation=_cv2_ocr.INTER_AREA)
    return _img

def _ocr_texto_bruto(img_bgr, reader) -> str:
    """Lê TODO o texto da imagem sem nenhuma tentativa de estruturar —
    usado como fallback quando `_estruturar_anuncio_google_ads` não
    reconhece o padrão de cores esperado (ex: anúncio de imagem/Display,
    em vez de anúncio de texto).

    width_ths baixo (padrão do EasyOCR é 0.5) evita que o CRAFT funda
    palavras próximas numa ÚNICA caixa de detecção — quando isso
    acontece, o reconhecedor devolve as palavras GRUDADAS, sem espaço
    entre elas (ex: título de anúncio virando "ReduzirInadimplência
    Escolar"), porque o modelo de reconhecimento não emite espaço de
    forma confiável em recortes largos com várias palavras. Com caixas
    menores (uma por palavra), a reconstrução manual de espaço vira
    desnecessária pro fallback, mas o texto pelo menos não sai
    concatenado.

    Ordena por posição (linha de cima pra baixo, esquerda pra direita
    dentro de cada linha) antes de juntar — sem isso, a ordem das
    palavras é a ordem em que o CRAFT detectou cada região, que não
    tem nenhuma relação com a ordem de leitura (validado num anúncio
    real: o texto saiu com pedaços do título, da descrição e de um
    sitelink todos embaralhados entre si)."""
    resultado = reader.readtext(img_bgr, detail=1, width_ths=0.15, height_ths=0.5)
    if not resultado:
        return ''
    _itens = [(bbox, (t or '').strip()) for bbox, t, _conf in resultado if (t or '').strip()]
    if not _itens:
        return ''

    def _y_centro(bbox):
        return sum((p[1] for p in bbox)) / len(bbox)
    _itens.sort(key=lambda item: _y_centro(item[0]))
    _linhas_agrupadas = []
    _linha_atual = [_itens[0]]
    _y_ref = _y_centro(_itens[0][0])
    _altura_media = max(1.0, sum((max((p[1] for p in it[0])) - min((p[1] for p in it[0])) for it in _itens)) / len(_itens))
    for item in _itens[1:]:
        _y_item = _y_centro(item[0])
        if abs(_y_item - _y_ref) > _altura_media * 0.6:
            _linhas_agrupadas.append(_linha_atual)
            _linha_atual = [item]
        else:
            _linha_atual.append(item)
        _y_ref = _y_item
    _linhas_agrupadas.append(_linha_atual)
    linhas = []
    for _grupo in _linhas_agrupadas:
        _grupo.sort(key=lambda item: item[0][0][0])
        linhas.append(' '.join((t for _bbox, t in _grupo)))
    return '\n'.join(linhas)

_REGEX_PATROCINADO = re.compile('^(patrocinad[oa]|sponsored|gesponsord|gesponsert|sponsoris[ée])$', re.IGNORECASE)

_REGEX_PATROCINADO_PREFIXO = re.compile('^(patrocinad[oa]|sponsored|gesponsord|gesponsert|sponsoris[ée])', re.IGNORECASE)

_REGEX_CTA_TITULO_CONHECIDO = re.compile('^(enviar\\s*mensagem|ligar\\s*agora|comprar\\s*agora|compre\\s*agora|saiba\\s*mais|cadastre-?se|fazer\\s*pedido|agendar(\\s*agora)?|reservar(\\s*agora)?|inscreva-?se|baixar\\s*agora|instalar(\\s*agora)?|pe(ç|c)a\\s*já|entre\\s*em\\s*contato(\\s+no\\s*app\\s*whatsapp)?|fale\\s*conosco|fale\\s*com\\s*a\\s*gente)$', re.IGNORECASE)

def _normalizar_url_exibida(texto: str) -> str:
    """Corrige erros de leitura de caractere (não de espaçamento) que o
    EasyOCR comete com frequência no campo de URL, validados nos testes
    reais com os anúncios da kedu:
    1) 'www' vem com maiúsculas erradas ('WWw.', 'WW.', 'Www.') — o
       modelo confunde a barra vertical do 'w' minúsculo repetido com
       maiúscula. Como um domínio real nunca tem maiúscula aí, é seguro
       normalizar sempre pra 'www.' minúsculo.
    2) a barra de fechamento do domínio ('.com.br/') é lida como um 'l'
       colado direto, sem espaço ('.com.brl', faltando o ponto antes do
       'br') — o traço vertical da barra é visualmente parecido com o
       'l'. Roda em QUALQUER posição da string (não só no final),
       porque depois dessa barra a URL pode continuar com mais
       segmentos de caminho (ex: '.combrlgestão/escolar'). Restrito ao
       padrão 'com.br' pra não arriscar mexer em outros TLDs onde a
       heurística não foi validada. (O caso em que a barra vira uma
       caixa de detecção SEPARADA, com espaço ao redor, já é corrigido
       antes desta função — ver o `re.sub` logo antes de
       `_txt_dominio_sem_espaco` em `_estruturar_anuncio_google_ads`.)
    3) mesma confusão barra→'l' do item 2, mas nas DUAS barras do
       protocolo ('http://' vira 'http:ll', 'https://' vira
       'https:ll') — validado com anúncio real da educbank
       ('http://www.educbank.com.br/' → 'http:llwww.educbank.com.br/').
       Tratado separado do item 2 porque aqui são duas barras coladas
       (não uma só) logo depois de ':', então a regex do domínio não
       cobre esse caso.
    """
    if not texto:
        return texto
    _url_v102 = str(texto).strip()
    _tem_sinal_url_v102 = bool(re.match('^(?:https?\\s*[:;/lI|.-]*\\s*)?[nNvVwW]{2,4}[.:]?\\s*|^https?\\s*[:;/lI|.-]+', _url_v102, flags=re.IGNORECASE))
    if _tem_sinal_url_v102:
        _url_v102 = re.sub('^([nNvVwW]{2,4})[.:]?\\s*', 'www.', _url_v102, flags=re.IGNORECASE)
        _url_v102 = re.sub('^(https?)[\\s:;/lI|.-]+(?=(?:www|[a-z0-9]))', '\\1://', _url_v102, flags=re.IGNORECASE)
        _url_v102 = re.sub('^(https?://)[nNvVwW]{2,4}[.:]?\\s*', '\\1www.', _url_v102, flags=re.IGNORECASE)
        _url_v102 = re.sub('\\s+', '', _url_v102)
        _url_v102 = re.sub('(?<=[a-z0-9])[,;:_]+(?=(?:com|net|org|io|app|shop|fr|de|nl|pt|be|es|it|uk|br)(?:[._]?br[lI]?)?(?:/|$))', '.', _url_v102, flags=re.IGNORECASE)
        _url_v102 = re.sub('\\.?(?P<tld>com)[._]?br[lI]?(?=/|$)', lambda m: '.com.br/', _url_v102, flags=re.IGNORECASE)
        _url_v102 = re.sub('\\.?(?P<tld>com|net|org|io|app|shop|fr|de|nl|pt|be|es|it|uk|br)[lI]?(?=/|$)', lambda m: '.' + m.group('tld').lower() + '/', _url_v102, flags=re.IGNORECASE)
        _url_v102 = re.sub('/+$', '/', _url_v102)
        texto = _url_v102
    texto = re.sub('^(https?)\\s*[;,.]?\\s*[:;]?\\s*[l|/]{1,3}(?=(?:www|[a-z0-9]))', '\\1://', texto, flags=re.IGNORECASE)
    texto = re.sub('^(https?)l(?=/{1,2}(?:www|[a-z0-9]))', '\\1:', texto, flags=re.IGNORECASE)
    texto = re.sub('^(https?):l{1,2}(?=[a-zA-Z0-9])', '\\1://', texto, flags=re.IGNORECASE)
    texto = re.sub('^((?:https?://)?)[nNvVwW]{2,4}[.:]{0,2}\\s*(?=[a-zA-Z0-9])', '\\1www.', texto)
    _tlds_ocr = 'com|net|org|io|shop|app|fr|de|nl|pt|be|es|it|uk|ie|at|ch|pl|cz|dk|se|no|fi|br|us|ca|au|nz|mx|ar|cl|co|pe|uy|za|jp|kr|sg|in'
    _match_tld = re.search(f'\\.?({_tlds_ocr})([._]?br)?(?=[lI/]|$)', texto, flags=re.IGNORECASE)
    if _match_tld:
        _antes, _resto = (texto[:_match_tld.start()], texto[_match_tld.end():])
        _tld = _match_tld.group(1).lower()
        if _match_tld.group(2) and _tld != 'br':
            _tld += '.br'
        if _resto[:1] in {'l', 'L', 'I', 'i'}:
            _resto = _resto[1:]
        _resto = re.sub('^/+', '', _resto)
        texto = _antes + '.' + _tld + '/' + _resto
    texto = re.sub('ãol', 'ão/', texto, flags=re.IGNORECASE)
    if '/' in texto:
        _pos_barra = texto.index('/')
        _dominio_parte, _caminho_parte = (texto[:_pos_barra + 1], texto[_pos_barra + 1:])
        _caminho_parte = re.sub('(?<=[a-zà-úãõ]{4})l(?=[a-zà-úãõ]{4})', '/', _caminho_parte, flags=re.IGNORECASE)
        texto = _dominio_parte + _caminho_parte
    texto = re.sub('_+(?=\\.?(?:com|net|org|io|shop|app)(?:\\.?br)?)', '', texto, flags=re.IGNORECASE)
    texto = re.sub('(?<!http:)(?<!https:)/{2,}', '/', texto)
    return texto

def _detectar_cor_fundo_pagina(img_bgr):
    """Detecta se a imagem tem uma margem/respiro CINZA (não branco) da
    PÁGINA sobrando ao redor do card do anúncio — comum quando o
    screenshot capturado (Central de Transparência) tem tamanho fixo
    maior que o conteúdo real do anúncio, sobrando um pedaço da cor de
    fundo da página (geralmente à direita e/ou embaixo do card,
    validado nos prints reais reportados pelo usuário). TAMBÉM cobre o
    caso do card em si (não só a margem da página ao redor) ter uma cor
    de fundo levemente tingida (ex: lavanda clarinho, BGR ~(250,236,236)
    em vez de branco puro) — comum em anúncios de Display.

    Sem tratar essa cor como fundo, ela é lida como "não-branco" pelos
    detectores de banda (`_detectar_bandas_texto`) e de coluna
    (`_dividir_banda_em_botoes`) — que assumem que QUALQUER pixel
    não-branco é texto/ícone. O resultado prático: o respiro branco que
    deveria separar duas bandas/colunas nunca aparece (o fundo tingido
    gruda direto em toda linha de conteúdo real, sem nenhuma faixa
    branca de verdade entre elas), e tudo vira uma banda só — gigante,
    quase 100% "preenchida" (o que também confunde a detecção de botão
    sólido, ver `_detectar_bandas_texto`) e mal classificada, ou nem
    reconhecida (cai no fallback de texto bruto, sem estrutura nenhuma).

    Amostra um bloco pequeno em CADA UM DOS 4 CANTOS da imagem (não só
    o inferior direito) e usa o primeiro que for uniforme e não-branco.
    Checar só um canto (sempre o mesmo) falha sempre que ELE, por
    acaso, cai dentro de algum elemento real do anúncio nesse ponto
    específico — bug real, anúncio "Compre Agora Seu Ingresso" da
    BuyTicket Brasil: o canto inferior direito cai dentro da barra de
    CTA preta (fim do card), então a função devolvia None mesmo com o
    resto do card inteiro num lavanda clarinho uniforme e óbvio nos
    outros 3 cantos. Devolve None só quando NENHUM dos 4 cantos serve —
    já branco (imagem "normal", sem esse problema) ou não uniforme o
    suficiente pra confiar que é fundo, não conteúdo real (ex: outro
    anúncio grudado logo abaixo/ao lado)."""
    import numpy as _np_fundo
    altura, largura = img_bgr.shape[:2]
    tam = max(4, min(20, altura // 10, largura // 10))
    if tam < 4:
        return None
    _cantos = (img_bgr[0:tam, 0:tam], img_bgr[0:tam, largura - tam:largura], img_bgr[altura - tam:altura, 0:tam], img_bgr[altura - tam:altura, largura - tam:largura])
    for canto in _cantos:
        if canto.size == 0:
            continue
        pixels = canto.reshape(-1, 3).astype(float)
        cor_bgr = pixels.mean(axis=0)
        if bool(_np_fundo.all(cor_bgr > 247)):
            continue
        if float(pixels.std(axis=0).max()) > 12:
            continue
        return cor_bgr
    return None

def _detectar_regiao_foto_embutida(img_bgr):
    """Detecta um retângulo de FOTO de verdade embutida no meio do
    anúncio (ex: a foto do show ao lado da descrição no anúncio da
    FanTicket, onde a descrição de 5 linhas fica ao lado de uma foto de
    pessoas dançando) — pra poder EXCLUIR esses pixels da detecção de
    bandas em `_detectar_bandas_texto`.

    Sem isso, os pixels bem coloridos e contínuos da foto nunca dão o
    respiro de 3px que separa uma linha de texto da outra (a foto ocupa
    várias linhas de altura sem nenhuma interrupção vertical), então
    TODAS as linhas de descrição que ficam do lado da foto grudam numa
    única banda gigante — e a leitura por OCR dessa banda mistura o
    texto da descrição com a área da foto, saindo embaralhada (ex.:
    "Faltou ingresso pode te segurança..." em vez da ordem real). A
    média de cor dessa banda gigante também sai "misto" (nem azul nem
    cinza uniforme, por causa da variedade de cor da foto), fazendo o
    resto do pipeline tratar a descrição inteira como se fosse uma
    fileira de botões — perdendo a descrição por completo.

    Detecta via DIVERSIDADE DE COR: uma foto de verdade tem muito mais
    tons distintos por área do que qualquer elemento de UI deste tipo
    de anúncio (fundo quase branco, texto cinza uniforme, título azul
    uniforme, no máximo um ícone de cor chapada) — mesmo um ícone
    colorido pequeno (ex: avatar, ícone do WhatsApp, ~40x40px) nunca
    passa de uma dúzia de tons (borda + preenchimento + antialiasing)
    numa área tão pequena. Divide a imagem em blocos de 20x20px e marca
    como "foto" qualquer bloco com mais de 15 tons distintos (RGB
    arredondado pro múltiplo de 24 mais próximo, pra ignorar ruído de
    compressão/antialiasing) — depois agrupa blocos "foto" vizinhos
    (4-conectividade) e devolve o retângulo (y_min, y_max, x_min, x_max)
    em pixels do maior grupo contíguo, só se ele for grande o bastante
    (>=80x80px — bem acima do tamanho de qualquer ícone já validado)
    pra não ser confundido com um ícone colorido pequeno. Devolve None
    quando não acha nenhum retângulo assim, ou quando ele tomaria conta
    de mais de 60% da imagem inteira (esse extrator é só pra anúncio de
    TEXTO com sitelinks — se a imagem inteira for foto, não há banda de
    texto real pra proteger)."""
    import cv2 as _cv2_foto
    import numpy as _np_foto
    altura_total, largura_total = img_bgr.shape[:2]
    img_rgb = img_bgr[:, :, ::-1]
    tam_bloco = 20
    n_blocos_y = altura_total // tam_bloco
    n_blocos_x = largura_total // tam_bloco
    if n_blocos_y == 0 or n_blocos_x == 0:
        return None
    img_hsv = _cv2_foto.cvtColor(img_bgr, _cv2_foto.COLOR_BGR2HSV)
    matiz = img_hsv[:, :, 0].astype(_np_foto.int32)
    saturacao = img_hsv[:, :, 1]
    matiz_quantizada = matiz // 8
    grade_foto = _np_foto.zeros((n_blocos_y, n_blocos_x), dtype=bool)
    for by in range(n_blocos_y):
        for bx in range(n_blocos_x):
            y0, y1 = (by * tam_bloco, (by + 1) * tam_bloco)
            x0, x1 = (bx * tam_bloco, (bx + 1) * tam_bloco)
            sat_bloco = saturacao[y0:y1, x0:x1]
            mask_saturado = sat_bloco >= 40
            if int(mask_saturado.sum()) < 30:
                continue
            matizes_bloco = matiz_quantizada[y0:y1, x0:x1][mask_saturado]
            if len(_np_foto.unique(matizes_bloco)) > 5:
                grade_foto[by, bx] = True
    if not grade_foto.any():
        return None
    visitado = _np_foto.zeros_like(grade_foto)
    melhor_grupo = []
    for by in range(n_blocos_y):
        for bx in range(n_blocos_x):
            if grade_foto[by, bx] and (not visitado[by, bx]):
                pilha = [(by, bx)]
                visitado[by, bx] = True
                grupo = []
                while pilha:
                    cy, cx = pilha.pop()
                    grupo.append((cy, cx))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = (cy + dy, cx + dx)
                        if 0 <= ny < n_blocos_y and 0 <= nx < n_blocos_x and grade_foto[ny, nx] and (not visitado[ny, nx]):
                            visitado[ny, nx] = True
                            pilha.append((ny, nx))
                if len(grupo) > len(melhor_grupo):
                    melhor_grupo = grupo
    if not melhor_grupo:
        return None
    ys = [c[0] for c in melhor_grupo]
    xs = [c[1] for c in melhor_grupo]
    y_min_bloco, y_max_bloco = (min(ys), max(ys))
    x_min_bloco, x_max_bloco = (min(xs), max(xs))
    nao_branco_total = _np_foto.any(img_rgb < 240, axis=2)
    densidade = _np_foto.zeros((n_blocos_y, n_blocos_x))
    for by in range(n_blocos_y):
        for bx in range(n_blocos_x):
            y0d, y1d = (by * tam_bloco, (by + 1) * tam_bloco)
            x0d, x1d = (bx * tam_bloco, (bx + 1) * tam_bloco)
            densidade[by, bx] = nao_branco_total[y0d:y1d, x0d:x1d].mean()
    _LIMIAR_DENSIDADE = 0.35
    visitado_dens = _np_foto.zeros((n_blocos_y, n_blocos_x), dtype=bool)
    pilha_dens = []
    for by in range(y_min_bloco, y_max_bloco + 1):
        for bx in range(x_min_bloco, x_max_bloco + 1):
            visitado_dens[by, bx] = True
            pilha_dens.append((by, bx))
    while pilha_dens:
        cy, cx = pilha_dens.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = (cy + dy, cx + dx)
            if 0 <= ny < n_blocos_y and 0 <= nx < n_blocos_x and (not visitado_dens[ny, nx]) and (densidade[ny, nx] >= _LIMIAR_DENSIDADE):
                visitado_dens[ny, nx] = True
                pilha_dens.append((ny, nx))
                y_min_bloco = min(y_min_bloco, ny)
                y_max_bloco = max(y_max_bloco, ny)
                x_min_bloco = min(x_min_bloco, nx)
                x_max_bloco = max(x_max_bloco, nx)
    largura_px = (x_max_bloco - x_min_bloco + 1) * tam_bloco
    altura_px = (y_max_bloco - y_min_bloco + 1) * tam_bloco
    if largura_px < 80 or altura_px < 80:
        return None
    if largura_px * altura_px > 0.6 * altura_total * largura_total:
        return None
    y0 = y_min_bloco * tam_bloco
    y1 = min((y_max_bloco + 1) * tam_bloco, altura_total)
    x0 = x_min_bloco * tam_bloco
    x1 = min((x_max_bloco + 1) * tam_bloco, largura_total)
    print(f'[OCR-DEBUG] _detectar_regiao_foto_embutida achou retângulo y=({y0},{y1}) x=({x0},{x1})', flush=True)
    return (y0, y1, x0, x1)

def _detectar_regiao_grafico_criativo(img_bgr, _regiao_foto_precalculada=None):
    """Detecta um bloco de CRIATIVO GRÁFICO (banner/imagem promocional
    embutida no anúncio — comum em anúncio de DISPLAY/gráfico, diferente
    do anúncio de TEXTO da Rede de Pesquisa que o resto deste arquivo
    foi pensado pra ler: ex. o banner "Copa do Mundo" com foto de
    pessoas + selo + botão desenhados DENTRO da própria imagem, no
    anúncio "Ingressos Copa 2026" da BuyTicket) — pra excluir esses
    pixels da detecção de bandas, igual já fazemos com foto de verdade
    em `_detectar_regiao_foto_embutida`.

    Por que uma função SEPARADA, e não só usar `_detectar_regiao_foto_
    embutida`: aquela mede diversidade de matiz bloco a bloco (20x20px),
    o que funciona bem pra uma FOTO contínua (pele, céu, roupa variando
    a cada bloco pequeno), mas falha num criativo gráfico tipo banner,
    que costuma ser um mosaico de ÁREAS DE COR SÓLIDA + texto (fundo
    roxo + texto amarelo aqui, selo verde ali, foto de pessoas noutro
    canto) — cada bloco 20x20 isolado dentro da área "fundo roxo + texto
    amarelo", por exemplo, só vê 2 matizes, nunca estoura o limiar de
    diversidade POR BLOCO. Só o pedacinho com rosto/pele de verdade
    passava — o resto do banner (texto/selo/botão) ficava de fora,
    sobrava como pixel "não-branco" comum, e vazava pra dentro da banda
    de texto real logo acima, produzindo uma leitura de OCR toda
    embaralhada (bug real, anúncio "Ingressos Copa 2026" da BuyTicket:
    título + descrição + TODO o texto do banner promocional viraram uma
    única banda "azul" ilegível).

    A saída: em vez de bloco 20x20, mede diversidade de matiz agregada
    numa FAIXA HORIZONTAL INTEIRA (toda a largura da imagem, 20px de
    altura) — a diversidade de cor do CONJUNTO (roxo + amarelo + verde +
    tons de pele, todos somados na mesma faixa) fica bem acima de
    qualquer texto de UI legítimo, mesmo um título grande e em negrito
    (que é sempre UMA cor só — a variação ali é antialiasing borda/fundo,
    não matizes diferentes). Validado nos dados reais: faixas de título/
    descrição nunca passam de ~3 matizes distintos; o banner promocional
    real ficou entre 9 e 23. A barra de CTA sólida (ex: "Compre Agora"
    em navy escuro, mesma cor de marca do título) também fica em só 1-2
    matizes — não é confundida com o criativo mesmo tendo saturação de
    cor parecida, porque aqui o que decide é DIVERSIDADE, não saturação.

    Uma faixa só conta como "quente" (parte do criativo) se, ALÉM da
    diversidade de matiz, cobrir uma fração mínima da LARGURA da imagem
    com pixels saturados (`_FRACAO_MIN_COBERTURA`) — sem isso, um ícone
    pequeno e colorido (ex: o logo circular "b" no cabeçalho, ~60x40px,
    que sozinho já tem matizes variados por causa do antialiasing das
    bordas) contava como "quente" igual a uma faixa cheia de banner, e
    isso bugava a busca de continuidade abaixo (ver próximo parágrafo):
    o logo no topo virava o início "falso" de uma sequência que pulava
    por cima do nome do anunciante e ia parar dentro do banner de
    verdade, apagando o nome da empresa do cabeçalho junto com o banner
    (regressão real, pega no anúncio "BuyTicket Brasil: Não tome golpe"
    — o cabeçalho INTEIRO ia embora, não só a foto).

    Busca a maior sequência de faixas "quentes" tolerando lacunas no
    meio via BUSCA À FRENTE (lookahead de até `_LOOKAHEAD_FAIXAS` faixas
    = ~120px): uma faixa fria isolada não quebra a sequência se outra
    faixa quente aparecer dentro dessa janela logo à frente — isso
    resolve o caso real de um trecho de TEXTO SOBRE FUNDO SÓLIDO dentro
    do próprio banner (ex: "O tempo tá correndo... / O ingresso de
    revenda não fica parado por muito tempo.", só 2-3 matizes, mas ainda
    dentro do mesmo criativo, sanduichado entre a foto acima e o botão
    "SALVAR MEU LUGAR" abaixo — sem essa busca à frente, esse trecho
    quebrava a detecção em dois pedaços pequenos demais, ou o algoritmo
    ficava só com o menor). O fim de uma sequência é SEMPRE a última
    faixa quente encontrada — nunca se estende pra dentro de um trecho
    frio que não leva a nenhuma faixa quente depois (é assim que a barra
    de CTA, colada logo abaixo do banner, nunca é engolida junto: não
    tem nenhuma faixa quente depois dela pra "puxar" a sequência até
    lá).

    Devolve (y0, y1, x0, x1) da região achada, ou None se nenhuma faixa
    passar do limiar, se a altura resultante for menor que 100px (pouco
    provável ser um criativo de verdade), ou se tomar mais de 70% da
    altura da imagem (a esta altura já não sobra anúncio de texto pra
    proteger)."""
    import cv2 as _cv2_graf
    import numpy as _np_graf
    altura_total, largura_total = img_bgr.shape[:2]
    img_hsv = _cv2_graf.cvtColor(img_bgr, _cv2_graf.COLOR_BGR2HSV)
    matiz = img_hsv[:, :, 0].astype(_np_graf.int32)
    saturacao = img_hsv[:, :, 1].copy()
    _regiao_foto_local = _regiao_foto_precalculada
    if _regiao_foto_local is None:
        _regiao_foto_local = _detectar_regiao_foto_embutida(img_bgr)
    if _regiao_foto_local is not None:
        _yf0g, _yf1g, _xf0g, _xf1g = _regiao_foto_local
        saturacao[_yf0g:_yf1g, _xf0g:_xf1g] = 0
    matiz_quantizada = matiz // 8
    tam_faixa = 20
    n_faixas = altura_total // tam_faixa
    if n_faixas == 0:
        return None
    _LIMIAR_MATIZES = 6
    _FRACAO_MIN_COBERTURA = 0.15
    _area_faixa = largura_total * tam_faixa
    _min_pixels_saturados = max(200, int(_area_faixa * _FRACAO_MIN_COBERTURA))
    faixa_e_quente = []
    for fy in range(n_faixas):
        y0, y1 = (fy * tam_faixa, (fy + 1) * tam_faixa)
        sat_faixa = saturacao[y0:y1, :]
        mask_sat = sat_faixa >= 40
        n_sat = int(mask_sat.sum())
        if n_sat < _min_pixels_saturados:
            faixa_e_quente.append(False)
            continue
        n_matizes = len(_np_graf.unique(matiz_quantizada[y0:y1, :][mask_sat]))
        faixa_e_quente.append(n_matizes > _LIMIAR_MATIZES)
    _LOOKAHEAD_FAIXAS = 6
    melhor_inicio, melhor_fim, melhor_tam = (None, None, 0)
    _i = 0
    while _i < n_faixas:
        if not faixa_e_quente[_i]:
            _i += 1
            continue
        _inicio = _i
        _fim = _i
        _j = _i + 1
        while _j < n_faixas:
            _achou_a_frente = False
            for _k in range(_j, min(_j + _LOOKAHEAD_FAIXAS, n_faixas)):
                if faixa_e_quente[_k]:
                    _fim = _k
                    _j = _k + 1
                    _achou_a_frente = True
                    break
            if not _achou_a_frente:
                break
        _tam_atual = _fim - _inicio + 1
        if _tam_atual > melhor_tam:
            melhor_tam, melhor_inicio, melhor_fim = (_tam_atual, _inicio, _fim)
        _i = _fim + 1
    if melhor_inicio is None:
        return None
    y0 = melhor_inicio * tam_faixa
    y1 = min((melhor_fim + 1) * tam_faixa, altura_total)
    altura_px = y1 - y0
    if altura_px < 100 or altura_px > 0.7 * altura_total:
        return None
    print(f'[OCR-DEBUG] _detectar_regiao_grafico_criativo achou faixa y=({y0},{y1})', flush=True)
    return (y0, y1, 0, largura_total)

def _detectar_bandas_texto(img_bgr):
    """Varre a imagem linha a linha (sem OCR) e agrupa em 'bandas'
    horizontais de texto, cada uma classificada pela cor média dos
    pixels não-brancos:
    - 'azul'      → título/link clicável (headline do anúncio ou de um
                    sitelink) — o Google Ads sempre usa azul aqui.
    - 'cinza'     → descrição, URL exibida, ou o rótulo "Patrocinado".
    - 'separador' → linha divisória fina (~2px) entre sitelinks.
    - 'misto'     → ícone colorido + texto (ex: botão "Enviar
                    mensagem" do WhatsApp) — tratado como possível CTA.
    Essa classificação por cor é bem mais confiável que tentar adivinhar
    a estrutura só pelo texto (validado nos prints reais do Google Ads:
    título sempre azul, descrição/URL sempre cinza uniforme)."""
    import numpy as _np_bandas
    import cv2 as _cv2_bandas
    img_rgb = img_bgr[:, :, ::-1]
    altura_total, _largura, _c = img_rgb.shape
    nao_branco = _np_bandas.any(img_rgb < 240, axis=2)
    _cor_fundo_pagina = _detectar_cor_fundo_pagina(img_bgr)
    if _cor_fundo_pagina is not None:
        _cor_fundo_rgb = _cor_fundo_pagina[::-1]
        _prox_fundo_pagina = _np_bandas.all(_np_bandas.abs(img_rgb.astype(_np_bandas.int16) - _cor_fundo_rgb.astype(_np_bandas.int16)) <= 10, axis=2)
        nao_branco = nao_branco & ~_prox_fundo_pagina
    _regiao_foto = _detectar_regiao_foto_embutida(img_bgr)
    if _regiao_foto is not None:
        _yf0, _yf1, _xf0, _xf1 = _regiao_foto
        nao_branco[_yf0:_yf1, _xf0:_xf1] = False
    _regiao_grafico = _detectar_regiao_grafico_criativo(img_bgr, _regiao_foto)
    if _regiao_grafico is not None:
        _yg0, _yg1, _xg0, _xg1 = _regiao_grafico
        nao_branco[_yg0:_yg1, _xg0:_xg1] = False
    _linhas_com_conteudo = _np_bandas.where(nao_branco.any(axis=1))[0]
    _y_primeiro_conteudo = int(_linhas_com_conteudo.min()) if len(_linhas_com_conteudo) else 0
    _y_limite_favicon = min(_y_primeiro_conteudo + 160, altura_total)
    _x_ignorar_quebra = min(int(_largura * 0.13), 110)
    nao_branco_quebra = nao_branco.copy()
    nao_branco_quebra[:_y_limite_favicon, :_x_ignorar_quebra] = False
    linhas = []
    _saturacao_total = _cv2_bandas.cvtColor(img_bgr, _cv2_bandas.COLOR_BGR2HSV)[:, :, 1]
    for y in range(altura_total):
        mask = nao_branco[y]
        n = int(mask.sum())
        mask_quebra = nao_branco_quebra[y]
        n_quebra = int(mask_quebra.sum())
        if n_quebra > 3:
            pix = img_rgb[y][mask_quebra]
            linhas.append((y, n, float(pix[:, 0].mean()), float(pix[:, 1].mean()), float(pix[:, 2].mean())))
    bandas_brutas = []
    atual = []
    y_ant = None
    for y, n, r, g, b in linhas:
        if y_ant is not None and y - y_ant > 3:
            if atual:
                bandas_brutas.append(atual)
            atual = []
        atual.append((y, n, r, g, b))
        y_ant = y
    if atual:
        bandas_brutas.append(atual)
    bandas = []
    for banda in bandas_brutas:
        y_min, y_max = (banda[0][0], banda[-1][0])
        peso_total = sum((x[1] for x in banda))
        r = sum((x[2] * x[1] for x in banda)) / peso_total
        g = sum((x[3] * x[1] for x in banda)) / peso_total
        b = sum((x[4] * x[1] for x in banda)) / peso_total
        altura = y_max - y_min + 1
        _cols_com_pixel_bandas = _np_bandas.where(nao_branco[y_min:y_max + 1].any(axis=0))[0]
        _taxa_preenchimento_bandas = 0.0
        _largura_conteudo_bandas = 0
        if len(_cols_com_pixel_bandas):
            _x0c_bandas = int(_cols_com_pixel_bandas.min())
            _x1c_bandas = int(_cols_com_pixel_bandas.max())
            _largura_conteudo_bandas = _x1c_bandas - _x0c_bandas + 1
            _caixa_bandas = nao_branco[y_min:y_max + 1, _x0c_bandas:_x1c_bandas + 1]
            _taxa_preenchimento_bandas = float(_caixa_bandas.mean())
        _x_min_botao_bandas = None
        _x_max_botao_bandas = None
        if altura >= 15 and _largura_conteudo_bandas >= 40 and (_taxa_preenchimento_bandas >= 0.6):
            classe = 'botao'
            _faixa_mask_botao = nao_branco[y_min:y_max + 1]
            if _faixa_mask_botao.size:
                _ocupacao_colunas = _faixa_mask_botao.mean(axis=0)
                _cols_solidas = _ocupacao_colunas >= 0.68
                _runs = []
                _ini_run = None
                for _xc, _eh_solida in enumerate(_cols_solidas):
                    if _eh_solida and _ini_run is None:
                        _ini_run = _xc
                    elif not _eh_solida and _ini_run is not None:
                        if _xc - _ini_run >= 40:
                            _runs.append((_ini_run, _xc - 1))
                        _ini_run = None
                if _ini_run is not None and len(_cols_solidas) - _ini_run >= 40:
                    _runs.append((_ini_run, len(_cols_solidas) - 1))
                if _runs:
                    _x_min_botao_bandas, _x_max_botao_bandas = max(_runs, key=lambda _r: _r[1] - _r[0])
        elif altura <= 3 and r > 190:
            classe = 'separador'
        elif b > r + 15 and b > 150:
            classe = 'azul'
        else:
            _mask_banda_cor = nao_branco[y_min:y_max + 1]
            _sat_banda = _saturacao_total[y_min:y_max + 1]
            _n_tinta = int(_mask_banda_cor.sum())
            _n_tinta_saturada = int((_mask_banda_cor & (_sat_banda >= 40)).sum())
            _fracao_saturada = _n_tinta_saturada / _n_tinta if _n_tinta else 0.0
            classe = 'cinza' if _fracao_saturada >= 0.6 else 'misto'
        x_min_favicon = 0
        if y_min < _y_limite_favicon and classe != 'azul':
            _regiao_favicon = img_rgb[y_min:y_max + 1, 0:_x_ignorar_quebra]
            if _regiao_favicon.size:
                _canal_max = _regiao_favicon.max(axis=2).astype(_np_bandas.int16)
                _canal_min = _regiao_favicon.min(axis=2).astype(_np_bandas.int16)
                _saturacao = _canal_max - _canal_min
                _n_pixels_coloridos = int((_saturacao > 30).sum())
                if _n_pixels_coloridos >= 8:
                    x_min_favicon = _x_ignorar_quebra
        bandas.append({'y_min': y_min, 'y_max': y_max, 'classe': classe, 'x_min_favicon': x_min_favicon, 'x_min_botao': _x_min_botao_bandas if classe == 'botao' else None, 'x_max_botao': _x_max_botao_bandas if classe == 'botao' else None})
    return bandas

def _detectar_hifen_no_intervalo(recorte_bgr, x_esq: int, x_dir: int) -> bool:
    """Verifica, olhando os PIXELS (não o OCR), se existe um hífen
    isolado no intervalo horizontal [x_esq, x_dir) do `recorte_bgr` —
    usado por `_ocr_banda` pra recuperar o "-" que separa duas
    palavras (ex: "Privadas - Prospecção") quando o detector de texto
    do EasyOCR (CRAFT) já descartou essa marca como ruído, por ela ser
    curta e fina demais (ver comentário em `_ocr_banda`). Testado
    direto nos pixels do vão entre duas caixas de palavra JÁ
    reconhecidas — mais confiável aqui do que pedir pro EasyOCR achar
    o hífen sozinho, porque a gente já sabe exatamente onde procurar.

    Critério: um hífen é um traço FINO (poucas linhas de altura, bem
    menor que a altura de uma letra) posicionado no MEIO vertical da
    linha — não no topo (onde ficaria um acento/til) nem na base (onde
    ficaria a haste de um "g"/"p"/"q"). Qualquer coisa fora desse
    perfil (ex: sujeira de compressão JPEG espalhada, sombra de um
    ícone vizinho) tende a não ter essa combinação específica de
    "fino + centralizado", então não é confundida com hífen."""
    if x_dir - x_esq < 2:
        return False
    import numpy as _np_hifen
    recorte = recorte_bgr[:, x_esq:x_dir]
    if recorte.size == 0:
        return False
    _cinza_hifen = recorte.mean(axis=2)
    if float(_np_hifen.median(_cinza_hifen)) < 128:
        nao_branco = _cinza_hifen > 160
    else:
        nao_branco = _np_hifen.any(recorte < 200, axis=2)
    altura = nao_branco.shape[0]
    if altura < 4:
        return False
    linhas_com_pixel = _np_hifen.where(nao_branco.any(axis=1))[0]
    if len(linhas_com_pixel) == 0:
        return False
    y_topo, y_base = (int(linhas_com_pixel.min()), int(linhas_com_pixel.max()))
    espessura = y_base - y_topo + 1
    centro_relativo = (y_topo + y_base) / 2 / altura
    if espessura > max(3, int(altura * 0.35)):
        return False
    if not 0.3 < centro_relativo < 0.7:
        return False
    colunas_com_pixel = nao_branco[y_topo:y_base + 1].any(axis=0)
    largura_pixels = int(colunas_com_pixel.sum())
    if largura_pixels < 3:
        return False
    blocos = 0
    dentro_de_bloco = False
    for tem_pixel in colunas_com_pixel:
        if tem_pixel and (not dentro_de_bloco):
            blocos += 1
            dentro_de_bloco = True
        elif not tem_pixel:
            dentro_de_bloco = False
    return blocos == 1

def _detectar_glifo_curto_no_intervalo(recorte_bgr, x_esq: int, x_dir: int) -> bool:
    """Verifica, pelos PIXELS (não pelo OCR), se existe alguma marca de
    tinta relevante — não necessariamente um hífen — no intervalo
    horizontal [x_esq, x_dir) do `recorte_bgr`. Complementa
    `_detectar_hifen_no_intervalo`: aquela função só reconhece um
    hífen (traço fino e centralizado); esta aqui pega qualquer OUTRA
    coisa que sobrar no vão — o caso real que motivou isso foi uma
    palavra de UMA letra acentuada sozinha entre duas outras palavras
    (ex: o "é" de "Entrar no Show é Garantido", um sitelink real da
    BuyTicket Brasil), que o CRAFT do EasyOCR descarta como caixa de
    detecção própria por ser pequena/fina demais (mesma causa-raiz do
    hífen perdido), mas cujo "buraco" no meio do texto não tem o
    perfil fino-e-centralizado de um hífen — tem a altura e a posição
    vertical (subindo até a faixa do acento) de uma letra de verdade.
    Quando dá positivo aqui, `_ocr_banda` faz uma segunda passada de
    OCR SÓ nesse recorte, bem mais sensível (ver
    `_recuperar_texto_no_intervalo`), pra tentar recuperar o texto
    perdido — em vez de inserir um "-" (que só faz sentido pro caso
    hífen)."""
    if x_dir - x_esq < 2:
        return False
    import numpy as _np_glifo
    recorte = recorte_bgr[:, x_esq:x_dir]
    if recorte.size == 0:
        return False
    _cinza_glifo = recorte.mean(axis=2)
    if float(_np_glifo.median(_cinza_glifo)) < 128:
        nao_branco = _cinza_glifo > 160
    else:
        nao_branco = _np_glifo.any(recorte < 235, axis=2)
    altura = nao_branco.shape[0]
    if altura < 4:
        return False
    linhas_com_pixel = _np_glifo.where(nao_branco.any(axis=1))[0]
    if len(linhas_com_pixel) == 0:
        return False
    y_topo, y_base = (int(linhas_com_pixel.min()), int(linhas_com_pixel.max()))
    espessura = y_base - y_topo + 1
    colunas_com_pixel = nao_branco[y_topo:y_base + 1].any(axis=0)
    largura_pixels = int(colunas_com_pixel.sum())
    if largura_pixels < 2:
        return False
    centro_relativo = (y_topo + y_base) / 2 / altura
    eh_perfil_hifen = espessura <= max(3, int(altura * 0.35)) and 0.3 < centro_relativo < 0.7
    return not eh_perfil_hifen

def _detectar_pontuacao_curta_no_intervalo(recorte_bgr, x_esq: int, x_dir: int) -> str:
    """Reconhece pontuação pequena que o CRAFT costuma ignorar como caixa.

    O caso que motivou esta função foi vírgula em texto de Display: o glifo
    continuava visível nos pixels, mas a releitura permissiva do EasyOCR
    interpretava a marca curta como o dígito ``1``. Como uma vírgula ocupa
    somente a parte inferior da linha e é muito menor que uma letra/dígito
    verdadeiro, dá para distingui-la geometricamente sem adivinhar pelo texto.

    Retorna apenas a pontuação quando o perfil é forte o bastante; caso
    contrário devolve string vazia e deixa o fallback normal tentar recuperar
    uma letra curta real (por exemplo, ``é``).
    """
    if x_dir - x_esq < 2:
        return ''
    import numpy as _np_pont
    recorte = recorte_bgr[:, x_esq:x_dir]
    if recorte.size == 0:
        return ''
    _pix = recorte.astype(_np_pont.int16)
    _cor_fundo = _np_pont.median(_pix.reshape(-1, 3), axis=0)
    _dist_fundo = _np_pont.max(_np_pont.abs(_pix - _cor_fundo), axis=2)
    tinta = _dist_fundo >= 24
    ys, xs = _np_pont.where(tinta)
    if len(xs) < 2:
        return ''
    y0, y1 = (int(ys.min()), int(ys.max()))
    x0, x1 = (int(xs.min()), int(xs.max()))
    h = y1 - y0 + 1
    w = x1 - x0 + 1
    altura_linha = max(1, tinta.shape[0])
    centro_y = (y0 + y1) / 2 / altura_linha
    if centro_y >= 0.5 and h <= max(9, int(altura_linha * 0.58)) and (w <= max(8, int(altura_linha * 0.42))) and (h * w <= max(48, int(altura_linha * altura_linha * 0.18))):
        return ','
    return ''

def _recuperar_texto_no_intervalo(reader, recorte_bgr, x_esq: int, x_dir: int) -> str:
    """Faz uma segunda passada de OCR, bem mais sensível, restrita a um
    vão pequeno onde `_detectar_glifo_curto_no_intervalo` já confirmou
    (pelos pixels) que sobrou alguma marca — usada só quando essa marca
    NÃO tem perfil de hífen. Recorta com uma margem generosa (a
    palavra perdida pode ser mais larga que o vão medido entre as
    caixas vizinhas, já que o CRAFT costuma cortar rente às bordas das
    palavras que ele DETECTA) e roda o EasyOCR com limiares bem
    permissivos — os mesmos já usados no fallback de "banda muda" mais
    acima em `_ocr_banda` — pra maximizar a chance de ler algo tão
    pequeno quanto uma letra acentuada isolada (ex: "é").

    Só aceita o resultado se vier CURTO (até 3 caracteres): o objetivo
    aqui é recuperar uma palavra de uma letra só (com ou sem acento),
    não arriscar duplicar/corromper texto de uma palavra vizinha que a
    margem generosa possa ter incluído por engano — se vier mais longo
    que isso, é mais seguro devolver vazio e deixar o texto original
    (só com o espaço) do que arriscar lixo."""
    if x_dir - x_esq < 2:
        return ''
    margem = 10
    largura_total = recorte_bgr.shape[1]
    x0 = max(0, x_esq - margem)
    x1 = min(largura_total, x_dir + margem)
    recorte = recorte_bgr[:, x0:x1]
    if recorte.size == 0:
        return ''
    resultado = reader.readtext(recorte, detail=1, width_ths=0.15, height_ths=0.5, text_threshold=0.3, low_text=0.2, link_threshold=0.2)
    if not resultado:
        return ''
    resultado.sort(key=lambda item: item[0][0][0])
    itens_texto = [(_bbox, (t or '').strip(), float(_conf or 0.0)) for _bbox, t, _conf in resultado if (t or '').strip()]
    if not itens_texto:
        return ''
    textos = [t for _bbox, t, _conf in itens_texto]
    texto = textos[0] if len(textos) == 1 else ''.join(textos)
    texto = texto.strip('\'"`´,.;:!?()[]{}').strip()
    if not texto:
        return ''
    if re.match('^\\d', texto):
        print(f'[OCR-DEBUG] glifo recuperado rejeitado (começa por dígito): {texto!r}', flush=True)
        return ''
    return texto if len(texto) <= 3 else ''

def _reler_banda_ampliada_se_suspeita(reader, recorte_bgr, texto_atual: str) -> str:
    """Reprocessa uma banda em 2.5x somente quando aparecem artefatos
    típicos de vírgula/antialiasing lidos como dígito 1. Mantém a leitura
    original salvo quando a alternativa reduz esses artefatos e continua
    muito parecida com o texto original."""
    if not texto_atual or recorte_bgr is None or recorte_bgr.size == 0:
        return texto_atual
    _rx_sus = re.compile('(?:^|\\s)1(?:\\s|(?=[A-Za-zÀ-ÿ]))|\\b1[A-Za-zÀ-ÿ]')
    _qtd_sus_atual = len(_rx_sus.findall(texto_atual))
    if _qtd_sus_atual == 0:
        return texto_atual
    try:
        import cv2 as _cv2_re
        import difflib as _difflib_re
        _ampliado = _cv2_re.resize(recorte_bgr, None, fx=2.5, fy=2.5, interpolation=_cv2_re.INTER_CUBIC)
        _res = reader.readtext(_ampliado, detail=1, width_ths=0.35, height_ths=0.5, text_threshold=0.55, low_text=0.3, link_threshold=0.3)
        if not _res:
            return texto_atual
        _res.sort(key=lambda it: (sum((p[1] for p in it[0])) / len(it[0]), it[0][0][0]))
        _cand = ' '.join(((it[1] or '').strip() for it in _res if (it[1] or '').strip())).strip()
        if not _cand:
            return texto_atual
        _cand = re.sub('\\s+([,.;:!?])', '\\1', _cand)
        _cand = re.sub('\\s{2,}', ' ', _cand).strip()
        _qtd_sus_cand = len(_rx_sus.findall(_cand))
        if _qtd_sus_cand >= _qtd_sus_atual:
            return texto_atual

        def _norm(_s):
            _s = unicodedata.normalize('NFKD', _s).encode('ascii', 'ignore').decode('ascii')
            return re.sub('[^a-z0-9]+', '', _s.lower())
        _na, _nb = (_norm(texto_atual), _norm(_cand))
        if not _na or not _nb:
            return texto_atual
        _sim = _difflib_re.SequenceMatcher(None, _na, _nb).ratio()
        _pal_a = len(re.findall('[A-Za-zÀ-ÿ0-9]+', texto_atual))
        _pal_b = len(re.findall('[A-Za-zÀ-ÿ0-9]+', _cand))
        if _sim >= 0.72 and _pal_b >= max(1, int(_pal_a * 0.7)):
            print(f'[OCR-DEBUG] releitura ampliada adotada: {texto_atual!r} -> {_cand!r} (sim={_sim:.2f})', flush=True)
            return _cand
    except Exception as e:
        print(f'[OCR-DEBUG] releitura ampliada falhou: {e!r}', flush=True)
    return texto_atual

_REGEX_ASPA_FECHAMENTO_TROCADA = re.compile('(["][^"\\\'\\n]{1,60})[\\\'](?=\\s|[.,;:!?)\\]]|$)')

def _normalizar_aspas_ocr(texto: str) -> str:
    """Normaliza aspas lidas pelo OCR: unifica variantes tipográficas
    (curvas " " ' ') pra aspas retas " e ' — e corrige o caso em que o
    EasyOCR lê a aspa DUPLA de fechamento de um trecho citado como um
    apóstrofo simples (') em vez da aspa dupla (") que está realmente
    impressa no anúncio (validado num anúncio real da BuyTicket
    Brasil: o card leu 'Ingressos BTS 2026 World Tour "Arirang'' —
    abre com aspa dupla reta, fecha com apóstrofo, quando o criativo
    original tem aspa dupla dos dois lados).
    Só troca quando existe uma aspa dupla de ABERTURA sem o fechamento
    correspondente por perto (heurística: abre com " e o próximo
    candidato a fechamento, a até 60 caracteres, é um apóstrofo solto
    seguido de espaço/pontuação/fim de string) — nunca mexe num
    apóstrofo que faça parte de uma contração ou plural de verdade no
    meio do texto, porque esses não vêm logo depois de uma aspa dupla
    aberta sem fechar."""
    if not texto:
        return texto
    texto = texto.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")
    texto = _REGEX_ASPA_FECHAMENTO_TROCADA.sub(lambda m: m.group(1) + '"', texto)
    return texto

_REGEX_ESPACO_ANTES_PONTUACAO = re.compile('\\s+([,.;:!?])')

_REGEX_O_OU_ZERO_ISOLADO = re.compile('(?<=\\s)[O0](?=\\s)')

def _corrigir_o_isolado(texto: str) -> str:
    """Troca um "O"/"0" isolado entre espaços pelo conectivo "o"
    minúsculo, EXCETO quando ele vem logo depois de uma pontuação de
    fim de frase (. ! ?) — nesse caso pode ser um "O" de verdade
    iniciando a frase seguinte (ex: "Vem crescendo. O aluno..."), então
    não mexe. Ignora quantos espaços houver entre a pontuação e a
    letra (o OCR às vezes insere espaço duplo ali)."""
    if not texto:
        return texto

    def _troca(m):
        i = m.start() - 1
        while i >= 0 and texto[i] == ' ':
            i -= 1
        if i >= 0 and texto[i] in '.!?':
            return m.group(0)
        return 'o'
    return _REGEX_O_OU_ZERO_ISOLADO.sub(_troca, texto)

def _limpar_pontuacao_ocr(texto: str) -> str:
    """Corrige espaçamento que o EasyOCR insere por engano ao redor de
    pontuação — ele costuma tratar cada caractere de pontuação como se
    fosse uma 'palavra' separada, com espaço antes (ex:
    'particulares , assegurando' em vez de 'particulares,
    assegurando'; 'mensalidades .' em vez de 'mensalidades.'). Cobre
    ,  .  ;  :  !  ?

    Também remove um '_' solto colado no FINAL do texto: sublinhado
    isolado não é pontuação de frase em português nenhuma — apareceu
    em testes reais no fim de descrições, provavelmente ruído que o
    detector de texto capturou perto da borda da caixa (mesma família
    de problema do hífen perdido, só que ao contrário: aqui ele "acha"
    texto onde não tem nada de fato)."""
    if not texto:
        return texto
    texto = re.sub('^[,;:]+\\s*', '', texto)
    texto = _REGEX_ESPACO_ANTES_PONTUACAO.sub('\\1', texto)
    texto = re.sub('(?<=\\w)\\s+[~^]\\s+(?=\\w)', ' ', texto)
    texto = re.sub('\\s{2,}', ' ', texto)
    texto = re.sub('(?<=\\|)\\s*[$@]\\s+(?=[A-Za-zÀ-ÿ])', ' ', texto)
    texto = re.sub('(?<=\\w)_+\\s*,\\s+(?=[A-ZÀ-Ý])', '. ', texto)
    texto = re.sub('_+\\s*$', '', texto).rstrip()

    def _remover_inicial_duplicada_pos_frase(_m):
        _pont, _letra, _palavra = (_m.group(1), _m.group(2), _m.group(3))
        if _palavra and _palavra[0].lower() == _letra.lower():
            print(f'[OCR-DEBUG] inicial duplicada fundida removida: {_letra!r} antes de {_palavra!r}', flush=True)
            return f'{_pont} {_palavra}'
        return _m.group(0)
    texto = re.sub('([.!?])\\s+([A-Za-zÀ-ÿ])\\s+([A-Za-zÀ-ÿ]{2,})\\b', _remover_inicial_duplicada_pos_frase, texto)
    _digitos = re.findall('\\d', texto)
    _palavras_alpha = re.findall('[A-Za-zÀ-ÿ]{2,}', texto)
    if len(_palavras_alpha) >= 4 and _digitos and all((d == '1' for d in _digitos)):
        texto = re.sub('(?<![A-Za-zÀ-ÿ0-9])1(?=[A-Za-zÀ-ÿ])', '', texto)
    texto = _corrigir_o_isolado(texto)
    return texto

def _dividir_banda_em_botoes(img_bgr, y_min: int, y_max: int, gap_minimo: int=None) -> list:
    """Detecta se uma banda (faixa horizontal já identificada por
    `_detectar_bandas_texto`) na verdade contém VÁRIOS botões/pílulas
    lado a lado na mesma altura — ex: "Sobre o isaac" / "Entre Em
    Contato" / "Saiba mais" — em vez de UM texto contínuo.

    `_detectar_bandas_texto` só enxerga o eixo Y (agrupa linhas por
    altura); quando os sitelinks vêm em formato de botão, lado a lado
    na MESMA faixa de Y (em vez de empilhados verticalmente, um por
    linha, com separador fino entre eles — o único formato que o resto
    do pipeline já tratava), a banda inteira é lida pelo OCR como um
    texto só, sem nenhuma separação (ex: virava "Matrícula Online
    Segura Sistema administração esc" grudado, perdendo os 2 botões
    como itens distintos).

    Esta função varre as COLUNAS (eixo X) dentro da faixa de Y da
    banda e agrupa em blocos contíguos, usando o mesmo princípio já
    usado pra separar bandas por linha (`_detectar_bandas_texto`): um
    vão em branco maior que `gap_minimo` pixels quebra um bloco do
    próximo. `gap_minimo` foi calibrado pra ficar ACIMA do espaço
    normal entre palavras de um mesmo texto (tipicamente bem menor) e
    ABAIXO do respiro/borda entre dois botões distintos — pode
    precisar de ajuste fino se aparecerem falsos positivos/negativos
    em anúncios reais.

    Devolve uma lista de (x_min, x_max) — um por bloco encontrado. Uma
    banda de texto NORMAL (título/descrição de uma linha só) sempre
    devolve UM bloco só (ou nenhum, se a faixa estiver vazia); só
    quando há 2+ blocos é que faz sentido tratar como fileira de
    botões — quem chama decide isso."""
    import numpy as _np_botoes
    altura_total = img_bgr.shape[0]
    y0 = max(0, y_min - 4)
    y1 = min(altura_total, y_max + 5)
    recorte_rgb = img_bgr[y0:y1, :, ::-1]
    if recorte_rgb.size == 0:
        return []
    if gap_minimo is None:
        gap_minimo = max(14, int((y_max - y_min) * 0.9))
    coluna_tem_pixel = _np_botoes.any(recorte_rgb < 235, axis=2).any(axis=0)
    _cor_fundo_pagina_botoes = _detectar_cor_fundo_pagina(img_bgr)
    if _cor_fundo_pagina_botoes is not None:
        _cor_fundo_rgb_botoes = _cor_fundo_pagina_botoes[::-1]
        _prox_fundo_botoes = _np_botoes.all(_np_botoes.abs(recorte_rgb.astype(_np_botoes.int16) - _cor_fundo_rgb_botoes.astype(_np_botoes.int16)) <= 10, axis=2).any(axis=0)
        coluna_tem_pixel = coluna_tem_pixel & ~_prox_fundo_botoes
    xs_com_pixel = _np_botoes.where(coluna_tem_pixel)[0]
    if len(xs_com_pixel) == 0:
        return []
    grupos = []
    x_ini = int(xs_com_pixel[0])
    x_ant = int(xs_com_pixel[0])
    for x in xs_com_pixel[1:]:
        x = int(x)
        if x - x_ant > gap_minimo:
            grupos.append((x_ini, x_ant))
            x_ini = x
        x_ant = x
    grupos.append((x_ini, x_ant))
    print(f'[OCR-DEBUG] _dividir_banda_em_botoes y=({y_min},{y_max}) altura_banda={y_max - y_min} gap_minimo={gap_minimo} -> {len(grupos)} bloco(s): {grupos}', flush=True)
    return grupos

def _reler_pontuacao_suspeita_caixa(reader, recorte_bgr, bbox, texto: str) -> str:
    """Releitura localizada quando o EasyOCR parece confundir vírgula.

    Casos observados em anúncios reais: ``Brasileira,`` saiu como
    ``Brasileira;`` e um artigo isolado ``A`` saiu como ``A,``. Em vez de
    substituir pontuação cegamente no texto final, recorta SOMENTE a caixa
    original, amplia 3x e roda uma segunda leitura com uma allowlist que
    contém vírgula/ponto/!/? mas NÃO contém ponto-e-vírgula. Só aceita a
    releitura se a sequência alfanumérica continuar a mesma, então essa
    rotina não pode trocar a palavra — apenas resolver a pontuação.
    """
    _t = (texto or '').strip()
    if not _t:
        return _t
    _suspeito = ';' in _t or bool(re.fullmatch('[AaOoEe],', _t))
    if not _suspeito:
        return _t
    try:
        import cv2 as _cv2_pont2
        import unicodedata as _ud_pont2
        xs = [int(round(p[0])) for p in bbox]
        ys = [int(round(p[1])) for p in bbox]
        x0, x1 = (max(0, min(xs) - 4), min(recorte_bgr.shape[1], max(xs) + 5))
        y0, y1 = (max(0, min(ys) - 4), min(recorte_bgr.shape[0], max(ys) + 5))
        _crop = recorte_bgr[y0:y1, x0:x1]
        if _crop.size == 0:
            return _t
        _crop = _cv2_pont2.resize(_crop, None, fx=3.0, fy=3.0, interpolation=_cv2_pont2.INTER_CUBIC)
        _allow = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzÁÀÂÃÉÊÍÓÔÕÚÜÇáàâãéêíóôõúüç0123456789,.!?-:()/%&\'"'
        _r = reader.readtext(_crop, detail=1, paragraph=False, allowlist=_allow, text_threshold=0.35, low_text=0.25, link_threshold=0.25, width_ths=0.2, height_ths=0.6)
        if not _r:
            return _t
        _r.sort(key=lambda it: min((p[0] for p in it[0])))
        _cand = ' '.join(((it[1] or '').strip() for it in _r if (it[1] or '').strip())).strip()
        if not _cand:
            return _t

        def _base(x):
            x = ''.join((c for c in _ud_pont2.normalize('NFKD', x) if not _ud_pont2.combining(c)))
            return re.sub('[^A-Za-z0-9]', '', x).lower()
        if _base(_cand) != _base(_t):
            return _t
        if ';' in _t and ';' not in _cand:
            print(f'[OCR-DEBUG] pontuação relida: {_t!r} -> {_cand!r}', flush=True)
            return _cand
        if re.fullmatch('[AaOoEe],', _t) and (not _cand.endswith(',')):
            print(f'[OCR-DEBUG] vírgula espúria removida: {_t!r} -> {_cand!r}', flush=True)
            return _cand
    except Exception as e:
        print(f'[OCR-DEBUG] releitura de pontuação falhou para {_t!r}: {e!r}', flush=True)
    return _t

def _filtrar_ruidos_ocr_linha(itens: list) -> list:
    """Remove caixas OCR espúrias usando GEOMETRIA + contexto da própria linha.

    Não corrige texto por dicionário nem por frase conhecida. O caso real que
    motivou isto é o EasyOCR separar o acento/antialiasing de ``Tá``/``Fã`` em
    uma caixa minúscula e reconhecê-la como ``1`` ou ``1F``. Como essa caixa
    fica praticamente COLADA à palavra anterior, ela é estruturalmente bem
    diferente de um número 1 legítimo em ``Fórmula 1``: o número real ocupa a
    altura normal da fonte e tem espaçamento de palavra dos dois lados.

    Também remove ``~`` isolado entre duas palavras (artefato observado em
    ``Ele ~ Tá``). A função só age quando há vizinhos textuais dos dois lados;
    números/tils legítimos fora desse padrão continuam intactos.
    """
    if not itens or len(itens) < 3:
        return itens
    import statistics as _stats_ruido

    def _txt(it):
        return (it[1] or '').strip()

    def _bbox_geom(it):
        bbox = it[0]
        xs = [float(pt[0]) for pt in bbox]
        ys = [float(pt[1]) for pt in bbox]
        return (min(xs), max(xs), min(ys), max(ys))

    def _tem_letra(t):
        return bool(re.search('[A-Za-zÀ-ÿ]', t or ''))
    _alturas_normais = []
    for _it in itens:
        _t = _txt(_it)
        if len(re.findall('[A-Za-zÀ-ÿ]', _t)) >= 2:
            _x0, _x1, _y0, _y1 = _bbox_geom(_it)
            _alturas_normais.append(max(1.0, _y1 - _y0))
    _altura_ref = _stats_ruido.median(_alturas_normais) if _alturas_normais else None
    saida = []
    for i, it in enumerate(itens):
        t = _txt(it)
        if not t:
            continue
        if i == 0 or i == len(itens) - 1:
            saida.append(it)
            continue
        ant = itens[i - 1]
        prox = itens[i + 1]
        ta, tp = (_txt(ant), _txt(prox))
        vizinhos_textuais = _tem_letra(ta) and _tem_letra(tp)
        if vizinhos_textuais and t in {'~', '˜', '^', '`', '´'}:
            print(f'[OCR-DEBUG] caixa-ruído removida entre palavras: {t!r}', flush=True)
            continue
        if vizinhos_textuais and re.fullmatch('[A-Za-zÀ-ÿ]', t):
            _prox_txt = tp.strip()
            if _prox_txt and _prox_txt[0].lower() == t.lower() and (len(_prox_txt) >= 2):
                x0, x1, y0, y1 = _bbox_geom(it)
                xp0, xp1, yp0, yp1 = _bbox_geom(prox)
                h = max(1.0, y1 - y0)
                w = max(1.0, x1 - x0)
                href = float(_altura_ref or max(1.0, yp1 - yp0))
                gap_prox = max(0.0, xp0 - x1)
                conf = float(it[2] or 0.0)
                _caixa_estreita = w <= href * 0.48
                _colado_prox = gap_prox <= max(3.0, href * 0.18)
                _conf_baixa = conf < 0.62
                if _caixa_estreita and (_colado_prox or _conf_baixa):
                    print(f'[OCR-DEBUG] letra-ruído duplicada removida: texto={t!r} prox={_prox_txt!r} conf={conf:.3f} w={w:.1f} h={h:.1f}/{href:.1f} gap_prox={gap_prox:.1f}', flush=True)
                    continue
        if vizinhos_textuais and re.fullmatch('1[A-Za-zÀ-ÿ]?', t):
            x0, x1, y0, y1 = _bbox_geom(it)
            xa0, xa1, ya0, ya1 = _bbox_geom(ant)
            xp0, xp1, yp0, yp1 = _bbox_geom(prox)
            h = max(1.0, y1 - y0)
            href = float(_altura_ref or max(1.0, ya1 - ya0, yp1 - yp0))
            gap_ant = max(0.0, x0 - xa1)
            gap_prox = max(0.0, xp0 - x1)
            conf = float(it[2] or 0.0)
            colado_anterior = gap_ant <= max(4.0, href * 0.28)
            caixa_baixa = h <= href * 0.72
            confianca_baixa = conf < 0.52
            if colado_anterior or caixa_baixa or confianca_baixa:
                print(f'[OCR-DEBUG] caixa-ruído numérica removida: texto={t!r} conf={conf:.3f} h={h:.1f}/{href:.1f} gap_ant={gap_ant:.1f} gap_prox={gap_prox:.1f}', flush=True)
                continue
        saida.append(it)
    return saida

def _ocr_banda(reader, img_bgr, y_min: int, y_max: int, x_min: int=None, x_max: int=None, retornar_linhas: bool=False):
    """Roda o EasyOCR só na faixa horizontal (com uma margem de alguns
    pixels) em vez da imagem inteira — mais rápido e evita misturar
    texto de faixas vizinhas quando há fragmentos detectados fora de
    ordem.

    Depois de juntar as palavras, checa cada VÃO entre duas palavras
    reconhecidas com `_detectar_hifen_no_intervalo` — não pra achar
    texto novo via OCR, mas pra recuperar um "-" que o detector de
    texto do EasyOCR (CRAFT) costuma descartar como ruído por ser uma
    marca curta e fina demais entre duas palavras (ex: "Matrículas
    Privadas - Prospecção" perdia o hífen antes desse fix). Já
    tentamos resolver isso baixando os limiares de detecção do
    próprio EasyOCR (min_size/text_threshold/low_text/link_threshold)
    e não funcionou — o CRAFT simplesmente não abre uma caixa de
    detecção só pro hífen mesmo mais sensível, então a checagem por
    pixel abaixo é a abordagem que realmente resolve, sem o
    trade-off de aumentar ruído em outras partes do anúncio.

    width_ths baixo (padrão do EasyOCR é 0.5): sem isso, o CRAFT
    frequentemente funde a banda inteira (ex: título "Reduzir
    Inadimplência Escolar") numa ÚNICA caixa de detecção. Quando isso
    acontece, `palavras` abaixo vira uma lista de 1 item só, o loop de
    reconstrução de espaço (que junta cada palavra com `" ".join`)
    nunca roda, e o texto sai exatamente como o reconhecedor do
    EasyOCR devolveu — GRUDADO, sem espaço nenhum entre as palavras
    (era esse o bug: "ReduzirInadimplênciaEscolarCansadode..."). Com
    width_ths baixo, cada palavra vira sua própria caixa, e a lógica
    de `" ".join(partes)" logo abaixo volta a fazer o trabalho dela de
    verdade."""
    altura_total = img_bgr.shape[0]
    largura_total = img_bgr.shape[1]
    y0 = max(0, y_min - 4)
    y1 = min(altura_total, y_max + 5)
    x0 = max(0, x_min - 6) if x_min is not None else 0
    x1 = min(largura_total, x_max + 7) if x_max is not None else largura_total
    recorte = img_bgr[y0:y1, x0:x1]
    resultado = reader.readtext(recorte, detail=1, width_ths=0.15, height_ths=0.5)
    if not resultado:
        resultado = reader.readtext(recorte, detail=1, width_ths=0.15, height_ths=0.5, text_threshold=0.4, low_text=0.3, link_threshold=0.3)
    if not resultado:
        return ('', []) if retornar_linhas else ''
    _resultado_pont = []
    for _bbox_p, _txt_p, _conf_p in resultado:
        _txt_corr_p = _reler_pontuacao_suspeita_caixa(reader, recorte, _bbox_p, _txt_p)
        _resultado_pont.append((_bbox_p, _txt_corr_p, _conf_p))
    resultado = _resultado_pont

    def _y_centro_bbox(bbox):
        _ys = [p[1] for p in bbox]
        return sum(_ys) / len(_ys)

    def _altura_bbox(bbox):
        _ys = [p[1] for p in bbox]
        return max(_ys) - min(_ys)
    resultado.sort(key=lambda item: _y_centro_bbox(item[0]))
    _altura_media = sum((_altura_bbox(item[0]) for item in resultado)) / len(resultado) if resultado else 20
    _tolerancia_linha = max(6, _altura_media * 0.6)
    _linhas_agrupadas = []
    for _item in resultado:
        _yc = _y_centro_bbox(_item[0])
        if _linhas_agrupadas and abs(_yc - _linhas_agrupadas[-1]['y_ref']) <= _tolerancia_linha:
            _grupo = _linhas_agrupadas[-1]
            _grupo['itens'].append(_item)
            _n = len(_grupo['itens'])
            _grupo['y_ref'] = (_grupo['y_ref'] * (_n - 1) + _yc) / _n
        else:
            _linhas_agrupadas.append({'y_ref': _yc, 'itens': [_item]})
    resultado = []
    linha_idx_por_palavra = []
    linhas_y_range = []
    for _idx_linha, _grupo in enumerate(_linhas_agrupadas):
        _grupo['itens'].sort(key=lambda item: item[0][0][0])
        _grupo['itens'] = _filtrar_ruidos_ocr_linha(_grupo['itens'])
        if not _grupo['itens']:
            continue
        _y_topo_linha = int(min((min((p[1] for p in item[0])) for item in _grupo['itens'])))
        _y_base_linha = int(max((max((p[1] for p in item[0])) for item in _grupo['itens'])))
        linhas_y_range.append((_y_topo_linha, _y_base_linha))
        for _item in _grupo['itens']:
            resultado.append(_item)
            linha_idx_por_palavra.append(_idx_linha)
    palavras = []
    _linha_idx_filtrada = []
    for _i_item, (bbox, t, _conf) in enumerate(resultado):
        _t = (t or '').strip()
        if _t:
            palavras.append((bbox, _t))
            _linha_idx_filtrada.append(linha_idx_por_palavra[_i_item])
    linha_idx_por_palavra = _linha_idx_filtrada
    if not palavras:
        return ('', []) if retornar_linhas else ''
    _MARGEM_VERTICAL_LINHA = 3

    def _recorte_da_linha(idx_linha):
        _y0_l, _y1_l = linhas_y_range[idx_linha]
        _y0_l = max(0, _y0_l - _MARGEM_VERTICAL_LINHA)
        _y1_l = min(recorte.shape[0], _y1_l + _MARGEM_VERTICAL_LINHA)
        return recorte[_y0_l:_y1_l, :]
    _LARGURA_MAX_VAO_GLIFO = 70
    _linhas_com_hifen_final_recuperado = set()
    partes = []
    _recorte_primeira_linha = _recorte_da_linha(linha_idx_por_palavra[0])
    _bbox_primeira = palavras[0][0]
    _x_esq_primeira = int(min((p[0] for p in _bbox_primeira)))
    if _x_esq_primeira <= _LARGURA_MAX_VAO_GLIFO:
        if _detectar_hifen_no_intervalo(_recorte_primeira_linha, 0, _x_esq_primeira):
            partes.append('-')
    partes.append(palavras[0][1])
    for i in range(1, len(palavras)):
        if linha_idx_por_palavra[i - 1] != linha_idx_por_palavra[i]:
            _idx_linha_anterior = linha_idx_por_palavra[i - 1]
            _recorte_linha_anterior = _recorte_da_linha(_idx_linha_anterior)
            _bbox_fim_linha = palavras[i - 1][0]
            _x_dir_fim_linha = int(max((p[0] for p in _bbox_fim_linha)))
            _x_lim_busca_hifen = min(_recorte_linha_anterior.shape[1], _x_dir_fim_linha + _LARGURA_MAX_VAO_GLIFO)
            if _x_lim_busca_hifen > _x_dir_fim_linha + 2 and _detectar_hifen_no_intervalo(_recorte_linha_anterior, _x_dir_fim_linha, _x_lim_busca_hifen):
                partes.append('-')
                _linhas_com_hifen_final_recuperado.add(_idx_linha_anterior)
                print(f'[OCR-DEBUG] hífen recuperado no final da linha {_idx_linha_anterior} antes da quebra', flush=True)
            partes.append(palavras[i][1])
            continue
        _recorte_linha_atual = _recorte_da_linha(linha_idx_por_palavra[i])
        _bbox_prev = palavras[i - 1][0]
        _bbox_atual = palavras[i][0]
        x_dir_prev = int(max((p[0] for p in _bbox_prev)))
        x_esq_atual = int(min((p[0] for p in _bbox_atual)))
        if x_esq_atual - x_dir_prev > _LARGURA_MAX_VAO_GLIFO:
            partes.append(palavras[i][1])
            continue
        if _detectar_hifen_no_intervalo(_recorte_linha_atual, x_dir_prev, x_esq_atual):
            partes.append('-')
        else:
            _pont = _detectar_pontuacao_curta_no_intervalo(_recorte_linha_atual, x_dir_prev, x_esq_atual)
            _prev_txt_pont = (palavras[i - 1][1] or '').strip()
            _prev_base_pont = re.sub('[^A-Za-zÀ-ÿ]', '', _prev_txt_pont)
            if _pont == ',' and len(_prev_base_pont) < 3:
                print(f'[OCR-DEBUG] vírgula geométrica rejeitada após palavra curta: {_prev_txt_pont!r}', flush=True)
                _pont = ''
            if _pont:
                partes.append(_pont)
            elif _detectar_glifo_curto_no_intervalo(_recorte_linha_atual, x_dir_prev, x_esq_atual):
                _txt_recuperado = _recuperar_texto_no_intervalo(reader, _recorte_linha_atual, x_dir_prev, x_esq_atual)
                if _txt_recuperado:
                    partes.append(_txt_recuperado)
        partes.append(palavras[i][1])
    _idx_ultima_linha = linha_idx_por_palavra[-1]
    _recorte_ultima_linha = _recorte_da_linha(_idx_ultima_linha)
    _bbox_ultima = palavras[-1][0]
    _x_dir_ultima = int(max((p[0] for p in _bbox_ultima)))
    _x_borda_direita = recorte.shape[1]
    _x_lim_busca_hifen_final = min(_recorte_ultima_linha.shape[1], _x_dir_ultima + _LARGURA_MAX_VAO_GLIFO)
    _hifen_final_recuperado = False
    if _x_lim_busca_hifen_final > _x_dir_ultima + 2 and _detectar_hifen_no_intervalo(_recorte_ultima_linha, _x_dir_ultima, _x_lim_busca_hifen_final):
        partes.append('-')
        _linhas_com_hifen_final_recuperado.add(_idx_ultima_linha)
        _hifen_final_recuperado = True
        print(f'[OCR-DEBUG] hífen recuperado no final da linha {_idx_ultima_linha}', flush=True)
    if not _hifen_final_recuperado and _x_borda_direita - _x_dir_ultima <= _LARGURA_MAX_VAO_GLIFO:
        _pont = _detectar_pontuacao_curta_no_intervalo(_recorte_ultima_linha, _x_dir_ultima, _x_borda_direita)
        if _pont == ',':
            _ult_txt_pont = (palavras[-1][1] or '').strip()
            _ult_base_pont = re.sub('[^A-Za-zÀ-ÿ]', '', _ult_txt_pont)
            if len(_ult_base_pont) < 3:
                print(f'[OCR-DEBUG] vírgula geométrica final rejeitada após palavra curta: {_ult_txt_pont!r}', flush=True)
                _pont = ''
        if _pont:
            partes.append(_pont)
        elif _detectar_glifo_curto_no_intervalo(_recorte_ultima_linha, _x_dir_ultima, _x_borda_direita):
            _txt_recuperado = _recuperar_texto_no_intervalo(reader, _recorte_ultima_linha, _x_dir_ultima, _x_borda_direita)
            if _txt_recuperado:
                partes.append(_txt_recuperado)
    _texto_completo = ' '.join(partes)
    _texto_completo = _reler_banda_ampliada_se_suspeita(reader, recorte, _texto_completo)
    if not retornar_linhas:
        return _texto_completo
    _linhas_out = []
    _idx_linha_atual = None
    _palavras_linha_atual = []
    for _pi, (_bbox, _txt) in enumerate(palavras):
        _idx_l = linha_idx_por_palavra[_pi]
        if _idx_linha_atual is None:
            _idx_linha_atual = _idx_l
        if _idx_l != _idx_linha_atual:
            _y0_l, _y1_l = linhas_y_range[_idx_linha_atual]
            _texto_linha_out = ' '.join(_palavras_linha_atual).strip()
            if _idx_linha_atual in _linhas_com_hifen_final_recuperado and (not _texto_linha_out.endswith('-')):
                _texto_linha_out = (_texto_linha_out + ' -').strip()
            _linhas_out.append({'texto': _texto_linha_out, 'altura': _y1_l - _y0_l})
            _palavras_linha_atual = []
            _idx_linha_atual = _idx_l
        _palavras_linha_atual.append(_txt)
    if _palavras_linha_atual:
        _y0_l, _y1_l = linhas_y_range[_idx_linha_atual]
        _texto_linha_out = ' '.join(_palavras_linha_atual).strip()
        if _idx_linha_atual in _linhas_com_hifen_final_recuperado and (not _texto_linha_out.endswith('-')):
            _texto_linha_out = (_texto_linha_out + ' -').strip()
        _linhas_out.append({'texto': _texto_linha_out, 'altura': _y1_l - _y0_l})
    return (_texto_completo, _linhas_out)

def _dividir_termos_relacionados_por_gap(reader, img_bgr, y_min: int, y_max: int) -> list:
    """Fallback pra linha de 'termos relacionados' (ex.: "Fórmula 1 ·
    Rock In Rio 2026 · Copa do Mundo 2026") quando o separador "·"/"•"
    some INTEIRO do texto reconhecido — não só vira um traço solto
    (caso já coberto pelo fallback de hífen em `_ocr_banda`), mas some
    junto com algum termo curto vizinho. Validado num anúncio real da
    BuyTicket Brasil: o "1" de "Fórmula 1" é um dígito isolado — mesmo
    problema do hífen (caixa curta/fina demais pro CRAFT abrir uma
    detecção só pra ele), só que sem o formato de traço fino que
    `_detectar_hifen_no_intervalo` reconhece, então aquele fallback
    nunca pega esse caso. Resultado real: "Fórmula 1 · Rock In Rio
    2026" saía como "Fórmula Rock In Rio 2026" grudado, sem nenhum
    separador sobrando pra guiar a quebra por regex de texto.

    Em vez de tentar recuperar o caractere perdido (o "1" e o "·" não
    voltam — o CRAFT simplesmente não abriu caixa pra eles), usa só a
    POSIÇÃO das palavras que FORAM reconhecidas: o vão horizontal onde
    ficava o separador (e o termo curto perdido, se houver) é bem mais
    largo que o espaço normal entre duas palavras do MESMO termo (ex.:
    o vão entre "Rock" e "In" é só um espaço; o vão onde sumiu "1 · " é
    várias vezes mais largo). Quebra nos vãos desproporcionalmente
    largos e devolve os termos resultantes — cada um pode perder um
    termo curto/separador que não voltou, mas pelo menos não fica mais
    grudado com o termo vizinho."""
    altura_total = img_bgr.shape[0]
    y0 = max(0, y_min - 4)
    y1 = min(altura_total, y_max + 5)
    recorte = img_bgr[y0:y1]
    resultado = reader.readtext(recorte, detail=1, width_ths=0.15, height_ths=0.5)
    if not resultado:
        return []
    palavras = [(bbox, (t or '').strip()) for bbox, t, _c in resultado if (t or '').strip()]
    if len(palavras) < 2:
        return []
    palavras.sort(key=lambda item: item[0][0][0])
    _caixas = [(int(min((p[0] for p in bbox))), int(max((p[0] for p in bbox))), txt) for bbox, txt in palavras]
    _vaos = [max(0, _caixas[i][0] - _caixas[i - 1][1]) for i in range(1, len(_caixas))]
    if not _vaos:
        return []
    _vaos_ordenados = sorted(_vaos)
    _melhor_idx = None
    _melhor_razao = 1.0
    for i in range(len(_vaos_ordenados) - 1):
        _den = max(1, _vaos_ordenados[i] + 1)
        _razao = (_vaos_ordenados[i + 1] + 1) / _den
        if _razao > _melhor_razao:
            _melhor_razao = _razao
            _melhor_idx = i
    if _melhor_idx is None:
        return []
    _limiar = _vaos_ordenados[_melhor_idx + 1]
    if _melhor_razao < 2.0 or _limiar < 8:
        return []
    _termos = []
    _termo_atual = [_caixas[0][2]]
    for i in range(1, len(_caixas)):
        if _vaos[i - 1] >= _limiar:
            _termos.append(' '.join(_termo_atual))
            _termo_atual = [_caixas[i][2]]
        else:
            _termo_atual.append(_caixas[i][2])
    _termos.append(' '.join(_termo_atual))
    return [t.strip() for t in _termos if t.strip()]

def _distancia_levenshtein(a: str, b: str) -> int:
    """Distância de edição clássica (nº mínimo de inserções/remoções/
    substituições de 1 caractere pra transformar `a` em `b`). Usada só
    por `_corrigir_nome_pagina_com_empresa` — implementada aqui (DP
    O(n*m) simples) pra não precisar de dependência externa (ex:
    `python-Levenshtein`) só por causa dessa comparação pontual."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    _linha_anterior = list(range(len(b) + 1))
    for i, _ca in enumerate(a, start=1):
        _linha_atual = [i]
        for j, _cb in enumerate(b, start=1):
            _custo = 0 if _ca == _cb else 1
            _linha_atual.append(min(_linha_anterior[j] + 1, _linha_atual[j - 1] + 1, _linha_anterior[j - 1] + _custo))
        _linha_anterior = _linha_atual
    return _linha_anterior[-1]

def _corrigir_nome_pagina_com_empresa(nome_ocr: str, empresa: str) -> str:
    """Substitui o nome da página lido pelo OCR pelo nome REAL da
    empresa já cadastrada no monitoramento, quando os dois são
    claramente a mesma marca — cobre erros de caractere que o EasyOCR
    comete no NOME (não na URL), ex: 'B' inicial lido como '3' na
    BuyTicket Brasil: '3uyTicket Brasil' → 'BuyTicket Brasil'.

    Diferente da URL (`_normalizar_url_exibida`), o nome da página não
    tem um formato fixo pra âncorar correções de caractere específicas
    (não tem "www."/TLD pra se guiar). Mas aqui a gente já SABE qual é
    o nome certo — é a própria empresa que o usuário está monitorando,
    vindo de cadastro, não de leitura de imagem. Em vez de adivinhar
    caractere por caractere, comparamos o texto lido com o nome
    cadastrado: se forem parecidos o bastante pra ser claramente a
    mesma marca com só 1-2 letras erradas de OCR, usamos o nome
    cadastrado (sempre correto).

    Critério: normaliza os dois (minúsculo, sem acento, sem pontuação)
    e mede a DISTÂNCIA DE EDIÇÃO (Levenshtein) entre eles — não a
    proporção de caracteres em comum (`difflib.SequenceMatcher`, testado
    antes e descartado): duas empresas DIFERENTES que só compartilham
    um pedaço do nome (ex: 'FanTicket Brasil' vs 'BuyTicket Brasil',
    ambas terminando em 'Ticket Brasil') batem um ratio de similaridade
    alto por SequenceMatcher mesmo sendo marcas distintas — o que
    trocaria o nome de uma empresa pelo da outra. Levenshtein não tem
    esse problema: mede erro caractere a caractere, e o mesmo par dá
    distância 3 (f≠b, a≠u, n≠y), bem acima do que 1-2 letras trocadas
    pelo OCR produziriam.

    Limite: aceita distância de até 15% do tamanho do maior nome
    normalizado, com piso de 2 caracteres (pra nomes curtos ainda
    tolerarem 1-2 erros de OCR) — calibrado pro caso real ('3uyticket-
    brasil' vs 'buyticketbrasil', distância 1) sem aceitar o caso
    'FanTicket'/'BuyTicket' acima (distância 3, sempre maior que o
    limite pra esse tamanho de nome).

    Também tenta uma segunda comparação removendo um TLD comum ("com",
    "com.br" etc.) GRUDADO no fim do texto lido, porque às vezes o
    EasyOCR não lê só o nome errado — ele funde o próprio nome com o
    domínio de baixo, tipo 'BuyTicket Brasil' virando 'ouyticketbrasil.
    com' (sem "www", sem espaço, com ".com" de brinde no final). Sem
    tirar esse TLD antes de comparar, a diferença de tamanho ('...com'
    tem ~3-6 caracteres a mais que o nome real) faria o texto nem
    entrar na comparação. Tentamos as duas versões (com e sem TLD) e
    ficamos com a que tiver a menor distância dentro do limite."""
    if not nome_ocr or not empresa:
        return nome_ocr

    def _norm_nome(s: str) -> str:
        s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
        return re.sub('[^a-z0-9]', '', s.lower())

    def _sem_tld_final(s: str) -> str:
        for _tld in ('combr', 'netbr', 'orgbr', 'iobr', 'shopbr', 'appbr', 'com', 'net', 'org', 'io', 'shop', 'app'):
            if s.endswith(_tld) and len(s) > len(_tld):
                return s[:-len(_tld)]
        return s
    _ocr_norm = _norm_nome(nome_ocr)
    _empresa_norm = _norm_nome(empresa)
    if not _ocr_norm or not _empresa_norm:
        return nome_ocr
    if _ocr_norm == _empresa_norm:
        return empresa
    _candidatos = {_ocr_norm, _sem_tld_final(_ocr_norm)}
    for _cand in _candidatos:
        if not _cand:
            continue
        if abs(len(_cand) - len(_empresa_norm)) <= 3:
            _maior = max(len(_cand), len(_empresa_norm))
            _limite = max(2, round(_maior * 0.15))
            if _distancia_levenshtein(_cand, _empresa_norm) <= _limite:
                return empresa
        if 4 <= len(_cand) < len(_empresa_norm) - 1:
            _limite_prefixo = max(1, round(len(_cand) * 0.2))
            for _offset in (0, 1):
                _prefixo = _empresa_norm[_offset:_offset + len(_cand)]
                if _prefixo and _distancia_levenshtein(_cand, _prefixo) <= _limite_prefixo:
                    return empresa
    return nome_ocr

def _melhor_nome_para_exibir(nome_ocr_linha: str, empresa: str) -> str:
    """Escolhe qual dos dois textos — o nome CADASTRADO da empresa
    (`empresa`) ou o texto que o OCR leu de verdade na imagem
    (`nome_ocr_linha`) — fica melhor pra EXIBIR no card, depois que já
    confirmamos (via `_corrigir_nome_pagina_com_empresa`) que os dois
    são a mesma marca.

    Normalmente `empresa` é a escolha certa — é a grafia oficial,
    cadastrada pelo usuário, e não depende de qualidade de imagem/OCR.
    Mas em alguns cadastros reais `empresa` vem SEM espaço e tudo
    minúsculo (ex: "buyticketbrasil" em vez de "BuyTicket Brasil" —
    provavelmente herdado de um campo tipo domínio/slug no cadastro),
    e nesses casos usar `empresa` direto piora o card em vez de
    melhorar: o OCR, mesmo lendo o cabeçalho do anúncio em CAIXA ALTA
    estilizada por design ("BUYTICKET BRASIL"), pelo menos preserva a
    separação de PALAVRA de verdade (o espaço), que `empresa` nem tem.

    Critério: se `empresa` tem espaço OU mistura maiúscula/minúscula,
    ela já está bem formatada — usa ela (fonte de verdade pra
    ortografia). Senão (tudo minúsculo/maiúsculo E sem nenhum espaço —
    sinal de slug/username, não de nome de exibição), prefere o texto
    lido da imagem, convertendo de CAIXA ALTA pra Title Case quando for
    o caso (cabeçalho de Display normalmente vem estilizado em
    maiúsculas), já que ele tem a informação de espaçamento que
    `empresa` perdeu."""
    if not empresa:
        return nome_ocr_linha or ''
    _empresa_bem_formatada = ' ' in empresa or (any((c.isupper() for c in empresa)) and any((c.islower() for c in empresa)))
    if _empresa_bem_formatada or not nome_ocr_linha:
        return empresa
    if nome_ocr_linha.isupper():
        return nome_ocr_linha.title()
    return nome_ocr_linha

def _extrair_titulo_descricao_por_altura(linhas: list) -> tuple:
    """Separa headline e descrição de anúncios Display pela altura REAL
    das caixas OCR.

    V12: em vez de escolher o primeiro/maior *salto* entre linhas, forma um
    BLOCO DE FONTE GRANDE a partir do começo. O headline de Display é sempre
    um conjunto consecutivo das linhas de maior fonte; a descrição começa
    quando a altura cai claramente abaixo desse grupo. Isso é mais estável
    para headlines de 1, 2 ou 3 linhas (ex.: ``Venda Seu Ingresso Aqui``,
    ``Ingressos Para Copa`` / ``Do Mundo`` e ``Volta, Bora`` / ``Viver Essa``
    / ``Emoção?``), sem promover a descrição de ~70% do tamanho do título.

    A referência é a maior altura observada nas linhas iniciais e uma linha
    continua no título quando mede pelo menos 80% dessa referência. A queda
    abaixo de 80% encerra o headline. Há uma tolerância de 76% apenas para uma
    linha CURTA imediatamente após outra linha de título, cobrindo pequenas
    diferenças de bbox causadas por acentos/descendentes sem puxar uma frase
    longa de descrição para o título.
    """
    if not linhas:
        return ('', [])
    linhas = [l for l in linhas if (l.get('texto') or '').strip()]
    if not linhas:
        return ('', [])
    if len(linhas) == 1:
        return (linhas[0]['texto'], [])
    if any((float(l.get('altura') or 0) <= 0 for l in linhas)):
        return (' '.join((l['texto'] for l in linhas)).strip(), [])
    alturas = [float(l.get('altura') or 0) for l in linhas]
    ref = max(alturas[:min(3, len(alturas))])
    corte = 1
    for i in range(1, len(linhas)):
        h = alturas[i]
        txt = (linhas[i].get('texto') or '').strip()
        razao = h / ref if ref > 0 else 0
        continua = razao >= 0.8
        if not continua and razao >= 0.76 and (len(txt) <= 22) and (corte >= 1):
            continua = True
        if not continua:
            break
        corte = i + 1
    if len(linhas) >= 3 and corte > 1:
        _txt0 = (linhas[0].get('texto') or '').strip()
        _txt1 = (linhas[1].get('texto') or '').strip()
        _h1 = alturas[1]
        _h2 = alturas[2]
        _descricao_wrap_coerente = _h1 > 0 and _h2 > 0 and (0.72 <= _h2 / _h1 <= 1.28)
        if 4 <= len(_txt0) <= 30 and len(_txt1) >= 32 and (len(_txt1) >= len(_txt0) * 1.45) and _descricao_wrap_coerente:
            print(f'[OCR-DEBUG] split-display-v34: descrição longa detectada após headline de 1 linha; forçando corte=1 (titulo={_txt0!r}, prox={_txt1!r})', flush=True)
            corte = 1
    if corte == len(linhas):
        for i in range(len(linhas) - 1):
            h0, h1 = (alturas[i], alturas[i + 1])
            if h0 > 0 and h1 / h0 <= 0.82:
                corte = i + 1
                break
    print('[OCR-DEBUG] split-display-v12 linhas=' + repr([(l.get('texto'), round(float(l.get('altura') or 0), 1)) for l in linhas]) + f' ref={ref:.1f} corte={corte}', flush=True)
    titulo = ' '.join((l['texto'] for l in linhas[:corte] if l.get('texto'))).strip()
    descricao = [l['texto'] for l in linhas[corte:] if l.get('texto')]
    return (titulo, descricao)

def _detectar_grade_cards_google_ads(img_bgr, reader, empresa: str=None):
    """Detecta o formato de anúncio em GRADE/CATÁLOGO do Google Ads.

    Esse layout é estruturalmente diferente do anúncio simples: há vários
    cards independentes (normalmente 2 colunas), cada um com uma imagem,
    um título logo ABAIXO da imagem e um CTA próprio (ex.: "Compre Agora").
    Tentar passar a captura inteira pelo parser linear de bandas mistura
    texto de cards diferentes na mesma faixa Y e também deixa texto que
    está DENTRO das artes vazar para título/CTA.

    Estratégia:
      1) só tenta este caminho em capturas bem mais altas que largas;
      2) roda uma leitura global com bboxes e procura 3+ ocorrências de
         um mesmo CTA do tipo "Compre Agora";
      3) para cada CTA, busca APENAS as caixas de texto imediatamente
         acima dele, na mesma coluna, numa janela curta — essa região é
         exatamente onde fica o título externo do card. Texto interno da
         arte fica mais distante e é ignorado;
      4) devolve cada card como um item de `sitelinks`, preservando a
         estrutura atual do JSON sem misturar todos os cards num único
         título/descrição/CTA.

    Retorna None quando não parece grade de cards.
    """
    import re as _re_grade
    from difflib import SequenceMatcher as _SM_grade
    h, w = img_bgr.shape[:2]
    if h < w * 1.45:
        return None
    try:
        _ocr = reader.readtext(img_bgr, detail=1, paragraph=False, width_ths=0.7, height_ths=0.5, text_threshold=0.55, low_text=0.35, link_threshold=0.35)
    except Exception as e:
        print(f'[OCR-DEBUG] grade-cards: leitura global falhou: {e!r}', flush=True)
        return None

    def _norm(txt):
        txt = (txt or '').strip().lower()
        txt = _re_grade.sub('[^a-z0-9áàâãéêíóôõúç ]+', ' ', txt)
        return _re_grade.sub('\\s+', ' ', txt).strip()

    def _bbox_info(item):
        bbox, txt, conf = item
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        return {'bbox': bbox, 'texto': (txt or '').strip(), 'conf': float(conf or 0), 'x0': min(xs), 'x1': max(xs), 'y0': min(ys), 'y1': max(ys), 'xc': (min(xs) + max(xs)) / 2, 'yc': (min(ys) + max(ys)) / 2}
    caixas = [_bbox_info(x) for x in _ocr if x and len(x) >= 3 and (x[1] or '').strip()]
    if not caixas:
        return None
    ctas = []
    for c in caixas:
        n = _norm(c['texto'])
        sim = _SM_grade(None, n, 'compre agora').ratio() if n else 0
        if c['yc'] > h * 0.18 and (n == 'compre agora' or sim >= 0.78 or ('compre' in n and 'agora' in n)):
            ctas.append(c)
    ctas.sort(key=lambda c: (c['yc'], c['xc']))
    _ctas_dedup = []
    for c in ctas:
        if any((abs(c['xc'] - d['xc']) < 20 and abs(c['yc'] - d['yc']) < 20 for d in _ctas_dedup)):
            continue
        _ctas_dedup.append(c)
    ctas = _ctas_dedup
    if len(ctas) < 3:
        return None
    janela_titulo = max(70, min(145, int(h * 0.062)))
    cards = []
    debug = []
    for i, cta in enumerate(ctas):
        largura_cta = max(1.0, cta['x1'] - cta['x0'])
        margem_x = max(80.0, largura_cta * 0.8)
        x_min = max(0.0, cta['x0'] - margem_x)
        x_max = min(float(w), cta['x1'] + margem_x)
        candidatos = []
        for b in caixas:
            if b is cta:
                continue
            if b['y1'] > cta['y0'] + 3:
                continue
            gap = cta['y0'] - b['y1']
            if gap < 4 or gap > janela_titulo:
                continue
            if not x_min <= b['xc'] <= x_max:
                continue
            overlap = max(0.0, min(b['x1'], x_max) - max(b['x0'], x_min))
            if overlap < min(20.0, (b['x1'] - b['x0']) * 0.25):
                continue
            n = _norm(b['texto'])
            if not n or 'compre agora' in n:
                continue
            if empresa and _norm(empresa).replace(' ', '') in n.replace(' ', ''):
                continue
            if '.com' in n or 'http' in n or 'www' in n:
                continue
            candidatos.append(b)
        if not candidatos:
            continue
        candidatos.sort(key=lambda b: (b['yc'], b['x0']))
        candidatos_por_proximidade = sorted(candidatos, key=lambda b: b['y1'], reverse=True)
        bloco = []
        limite_superior = cta['y0']
        for b in candidatos_por_proximidade:
            gap_bloco = limite_superior - b['y1']
            if bloco and gap_bloco > max(22, int(h * 0.014)):
                break
            bloco.append(b)
            limite_superior = min(limite_superior, b['y0'])
        bloco.sort(key=lambda b: (b['yc'], b['x0']))
        linhas = []
        for b in bloco:
            colocado = False
            alt = max(8.0, b['y1'] - b['y0'])
            for linha in linhas:
                if abs(b['yc'] - linha['yc']) <= max(8.0, alt * 0.45):
                    linha['itens'].append(b)
                    linha['yc'] = sum((x['yc'] for x in linha['itens'])) / len(linha['itens'])
                    colocado = True
                    break
            if not colocado:
                linhas.append({'yc': b['yc'], 'itens': [b]})
        linhas.sort(key=lambda l: l['yc'])
        partes = []
        for linha in linhas:
            itens = sorted(linha['itens'], key=lambda b: b['x0'])
            txt = ' '.join((x['texto'] for x in itens if x['texto'])).strip()
            txt = _limpar_pontuacao_ocr(txt)
            if txt:
                partes.append(txt)
        titulo = ' '.join(partes).strip()
        titulo = _re_grade.sub('\\s{2,}', ' ', titulo)
        if not titulo:
            continue
        if any((_norm(x['titulo']) == _norm(titulo) for x in cards)):
            continue
        cards.append({'titulo': titulo, 'descricao': 'Compre Agora'})
        debug.append({'idx': len(debug), 'classe': 'grade-card', 'sep_antes': False, 'texto': f'{titulo} | Compre Agora', 'decisao': 'grade de cards → título externo associado ao CTA da mesma coluna', 'y_min': int(min([b['y0'] for b in bloco] + [cta['y0']])), 'y_max': int(cta['y1']), 'x_min_favicon': 0})
    if len(cards) < 3:
        return None
    print(f'[OCR-DEBUG] grade-cards detectada: {len(cards)} card(s) -> {cards!r}', flush=True)
    return {'titulo': '', 'descricao': '', 'url_exibida': empresa or '', 'url_final': '', 'cta': '', 'cta_subtitulo': '', 'sitelinks': cards, '_debug_bandas': debug, '_layout_ocr': 'grade_cards'}

def _detectar_display_foto_central(img_bgr, reader, empresa: str=None):
    """V124 — Display com cabeçalho em cima, FOTO CENTRAL grande e texto embaixo.

    Estrutura típica:
        [avatar] Nome da empresa
        [        FOTO / ARTE GRANDE        ]
        Título do anúncio
        CTA

    Exemplo real:
        FunBuyNet
        [foto show]
        Oasis Tickets - FunBuyNet
        Abrir

    A foto central é ignorada. O detector usa a geometria vertical do OCR:
    precisa existir um cabeçalho no topo e um grande vazio textual entre ele
    e o bloco inferior. Assim não confunde esse formato com anúncios de Busca.
    """
    import re as _re_fc
    if img_bgr is None or getattr(img_bgr, 'size', 0) == 0:
        return None
    h, w = img_bgr.shape[:2]
    if h < 320 or w < 360:
        return None
    _ratio = w / max(float(h), 1.0)
    if not 0.82 <= _ratio <= 1.55:
        return None
    try:
        _ocr = reader.readtext(img_bgr, detail=1, paragraph=False, width_ths=0.55, height_ths=0.55, text_threshold=0.4, low_text=0.25, link_threshold=0.25)
    except Exception as _exc:
        print(f'[OCR-DEBUG] display-foto-central: OCR falhou: {_exc!r}', flush=True)
        return None
    _caixas = []
    for _item in _ocr or []:
        if not _item or len(_item) < 3:
            continue
        _bbox, _txt, _conf = _item
        _txt = _limpar_pontuacao_ocr((_txt or '').strip())
        if not _txt:
            continue
        _xs = [float(p[0]) for p in _bbox]
        _ys = [float(p[1]) for p in _bbox]
        _caixas.append({'texto': _txt, 'x0': min(_xs), 'x1': max(_xs), 'y0': min(_ys), 'y1': max(_ys), 'xc': (min(_xs) + max(_xs)) / 2.0, 'yc': (min(_ys) + max(_ys)) / 2.0, 'altura': max(1.0, max(_ys) - min(_ys))})
    if len(_caixas) < 3:
        return None
    _caixas.sort(key=lambda c: (c['yc'], c['x0']))
    _linhas = []
    for _c in _caixas:
        _alocada = False
        for _l in _linhas:
            _tol = max(8.0, min(_c['altura'], _l['altura']) * 0.55)
            if abs(_c['yc'] - _l['yc']) <= _tol:
                _l['itens'].append(_c)
                _l['yc'] = sum((x['yc'] for x in _l['itens'])) / len(_l['itens'])
                _l['altura'] = max(_l['altura'], _c['altura'])
                _alocada = True
                break
        if not _alocada:
            _linhas.append({'yc': _c['yc'], 'altura': _c['altura'], 'itens': [_c]})
    _linhas.sort(key=lambda l: l['yc'])
    for _l in _linhas:
        _l['itens'].sort(key=lambda c: c['x0'])
        _l['texto'] = _limpar_pontuacao_ocr(' '.join((c['texto'] for c in _l['itens'])).strip())
        _l['x0'] = min((c['x0'] for c in _l['itens']))
        _l['x1'] = max((c['x1'] for c in _l['itens']))
        _l['xc'] = (_l['x0'] + _l['x1']) / 2.0
    _linhas = [l for l in _linhas if l.get('texto')]
    if len(_linhas) < 3:
        return None

    def _norm(_s):
        return _re_fc.sub('[^a-z0-9]', '', str(_s or '').lower())
    _emp_norm = _norm(empresa)
    _idx_header = None
    for _i, _l in enumerate(_linhas):
        if _l['yc'] > h * 0.24:
            break
        _n = _norm(_l['texto'])
        if _emp_norm and _n and (_n == _emp_norm or _emp_norm in _n or _n in _emp_norm):
            _idx_header = _i
            break
    if _idx_header is None:
        return None
    _header = _linhas[_idx_header]
    _idx_bloco_inferior = None
    _maior_gap = 0.0
    for _i in range(_idx_header + 1, len(_linhas)):
        _prev = _linhas[_i - 1]
        _cur = _linhas[_i]
        _gap = float(_cur['yc'] - _prev['yc'])
        if _gap > _maior_gap:
            _maior_gap = _gap
        if _gap >= h * 0.28 and _cur['yc'] >= h * 0.68:
            _idx_bloco_inferior = _i
            break
    if _idx_bloco_inferior is None:
        return None
    _inferiores = _linhas[_idx_bloco_inferior:]
    if not _inferiores:
        return None
    _rx_cta = _re_fc.compile('^(?:abrir|saiba\\s*mais|compre\\s*agora|comprar\\s*agora|acesse|acessar|ver\\s*mais|conferir|comprar|reservar)(?:\\s*[>›»→❯➜])?$', _re_fc.IGNORECASE)
    _cta = ''
    _conteudo = []
    for _l in _inferiores:
        _txt = (_l['texto'] or '').strip()
        _txt_cta = _re_fc.sub('\\s*[>›»→❯➜]+\\s*$', '', _txt).strip()
        if _rx_cta.match(_txt):
            if not _cta:
                _cta = _txt_cta
            continue
        _conteudo.append({'texto': _txt, 'altura': _l['altura'], 'yc': _l['yc']})
    if not _conteudo:
        return None
    _titulo, _desc_linhas = _extrair_titulo_descricao_por_altura([{'texto': l['texto'], 'altura': l['altura']} for l in _conteudo])
    _titulo = _limpar_pontuacao_ocr(_titulo or '')
    _descricao = ' '.join((_limpar_pontuacao_ocr(x) for x in _desc_linhas or [] if x)).strip()
    if not _titulo:
        return None
    if not _cta:
        return None
    _debug = [{'idx': 0, 'classe': 'display-foto-central', 'sep_antes': False, 'texto': f"{empresa or ''} | {_titulo} | {_descricao} | {_cta}".strip(' |'), 'decisao': 'Display com cabeçalho superior + foto central grande + bloco inferior → foto ignorada; nome da empresa tratado como cabeçalho; título extraído abaixo da foto; CTA identificado separadamente', 'y_min': 0, 'y_max': int(h), 'x_min_favicon': 0}]
    print(f'[OCR-DEBUG] display-foto-central detectado gap={_maior_gap:.1f}px/{h} empresa={empresa!r} titulo={_titulo!r} cta={_cta!r}', flush=True)
    return {'titulo': _titulo, 'descricao': _descricao, 'url_exibida': empresa or '', 'url_final': '', 'cta': _cta, 'cta_subtitulo': '', 'sitelinks': [], '_debug_bandas': _debug, '_layout_ocr': 'display_foto_central'}

def _detectar_display_imagem_topo_card_rodape(img_bgr, reader, empresa: str=None):
    """V116 — detecta Display com FOTO grande em cima + card textual no rodapé.

    Exemplo real:
      [ foto/arte ocupando ~2/3 superiores ]
      [ headline                                     ]
      [ avatar/logo ] [ descrição ] [ botão CTA     ]

    Regras:
      - ignora completamente a foto superior;
      - usa o nome cadastrado da empresa como cabeçalho;
      - ignora texto dentro do avatar/logo;
      - separa headline, descrição e CTA pela geometria do rodapé.

    Retorna None quando a geometria não é forte o suficiente, preservando os
    parsers já existentes.
    """
    import cv2 as _cv2_top
    import numpy as _np_top
    import re as _re_top
    if img_bgr is None or getattr(img_bgr, 'size', 0) == 0:
        return None
    h, w = img_bgr.shape[:2]
    if h < 320 or w < 420:
        return None
    _ratio = w / max(float(h), 1.0)
    if not 0.9 <= _ratio <= 1.55:
        return None
    try:
        _gray = _cv2_top.cvtColor(img_bgr, _cv2_top.COLOR_BGR2GRAY)
    except Exception:
        return None
    _row_mean = _gray.mean(axis=1)
    _ini_y = int(h * 0.5)
    _fim_y = int(h * 0.82)
    _faixa = max(5, int(h * 0.012))
    _melhor = None
    for _y in range(_ini_y, _fim_y):
        _acima = _row_mean[max(0, _y - _faixa):_y]
        _abaixo = _row_mean[_y:min(h, _y + _faixa)]
        if _acima.size == 0 or _abaixo.size == 0:
            continue
        _m_acima = float(_acima.mean())
        _m_abaixo = float(_abaixo.mean())
        _score = _m_abaixo - _m_acima
        if _melhor is None or _score > _melhor[0]:
            _melhor = (_score, _y, _m_acima, _m_abaixo)
    if not _melhor:
        return None
    _score, _seam_y, _m_acima, _m_abaixo = _melhor
    _rodape = _gray[_seam_y:, :]
    _foto = _gray[:max(1, _seam_y - _faixa), :]
    if _rodape.size == 0 or _foto.size == 0:
        return None
    _rodape_mean = float(_rodape.mean())
    _foto_std = float(_foto.std())
    _foto_frac_quase_branca = float((_foto >= 245).mean())
    _foto_mean = float(_foto.mean())
    if not (_score >= 45 and _rodape_mean >= 205 and (_foto_std >= 35) and (_foto_mean <= 190) and (_foto_frac_quase_branca <= 0.35) and (float((_foto <= 100).mean()) >= 0.12) and (0.54 <= _seam_y / float(h) <= 0.78)):
        return None
    _y0 = min(h - 1, _seam_y + 2)
    _crop = img_bgr[_y0:h, :]
    if _crop.size == 0:
        return None
    try:
        _ocr = reader.readtext(_crop, detail=1, paragraph=False, width_ths=0.6, height_ths=0.55, text_threshold=0.4, low_text=0.25, link_threshold=0.25)
    except Exception as _exc:
        print(f'[OCR-DEBUG] top-card: OCR do rodapé falhou: {_exc!r}', flush=True)
        return None
    _caixas = []
    for _item in _ocr or []:
        if not _item or len(_item) < 3:
            continue
        _bbox, _txt, _conf = _item
        _txt = _limpar_pontuacao_ocr((_txt or '').strip())
        if not _txt:
            continue
        _xs = [float(p[0]) for p in _bbox]
        _ys = [float(p[1]) for p in _bbox]
        _caixas.append({'texto': _txt, 'conf': float(_conf or 0), 'x0': min(_xs), 'x1': max(_xs), 'y0': min(_ys), 'y1': max(_ys), 'xc': (min(_xs) + max(_xs)) / 2.0, 'yc': (min(_ys) + max(_ys)) / 2.0, 'altura': max(1.0, max(_ys) - min(_ys))})
    if len(_caixas) < 3:
        return None
    _caixas.sort(key=lambda c: (c['yc'], c['x0']))
    _linhas = []
    for _c in _caixas:
        _alocada = False
        for _l in _linhas:
            _tol = max(7.0, min(_c['altura'], _l['altura']) * 0.55)
            if abs(_c['yc'] - _l['yc']) <= _tol:
                _l['itens'].append(_c)
                _l['yc'] = sum((x['yc'] for x in _l['itens'])) / len(_l['itens'])
                _l['altura'] = max(_l['altura'], _c['altura'])
                _alocada = True
                break
        if not _alocada:
            _linhas.append({'yc': _c['yc'], 'altura': _c['altura'], 'itens': [_c]})
    _linhas.sort(key=lambda l: l['yc'])
    for _l in _linhas:
        _l['itens'].sort(key=lambda c: c['x0'])
        _l['texto'] = _limpar_pontuacao_ocr(' '.join((c['texto'] for c in _l['itens'])).strip())
        _l['x0'] = min((c['x0'] for c in _l['itens']))
        _l['x1'] = max((c['x1'] for c in _l['itens']))
        _l['xc'] = (_l['x0'] + _l['x1']) / 2.0
    _rx_cta = _re_top.compile('^(?:abrir|saiba\\s*mais|compre\\s*agora|comprar\\s*agora|acesse|acessar|ver\\s*mais|conferir|comprar|reservar)(?:\\s*[>›»→❯➜])?$', _re_top.IGNORECASE)

    def _norm_empresa(_s):
        return _re_top.sub('[^a-z0-9]', '', str(_s or '').lower())
    _empresa_norm = _norm_empresa(empresa)
    _cta = ''
    _conteudo = []
    _avatar_ignorados = []

    def _ocr_texto_regiao(_img_regiao):
        if _img_regiao is None or getattr(_img_regiao, 'size', 0) == 0:
            return ''
        try:
            _itens_regiao = reader.readtext(_img_regiao, detail=1, paragraph=False, width_ths=0.55, height_ths=0.55, text_threshold=0.35, low_text=0.2, link_threshold=0.2)
        except Exception:
            return ''
        _partes_regiao = []
        for _item_regiao in _itens_regiao or []:
            if not _item_regiao or len(_item_regiao) < 3:
                continue
            _bbox_r, _txt_r, _conf_r = _item_regiao
            _txt_r = _limpar_pontuacao_ocr((_txt_r or '').strip())
            if not _txt_r:
                continue
            _ys_r = [float(p[1]) for p in _bbox_r]
            _xs_r = [float(p[0]) for p in _bbox_r]
            _partes_regiao.append((min(_ys_r), min(_xs_r), _txt_r))
        _partes_regiao.sort(key=lambda x: (x[0], x[1]))
        return ' '.join((x[2] for x in _partes_regiao)).strip()
    _h_crop = _crop.shape[0]
    _w_crop = _crop.shape[1]
    _desc_x0 = int(_w_crop * 0.2)
    _desc_x1 = int(_w_crop * 0.62)
    _desc_y0 = int(_h_crop * 0.3)
    _descricao_geometrica = _ocr_texto_regiao(_crop[_desc_y0:_h_crop, _desc_x0:_desc_x1])
    _cta_x0 = int(_w_crop * 0.61)
    _cta_y0 = int(_h_crop * 0.28)
    _cta_geometrico_bruto = _ocr_texto_regiao(_crop[_cta_y0:_h_crop, _cta_x0:_w_crop])
    _m_cta_geo = _re_top.search('(?i)\\b(abrir|saiba\\s*mais|compre\\s*agora|comprar\\s*agora|acesse|acessar|ver\\s*mais|conferir|comprar|reservar)\\b', _cta_geometrico_bruto or '')
    if _m_cta_geo:
        _cta = _m_cta_geo.group(1).strip()
    for _l in _linhas:
        _txt = (_l.get('texto') or '').strip()
        if not _txt:
            continue
        _txt_cta = _re_top.sub('\\s*[>›»→❯➜]+\\s*$', '', _txt).strip()
        if _rx_cta.match(_txt) and _l['xc'] >= w * 0.55 and (_l['yc'] >= _crop.shape[0] * 0.35):
            if not _cta:
                _cta = _txt_cta
            continue
        if _cta:
            _txt = _re_top.sub('(?i)\\b' + _re_top.escape(_cta) + '\\b\\s*[>›»→❯➜]*', '', _txt).strip()
            if not _txt:
                continue
            _l = dict(_l)
            _l['texto'] = _txt
        _eh_avatar = _l['xc'] <= w * 0.28 and _l['yc'] >= _crop.shape[0] * 0.32 and _empresa_norm and (_norm_empresa(_txt) == _empresa_norm or _empresa_norm in _norm_empresa(_txt) or _norm_empresa(_txt) in _empresa_norm)
        if _eh_avatar:
            _avatar_ignorados.append(_txt)
            continue
        _conteudo.append(_l)
    if len(_conteudo) < 2:
        return None
    _conteudo.sort(key=lambda l: l['yc'])
    _headline = _conteudo[0]
    if _headline['yc'] > _crop.shape[0] * 0.42:
        return None
    _titulo = _limpar_pontuacao_ocr(_headline['texto'])
    _desc_linhas = []
    for _l in _conteudo[1:]:
        if _l['xc'] >= w * 0.64:
            continue
        _desc_linhas.append(_l['texto'])
    _descricao = ' '.join(_desc_linhas).strip()
    if _descricao_geometrica:
        _descricao_geo_limpa = _descricao_geometrica
        if empresa:
            _emp_rx = _re_top.escape(str(empresa).strip())
            _descricao_geo_limpa = _re_top.sub(f'(?i)^\\s*[\\[\\(]?[A-Za-z0-9._-]*{_emp_rx}[A-Za-z0-9._-]*[\\]\\)]?\\s+', '', _descricao_geo_limpa).strip()
        if _cta:
            _descricao_geo_limpa = _re_top.sub('(?i)\\b' + _re_top.escape(_cta) + '\\b\\s*[>›»→❯➜]*', '', _descricao_geo_limpa).strip()
        if _descricao_geo_limpa:
            _descricao = _descricao_geo_limpa
    if not _titulo or not (_descricao or _cta):
        return None
    _debug = [{'idx': 0, 'classe': 'display-top-card', 'sep_antes': False, 'texto': f'{_titulo} | {_descricao} | {_cta}'.strip(' |'), 'decisao': 'Display com foto superior REAL + card inferior → foto ignorada; headline extraído do topo do rodapé; avatar/logo ignorado; descrição extraída por crop geométrico da coluna central; CTA extraído por crop geométrico independente do botão à direita', 'y_min': int(_seam_y), 'y_max': int(h), 'x_min_favicon': 0}]
    print(f'[OCR-DEBUG] display-top-card detectado seam={_seam_y}/{h} score={_score:.1f} foto_mean={_foto_mean:.1f} foto_branca={_foto_frac_quase_branca:.2%} foto_escura={float((_foto <= 100).mean()):.2%} avatar_ignorado={_avatar_ignorados!r} titulo={_titulo!r} descricao={_descricao!r} cta={_cta!r}', flush=True)
    return {'titulo': _titulo, 'descricao': _descricao, 'url_exibida': empresa or '', 'url_final': '', 'cta': _cta, 'cta_subtitulo': '', 'sitelinks': [], '_debug_bandas': _debug, '_layout_ocr': 'display_top_card'}

def _detectar_card_split_google_ads(img_bgr, reader, empresa: str=None):
    """Detecta anúncio gráfico em DUAS COLUNAS.

    Padrão real:
      - painel/arte/foto à esquerda;
      - card branco à direita;
      - avatar/logo grande no topo direito;
      - título + descrição + CTA no painel direito.

    O painel esquerdo é tratado como ARTE e ignorado por completo. Isso evita
    que textos internos da foto/peça ("Comprar ou Vender Ingressos") vazem para
    título/descrição. Um caractere grande isolado no topo direito (ex.: "F") é
    tratado como avatar, não como conteúdo.

    Retorna None quando a geometria não é suficientemente forte para classificar
    o anúncio como split-card.
    """
    import cv2 as _cv2_split
    import numpy as _np_split
    import re as _re_split
    if img_bgr is None or getattr(img_bgr, 'size', 0) == 0:
        return None
    h, w = img_bgr.shape[:2]
    if h < 220 or w < 360:
        return None
    _ratio = w / max(1.0, float(h))
    if not 0.9 <= _ratio <= 2.2:
        return None
    try:
        _gray = _cv2_split.cvtColor(img_bgr, _cv2_split.COLOR_BGR2GRAY)
    except Exception:
        return None
    _col_mean = _gray.mean(axis=0)
    _ini_x = int(w * 0.28)
    _fim_x = int(w * 0.68)
    _faixa = max(6, int(w * 0.015))
    _melhor = None
    for _x in range(_ini_x, _fim_x):
        _esq = _col_mean[max(0, _x - _faixa):_x]
        _dir = _col_mean[_x:min(w, _x + _faixa)]
        if _esq.size == 0 or _dir.size == 0:
            continue
        _m_esq = float(_esq.mean())
        _m_dir = float(_dir.mean())
        _score = _m_dir - _m_esq
        if _melhor is None or _score > _melhor[0]:
            _melhor = (_score, _x, _m_esq, _m_dir)
    if not _melhor:
        return None
    _score, _seam_x, _media_esq_borda, _media_dir_borda = _melhor
    _painel_dir = _gray[:, min(w - 1, _seam_x + _faixa):]
    _painel_esq = _gray[:, :max(1, _seam_x - _faixa)]
    if _painel_dir.size == 0 or _painel_esq.size == 0:
        return None
    _media_dir = float(_painel_dir.mean())
    _media_esq = float(_painel_esq.mean())
    if not (_score >= 75 and _media_dir >= 215 and (_media_dir - _media_esq >= 55) and (0.34 <= _seam_x / float(w) <= 0.62)):
        return None
    _x0 = min(w - 1, _seam_x + max(8, int(w * 0.025)))
    _x1 = max(_x0 + 1, w - max(5, int(w * 0.012)))
    _crop = img_bgr[:, _x0:_x1]
    if _crop.size == 0:
        return None
    try:
        _ocr = reader.readtext(_crop, detail=1, paragraph=False, width_ths=0.55, height_ths=0.55, text_threshold=0.4, low_text=0.25, link_threshold=0.25)
    except Exception as _exc:
        print(f'[OCR-DEBUG] split-card: OCR do painel direito falhou: {_exc!r}', flush=True)
        return None
    _caixas = []
    for _item in _ocr or []:
        if not _item or len(_item) < 3:
            continue
        _bbox, _txt, _conf = _item
        _txt = _limpar_pontuacao_ocr((_txt or '').strip())
        if not _txt:
            continue
        _xs = [float(p[0]) for p in _bbox]
        _ys = [float(p[1]) for p in _bbox]
        _altura = max(_ys) - min(_ys)
        _caixas.append({'texto': _txt, 'conf': float(_conf or 0), 'x0': min(_xs), 'x1': max(_xs), 'y0': min(_ys), 'y1': max(_ys), 'yc': (min(_ys) + max(_ys)) / 2, 'altura': max(1.0, _altura)})
    if len(_caixas) < 2:
        return None
    _caixas.sort(key=lambda c: (c['yc'], c['x0']))
    _linhas = []
    for _c in _caixas:
        _alocada = False
        for _l in _linhas:
            _tol = max(8.0, min(_c['altura'], _l['altura']) * 0.55)
            if abs(_c['yc'] - _l['yc']) <= _tol:
                _l['itens'].append(_c)
                _l['yc'] = sum((x['yc'] for x in _l['itens'])) / len(_l['itens'])
                _l['altura'] = max(_l['altura'], _c['altura'])
                _alocada = True
                break
        if not _alocada:
            _linhas.append({'yc': _c['yc'], 'altura': _c['altura'], 'itens': [_c]})
    _linhas.sort(key=lambda l: l['yc'])
    for _l in _linhas:
        _l['itens'].sort(key=lambda c: c['x0'])
        _l['texto'] = _limpar_pontuacao_ocr(' '.join((c['texto'] for c in _l['itens'])).strip())
    _alturas_validas = [l['altura'] for l in _linhas if l.get('texto')]
    _med_alt = float(_np_split.median(_alturas_validas)) if _alturas_validas else 0.0
    _conteudo = []
    _avatar_ignorados = []
    _cta = ''
    _cta_y = -1.0
    _rx_cta_split = _re_split.compile('^(?:abrir|compre\\s*agora|comprar\\s*agora|saiba\\s*mais|acessar|acesse|ver\\s*mais|conferir|comprar|reservar|inscreva-?se|cadastre-?se)$', _re_split.IGNORECASE)
    for _l in _linhas:
        _txt = (_l.get('texto') or '').strip()
        if not _txt:
            continue
        _compacto = _re_split.sub('[^A-Za-zÀ-ÿ0-9]', '', _txt)
        _eh_avatar = _l['yc'] < h * 0.42 and len(_compacto) <= 2 and (_l['altura'] >= max(26.0, _med_alt * 1.45))
        if _eh_avatar:
            _avatar_ignorados.append(_txt)
            continue
        _txt_cta_split = _re_split.sub('\\s*[>›»→❯➜➤►]+\\s*$', '', _txt).strip()
        if _rx_cta_split.match(_txt_cta_split) and _l['yc'] > h * 0.45:
            if _l['yc'] > _cta_y:
                _cta = _txt_cta_split
                _cta_y = _l['yc']
            continue
        _conteudo.append({'texto': _txt, 'altura': _l['altura'], 'yc': _l['yc']})
    if not _conteudo:
        return None
    if _cta_y > 0:
        _conteudo = [l for l in _conteudo if l['yc'] < _cta_y - 5]
    if not _conteudo:
        return None
    _conteudo.sort(key=lambda l: l['yc'])
    _titulo, _descricao_linhas = _extrair_titulo_descricao_por_altura([{'texto': l['texto'], 'altura': l['altura']} for l in _conteudo])
    _titulo = _limpar_pontuacao_ocr(_titulo or '')
    _descricao_linhas = [_limpar_pontuacao_ocr(x) for x in _descricao_linhas or [] if x]
    _descricao = ' '.join(_descricao_linhas).strip()
    if not _titulo or not (_descricao or _cta):
        return None
    _debug = [{'idx': 0, 'classe': 'split-card', 'sep_antes': False, 'texto': f'{_titulo} | {_descricao} | {_cta}'.strip(' |'), 'decisao': 'anúncio gráfico em duas colunas → painel esquerdo/foto ignorado; avatar grande isolado ignorado; título/descrição separados por altura no painel direito; CTA identificado no botão', 'y_min': 0, 'y_max': int(h), 'x_min_favicon': int(_seam_x)}]
    print(f'[OCR-DEBUG] split-card detectado seam={_seam_x}/{w} score={_score:.1f} avatar_ignorado={_avatar_ignorados!r} titulo={_titulo!r} cta={_cta!r}', flush=True)
    return {'titulo': _titulo, 'descricao': _descricao, 'url_exibida': empresa or '', 'url_final': '', 'cta': _cta, 'cta_subtitulo': '', 'sitelinks': [], '_debug_bandas': _debug, '_layout_ocr': 'split_card'}

def _estruturar_anuncio_google_ads(img_bgr, reader, empresa: str=None):
    """Usa as bandas de cor pra separar um anúncio de TEXTO do Google
    Ads (Rede de Pesquisa) nos campos titulo/descricao/url_exibida/cta/
    sitelinks, sem depender de nenhuma IA generativa. Cobre tanto o
    anúncio simples (título + descrição + URL) quanto o anúncio com
    sitelinks expandidos (vários pares título+descrição depois do
    anúncio principal, separados por linhas divisórias finas).

    `empresa`, quando informado, é o nome da empresa já cadastrada no
    monitoramento do usuário — usado só pra corrigir o NOME DA PÁGINA
    do cabeçalho (ver `_corrigir_nome_pagina_com_empresa`) quando o OCR
    erra 1-2 caracteres da marca. Opcional: se não vier (ou vier None),
    o nome da página simplesmente não passa por essa correção extra,
    igual ao comportamento antigo.

    Devolve None quando a imagem não tem NENHUM texto detectável (nem
    título nem descrição) — nesse caso quem chama deve cair no fallback
    de texto bruto, porque provavelmente não é um anúncio de texto
    padrão (ex: anúncio de Display/imagem)."""
    _display_foto_central = _detectar_display_foto_central(img_bgr, reader, empresa=empresa)
    if _display_foto_central is not None:
        return _display_foto_central
    _display_top_card = _detectar_display_imagem_topo_card_rodape(img_bgr, reader, empresa=empresa)
    if _display_top_card is not None:
        return _display_top_card
    _split_card = _detectar_card_split_google_ads(img_bgr, reader, empresa=empresa)
    if _split_card is not None:
        return _split_card
    _grade = _detectar_grade_cards_google_ads(img_bgr, reader, empresa=empresa)
    if _grade is not None:
        return _grade
    bandas = _detectar_bandas_texto(img_bgr)
    bandas_texto = []
    _sep_pendente = False
    for _b in bandas:
        if _b['classe'] == 'separador':
            _sep_pendente = True
            continue
        _bt = dict(_b)
        _bt['sep_antes'] = _sep_pendente
        bandas_texto.append(_bt)
        _sep_pendente = False
    if not bandas_texto:
        return None
    resultado = {'titulo': '', 'descricao': '', 'url_exibida': '', 'url_final': '', 'cta': '', 'cta_subtitulo': '', 'sitelinks': []}
    idx = 0
    print(f'[OCR-DEBUG] bandas_texto totais={len(bandas_texto)} -> ' + str([(i, b['y_min'], b['y_max'], b['classe'], b.get('sep_antes')) for i, b in enumerate(bandas_texto)]), flush=True)
    _debug_bandas = [{'idx': i, 'y_min': b['y_min'], 'y_max': b['y_max'], 'classe': b['classe'], 'sep_antes': b.get('sep_antes'), 'x_min_favicon': b.get('x_min_favicon') or 0} for i, b in enumerate(bandas_texto)]
    primeiro_texto = _ocr_banda(reader, img_bgr, bandas_texto[0]['y_min'], bandas_texto[0]['y_max'], x_min=bandas_texto[0].get('x_min_favicon') or None)
    _primeiro_texto_strip = primeiro_texto.strip()
    _eh_patrocinado = bool(_REGEX_PATROCINADO.match(_primeiro_texto_strip))
    _texto_apos_patrocinado = None
    if not _eh_patrocinado:
        _match_prefixo_patrocinado = _REGEX_PATROCINADO_PREFIXO.match(_primeiro_texto_strip)
        if _match_prefixo_patrocinado:
            _resto_bruto = _primeiro_texto_strip[_match_prefixo_patrocinado.end():]
            if _resto_bruto and (_resto_bruto[0] in ' :-' or _resto_bruto[0].isupper()):
                _texto_apos_patrocinado = _resto_bruto.lstrip(' :-').strip()
    print(f'[OCR-DEBUG] primeira banda bruto={_primeiro_texto_strip!r} eh_patrocinado={_eh_patrocinado} texto_apos_patrocinado={_texto_apos_patrocinado!r}', flush=True)
    _debug_bandas[0]['texto'] = _primeiro_texto_strip
    if _eh_patrocinado:
        _debug_bandas[0]['decisao'] = 'patrocinado (descartada)'
        idx = 1
    elif _texto_apos_patrocinado:
        _debug_bandas[0]['decisao'] = f'rótulo de anúncio patrocinado grudado no início — removido, resto tratado como cabeçalho: {_texto_apos_patrocinado!r}'
    else:
        _debug_bandas[0]['decisao'] = 'não é rótulo de anúncio patrocinado'
    _partes_dominio = []
    _altura_max_linha_cabecalho = 0
    while idx < len(bandas_texto) and bandas_texto[idx]['classe'] not in ('azul', 'botao') and (idx == 0 or bandas_texto[idx]['y_min'] - bandas_texto[idx - 1]['y_max'] <= 80) and (not (_altura_max_linha_cabecalho > 0 and bandas_texto[idx]['y_max'] - bandas_texto[idx]['y_min'] + 1 >= _altura_max_linha_cabecalho * 1.6)):
        if idx == 0 and _texto_apos_patrocinado is not None:
            _txt_dominio = _texto_apos_patrocinado
        else:
            _txt_dominio = _ocr_banda(reader, img_bgr, bandas_texto[idx]['y_min'], bandas_texto[idx]['y_max'], x_min=bandas_texto[idx].get('x_min_favicon') or None).strip()
        _txt_dominio = re.sub('(?<!\\S)l(?!\\S)', '/', _txt_dominio)
        _txt_dominio = re.sub('(?<!\\S)1[A-Z]?(?!\\S)', '', _txt_dominio)
        _txt_dominio = re.sub('\\s{2,}', ' ', _txt_dominio).strip()
        _tem_prefixo_www_forte = bool(re.search('^(?:https?://)?[nNvVwW]{2,4}[.:]|\\bwww\\b', _txt_dominio, re.IGNORECASE))
        _parece_dominio_ou_url = bool(re.search('\\bwww\\b|\\.\\s?[a-zA-Z]{2,4}\\b|^[nNvVwW]{2,4}[.:]', _txt_dominio, re.IGNORECASE))
        if _parece_dominio_ou_url:
            _txt_dominio_sem_espaco = re.sub('\\s+', '', _txt_dominio)
        else:
            _txt_dominio_sem_espaco = re.sub('\\s+', ' ', _txt_dominio).strip()
        _txt_dominio_sem_espaco = re.sub('^[^a-zA-Z0-9]+', '', _txt_dominio_sem_espaco)
        _nome_corrigido_p_empresa = False
        if not _tem_prefixo_www_forte and empresa:
            _txt_corrigido = _corrigir_nome_pagina_com_empresa(_txt_dominio_sem_espaco, empresa)
            if _txt_corrigido != _txt_dominio_sem_espaco:
                _txt_dominio_sem_espaco = _txt_corrigido
                _nome_corrigido_p_empresa = True
                _parece_dominio_ou_url = False
        print(f"[OCR-DEBUG] header-linha idx={idx} classe={bandas_texto[idx]['classe']!r} bruto={_txt_dominio!r} limpo={_txt_dominio_sem_espaco!r} corrigido_p_empresa={_nome_corrigido_p_empresa}", flush=True)
        _debug_bandas[idx]['texto'] = _txt_dominio
        _debug_bandas[idx]['decisao'] = f"cabeçalho ({('URL' if _parece_dominio_ou_url else 'nome da página')}, limpo: {_txt_dominio_sem_espaco!r}" + (', corrigido p/ nome cadastrado da empresa' if _nome_corrigido_p_empresa else '') + ')' if _txt_dominio_sem_espaco else 'cabeçalho/URL (vazio após limpeza — descartada)'
        if _txt_dominio_sem_espaco:
            if _nome_corrigido_p_empresa and (not _parece_dominio_ou_url):
                _nome_exibicao = _txt_dominio_sem_espaco.strip()
                if ' ' not in _nome_exibicao and _nome_exibicao.lower().endswith('brasil'):
                    _marca = _nome_exibicao[:-6]
                    if _marca.lower().endswith('ticket') and len(_marca) > 6:
                        _prefixo = _marca[:-6]
                        _marca = _prefixo[:1].upper() + _prefixo[1:].lower() + 'Ticket'
                    else:
                        _marca = _marca[:1].upper() + _marca[1:]
                    _nome_exibicao = f'{_marca} Brasil'
                _partes_dominio.append(_nome_exibicao)
            else:
                _partes_dominio.append(_normalizar_url_exibida(_txt_dominio_sem_espaco))
            _altura_linha_cabecalho_atual = bandas_texto[idx]['y_max'] - bandas_texto[idx]['y_min'] + 1
            if _altura_linha_cabecalho_atual > _altura_max_linha_cabecalho:
                _altura_max_linha_cabecalho = _altura_linha_cabecalho_atual
        idx += 1

    def _chave_dedup_dominio(s: str) -> str:
        s2 = re.sub('^\\d(?=[a-zA-Z])', '', s)
        s2 = re.sub('^https?://', '', s2, flags=re.IGNORECASE)
        s2 = re.sub('^www\\.', '', s2, flags=re.IGNORECASE)
        return s2.lower()

    def _linha_com_digito_lider(s: str) -> bool:
        return bool(re.match('^\\d[a-zA-Z]', s))
    _grupos_dominio = {}
    _ordem_chaves_dominio = []
    for _p in _partes_dominio:
        _k = _chave_dedup_dominio(_p)
        if _k not in _grupos_dominio:
            _grupos_dominio[_k] = []
            _ordem_chaves_dominio.append(_k)
        _grupos_dominio[_k].append(_p)
    _partes_dominio = []
    for _k in _ordem_chaves_dominio:
        _candidatos = _grupos_dominio[_k]
        _limpos = [c for c in _candidatos if not _linha_com_digito_lider(c)]
        _pool = _limpos if _limpos else _candidatos
        _com_protocolo = [c for c in _pool if re.match('^https?://', c, re.IGNORECASE)]
        _partes_dominio.append(_com_protocolo[0] if _com_protocolo else _pool[0])
    resultado['url_exibida'] = '\n'.join(_partes_dominio)
    pares = []
    par_atual = None
    while idx < len(bandas_texto) and bandas_texto[idx]['classe'] == 'azul':
        if _ocr_banda(reader, img_bgr, bandas_texto[idx]['y_min'], bandas_texto[idx]['y_max']).strip():
            break
        _debug_bandas[idx]['decisao'] = 'azul → vazia (só ícone/logo, sem texto) — ignorada'
        idx += 1
    _bandas_restantes_display = bandas_texto[idx:]
    _tem_azul_de_verdade = any((b['classe'] == 'azul' and _ocr_banda(reader, img_bgr, b['y_min'], b['y_max']).strip() for b in _bandas_restantes_display))
    if not _tem_azul_de_verdade and _bandas_restantes_display and (_bandas_restantes_display[0]['classe'] in ('cinza', 'misto')):
        _fim_bloco_display = 0
        while _fim_bloco_display < len(_bandas_restantes_display) and _bandas_restantes_display[_fim_bloco_display]['classe'] in ('cinza', 'misto'):
            _fim_bloco_display += 1
        _bandas_display = _bandas_restantes_display[:_fim_bloco_display]
        _linhas_display = []
        for _b_display in _bandas_display:
            _txt_display_bruto, _linhas_bbox_display = _ocr_banda(reader, img_bgr, _b_display['y_min'], _b_display['y_max'], retornar_linhas=True)
            _txt_display = _limpar_pontuacao_ocr((_txt_display_bruto or '').strip())
            _alturas_reais = [float(_l.get('altura') or 0) for _l in _linhas_bbox_display or [] if (_l.get('texto') or '').strip() and float(_l.get('altura') or 0) > 0]
            if _alturas_reais:
                _alturas_reais.sort()
                _altura_display = _alturas_reais[len(_alturas_reais) // 2]
            else:
                _altura_display = _b_display['y_max'] - _b_display['y_min'] + 1
            _linhas_display.append({'texto': _txt_display, 'altura': _altura_display})
        _linhas_display_com_texto = [l for l in _linhas_display if l['texto']]
        if _linhas_display_com_texto:
            _titulo_display, _descricao_linhas_display = _extrair_titulo_descricao_por_altura(_linhas_display_com_texto)
            if _titulo_display:
                pares = [[_titulo_display, _descricao_linhas_display]]
                for _i_b, _b_display in enumerate(_bandas_display):
                    _idx_global_display = idx + _i_b
                    if _idx_global_display < len(_debug_bandas):
                        _debug_bandas[_idx_global_display]['texto'] = _linhas_display[_i_b]['texto'] if _i_b < len(_linhas_display) else ''
                        _debug_bandas[_idx_global_display]['decisao'] = 'cinza → título/descrição de Display sem sitelinks (separado por altura de fonte, sem nenhuma banda azul no anúncio)'
                idx += _fim_bloco_display
    _cta_aberto = False
    _ignorar_proxima_linha_rating = False
    _descricao_busca_forcada = False
    _alturas_bandas_texto = sorted((b['y_max'] - b['y_min'] for b in bandas_texto))
    _altura_tipica_texto = _alturas_bandas_texto[len(_alturas_bandas_texto) // 2] if _alturas_bandas_texto else None
    while idx < len(bandas_texto):
        banda = bandas_texto[idx]
        _altura_banda_atual = banda['y_max'] - banda['y_min']
        _gap_minimo_botoes = None
        _titulo_ja_reconhecido = bool(pares) or par_atual is not None
        if _titulo_ja_reconhecido and _altura_tipica_texto and (_altura_banda_atual > _altura_tipica_texto * 1.6):
            _gap_minimo_botoes = max(14, int(_altura_tipica_texto * 0.5))
        _continuacao_titulo_aberto = par_atual is not None and (not par_atual[1]) and (not banda.get('sep_antes'))
        if banda['classe'] != 'botao' and _titulo_ja_reconhecido and (not _continuacao_titulo_aberto):
            _grupos_botoes = _dividir_banda_em_botoes(img_bgr, banda['y_min'], banda['y_max'], gap_minimo=_gap_minimo_botoes)
        else:
            _grupos_botoes = []
        if len(_grupos_botoes) == 2 and (_grupos_botoes[0][1] - _grupos_botoes[0][0] <= 55 or _grupos_botoes[-1][1] - _grupos_botoes[-1][0] <= 55):
            _grupos_botoes = []
        if len(_grupos_botoes) == 2 and banda.get('classe') in ('misto', 'cinza') and (par_atual is not None) and (not banda.get('sep_antes')) and (_grupos_botoes[1][0] >= int(img_bgr.shape[1] * 0.62)):
            _grupos_botoes = []
        if len(_grupos_botoes) >= 5:
            _debug_bandas[idx]['decisao'] = f'divisor visual geométrico ({len(_grupos_botoes)} microblocos) → ignorado; mantém descrição em andamento'
            idx += 1
            continue
        if len(_grupos_botoes) >= 2:
            _texto_pre_fileira_bruto = _ocr_banda(reader, img_bgr, banda['y_min'], banda['y_max']).strip()
            _texto_pre_fileira = _limpar_pontuacao_ocr(_texto_pre_fileira_bruto)
            _ruido_pre_compacto = re.sub('\\s+', '', _texto_pre_fileira or '')
            _ruido_pre_restante = re.sub('[|¦│┃!Il1_\\-–—./\\\\]', '', _ruido_pre_compacto)
            if len(_ruido_pre_compacto) >= 4 and (not _ruido_pre_restante) and (len(re.findall('[|¦│┃!Il1_\\-–—./\\\\]', _ruido_pre_compacto)) >= 4):
                _debug_bandas[idx]['texto'] = _texto_pre_fileira
                _debug_bandas[idx]['decisao'] = 'divisor visual/ruído de OCR → ignorado ANTES da detecção de fileira; mantém descrição em andamento'
                idx += 1
                continue
        if len(_grupos_botoes) >= 2:
            print(f'[OCR-DEBUG] banda idx={idx} reconhecida como fileira de botões, {len(_grupos_botoes)} bloco(s): {_grupos_botoes}', flush=True)
            _debug_bandas[idx]['decisao'] = f'fileira de botões ({len(_grupos_botoes)} bloco(s))'
            if par_atual is not None:
                pares.append(par_atual)
                par_atual = None
            _cta_aberto = False
            _textos_botoes_debug = []
            for _x_ini, _x_fim in _grupos_botoes:
                _texto_botao = _limpar_pontuacao_ocr(_ocr_banda(reader, img_bgr, banda['y_min'], banda['y_max'], x_min=_x_ini, x_max=_x_fim).strip())
                _textos_botoes_debug.append(_texto_botao)
                if _texto_botao:
                    resultado['sitelinks'].append({'titulo': _texto_botao, 'descricao': ''})
            _debug_bandas[idx]['texto'] = ' | '.join(_textos_botoes_debug)
            idx += 1
            continue
        if banda['classe'] == 'botao' and banda.get('x_min_botao') is not None:
            _texto_banda_bruto = _ocr_banda(reader, img_bgr, banda['y_min'], banda['y_max'], x_min=banda.get('x_min_botao'), x_max=banda.get('x_max_botao')).strip()
        else:
            _texto_banda_bruto = _ocr_banda(reader, img_bgr, banda['y_min'], banda['y_max']).strip()
        texto = _limpar_pontuacao_ocr(_texto_banda_bruto)
        _debug_bandas[idx]['texto'] = texto
        _texto_ruido_sep = re.sub('\\s+', '', texto or '')
        _texto_ruido_restante = re.sub('[|¦│┃!Il1_\\-–—./\\\\]', '', _texto_ruido_sep)
        if len(_texto_ruido_sep) >= 4 and (not _texto_ruido_restante) and (len(re.findall('[|¦│┃!Il1_\\-–—./\\\\]', _texto_ruido_sep)) >= 4):
            _debug_bandas[idx]['decisao'] = 'divisor visual/ruído de OCR → ignorado; mantém descrição em andamento'
            idx += 1
            continue
        _texto_rating_norm = re.sub('\\s+', ' ', (texto or '').strip())
        if re.match('(?i)^rating\\s+for\\b', _texto_rating_norm):
            _ignorar_proxima_linha_rating = True
            _debug_bandas[idx]['decisao'] = 'rating do Google → descartado (cabeçalho de avaliação)'
            idx += 1
            continue
        if _ignorar_proxima_linha_rating and _texto_rating_norm:
            _ignorar_proxima_linha_rating = False
            _debug_bandas[idx]['decisao'] = 'rating do Google → descartado (nota/estrelas/avaliações)'
            idx += 1
            continue
        _texto_desc_norm = re.sub('\\s+', ' ', (texto or '').strip())
        _buy_sell_parece_continuacao_titulo = banda['classe'] == 'azul' and (not banda.get('sep_antes')) and (par_atual is not None) and (not par_atual[1]) and bool(re.match('(?i)^buy\\s*(?:&|and)\\s*sell\\b', _texto_desc_norm)) and bool(re.search('(?i)\\|\\s*(?:TS|TicketSwap)\\s*$', _texto_desc_norm)) and (len(_texto_desc_norm.split()) <= 8)
        if par_atual is not None and _titulo_ja_reconhecido and re.match('(?i)^buy\\s*(?:&|and)\\s*sell\\b', _texto_desc_norm) and (not _buy_sell_parece_continuacao_titulo):
            _descricao_busca_forcada = True
        _azul_parece_links_relacionados = banda['classe'] == 'azul' and bool(re.search('[·•]', _texto_desc_norm)) and (len([p for p in re.split('\\s*[·•]\\s*', _texto_desc_norm) if p.strip()]) >= 2)
        _empresa_norm_v57 = str(empresa or '').strip().lower().replace(' ', '')
        _partes_hifen_v57 = [p.strip() for p in re.split('\\s+[\\-–—]\\s+', re.sub('\\s*[\\-–—]\\s*$', '', _texto_desc_norm)) if p.strip()]
        _azul_parece_links_relacionados_hifen = banda['classe'] == 'azul' and _empresa_norm_v57 == 'ticketswap' and (len(_partes_hifen_v57) >= 2) and all((re.search('(?i)\\b(?:ticketswap|testimonial(?:s)?|review(?:s)?|homepage|how\\s+.*works|download|contact|sell\\s+your|buy\\s+&\\s+sell|find\\s+last|about)\\b', _p) for _p in _partes_hifen_v57))
        if _descricao_busca_forcada and (_azul_parece_links_relacionados or _azul_parece_links_relacionados_hifen):
            _descricao_busca_forcada = False
        if _descricao_busca_forcada and par_atual is not None and _texto_desc_norm and (not banda.get('sep_antes')) and (banda['classe'] != 'botao'):
            par_atual[1].append(texto)
            _debug_bandas[idx]['decisao'] = f"{banda['classe']} → descrição de Busca em andamento (bloco iniciado por 'Buy & sell'; cor ignorada)"
            idx += 1
            continue
        if banda['classe'] == 'azul':
            _titulo_e_descricao_ja_fechados = bool(pares) or (par_atual is not None and par_atual[1])
            _portao_seguranca_relacionados = bool(banda.get('sep_antes')) or _titulo_e_descricao_ja_fechados
            _partes_relacionados = None
            _relacionados_split_textual_confiavel = False
            if re.search('[·•]', texto):
                _candidatos_relacionados = [p.strip() for p in re.split('\\s*[·•]\\s*', texto) if p.strip()]
                if _portao_seguranca_relacionados and len(_candidatos_relacionados) >= 2:
                    _partes_relacionados = _candidatos_relacionados
                    _relacionados_split_textual_confiavel = True
            elif re.search('\\s[\\-–—]\\s', texto):
                _texto_sem_travessao_final = re.sub('\\s*[\\-–—]\\s*$', '', texto)
                _candidatos_relacionados = [p.strip() for p in re.split('\\s+[\\-–—]\\s+', _texto_sem_travessao_final) if p.strip()]
                if _portao_seguranca_relacionados and len(_candidatos_relacionados) == 3 and bool(re.search('\\s[\\-–—]\\s*$', texto or '')) and re.search('(?i)\\b(?:compre|comprar|venda|vender)\\b.*\\bingressos?\\b', _candidatos_relacionados[0]) and (re.fullmatch('(?i)(?:segunda(?:-feira)?|terça(?:-feira)?|terca(?:-feira)?|quarta(?:-feira)?|quinta(?:-feira)?|sexta(?:-feira)?|sábado|sabado|domingo)', _candidatos_relacionados[2].strip()) or re.fullmatch('(?i)\\d{1,2}\\s+dias?', _candidatos_relacionados[2].strip())):
                    _partes_relacionados = [_candidatos_relacionados[0], f'{_candidatos_relacionados[1]} - {_candidatos_relacionados[2]}']
                    _relacionados_split_textual_confiavel = True
                elif _portao_seguranca_relacionados and len(_candidatos_relacionados) == 4 and all((re.fullmatch('(?i)(?:segunda(?:-feira)?|terça(?:-feira)?|terca(?:-feira)?|quarta(?:-feira)?|quinta(?:-feira)?|sexta(?:-feira)?|sábado|sabado|domingo)', _candidatos_relacionados[_i_dia].strip()) for _i_dia in (1, 3))) and all((not re.fullmatch('(?i)(?:segunda(?:-feira)?|terça(?:-feira)?|terca(?:-feira)?|quarta(?:-feira)?|quinta(?:-feira)?|sexta(?:-feira)?|sábado|sabado|domingo)', _candidatos_relacionados[_i_evento].strip()) for _i_evento in (0, 2))):
                    _partes_relacionados = [f'{_candidatos_relacionados[0]} - {_candidatos_relacionados[1]}', f'{_candidatos_relacionados[2]} - {_candidatos_relacionados[3]}']
                    _relacionados_split_textual_confiavel = True
                elif _portao_seguranca_relacionados and len(_candidatos_relacionados) >= 3:
                    _partes_relacionados = _candidatos_relacionados
                elif _titulo_e_descricao_ja_fechados and (not banda.get('sep_antes')) and (len(_candidatos_relacionados) == 2) and all((re.search('\\b(?:19|20)\\d{2}\\b', _p) for _p in _candidatos_relacionados)):
                    _partes_relacionados = _candidatos_relacionados
                elif _titulo_e_descricao_ja_fechados and len(_candidatos_relacionados) == 2 and re.fullmatch('(?i)(?:compre|comprar)\\s+ou\\s+(?:venda|vender)\\s+ingressos?', _candidatos_relacionados[0].strip()) and re.fullmatch('(?i)ingressos?\\s+(?:artes?\\s+e\\s+teatro|teatros?|shows?|esportes?|eventos?|festivais?|futebol|música|musica|comédia|comedia)', _candidatos_relacionados[1].strip()):
                    _partes_relacionados = _candidatos_relacionados
                    _relacionados_split_textual_confiavel = True
                elif _titulo_e_descricao_ja_fechados and (not banda.get('sep_antes')) and (len(_candidatos_relacionados) == 2) and (str(empresa or '').strip().lower().replace(' ', '') == 'ticketswap') and any((re.search('(?i)\\b(?:ticketswap|testimonial(?:s)?|review(?:s)?|homepage|how\\s+.*works|download|contact|sell\\s+your|buy\\s+&\\s+sell|find\\s+last|about)\\b', _p) for _p in _candidatos_relacionados)):
                    _partes_relacionados = _candidatos_relacionados
                    _relacionados_split_textual_confiavel = True
                elif _titulo_e_descricao_ja_fechados and (not banda.get('sep_antes')) and (len(_candidatos_relacionados) == 2) and bool(re.search('\\s[\\-–—]\\s*$', texto or '')) and all((re.search('(?i)\\b(?:eventos?\\s+em|compre\\s+ou\\s+venda\\s+ingressos?|comprar\\s+ou\\s+vender\\s+ingressos?|compre\\s+ingressos?|comprar\\s+ingressos?|venda\\s+ingressos?|vender\\s+ingressos?|ingressos?\\s+(?:show|shows|evento|eventos|esporte|esportes|futebol|festival|festivais|teatro|teatros)|shows?\\s+em|como\\s+funciona|sobre\\s+(?:a|o)|categorias?|homepage)\\b', _p) for _p in _candidatos_relacionados)):
                    _partes_relacionados = _candidatos_relacionados
                    _relacionados_split_textual_confiavel = True
            if str(empresa or '').strip().lower().replace(' ', '') == 'ticketswap' and _partes_relacionados:
                _partes_relacionados = [re.sub('(?i)^reg[ií]strate\\s*[,;:]\\s*entra$', 'Regístrate o entra', _p.strip()) for _p in _partes_relacionados]
            if _portao_seguranca_relacionados and (not _relacionados_split_textual_confiavel):
                _candidatos_gap = _dividir_termos_relacionados_por_gap(reader, img_bgr, banda['y_min'], banda['y_max'])
                if len(_candidatos_gap) >= 3 and len(_candidatos_gap) > len(_partes_relacionados or []):
                    _partes_relacionados = _candidatos_gap
            if _partes_relacionados and len(_partes_relacionados) >= 2:
                _debug_bandas[idx]['decisao'] = f'azul → linha de termos relacionados ({len(_partes_relacionados)} link(s) separados por hr, em vez de ficarem grudados)'
                if par_atual is not None:
                    pares.append(par_atual)
                    par_atual = None
                for _termo_rel in _partes_relacionados:
                    resultado['sitelinks'].append({'titulo': _termo_rel, 'descricao': ''})
                idx += 1
                continue
            _cta_aberto = False
            if par_atual is not None and (not par_atual[1]) and (not banda.get('sep_antes')):
                par_atual[0] = (par_atual[0] + ' ' + texto).strip()
                _debug_bandas[idx]['decisao'] = 'azul → quebra de linha do título/sitelink em andamento (juntada)'
            elif par_atual is not None:
                pares.append(par_atual)
                par_atual = [texto, []]
                _debug_bandas[idx]['decisao'] = 'azul → NOVO título/sitelink' + (' (por causa de separador antes)' if banda.get('sep_antes') else ' (par anterior já tinha descrição, ou é o primeiro)')
            else:
                _par_criado_via_empresa = False
                if not pares and (not resultado['url_exibida']) and empresa:
                    _, _linhas_banda = _ocr_banda(reader, img_bgr, banda['y_min'], banda['y_max'], retornar_linhas=True)
                    if _linhas_banda:
                        _primeira_linha_txt = _limpar_pontuacao_ocr(_linhas_banda[0]['texto'])
                        if _corrigir_nome_pagina_com_empresa(_primeira_linha_txt, empresa) == empresa:
                            resultado['url_exibida'] = _melhor_nome_para_exibir(_primeira_linha_txt, empresa)
                            if _linhas_banda[1:]:
                                _titulo_extraido, _descricao_linhas = _extrair_titulo_descricao_por_altura(_linhas_banda[1:])
                            else:
                                _fim_bloco_cinza = idx + 1
                                while _fim_bloco_cinza < len(bandas_texto) and bandas_texto[_fim_bloco_cinza]['classe'] in ('cinza', 'misto'):
                                    _fim_bloco_cinza += 1
                                _bandas_cinza_seguintes = bandas_texto[idx + 1:_fim_bloco_cinza]
                                _linhas_seguintes = []
                                for _b_seg in _bandas_cinza_seguintes:
                                    _txt_seg_bruto, _linhas_bbox_seg = _ocr_banda(reader, img_bgr, _b_seg['y_min'], _b_seg['y_max'], retornar_linhas=True)
                                    _txt_seg = _limpar_pontuacao_ocr((_txt_seg_bruto or '').strip())
                                    _alturas_seg = [float(_l.get('altura') or 0) for _l in _linhas_bbox_seg or [] if (_l.get('texto') or '').strip() and float(_l.get('altura') or 0) > 0]
                                    if _alturas_seg:
                                        _alturas_seg.sort()
                                        _altura_seg = _alturas_seg[len(_alturas_seg) // 2]
                                    else:
                                        _altura_seg = _b_seg['y_max'] - _b_seg['y_min'] + 1
                                    _linhas_seguintes.append({'texto': _txt_seg, 'altura': _altura_seg})
                                _titulo_extraido, _descricao_linhas = _extrair_titulo_descricao_por_altura([l for l in _linhas_seguintes if l['texto']])
                                for _k_seg in range(idx + 1, _fim_bloco_cinza):
                                    if _k_seg < len(_debug_bandas):
                                        _debug_bandas[_k_seg]['decisao'] = 'cinza → título/descrição de Display separado por altura de fonte (cabeçalho já identificado numa banda azul à parte)'
                                idx = _fim_bloco_cinza - 1
                            par_atual = [_limpar_pontuacao_ocr(_titulo_extraido), [_limpar_pontuacao_ocr(l) for l in _descricao_linhas if l]]
                            _debug_bandas[idx]['decisao'] = f'azul → cabeçalho de Display: nome da empresa {empresa!r} extraído da 1ª linha, título+descrição separados por altura de fonte'
                            _par_criado_via_empresa = True
                if not _par_criado_via_empresa:
                    if not texto.strip():
                        _debug_bandas[idx]['decisao'] = 'azul → vazia (só ícone/logo, sem texto) — ignorada'
                    else:
                        par_atual = [texto, []]
                        _debug_bandas[idx]['decisao'] = 'azul → NOVO título/sitelink' + (' (por causa de separador antes)' if banda.get('sep_antes') else ' (par anterior já tinha descrição, ou é o primeiro)')
        elif banda['classe'] == 'cinza':
            if _cta_aberto:
                resultado['cta_subtitulo'] = (resultado['cta_subtitulo'] + ' ' + texto).strip()
                _debug_bandas[idx]['decisao'] = 'cinza → subtítulo do CTA'
            elif not resultado['cta'] and _REGEX_CTA_TITULO_CONHECIDO.match(texto):
                resultado['cta'] = texto
                _cta_aberto = True
                _debug_bandas[idx]['decisao'] = 'cinza → CTA (bateu regex de CTA conhecido)'
            elif par_atual is not None:
                _titulo_ou_desc_ja_existe = bool(par_atual[1]) or bool(pares)
                if banda.get('sep_antes') and _titulo_ou_desc_ja_existe:
                    pares.append(par_atual)
                    par_atual = [texto, []]
                    _debug_bandas[idx]['decisao'] = 'cinza → NOVO sitelink em texto preto (por causa de separador antes)'
                elif (texto or '').strip():
                    par_atual[1].append(texto)
                    _debug_bandas[idx]['decisao'] = 'cinza → descrição do título/sitelink em andamento'
                else:
                    _debug_bandas[idx]['decisao'] = 'cinza → vazia (sem texto OCR) — ignorada'
            else:
                _debug_bandas[idx]['decisao'] = 'cinza → descartada (sem título/sitelink aberto nem CTA)'
        elif banda['classe'] == 'botao':
            _texto_cta_limpo = (texto or '').strip()
            _cta_suspeito_curto = bool(_texto_cta_limpo) and len(re.sub('[^A-Za-zÀ-ÿ0-9]', '', _texto_cta_limpo)) <= 4
            _cta_atual_conhecido = bool(_REGEX_CTA_TITULO_CONHECIDO.match(_texto_cta_limpo))
            _ha_botao_valido_mais_abaixo = False
            _ha_cta_conhecido_mais_abaixo = False
            _txt_cta_conhecido_mais_abaixo = ''
            if not resultado['cta']:
                for _j_cta in range(idx + 1, len(bandas_texto)):
                    _b_cta_fut = bandas_texto[_j_cta]
                    if _b_cta_fut.get('classe') != 'botao':
                        continue
                    if _b_cta_fut.get('x_min_botao') is not None:
                        _txt_cta_fut = _ocr_banda(reader, img_bgr, _b_cta_fut['y_min'], _b_cta_fut['y_max'], x_min=_b_cta_fut.get('x_min_botao'), x_max=_b_cta_fut.get('x_max_botao')).strip()
                    else:
                        _txt_cta_fut = _ocr_banda(reader, img_bgr, _b_cta_fut['y_min'], _b_cta_fut['y_max']).strip()
                    _txt_cta_fut = _limpar_pontuacao_ocr(_txt_cta_fut)
                    if len(re.sub('[^A-Za-zÀ-ÿ0-9]', '', _txt_cta_fut)) >= 5:
                        _ha_botao_valido_mais_abaixo = True
                    if _REGEX_CTA_TITULO_CONHECIDO.match(_txt_cta_fut):
                        _ha_cta_conhecido_mais_abaixo = True
                        _txt_cta_conhecido_mais_abaixo = _txt_cta_fut
                        break
            _ignorar_por_cta_conhecido_abaixo = bool(_texto_cta_limpo) and (not _cta_atual_conhecido) and _ha_cta_conhecido_mais_abaixo
            if _ignorar_por_cta_conhecido_abaixo:
                _debug_bandas[idx]['decisao'] = f"botao → ignorado como conteúdo interno da arte (CTA conhecido mais abaixo: '{_txt_cta_conhecido_mais_abaixo}')"
            elif _cta_suspeito_curto and _ha_botao_valido_mais_abaixo:
                _debug_bandas[idx]['decisao'] = 'botao → ignorado como falso CTA (texto curto e existe botão válido mais abaixo)'
            else:
                if par_atual is not None:
                    pares.append(par_atual)
                    par_atual = None
                if not resultado['cta'] and _texto_cta_limpo:
                    resultado['cta'] = _texto_cta_limpo
                    _cta_aberto = True
                    _debug_bandas[idx]['decisao'] = 'botao → CTA (taxa de preenchimento alta, validado)'
                elif not _texto_cta_limpo:
                    _debug_bandas[idx]['decisao'] = 'botao → descartada (OCR vazio)'
                else:
                    _debug_bandas[idx]['decisao'] = 'botao → descartada (CTA já preenchido)'
        else:
            _misto_palavras = [p for p in re.split('\\s+', (texto or '').strip()) if p]
            _misto_parece_frase = len(_misto_palavras) >= 4 or len((texto or '').strip()) >= 28
            _misto_cta_conhecido = bool(_REGEX_CTA_TITULO_CONHECIDO.match((texto or '').strip()))
            _prox_banda_misto_sem_sep = False
            if idx + 1 < len(bandas_texto):
                _prox_b = bandas_texto[idx + 1]
                _prox_banda_misto_sem_sep = _prox_b.get('classe') == 'misto' and (not _prox_b.get('sep_antes'))
            _misto_tem_pontuacao_corpo = bool(re.search('[.,;:!?]', (texto or '').strip()))
            _misto_sep_falso_descricao = par_atual is not None and bool(banda.get('sep_antes')) and (not _misto_cta_conhecido) and _prox_banda_misto_sem_sep and _misto_tem_pontuacao_corpo and (len(_misto_palavras) >= 7 or len((texto or '').strip()) >= 45)
            _misto_continua_descricao = par_atual is not None and (not _misto_cta_conhecido) and (not banda.get('sep_antes') and (bool(par_atual[1]) or _misto_parece_frase) or _misto_sep_falso_descricao)
            _misto_separados_restantes = 0
            if banda.get('sep_antes') and (not _misto_cta_conhecido):
                for _j_sl in range(idx, len(bandas_texto)):
                    _b_sl = bandas_texto[_j_sl]
                    if _b_sl.get('classe') == 'misto' and _b_sl.get('sep_antes'):
                        _misto_separados_restantes += 1
            _misto_lista_sitelinks = banda.get('sep_antes') and (not _misto_cta_conhecido) and _titulo_ja_reconhecido and (_misto_separados_restantes >= 2)
            _misto_tem_contexto_sitelink = banda.get('sep_antes') and (not _misto_cta_conhecido) and (_misto_lista_sitelinks or (par_atual is not None and (bool(par_atual[1]) or bool(pares))))
            if _misto_tem_contexto_sitelink:
                if par_atual is not None:
                    pares.append(par_atual)
                par_atual = [texto, []]
                _debug_bandas[idx]['decisao'] = 'misto → NOVO sitelink em texto preto/cinza (separador antes; lista de sitelinks detectada)' if _misto_lista_sitelinks else 'misto → NOVO sitelink em texto preto/cinza (por causa de separador antes)'
            elif _misto_continua_descricao:
                par_atual[1].append(texto)
                _debug_bandas[idx]['decisao'] = 'misto → descrição do título/sitelink em andamento (falso separador detectado; frase longa + continuação na linha seguinte; não é CTA)' if _misto_sep_falso_descricao else 'misto → descrição do título/sitelink em andamento (frase corrida sem separador; não é CTA)'
            elif _titulo_ja_reconhecido:
                if not (texto or '').strip():
                    _debug_bandas[idx]['decisao'] = 'misto → vazia (sem texto OCR) — ignorada'
                elif not resultado['cta']:
                    resultado['cta'] = texto
                    _cta_aberto = True
                    _debug_bandas[idx]['decisao'] = 'misto → CTA'
                else:
                    _debug_bandas[idx]['decisao'] = 'misto → descartada (CTA já preenchido)'
            elif par_atual is not None:
                par_atual[1].append(texto)
                _debug_bandas[idx]['decisao'] = 'misto → descrição (título ainda não reconhecido, não pode ser CTA)'
            else:
                _debug_bandas[idx]['decisao'] = 'misto → descartada (sem título aberto, mas não pode ser CTA aqui)'
        idx += 1
    if par_atual is not None:
        pares.append(par_atual)
    resultado['_debug_bandas'] = _debug_bandas
    if not pares:
        return resultado if resultado['url_exibida'] else None
    resultado['titulo'] = _normalizar_aspas_ocr(pares[0][0])
    resultado['descricao'] = _normalizar_aspas_ocr(' '.join((l for l in pares[0][1] if l)).strip())
    for titulo_sl, linhas_sl in pares[1:]:
        descricao_sl = _normalizar_aspas_ocr(' '.join((l for l in linhas_sl if l)).strip())
        if titulo_sl:
            resultado['sitelinks'].append({'titulo': _normalizar_aspas_ocr(titulo_sl), 'descricao': descricao_sl})
    resultado = _corrigir_estrutura_ticketswap_ocr(resultado, empresa=empresa)
    return resultado

def _corrigir_estrutura_ticketswap_ocr(resultado: dict, empresa: str=None) -> dict:
    """V51 — corrige artefatos estruturais recorrentes dos anúncios TicketSwap.

    O Google usa muitos separadores verticais (``|``) nos headlines e
    descrições da TicketSwap. O EasyOCR às vezes: (1) lê uma barra como uma
    letra isolada (ex.: ``| P Porto``), (2) perde a barra antes do ``TS`` e
    (3) desloca o segundo dia de um intervalo de datas para perto da cidade,
    deixando ruído ``1 ~`` no lugar do travessão.

    As correções abaixo só rodam quando a empresa/URL é TicketSwap e exigem
    padrões estruturais fortes, para não alterar anúncios de outras marcas.
    """
    if not isinstance(resultado, dict):
        return resultado
    _empresa_norm = re.sub('[^a-z0-9]+', '', (empresa or '').lower())
    _url_norm = (resultado.get('url_exibida') or '').lower()
    if 'ticketswap' not in _empresa_norm and 'ticketswap' not in _url_norm:
        return resultado
    titulo = re.sub('\\s+', ' ', (resultado.get('titulo') or '').strip())
    descricao = re.sub('\\s+', ' ', (resultado.get('descricao') or '').strip())
    _eh_ticketswap_de = bool(re.search('ticketswap\\.de(?:/|$)', _url_norm, re.IGNORECASE))
    if _eh_ticketswap_de:
        _rx_fuer_nome = re.compile('(?i)\\bfür\\s*,\\s*([^"|]{2,80}?)"(?=\\s*(?:\\||kaufen|verkaufen|$))')
        titulo = _rx_fuer_nome.sub(lambda m: 'für "' + m.group(1).strip() + '"', titulo)
        descricao = _rx_fuer_nome.sub(lambda m: 'für "' + m.group(1).strip() + '"', descricao)
        descricao = re.sub('(?i)(\\bund verkaufen)\\s+(?=(?:Olympiahalle|Mercedes-Benz Arena|Uber Arena|Lanxess Arena|Barclays Arena|SAP Arena)\\b)', '\\1 | ', descricao)
        descricao = re.sub('((?:Olympiahalle|Mercedes-Benz Arena|Uber Arena|Lanxess Arena|Barclays Arena|SAP Arena)[^|]{2,80}?)\\s+(?=(?:Mo|Di|Mi|Do|Fr|Sa|So)\\.,\\s*\\d)', '\\1 | ', descricao, flags=re.IGNORECASE)
    titulo = re.sub("(\\b20\\d{2})\\s*\\|\\s*P\\s+([A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]{2,})\\b", '\\1 | \\2 |', titulo)
    titulo = re.sub('(?i)(\\b(?:bilhetes|tickets))\\s+TS$', '\\1 | TS', titulo)
    titulo = re.sub('(?i)(?<![|:;\\-–—])\\s+(?=Buy\\s*&\\s*sell\\s+(?:tickets|bilhetes)\\s*\\|\\s*TS$)', ' | ', titulo, count=1)
    titulo = re.sub('(?i)\\b(tickets|bilhetes)\\s+(?=Buy\\s*&\\s*sell\\s+on\\s+TicketSwap$)', '\\1 | ', titulo, count=1)
    _rx_pipe_ruido_local = re.compile('(?i)(\\|)\\s*[FI]\\s+(?=(?:Palladium|Arena|Stadium|Stadion|Dome|Hall|Theatre|Theater|Olympiahalle|Mercedes-Benz|Uber Arena|Lanxess Arena|Barclays Arena|SAP Arena)\\b)')
    _rx_pipe_ruido_data = re.compile('(?i)(\\|)\\s*[FI]\\s+(?=(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Mo|Di|Mi|Do|Fr|Sa|So)[.,]?(?:\\s|$))')
    titulo = _rx_pipe_ruido_local.sub('\\1 ', titulo)
    titulo = _rx_pipe_ruido_data.sub('\\1 ', titulo)
    descricao = _rx_pipe_ruido_local.sub('\\1 ', descricao)
    descricao = _rx_pipe_ruido_data.sub('\\1 ', descricao)
    _rx_pipe_p_extra_caps = re.compile('(\\|)\\s*P\\s+(?=[A-ZÀ-Ý0-9]{3,}(?:\\s|$))')
    titulo = _rx_pipe_p_extra_caps.sub('\\1 ', titulo)
    descricao = _rx_pipe_p_extra_caps.sub('\\1 ', descricao)
    descricao = re.sub('\\s+[\\-–—]+\\s*$', '', descricao).strip()
    titulo = re.sub('(?i)\\bWorld\\s+Tour\\s+Tickets$', lambda m: re.sub('\\s+Tickets$', ' | Tickets', m.group(0), flags=re.IGNORECASE), titulo)
    titulo = re.sub("(\\|\\s*[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]{2,})\\s+(?=(?:Compra e vende|Compre|Buy & sell|Koop en verkoop|Kaufe und verkaufe)\\b)", '\\1 | ', titulo, flags=re.IGNORECASE)
    _rx_data_deslocada = re.compile("(?P<local>[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]{2,})\\s+(?P<data_fim>\\d{1,2}/\\d{2})\\.\\s+(?P<miolo>[^|]{3,100}?)\\s*\\|\\s*(?P<data_ini>\\d{1,2}/\\d{2})\\s+(?:1\\s*)?[~\\-–—]+")

    def _repor_intervalo(m):
        try:
            di, mi = [int(x) for x in m.group('data_ini').split('/')]
            df, mf = [int(x) for x in m.group('data_fim').split('/')]
            if mi != mf or di >= df:
                return m.group(0)
        except Exception:
            return m.group(0)
        return f"{m.group('local')} | {m.group('miolo').strip()} | {m.group('data_ini')} – {m.group('data_fim')}."
    descricao = _rx_data_deslocada.sub(_repor_intervalo, descricao)
    descricao = re.sub("\\|\\s*[=@$]+\\s*(?=[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:\\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+){0,5}\\s*,)", '| ', descricao)
    descricao = re.sub("(\\b[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+\\s*,\\s*[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+)\\s+(?=(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s*,\\s*[A-Z][a-z]{2}\\s+\\d{1,2}\\b)", '\\1 | ', descricao)
    descricao = re.sub("(\\b(?:[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:\\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+){0,4})\\s*,\\s*[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+)\\s+(?=(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s*,\\s*[A-Z][a-z]{2}\\s+\\d{1,2}\\b)", '\\1 | ', descricao)
    descricao = re.sub("(?<!\\|)\\s+(?P<venue>[A-ZÀ-Ý][A-Za-zÀ-ÿ0-9.'’&-]*(?:\\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ0-9.'’&-]*){0,2}\\s*,\\s*[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+)\\s+(?=(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s*,\\s*[A-Z][a-z]{2}\\s+\\d{1,2}\\b)", ' | \\g<venue> ', descricao)
    descricao = re.sub('(?i)(Buy\\s*&\\s*sell\\s+tickets\\s+for\\s+Kim\\s+Wilde)\\s+(?=Concertgebouw\\s*Brugge\\b)', '\\1 | ', descricao)
    descricao = re.sub('(?i)\\bConcertgebouw\\s*Brugge\\s*,\\s*Bruges\\b', 'Concertgebouw Brugge, Bruges', descricao)
    descricao = re.sub('(?i)(Concertgebouw Brugge, Bruges)\\s+(?=Wed\\s*,\\s*Oct\\s+29\\b)', '\\1 | ', descricao)
    descricao = re.sub('(?<!\\d)(\\d{1,2})\\.(\\d{2})\\s*(AM|PM)\\b', '\\1:\\2 \\3', descricao, flags=re.IGNORECASE)
    descricao = re.sub('\\s+(?:1\\s*)?[~^]+\\s*$', '', descricao).strip()
    descricao = re.sub('\\s+-\\s*$', '', descricao).strip()
    descricao = re.sub('(?i)\\bcomprar\\s+r(?:e)?\\s+vender\\b', 'comprar e vender', descricao)
    resultado['titulo'] = titulo
    resultado['descricao'] = descricao
    return resultado


def _readtext_instrumentado(reader, imagem, *args, etapa="readtext", **kwargs):
    _mem_snapshot_ocr(f"antes {etapa}")
    try:
        _res = reader.readtext(imagem, *args, **kwargs)
        _mem_snapshot_ocr(f"depois {etapa}")
        return _res
    except BaseException:
        _mem_snapshot_ocr(f"erro {etapa}")
        raise


def _extrair_ocr_estruturado_imagem(url_imagem: str, empresa: str=None, retornar_diagnostico: bool=False):
    _mem_snapshot_ocr('entrada extrair_ocr_estruturado')
    """Baixa a imagem (já no nosso R2) e separa, de forma ESTRUTURADA,
    os campos título/descrição/url_exibida/cta/sitelinks de um anúncio
    de TEXTO do Google Ads — sem nenhuma IA generativa, só EasyOCR +
    análise de cor (ver `_estruturar_anuncio_google_ads` e
    `_detectar_bandas_texto` pra entender a heurística: título é sempre
    azul, descrição/URL são sempre cinza uniforme, um traço fino
    cinza-claro separa cada sitelink — validado nos prints reais do
    Google Ads).

    `empresa`, quando informado, é repassado pra
    `_estruturar_anuncio_google_ads` só pra corrigir o NOME DA PÁGINA
    do cabeçalho usando o nome já cadastrado no monitoramento (ver
    `_corrigir_nome_pagina_com_empresa`) — opcional, não quebra quem
    chama sem passar esse argumento (comportamento igual ao antigo).

    Se a imagem não bater com esse padrão (ex: anúncio de Display com
    imagem, ou algum layout fora do comum), cai no fallback: todo o
    texto bruto lido pelo EasyOCR vai pro campo 'descricao', sem tentar
    separar nada — melhor ter o texto todo num campo só do que perder a
    informação.

    Devolve um dict com todas as chaves (algumas vazias) quando a
    extração RODOU de verdade — isso vale mesmo se a imagem não tiver
    nenhum texto legível (dict com tudo vazio).

    Devolve None quando a extração NÃO RODOU por causa de uma FALHA real
    — download da imagem falhou, EasyOCR não conseguiu processar etc.
    Quem chama essa função trata None como 'tenta de novo depois' — não
    grava nada no banco, deixando `ocr_texto` como NULL (pendente) pra
    essa imagem voltar pra fila na próxima passada."""
    _etapa_ocr_diag = 'download'
    try:
        _img = _baixar_imagem_cv2(url_imagem)
        if _img is None:
            _diag = {'etapa': 'decodificacao', 'erro': 'A imagem foi baixada, mas o OpenCV não conseguiu decodificar o arquivo.', 'url': url_imagem}
            print(f'[OCR-DEBUG] _extrair_ocr_estruturado_imagem FALHA (imagem não decodificou) url={url_imagem!r}', flush=True)
            return (None, _diag) if retornar_diagnostico else None
        import time as _time_ocr_estr
        _etapa_ocr_diag = 'aguardando_easyocr'
        with _lock_easyocr_execucao:
            _espera = _MIN_INTERVALO_OCR_SEG - (_time_ocr_estr.time() - _ultima_chamada_ocr[0])
            if _espera > 0:
                _time_ocr_estr.sleep(_espera)
            _etapa_ocr_diag = 'inicializacao_easyocr'
            _reader = _get_easyocr()
            _etapa_ocr_diag = 'leitura_ocr'
            with _recurso_cpu_pesada('easyocr-estruturado'):
                _estruturado = _estruturar_anuncio_google_ads(_img, _reader, empresa=empresa)
            if _estruturado is None or not _ocr_estruturado_tem_conteudo(_estruturado):
                _etapa_ocr_diag = 'fallback_ocr_bruto'
                with _recurso_cpu_pesada('easyocr-fallback-bruto'):
                    texto_bruto = _ocr_texto_bruto(_img, _reader)
                _linhas_fallback = [l.strip() for l in texto_bruto.split('\n') if l.strip()]
                _titulo_fallback = _normalizar_aspas_ocr(_linhas_fallback[0]) if _linhas_fallback and len(_linhas_fallback[0]) <= 80 else ''
                _descricao_fallback = _normalizar_aspas_ocr('\n'.join(_linhas_fallback[1:] if _titulo_fallback else _linhas_fallback))
                try:
                    _regiao_grafico_dbg = _detectar_regiao_grafico_criativo(_img)
                except Exception as _e_dbg_graf:
                    _regiao_grafico_dbg = f'erro ao detectar: {_e_dbg_graf!r}'
                _estruturado = {'titulo': _titulo_fallback, 'descricao': _descricao_fallback, 'url_exibida': '', 'url_final': '', 'cta': '', 'cta_subtitulo': '', 'sitelinks': [], '_debug_bandas': [{'idx': 0, 'y_min': 0, 'y_max': 0, 'classe': 'fallback_bruto', 'sep_antes': False, 'texto': f'regiao_grafico_detectada={_regiao_grafico_dbg!r}', 'decisao': '_estruturar_anuncio_google_ads não reconheceu padrão de bandas — caiu no OCR bruto (título/descrição separados por heurística de 1ª linha)'}]}
            _ultima_chamada_ocr[0] = _time_ocr_estr.time()
        print(f"[OCR-DEBUG] _extrair_ocr_estruturado_imagem OK url={url_imagem!r} titulo={_estruturado.get('titulo')!r} cta={_estruturado.get('cta')!r} cta_subtitulo={_estruturado.get('cta_subtitulo')!r} sitelinks={_estruturado.get('sitelinks')!r}", flush=True)
        return (_estruturado, None) if retornar_diagnostico else _estruturado
    except ZeroDivisionError as e:
        import traceback as _tb_v81
        _trace_v81 = _tb_v81.format_exc()
        print(f'[OCR-DEBUG] parser estruturado ZeroDivisionError; usando fallback bruto url={url_imagem!r}\n{_trace_v81}', flush=True)
        try:
            if '_img' not in locals() or _img is None:
                raise RuntimeError('imagem indisponível para fallback após ZeroDivisionError')
            if '_reader' not in locals() or _reader is None:
                _reader = _get_easyocr()
            _etapa_ocr_diag = 'fallback_apos_zerodivision'
            with _lock_easyocr_execucao:
                with _recurso_cpu_pesada('easyocr-fallback-zerodivision'):
                    _texto_v81 = _ocr_texto_bruto(_img, _reader)
            _linhas_v81 = [l.strip() for l in (_texto_v81 or '').split('\n') if l.strip()]
            _titulo_v81 = _normalizar_aspas_ocr(_linhas_v81[0]) if _linhas_v81 and len(_linhas_v81[0]) <= 80 else ''
            _descricao_v81 = _normalizar_aspas_ocr('\n'.join(_linhas_v81[1:] if _titulo_v81 else _linhas_v81))
            _fallback_v81 = {'titulo': _titulo_v81, 'descricao': _descricao_v81, 'url_exibida': '', 'url_final': '', 'cta': '', 'cta_subtitulo': '', 'sitelinks': [], '_debug_bandas': [{'idx': 0, 'y_min': 0, 'y_max': 0, 'classe': 'fallback_zerodivision', 'sep_antes': False, 'texto': 'Parser estruturado encontrou divisão por zero; OCR bruto preservado.', 'decisao': 'V81 → fallback bruto automático após ZeroDivisionError'}]}
            return (_fallback_v81, None) if retornar_diagnostico else _fallback_v81
        except Exception as _e_fb_v81:
            _diag = {'etapa': _etapa_ocr_diag, 'erro': f'{type(_e_fb_v81).__name__}: {_e_fb_v81}', 'erro_original': f'ZeroDivisionError: {e}', 'traceback_original': _trace_v81[-6000:], 'url': url_imagem}
            print(f'[OCR-DEBUG] fallback após ZeroDivisionError também falhou: {_e_fb_v81!r}', flush=True)
            return (None, _diag) if retornar_diagnostico else None
    except Exception as e:
        import traceback as _tb_diag_v81
        _diag = {'etapa': _etapa_ocr_diag, 'erro': f'{type(e).__name__}: {e}', 'traceback': _tb_diag_v81.format_exc()[-6000:], 'url': url_imagem}
        print(f'[OCR-DEBUG] _extrair_ocr_estruturado_imagem FALHA (exceção): {e!r}', flush=True)
        return (None, _diag) if retornar_diagnostico else None

def _ocr_estruturado_tem_conteudo(d: dict) -> bool:
    """True se algum campo veio preenchido — usado pra decidir se o
    resultado conta como 'achou texto' (mesmo critério que antes era só
    `texto.strip()` não-vazio)."""
    if not d:
        return False
    return bool(d.get('titulo') or d.get('descricao') or d.get('url_exibida') or d.get('url_final') or d.get('cta') or d.get('sitelinks'))

_MIN_INTERVALO_OCR_SEG = 0.0



def _achatar_ocr_estruturado(d: dict) -> str:
    if not d:
        return ""
    linhas = []
    for campo in ("titulo", "descricao", "url_exibida", "cta"):
        v = str(d.get(campo) or "").strip()
        if v:
            linhas.append(v)
    for sl in (d.get("sitelinks") or []):
        if not sl:
            continue
        if isinstance(sl, dict):
            if sl.get("titulo"):
                linhas.append(str(sl["titulo"]))
            if sl.get("descricao"):
                linhas.append(str(sl["descricao"]))
        else:
            linhas.append(str(sl))
    return "\n".join(linhas)



def _agora_iso_worker():
    import datetime as _dtw
    return _dtw.datetime.now(_dtw.timezone.utc).isoformat()


def _supabase_worker():
    from supabase import create_client

    url = (
        os.environ.get("SUPABASE_URL")
        or os.environ.get("PUBLIC_SUPABASE_URL")
    )
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        raise RuntimeError(
            "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY "
            "(ou SUPABASE_KEY) no serviço do worker."
        )
    return create_client(url, key)


_FILTRO_OCR_URL_GOOGLE_WORKER = (
    "url_origem.ilike.%googlesyndication.com%,"
    "url_origem.ilike.%googleusercontent.com%"
)


def _atividade_update_worker(sb, atividade_id: str, status: str, detalhes: dict):
    if not atividade_id:
        return
    payload = {
        "status": "pendente" if status == "na_fila" else status,
        "detalhes": dict(detalhes or {}),
    }
    if status == "na_fila":
        payload["detalhes"]["status_visual"] = "na_fila"
    sb.table("atividades").update(payload).eq("id", atividade_id).execute()


def _buscar_proxima_atividade_worker(sb):
    """Busca uma atividade OCR enfileirada ou abandonada após restart.

    Um único replica/instância deste worker deve ser executado.
    """
    res = (
        sb.table("atividades")
        .select("id,user_id,tipo,status,detalhes,titulo")
        .eq("tipo", "ocr_gads")
        .in_("status", ["pendente", "em_andamento"])
        .order("criado_em", desc=False)
        .limit(50)
        .execute()
    )
    rows = res.data or []

    # Prioriza pendentes; em_andamento antigo é retomado depois.
    for st in ("pendente", "em_andamento"):
        for row in rows:
            if row.get("status") != st:
                continue
            det = row.get("detalhes") or {}
            if not det.get("empresa"):
                continue
            return row
    return None


def _buscar_midia_pendente_worker(sb, user_id: str, empresa: str):
    res = (
        sb.table("midias")
        .select("id,url_cdn,url_origem")
        .eq("user_id", user_id)
        .eq("empresa", empresa)
        .eq("tipo", "imagem")
        .is_("ocr_texto", "null")
        .or_(_FILTRO_OCR_URL_GOOGLE_WORKER)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def _contar_pendentes_worker(sb, user_id: str, empresa: str) -> int:
    res = (
        sb.table("midias")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("empresa", empresa)
        .eq("tipo", "imagem")
        .is_("ocr_texto", "null")
        .or_(_FILTRO_OCR_URL_GOOGLE_WORKER)
        .execute()
    )
    return int(res.count or 0)


def _processar_atividade_worker(sb, atividade: dict):
    atividade_id = atividade["id"]
    user_id = atividade["user_id"]
    det = atividade.get("detalhes") or {}
    empresa = str(det.get("empresa") or "")
    processadas = int(det.get("processadas") or 0)
    total = max(
        int(det.get("total") or 0),
        processadas + _contar_pendentes_worker(sb, user_id, empresa),
    )

    _atividade_update_worker(
        sb,
        atividade_id,
        "em_andamento",
        {
            "empresa": empresa,
            "processadas": processadas,
            "total": total,
            "worker": "externo",
            "worker_externo": True,
            "ultimo_heartbeat_em": _agora_iso_worker(),
            "aviso": "OCR em processamento no worker externo.",
        },
    )

    print(
        f"[OCR-WORKER] atividade INICIO id={atividade_id} "
        f"empresa={empresa!r} processadas={processadas}/{total}",
        flush=True,
    )

    erros = []

    while True:
        midia = _buscar_midia_pendente_worker(sb, user_id, empresa)
        if not midia:
            break

        midia_id = str(midia.get("id") or "")
        url_cdn = str(midia.get("url_cdn") or "")

        if not url_cdn:
            erros.append({
                "id": midia_id,
                "etapa": "worker_externo",
                "erro": "url_cdn ausente",
            })
            # Não há coluna de erro garantida. Para evitar loop infinito,
            # encerra a atividade e deixa a mídia pendente para Refazer.
            break

        try:
            print(
                f"[OCR-WORKER] imagem INICIO id={midia_id} "
                f"empresa={empresa!r} RSS={_rss_processo_mb():.1f} MB",
                flush=True,
            )

            estruturado, diag = _extrair_ocr_estruturado_imagem(
                url_cdn,
                empresa=empresa,
                retornar_diagnostico=True,
            )

            if estruturado is None:
                erros.append({
                    "id": midia_id,
                    "etapa": str((diag or {}).get("etapa") or "ocr"),
                    "erro": str(
                        (diag or {}).get("erro")
                        or "A extração OCR retornou vazio."
                    ),
                    "url_cdn": url_cdn,
                    "url_origem": str(midia.get("url_origem") or ""),
                })
                break

            texto = _achatar_ocr_estruturado(estruturado)
            sb.table("midias").update({
                "ocr_texto": texto or "",
                "ocr_estruturado": (
                    json.dumps(estruturado, ensure_ascii=False)
                    if _ocr_estruturado_tem_conteudo(estruturado)
                    else None
                ),
            }).eq("id", midia_id).execute()

            processadas += 1

            _atividade_update_worker(
                sb,
                atividade_id,
                "em_andamento",
                {
                    "empresa": empresa,
                    "processadas": processadas,
                    "total": max(total, processadas),
                    "worker": "externo",
                    "worker_externo": True,
                    "ultimo_heartbeat_em": _agora_iso_worker(),
                    "aviso": (
                        f"OCR em processamento — "
                        f"{processadas} de {max(total, processadas)}."
                    ),
                },
            )

            print(
                f"[OCR-WORKER] imagem FIM id={midia_id} "
                f"processadas={processadas}/{max(total, processadas)} "
                f"RSS={_rss_processo_mb():.1f} MB",
                flush=True,
            )

            # O Reader permanece carregado NESTE container de worker.
            # Isso é intencional: não afeta a RAM do Streamlit e evita
            # recarregar ~800 MB de modelo para cada imagem.

        except BaseException as exc:
            erros.append({
                "id": midia_id,
                "etapa": "worker_externo",
                "erro": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
                "url_cdn": url_cdn,
                "url_origem": str(midia.get("url_origem") or ""),
            })
            break

    restantes = _contar_pendentes_worker(sb, user_id, empresa)

    if erros:
        _atividade_update_worker(
            sb,
            atividade_id,
            "erro",
            {
                "empresa": empresa,
                "processadas": processadas,
                "total": max(total, processadas + restantes),
                "worker": "externo",
                "worker_externo": True,
                "ultimo_heartbeat_em": _agora_iso_worker(),
                "aviso": (
                    f"{len(erros)} mídia(s) falharam. "
                    "Use Refazer após corrigir/verificar."
                ),
                "erros_detalhados": erros[:20],
                "total_erros_detalhados": len(erros),
            },
        )
        print(
            f"[OCR-WORKER] atividade ERRO id={atividade_id} "
            f"empresa={empresa!r} restantes={restantes}",
            flush=True,
        )
        return

    _atividade_update_worker(
        sb,
        atividade_id,
        "concluido",
        {
            "empresa": empresa,
            "processadas": processadas,
            "total": max(total, processadas),
            "worker": "externo",
            "worker_externo": True,
            "ultimo_heartbeat_em": _agora_iso_worker(),
        },
    )
    print(
        f"[OCR-WORKER] atividade CONCLUIDA id={atividade_id} "
        f"empresa={empresa!r} processadas={processadas}",
        flush=True,
    )


def _daemon_worker():
    sb = _supabase_worker()
    poll = max(2.0, float(os.environ.get("OCR_POLL_SECONDS", "5")))
    print(
        f"[OCR-WORKER] daemon iniciado poll={poll}s "
        f"RSS={_rss_processo_mb():.1f} MB",
        flush=True,
    )

    while True:
        try:
            atividade = _buscar_proxima_atividade_worker(sb)
            if atividade:
                _processar_atividade_worker(sb, atividade)
            else:
                time.sleep(poll)
        except KeyboardInterrupt:
            print("[OCR-WORKER] encerrado por sinal", flush=True)
            return 0
        except BaseException as exc:
            print(
                f"[OCR-WORKER] loop ERRO {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            traceback.print_exc()
            time.sleep(min(30.0, poll * 2))


def _cli_single_image():
    if len(sys.argv) != 3:
        print("uso: ocr_worker.py <input.json> <output.json>", file=sys.stderr)
        return 2

    entrada, saida = sys.argv[1], sys.argv[2]
    _mem_snapshot_ocr('worker inicio')
    try:
        with open(entrada, "r", encoding="utf-8") as f:
            payload = json.load(f)

        empresa = payload.get("empresa")
        item = payload.get("item") or {}
        midia_id = str(item.get("id") or "")
        url_cdn = str(item.get("url_cdn") or "")
        if not url_cdn:
            raise RuntimeError("url_cdn ausente")

        estruturado, diag = _extrair_ocr_estruturado_imagem(
            url_cdn,
            empresa=empresa,
            retornar_diagnostico=True,
        )
        resultado = {
            "ok": estruturado is not None,
            "id": midia_id,
            "estruturado": estruturado,
            "diag": diag,
        }
        with open(saida, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False)
        _mem_snapshot_ocr('worker fim antes return')
        return 0 if resultado["ok"] else 3
    except BaseException as exc:
        try:
            with open(saida, "w", encoding="utf-8") as f:
                json.dump({
                    "ok": False,
                    "erro": f"{type(exc).__name__}: {exc}",
                    "diag": {
                        "etapa": "worker_externo",
                        "erro": f"{type(exc).__name__}: {exc}",
                    },
                }, f, ensure_ascii=False)
        except Exception:
            pass
        return 4


if __name__ == "__main__":
    # Sem argumentos = serviço/daemon externo.
    # Com dois argumentos = compatibilidade com teste local de uma imagem.
    if len(sys.argv) == 1:
        raise SystemExit(_daemon_worker() or 0)
    raise SystemExit(_cli_single_image())
