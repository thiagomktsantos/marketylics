from playwright.sync_api import sync_playwright
import streamlit as st
import streamlit.components.v1 as components
import google.generativeai as genai
import pandas as pd
import re
import unicodedata
import trafilatura
import requests
from supabase import create_client, Client

# ---------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ---------------------------------------------------

st.set_page_config(
    page_title="Marketylics · Competitive Intelligence",
    page_icon="https://raw.githubusercontent.com/thiagomktsantos/marketylics/231a39c102b672fbb803b0ecf335febdd119d3b1/images/favicon.jpg",
    layout="wide"
)

# ---------------------------------------------------
#  SUPABASE
# ---------------------------------------------------

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = get_supabase()

# ---------------------------------------------------
# CONFIGURAÇÃO GEMINI
# ---------------------------------------------------

if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    gemini_model = genai.GenerativeModel("gemini-2.5-flash")
else:
    gemini_model = None

# ---------------------------------------------------
# LISTA ESTADOS E CIDADES
# ---------------------------------------------------

ESTADOS_CIDADES = {
    "Acre": ["Rio Branco", "Cruzeiro do Sul"],
    "Alagoas": ["Maceió", "Arapiraca"],
    "Amapá": ["Macapá", "Santana"],
    "Amazonas": ["Manaus", "Parintins"],
    "Bahia": ["Salvador", "Feira de Santana"],
    "Ceará": ["Fortaleza", "Juazeiro do Norte", "Sobral"],
    "Distrito Federal": ["Brasília"],
    "Espírito Santo": ["Vitória", "Vila Velha"],
    "Goiás": ["Goiânia", "Anápolis"],
    "Maranhão": ["São Luís", "Imperatriz"],
    "Mato Grosso": ["Cuiabá", "Rondonópolis"],
    "Mato Grosso do Sul": ["Campo Grande", "Dourados"],
    "Minas Gerais": ["Belo Horizonte", "Uberlândia"],
    "Pará": ["Belém", "Santarém"],
    "Paraíba": ["João Pessoa", "Campina Grande"],
    "Paraná": ["Curitiba", "Londrina"],
    "Pernambuco": ["Recife", "Caruaru"],
    "Piauí": ["Teresina", "Parnaíba"],
    "Rio de Janeiro": ["Rio de Janeiro", "Niterói"],
    "Rio Grande do Norte": ["Natal", "Mossoró"],
    "Rio Grande do Sul": ["Porto Alegre", "Caxias do Sul"],
    "Rondônia": ["Porto Velho", "Ji-Paraná"],
    "Roraima": ["Boa Vista"],
    "Santa Catarina": ["Florianópolis", "Joinville"],
    "São Paulo": ["São Paulo", "Campinas", "Santos"],
    "Sergipe": ["Aracaju"],
    "Tocantins": ["Palmas"]
}

SUBNICHOS = {
    "Alimentação": ["Restaurante", "Delivery", "Confeitaria", "Padaria", "Lanchonete", "Food Truck", "Catering", "Franquia de Alimentação"],
    "Marketing": ["Agência Digital", "Marketing de Conteúdo", "SEO", "Tráfego Pago", "Social Media", "Branding", "Email Marketing", "Inbound Marketing"],
    "Tecnologia": ["Software House", "SaaS", "Consultoria TI", "Segurança", "Dados & BI", "Mobile", "Cloud", "Inteligência Artificial"],
    "Varejo": ["E-commerce", "Moda", "Eletrônicos", "Alimentos", "Farmácia", "Pet Shop", "Decoração", "Esportes"],
    "Saúde": ["Clínica Médica", "Odontologia", "Psicologia", "Nutrição", "Fisioterapia", "Academia", "Farmácia", "Estética"],
    "Educação": ["Escola", "Curso Online", "Coaching", "Consultoria", "Idiomas", "Pré-vestibular", "Creche", "Faculdade"],
    "Indústria": ["Manufatura", "Construção", "Agronegócio", "Química", "Têxtil", "Metalurgia", "Energia", "Logística"],
}

# ---------------------------------------------------
# PALETA DE CORES GLOBAL PARA AVATARES
# ---------------------------------------------------

AVATAR_COLORS = ["#27ae60", "#3a9fd6", "#2ecc71", "#5bc4f5", "#1a7abf", "#1a2e4a"]

def get_avatar_color(index: int) -> str:
    return AVATAR_COLORS[index % len(AVATAR_COLORS)]

def get_minha_empresa_color() -> str:
    return AVATAR_COLORS[0]

def get_concorrente_color(concorrente_index: int) -> str:
    return AVATAR_COLORS[(concorrente_index + 1) % len(AVATAR_COLORS)]

# ---------------------------------------------------
# FUNÇÕES AUXILIARES
# ---------------------------------------------------

def remover_acentos(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

def limpar_site(url):
    if not url:
        return ""
    url = url.strip().lower()
    url = re.sub(r"^https?:\/\/", "", url, flags=re.IGNORECASE)
    url = re.sub(r"^www\.", "", url, flags=re.IGNORECASE)
    url = remover_acentos(url)
    url = re.sub(r"[^a-z0-9\.\-\/]", "", url)
    url = url.rstrip("/")
    return url

def gerar_avatar(nome):
    nome = nome.strip().upper()
    if not nome:
        return "?"
    partes = nome.split()
    if len(partes) == 1:
        return partes[0][0]
    return partes[0][0] + partes[1][0]

def obter_instagram_handle(valor):
    if not valor:
        return ""
    valor = valor.strip()
    valor = re.sub(r"^https?:\/\/(www\.)?instagram\.com\/", "", valor, flags=re.IGNORECASE)
    valor = valor.strip("/")
    valor = valor.lstrip("@")
    if valor:
        valor = "@" + valor
    return valor

def obter_facebook_handle(valor):
    if not valor:
        return ""
    valor = valor.strip()
    valor = re.sub(r"^https?:\/\/(www\.)?facebook\.com\/", "", valor, flags=re.IGNORECASE)
    valor = valor.strip("/")
    return valor

def empresa_tem_dados(emp):
    return bool(emp.get("nome", "").strip())

def formatar_url(url):
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url

# ---------------------------------------------------
# SUPABASE — USUÁRIOS / AUTH
# ---------------------------------------------------

def login_supabase(email: str, senha: str):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": senha})
        return res.user, None
    except Exception as e:
        return None, str(e)

def cadastro_supabase(email: str, senha: str):
    try:
        res = supabase.auth.sign_up({"email": email, "password": senha})
        return res.user, None
    except Exception as e:
        return None, str(e)

def logout_supabase():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass

# ---------------------------------------------------
# SUPABASE — DADOS DO USUÁRIO
# ---------------------------------------------------

def carregar_dados_usuario(user_id: str) -> dict:
    try:
        res = supabase.table("ci_dados").select("*").eq("user_id", user_id).execute()
        if res.data:
            row = res.data[0]
            return {
                "minha_empresa": row.get("minha_empresa", {}),
                "concorrentes": row.get("concorrentes", []),
                "metricas_redes": row.get("metricas_redes", {}),
                "ads_cache": row.get("ads_cache", {}),
                "analises_salvas": row.get("analises_salvas", []),
            }
    except Exception:
        pass
    return {
        "minha_empresa": {
            "nome": "", "setor": "Marketing", "tipo": "",
            "estado": "", "cidade": "",
            "instagram": "@", "fb_page": "", "site": "",
            "servicos": [], "ads_id": "", "ads_page_pic": ""
        },
        "concorrentes": [],
        "metricas_redes": {},
        "ads_cache": {},
        "analises_salvas": [],
    }

def salvar_dados_usuario(user_id: str):
    try:
        payload = {
            "user_id": user_id,
            "minha_empresa": st.session_state.dados["minha_empresa"],
            "concorrentes": st.session_state.dados["concorrentes"],
            "metricas_redes": st.session_state.metricas_redes,
            "analises_salvas": st.session_state.get("analises_salvas", []),
        }
        supabase.table("ci_dados").upsert(payload, on_conflict="user_id").execute()
    except Exception as e:
        st.toast(f"⚠️ Erro ao salvar: {e}", icon="⚠️")

# ---------------------------------------------------
# ESTADO DA SESSÃO
# ---------------------------------------------------

if "logado" not in st.session_state:
    st.session_state.logado = False
if "user" not in st.session_state:
    st.session_state.user = None
if "auth_tab" not in st.session_state:
    st.session_state.auth_tab = "login"
if "dados" not in st.session_state:
    st.session_state.dados = {
        "minha_empresa": {
            "nome": "", "setor": "Marketing", "tipo": "",
            "estado": "", "cidade": "",
            "instagram": "@", "fb_page": "", "site": "",
            "servicos": [], "ads_id": "", "ads_page_pic": ""
        },
        "concorrentes": []
    }
if "metricas_redes" not in st.session_state:
    st.session_state.metricas_redes = {}
if "pagina" not in st.session_state:
    st.session_state.pagina = "home"
if "mostrar_form_concorrente" not in st.session_state:
    st.session_state.mostrar_form_concorrente = False
if "editando_concorrente" not in st.session_state:
    st.session_state.editando_concorrente = None
if "editar_empresa" not in st.session_state:
    st.session_state.editar_empresa = False
if "relatorio_sites" not in st.session_state:
    st.session_state.relatorio_sites = {}
if "relatorio_gemini" not in st.session_state:
    st.session_state.relatorio_gemini = ""
if "analises_salvas" not in st.session_state:
    st.session_state.analises_salvas = []

empresa = st.session_state.dados["minha_empresa"]
campos_padrao = {
    "estado": "", "cidade": "", "instagram": "@",
    "fb_page": "", "site": "", "servicos": [], "ads_id": "", "ads_page_pic": ""
}
for campo, valor in campos_padrao.items():
    if campo not in empresa:
        empresa[campo] = valor

# ---------------------------------------------------
# CONTROLE NAVEGAÇÃO
# ---------------------------------------------------

def trocar_pagina(destino):
    st.session_state.pagina = destino
    st.session_state.mostrar_form_concorrente = False
    st.session_state.editando_concorrente = None
    st.session_state.editar_empresa = False

# ---------------------------------------------------
# FUNÇÃO IA — BATTLE CARD
# ---------------------------------------------------

def consultar_ia(prompt):
    if gemini_model is None:
        return "Erro: Chave API Gemini não configurada."
    try:
        emp = st.session_state.dados["minha_empresa"]
        contexto = f"""
Empresa: {emp['nome']}
Setor: {emp['setor']}
Instagram: {emp['instagram']}
"""
        resposta = gemini_model.generate_content(contexto + "\n" + prompt)
        return resposta.text
    except Exception as e:
        return f"Erro: {str(e)}"

# ---------------------------------------------------
# TRAFILATURA — EXTRAÇÃO DE CONTEÚDO
# ---------------------------------------------------

def extrair_conteudo_site(url: str) -> str:
    url_fmt = formatar_url(url)
    if not url_fmt:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        resp = requests.get(url_fmt, headers=headers, timeout=15, allow_redirects=True)
        resp.encoding = resp.apparent_encoding
        html = resp.text

        texto = trafilatura.extract(
            html,
            include_tables=True,
            include_links=False,
            include_images=False,
            no_fallback=False,
            favor_recall=True,
        )
        if texto and len(texto) > 100:
            return texto

        import re as _re
        texto_bruto = _re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=_re.DOTALL)
        texto_bruto = _re.sub(r"<style[^>]*>.*?</style>", " ", texto_bruto, flags=_re.DOTALL)
        texto_bruto = _re.sub(r"<[^>]+>", " ", texto_bruto)
        texto_bruto = _re.sub(r"\s+", " ", texto_bruto).strip()
        return texto_bruto[:5000] if texto_bruto else ""
    except Exception as e:
        return f"[Erro ao acessar {url}: {e}]"

# ---------------------------------------------------
# GEMINI — RELATÓRIO DE POSICIONAMENTO
# ---------------------------------------------------

def gerar_relatorio_posicionamento(empresa_principal: dict, concorrentes_data: list) -> str:
    if gemini_model is None:
        return "Erro: Chave API Gemini não configurada."

    secoes = []
    if empresa_principal.get("conteudo"):
        secoes.append(f"""
## MINHA EMPRESA — {empresa_principal['nome']} ({empresa_principal['url']})
{empresa_principal['conteudo'][:3000]}
""")

    for c in concorrentes_data:
        if c.get("conteudo"):
            secoes.append(f"""
## CONCORRENTE — {c['nome']} ({c['url']})
{c['conteudo'][:3000]}
""")

    if not secoes:
        return "Nenhum conteúdo extraído dos sites para análise."

    prompt = f"""
Você é um especialista em marketing digital e inteligência competitiva.
Analise o conteúdo extraído dos sites abaixo e gere um **Relatório de Posicionamento Competitivo** completo em português.

{''.join(secoes)}

---

O relatório deve conter:

### 1. 📌 Proposta de Valor
Para cada empresa, identifique a proposta de valor central comunicada no site.

### 2. 🎯 Posicionamento de Mercado
Como cada empresa se posiciona? (premium, popular, nicho, generalista etc.)

### 3. 🔑 Palavras-chave e Mensagens Principais
Quais termos, promessas e mensagens cada empresa repete com mais frequência?

### 4. 🛠️ Serviços e Diferenciais
Liste os principais serviços/produtos destacados por cada empresa.

### 5. ⚔️ Análise Competitiva
Compare minha empresa com os concorrentes. Onde estamos mais fortes? Onde estamos vulneráveis?

### 6. 💡 Recomendações Estratégicas
Com base na análise, sugira 3 a 5 ações concretas para melhorar o posicionamento da minha empresa.

Seja direto, objetivo e use dados do conteúdo real dos sites.
"""

    try:
        resposta = gemini_model.generate_content(prompt)
        return resposta.text
    except Exception as e:
        return f"Erro ao gerar relatório: {e}"

# ---------------------------------------------------
# CSS GLOBAL
# ---------------------------------------------------

st.markdown("""
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
    font-weight: normal;
    font-style: normal;
}

@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif !important; }

[data-testid="stSidebar"] {
    background-color: #0f1117 !important;
    border-right: 1px solid #1e2530 !important;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }

section.main .block-container {
    padding: 2rem 2.5rem !important;
    max-width: 1100px !important;
    background: #f0f4f8 !important;
}

[data-testid="stAppViewContainer"] { background: #f0f4f8 !important; }
section.main { background: #f0f4f8 !important; }

.page-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 28px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;
}
.page-title { font-size: 28px; font-weight: 600; color: #111827; letter-spacing: -0.5px; margin: 0; font-family: 'Animo', 'DM Sans', sans-serif; }
.page-subtitle { font-size: 16px; color: #6b7280; margin-top: 3px; }

section.main div.stButton > button {
    border-radius: 8px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    border: 1px solid #d1d5db !important;
    background: #ffffff !important;
    color: #374151 !important;
    box-shadow: none !important;
    padding: 8px 16px !important;
    min-height: 40px !important;
    transition: all 0.12s ease !important;
    font-family: 'DM Sans', sans-serif !important;
}
section.main div.stButton > button:hover {
    background: #f9fafb !important;
    border-color: #9ca3af !important;
    color: #111827 !important;
}

section.main div.stButton > button[kind="primary"],
[data-testid="stMainBlockContainer"] button[kind="primary"],
button[data-testid="baseButton-primary"],
div.stButton > button[kind="primary"] {
    background: #0780c0 !important;
    color: #ffffff !important;
    border: none !important;
    opacity: 1 !important;
}
section.main div.stButton > button[kind="primary"]:hover,
[data-testid="stMainBlockContainer"] button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover,
div.stButton > button[kind="primary"]:hover {
    background: #065f9e !important;
    color: #ffffff !important;
    opacity: 1 !important;
}

section.main div.stFormSubmitButton > button {
    background: #111827 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    min-height: 40px !important;
    font-family: 'DM Sans', sans-serif !important;
    transition: all 0.12s ease !important;
}
section.main div.stFormSubmitButton > button:hover {
    background: #1f2937 !important;
}

.form-section-header {
    font-size: 13px; font-weight: 600; color: #6b7280;
    text-transform: uppercase; letter-spacing: 0.8px;
    padding: 20px 0 12px 0; border-bottom: 1px solid #f3f4f6;
    margin-bottom: 16px; font-family: 'DM Sans', sans-serif;
}

section.main div[data-testid="stTextInput"] input,
section.main div[data-testid="stSelectbox"] select,
section.main div[data-baseweb="select"] {
    font-size: 15px !important; border-radius: 7px !important;
    border: 1px solid #e5e7eb !important;
    font-family: 'DM Sans', sans-serif !important; color: #111827 !important;
}
section.main label {
    font-size: 14px !important; font-weight: 500 !important;
    color: #374151 !important; font-family: 'DM Sans', sans-serif !important;
    margin-bottom: 4px !important;
}
section.main h1, section.main h2, section.main h3 {
    font-family: 'Animo', 'DM Sans', sans-serif !important;
}
section.main h1 { font-size: 28px !important; font-weight: 600 !important; color: #111827 !important; }
section.main h2 { font-size: 20px !important; font-weight: 600 !important; color: #111827 !important; margin-top: 28px !important; }
section.main h3 { font-size: 16px !important; font-weight: 600 !important; color: #374151 !important; }
section.main hr { border: none !important; border-top: 1px solid #f3f4f6 !important; margin: 20px 0 !important; }

div[data-testid="stInfo"] {
    background: #f0f9ff !important; border: 1px solid #bae6fd !important;
    border-radius: 8px !important; font-size: 15px !important;
    color: #0c4a6e !important; padding: 14px 18px !important;
}
div[data-testid="stWarning"] {
    background: #fffbeb !important; border: 1px solid #fcd34d !important;
    border-radius: 8px !important; font-size: 15px !important; padding: 14px 18px !important;
}
div[data-testid="stSuccess"] {
    background: #f0fdf4 !important; border: 1px solid #86efac !important;
    border-radius: 8px !important; font-size: 15px !important; padding: 14px 18px !important;
}
div[data-testid="stError"] {
    background: #fef2f2 !important; border: 1px solid #fca5a5 !important;
    border-radius: 8px !important; font-size: 15px !important; padding: 14px 18px !important;
}

details summary { font-size: 16px !important; font-weight: 500 !important; padding: 14px 0 !important; }

.popup-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    z-index: 999999; backdrop-filter: blur(2px);
}
.popup-box {
    position: fixed; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    background: #ffffff; width: 480px; border-radius: 14px;
    padding: 32px; z-index: 9999999; border: 1px solid #e5e7eb;
    color: #111827; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.popup-title { font-size: 20px; font-weight: 600; margin-bottom: 10px; color: #111827; }
.popup-text { color: #6b7280; margin-bottom: 24px; font-size: 15px; line-height: 1.6; }

div[data-baseweb="select"] > div {
    border-radius: 7px !important; min-height: 42px !important;
    font-size: 15px !important; font-family: 'DM Sans', sans-serif !important;
}
div[data-testid="stDataFrame"] {
    border-radius: 10px !important; overflow: hidden !important; border: 1px solid #e5e7eb !important;
}
section.main div[data-testid="stTextArea"] textarea {
    font-size: 15px !important; border-radius: 7px !important;
    border: 1px solid #e5e7eb !important;
    font-family: 'DM Sans', sans-serif !important;
    color: #111827 !important; resize: vertical !important;
}

div[data-testid="stTabs"] > div:first-child {
    justify-content: center !important; border-bottom: 2px solid #e5e7eb !important; gap: 0 !important;
}
div[data-testid="stTabs"] button[role="tab"] {
    font-size: 15px !important;
    font-weight: 600 !important;
    font-family: 'DM Sans', sans-serif !important;
    padding: 10px 32px !important;
    color: #9ca3af !important;
    border-radius: 8px 8px 0px 0px !important;
    margin-bottom: -2px !important;
    text-transform: uppercase;
}
div[data-testid="stTabs"] button[role="tab"] p,
div[data-testid="stTabs"] button[role="tab"] div,
div[data-testid="stTabs"] button[role="tab"] [data-testid="stMarkdownContainer"],
div[data-testid="stTabs"] button[role="tab"] [data-testid="stMarkdownContainer"] p {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    margin: 0 !important;
    padding: 0 !important;
    text-transform: uppercase;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #fff !important;
    background-color: #3a9fd6 !important;
}

.sb-logo { padding:22px 18px 16px; border-bottom:1px solid #1e2530; margin-bottom:8px; }
.sb-logo-sub { font-size:8.4px; color:#3a9fd6; font-weight:600; letter-spacing:2px; text-transform:uppercase; text-align:center; font-family:'DM Sans',sans-serif; }

[data-testid="stSidebar"] div.stButton > button {
    position: fixed !important;
    top: -9999px !important;
    left: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    visibility: hidden !important;
}
[data-testid="stSidebar"] .stElementContainer:has(div.stButton) {
    margin: 0 !important;
    padding: 0 !important;
    height: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
    line-height: 0 !important;
    display: none !important;
}

/* ─────────────────────────────────────────────────────
   CONTAINERS COM BORDA — fundo branco FORÇADO
   ───────────────────────────────────────────────────── */
section.main [data-testid="stVerticalBlockBorderWrapper"],
section.main [data-testid="stVerticalBlockBorderWrapper"] > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] > div > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] > div > div > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] > div > div > div > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"],
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHorizontalBlock"],
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stLayoutWrapper"],
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stLayoutWrapper"] > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stLayoutWrapper"] > div > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="column"],
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="column"] > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] [data-testid="column"] > div > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] .stElementContainer,
section.main [data-testid="stVerticalBlockBorderWrapper"] .stElementContainer > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] .stElementContainer > div > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stForm"],
section.main [data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stForm"] > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stForm"] > div > div,
section.main [data-testid="stVerticalBlockBorderWrapper"] [class^="st-emotion-cache-"],
section.main [data-testid="stVerticalBlockBorderWrapper"] [class*=" st-emotion-cache-"] {
    background: #ffffff !important;
    background-color: #ffffff !important;
}

section.main [data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid #e5e7eb !important;
    border-radius: 14px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
}

section.main [data-testid="stVerticalBlockBorderWrapper"] input,
section.main [data-testid="stVerticalBlockBorderWrapper"] textarea {
    background: #ffffff !important;
    background-color: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 7px !important;
    font-size: 15px !important;
    color: #111827 !important;
}

section.main [data-testid="stVerticalBlockBorderWrapper"] [data-baseweb="select"] > div {
    background: #ffffff !important;
    background-color: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 7px !important;
}

section.main [data-testid="stVerticalBlockBorderWrapper"] iframe,
section.main [data-testid="stVerticalBlockBorderWrapper"] canvas,
section.main [data-testid="stVerticalBlockBorderWrapper"] img,
section.main [data-testid="stVerticalBlockBorderWrapper"] svg,
section.main [data-testid="stVerticalBlockBorderWrapper"] video {
    background: transparent !important;
    background-color: transparent !important;
}

button[data-testid="baseButton-secondary"][kind="secondary"]:has(~ *) {
    display: none !important;
}

/* ── OCULTAR campo ads_id no formulário de concorrentes ── */
.st-key-ads_id_hidden {
    display: none !important;
    height: 0 !important;
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
}
</style>
""", unsafe_allow_html=True)

# ── Força fundo branco via JavaScript — bypass garantido do st-emotion-cache ──
components.html("""
<script>
(function() {
    var TAGS_IGNORADAS = ['iframe','canvas','img','svg','video','input','textarea','select','option'];

    function forcarBranco() {
        var containers = window.parent.document.querySelectorAll(
            '[data-testid="stVerticalBlockBorderWrapper"], ' +
            '[data-testid="stVerticalBlockBorderWrapper"] *'
        );
        containers.forEach(function(el) {
            if (TAGS_IGNORADAS.indexOf(el.tagName.toLowerCase()) === -1) {
                el.style.setProperty('background', '#ffffff', 'important');
                el.style.setProperty('background-color', '#ffffff', 'important');
            }
        });
    }

    forcarBranco();
    setTimeout(forcarBranco, 200);
    setTimeout(forcarBranco, 500);
    setTimeout(forcarBranco, 1000);
    setTimeout(forcarBranco, 2000);

    var observer = new MutationObserver(function() {
        forcarBranco();
    });

    observer.observe(window.parent.document.body, {
        childList: true,
        subtree: true,
        attributes: false
    });
})();
</script>
""", height=0)

# ---------------------------------------------------
# CARD HELPERS
# ---------------------------------------------------

CARD_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
html, body {
    background: transparent;
    font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    -webkit-font-smoothing: antialiased;
    overflow: visible;
}
body { padding-bottom: 8px; }
"""
CARD_FONT_IMPORT = """<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">"""

# ---------------------------------------------------
# LOGIN / CADASTRO (Supabase Auth)
# ---------------------------------------------------

import base64
from pathlib import Path

def get_logo_base64():
    logo_path = Path("images/logo-marketylics.jpg")
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

def get_logo_white_base64():
    logo_path = Path("images/logo-marketylics-white.png")
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

if not st.session_state.logado:
    logo_b64 = get_logo_base64()
    logo_src = f"data:image/jpeg;base64,{logo_b64}" if logo_b64 else ""

    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif !important; }

    header, #MainMenu, [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }

    [data-testid="stAppViewContainer"] { background: #f0f2f5 !important; }

    section.main .block-container {
        max-width: 440px !important;
        padding: 48px 24px !important;
        margin: 0 auto !important;
        background: transparent !important;
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        border: none !important;
        background: #ffffff !important;
        border-radius: 16px !important;
        box-shadow: 0 2px 20px rgba(0,0,0,0.08) !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] > div,
    [data-testid="stVerticalBlockBorderWrapper"] > div > div,
    [data-testid="stVerticalBlock"],
    div[data-testid="stForm"],
    div[data-testid="stForm"] > div,
    div[data-baseweb="tab-panel"] {
        background: #ffffff !important;
        border: none !important;
        border-radius: 16px !important;
    }
    [data-testid="stVerticalBlock"] {
        width: 100% !important;
        max-width: 440px !important;
        margin: 0 auto !important;
    }
    div[class*="st-emotion-cache"] {
        border-color: transparent !important;
    }

    div[data-testid="stTextInput"] input {
        border: 1.5px solid #e5e7eb !important;
        border-radius: 8px !important;
        background: #fafafa !important;
        font-size: 15px !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #3a9fd6 !important;
        background: #fff !important;
        box-shadow: none !important;
    }

    div.stFormSubmitButton > button {
        background: linear-gradient(135deg, #3a9fd6 0%, #2ecc71 100%) !important;
        color: #fff !important;
        border: none !important;
        border-radius: 8px !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        padding: 12px !important;
        width: 100% !important;
        margin-bottom: 15px;
    }
    div.stFormSubmitButton > button:hover { opacity: 0.9 !important; }

    div[data-testid="stTabs"] > div:first-child {
        justify-content: center !important;
        border-bottom: 2px solid #e5e7eb !important;
        gap: 0 !important;
        margin-bottom: 8px !important;
    }
    div[data-testid="stTabs"] button[role="tab"] {
        font-size: 18px !important;
        font-weight: 900 !important;
        font-family: 'DM Sans', sans-serif !important;
        padding: 8px 0 !important;
        color: #9ca3af !important;
        border-radius: 8px 8px 0px 0px !important;
        margin-bottom: -2px !important;
        background: transparent !important;
        box-shadow: none !important;
        flex: 1 !important;
        text-align: center !important;
    }
    div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        color: #fff !important;
        background-color: #3a9fd6 !important;
    }
    div[data-testid="stTabs"] button[role="tab"]:focus,
    div[data-testid="stTabs"] button[role="tab"]:focus-visible {
        box-shadow: none !important;
        outline: none !important;
    }
    div[data-baseweb="tab-highlight"] {
        background-color: #3a9fd6 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown(f"""
        <div style="text-align:center;margin-bottom:24px">
            {'<img src="' + logo_src + '" style="width:200px;" />' if logo_src else '<div style="font-size:24px;font-weight:700;color:#1a2234">Marketylics</div>'}
            <div style="font-size:10.9px;color:#3a9fd6;font-weight:600;letter-spacing:2px;text-transform:uppercase">Competitive Intelligence</div>
        </div>
        """, unsafe_allow_html=True)

        aba = st.tabs(["Já tenho conta", "Criar conta"])

        with aba[0]:
            with st.form("form_login"):
                email_login = st.text_input("E-mail", placeholder="seu@email.com")
                senha_login = st.text_input("Senha", type="password", placeholder="••••••••")
                submit_login = st.form_submit_button("Entrar na plataforma →", use_container_width=True)

            if submit_login:
                if email_login and senha_login:
                    with st.spinner("Autenticando..."):
                        user, err = login_supabase(email_login, senha_login)
                    if user:
                        st.session_state.logado = True
                        st.session_state.user = user
                        dados_db = carregar_dados_usuario(user.id)
                        minha_emp = dados_db["minha_empresa"] or {
                            "nome": "", "setor": "Marketing", "tipo": "",
                            "estado": "", "cidade": "",
                            "instagram": "@", "fb_page": "", "site": "",
                            "servicos": [], "ads_id": "", "ads_page_pic": ""
                        }
                        if "ads_id" not in minha_emp:
                            minha_emp["ads_id"] = ""
                        if "ads_page_pic" not in minha_emp:
                            minha_emp["ads_page_pic"] = ""
                        st.session_state.dados = {
                            "minha_empresa": minha_emp,
                            "concorrentes": dados_db.get("concorrentes", []),
                        }
                        st.session_state.metricas_redes = dados_db.get("metricas_redes", {})
                        st.session_state.ads_cache = dados_db.get("ads_cache", {})
                        st.session_state.analises_salvas = dados_db.get("analises_salvas", [])  
                        st.rerun()
                    else:
                        st.error(f"Erro ao entrar: {err}")
                else:
                    st.warning("Preencha e-mail e senha.")

        with aba[1]:
            with st.form("form_cadastro"):
                email_cad  = st.text_input("E-mail", placeholder="seu@email.com", key="cad_email")
                senha_cad  = st.text_input("Senha", type="password", placeholder="Mínimo 6 caracteres", key="cad_senha")
                senha_cad2 = st.text_input("Confirmar senha", type="password", placeholder="Repita a senha", key="cad_senha2")
                submit_cad = st.form_submit_button("Criar conta", use_container_width=True)

            if submit_cad:
                if not email_cad or not senha_cad:
                    st.warning("Preencha todos os campos.")
                elif senha_cad != senha_cad2:
                    st.error("As senhas não coincidem.")
                elif len(senha_cad) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                else:
                    with st.spinner("Criando conta..."):
                        user, err = cadastro_supabase(email_cad, senha_cad)
                    if user:
                        st.success("Conta criada! Verifique seu e-mail para confirmar, depois faça login.")
                    else:
                        st.error(f"Erro: {err}")

        st.markdown("""
        <div style="text-align:center;font-size:11px;color:#696969;margin-bottom:16px">
            🔒 Conexão segura com criptografia SSL &nbsp;·&nbsp;
            <a href="#" style="color:#3a9fd6;text-decoration:none">Termos de Uso</a> &nbsp;·&nbsp;
            <a href="#" style="color:#3a9fd6;text-decoration:none">Privacidade</a>
        </div>
        """, unsafe_allow_html=True)

    st.stop()

# ---------------------------------------------------
# SIDEBAR (apenas quando logado)
# ---------------------------------------------------

with st.sidebar:

    logo_white_b64 = get_logo_white_base64()
    logo_white_src = f"data:image/png;base64,{logo_white_b64}" if logo_white_b64 else ""

    paginas = ["home", "cad", "geral", "redes", "sites", "ads", "insights", "sair"]
    for p in paginas:
        if st.button(p, key=f"_hidden_{p}"):
            if p == "sair":
                logout_supabase()
                for k in ["logado","user","dados","metricas_redes","pagina",
                          "mostrar_form_concorrente","editando_concorrente",
                          "editar_empresa","relatorio_sites","relatorio_gemini"]:
                    if k in st.session_state:
                        del st.session_state[k]
            else:
                trocar_pagina(p)
            st.rerun()

    pagina_atual = st.session_state.pagina
    user_email = st.session_state.user.email if st.session_state.user else ""

    menu_html = f"""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
 
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: #0d1117;
    font-family: 'DM Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}}
.logo-wrap {{
    text-align: center;
    padding: 28px 20px 20px;
}}
.logo-wrap img {{ width: 180px; display: block; margin: 0 auto 6px; }}
.logo-sub {{
    font-size: 8.3px; font-weight: 700; letter-spacing: 3px;
    text-transform: uppercase; color: #3a9fd6;
    font-family: 'DM Sans', sans-serif;
}}
.sec {{
    display: flex; align-items: center; gap: 10px;
    padding: 15px 14px 8px;
}}
.sec-dot {{
    width: 7px; height: 7px; border-radius: 50%;
    background: #3a9fd6; flex-shrink: 0;
}}
.sec-line {{ flex: 1; height: 1px; background: #1e2a3a; }}
.sec-label {{
    font-size: 10px; font-weight: 700; letter-spacing: 2px;
    text-transform: uppercase; color: #3a9fd6;
    white-space: nowrap;
}}
.nav-list {{ padding: 4px 10px; flex: 1; }}
.nav-item {{
    display: flex; align-items: center; gap: 14px;
    padding: 6px 16px;
    border-radius: 10px;
    margin-bottom: 3px;
    cursor: pointer;
    text-decoration: none;
    background: #131c2b;
    border: 1px solid #1e2a3a;
    transition: background 0.15s, border-color 0.15s;
    position: relative;
}}
.nav-item:hover {{
    background: #1a2535;
    border-color: #1e2a3a;
}}
.nav-item.active {{
    background: #0e2a47;
    border-color: #1e5a8a;
    border-left: 4px solid #00a7e3;
}}
.nav-icon {{
    width: 26px; text-align: center; flex-shrink: 0;
    font-size: 18px; color: #8a9bb0;
}}
.nav-item.active .nav-icon {{ color: #e2eaf5; }}
.nav-label {{
    font-size: 14px; font-weight: 600;
    color: #8a9bb0; flex: 1;
    letter-spacing: 0.1px;
}}
.nav-item.active .nav-label {{ color: #e2eaf5; }}
.nav-arrow {{
    font-size: 13px; color: #3a4f6a;
    flex-shrink: 0;
}}
.nav-item.active .nav-arrow {{ color: #3a9fd6; }}
.footer {{
    border-top: 1px solid #1e2a3a;
    padding: 16px 14px 12px;
    margin-top: auto;
}}
.footer-email {{
    display: flex; align-items: center; gap: 10px;
    margin-bottom: 12px;
}}
.footer-email i {{ font-size: 22px; color: #3a9fd6; }}
.footer-email span {{
    font-size: 13px; color: #5a7090;
    word-break: break-all;
    font-family: 'DM Sans', sans-serif;
}}
.btn-sair {{
    display: flex; align-items: center; justify-content: center;
    gap: 10px; width: 100%; padding: 7px 0;
    border: 1px solid #1e2a3a; border-radius: 10px;
    background: transparent; cursor: pointer;
    font-size: 15px; font-weight: 600; color: #5a7090;
    font-family: 'DM Sans', sans-serif;
    transition: all 0.15s;
}}
.btn-sair:hover {{
    background: #1a2535; color: #e2eaf5;
    border-color: #3a9fd6;
}}
.btn-sair i {{ font-size: 16px; }}
</style>
 
<body>
<div class="logo-wrap">
    {'<img src="' + logo_white_src + '" />' if logo_white_src else '<div style="font-size:20px;font-weight:700;color:#fff">Marketylics</div>'}
    <div class="logo-sub">Competitive Intelligence</div>
</div>
<div class="sec">
    <span class="sec-dot"></span>
    <span class="sec-label">Dados Principais</span>
    <span class="sec-line"></span>
</div>
<div class="nav-list">
    <a class="nav-item {'active' if pagina_atual == 'home' else ''}" onclick="nav('home')">
        <span class="nav-icon"><i class="fa-solid fa-building-columns"></i></span>
        <span class="nav-label">Minha Empresa</span>
    </a>
    <a class="nav-item {'active' if pagina_atual == 'cad' else ''}" onclick="nav('cad')">
        <span class="nav-icon"><i class="fa-solid fa-crosshairs"></i></span>
        <span class="nav-label">Concorrentes</span>
    </a>
</div>
<div class="sec">
    <span class="sec-dot"></span>
    <span class="sec-label">Análise Competitiva</span>
    <span class="sec-line"></span>
</div>
<div class="nav-list">
    <a class="nav-item {'active' if pagina_atual == 'geral' else ''}" onclick="nav('geral')">
        <span class="nav-icon"><i class="fa-solid fa-chart-bar"></i></span>
        <span class="nav-label">Dashboard Geral</span>
        <span class="nav-arrow"><i class="fa-solid fa-chevron-right"></i></span>
    </a>
    <a class="nav-item {'active' if pagina_atual == 'redes' else ''}" onclick="nav('redes')">
        <span class="nav-icon"><i class="fa-brands fa-instagram"></i></span>
        <span class="nav-label">Redes Sociais</span>
        <span class="nav-arrow"><i class="fa-solid fa-chevron-right"></i></span>
    </a>
    <a class="nav-item {'active' if pagina_atual == 'sites' else ''}" onclick="nav('sites')">
        <span class="nav-icon"><i class="fa-solid fa-magnifying-glass-chart"></i></span>
        <span class="nav-label">Confronto de Sites</span>
        <span class="nav-arrow"><i class="fa-solid fa-chevron-right"></i></span>
    </a>
    <a class="nav-item {'active' if pagina_atual == 'ads' else ''}" onclick="nav('ads')">
        <span class="nav-icon"><i class="fa-solid fa-rectangle-ad"></i></span>
        <span class="nav-label">Biblioteca de Ads</span>
        <span class="nav-arrow"><i class="fa-solid fa-chevron-right"></i></span>
    </a>
    <a class="nav-item {'active' if pagina_atual == 'insights' else ''}" onclick="nav('insights')">
        <span class="nav-icon"><i class="fa-solid fa-lightbulb"></i></span>
        <span class="nav-label">Insights</span>
        <span class="nav-arrow"><i class="fa-solid fa-chevron-right"></i></span>
    </a>
</div>
<div class="footer">
    <div class="footer-email">
        <i class="fa-solid fa-circle-user"></i>
        <span>{user_email}</span>
    </div>
    <button class="btn-sair" onclick="nav('sair')">
        <i class="fa-solid fa-right-from-bracket"></i>
        Sair
    </button>
</div>
</body>
<script>
function nav(page) {{
    var norm = page.split(/\s+/).join(' ').trim();
    const buttons = window.parent.document.querySelectorAll('[data-testid="stSidebar"] button');
    for (const btn of buttons) {{
        if ((btn.innerText || btn.textContent || '').split(/\s+/).join(' ').trim() === norm) {{
            btn.click();
            break;
        }}
    }}
}}
</script>
"""

    components.html(menu_html, height=620, scrolling=False)

# ---------------------------------------------------
# HELPER — CABEÇALHO COM PERÍODO
# ---------------------------------------------------

def cabecalho_analise(titulo, subtitulo=""):
    import datetime
    h1, h2 = st.columns([6, 3])
    with h1:
        st.markdown(
            f"<h1 style='font-size:28px;font-weight:600;color:#111827;letter-spacing:-0.5px;margin:0;font-family:DM Sans,sans-serif'>{titulo}</h1>",
            unsafe_allow_html=True
        )
        if subtitulo:
            st.markdown(f"<div style='font-size:16px;color:#6b7280;margin-top:3px'>{subtitulo}</div>", unsafe_allow_html=True)
    with h2:
        periodo = st.selectbox(
            "Período",
            ["Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Últimos 12 meses", "Todo o período"],
            index=1,
            label_visibility="collapsed"
        )
    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:16px 0 24px 0'/>", unsafe_allow_html=True)
    periodo_map = {
        "Últimos 7 dias": 7, "Últimos 30 dias": 30,
        "Últimos 90 dias": 90, "Últimos 12 meses": 365, "Todo o período": None,
    }
    dias = periodo_map[periodo]
    if dias:
        data_inicio = (datetime.date.today() - datetime.timedelta(days=dias)).strftime("%Y-%m-%d")
    else:
        data_inicio = None
    return periodo, data_inicio

def cabecalho_simples(titulo, subtitulo=""):
    st.markdown(
        f"<h1 style='font-size:28px;font-weight:600;color:#111827;"
        f"letter-spacing:-0.5px;margin:0;font-family:DM Sans,sans-serif'>{titulo}</h1>",
        unsafe_allow_html=True,
    )
    if subtitulo:
        st.markdown(
            f"<div style='font-size:16px;color:#6b7280;margin-top:3px'>{subtitulo}</div>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "<hr style='border:none;border-top:1px solid #e5e7eb;margin:16px 0 24px 0'/>",
        unsafe_allow_html=True,
    )

# ===================================================
# PÁGINAS
# ===================================================

# ---------------------------------------------------
# FUNÇÃO salvar_cache_ads 
# ---------------------------------------------------
 
def salvar_cache_ads(dados: dict):
    try:
        user_id = st.session_state.user.id
 
        dados_limpos = {}
        for empresa, entry in dados.items():
            entry_limpa = dict(entry)
            ads_limpos = []
            for ad in entry.get("data", []):
                ad_limpo = dict(ad)
                ad_limpo.pop("images_b64", None)
                ad_limpo.pop("video_thumb", None)
                ads_limpos.append(ad_limpo)
            entry_limpa["data"] = ads_limpos
            dados_limpos[empresa] = entry_limpa
 
        payload = {
            "user_id": user_id,
            "minha_empresa": st.session_state.dados.get("minha_empresa", {}),
            "concorrentes": st.session_state.dados.get("concorrentes", []),
            "metricas_redes": st.session_state.get("metricas_redes", {}),
            "ads_cache": dados_limpos,
        }
        supabase.table("ci_dados").upsert(payload, on_conflict="user_id").execute()
    except Exception as e:
        st.toast(f"⚠️ Erro ao salvar cache de ads: {e}", icon="⚠️")

# ---------------------------------------------------
# HOME — Minha Empresa
# ---------------------------------------------------

if st.session_state.pagina == "home":

    emp = st.session_state.dados["minha_empresa"]
    tem_dados = empresa_tem_dados(emp)

    if not tem_dados and not st.session_state.editar_empresa:
        st.session_state.editar_empresa = True

    st.markdown("""
    <style>
    .st-key-card_identificacao,
    .st-key-card_identificacao > div,
    .st-key-card_identificacao > div > div,
    .st-key-card_identificacao [class*="st-emotion-cache"],
    .st-key-card_identificacao [data-testid="stHorizontalBlock"],
    .st-key-card_identificacao [data-testid="column"],
    .st-key-card_identificacao [data-testid="column"] > div,
    .st-key-card_identificacao .stElementContainer,
    .st-key-card_identificacao .stElementContainer > div {
        background: #ffffff !important;
        background-color: #ffffff !important;
    }
    .st-key-card_identificacao {
        border: 1px solid #e5e7eb !important;
        border-radius: 14px !important;
        padding: 20px 28px !important;
        margin-bottom: 12px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
    }
    .st-key-card_setor,
    .st-key-card_setor > div,
    .st-key-card_setor > div > div,
    .st-key-card_setor [class*="st-emotion-cache"],
    .st-key-card_setor [data-testid="stHorizontalBlock"],
    .st-key-card_setor [data-testid="column"],
    .st-key-card_setor [data-testid="column"] > div,
    .st-key-card_setor .stElementContainer,
    .st-key-card_setor .stElementContainer > div {
        background: #ffffff !important;
        background-color: #ffffff !important;
    }
    .st-key-card_setor {
        border: 1px solid #e5e7eb !important;
        border-radius: 14px !important;
        padding: 20px 28px !important;
        margin-bottom: 12px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
    }
    .st-key-card_redes,
    .st-key-card_redes > div,
    .st-key-card_redes > div > div,
    .st-key-card_redes [class*="st-emotion-cache"],
    .st-key-card_redes [data-testid="stHorizontalBlock"],
    .st-key-card_redes [data-testid="column"],
    .st-key-card_redes [data-testid="column"] > div,
    .st-key-card_redes .stElementContainer,
    .st-key-card_redes .stElementContainer > div,
    .st-key-card_redes div[data-testid="stForm"],
    .st-key-card_redes div[data-testid="stForm"] > div,
    .st-key-card_redes div[data-testid="stForm"] > div > div {
        background: #ffffff !important;
        background-color: #ffffff !important;
    }
    .st-key-card_redes {
        border: 1px solid #e5e7eb !important;
        border-radius: 14px !important;
        padding: 20px 28px !important;
        margin-bottom: 12px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
    }
    .st-key-card_identificacao input,
    .st-key-card_setor input,
    .st-key-card_redes input,
    .st-key-card_identificacao textarea,
    .st-key-card_setor textarea,
    .st-key-card_redes textarea {
        background: #ffffff !important;
        background-color: #ffffff !important;
        border: 1px solid #e5e7eb !important;
        border-radius: 7px !important;
    }
    .st-key-card_identificacao [data-baseweb="select"] > div,
    .st-key-card_setor [data-baseweb="select"] > div,
    .st-key-card_redes [data-baseweb="select"] > div {
        background: #ffffff !important;
        background-color: #ffffff !important;
        border: 1px solid #e5e7eb !important;
        border-radius: 7px !important;
    }
    .st-key-card_redes div[data-testid="stForm"] {
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }
    .st-key-btn_home_editar_ghost,
    .stElementContainer:has(.st-key-btn_home_editar_ghost) {
        position: fixed !important;
        top: -9999px !important;
        left: -9999px !important;
        width: 1px !important;
        height: 1px !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
        visibility: hidden !important;
        display: block !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if st.session_state.editar_empresa or not tem_dados:

        h1, h2 = st.columns([7, 3])
        with h1:
            components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; }
.titulo {
    font-family: 'Animo', 'DM Sans', sans-serif;
    font-size: 32px; font-weight: 700; color: #1a2e4a;
    text-transform: uppercase; margin: 0 0 6px 0; letter-spacing: 0.5px;
}
.sub { font-family: 'DM Sans', sans-serif; font-size: 14px; color: #6b7280; }
</style>
<div class="titulo">Minha Empresa</div>
<div class="sub">Gerencie as informações e tenha uma visão geral da sua empresa.</div>
""", height=70)

        with h2:
            st.markdown("<div style='padding-top:6px;'/>", unsafe_allow_html=True)

        st.markdown(
            "<hr style='border:none;border-top:1px solid #e5e7eb;margin:4px 0 20px 0'/>",
            unsafe_allow_html=True,
        )

        def sec_label(label):
            st.markdown(
                f"<div style='font-size:11px;font-weight:700;color:#9ca3af;"
                f"text-transform:uppercase;letter-spacing:1px;"
                f"margin-bottom:12px'>{label}</div>",
                unsafe_allow_html=True,
            )

        def form_divider():
            st.markdown(
                "<div style='margin:16px 0;border-top:1px solid #f3f4f6'/>",
                unsafe_allow_html=True,
            )

        with st.container(key="card_identificacao"):
            sec_label("Identificação")
            c1, c2 = st.columns(2)
            emp["nome"] = c1.text_input(
                "Nome da Empresa",
                value=emp.get("nome", ""),
                key="edit_nome",
                placeholder="Ex: Marketylics",
            )
            site_digitado = c2.text_input(
                "Site",
                value=emp.get("site", ""),
                key="edit_site",
                placeholder="Ex: marketylics.com",
            )
            emp["site"] = limpar_site(site_digitado)

        with st.container(key="card_setor"):
            sec_label("Setor")
            c3, c4 = st.columns(2)
            setor_opcoes = list(SUBNICHOS.keys())
            setor_atual  = emp.get("setor", "Marketing")
            setor_idx    = setor_opcoes.index(setor_atual) if setor_atual in setor_opcoes else 0

            def on_setor_change():
                emp["tipo"] = ""
                st.session_state["_tipo_reset"] = True

            emp["setor"] = c3.selectbox(
                "Setor",
                setor_opcoes,
                index=setor_idx,
                key="sel_setor",
                on_change=on_setor_change,
            )

            subnichos_disponiveis = SUBNICHOS.get(emp["setor"], [])
            tipo_atual = emp.get("tipo", "")
            tipo_idx   = 0 if st.session_state.get("_tipo_reset") else (
                subnichos_disponiveis.index(tipo_atual) if tipo_atual in subnichos_disponiveis else 0
            )
            st.session_state["_tipo_reset"] = False

            emp["tipo"] = c4.selectbox(
                "Sub-nicho",
                subnichos_disponiveis,
                index=tipo_idx,
                key="sel_tipo",
            )

        with st.container(key="card_redes"):
            with st.form("cad_empresa", clear_on_submit=False):

                sec_label("Redes Sociais")
                c5, c6 = st.columns(2)
                emp["instagram"] = c5.text_input(
                    "Instagram",
                    value=emp.get("instagram", "@"),
                    placeholder="@suaempresa",
                )
                emp["fb_page"] = c6.text_input(
                    "Facebook",
                    value=emp.get("fb_page", ""),
                    placeholder="facebook.com/suaempresa",
                )

                servicos_text = st.text_input(
                    "Serviços (separados por vírgula)",
                    value=", ".join(emp.get("servicos", [])),
                    placeholder="Ex: SEO, Tráfego Pago, Social Media",
                )
                emp["servicos"] = [s.strip() for s in servicos_text.split(",") if s.strip()]

                form_divider()

                sec_label("Localização")
                loc1, loc2 = st.columns(2)
                estados      = list(ESTADOS_CIDADES.keys())
                estado_atual = emp.get("estado", "")
                estado_index = estados.index(estado_atual) if estado_atual in estados else 0
                emp["estado"] = loc1.selectbox("Estado", estados, index=estado_index)

                cidades      = ESTADOS_CIDADES.get(emp["estado"], [])
                cidade_atual = emp.get("cidade", "")
                cidade_index = cidades.index(cidade_atual) if cidade_atual in cidades else 0
                emp["cidade"] = loc2.selectbox("Cidade", cidades, index=cidade_index)

                form_divider()

                col_salvar, col_cancelar = st.columns(2)
                salvar   = col_salvar.form_submit_button("Salvar",   use_container_width=True)
                cancelar = col_cancelar.form_submit_button("Cancelar", use_container_width=True)

                if cancelar:
                    if tem_dados:
                        st.session_state.editar_empresa = False
                        st.rerun()
                    else:
                        st.warning("Preencha pelo menos o nome da empresa para continuar.")

                if salvar:
                    emp["nome"] = st.session_state.get("edit_nome", emp.get("nome", ""))
                    emp["site"] = limpar_site(st.session_state.get("edit_site", emp.get("site", "")))
                    if emp["nome"].strip():
                        st.session_state.editar_empresa = False
                        salvar_dados_usuario(st.session_state.user.id)
                        st.success("Empresa salva com sucesso!")
                        st.rerun()
                    else:
                        st.error("Informe pelo menos o nome da empresa.")

    else:
        # ── MODO VISUALIZAÇÃO ─────────────────────────────────────

        # Botão ghost — oculto via CSS, acionado pelo HTML abaixo
        if st.button("Editar Empresa", key="btn_home_editar_ghost"):
            st.session_state.editar_empresa = True
            st.rerun()

        h1, h2 = st.columns([7, 3])
        with h1:
            components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; }
.titulo {
    font-family: 'Animo', 'DM Sans', sans-serif;
    font-size: 32px; font-weight: 700; color: #1a2e4a;
    text-transform: uppercase; margin: 0 0 6px 0; letter-spacing: 0.5px;
}
.sub { font-family: 'DM Sans', sans-serif; font-size: 14px; color: #6b7280; }
</style>
<div class="titulo">Minha Empresa</div>
<div class="sub">Gerencie as informações e tenha uma visão geral da sua empresa.</div>
""", height=70)

        with h2:
            st.markdown("<div style='padding-top:6px;'/>", unsafe_allow_html=True)
            components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; font-family: 'DM Sans', sans-serif; }
.btn {
    width: 100%;
    padding: 10px 16px;
    background: #0780c0;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    transition: background 0.15s;
    min-height: 40px;
    box-sizing: border-box;
}
.btn:hover { background: #065f9e; }
</style>
<button class="btn" onclick="triggerEditar()">
    Editar Empresa
</button>
<script>
function triggerEditar() {
    var btns = window.parent.document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
        var txt = (btns[i].textContent || btns[i].innerText || '').trim();
        if (txt === 'Editar Empresa') {
            btns[i].click();
            return;
        }
    }
}
(function() {
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        try {
            if (iframes[i].contentWindow === window) {
                iframes[i].style.height = '46px';
                break;
            }
        } catch(e) {}
    }
})();
</script>
""", height=46, scrolling=False)

        st.markdown(
            "<hr style='border:none;border-top:1px solid #e5e7eb;margin:4px 0 20px 0'/>",
            unsafe_allow_html=True,
        )

        cor_empresa = get_minha_empresa_color()
        avatar      = gerar_avatar(emp["nome"])
        loc         = emp.get("cidade", "")
        if emp.get("estado"):
            loc += (", " if loc else "") + emp["estado"]
        servicos_html = (
            "".join([f"<span class='empresa-tag'>{s}</span>" for s in emp.get("servicos", [])])
            if emp.get("servicos") else "<span style='color:#9ca3af;font-size:14px'>—</span>"
        )

        components.html(f"""
<!DOCTYPE html>
<html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ background: transparent; font-family: 'DM Sans', sans-serif; -webkit-font-smoothing: antialiased; }}
body {{ background: transparent; overflow: hidden; padding-bottom: 2px; }}
.empresa-card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; overflow: hidden; position: relative; }}
.empresa-card-deco {{ position: absolute; top: 0; right: 0; width: 260px; height: 110px; pointer-events: none; opacity: 0.4; }}
.empresa-card-body {{ padding: 24px 28px; }}
.empresa-top {{ display: flex; align-items: center; gap: 16px; margin-bottom: 20px; padding-bottom: 18px; border-bottom: 1px solid #f3f4f6; }}
.empresa-avatar {{ width: 52px; height: 52px; min-width: 52px; border-radius: 50%; background: {cor_empresa}; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; color: #fff; flex-shrink: 0; }}
.empresa-nome {{ font-size: 20px; font-weight: 700; color: #111827; margin-bottom: 2px; letter-spacing: -0.3px; }}
.empresa-sub {{ font-size: 14px; color: #6b7280; font-weight: 500; }}
.empresa-grid {{ display: grid; grid-template-columns: 1fr 1px 1fr 1px 1fr; gap: 0; }}
.empresa-divider {{ background: #f0f0f0; margin: 0 24px; align-self: stretch; }}
.empresa-col {{ padding: 0 4px; }}
.empresa-sec-title {{ font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: #6b7280; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid #f3f4f6; }}
.empresa-row {{ display: flex; align-items: flex-start; gap: 10px; margin-bottom: 12px; }}
.empresa-ico {{ width: 36px; height: 36px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 9px; }}
.empresa-ico svg {{ width: 20px; height: 20px; }}
.empresa-lbl {{ font-size: 13px; color: #717885; display: block; margin-bottom: -2px; }}
.empresa-val {{ font-size: 14px; color: #111827; font-weight: 600; }}
.empresa-tags-wrap {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.empresa-tag {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 500; }}
</style>
</head>
<body>
<div class="empresa-card" id="card">
    <svg class="empresa-card-deco" viewBox="0 0 260 110" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMaxYMin meet">
        <path d="M 0 88 C 55 64 110 76 170 50 C 210 34 238 26 260 14" stroke="#93c5fd" stroke-width="1.5" fill="none"/>
        <circle cx="170" cy="50" r="3.5" fill="#60a5fa"/>
        <circle cx="238" cy="26" r="3.5" fill="#60a5fa"/>
        <circle cx="254" cy="16" r="4" fill="#3b82f6"/>
        <rect x="185" y="58" width="11" height="38" rx="3" fill="#93c5fd" opacity="0.5"/>
        <rect x="202" y="46" width="11" height="50" rx="3" fill="#60a5fa" opacity="0.6"/>
        <rect x="219" y="33" width="11" height="63" rx="3" fill="#3b82f6" opacity="0.68"/>
        <rect x="236" y="20" width="11" height="76" rx="3" fill="#2563eb" opacity="0.75"/>
    </svg>
    <div class="empresa-card-body">
        <div class="empresa-top">
            <div class="empresa-avatar">{avatar}</div>
            <div>
                <div class="empresa-nome">{emp['nome']}</div>
                <div class="empresa-sub">{emp.get('setor','')}{' · ' + emp['tipo'] if emp.get('tipo') else ''}</div>
            </div>
        </div>
        <div class="empresa-grid">
            <div class="empresa-col">
                <div class="empresa-sec-title">Presença Digital</div>
                <div class="empresa-row">
                    <span class="empresa-ico" style="background:#f3f4f6;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
                            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
                        </svg>
                    </span>
                    <div><span class="empresa-lbl">Site</span><span class="empresa-val">{emp.get('site') or '—'}</span></div>
                </div>
                <div class="empresa-row">
                    <span class="empresa-ico" style="background:#fff0f6;">
                        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <defs><linearGradient id="ig_emp" x1="0%" y1="100%" x2="100%" y2="0%">
                                <stop offset="0%" stop-color="#f09433"/><stop offset="25%" stop-color="#e6683c"/>
                                <stop offset="50%" stop-color="#dc2743"/><stop offset="75%" stop-color="#cc2366"/>
                                <stop offset="100%" stop-color="#bc1888"/>
                            </linearGradient></defs>
                            <rect x="2" y="2" width="20" height="20" rx="5" fill="url(#ig_emp)"/>
                            <circle cx="12" cy="12" r="4.5" stroke="white" stroke-width="1.8" fill="none"/>
                            <circle cx="17.5" cy="6.5" r="1.2" fill="white"/>
                        </svg>
                    </span>
                    <div><span class="empresa-lbl">Instagram</span><span class="empresa-val">{emp.get('instagram') or '—'}</span></div>
                </div>
                <div class="empresa-row">
                    <span class="empresa-ico" style="background:#e8f0fe;">
                        <svg viewBox="0 0 24 24" fill="#1877F2">
                            <path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.268h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/>
                        </svg>
                    </span>
                    <div><span class="empresa-lbl">Facebook</span><span class="empresa-val">{emp.get('fb_page') or '—'}</span></div>
                </div>
            </div>
            <div class="empresa-divider"></div>
            <div class="empresa-col">
                <div class="empresa-sec-title">Localização</div>
                <div class="empresa-row">
                    <span class="empresa-ico" style="background:#f3f4f6;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
                            <circle cx="12" cy="10" r="3"/>
                        </svg>
                    </span>
                    <div><span class="empresa-lbl">Cidade / Estado</span><span class="empresa-val">{loc or '—'}</span></div>
                </div>
            </div>
            <div class="empresa-divider"></div>
            <div class="empresa-col">
                <div class="empresa-sec-title">Serviços</div>
                <div class="empresa-tags-wrap">{servicos_html}</div>
            </div>
        </div>
    </div>
</div>
<script>
function ajustarAltura() {{
    var card = document.getElementById('card');
    if (!card) return;
    var h = card.getBoundingClientRect().height;
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var j = 0; j < iframes.length; j++) {{
        try {{ if (iframes[j].contentWindow === window) {{ iframes[j].style.height = (h + 8) + 'px'; break; }} }} catch(e) {{}}
    }}
}}
document.addEventListener('DOMContentLoaded', ajustarAltura);
window.addEventListener('load', ajustarAltura);
setTimeout(ajustarAltura, 300);
setTimeout(ajustarAltura, 800);
</script>
</body>
</html>
        """, height=320, scrolling=False)

        st.markdown("""
        <div style='background:#e7fbff;border:1px solid #6fd1f3;border-radius:12px;
                    padding:14px 20px;display:flex;align-items:center;gap:16px;
                    margin-top:8px;box-shadow:0 1px 3px rgba(0,0,0,0.04)'>
            <div style='width:42px;height:42px;border-radius:10px;background:#007dbb;
                        display:flex;align-items:center;justify-content:center;flex-shrink:0'>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                    <path d="M9 12l2 2 4-4" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M12 2L3 7v5c0 5.25 3.75 10.15 9 11.35C17.25 22.15 21 17.25 21 12V7L12 2z"
                          stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div style='font-size:16px;font-weight:600;color:#0f172a'>Mantenha suas informações atualizadas</div>
                <div style='font-size:13px;color:#64748b;margin-top:-3px'>Dados atualizados garantem análises mais precisas e relatórios mais completos.</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ---------------------------------------------------
# PAGINA - CONCORRENTES
# ---------------------------------------------------

elif st.session_state.pagina == "cad":
 
    st.markdown("""
    <style>
    div[data-testid="stForm"] {
        background: #ffffff !important;
        border: 1px solid #e5e7eb !important;
        border-radius: 14px !important;
        padding: 28px 32px !important;
        margin-bottom: 28px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
    }
    .st-key-ads_id_hidden {
        display: none !important;
        height: 0 !important;
        overflow: hidden !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)
 
    top1, top2 = st.columns([7, 3])
    with top1:
        components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; }
.titulo {
    font-family: 'Animo', 'DM Sans', sans-serif;
    font-size: 32px; font-weight: 700; color: #1a2e4a;
    text-transform: uppercase; margin: 0 0 6px 0; letter-spacing: 0.5px;
}
.sub { font-family: 'DM Sans', sans-serif; font-size: 14px; color: #6b7280; }
</style>
<div class="titulo">Concorrentes</div>
<div class="sub">Acompanhe e gerencie seus concorrentes para uma análise mais estratégica.</div>
""", height=70)
 
    with top2:
        st.markdown("<div style='padding-top:6px'/>", unsafe_allow_html=True)
        if st.button("＋ Adicionar Concorrente", use_container_width=True, type="primary"):
            st.session_state.mostrar_form_concorrente = True
            st.session_state.editando_concorrente = None
            st.rerun()
 
    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:4px 0 24px 0'/>", unsafe_allow_html=True)
 
    if st.session_state.mostrar_form_concorrente or st.session_state.editando_concorrente is not None:
        concorrente_edit = None
        if st.session_state.editando_concorrente is not None:
            concorrente_edit = st.session_state.dados["concorrentes"][st.session_state.editando_concorrente]
 
        titulo_form = "✏️ Editar Concorrente" if concorrente_edit else "➕ Novo Concorrente"
        st.markdown(f"<div style='font-size:16px;font-weight:700;color:#111827;margin-bottom:16px'>{titulo_form}</div>", unsafe_allow_html=True)
 
        with st.form("cad_concorrente", clear_on_submit=False):
            st.markdown("<div style='font-size:11px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px'>Identificação</div>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            n = c1.text_input("Nome do Concorrente", value=(concorrente_edit["nome"] if concorrente_edit else ""))
            u = c2.text_input("URL do Site", value=(concorrente_edit["url"] if concorrente_edit else ""))
 
            st.markdown("<div style='margin:16px 0;border-top:1px solid #f3f4f6'/>", unsafe_allow_html=True)
            st.markdown("<div style='font-size:11px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px'>Redes Sociais</div>", unsafe_allow_html=True)
            c3, c4 = st.columns(2)
            insta_handle = c3.text_input("Instagram", value=(concorrente_edit["instagram"] if concorrente_edit else "@"))
            fb_p = c4.text_input("Facebook", value=(concorrente_edit["fb_page"] if concorrente_edit else ""))
 
            ads_manual = st.text_input(
                "ads_id_hidden",
                value=(concorrente_edit.get("ads_id", "") if concorrente_edit else ""),
                key="ads_id_hidden",
                label_visibility="hidden",
                autocomplete="off",
            )
 
            col1, col2 = st.columns(2)
            salvar   = col1.form_submit_button("Salvar",   use_container_width=True)
            cancelar = col2.form_submit_button("Cancelar", use_container_width=True)
 
            if cancelar:
                st.session_state.mostrar_form_concorrente = False
                st.session_state.editando_concorrente = None
                st.rerun()
 
            if salvar:
                clean_handle      = obter_instagram_handle(insta_handle)
                fb_clean          = obter_facebook_handle(fb_p)
                site_clean        = limpar_site(u)
                existing_ads_id   = (concorrente_edit.get("ads_id", "") if concorrente_edit else "").strip()
                existing_page_pic = (concorrente_edit.get("ads_page_pic", "") if concorrente_edit else "")
                dados_novos = {
                    "nome":         n,
                    "url":          site_clean,
                    "instagram":    clean_handle,
                    "fb_page":      fb_clean,
                    "ads_id":       existing_ads_id,
                    "ads_page_pic": existing_page_pic,
                }
                if st.session_state.editando_concorrente is not None:
                    st.session_state.dados["concorrentes"][st.session_state.editando_concorrente] = dados_novos
                else:
                    st.session_state.dados["concorrentes"].append(dados_novos)
                st.session_state.mostrar_form_concorrente = False
                st.session_state.editando_concorrente = None
                salvar_dados_usuario(st.session_state.user.id)
                st.rerun()
 
    concorrentes = st.session_state.dados["concorrentes"]
 
    if concorrentes:
        import json as _json_conc
 
        # ── Oculta botões Streamlit e containers completamente ───
        hide_btns_css = "\n".join([
            f"""
            .st-key-editar_{i},
            .st-key-remove_{i},
            .stElementContainer:has(.st-key-editar_{i}),
            .stElementContainer:has(.st-key-remove_{i}) {{
                display: none !important;
                height: 0 !important;
                min-height: 0 !important;
                max-height: 0 !important;
                margin: 0 !important;
                padding: 0 !important;
                overflow: hidden !important;
                visibility: hidden !important;
            }}
            """
            for i in range(len(concorrentes))
        ])
        st.markdown(f"<style>{hide_btns_css}</style>", unsafe_allow_html=True)
 
        # ── Monta JSON dos cards ─────────────────────────────────
        cards_conc = []
        for i, c in enumerate(concorrentes):
            cards_conc.append({
                "idx":       i,
                "nome":      c.get("nome", ""),
                "url":       c.get("url", ""),
                "instagram": c.get("instagram", ""),
                "fb_page":   c.get("fb_page", ""),
                "cor":       get_concorrente_color(i),
                "avatar":    gerar_avatar(c.get("nome", "?")),
            })
        cards_json = _json_conc.dumps(cards_conc, ensure_ascii=True)
 
        # ── Estima altura: ~300px por linha de 2 cards ──────────
        n_rows     = (len(concorrentes) + 1) // 2
        est_height = 40 + n_rows * 320
 
        components.html(f"""<!DOCTYPE html>
<html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<script id="cards-data" type="application/json">{cards_json}</script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
    background: transparent;
    font-family: 'DM Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
    overflow: visible;
}}
body {{ padding-bottom: 8px; }}
 
.outer-wrap {{
    background: #d2dde9;
    border-radius: 16px;
    padding: 20px;
    min-height: 60px;
}}
.cards-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 20px;
}}
.card {{
    background: #fff;
    border: 1px solid #dde1e7;
    border-radius: 14px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    box-shadow: 0 4px 20px rgba(0,0,0,0.10);
    transition: border-color 0.15s;
}}
.card:hover {{ border-color: #6fd1f3; }}
 
.card-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px 14px;
}}
.avatar {{
    width: 44px; height: 44px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; font-weight: 700; color: #fff; flex-shrink: 0;
}}
.name {{ font-size: 16px; font-weight: 700; color: #111827; }}
.badge {{
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 700;
    background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe;
}}
.divider {{ height: 1px; background: #f3f4f6; margin: 0 20px; }}
.card-body {{
    padding: 14px 20px 18px;
    display: flex; flex-direction: column; gap: 10px;
}}
.sec-title {{
    font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1.2px; color: #6b7280;
    padding-bottom: 8px; border-bottom: 1px solid #f3f4f6; margin-bottom: 2px;
}}
.row {{ display: flex; align-items: center; gap: 12px; }}
.icon-wrap {{
    width: 36px; height: 36px; border-radius: 8px; background: #f3f4f6;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}}
.row-label {{ font-size: 13px; color: #717885; display: block; }}
.row-value {{
    font-size: 14px; color: #111827; font-weight: 600;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block;
}}
.card-footer {{ display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid #f3f4f6; }}
.footer-btn {{
    padding: 11px 0; font-size: 14px; font-weight: 600; color: #6b7280;
    cursor: pointer; background: transparent; border: none;
    font-family: 'DM Sans', sans-serif; transition: background 0.12s;
    display: flex; align-items: center; justify-content: center; gap: 6px;
}}
.footer-btn:hover {{ background: #f9fafb; color: #111827; }}
.footer-btn.danger {{ border-left: 1px solid #f3f4f6; }}
.footer-btn.danger:hover {{ background: #fef2f2; color: #dc2626; }}
</style>
</head>
<body>
<div class="outer-wrap">
    <div class="cards-grid" id="grid"></div>
</div>
<script>
(function() {{
    var CARDS = JSON.parse(document.getElementById('cards-data').textContent);
 
    var ICON_GLOBE = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>';
    var ICON_FB    = '<svg width="20" height="20" viewBox="0 0 24 24" fill="#1877F2"><path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.268h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/></svg>';
    var ICON_EDIT  = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
    var ICON_TRASH = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>';
 
    function igIcon(idx) {{
        return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none">'
            + '<defs><linearGradient id="ig' + idx + '" x1="0%" y1="100%" x2="100%" y2="0%">'
            + '<stop offset="0%" stop-color="#f09433"/><stop offset="25%" stop-color="#e6683c"/>'
            + '<stop offset="50%" stop-color="#dc2743"/><stop offset="75%" stop-color="#cc2366"/>'
            + '<stop offset="100%" stop-color="#bc1888"/></linearGradient></defs>'
            + '<rect x="2" y="2" width="20" height="20" rx="5" fill="url(#ig' + idx + ')"/>'
            + '<circle cx="12" cy="12" r="4.5" stroke="white" stroke-width="1.8" fill="none"/>'
            + '<circle cx="17.5" cy="6.5" r="1.2" fill="white"/></svg>';
    }}
 
    function makeRow(iconHtml, iconBg, label, value) {{
        return '<div class="row">'
            + '<div class="icon-wrap" style="background:' + iconBg + '">' + iconHtml + '</div>'
            + '<div style="flex:1;min-width:0">'
            + '<span class="row-label">' + label + '</span>'
            + '<span class="row-value">' + (value || '—') + '</span>'
            + '</div></div>';
    }}
 
    function acionar(idx, action) {{
        var label = action === 'editar' ? 'Editar Concorrente' : 'Remover Concorrente';
        var btns  = window.parent.document.querySelectorAll('button');
        var found = [];
        btns.forEach(function(b) {{
            var txt = (b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
            if (txt === label) found.push(b);
        }});
        if (found[idx]) {{ found[idx].click(); return; }}
        if (found[0])   {{ found[0].click(); }}
    }}
 
    function syncHeight() {{
        var h = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
        var iframes = window.parent.document.querySelectorAll('iframe');
        for (var i = 0; i < iframes.length; i++) {{
            try {{
                if (iframes[i].contentWindow === window) {{
                    iframes[i].style.height = (h + 12) + 'px';
                    break;
                }}
            }} catch(e) {{}}
        }}
    }}
 
    function buildCards() {{
        var grid = document.getElementById('grid');
        if (!grid) return;
 
        CARDS.forEach(function(c) {{
            var card = document.createElement('div');
            card.className = 'card';
 
            /* header */
            var hdr = document.createElement('div');
            hdr.className = 'card-header';
            hdr.innerHTML =
                '<div class="avatar" style="background:' + c.cor + '">' + c.avatar + '</div>'
                + '<div style="flex:1;min-width:0">'
                + '<div class="name">' + c.nome + '</div>'
                + '<span class="badge">Concorrente</span>'
                + '</div>';
            card.appendChild(hdr);
 
            /* divider */
            var dvd = document.createElement('div');
            dvd.className = 'divider';
            card.appendChild(dvd);
 
            /* body */
            var body = document.createElement('div');
            body.className = 'card-body';
            body.innerHTML =
                '<div class="sec-title">Presença Digital</div>'
                + makeRow(ICON_GLOBE, '#f3f4f6',  'Site',      c.url)
                + makeRow(igIcon(c.idx), '#fff0f6', 'Instagram', c.instagram)
                + makeRow(ICON_FB,    '#e8f0fe',  'Facebook',  c.fb_page);
            card.appendChild(body);
 
            /* footer */
            var footer = document.createElement('div');
            footer.className = 'card-footer';
            var btnEdit = document.createElement('button');
            btnEdit.className = 'footer-btn';
            btnEdit.innerHTML = ICON_EDIT + 'Editar';
            btnEdit.onclick = (function(i) {{ return function() {{ acionar(i, 'editar'); }}; }})(c.idx);
            var btnRm = document.createElement('button');
            btnRm.className = 'footer-btn danger';
            btnRm.innerHTML = ICON_TRASH + 'Remover';
            btnRm.onclick = (function(i) {{ return function() {{ acionar(i, 'remove'); }}; }})(c.idx);
            footer.appendChild(btnEdit);
            footer.appendChild(btnRm);
            card.appendChild(footer);
 
            grid.appendChild(card);
        }});
 
        syncHeight();
    }}
 
    document.addEventListener('DOMContentLoaded', buildCards);
    if (document.readyState !== 'loading') buildCards();
    [200, 500, 1000].forEach(function(t) {{ setTimeout(syncHeight, t); }});
    if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
}})();
</script>
</body>
</html>
""", height=est_height, scrolling=False)
 
        # ── Botões Streamlit reais (ocultos via CSS) ─────────────
        for i, c in enumerate(concorrentes):
            b1, b2 = st.columns(2)
            with b1:
                if st.button("Editar Concorrente", key=f"editar_{i}", use_container_width=True):
                    st.session_state.editando_concorrente = i
                    st.session_state.mostrar_form_concorrente = False
                    st.rerun()
            with b2:
                if st.button("Remover Concorrente", key=f"remove_{i}", use_container_width=True):
                    nome_removido = st.session_state.dados["concorrentes"][i].get("nome", "")
                    st.session_state.dados["concorrentes"].pop(i)
                    if nome_removido and nome_removido in st.session_state.get("ads_cache", {}):
                        del st.session_state.ads_cache[nome_removido]
                        salvar_cache_ads(st.session_state.ads_cache)
                    salvar_dados_usuario(st.session_state.user.id)
                    st.rerun()
 
    else:
        st.markdown("""
        <div style='background:#fff;border:1px dashed #d1d5db;border-radius:14px;
                    padding:48px 32px;text-align:center;margin-top:10px;'>
            <div style='font-size:32px;margin-bottom:12px'>🎯</div>
            <div style='font-size:16px;font-weight:600;color:#374151;margin-bottom:6px'>Nenhum concorrente cadastrado</div>
            <div style='font-size:14px;color:#9ca3af'>Clique em <b>＋ Adicionar</b> para começar a monitorar seus concorrentes.</div>
        </div>
        """, unsafe_allow_html=True)

# ---------------------------------------------------
# PAGINA - DASHBOARD GERAL
# ---------------------------------------------------

elif st.session_state.pagina == "geral":

    import datetime as _dt
    import json as _json

    emp = st.session_state.dados["minha_empresa"]
    concorrentes = st.session_state.dados["concorrentes"]

    # ── Cabeçalho ──────────────────────────────────────────────────
    h1, h2 = st.columns([7, 3])
    with h1:
        components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; }
.titulo {
    font-family: 'Animo', 'DM Sans', sans-serif;
    font-size: 32px; font-weight: 700; color: #1a2e4a;
    text-transform: uppercase; margin: 0 0 6px 0; letter-spacing: 0.5px;
}
.sub { font-family: 'DM Sans', sans-serif; font-size: 14px; color: #6b7280; }
</style>
<div class="titulo">Dashboard Geral</div>
<div class="sub">Panorama competitivo da sua empresa e concorrentes.</div>
""", height=70)

    with h2:
        st.markdown("<div style='padding-top:6px'/>", unsafe_allow_html=True)
        ultima_coleta = st.session_state.metricas_redes.get("ultima_coleta", "")
        if ultima_coleta:
            st.markdown(
                f"<div style='font-size:13px;color:#6b7280;text-align:center;padding-top:8px'>"
                f"🕒 Dados de: <b>{ultima_coleta}</b></div>",
                unsafe_allow_html=True,
            )

    st.markdown(
        "<hr style='border:none;border-top:1px solid #e5e7eb;margin:4px 0 24px 0'/>",
        unsafe_allow_html=True,
    )

    # ── Montar lista de todas as empresas ──────────────────────────
    todas_empresas_geral = []
    if emp.get("nome"):
        todas_empresas_geral.append({
            "nome": emp["nome"],
            "tipo": "minha",
            "instagram": emp.get("instagram", ""),
            "site": emp.get("site", ""),
            "setor": emp.get("setor", ""),
            "tipo_nicho": emp.get("tipo", ""),
            "cidade": emp.get("cidade", ""),
            "estado": emp.get("estado", ""),
        })
    for c in concorrentes:
        if c.get("nome"):
            todas_empresas_geral.append({
                "nome": c["nome"],
                "tipo": "concorrente",
                "instagram": c.get("instagram", ""),
                "site": c.get("url", ""),
                "setor": "",
                "tipo_nicho": "",
                "cidade": "",
                "estado": "",
            })

    # ── Dados de redes sociais do cache ────────────────────────────
    cache_redes = st.session_state.metricas_redes.get("dados", [])
    dados_redes_map = {}
    for r in cache_redes:
        if not r.get("erro") and r.get("nome"):
            dados_redes_map[r["nome"]] = r

    # ── Dados de ads do cache ──────────────────────────────────────
    ads_cache = st.session_state.get("ads_cache", {})

    def fmt_num(n):
        n = int(n or 0)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n/1_000:.1f}K"
        return str(n)

    # ══════════════════════════════════════════════════════════════
    # BLOCO 1: TABELA RESUMO GERAL
    # ══════════════════════════════════════════════════════════════

    st.markdown(
        "<div style='font-size:16px;font-weight:700;color:#1a2e4a;"
        "letter-spacing:0.2px;margin:8px 0 14px'>📋 Resumo Comparativo</div>",
        unsafe_allow_html=True,
    )

    rows_html = ""
    for i, e in enumerate(todas_empresas_geral):
        is_minha = e["tipo"] == "minha"
        cor      = get_minha_empresa_color() if is_minha else get_concorrente_color(i - 1 if not is_minha else 0)
        av       = gerar_avatar(e["nome"])
        badge    = "Minha Empresa" if is_minha else "Concorrente"
        bg_badge = "#eff6ff" if is_minha else "#f3f4f6"
        col_badge= "#1d4ed8" if is_minha else "#6b7280"

        redes = dados_redes_map.get(e["nome"], {})
        seg   = redes.get("seguidores", 0)
        eng   = redes.get("eng_pct", 0.0)
        posts = redes.get("total_posts", 0)

        n_ads_total  = len(ads_cache.get(e["nome"], {}).get("data", []))
        n_ads_ativos = sum(1 for a in ads_cache.get(e["nome"], {}).get("data", []) if a.get("ativo", True))

        has_ig   = bool(e.get("instagram") and e["instagram"] not in ("@",""))
        has_site = bool(e.get("site"))

        rows_html += f"""
        <tr>
            <td>
                <div style="display:flex;align-items:center;gap:10px">
                    <div style="width:32px;height:32px;border-radius:50%;background:{cor};
                                display:flex;align-items:center;justify-content:center;
                                font-size:12px;font-weight:700;color:#fff;flex-shrink:0">{av}</div>
                    <div>
                        <div style="font-weight:700;color:#111827;font-size:13px">{e['nome']}</div>
                        <span style="font-size:11px;background:{bg_badge};color:{col_badge};
                                     border:1px solid {'#bfdbfe' if is_minha else '#e5e7eb'};
                                     padding:1px 7px;border-radius:20px;font-weight:600">{badge}</span>
                    </div>
                </div>
            </td>
            <td style="text-align:center">
                <span style="color:{'#22c55e' if has_ig else '#d1d5db'};font-size:14px">{'✓' if has_ig else '—'}</span>
            </td>
            <td style="text-align:center">
                <span style="color:{'#22c55e' if has_site else '#d1d5db'};font-size:14px">{'✓' if has_site else '—'}</span>
            </td>
            <td style="text-align:center;font-weight:700;color:#111827">{fmt_num(seg) if seg else '—'}</td>
            <td style="text-align:center;font-weight:700;color:#111827">{f'{eng:.1f}%' if seg else '—'}</td>
            <td style="text-align:center;font-weight:700;color:#111827">{fmt_num(posts) if posts else '—'}</td>
            <td style="text-align:center;font-weight:700;color:#111827">{n_ads_ativos if n_ads_ativos else '—'}</td>
            <td style="text-align:center;font-weight:600;color:#6b7280">{n_ads_total if n_ads_total else '—'}</td>
        </tr>
        """

    components.html(f"""
<!DOCTYPE html><html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
body {{ padding-bottom:8px; }}
.wrap {{ background:#fff; border:1px solid #e5e7eb; border-radius:14px; overflow:hidden; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{
    background:#f9fafb; color:#9ca3af; font-size:11px; font-weight:700;
    text-transform:uppercase; letter-spacing:0.6px;
    padding:11px 14px; text-align:left; border-bottom:1px solid #e5e7eb;
    white-space:nowrap;
}}
td {{ padding:12px 14px; border-bottom:1px solid #f3f4f6; vertical-align:middle; color:#374151; }}
tr:last-child td {{ border-bottom:none; }}
tr:hover td {{ background:#f9fafb; }}
</style>
</head>
<body>
<div class="wrap">
    <table>
        <thead>
            <tr>
                <th>Empresa</th>
                <th style="text-align:center">Instagram</th>
                <th style="text-align:center">Site</th>
                <th style="text-align:center">Seguidores</th>
                <th style="text-align:center">Engaj. %</th>
                <th style="text-align:center">Posts</th>
                <th style="text-align:center">Ads Ativos</th>
                <th style="text-align:center">Ads Total</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
</div>
<script>
function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = (h + 8) + 'px'; break;
        }} }} catch(e) {{}}
    }}
}}
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 200); setTimeout(syncHeight, 600);
</script>
</body></html>
""", height=200, scrolling=False) 
    
    # ══════════════════════════════════════════════════════════════
    # BLOCO 2: GRÁFICOS COMPARATIVOS DE REDES SOCIAIS
    # ══════════════════════════════════════════════════════════════

    ok_redes = [r for r in cache_redes if not r.get("erro") and r.get("seguidores", 0) > 0]

    if ok_redes:
        st.markdown(
            "<div style='font-size:16px;font-weight:700;color:#1a2e4a;"
            "letter-spacing:0.2px;margin-bottom:14px'>📊 Comparativo — Redes Sociais</div>",
            unsafe_allow_html=True,
        )

        nomes_g   = [r["nome"] for r in ok_redes]
        segs_g    = [r.get("seguidores", 0) for r in ok_redes]
        eng_pct_g = [float(r.get("eng_pct", 0.0)) for r in ok_redes]
        posts_g   = [r.get("total_posts", 0) for r in ok_redes]
        eng_med_g = [float(r.get("eng_medio", 0.0)) for r in ok_redes]
        cores_g   = [get_avatar_color(i) for i in range(len(ok_redes))]

        nomes_json    = _json.dumps(nomes_g, ensure_ascii=False)
        segs_json     = _json.dumps(segs_g)
        eng_pct_json  = _json.dumps([round(v, 2) for v in eng_pct_g])
        posts_json    = _json.dumps(posts_g)
        eng_med_json  = _json.dumps([round(v, 1) for v in eng_med_g])
        cores_json    = _json.dumps(cores_g)

        components.html(f"""
<!DOCTYPE html><html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; -webkit-font-smoothing:antialiased; }}
body {{ padding-bottom:8px; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px; }}
.card {{
    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
    padding:18px 20px 14px;
}}
.card-title {{
    font-size:12px; font-weight:800; color:#1a2e4a;
    text-transform:uppercase; letter-spacing:0.6px;
    padding-bottom:10px; border-bottom:1px solid #f3f4f6;
    margin-bottom:12px;
}}
.chart-wrap {{ position:relative; width:100%; height:180px; }}
.legend {{
    display:flex; flex-wrap:wrap; gap:10px;
    margin-top:10px; font-size:11px; color:#6b7280;
}}
.leg-item {{ display:flex; align-items:center; gap:5px; }}
.leg-dot {{
    width:10px; height:10px; border-radius:2px; flex-shrink:0;
}}
</style>
</head>
<body>

<div class="grid">
    <!-- Seguidores -->
    <div class="card">
        <div class="card-title">Seguidores</div>
        <div class="chart-wrap"><canvas id="ch_seg" role="img" aria-label="Comparativo de seguidores"></canvas></div>
        <div class="legend" id="leg_seg"></div>
    </div>
    <!-- Taxa de Engajamento -->
    <div class="card">
        <div class="card-title">Taxa de Engajamento (%)</div>
        <div class="chart-wrap"><canvas id="ch_eng" role="img" aria-label="Comparativo de engajamento"></canvas></div>
        <div class="legend" id="leg_eng"></div>
    </div>
</div>

<div class="grid">
    <!-- Total de Posts -->
    <div class="card">
        <div class="card-title">Total de Publicações</div>
        <div class="chart-wrap"><canvas id="ch_posts" role="img" aria-label="Comparativo de publicações"></canvas></div>
        <div class="legend" id="leg_posts"></div>
    </div>
    <!-- Engajamento Médio por Post -->
    <div class="card">
        <div class="card-title">Engajamento Médio por Post</div>
        <div class="chart-wrap"><canvas id="ch_engmed" role="img" aria-label="Engajamento médio por post"></canvas></div>
        <div class="legend" id="leg_engmed"></div>
    </div>
</div>

<script>
var NOMES   = {nomes_json};
var SEGS    = {segs_json};
var ENG_PCT = {eng_pct_json};
var POSTS   = {posts_json};
var ENG_MED = {eng_med_json};
var CORES   = {cores_json};

function makeLegend(containerId, labels, values, suffix) {{
    var el = document.getElementById(containerId);
    if (!el) return;
    labels.forEach(function(name, i) {{
        var item = document.createElement('span');
        item.className = 'leg-item';
        var dot = document.createElement('span');
        dot.className = 'leg-dot';
        dot.style.background = CORES[i];
        item.appendChild(dot);
        var txt = document.createTextNode(name + ' ' + (suffix === '%' ? values[i].toFixed(1) + '%' : fmtNum(values[i])));
        item.appendChild(txt);
        el.appendChild(item);
    }});
}}

function fmtNum(n) {{
    n = Math.round(n);
    if (n >= 1000000) return (n/1000000).toFixed(1) + 'M';
    if (n >= 1000)    return (n/1000).toFixed(1) + 'K';
    return String(n);
}}

var DEFAULTS = {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
        legend: {{ display: false }},
        tooltip: {{
            callbacks: {{
                label: function(ctx) {{
                    return ' ' + ctx.dataset.label + ': ' + fmtNum(ctx.parsed.y);
                }}
            }}
        }}
    }},
    scales: {{
        x: {{
            grid: {{ display: false }},
            ticks: {{
                font: {{ family: "'DM Sans', sans-serif", size: 11, weight: '600' }},
                color: '#6b7280',
                maxRotation: 0,
            }},
            border: {{ display: false }}
        }},
        y: {{
            grid: {{ color: '#f3f4f6', lineWidth: 1 }},
            ticks: {{
                font: {{ family: "'DM Sans', sans-serif", size: 11 }},
                color: '#9ca3af',
                callback: function(v) {{ return fmtNum(v); }}
            }},
            border: {{ display: false }}
        }}
    }}
}};

function DEFAULTS_PCT() {{
    var d = JSON.parse(JSON.stringify(DEFAULTS));
    d.scales.y.ticks.callback = function(v) {{ return v + '%'; }};
    d.plugins.tooltip.callbacks.label = function(ctx) {{
        return ' ' + ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(1) + '%';
    }};
    return d;
}}

new Chart(document.getElementById('ch_seg'), {{
    type: 'bar',
    data: {{
        labels: NOMES,
        datasets: [{{
            label: 'Seguidores',
            data: SEGS,
            backgroundColor: CORES,
            borderRadius: 6,
            borderSkipped: false,
        }}]
    }},
    options: DEFAULTS
}});
makeLegend('leg_seg', NOMES, SEGS, '');

new Chart(document.getElementById('ch_eng'), {{
    type: 'bar',
    data: {{
        labels: NOMES,
        datasets: [{{
            label: 'Engajamento %',
            data: ENG_PCT,
            backgroundColor: CORES,
            borderRadius: 6,
            borderSkipped: false,
        }}]
    }},
    options: DEFAULTS_PCT()
}});
makeLegend('leg_eng', NOMES, ENG_PCT, '%');

new Chart(document.getElementById('ch_posts'), {{
    type: 'bar',
    data: {{
        labels: NOMES,
        datasets: [{{
            label: 'Publicações',
            data: POSTS,
            backgroundColor: CORES,
            borderRadius: 6,
            borderSkipped: false,
        }}]
    }},
    options: DEFAULTS
}});
makeLegend('leg_posts', NOMES, POSTS, '');

new Chart(document.getElementById('ch_engmed'), {{
    type: 'bar',
    data: {{
        labels: NOMES,
        datasets: [{{
            label: 'Eng. médio',
            data: ENG_MED,
            backgroundColor: CORES,
            borderRadius: 6,
            borderSkipped: false,
        }}]
    }},
    options: DEFAULTS
}});
makeLegend('leg_engmed', NOMES, ENG_MED, '');

function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = (h + 8) + 'px'; break;
        }} }} catch(e) {{}}
    }}
}}
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 300); setTimeout(syncHeight, 800);
</script>
</body></html>
""", height=560, scrolling=False)

    else:
        st.markdown("""
        <div style='background:#fff;border:1px dashed #d1d5db;border-radius:14px;
                    padding:36px 32px;text-align:center;margin-bottom:24px'>
            <div style='font-size:28px;margin-bottom:10px'>📊</div>
            <div style='font-size:15px;font-weight:600;color:#374151;margin-bottom:6px'>Sem dados de redes sociais</div>
            <div style='font-size:13px;color:#9ca3af'>Acesse <b>Redes Sociais</b> e clique em <b>Coletar dados</b> para ver os gráficos aqui.</div>
        </div>
        """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # BLOCO 3: COMPARATIVO DE ADS
    # ══════════════════════════════════════════════════════════════

    empresas_com_ads = {k: v for k, v in ads_cache.items() if v.get("data")}
    if empresas_com_ads:
        st.markdown(
            "<div style='font-size:16px;font-weight:700;color:#1a2e4a;"
            "letter-spacing:0.2px;margin:8px 0 14px'>📢 Comparativo — Anúncios Meta</div>",
            unsafe_allow_html=True,
        )

        ads_nomes  = list(empresas_com_ads.keys())
        ads_totais = [len(v.get("data", [])) for v in empresas_com_ads.values()]
        ads_ativos = [sum(1 for a in v.get("data",[]) if a.get("ativo",True)) for v in empresas_com_ads.values()]
        ads_cores  = []
        for nome in ads_nomes:
            idx_e = next((i for i,e in enumerate(todas_empresas_geral) if e["nome"]==nome), 0)
            ads_cores.append(get_avatar_color(idx_e))

        ads_nomes_json  = _json.dumps(ads_nomes, ensure_ascii=False)
        ads_totais_json = _json.dumps(ads_totais)
        ads_ativos_json = _json.dumps(ads_ativos)
        ads_cores_json  = _json.dumps(ads_cores)

        components.html(f"""
<!DOCTYPE html><html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
body {{ padding-bottom:8px; }}
.wrap {{ background:#fff; border:1px solid #e5e7eb; border-radius:14px; padding:18px 20px 14px; }}
.card-title {{
    font-size:12px; font-weight:800; color:#1a2e4a;
    text-transform:uppercase; letter-spacing:0.6px;
    padding-bottom:10px; border-bottom:1px solid #f3f4f6; margin-bottom:12px;
}}
.chart-wrap {{ position:relative; width:100%; height:180px; }}
.legend {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:10px; font-size:11px; color:#6b7280; }}
.leg-item {{ display:flex; align-items:center; gap:5px; }}
.leg-dot {{ width:10px; height:10px; border-radius:2px; flex-shrink:0; }}
</style>
</head>
<body>
<div class="wrap">
    <div class="card-title">Total de Anúncios por Empresa</div>
    <div class="chart-wrap"><canvas id="ch_ads" role="img" aria-label="Comparativo de anúncios"></canvas></div>
    <div class="legend" id="leg_ads"></div>
</div>
<script>
var NOMES   = {ads_nomes_json};
var TOTAIS  = {ads_totais_json};
var ATIVOS  = {ads_ativos_json};
var CORES   = {ads_cores_json};

function fmtNum(n) {{
    n = Math.round(n);
    if (n >= 1000) return (n/1000).toFixed(1) + 'K';
    return String(n);
}}

new Chart(document.getElementById('ch_ads'), {{
    type: 'bar',
    data: {{
        labels: NOMES,
        datasets: [
            {{
                label: 'Ativos',
                data: ATIVOS,
                backgroundColor: CORES,
                borderRadius: 6,
                borderSkipped: false,
            }},
            {{
                label: 'Histórico',
                data: TOTAIS.map(function(t,i) {{ return t - ATIVOS[i]; }}),
                backgroundColor: CORES.map(function(c) {{ return c + '55'; }}),
                borderRadius: 6,
                borderSkipped: false,
            }}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{
                stacked: true,
                grid: {{ display: false }},
                ticks: {{ font: {{ family:"'DM Sans',sans-serif", size:11, weight:'600' }}, color:'#6b7280', maxRotation:0 }},
                border: {{ display: false }}
            }},
            y: {{
                stacked: true,
                grid: {{ color: '#f3f4f6' }},
                ticks: {{ font: {{ family:"'DM Sans',sans-serif", size:11 }}, color:'#9ca3af' }},
                border: {{ display: false }}
            }}
        }}
    }}
}});

var legEl = document.getElementById('leg_ads');
NOMES.forEach(function(name, i) {{
    var item = document.createElement('span');
    item.className = 'leg-item';
    var dot = document.createElement('span');
    dot.className = 'leg-dot';
    dot.style.background = CORES[i];
    item.appendChild(dot);
    var txt = document.createTextNode(name + ' ' + ATIVOS[i] + ' ativos / ' + TOTAIS[i] + ' total');
    item.appendChild(txt);
    legEl.appendChild(item);
}});

function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = (h + 8) + 'px'; break;
        }} }} catch(e) {{}}
    }}
}}
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
setTimeout(syncHeight, 300); setTimeout(syncHeight, 800);
</script>
</body></html>
""", height=280, scrolling=False)

    # ── Aviso se sem dados ──────────────────────────────────────────
    if not ok_redes and not empresas_com_ads:
        st.markdown("""
        <div style='background:#fffbeb;border:1px solid #fcd34d;border-radius:12px;
                    padding:14px 18px;font-size:14px;color:#92400e;
                    display:flex;align-items:flex-start;gap:12px;margin-top:12px'>
            <span style='font-size:20px;flex-shrink:0'>💡</span>
            <div>
                <b>Para enriquecer este painel:</b><br>
                • Acesse <b>Redes Sociais</b> → clique em <b>Coletar dados</b> para ver os gráficos de Instagram<br>
                • Acesse <b>Biblioteca de Ads</b> → configure e busque anúncios para ver o comparativo de Meta Ads
            </div>
        </div>
        """, unsafe_allow_html=True)


# ---------------------------------------------------
# PAGINA - CONFRONTO DE SITES
# ---------------------------------------------------
 
elif st.session_state.pagina == "sites":

    import datetime as _dt
    import json as _json_sites

    emp = st.session_state.dados["minha_empresa"]
    concorrentes = st.session_state.dados["concorrentes"]

    if "redes_analises_salvas" not in st.session_state:
        st.session_state.redes_analises_salvas = []
    if "redes_analise_vistas" not in st.session_state:
        st.session_state.redes_analise_vistas = 0

    # ── Inicializar estados ────────────────────────────────────────
    if "sites_main_tab" not in st.session_state:
        st.session_state.sites_main_tab = "sites"
    if "relatorio_sites" not in st.session_state:
        st.session_state.relatorio_sites = {}
    if "relatorio_gemini" not in st.session_state:
        st.session_state.relatorio_gemini = ""
    if "analises_salvas" not in st.session_state:
        st.session_state.analises_salvas = []
    if "sites_analise_vistas" not in st.session_state:
        st.session_state.sites_analise_vistas = 0

    # ── Montar lista de sites ──────────────────────────────────────
    sites_disponiveis = []
    if emp.get("site"):
        sites_disponiveis.append({
            "nome": emp["nome"], "url": emp["site"],
            "tipo": "minha", "instagram": emp.get("instagram", "")
        })
    for c in concorrentes:
        if c.get("url"):
            sites_disponiveis.append({
                "nome": c["nome"], "url": c["url"],
                "tipo": "concorrente", "instagram": c.get("instagram", "")
            })

    if not sites_disponiveis:
        st.info("Cadastre o site da sua empresa e de pelo menos um concorrente para usar esta funcionalidade.")
        st.stop()

    # ── Estado das análises individuais ───────────────────────────
    for idx_s, s in enumerate(sites_disponiveis):
        chave = f"sites_analise_{idx_s}"
        if chave not in st.session_state:
            st.session_state[chave] = ""

    # ── Cabeçalho ──────────────────────────────────────────────────
    h1, h2 = st.columns([7, 3])
    with h1:
        components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; }
.titulo {
    font-family: 'Animo', 'DM Sans', sans-serif;
    font-size: 32px; font-weight: 700; color: #1a2e4a;
    text-transform: uppercase; margin: 0 0 6px 0; letter-spacing: 0.5px;
}
.sub { font-family: 'DM Sans', sans-serif; font-size: 14px; color: #6b7280; }
</style>
<div class="titulo">Confronto de Sites</div>
<div class="sub">Análise comparativa de posicionamento via IA.</div>
""", height=65)

    with h2:
        gerar_btn = st.button("Gerar Relatório Geral", type="primary", use_container_width=True)
        ultimo_relatorio = st.session_state.get("sites_ultima_geracao", "")
        if ultimo_relatorio:
            st.markdown(
                f"<div style='font-size:13px;color:#6b7280;text-align:center;margin-top:-8px'>"
                f"🕒 Última análise: <b>{ultimo_relatorio}</b></div>",
                unsafe_allow_html=True,
            )

    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:8px 0 8px 0'/>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # GHOST BUTTONS — Navegação de abas
    # ══════════════════════════════════════════════════════════════
    st.markdown("""
    <style>
    .st-key-_sites_ghost_tab_sites_,
    .st-key-_sites_ghost_tab_analise_ {
        position: fixed !important; top: -9999px !important; left: -9999px !important;
        width: 0 !important; height: 0 !important; overflow: hidden !important;
        opacity: 0 !important; pointer-events: none !important; visibility: hidden !important; display: none !important;
    }
    .stElementContainer:has(.st-key-_sites_ghost_tab_sites_),
    .stElementContainer:has(.st-key-_sites_ghost_tab_analise_) {
        display: none !important; height: 0 !important; min-height: 0 !important;
        max-height: 0 !important; padding: 0 !important; margin: 0 !important; overflow: hidden !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if st.button("sites_tab", key="_sites_ghost_tab_sites_"):
        st.session_state.sites_main_tab = "sites"
        st.rerun()
    if st.button("analise_tab", key="_sites_ghost_tab_analise_"):
        st.session_state.sites_main_tab = "analise"
        st.rerun()

    # ══════════════════════════════════════════════════════════════
    # GHOST BUTTONS — Análise individual por site
    # ══════════════════════════════════════════════════════════════
    ghost_css_ia = "\n".join([
        f".st-key-btn_site_ia_{i} {{ display: none !important; }}"
        f".stElementContainer:has(.st-key-btn_site_ia_{i}) {{ display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; }}"
        for i in range(len(sites_disponiveis))
    ])
    st.markdown(f"<style>{ghost_css_ia}</style>", unsafe_allow_html=True)

    site_ia_triggers = {}
    for idx_s in range(len(sites_disponiveis)):
        triggered = st.button(
            f"SITE_IA_{idx_s}",
            key=f"btn_site_ia_{idx_s}",
        )
        site_ia_triggers[idx_s] = triggered

    # ══════════════════════════════════════════════════════════════
    # GHOST BUTTONS — Remover análises salvas
    # ══════════════════════════════════════════════════════════════
    analises_para_rm = st.session_state.get("analises_salvas", [])
    acoes_rm = {}
    for i in range(len(analises_para_rm)):
        acoes_rm[f"rm_{i}"] = st.button(f"_rm_analise_{i}_", key=f"btn_rm_analise_{i}")

    rm_css = "\n".join([
        f".st-key-btn_rm_analise_{i} {{ display: none !important; }}"
        f".stElementContainer:has(.st-key-btn_rm_analise_{i}) {{ display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; }}"
        for i in range(len(analises_para_rm))
    ])
    st.markdown(f"<style>{rm_css}</style>", unsafe_allow_html=True)

    for i in range(len(analises_para_rm) - 1, -1, -1):
        if acoes_rm.get(f"rm_{i}"):
            st.session_state.analises_salvas.pop(i)
            salvar_dados_usuario(st.session_state.user.id)
            st.rerun()

    # ══════════════════════════════════════════════════════════════
    # PROCESSAR — Análise individual com overlay de loading
    # ══════════════════════════════════════════════════════════════
    for idx_s, s in enumerate(sites_disponiveis):
        if site_ia_triggers.get(idx_s):
            is_minha = s["tipo"] == "minha"
            if gemini_model is None:
                st.session_state[f"sites_analise_{idx_s}"] = "⚠️ Configure GEMINI_API_KEY nos secrets."
            else:
                modal_site_placeholder = st.empty()

                def _render_modal_site(fase: str, nome: str, pct: int, _ph=modal_site_placeholder):
                    fases = {
                        "lendo":     ("Acessando o site…",       "Lendo conteúdo da página…"),
                        "enviando":  ("Enviando para o Gemini…", "Processando com IA…"),
                        "gerando":   ("Gerando relatório…",      "Finalizando análise…"),
                        "concluido": ("Análise concluída!",      "Redirecionando…"),
                    }
                    sub1, sub2 = fases.get(fase, ("Processando…", "Aguarde…"))
                    is_done  = fase == "concluido"
                    cor_pct  = "#22c55e" if is_done else "#3a9fd6"
                    icone    = "✅" if is_done else "⏳"
                    rodape   = (
                        '<div style="text-align:center;margin-top:18px;font-size:13px;color:#64748b;">'
                        'Fechando automaticamente…</div>'
                    ) if is_done else ""

                    nome_safe = (nome or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("'", "&#39;").replace('"', "&quot;")

                    html_modal = f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.overlay {{
    position:fixed; inset:0;
    background:rgba(0,0,0,0.72);
    z-index:999999;
    display:flex; align-items:center; justify-content:center;
    padding:24px;
}}
.card {{
    background:#0e2a47;
    border-radius:20px;
    padding:32px;
    width:min(95vw,480px);
    box-shadow:0 20px 60px rgba(0,0,0,0.5);
    border:1px solid #1e3a5f;
}}
.spin-wrap {{
    width:44px; height:44px; border-radius:50%;
    border:3px solid #1e3a5f;
    border-top-color:#3a9fd6;
    flex-shrink:0;
    animation: spin 0.85s linear infinite;
}}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style>
<div class="overlay">
<div class="card">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;">
        {'<div style="width:44px;height:44px;border-radius:50%;background:#22c55e;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;">✅</div>' if is_done else '<div class="spin-wrap"></div>'}
        <div style="flex:1;min-width:0;">
            <div style="font-size:17px;font-weight:800;color:#f1f5f9;">{sub1}</div>
            <div style="font-size:13px;color:#94a3b8;margin-top:3px;">{sub2}</div>
        </div>
        <div style="font-size:22px;font-weight:900;color:{cor_pct};flex-shrink:0;">{pct}%</div>
    </div>
    <div style="background:#1e3a5f;border-radius:8px;height:8px;margin-bottom:20px;overflow:hidden;">
        <div style="background:linear-gradient(90deg,#3a9fd6,#22c55e);height:100%;width:{pct}%;border-radius:8px;"></div>
    </div>
    <div style="background:#071929;border-radius:12px;padding:14px 18px;
                display:flex;align-items:center;justify-content:space-between;gap:12px;
                border:1px solid #1a3a5a;margin-bottom:4px;">
        <div>
            <div style="font-size:14px;font-weight:700;color:#e2e8f0;">{nome_safe}</div>
            <div style="font-size:12px;color:#4a7099;margin-top:3px;">Analisando site com IA…</div>
        </div>
        <div style="font-size:18px;">{icone}</div>
    </div>
    {rodape}
</div>
</div>
<script>
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.position = 'fixed';
                iframes[i].style.inset    = '0';
                iframes[i].style.width    = '100vw';
                iframes[i].style.height   = '100vh';
                iframes[i].style.zIndex   = '999998';
                iframes[i].style.border   = 'none';
                break;
            }}
        }} catch(e) {{}}
    }}
}})();
</script>
"""
                    with _ph:
                        components.html(html_modal, height=600, scrolling=False)

                _render_modal_site("lendo", s["nome"], 15)
                conteudo_site = extrair_conteudo_site(s["url"])

                _render_modal_site("enviando", s["nome"], 50)
                try:
                    prompt_individual = f"""
Você é um especialista em marketing digital e posicionamento de marca.
Analise o conteúdo extraído do site abaixo e gere uma análise individual detalhada em português.

Empresa: {s['nome']} ({s['url']})
URL: {s['url']}
Tipo: {"Minha Empresa" if is_minha else "Concorrente"}

Conteúdo extraído do site:
{conteudo_site[:4000] if conteudo_site else "Não foi possível extrair conteúdo."}

---

IMPORTANTE: Sempre que mencionar o nome da empresa ao longo do relatório, inclua o endereço do site entre parênteses. Exemplo: "{s['nome']} ({s['url']})".

Responda com as seguintes seções:

### 📌 Proposta de Valor
Qual é a proposta central comunicada no site?

### 🎯 Posicionamento
Como esta empresa se posiciona no mercado? (premium, popular, nicho, generalista etc.)

### 🔑 Mensagens Principais
Quais são os termos, promessas e mensagens mais repetidos?

### 🛠️ Serviços / Produtos Destacados
Liste os principais serviços ou produtos apresentados no site.

### ✅ Pontos Fortes
3 pontos positivos observados na comunicação do site.

### ⚠️ Pontos de Atenção
2 pontos que poderiam ser melhorados.

### 💡 Recomendação
1 ação concreta de alto impacto para melhorar o posicionamento.

Seja direto e objetivo, baseando-se apenas no conteúdo real do site.
"""
                    _render_modal_site("gerando", s["nome"], 80)
                    resp = gemini_model.generate_content(prompt_individual)
                    st.session_state[f"sites_analise_{idx_s}"] = resp.text

                    # ── Remove duplicata e salva ──
                    st.session_state.analises_salvas = [
                        a for a in st.session_state.analises_salvas
                        if not (a.get("tipo") == "individual" and s["nome"] in a.get("sites", []))
                    ]
                    titulo_auto = f"Análise Individual — {s['nome']} ({s['url']}) — {_dt.datetime.now().strftime('%d/%m/%Y %H:%M')}"
                    st.session_state.analises_salvas.append({
                        "titulo": titulo_auto,
                        "data": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "relatorio": resp.text,
                        "sites": [f"{s['nome']} ({s['url']})"],
                        "tipo": "individual",
                        "empresa": f"{s['nome']} ({s['url']})",
                        "url": s["url"],
                    })

                    salvar_dados_usuario(st.session_state.user.id)

                    _render_modal_site("concluido", s["nome"], 100)
                    import time as _time; _time.sleep(1.5)
                    modal_site_placeholder.empty()

                    st.session_state.sites_main_tab = "analise"
                    st.rerun()

                except Exception as e:
                    modal_site_placeholder.empty()
                    st.session_state[f"sites_analise_{idx_s}"] = f"Erro: {e}"
                    st.rerun()

    # ══════════════════════════════════════════════════════════════
    # PROCESSAR — Relatório geral com modal de loading
    # ══════════════════════════════════════════════════════════════
    if gerar_btn:
        st.session_state.relatorio_gemini = ""
        st.session_state.relatorio_sites = {}

        modal_geral_placeholder = st.empty()

        def _render_modal_geral(fase: str, descricao: str, pct: int, _ph=modal_geral_placeholder):
            fases = {
                "lendo":     ("Acessando os sites…",       "Lendo conteúdo das páginas…"),
                "enviando":  ("Enviando para o Gemini…",   "Processando com IA…"),
                "gerando":   ("Gerando relatório geral…",  "Comparando posicionamentos…"),
                "concluido": ("Relatório concluído!",       "Redirecionando…"),
            }
            sub1, sub2 = fases.get(fase, ("Processando…", "Aguarde…"))
            is_done  = fase == "concluido"
            cor_pct  = "#22c55e" if is_done else "#3a9fd6"
            icone    = "✅" if is_done else "⏳"
            rodape   = (
                '<div style="text-align:center;margin-top:18px;font-size:13px;color:#64748b;">'
                'Fechando automaticamente…</div>'
            ) if is_done else ""

            desc_safe = (descricao or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("'","&#39;").replace('"',"&quot;")

            html_modal = f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.overlay {{
    position:fixed; inset:0;
    background:rgba(0,0,0,0.72);
    z-index:999999;
    display:flex; align-items:center; justify-content:center;
    padding:24px;
}}
.card {{
    background:#0e2a47;
    border-radius:20px;
    padding:32px;
    width:min(95vw,480px);
    box-shadow:0 20px 60px rgba(0,0,0,0.5);
    border:1px solid #1e3a5f;
}}
.spin-wrap {{
    width:44px; height:44px; border-radius:50%;
    border:3px solid #1e3a5f;
    border-top-color:#3a9fd6;
    flex-shrink:0;
    animation: spin 0.85s linear infinite;
}}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style>
<div class="overlay">
<div class="card">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;">
        {'<div style="width:44px;height:44px;border-radius:50%;background:#22c55e;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;">✅</div>' if is_done else '<div class="spin-wrap"></div>'}
        <div style="flex:1;min-width:0;">
            <div style="font-size:17px;font-weight:800;color:#f1f5f9;">{sub1}</div>
            <div style="font-size:13px;color:#94a3b8;margin-top:3px;">{sub2}</div>
        </div>
        <div style="font-size:22px;font-weight:900;color:{cor_pct};flex-shrink:0;">{pct}%</div>
    </div>
    <div style="background:#1e3a5f;border-radius:8px;height:8px;margin-bottom:20px;overflow:hidden;">
        <div style="background:linear-gradient(90deg,#3a9fd6,#22c55e);height:100%;width:{pct}%;border-radius:8px;transition:width 0.3s;"></div>
    </div>
    <div style="background:#071929;border-radius:12px;padding:14px 18px;
                display:flex;align-items:center;justify-content:space-between;gap:12px;
                border:1px solid #1a3a5a;margin-bottom:4px;">
        <div>
            <div style="font-size:14px;font-weight:700;color:#e2e8f0;">{desc_safe}</div>
            <div style="font-size:12px;color:#4a7099;margin-top:3px;">Relatório comparativo geral…</div>
        </div>
        <div style="font-size:18px;">{icone}</div>
    </div>
    {rodape}
</div>
</div>
<script>
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.position = 'fixed';
                iframes[i].style.inset    = '0';
                iframes[i].style.width    = '100vw';
                iframes[i].style.height   = '100vh';
                iframes[i].style.zIndex   = '999998';
                iframes[i].style.border   = 'none';
                break;
            }}
        }} catch(e) {{}}
    }}
}})();
</script>
"""
            with _ph:
                components.html(html_modal, height=600, scrolling=False)

        # ── Lendo os sites com modal ──
        total_sites = len(sites_disponiveis)
        for i_s, s in enumerate(sites_disponiveis):
            pct_leitura = int(10 + (i_s / total_sites) * 35)
            _render_modal_geral("lendo", f"Lendo {s['nome']} ({s['url']}) — {i_s + 1}/{total_sites}", pct_leitura)
            conteudo = extrair_conteudo_site(s["url"])
            st.session_state.relatorio_sites[s["url"]] = conteudo

        _render_modal_geral("enviando", f"{total_sites} site{'s' if total_sites != 1 else ''} lido{'s' if total_sites != 1 else ''} — enviando para IA…", 55)

        empresa_principal = None
        concorrentes_data = []
        for s in sites_disponiveis:
            item = {
                "nome": s["nome"],
                "url":  s["url"],
                "conteudo": st.session_state.relatorio_sites.get(s["url"], ""),
            }
            if s["tipo"] == "minha":
                empresa_principal = item
            else:
                concorrentes_data.append(item)

        if empresa_principal is None and sites_disponiveis:
            empresa_principal = {
                "nome": sites_disponiveis[0]["nome"],
                "url":  sites_disponiveis[0]["url"],
                "conteudo": st.session_state.relatorio_sites.get(sites_disponiveis[0]["url"], ""),
            }

        _render_modal_geral("gerando", "Comparando posicionamentos…", 80)

        relatorio = gerar_relatorio_posicionamento(empresa_principal, concorrentes_data)
        st.session_state.relatorio_gemini = relatorio
        st.session_state["sites_ultima_geracao"] = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")

        # ── Título com nomes + URLs de todos os sites ──
        nomes_com_url = [f"{s['nome']} ({s['url']})" for s in sites_disponiveis]
        titulo_auto = f"Relatório Geral — {' vs. '.join(nomes_com_url)} — {_dt.datetime.now().strftime('%d/%m/%Y %H:%M')}"
        st.session_state.analises_salvas.append({
            "titulo": titulo_auto,
            "data": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
            "relatorio": relatorio,
            "sites": nomes_com_url,
            "tipo": "geral",
        })

        salvar_dados_usuario(st.session_state.user.id)

        _render_modal_geral("concluido", "Relatório geral pronto!", 100)
        import time as _time; _time.sleep(1.5)
        modal_geral_placeholder.empty()

        st.session_state.sites_main_tab = "analise"
        st.rerun()

    # ══════════════════════════════════════════════════════════════
    # BARRA DE NAVEGAÇÃO PRINCIPAL — Com contagens e badge NOVA
    # ══════════════════════════════════════════════════════════════
    main_tab = st.session_state.sites_main_tab
    analises_nav = st.session_state.get("analises_salvas", [])
    qtd_total_analise = len(analises_nav)

    nao_lidas = max(0, qtd_total_analise - st.session_state.sites_analise_vistas)
    if main_tab == "analise":
        st.session_state.sites_analise_vistas = qtd_total_analise
        nao_lidas = 0

    components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; -webkit-font-smoothing:antialiased; }}
.nav-bar {{ display:grid; grid-template-columns: 1fr 1fr; gap:12px; width:100%; }}
.nav-item {{
    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
    padding:16px 20px; cursor:pointer; display:flex; align-items:center;
    gap:14px; transition:all 0.15s; position:relative; overflow:hidden;
}}
.nav-item:hover {{ border-color:#3a9fd6; box-shadow:0 2px 12px rgba(58,159,214,0.12); }}
.nav-item.active {{
    background:#0e2a47; border-color:#0e2a47;
    box-shadow:0 4px 20px rgba(14,42,71,0.22);
}}
.nav-item.active::after {{
    content:''; position:absolute; bottom:0;left:0;right:0; height:3px;
    background:linear-gradient(90deg,#3a9fd6,#2ecc71);
    border-radius:0 0 14px 14px;
}}
.nav-icon {{
    width:40px;height:40px;border-radius:10px;
    display:flex;align-items:center;justify-content:center;
    flex-shrink:0; background:#f3f4f6; transition:background 0.15s;
}}
.nav-item.active .nav-icon {{ background:rgba(255,255,255,0.12); }}
.nav-icon svg {{ width:20px;height:20px; }}
.nav-content {{ flex:1;min-width:0; }}
.nav-title {{ font-size:15px;font-weight:700;color:#1a2e4a; display:block;margin-bottom:2px; }}
.nav-item.active .nav-title {{ color:#ffffff; }}
.nav-sub {{ font-size:12px;color:#9ca3af; }}
.nav-item.active .nav-sub {{ color:rgba(255,255,255,0.55); }}
.nav-right {{ display:flex; flex-direction:column; align-items:flex-end; gap:5px; flex-shrink:0; }}
.count-badge {{
    min-width:26px; height:26px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-size:12px; font-weight:800; padding:0 5px;
    background:#e5e7eb; color:#6b7280;
}}
.count-badge.has {{ background:#3a9fd6; color:#fff; }}
.nav-item.active .count-badge {{ background:rgba(255,255,255,0.18); color:#fff; }}
.nav-item.active .count-badge.has {{ background:rgba(58,159,214,0.5); color:#fff; }}
.new-badge {{
    background:#ef4444; color:#fff;
    font-size:10px; font-weight:800;
    padding:2px 7px; border-radius:20px;
    letter-spacing:0.3px; text-transform:uppercase;
    animation: pulse 1.5s infinite;
}}
@keyframes pulse {{
    0%,100% {{ opacity:1; transform:scale(1); }}
    50%      {{ opacity:0.75; transform:scale(0.95); }}
}}
</style>
<div class="nav-bar">

    <div class="nav-item {'active' if main_tab == 'sites' else ''}" onclick="triggerTab('sites_tab')">
        <div class="nav-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="{'#ffffff' if main_tab == 'sites' else '#6b7280'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <line x1="2" y1="12" x2="22" y2="12"/>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
        </div>
        <div class="nav-content">
            <span class="nav-title">Sites configurados</span>
            <span class="nav-sub">Visualize e analise individualmente</span>
        </div>
        <div class="nav-right">
            <div class="count-badge {'has' if len(sites_disponiveis) > 0 else ''}">{len(sites_disponiveis)}</div>
        </div>
    </div>

    <div class="nav-item {'active' if main_tab == 'analise' else ''}" onclick="triggerTab('analise_tab')">
        <div class="nav-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="{'#ffffff' if main_tab == 'analise' else '#6b7280'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
        </div>
        <div class="nav-content">
            <span class="nav-title">Análise de IA</span>
            <span class="nav-sub">Relatórios individuais e comparativos</span>
        </div>
        <div class="nav-right">
            <div class="count-badge {'has' if qtd_total_analise > 0 else ''}">{qtd_total_analise}</div>
            {'<div class="new-badge">NOVA</div>' if nao_lidas > 0 else ''}
        </div>
    </div>

</div>
<script>
function triggerTab(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(' ').filter(Boolean).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
          if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '90px';
            iframes[i].style.marginTop = '-10px';
            break;
          }}
        }} catch(e) {{}}
    }}
}})();
</script>
""", height=90, scrolling=False)

    # ══════════════════════════════════════════════════════════════
    # ABA: SITES CONFIGURADOS
    # ══════════════════════════════════════════════════════════════
    if main_tab == "sites":

        cards_data = []
        for idx_s, s in enumerate(sites_disponiveis):
            is_minha   = s["tipo"] == "minha"
            cor_avatar = get_minha_empresa_color() if is_minha else get_concorrente_color(idx_s - 1 if not is_minha else 0)
            badge_bg   = "#f0fdf4" if is_minha else "#eff6ff"
            badge_txt  = "#15803d" if is_minha else "#1d4ed8"
            badge_brd  = "#bbf7d0" if is_minha else "#bfdbfe"
            badge_lbl  = "Minha Empresa" if is_minha else "Concorrente"
            avatar_letras = gerar_avatar(s["nome"])
            tem_analise = bool(st.session_state.get(f"sites_analise_{idx_s}", ""))

            ultima_analise = ""
            for a in reversed(st.session_state.get("analises_salvas", [])):
                if a.get("tipo") == "individual" and s["nome"] in a.get("sites", []):
                    ultima_analise = a.get("data", "")
                    break

            cards_data.append({
                "idx":            idx_s,
                "nome":           s["nome"],
                "url":            s["url"],
                "tipo":           s["tipo"],
                "cor":            cor_avatar,
                "badge_bg":       badge_bg,
                "badge_txt":      badge_txt,
                "badge_brd":      badge_brd,
                "badge_lbl":      badge_lbl,
                "avatar":         avatar_letras,
                "tem_analise":    tem_analise,
                "ultima_analise": ultima_analise,
            })

        cards_json_str = _json_sites.dumps(cards_data, ensure_ascii=True)

        _html_cards = f"""<!DOCTYPE html><html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
    background:transparent; font-family:'DM Sans',sans-serif;
    -webkit-font-smoothing:antialiased; overflow:visible;
}}
body {{ padding-bottom:8px; }}
.outer-wrap {{ background:#d2dde9; border-radius:16px; padding:20px; }}
.cards-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:20px; }}
.site-card {{
    background:#fff; border:1px solid #fff; border-radius:14px;
    overflow:hidden; display:flex; flex-direction:column;
    transition:box-shadow 0.15s; box-shadow:0 4px 20px rgba(0,0,0,0.10);
}}
.site-card:hover {{ border:1px solid #6fd1f3!important; }}
.card-header {{
    display:flex; align-items:center; gap:12px;
    padding:16px 18px 14px; border-bottom:1px solid #f3f4f6;
}}
.avatar {{
    width:40px;height:40px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    font-size:14px;font-weight:700;color:#fff;flex-shrink:0;
}}
.card-name {{ font-size:16px;font-weight:700;color:#111827; white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }}
.badge {{ display:inline-block; padding:2px 10px;border-radius:20px; font-size:11px;font-weight:700; }}
.url-row {{
    display:flex;align-items:center;gap:6px; padding:9px 18px;
    font-size:13px;font-weight:600;color:#374151;
    border-bottom:1px solid #f3f4f6; background:#fafbfc;
    overflow:hidden; white-space:nowrap; text-overflow:ellipsis;
}}
.preview-wrap {{
    margin:14px; border-radius:10px; overflow:hidden;
    border:1px solid #e5e7eb; background:#f9fafb;
    aspect-ratio:16/9; position:relative; flex-shrink:0;
}}
.preview-wrap img {{
    width:100%;height:100%; display:block;
    object-fit:cover; object-position:top; border-radius:10px;
}}
.preview-fallback {{
    width:100%;height:100%; display:flex;align-items:center;justify-content:center;
    flex-direction:column;gap:8px; background:#f3f4f6;border-radius:10px;
}}
.analise-badge {{
    margin: 0 14px 10px;
    padding: 9px 14px;
    background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
    border: 1px solid #86efac;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    color: #15803d;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    cursor: pointer;
    transition: all 0.15s;
}}
.analise-badge:hover {{
    background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
    border-color: #4ade80;
    box-shadow: 0 2px 8px rgba(34,197,94,0.15);
    transform: translateY(-1px);
}}
.analise-badge-left {{ display: flex; align-items: center; gap: 7px; }}
.analise-badge-arrow {{ font-size: 14px; opacity: 0.7; }}
.btn-wrap {{ padding:0 14px 16px; }}
.btn-analisar {{
    width:100%;padding:11px 0;
    border:1px solid #3a9fd6;border-radius:8px;
    background:#eff6ff;font-size:14px;font-weight:700;color:#1d4ed8;
    cursor:pointer;font-family:'DM Sans',sans-serif;
    transition:background 0.15s;
    display:flex;align-items:center;justify-content:center;gap:7px;
}}
.btn-analisar:hover {{ background:#dbeafe; }}
</style>
</head>
<body>
<div class="outer-wrap">
    <div class="cards-grid" id="cards-grid"></div>
</div>

<script>
var CARDS = {cards_json_str};

function buildCards() {{
    var grid = document.getElementById('cards-grid');
    grid.innerHTML = '';
    CARDS.forEach(function(c) {{
        var card = document.createElement('div');
        card.className = 'site-card';

        var hdr = document.createElement('div');
        hdr.className = 'card-header';
        hdr.innerHTML =
            '<div class="avatar" style="background:' + c.cor + '">' + c.avatar + '</div>'
            + '<div style="flex:1;min-width:0">'
            + '<div class="card-name">' + c.nome + '</div>'
            + '<span class="badge" style="background:' + c.badge_bg + ';color:' + c.badge_txt + ';border:1px solid ' + c.badge_brd + '">' + c.badge_lbl + '</span>'
            + '</div>';
        card.appendChild(hdr);

        var urlRow = document.createElement('div');
        urlRow.className = 'url-row';
        urlRow.innerHTML =
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            + '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>'
            + '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'
            + '</svg>'
            + '<span>' + c.url + '</span>';
        card.appendChild(urlRow);

        var prevWrap = document.createElement('div');
        prevWrap.className = 'preview-wrap';
        var img = document.createElement('img');
        img.src = 'https://api.microlink.io/?url=https://' + c.url + '&screenshot=true&meta=false&embed=screenshot.url';
        img.loading = 'lazy';
        img.alt = 'Preview ' + c.nome;
        img.onerror = function() {{
            prevWrap.innerHTML =
                '<div class="preview-fallback">'
                + '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#d1d5db" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>'
                + '<span style="font-size:12px;color:#9ca3af">Prévia indisponível</span>'
                + '</div>';
        }};
        img.addEventListener('load', function() {{ setTimeout(syncHeight, 100); }});
        prevWrap.appendChild(img);
        card.appendChild(prevWrap);

        if (c.tem_analise && c.ultima_analise) {{
            var abadge = document.createElement('div');
            abadge.className = 'analise-badge';
            abadge.title = 'Ver análise na aba Análise de IA';
            abadge.innerHTML =
                '<div class="analise-badge-left">'
                + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#15803d" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
                + '<span>Última análise: <b>' + c.ultima_analise + '</b></span>'
                + '</div>'
                + '<span class="analise-badge-arrow">→ Ver análise</span>';
            abadge.onclick = function() {{ triggerAnaliseTab(); }};
            card.appendChild(abadge);
        }}

        var btnWrap = document.createElement('div');
        btnWrap.className = 'btn-wrap';
        var btn = document.createElement('button');
        btn.className = 'btn-analisar';
        btn.id = 'btn_analisar_' + c.idx;
        btn.innerHTML = c.tem_analise ? '🔁 Fazer nova análise' : '✨ Analisar este site com IA';
        btn.onclick = (function(idx, nome, btnEl) {{
            return function() {{
                btnEl.disabled = true;
                btnEl.innerHTML = '⏳ Analisando…';
                triggerSiteIA(idx, nome);
            }};
        }})(c.idx, c.nome, btn);
        btnWrap.appendChild(btn);
        card.appendChild(btnWrap);

        grid.appendChild(card);
    }});
    syncHeight();
}}

function triggerAnaliseTab() {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {{
        var txt = (btns[i].innerText || btns[i].textContent || '').replace(/ +/g,' ').trim();
        if (txt === 'analise_tab') {{ btns[i].click(); return; }}
    }}
}}

function triggerSiteIA(idx, nome) {{
    var targetText = 'SITE_IA_' + idx;
    var btns = window.parent.document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {{
        var txt = (btns[i].innerText || btns[i].textContent || '').replace(/ +/g, ' ').trim();
        if (txt === targetText) {{ btns[i].click(); return; }}
    }}
}}

function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.height = (h + 12) + 'px';
                break;
            }}
        }} catch(e) {{}}
    }}
}}

try {{
    buildCards();
}} catch(err) {{
    document.getElementById('cards-grid').innerHTML =
        '<div style="padding:20px;color:red;font-size:13px">Erro ao renderizar cards: ' + err.message + '</div>';
}}
syncHeight();
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 100);
setTimeout(syncHeight, 300);
setTimeout(syncHeight, 800);
setTimeout(syncHeight, 1500);
setTimeout(syncHeight, 3000);
</script>
</body></html>"""

        components.html(_html_cards, height=1200, scrolling=False)

    # ══════════════════════════════════════════════════════════════
    # ABA: ANÁLISE DE IA
    # ══════════════════════════════════════════════════════════════
    elif main_tab == "analise":

        analises = st.session_state.get("analises_salvas", [])
        analises_individuais = [(i, a) for i, a in enumerate(analises) if a.get("tipo") == "individual"]
        analises_gerais      = [(i, a) for i, a in enumerate(analises) if a.get("tipo") == "geral"]

        # Limpa estado temporário — relatório já foi salvo em analises_salvas
        st.session_state.relatorio_gemini = ""

        # ── Renderiza seções em cards visuais ──
        def _build_analises_html(lista_individuais, lista_gerais):

            relatorios_js = {}
            for i, a in lista_individuais + lista_gerais:
                relatorios_js[str(i)] = (a.get("relatorio") or "")
            relatorios_json = _json_sites.dumps(relatorios_js, ensure_ascii=False)

            def card_item(idx_real, analise):
                titulo          = analise.get("titulo", "—")
                tipo            = analise.get("tipo", "geral")
                icon            = "🏢" if tipo == "individual" else "📋"
                nome_arquivo_js = titulo.replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "").replace(".", "")

                return f"""
<div class="analise-card" id="card_{idx_real}">
    <div class="card-top" onclick="toggleCard({idx_real})">
        <div class="card-icon-wrap">{icon}</div>
        <div class="card-info">
            <div class="card-titulo">{titulo}</div>
        </div>
        <div class="card-chevron" id="chev_{idx_real}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
    </div>
    <div class="card-body" id="body_{idx_real}" style="display:none">
        <div class="card-relatorio" id="rel_{idx_real}"></div>
        <div class="card-acoes">
            <button class="btn-dl" onclick="baixar({idx_real}, '{nome_arquivo_js}')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Baixar .txt
            </button>
            <button class="btn-rm" onclick="remover({idx_real})">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                Remover
            </button>
        </div>
    </div>
</div>"""

            if lista_individuais:
                items_ind = "".join(card_item(i, a) for i, a in reversed(lista_individuais))
                html_ind = f"""
<div class="secao">
    <div class="secao-header">
        <div class="secao-icon ind">🏢</div>
        <div><div class="secao-titulo">Análises Individuais</div></div>
        <div class="secao-count">{len(lista_individuais)}</div>
    </div>
    <div class="secao-cards">{items_ind}</div>
</div>"""
            else:
                html_ind = """
<div class="secao">
    <div class="secao-header">
        <div class="secao-icon ind">🏢</div>
        <div><div class="secao-titulo">Análises Individuais</div></div>
        <div class="secao-count">0</div>
    </div>
    <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <div class="empty-txt">Nenhuma análise individual ainda.<br>Vá em <b>Sites configurados</b> e clique em <b>Analisar este site com IA</b>.</div>
    </div>
</div>"""

            if lista_gerais:
                items_ger = "".join(card_item(i, a) for i, a in reversed(lista_gerais))
                html_ger = f"""
<div class="secao">
    <div class="secao-header">
        <div class="secao-icon ger">📋</div>
        <div><div class="secao-titulo">Relatórios Gerais</div></div>
        <div class="secao-count">{len(lista_gerais)}</div>
    </div>
    <div class="secao-cards">{items_ger}</div>
</div>"""
            else:
                html_ger = """
<div class="secao">
    <div class="secao-header">
        <div class="secao-icon ger">📋</div>
        <div><div class="secao-titulo">Relatórios Gerais</div></div>
        <div class="secao-count">0</div>
    </div>
    <div class="empty-state">
        <div class="empty-icon">📊</div>
        <div class="empty-txt">Nenhum relatório geral ainda.<br>Clique em <b>Gerar Relatório Geral</b> no topo da página.</div>
    </div>
</div>"""

            return f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html {{ background:transparent; font-family:'DM Sans',sans-serif; -webkit-font-smoothing:antialiased; }}
body {{ background:transparent; overflow:visible; padding-bottom:16px; }}
.secao {{ margin-bottom:24px; }}
.secao-header {{
    display:flex; align-items:center; gap:10px;
    padding:0 4px 10px;
    border-bottom:2px solid #e5e7eb;
    margin-bottom:10px;
}}
.secao-titulo {{
    font-size:13px; font-weight:800; color:#6b7280;
    text-transform:uppercase; letter-spacing:0.8px;
}}
.secao-count {{
    margin-left:auto;
    background:#f3f4f6; color:#6b7280;
    font-size:12px; font-weight:700;
    padding:2px 10px; border-radius:20px;
}}
.secao-cards {{
    display:flex; flex-direction:column;
    border:1px solid #e5e7eb; border-radius:12px;
    overflow:hidden; background:#fff;
}}
.analise-card {{ border-bottom:1px solid #f3f4f6; }}
.analise-card:last-child {{ border-bottom:none; }}
.card-top {{
    display:flex; align-items:center; gap:12px;
    padding:14px 16px; cursor:pointer;
    transition:background 0.12s; user-select:none;
}}
.card-top:hover {{ background:#f9fafb; }}
.card-icon-wrap {{ font-size:18px; flex-shrink:0; }}
.card-info {{ flex:1; min-width:0; }}
.card-titulo {{
    font-size:14px; font-weight:600; color:#111827;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.card-chevron {{
    color:#d1d5db; flex-shrink:0;
    transition:transform 0.2s, color 0.15s;
    display:flex; align-items:center;
}}
.card-chevron.open {{ transform:rotate(180deg); color:#3a9fd6; }}
.card-top:hover .card-chevron {{ color:#9ca3af; }}
.card-body {{
    padding:16px; background:#fafbfc;
    border-top:1px solid #f3f4f6;
}}
.card-relatorio {{
    font-size:13px; color:#374151; line-height:1.8;
    max-height:400px; overflow-y:auto;
    padding:14px 16px; border-radius:8px;
    background:#fff; border:1px solid #e5e7eb;
    margin-bottom:12px;
    white-space:pre-wrap; word-break:break-word;
}}
.card-acoes {{ display:flex; gap:8px; }}
.btn-dl {{
    flex:1; padding:9px 14px; border-radius:8px;
    border:1px solid #e5e7eb; background:#fff;
    font-size:13px; font-weight:600; color:#374151;
    cursor:pointer; font-family:'DM Sans',sans-serif;
    transition:all 0.15s;
    display:flex; align-items:center; justify-content:center; gap:6px;
}}
.btn-dl:hover {{ background:#eff6ff; border-color:#3a9fd6; color:#1d4ed8; }}
.btn-rm {{
    padding:9px 14px; border-radius:8px;
    border:1px solid #e5e7eb; background:#fff;
    font-size:13px; font-weight:600; color:#9ca3af;
    cursor:pointer; font-family:'DM Sans',sans-serif;
    transition:all 0.15s; white-space:nowrap;
    display:flex; align-items:center; justify-content:center; gap:6px;
}}
.btn-rm:hover {{ background:#fef2f2; border-color:#fca5a5; color:#dc2626; }}
.empty-state {{
    border:1px dashed #e5e7eb; border-radius:12px;
    padding:32px 24px; text-align:center;
    display:flex; flex-direction:column; align-items:center; gap:8px;
    background:#fff;
}}
.empty-icon {{ font-size:28px; opacity:0.5; }}
.empty-txt {{ font-size:13px; color:#9ca3af; line-height:1.6; }}
</style>

{html_ind}
{html_ger}

<script>
var RELATORIOS = {relatorios_json};

function toggleCard(idx) {{
    var body = document.getElementById('body_' + idx);
    var chev = document.getElementById('chev_' + idx);
    var rel  = document.getElementById('rel_' + idx);
    var aberto = body.style.display !== 'none';
    body.style.display = aberto ? 'none' : 'block';
    chev.classList.toggle('open', !aberto);
    if (!aberto && rel && !rel.dataset.loaded) {{
        rel.textContent = RELATORIOS[String(idx)] || '';
        rel.dataset.loaded = '1';
    }}
    setTimeout(ajustarAltura, 60);
}}

function remover(idx) {{
    var targetText = '_rm_analise_' + idx + '_';
    var btns = window.parent.document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {{
        if ((btns[i].innerText || '').trim() === targetText) {{ btns[i].click(); return; }}
    }}
}}

function baixar(idx, nome) {{
    var conteudo = RELATORIOS[String(idx)] || '';
    var blob = new Blob([conteudo], {{type: 'text/plain;charset=utf-8'}});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = nome + '.txt';
    a.click();
}}

function ajustarAltura() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.height = (h + 8) + 'px'; break;
            }}
        }} catch(e) {{}}
    }}
}}

var ro = new ResizeObserver(ajustarAltura);
ro.observe(document.body);
window.addEventListener('load', ajustarAltura);
setTimeout(ajustarAltura, 200);
setTimeout(ajustarAltura, 600);
setTimeout(ajustarAltura, 1200);
</script>"""

        # ── Renderiza ──
        if not analises:
            components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
html, body { background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }
.empty {
    background:#fff; border:1px dashed #d1d5db; border-radius:14px;
    padding:64px 48px; text-align:center;
    display:flex; flex-direction:column; align-items:center; gap:14px;
}
.empty-icon { font-size:40px; }
.empty-title { font-size:18px; font-weight:700; color:#374151; }
.empty-sub { font-size:14px; color:#9ca3af; line-height:1.7; max-width:400px; }
</style>
<div class="empty">
    <div class="empty-icon">📋</div>
    <div class="empty-title">Nenhuma análise ainda</div>
    <div class="empty-sub">
        Clique em <b>Gerar Relatório Geral</b> ou analise um site individualmente
        na aba <b>Sites configurados</b>.
    </div>
</div>
<script>
(function() {
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        try { if (iframes[i].contentWindow === window) {
            iframes[i].style.height = '300px'; break;
        } } catch(e) {}
    }
})();
</script>
""", height=300, scrolling=False)
        else:
            html_final = _build_analises_html(analises_individuais, analises_gerais)
            components.html(html_final, height=200, scrolling=False)

# ---------------------------------------------------
# PAGINA - ADS (Biblioteca de Anúncios com Meta Ad Library API)
# ---------------------------------------------------

elif st.session_state.pagina == "ads":

    import datetime as _dt
    import json as _json
    import base64 as _b64
    import time as _time

    emp   = st.session_state.dados["minha_empresa"]
    concs = st.session_state.dados["concorrentes"]

    CACHE_TTL_HORAS = 24
    APIFY_ACTOR_ID  = "curious_coder~facebook-ads-library-scraper"

    def carregar_cache_ads() -> dict:
        if st.session_state.get("ads_cache"):
            return st.session_state.ads_cache
        try:
            res = (
                supabase.table("ci_dados")
                .select("ads_cache")
                .eq("user_id", st.session_state.user.id)
                .execute()
            )
            if res.data and res.data[0].get("ads_cache"):
                return res.data[0]["ads_cache"]
        except Exception:
            pass
        return {}

    def merge_ads(cache_existente: dict, novos: dict) -> dict:
        resultado = dict(cache_existente)
        for nome_empresa, novo_entry in novos.items():
            novos_ads = novo_entry.get("data", [])
            novos_ids = {str(a.get("id", "")) for a in novos_ads if a.get("id")}
            entry_existente = resultado.get(nome_empresa, {})
            ads_anteriores = entry_existente.get("data", [])
            ads_anteriores_atualizados = []
            for ad in ads_anteriores:
                ad_id = str(ad.get("id", ""))
                ad["ativo"] = (ad_id in novos_ids) if ad_id else ad.get("ativo", True)
                ads_anteriores_atualizados.append(ad)
            ids_existentes = {str(a.get("id", "")) for a in ads_anteriores_atualizados if a.get("id")}
            for ad in novos_ads:
                ad_id = str(ad.get("id", ""))
                if not ad_id or ad_id not in ids_existentes:
                    ad["ativo"] = True
                    ads_anteriores_atualizados.append(ad)
            resultado[nome_empresa] = {
                **novo_entry,
                "data": ads_anteriores_atualizados,
                "ts": novo_entry.get("ts", entry_existente.get("ts", "")),
                "ts_historico": entry_existente.get("ts", ""),
            }
        return resultado

    def cache_esta_fresco(ts_str: str) -> bool:
        if not ts_str:
            return False
        try:
            ts = _dt.datetime.strptime(ts_str, "%d/%m/%Y %H:%M")
            return (_dt.datetime.now() - ts).total_seconds() < CACHE_TTL_HORAS * 3600
        except Exception:
            return False

    def _url_para_base64(url: str) -> str:
        if not url or not url.startswith("http"):
            return ""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.facebook.com/",
            }
            r = requests.get(url, headers=headers, timeout=10, stream=True)
            if r.status_code != 200:
                return ""
            ct = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            if not ct.startswith("image/"):
                ct = "image/jpeg"
            data = _b64.b64encode(r.content).decode("utf-8")
            return f"data:{ct};base64,{data}"
        except Exception:
            return ""

    def _truncar(txt, n=160):
        if not txt:
            return ""
        txt = str(txt).strip()
        return txt[:n] + "…" if len(txt) > n else txt

    def _is_dynamic(txt):
        if not txt:
            return False
        return bool(re.search(r'\{\{[^}]+\}\}', txt))

    def _clean_dynamic(txt):
        if not txt:
            return ""
        cleaned = re.sub(r'\{\{[^}]+\}\}', '', txt).strip()
        lines = [l.strip() for l in cleaned.split('\n') if l.strip()]
        return ' '.join(lines)

    def _dias_ativo(start_raw: str) -> str:
        if not start_raw:
            return ""
        try:
            ts_int = int(str(start_raw).strip())
            if ts_int > 10**9:
                dto = _dt.datetime.utcfromtimestamp(ts_int)
            else:
                raise ValueError
        except (ValueError, OSError):
            try:
                dto = _dt.datetime.strptime(str(start_raw)[:10], "%Y-%m-%d")
            except Exception:
                return str(start_raw)[:10]
        data_fmt = f"{dto.day:02d}/{dto.month:02d}/{dto.year}"
        dias = (_dt.datetime.now() - dto).days
        if dias == 0:
            dias_str = "hoje"
        elif dias == 1:
            dias_str = "1 dia ativo"
        else:
            dias_str = f"{dias} dias ativo"
        return f"{data_fmt} ({dias_str})"

    def _extract_images(ad: dict) -> list:
        imgs = []
        seen = set()
        def add(url):
            url = (url or "").strip()
            if url and url not in seen and url.startswith("http"):
                seen.add(url); imgs.append(url)
        
        snapshot = ad.get("snapshot") or {}
        cards    = snapshot.get("cards") or []
        
        # 1. Imagens diretas no ad
        for k in ("image_url", "original_image_url", "resized_image_url",
                  "thumbnail_url", "preview_image_url", "full_picture"):
            add(ad.get(k))
        
        # 2. Imagens diretas no snapshot
        for k in ("image_url", "original_image_url", "resized_image_url",
                  "thumbnail_url", "background_image"):
            add(snapshot.get(k))
        
        # 3. snapshot.images[] — lista de objetos com resized/original
        for obj in (snapshot.get("images") or []):
            if isinstance(obj, dict):
                add(obj.get("resized_image_url"))
                add(obj.get("original_image_url"))
                add(obj.get("watermarked_resized_image_url"))
                add(obj.get("image_url"))
                add(obj.get("url"))
                add(obj.get("src"))
            elif isinstance(obj, str):
                add(obj)
        
        # 4. snapshot.videos[] — preview image dos vídeos (thumb)
        for obj in (snapshot.get("videos") or []):
            if isinstance(obj, dict):
                add(obj.get("video_preview_image_url"))
        
        # 5. Cards do snapshot (carrossel)
        for card in cards:
            if not isinstance(card, dict): continue
            add(card.get("original_image_url"))
            add(card.get("resized_image_url"))
            add(card.get("image_url"))
            add(card.get("thumbnail_url"))
            add(card.get("picture"))
            add(card.get("video_preview_image_url"))
        
        # 6. creative_images[]
        for obj in (ad.get("creative_images") or []):
            if isinstance(obj, dict):
                for k in ("original_image_url", "image_url", "url"):
                    add(obj.get(k))
            elif isinstance(obj, str):
                add(obj)
        
        # 7. images[] no nível raiz
        for obj in (ad.get("images") or []):
            if isinstance(obj, dict):
                for k in ("original_image_url", "resized_image_url", "image_url", "url", "src"):
                    add(obj.get(k))
            elif isinstance(obj, str):
                add(obj)
        
        return imgs

    def _extract_copy(ad: dict) -> dict:
        snapshot = ad.get("snapshot") or {}
        cards    = snapshot.get("cards") or []

        def first_str(val):
            if isinstance(val, list):
                for v in val:
                    if v and isinstance(v, str) and v.strip():
                        return v.strip()
            if isinstance(val, str) and val.strip():
                return val.strip()
            # ← NOVO: se for dict com chave "text"
            if isinstance(val, dict) and val.get("text"):
                return val["text"].strip()
            return ""

        # ← NOVO: extrai corretamente snapshot.body.text
        snapshot_body_raw = snapshot.get("body") or {}
        snapshot_body_text = (
            snapshot_body_raw.get("text")
            if isinstance(snapshot_body_raw, dict)
            else snapshot_body_raw
        ) or ""

        body  = (first_str(ad.get("ad_creative_bodies"))
                 or snapshot_body_text                       
                 or first_str(ad.get("body"))
                 or first_str(ad.get("message"))
                 or first_str(snapshot.get("message")))

        title = (first_str(ad.get("ad_creative_link_titles"))
                 or first_str(snapshot.get("title"))
                 or first_str(ad.get("title"))
                 or first_str(snapshot.get("link_title")))

        desc  = (first_str(ad.get("ad_creative_link_descriptions"))
                 or first_str(snapshot.get("link_description"))
                 or first_str(ad.get("description"))
                 or first_str(snapshot.get("description")))

        cta   = (first_str(ad.get("cta_type"))
                 or first_str(snapshot.get("cta_type"))
                 or first_str(ad.get("call_to_action_type")))

        caption = (first_str(snapshot.get("caption"))
                   or first_str(ad.get("caption")))

        # Se body é template dinâmico, busca nos cards primeiro
        if (not body or _is_dynamic(body)) and cards:
            for card in cards:
                if isinstance(card, dict):
                    v = first_str(card.get("body") or card.get("message") or "")
                    if v and not _is_dynamic(v):
                        body = v
                        break
            # title do card também
            if not title or _is_dynamic(title):
                for card in cards:
                    if isinstance(card, dict):
                        v = first_str(card.get("title") or "")
                        if v and not _is_dynamic(v):
                            title = v
                            break

        # Limpa title se estiver contido no body ou for prefixo dele
        if title and body and (title in body or body.startswith(title)):
            title = ""

        # Limpa desc se for igual ao body, contido nele, ou se body está contido no desc
        if desc and body and (
            desc.strip() == body.strip()
            or desc.strip() in body.strip()
            or body.strip() in desc.strip()
            or desc.strip()[:80] in body.strip()
            or body.strip()[:80] in desc.strip()
        ):
            desc = ""

        # Limpa desc se for igual ao title
        if desc and title and desc.strip() == title.strip():
            desc = ""

        # Remove title quando body já existe
        if title and body:
            title = ""

        return {"body": body, "title": title, "desc": desc, "cta": cta, "caption": caption}

    def _extract_videos(ad: dict) -> list:
        vids = []
        seen = set()
        snapshot = ad.get("snapshot") or {}
        cards    = snapshot.get("cards") or []

        def add(url):
            url = (url or "").strip()
            if url and url not in seen and url.startswith("http"):
                seen.add(url); vids.append(url)

        # 1. Vídeos diretos no ad e snapshot
        for k in ("video_hd_url", "video_sd_url", "video_url"):
            add(ad.get(k))
            add(snapshot.get(k))

        # 2. snapshot.videos[] — lista de objetos ← ERA ISSO QUE FALTAVA
        for obj in (snapshot.get("videos") or []):
            if isinstance(obj, dict):
                add(obj.get("video_sd_url"))   # sd primeiro (menor, mais rápido)
                add(obj.get("video_hd_url"))
                add(obj.get("video_url"))

        # 3. Cards
        for card in cards:
            if isinstance(card, dict):
                for k in ("video_hd_url", "video_sd_url", "video_url"):
                    add(card.get(k))

        # 4. videos[] no nível raiz
        for v in (ad.get("videos") or []):
            if isinstance(v, str):
                add(v)
            elif isinstance(v, dict):
                add(v.get("video_sd_url"))
                add(v.get("video_hd_url"))

        sd = [u for u in vids if any(x in u.lower() for x in ("sd", "360", "480", "_sd", "m412"))]
        hd = [u for u in vids if u not in sd]
        return sd + hd

    def _normalizar_item_apify(item: dict) -> dict:
        snapshot = item.get("snapshot") or {}
        cards    = snapshot.get("cards") or []

        ad_id   = str(item.get("adArchiveID") or item.get("ad_archive_id") or item.get("id") or "")
        page_id = str(item.get("pageID") or item.get("page_id") or "")
        page_name = (item.get("pageName") or item.get("page_name") or snapshot.get("page_name") or "")
        page_profile_picture = (
            item.get("pageProfilePicture")
            or item.get("page_profile_picture")
            or snapshot.get("page_profile_picture_url")
            or ""
        )

        images = _extract_images(item)
        videos = _extract_videos(item)
        copy = _extract_copy(item)

        # Pega de todos os campos possíveis
        plats_raw = (
            item.get("publisher_platform")
            or item.get("publisherPlatform")
            or item.get("publisher_platforms")
            or snapshot.get("publisher_platform")
            or snapshot.get("publisher_platforms")
            or []
        )

        if isinstance(plats_raw, str):
            plats_raw = [plats_raw]

        plats = []
        for p in plats_raw:
            if isinstance(p, dict):
                val = p.get("name") or p.get("value") or str(p)
                plats.append(val.lower())
            elif isinstance(p, str):
                plats.append(p.lower())  # "FACEBOOK" → "facebook"

        if not plats:
            plats = ["facebook", "instagram"]

        raw_media_type = (
            item.get("mediaType")
            or item.get("media_type")
            or snapshot.get("display_format")
            or ""
        ).upper()

        has_video   = bool(videos) or raw_media_type in ("VIDEO", "REELS")
        has_cards   = len(cards) > 1 and not has_video
        has_image   = bool(images) and not has_video

        if has_video:   fmt = "Vídeo"
        elif has_cards: fmt = "Carrossel"
        elif has_image: fmt = "Imagem"
        else:           fmt = "Texto"

        is_dyn  = (_is_dynamic(copy["body"]) or _is_dynamic(copy["title"]) or _is_dynamic(copy["desc"]))
        body_c  = _clean_dynamic(copy["body"])  if _is_dynamic(copy["body"])  else copy["body"]
        title_c = _clean_dynamic(copy["title"]) if _is_dynamic(copy["title"]) else copy["title"]
        desc_c  = _clean_dynamic(copy["desc"])  if _is_dynamic(copy["desc"])  else copy["desc"]

        imp = item.get("impressionsWithIndex") or item.get("impressions") or {}
        if isinstance(imp, dict):
            lo = imp.get("lowerBound") or imp.get("lower_bound") or ""
            hi = imp.get("upperBound") or imp.get("upper_bound") or ""
            imp_str = f"{lo}–{hi}" if (lo or hi) else ""
        else:
            imp_str = str(imp) if imp else ""

        baixo_volume = bool(
            item.get("isLowVolumeImpressions")
            or item.get("low_volume")
            or item.get("low_volume_impressions")
            or (isinstance(imp, dict) and imp.get("lowerBound") == "<100")
            or imp_str == "<100"
        )

        start_raw = (
            item.get("startDate")
            or item.get("ad_delivery_start_time")
            or item.get("start_date")
            or ""
        )
        start_fmt = _dias_ativo(str(start_raw)) if start_raw else ""

        snap_url = (item.get("adSnapshotURL")
                    or item.get("ad_snapshot_url")
                    or (f"https://www.facebook.com/ads/library/?id={ad_id}" if ad_id else ""))

        images_b64 = []
        if images:
            b64 = _url_para_base64(images[0])
            images_b64.append(b64 if b64 else images[0])
            images_b64.extend(images[1:3])

        return {
            "id":                  ad_id,
            "page_name":           page_name,
            "page_id":             page_id,
            "page_profile_picture": page_profile_picture,
            "body":                body_c,
            "body_raw":            copy["body"],
            "title":               title_c,
            "description":         desc_c,
            "cta":                 copy["cta"],
            "caption":             copy["caption"],
            "images":              images,
            "images_b64":          images_b64,
            "videos":              videos,
            "snapshot_url":        snap_url,
            "data_inicio":         start_fmt,
            "data_raw":            str(start_raw),
            "impressoes":          imp_str,
            "baixo_volume":        baixo_volume,
            "plataformas":         plats,
            "formato":             fmt,
            "is_dynamic":          is_dyn,
        }

    def _apify_run_sync(search_term: str, limit: int = 100) -> tuple:
        api_token = st.secrets.get("APIFY_TOKEN", "")
        if not api_token:
            return [], [], "APIFY_TOKEN não configurada nos secrets."

        run_url = (
            f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs"
            f"?token={api_token}"
        )

        import urllib.parse
        search_term_stripped = search_term.strip()

        if search_term_stripped.isdigit():
            ad_library_url = (
                f"https://www.facebook.com/ads/library/"
                f"?active_status=active&ad_type=all&country=BR"
                f"&is_targeted_country=false&media_type=all"
                f"&search_type=page&sort_data[direction]=desc"
                f"&sort_data[mode]=total_impressions"
                f"&view_all_page_id={search_term_stripped}"
            )
        else:
            query_encoded = urllib.parse.quote(search_term_stripped)
            ad_library_url = (
                f"https://www.facebook.com/ads/library/"
                f"?active_status=active&ad_type=all&country=BR"
                f"&is_targeted_country=false&media_type=all"
                f"&search_type=page&sort_data[direction]=desc"
                f"&sort_data[mode]=total_impressions"
                f"&q={query_encoded}"
            )

        payload = {
            "urls": [{"url": ad_library_url}],
            "count": limit,
            "scrapeAdDetails": False,
            "scrapePageAds.activeStatus": "active",
            "scrapePageAds.countryCode": "BR",
            "scrapePageAds.sortBy": "impressions_desc",
        }

        try:
            r_start = requests.post(run_url, json=payload, timeout=30)
            r_start.raise_for_status()
            run_data = r_start.json()
        except Exception as e:
            return [], [], f"Erro ao iniciar run Apify: {e}"

        run_id     = run_data.get("data", {}).get("id") or run_data.get("id")
        dataset_id = run_data.get("data", {}).get("defaultDatasetId") or run_data.get("defaultDatasetId")

        if not run_id:
            return [], [], f"Apify não retornou run ID. Resposta: {run_data}"

        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={api_token}"
        deadline   = _time.time() + 180
        status     = "RUNNING"
        while _time.time() < deadline:
            try:
                r_st   = requests.get(status_url, timeout=15)
                jdata  = r_st.json().get("data", {})
                status = jdata.get("status", "RUNNING")
                if not dataset_id:
                    dataset_id = jdata.get("defaultDatasetId") or dataset_id
            except Exception:
                pass
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
            _time.sleep(5)

        if status != "SUCCEEDED":
            return [], [], f"Run Apify terminou com status: {status}"

        if not dataset_id:
            return [], [], "Apify não retornou dataset ID."

        items_url = (
            f"https://api.apify.com/v2/datasets/{dataset_id}/items"
            f"?token={api_token}&limit={limit}&clean=true"
        )
        try:
            r_items = requests.get(items_url, timeout=30)
            r_items.raise_for_status()
            raw_items = r_items.json()
        except Exception as e:
            return [], [], f"Erro ao ler dataset Apify: {e}"

        if not isinstance(raw_items, list):
            raw_items = raw_items.get("items", []) if isinstance(raw_items, dict) else []

        if not raw_items:
            return [], [], None

        ads_normalizados = [_normalizar_item_apify(item) for item in raw_items]
        return ads_normalizados, raw_items[:100], None

    def buscar_ads_apify(query: str, limit: int = 100) -> tuple:
        return _apify_run_sync(query.strip(), limit=limit)

    def _render_loader(placeholder, progresso: list, total: int, atual: int, finalizado: bool = False):
        progresso_pct = int((atual / total) * 100) if total else 100

        if finalizado:
            texto_status = "Busca concluída"
            subtexto     = f"{atual}/{total} empresas processadas"
        else:
            texto_status = "Buscando anúncios..."
            subtexto     = f"Processando {atual} de {total} empresas"

        itens_html = ""
        for item in progresso:
            status = item.get("status", "")
            nome   = item.get("nome", "")
            msg    = item.get("msg", "")
            count  = item.get("count")

            if status == "loading":
                icone = "⏳"; cor_txt = "#f59e0b"; bg = "#1a3a2a"; brd = "#f59e0b22"
            elif status == "done":
                icone = "✅"; cor_txt = "#22c55e"; bg = "#0f2a1a"; brd = "#22c55e33"
            elif status == "error":
                icone = "❌"; cor_txt = "#f87171"; bg = "#2a0f0f"; brd = "#f8717133"
            elif status == "cache":
                icone = "🗂️"; cor_txt = "#3a9fd6"; bg = "#0e2240"; brd = "#3a9fd633"
            else:
                icone = "•"; cor_txt = "#9ca3af"; bg = "#1a2535"; brd = "#ffffff11"

            count_str = f'<span style="font-size:13px;font-weight:800;color:{cor_txt}">{count} anúncios</span>' if count is not None else "<span></span>"
            nome_safe = str(nome or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            msg_safe  = str(msg or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"','&quot;')

            itens_html += f"""
            <div style="display:flex;align-items:center;gap:12px;
                        padding:11px 14px;border-radius:10px;
                        background:{bg};border:1px solid {brd};
                        margin-bottom:8px">
                <span style="font-size:17px;flex-shrink:0">{icone}</span>
                <div style="flex:1;min-width:0">
                    <div style="font-size:13px;font-weight:700;color:#f1f5f9">{nome_safe}</div>
                    <div style="font-size:11px;color:#64748b;margin-top:2px">{msg_safe}</div>
                </div>
                {count_str}
            </div>"""

        barra_cor = "#22c55e" if finalizado else "#3a9fd6"
        spinner   = '' if finalizado else '<div style="width:22px;height:22px;border:2.5px solid #1e3a5f;border-top-color:#3a9fd6;border-radius:50%;animation:spin 0.8s linear infinite;flex-shrink:0"></div>'
        check     = '<div style="width:28px;height:28px;border-radius:50%;background:#22c55e22;border:1.5px solid #22c55e;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0">✅</div>' if finalizado else ''
        fechar_js = "setTimeout(function(){var m=document.getElementById('ads_loader_modal');if(m){m.style.opacity='0';m.style.transition='opacity 0.4s';setTimeout(function(){var m=document.getElementById('ads_loader_modal');if(m)m.remove();},400);}},1500);" if finalizado else ""

        placeholder.markdown(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
@keyframes fadeIn {{from{{opacity:0;transform:scale(0.96)}}to{{opacity:1;transform:scale(1)}}}}
@keyframes spin   {{to{{transform:rotate(360deg)}}}}
#ads_loader_modal{{
    position:fixed;inset:0;
    background:rgba(5,15,30,0.75);
    backdrop-filter:blur(4px);
    -webkit-backdrop-filter:blur(4px);
    z-index:99999;
    display:flex;align-items:center;justify-content:center;
    animation:fadeIn 0.2s ease;
    transition:opacity 0.4s;
    font-family:'DM Sans',sans-serif;
}}
#ads_loader_box{{
    background:#0e1e35;
    border:1px solid #1e3a5f;
    border-radius:18px;
    padding:28px;
    width:min(92vw,460px);
    box-shadow:0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px rgba(58,159,214,0.1);
}}
</style>
<div id="ads_loader_modal">
<div id="ads_loader_box">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
        {spinner}{check}
        <div>
            <div style="font-size:16px;font-weight:800;color:#f1f5f9;letter-spacing:-0.2px">{texto_status}</div>
            <div style="font-size:12px;color:#64748b;margin-top:2px">{subtexto}</div>
        </div>
        <div style="margin-left:auto;font-size:13px;font-weight:800;color:{'#22c55e' if finalizado else '#3a9fd6'}">{progresso_pct}%</div>
    </div>
    <div style="background:#07111f;border-radius:8px;height:5px;margin-bottom:20px;overflow:hidden">
        <div style="height:100%;width:{progresso_pct}%;background:linear-gradient(90deg,#1d6fa8,{barra_cor});border-radius:8px;transition:width 0.4s ease;{'box-shadow:0 0 8px #22c55e66' if finalizado else ''}"></div>
    </div>
    <div>{itens_html}</div>
    {'<div style="text-align:center;margin-top:16px;font-size:12px;color:#475569;font-weight:600">Fechando automaticamente...</div>' if finalizado else ''}
</div>
</div>
<script>{fechar_js}</script>
""", unsafe_allow_html=True)

    def executar_busca(empresas: list, query_values: dict, forcar: bool = False):
        erros  = {}
        novos  = {}
        cache_atual = dict(st.session_state.ads_cache or {})

        loader_placeholder = st.empty()
        total = len(empresas)
        progresso = []

        for idx_e, e in enumerate(empresas):
            ck = e["nome"]

            entrada_cache = cache_atual.get(ck, {})
            if not forcar and entrada_cache and cache_esta_fresco(entrada_cache.get("ts", "")):
                total_ads = len(entrada_cache.get("data", []))
                ativos = sum(1 for a in entrada_cache.get("data", []) if a.get("ativo", True))
                inativos = total_ads - ativos
                progresso.append({
                    "nome": ck,
                    "status": "cache",
                    "msg": f"Cache válido ({entrada_cache.get('ts','')})",
                    "count": ativos,
                    "inativos": inativos,
                })
                _render_loader(loader_placeholder, progresso, total, idx_e + 1)
                continue

            if e["tipo"] == "minha":
                ads_id_salvo = st.session_state.dados["minha_empresa"].get("ads_id", "").strip()
            else:
                ads_id_salvo = st.session_state.dados["concorrentes"][e["idx"]].get("ads_id", "").strip()

            query = ads_id_salvo or query_values.get(ck, "").strip()
            if not query:
                continue

            label = f"page_id: {query}" if query.isdigit() else f"keyword: {query}"
            progresso.append({
                "nome": ck,
                "status": "loading",
                "msg": f"Buscando ({label})...",
                "count": None,
                "inativos": 0,
            })
            _render_loader(loader_placeholder, progresso, total, idx_e + 1)

            ads, raw, erro = buscar_ads_apify(query)

            if erro:
                erros[ck] = erro
                progresso[-1] = {
                    "nome": ck,
                    "status": "error",
                    "msg": erro[:80],
                    "count": 0,
                    "inativos": 0,
                }
            else:
                novos[ck] = {
                    "data":  ads,
                    "ts":    _dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "nome":  ck,
                    "query": query,
                    "_raw":  raw,
                }
                progresso[-1] = {
                    "nome": ck,
                    "status": "done",
                    "msg": f"{len(ads)} anúncios encontrados",
                    "count": len(ads),
                    "inativos": 0,
                }
            _render_loader(loader_placeholder, progresso, total, idx_e + 1)

        _render_loader(loader_placeholder, progresso, total, total, finalizado=True)
        import time as _ttt; _ttt.sleep(3)
        loader_placeholder.empty()

        cache_mergeado = merge_ads(cache_atual, novos)
        st.session_state.ads_cache = cache_mergeado
        st.session_state.ads_erro  = erros
        salvar_cache_ads(cache_mergeado)
        st.rerun()

    if "ads_cache" not in st.session_state or not st.session_state.ads_cache:
        st.session_state.ads_cache = carregar_cache_ads()
    if "ads_erro" not in st.session_state:
        st.session_state.ads_erro = {}
    if "ads_onboarding_empresa" not in st.session_state:
        st.session_state.ads_onboarding_empresa = None
    if "ads_onboarding_paginas" not in st.session_state:
        st.session_state.ads_onboarding_paginas = []
    if "ads_onboarding_termo" not in st.session_state:
        st.session_state.ads_onboarding_termo = ""
    if "ads_editando_empresa" not in st.session_state:
        st.session_state.ads_editando_empresa = None
    if "ads_aba_conteudo" not in st.session_state:
        st.session_state.ads_aba_conteudo = {}
    if "ads_main_tab" not in st.session_state:
        st.session_state.ads_main_tab = "empresas"
    if "ads_config_empresa_selecionada" not in st.session_state:
        st.session_state.ads_config_empresa_selecionada = None

    def safe_key(s):
        return re.sub(r"[^a-zA-Z0-9_]", "_", s)

    todas_empresas = []
    if emp.get("nome"):
        todas_empresas.append({"nome": emp["nome"], "tipo": "minha", "idx": 0})
    for i, c in enumerate(concs):
        if c.get("nome"):
            todas_empresas.append({"nome": c["nome"], "tipo": "concorrente", "idx": i})

    def empresa_tem_ads_id(e: dict) -> bool:
        if e["tipo"] == "minha":
            return bool(emp.get("ads_id", "").strip())
        else:
            cd = concs[e["idx"]]
            return bool(cd.get("ads_id", "").strip())

    def salvar_ads_id(e: dict, ads_id: str, page_pic: str = ""):
        if e["tipo"] == "minha":
            st.session_state.dados["minha_empresa"]["ads_id"] = ads_id
            if page_pic:
                st.session_state.dados["minha_empresa"]["ads_page_pic"] = page_pic
        else:
            st.session_state.dados["concorrentes"][e["idx"]]["ads_id"] = ads_id
            if page_pic:
                st.session_state.dados["concorrentes"][e["idx"]]["ads_page_pic"] = page_pic
        salvar_dados_usuario(st.session_state.user.id)

    def buscar_paginas_facebook(termo: str) -> list:
        ads, _, erro = _apify_run_sync(termo, limit=20)
        if erro or not ads:
            return []
        paginas = {}
        for ad in ads:
            pid  = ad.get("page_id", "") or ""
            nome = ad.get("page_name", "") or ""
            pic  = ad.get("page_profile_picture", "") or ""
            if nome and nome not in paginas:
                paginas[nome] = {"nome": nome, "page_id": pid, "total_ads": 0, "profile_picture": pic}
            if nome in paginas:
                paginas[nome]["total_ads"] += 1
                if not paginas[nome]["profile_picture"] and pic:
                    paginas[nome]["profile_picture"] = pic
        return sorted(paginas.values(), key=lambda x: x["total_ads"], reverse=True)

    # ══════════════════════════════════════════════════════════════════
    # CABEÇALHO DA PÁGINA
    # ══════════════════════════════════════════════════════════════════

    h1_col, h2_col, h3_col = st.columns([6, 2, 3])

    with h1_col:
        components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; }
.titulo {
    font-family: 'Animo', 'DM Sans', sans-serif;
    font-size: 32px; font-weight: 700; color: #1a2e4a;
    text-transform: uppercase; margin: 0 0 6px 0; letter-spacing: 0.5px;
}
.sub { font-family: 'DM Sans', sans-serif; font-size: 14px; color: #6b7280; }
</style>
<div class="titulo">Biblioteca de Ads</div>
<div class="sub">Criativos, copies e formatos dos anúncios dos seus concorrentes.</div>
""", height=65)

    with h2_col:
        st.markdown("""
        <style>
        .st-key-_ads_ghost_tab_configuracao_,
        .st-key-_ads_ghost_tab_empresas_,
        .st-key-_ads_ghost_tab_analise_ {
            display: none !important;
        }
        .stElementContainer:has(.st-key-_ads_ghost_tab_configuracao_),
        .stElementContainer:has(.st-key-_ads_ghost_tab_empresas_),
        .stElementContainer:has(.st-key-_ads_ghost_tab_analise_) {
            display: none !important;
        }
        </style>
        """, unsafe_allow_html=True)

    with h3_col:
        st.markdown("""
        <style>
        .st-key-ads_buscar_header_btn {
            margin-bottom: -16px !important;
        }
        .stElementContainer:has(.st-key-ads_buscar_header_btn) {
            margin-bottom: -12px !important;
        }
        </style>
        """, unsafe_allow_html=True)
        gerar_btn_ads_header = st.button(
            "Buscar / Atualizar Anúncios",
            type="primary",
            use_container_width=True,
            key="ads_buscar_header_btn",
        )
        if st.session_state.ads_cache:
            _tss = [v.get("ts", "") for v in st.session_state.ads_cache.values() if v.get("ts")]
            if _tss:
                _ultima_ts = min(_tss)
                _d = {k: v for k, v in st.session_state.ads_cache.items()}
                import json as _json_ads
                _djs = _json_ads.dumps(list(_d.values()), ensure_ascii=False).replace("</", "<\\/").replace("\\", "\\\\").replace("'", "\\'")
                _fn = f'dados_ads_{_ultima_ts.replace("/","_").replace(" ","_").replace(":","")}.json'

                if st.button("ads_limpar_cache", key="ads_limpar_cache_btn"):
                    st.session_state.ads_cache = {}
                    st.session_state.ads_erro = {}
                    try:
                        supabase.table("ci_dados").update({"ads_cache": {}}).eq("user_id", st.session_state.user.id).execute()
                    except Exception:
                        pass
                    st.toast("Cache limpo!", icon="🗑️")
                    st.rerun()

                st.markdown("""
                <style>
                .st-key-ads_limpar_cache_btn {
                    position: fixed !important; top: -9999px !important; left: -9999px !important;
                    width: 0 !important; height: 0 !important; overflow: hidden !important;
                    opacity: 0 !important; pointer-events: none !important; display: none !important;
                }
                .stElementContainer:has(.st-key-ads_limpar_cache_btn) {
                    display: none !important; height: 0 !important; min-height: 0 !important;
                    max-height: 0 !important; padding: 0 !important; margin: 0 !important; overflow: hidden !important;
                }
                </style>
                """, unsafe_allow_html=True)

                components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.row-coleta {{
    display:flex;
    align-items:center; justify-content:center; gap:6px;
    font-size:13px; color:#6b7280; font-family:'DM Sans',sans-serif;
    flex-wrap:nowrap; white-space:nowrap;
}}
.link-btn {{
    font-size:11px; color:#6b7280;
    cursor:pointer; text-underline-offset:3px;
    background:none; border:none; padding:0;
    font-family:'DM Sans',sans-serif;
}}
.link-btn:hover {{ text-decoration:underline; color:#374151; }}
.sep {{ color:#d1d5db; font-size:12px; }}
.clear-btn {{
    font-size:11px; color:#6b7280;
    cursor:pointer; background:none; border:none; padding:0;
    font-family:'DM Sans',sans-serif; text-underline-offset:3px;
}}
.clear-btn:hover {{ text-decoration:underline; color:#374151; }}
</style>
<div class="row-coleta">
    <button class="link-btn" onclick="abrirModal()">🕒 Última busca: <b>{_ultima_ts}</b></button>
    <span class="sep">|</span>
    <button class="clear-btn" onclick="triggerLimpar()">Limpar cache</button>
</div>
<script>
var DADOS_JSON = '{_djs}';
var FILENAME   = '{_fn}';
var ULTIMA     = '{_ultima_ts}';

function triggerLimpar() {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === 'ads_limpar_cache') {{ b.click(); return; }}
    }}
}}

function abrirModal() {{
    window.fechar = function() {{
        var o = window.parent.document.getElementById('raw_modal_overlay');
        if (o) o.remove();
        if (window.parent.__rawEsc) {{
            window.parent.document.removeEventListener('keydown', window.parent.__rawEsc);
            window.parent.__rawEsc = null;
        }}
    }};
    var doc = window.parent.document;
    var old = doc.getElementById('raw_modal_overlay');
    if (old) old.remove();
    var D;
    try {{ D = JSON.parse(DADOS_JSON); }} catch(e) {{ D = []; }}
    var Dstr = JSON.stringify(D, null, 2);
    var ov = doc.createElement('div');
    ov.id = 'raw_modal_overlay';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:999999;display:flex;align-items:center;justify-content:center;padding:24px;';
    ov.onclick = function(e) {{ if(e.target===ov) fechar(); }};
    var box = doc.createElement('div');
    box.style.cssText = 'background:#0d1117;border-radius:16px;overflow:hidden;position:relative;width:min(95vw,1100px);max-height:88vh;display:flex;flex-direction:column;border:1px solid #1e395e;';
    var hdr = doc.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:16px 24px;border-bottom:1px solid #1e395e;background:#0e1e35;flex-shrink:0;';
    hdr.innerHTML =
        '<div><div style="font-size:15px;font-weight:700;color:#e6edf3;font-family:DM Sans,sans-serif;">📦 Cache de Anúncios</div>'
        + '<div style="font-size:12px;color:#8b949e;margin-top:2px;">Última busca: ' + ULTIMA + '</div></div>'
        + '<div style="display:flex;gap:10px;">'
        + '<button id="raw_copy_btn" style="padding:7px 16px;border:1px solid #1e395e;border-radius:8px;background:#0e1e35;color:#22c45e;font-size:13px;font-weight:600;cursor:pointer;">📋 Copiar</button>'
        + '<button id="raw_down_btn" style="padding:7px 16px;border:1px solid #1e395e;border-radius:8px;background:#0e1e35;color:#22c45e;font-size:13px;font-weight:600;cursor:pointer;">⬇️ Baixar JSON</button>'
        + '<button id="raw_close_btn" style="width:34px;height:34px;border-radius:50%;background:#0e1e35;border:1px solid #1e395e;color:#22c45e;font-size:18px;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center;">✕</button>'
        + '</div>';
    var pre = doc.createElement('pre');
    pre.style.cssText = 'flex:1;overflow-y:auto;overflow-x:auto;padding:20px 24px;font-size:12.5px;line-height:1.7;color:#e6edf3;font-family:monospace;background:#0d1117;margin:0;white-space:pre;max-height:calc(88vh - 80px);';
    pre.textContent = Dstr;
    box.appendChild(hdr);
    box.appendChild(pre);
    ov.appendChild(box);
    doc.body.appendChild(ov);

    doc.getElementById('raw_close_btn').addEventListener('click', window.fechar);
    doc.getElementById('raw_copy_btn').addEventListener('click', function() {{
        var b = doc.getElementById('raw_copy_btn');
        try {{
            var ta = doc.createElement('textarea');
            ta.value = Dstr;
            ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;';
            doc.body.appendChild(ta);
            ta.focus();
            ta.select();
            doc.execCommand('copy');
            doc.body.removeChild(ta);
            b.textContent = '✅ Copiado!';
            setTimeout(function() {{ b.textContent = '📋 Copiar'; }}, 2000);
        }} catch(e) {{
            b.textContent = '❌ Erro';
            setTimeout(function() {{ b.textContent = '📋 Copiar'; }}, 2000);
        }}
    }});
    doc.getElementById('raw_down_btn').addEventListener('click', function() {{
        var a = doc.createElement('a');
        a.href = URL.createObjectURL(new Blob([Dstr], {{type:'application/json'}}));
        a.download = FILENAME;
        a.click();
    }});

    window.parent.__rawEsc = function(e) {{ if(e.key==='Escape') window.fechar(); }};
    doc.addEventListener('keydown', window.parent.__rawEsc);
}}
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '28px';
            iframes[i].style.marginTop = '-8px';
            break;
        }} }} catch(e) {{}}
    }}
}})();
</script>
""", height=28, scrolling=False)

    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:4px 0 8px 0'/>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════
    # GHOST BUTTONS — navegação principal (COMPLETAMENTE OCULTOS)
    # ══════════════════════════════════════════════════════════════════

    st.markdown("""
    <style>
    .st-key-_ads_ghost_tab_configuracao_,
    .st-key-_ads_ghost_tab_empresas_,
    .st-key-_ads_ghost_tab_analise_ {
        position: fixed !important;
        top: -9999px !important;
        left: -9999px !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
        visibility: hidden !important;
        display: none !important;
    }
    .stElementContainer:has(.st-key-_ads_ghost_tab_configuracao_),
    .stElementContainer:has(.st-key-_ads_ghost_tab_empresas_),
    .stElementContainer:has(.st-key-_ads_ghost_tab_analise_) {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
        max-height: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if st.button("tab_cfg", key="_ads_ghost_tab_configuracao_"):
        st.session_state.ads_main_tab = "configuracao"
        st.session_state.ads_config_empresa_selecionada = None
        st.rerun()
    if st.button("tab_emp", key="_ads_ghost_tab_empresas_"):
        st.session_state.ads_main_tab = "empresas"
        st.rerun()
    if st.button("tab_ia", key="_ads_ghost_tab_analise_"):
        st.session_state.ads_main_tab = "analise"
        st.rerun()

    # Ghost para lápis de empresa
    lapiz_ghost_css_parts = []
    for ci, e in enumerate(todas_empresas):
        sk = safe_key(e["nome"])
        lapiz_key = f"_ads_lapiz_{sk}_{ci}_"
        lapiz_ghost_css_parts.append(f"""
        .st-key-{lapiz_key.strip('_')} {{
            position: fixed !important; top: -9999px !important; left: -9999px !important;
            width: 0 !important; height: 0 !important; overflow: hidden !important;
            opacity: 0 !important; pointer-events: none !important; visibility: hidden !important; display: none !important;
        }}
        .stElementContainer:has(.st-key-{lapiz_key.strip('_')}) {{
            display: none !important; height: 0 !important; min-height: 0 !important;
            max-height: 0 !important; padding: 0 !important; margin: 0 !important; overflow: hidden !important;
        }}
        """)
    if lapiz_ghost_css_parts:
        st.markdown(f"<style>{''.join(lapiz_ghost_css_parts)}</style>", unsafe_allow_html=True)

    lapiz_triggers = {}
    for ci, e in enumerate(todas_empresas):
        sk = safe_key(e["nome"])
        lapiz_key = f"_ads_lapiz_{sk}_{ci}_"
        if st.button(f"lapiz_{sk}", key=lapiz_key.strip('_')):
            st.session_state.ads_main_tab = "configuracao"
            st.session_state.ads_config_empresa_selecionada = e["nome"]
            st.session_state.ads_editando_empresa = e["nome"]
            st.rerun()
        lapiz_triggers[ci] = lapiz_key

    # ── Calcular dados
    main_tab = st.session_state.ads_main_tab
    empresas_configuradas = [e for e in todas_empresas if empresa_tem_ads_id(e)]
    empresas_sem_config   = [e for e in todas_empresas if not empresa_tem_ads_id(e)]

    n_configuradas = len(empresas_configuradas)
    n_sem_config   = len(empresas_sem_config)

    # ── Processar busca do cabeçalho
    if gerar_btn_ads_header:
        query_values_header = {}
        for e in todas_empresas:
            if empresa_tem_ads_id(e):
                ck = e["nome"]
                ads_id_salvo = emp.get("ads_id","") if e["tipo"]=="minha" else concs[e["idx"]].get("ads_id","")
                query_values_header[ck] = ads_id_salvo
        if query_values_header:
            executar_busca([e for e in todas_empresas if empresa_tem_ads_id(e)], query_values_header, forcar=False)
        else:
            st.warning("Configure pelo menos uma empresa antes de buscar.")

    # ══════════════════════════════════════════════════════════════════
    # BARRA DE NAVEGAÇÃO PRINCIPAL (3 abas) — SEM BADGES NUMÉRICOS
    # ══════════════════════════════════════════════════════════════════

    components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; -webkit-font-smoothing:antialiased; }}
.nav-bar {{
    display:grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap:12px;
    width:100%;
    margin-bottom:0px;
}}
.nav-item {{
    background:#fff;
    border:1px solid #e5e7eb;
    border-radius:14px;
    padding:16px 20px;
    cursor:pointer;
    display:flex;
    align-items:center;
    gap:14px;
    transition:all 0.15s;
    position:relative;
    overflow:hidden;
}}
.nav-item:hover {{
    border-color:#3a9fd6;
    box-shadow:0 2px 12px rgba(58,159,214,0.12);
}}
.nav-item.active {{
    background:#0e2a47;
    border-color:#0e2a47;
    box-shadow:0 4px 20px rgba(14,42,71,0.22);
}}
.nav-item.active::after {{
    content:'';
    position:absolute;
    bottom:0;left:0;right:0;
    height:3px;
    background:linear-gradient(90deg,#3a9fd6,#2ecc71);
    border-radius:0 0 14px 14px;
}}
.nav-icon {{
    width:40px;height:40px;border-radius:10px;
    display:flex;align-items:center;justify-content:center;
    flex-shrink:0;
    background:#f3f4f6;
    transition:background 0.15s;
}}
.nav-item.active .nav-icon {{
    background:rgba(255,255,255,0.12);
}}
.nav-icon svg {{ width:20px;height:20px; }}
.nav-content {{ flex:1;min-width:0; }}
.nav-title {{
    font-size:15px;font-weight:700;color:#1a2e4a;
    display:block;margin-bottom:2px;
}}
.nav-item.active .nav-title {{ color:#ffffff; }}
.nav-sub {{
    font-size:12px;color:#9ca3af;
}}
.nav-item.active .nav-sub {{ color:rgba(255,255,255,0.55); }}
.nav-right {{ display:flex; flex-direction:column; align-items:flex-end; gap:5px; flex-shrink:0; }}
.count-badge {{
    min-width:26px; height:26px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-size:12px; font-weight:800; padding:0 5px;
    background:#e5e7eb; color:#6b7280;
}}
.count-badge.has {{ background:#3a9fd6; color:#fff; }}
.nav-item.active .count-badge {{ background:rgba(255,255,255,0.18); color:#fff; }}
.nav-item.active .count-badge.has {{ background:rgba(58,159,214,0.5); color:#fff; }}
</style>
<div class="nav-bar">
    <div class="nav-item {'active' if main_tab == 'configuracao' else ''}" onclick="triggerTab('tab_cfg')">
        <div class="nav-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="{'#ffffff' if main_tab == 'configuracao' else '#6b7280'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
        </div>
        <div class="nav-content">
            <span class="nav-title">Configuração</span>
            <span class="nav-sub">Configure suas empresas</span>
        </div>
    </div>
    <div class="nav-item {'active' if main_tab == 'empresas' else ''}" onclick="triggerTab('tab_emp')">
        <div class="nav-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="{'#ffffff' if main_tab == 'empresas' else '#6b7280'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
            </svg>
        </div>
        <div class="nav-content">
            <span class="nav-title">Empresas configuradas</span>
            <span class="nav-sub">Gerencie empresas cadastradas</span>
        </div>
        <div class="nav-right">
            <div class="count-badge {'has' if n_configuradas > 0 else ''}">{n_configuradas}</div>
        </div>
    </div>
    <div class="nav-item {'active' if main_tab == 'analise' else ''}" onclick="triggerTab('tab_ia')">
        <div class="nav-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="{'#ffffff' if main_tab == 'analise' else '#6b7280'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
        </div>
        <div class="nav-content">
            <span class="nav-title">Análise de IA</span>
            <span class="nav-sub">Visualize análises inteligentes</span>
        </div>
    </div>
</div>
<script>
function triggerTab(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
          if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '90px';
            iframes[i].style.marginTop = '-15px';
            break;
          }}
        }} catch(e) {{}}
    }}
}})();
</script>
""", height=90, scrolling=False)

    st.markdown("""
    <style>
    /* Remove espaço entre nav-bar e conteúdo seguinte */
    section.main .block-container > div > div:has(> iframe) + div {
        margin-top: -64px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if not todas_empresas:
        st.info("Cadastre sua empresa e concorrentes para usar esta funcionalidade.")
        st.stop()

    if not st.secrets.get("APIFY_TOKEN", ""):
        st.warning("Configure `APIFY_TOKEN` no secrets.toml para usar esta funcionalidade.")

# ══════════════════════════════════════════════════════════════════
# ABA: CONFIGURAÇÃO — Cards de empresa
# ══════════════════════════════════════════════════════════════════

    if main_tab == "configuracao":

        editando_empresa   = st.session_state.ads_editando_empresa
        onboarding_empresa = st.session_state.ads_onboarding_empresa
        onboarding_paginas = st.session_state.ads_onboarding_paginas

        # ── Ghost buttons ocultos via CSS
        all_ghost_css = "".join([f"""
        .st-key-cfg_ghost_edit_{ci},
        .st-key-cfg_ghost_save_{ci},
        .st-key-cfg_ghost_cancel_{ci},
        .st-key-cfg_ghost_buscar_{ci},
        .st-key-cfg_input_val_{ci} {{
            position:fixed!important;top:-9999px!important;left:-9999px!important;
            width:0!important;height:0!important;overflow:hidden!important;
            opacity:0!important;pointer-events:none!important;display:none!important;
        }}
        .stElementContainer:has(.st-key-cfg_ghost_edit_{ci}),
        .stElementContainer:has(.st-key-cfg_ghost_save_{ci}),
        .stElementContainer:has(.st-key-cfg_ghost_cancel_{ci}),
        .stElementContainer:has(.st-key-cfg_ghost_buscar_{ci}),
        .stElementContainer:has(.st-key-cfg_input_val_{ci}) {{
            display:none!important;height:0!important;min-height:0!important;
            max-height:0!important;padding:0!important;margin:0!important;overflow:hidden!important;
        }}
        """ for ci in range(len(todas_empresas))])

        st.markdown(f"<style>{all_ghost_css}</style>", unsafe_allow_html=True)

        # ── Ghost triggers
        ghost_edit    = {}
        ghost_save    = {}
        ghost_cancel  = {}
        ghost_buscar  = {}
        input_vals    = {}

        for ci, e in enumerate(todas_empresas):
            ghost_edit[ci]   = st.button(str(ci),          key=f"cfg_ghost_edit_{ci}")
            ghost_save[ci]   = st.button(f"save_{ci}",     key=f"cfg_ghost_save_{ci}")
            ghost_cancel[ci] = st.button(f"cancel_{ci}",   key=f"cfg_ghost_cancel_{ci}")
            ghost_buscar[ci] = st.button(f"buscar_{ci}",   key=f"cfg_ghost_buscar_{ci}")
            is_minha_e = e["tipo"] == "minha"
            ads_id_e   = emp.get("ads_id","") if is_minha_e else concs[e["idx"]].get("ads_id","")
            input_vals[ci] = st.text_input(
                f"val_{ci}", value=ads_id_e,
                key=f"cfg_input_val_{ci}", label_visibility="hidden",
            )

        # ── Processar ações
        for ci, e in enumerate(todas_empresas):
            if ghost_edit[ci]:
                st.session_state.ads_editando_empresa   = e["nome"]
                st.session_state.ads_onboarding_empresa = None
                st.session_state.ads_onboarding_paginas = []
                st.rerun()
            if ghost_cancel[ci]:
                st.session_state.ads_editando_empresa   = None
                st.session_state.ads_onboarding_empresa = None
                st.session_state.ads_onboarding_paginas = []
                st.rerun()
            if ghost_save[ci]:
                val = input_vals.get(ci,"").strip()
                if val:
                    salvar_ads_id(e, val)
                    st.session_state.ads_editando_empresa   = None
                    st.session_state.ads_onboarding_empresa = None
                    st.session_state.ads_onboarding_paginas = []
                    st.toast(f"✅ {e['nome']} salvo!", icon="✅")
                    st.rerun()
            if ghost_buscar[ci]:
                val = input_vals.get(ci,"").strip()
                if val:
                    st.session_state.ads_onboarding_empresa = e["nome"]
                    st.session_state.ads_editando_empresa   = e["nome"]
                    with st.spinner("Buscando…"):
                        paginas = buscar_paginas_facebook(val)
                    st.session_state.ads_onboarding_paginas = paginas
                    st.rerun()

        # ── INFO BOX
        st.markdown("""
        <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;
                    padding:11px 16px;font-size:13px;color:#0369a1;
                    display:flex;align-items:flex-start;gap:10px;
                    line-height:1.6;margin-top:-65px">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0369a1"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                 style="flex-shrink:0;margin-top:2px">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <div>
                Clique em <strong>✏️ Editar</strong> em cada empresa para configurar.
                Cole o <strong>nome exato da página</strong> ou o <strong>ID numérico</strong>
                do Facebook, depois clique em <strong>Buscar páginas</strong> para encontrar
                ou <strong>Salvar ID</strong> para salvar diretamente.
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Monta HTML dos cards
        cards_html = ""
        for ci, e in enumerate(todas_empresas):
            is_minha  = e["tipo"] == "minha"
            ads_id    = emp.get("ads_id","") if is_minha else concs[e["idx"]].get("ads_id","")
            page_pic  = emp.get("ads_page_pic","") if is_minha else concs[e["idx"]].get("ads_page_pic","")
            has_id    = bool(ads_id.strip())
            is_editing = (editando_empresa == e["nome"])
            cor       = get_minha_empresa_color() if is_minha else get_concorrente_color(e["idx"])
            av_txt    = gerar_avatar(e["nome"])
            badge_lbl = "Minha empresa" if is_minha else "Concorrente"
            badge_bg  = "#f0fdf4" if is_minha else "#eff6ff"
            badge_col = "#15803d" if is_minha else "#1d4ed8"
            badge_brd = "#bbf7d0" if is_minha else "#bfdbfe"
            dot_col   = "#22c55e" if is_minha else "#3b82f6"
            id_bg     = "#f0fdf4" if has_id else "#f3f4f6"
            id_brd    = "#bbf7d0" if has_id else "#e5e7eb"
            id_dot    = "#22c55e" if has_id else "#d1d5db"
            id_fw     = "600"     if has_id else "400"
            id_color  = "#15803d" if has_id else "#9ca3af"
            id_ff     = "monospace" if has_id else "inherit"
            id_text   = ads_id if has_id else "Não configurado"

            if page_pic and page_pic.startswith("http"):
                av_html = (
                    f'<div style="width:44px;height:44px;border-radius:50%;overflow:hidden;'
                    f'flex-shrink:0;border:2px solid #e5e7eb">'
                    f'<img src="{page_pic}" style="width:100%;height:100%;object-fit:cover;display:block"'
                    f' onerror="this.parentElement.style.background=\'{cor}\';'
                    f'this.parentElement.innerHTML=\'<div style=&quot;display:flex;align-items:center;'
                    f'justify-content:center;width:100%;height:100%;font-size:15px;font-weight:700;'
                    f'color:#fff&quot;>{av_txt}</div>\'" /></div>'
                )
            else:
                av_html = (
                    f'<div style="width:44px;height:44px;border-radius:50%;background:{cor};'
                    f'display:flex;align-items:center;justify-content:center;font-size:15px;'
                    f'font-weight:700;color:#fff;flex-shrink:0">{av_txt}</div>'
                )

            border_style = (
                "border:2px solid #3a9fd6;box-shadow:0 0 0 3px rgba(58,159,214,0.12);"
                if is_editing else "border:1px solid #e5e7eb;"
            )

            # Seção de edição inline (aparece quando is_editing)
            edit_section = f"""
            <div class="edit-section">
                <div style="font-size:11px;font-weight:700;color:#9ca3af;
                            text-transform:uppercase;letter-spacing:0.8px;
                            margin-bottom:8px">ID ou nome da página do Facebook</div>
                <input
                    id="cfg_input_{ci}"
                    type="text"
                    value="{ads_id}"
                    placeholder="Ex: Marketylics  ou  102803918240129"
                    oninput="syncInput({ci}, this.value)"
                    style="width:100%;height:42px;border:1.5px solid #e5e7eb;
                           border-radius:8px;padding:0 14px;font-size:14px;
                           font-family:'DM Sans',sans-serif;color:#111827;
                           background:#fafafa;outline:none;transition:border-color 0.15s;
                           margin-bottom:12px;display:block"
                    onfocus="this.style.borderColor='#3a9fd6';this.style.background='#fff'"
                    onblur="this.style.borderColor='#e5e7eb';this.style.background='#fafafa'"
                />
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                    <button class="btn-buscar" onclick="triggerGhost('buscar_{ci}')">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" stroke-width="2"
                             stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="11" cy="11" r="8"/>
                            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                        </svg>
                        Buscar páginas
                    </button>
                    <button class="btn-salvar" onclick="triggerGhost('save_{ci}')">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" stroke-width="2"
                             stroke-linecap="round" stroke-linejoin="round">
                            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                            <polyline points="17 21 17 13 7 13 7 21"/>
                            <polyline points="7 3 7 8 15 8"/>
                        </svg>
                        Salvar ID
                    </button>
                </div>
            </div>
            """ if is_editing else ""

            cancel_btn = f"""
            <button class="cancel-btn" onclick="triggerGhost('cancel_{ci}')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2.5"
                     stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
                Cancelar
            </button>
            """ if is_editing else f"""
            <button class="edit-btn" onclick="triggerGhost('{ci}')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
                Editar
            </button>
            """

            cards_html += f"""
            <div class="card" style="{border_style}">
                <div class="card-header">
                    {av_html}
                    <div style="flex:1;min-width:0">
                        <div class="nome">{e["nome"]}</div>
                        <div style="display:inline-flex;align-items:center;gap:5px;
                                    background:{badge_bg};color:{badge_col};
                                    border:1px solid {badge_brd};
                                    padding:3px 10px;border-radius:20px;
                                    font-size:11px;font-weight:700;margin-top:4px">
                            {badge_lbl}
                        </div>
                    </div>
                </div>
                <div class="card-body">
                    <div style="border-radius:8px;padding:10px 14px;
                                display:flex;align-items:center;gap:10px;
                                background:{id_bg};border:1px solid {id_brd}">
                        <span style="font-size:16px;flex-shrink:0">{"✅" if has_id else "⬜"}</span>
                        <div style="min-width:0;flex:1">
                            <div style="font-size:10px;font-weight:700;color:#9ca3af;
                                        text-transform:uppercase;letter-spacing:0.6px;
                                        margin-bottom:3px">ID / Nome da página</div>
                            <div style="font-weight:{id_fw};color:{id_color};
                                        font-family:{id_ff};font-size:13px;
                                        overflow:hidden;text-overflow:ellipsis;
                                        white-space:nowrap">{id_text}</div>
                        </div>
                    </div>
                    {edit_section}
                </div>
                <div class="card-footer">
                    {cancel_btn}
                </div>
            </div>"""

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
    background:transparent;
    font-family:'DM Sans',sans-serif;
    overflow:hidden;
    /* remove qualquer margem do iframe em relação à nav bar */
    margin-top:0 !important;
    padding-top:0 !important;
}}
.outer {{
    background:#d2dde9;
    border:1px solid #cbd5e1;
    border-radius:16px;
    padding:16px;
}}
.cards-grid {{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:14px;
}}
.card {{
    background:#fff;
    border-radius:12px;
    overflow:hidden;
    display:flex;
    flex-direction:column;
}}
.card-header {{
    display:flex;align-items:center;gap:12px;
    padding:16px 16px 12px;
}}
.card-body {{
    padding:0 16px 14px;
    display:flex;flex-direction:column;gap:12px;
}}
.edit-section {{
    padding-top:12px;
    border-top:1px solid #f3f4f6;
}}
.nome {{
    font-size:14px;font-weight:700;color:#1a2e4a;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}}
.card-footer {{
    border-top:1px solid #f3f4f6;
    padding:0;
}}
.edit-btn {{
    width:100%;padding:10px 0;
    background:#fff;border:none;
    outline:none;-webkit-appearance:none;
    font-size:13px;font-weight:600;color:#6b7280;
    cursor:pointer;font-family:'DM Sans',sans-serif;
    display:flex;align-items:center;justify-content:center;gap:7px;
    transition:background 0.12s;
}}
.edit-btn:hover {{ background:#f9fafb;color:#111827; }}
.cancel-btn {{
    width:100%;padding:10px 0;
    background:#fff;border:none;
    outline:none;-webkit-appearance:none;
    font-size:13px;font-weight:600;color:#9ca3af;
    cursor:pointer;font-family:'DM Sans',sans-serif;
    display:flex;align-items:center;justify-content:center;gap:6px;
    transition:all 0.12s;
}}
.cancel-btn:hover {{ background:#fef2f2;color:#dc2626; }}
.btn-buscar {{
    display:flex;align-items:center;justify-content:center;gap:7px;
    padding:10px 0;border:1.5px solid #3a9fd6;border-radius:8px;
    background:#eff6ff;font-size:13px;font-weight:700;color:#1d4ed8;
    cursor:pointer;font-family:'DM Sans',sans-serif;transition:background 0.15s;
}}
.btn-buscar:hover {{ background:#dbeafe; }}
.btn-salvar {{
    display:flex;align-items:center;justify-content:center;gap:7px;
    padding:10px 0;border:none;border-radius:8px;
    background:#0e2a47;font-size:13px;font-weight:700;color:#fff;
    cursor:pointer;font-family:'DM Sans',sans-serif;transition:background 0.15s;
}}
.btn-salvar:hover {{ background:#1a3a5c; }}
</style>
<div class="outer">
    <div class="cards-grid">{cards_html}</div>
</div>
<script>
function syncInput(ci, val) {{
    var inputs = window.parent.document.querySelectorAll('input');
    inputs.forEach(function(inp) {{
        var label = inp.getAttribute('aria-label') || '';
        if (label === 'val_' + ci) {{
            var setter = Object.getOwnPropertyDescriptor(
                window.parent.HTMLInputElement.prototype, 'value').set;
            setter.call(inp, val);
            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}
    }});
}}
function triggerGhost(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === String(label)) {{ b.click(); return; }}
    }}
}}
function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.height = (h + 4) + 'px';
                iframes[i].style.marginTop = '-8px';
                break;
            }}
        }} catch(ex) {{}}
    }}
}}
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 80);
setTimeout(syncHeight, 300);
</script>
""", height=250, scrolling=False)

        # ── Páginas encontradas
        if onboarding_empresa and onboarding_paginas:
            e_ob = next((x for x in todas_empresas if x["nome"] == onboarding_empresa), None)
            if e_ob:
                ci_ob = next(i for i, x in enumerate(todas_empresas) if x["nome"] == onboarding_empresa)
                sk_ob = safe_key(e_ob["nome"])
                st.markdown(
                    f"<div style='font-size:11px;font-weight:700;color:#6b7280;"
                    f"text-transform:uppercase;letter-spacing:0.5px;margin:12px 0 8px'>"
                    f"📋 {len(onboarding_paginas[:8])} página(s) encontrada(s)</div>",
                    unsafe_allow_html=True,
                )
                for pi, pg in enumerate(onboarding_paginas[:8]):
                    initial = (pg.get("nome","P") or "P")[0].upper()
                    pic     = pg.get("profile_picture","")
                    thumb   = (
                        f'<img src="{pic}" style="width:34px;height:34px;border-radius:50%;'
                        f'object-fit:cover;display:block" onerror="this.style.display=\'none\'" />'
                        if pic and pic.startswith("http")
                        else f'<span style="font-size:14px;font-weight:700;color:#6b7280">{initial}</span>'
                    )
                    col_pg, col_usar = st.columns([4, 1])
                    with col_pg:
                        st.markdown(f"""
                        <div style="display:flex;align-items:center;gap:12px;
                                    padding:10px 14px;background:#f9fafb;
                                    border:1px solid #e5e7eb;border-radius:10px;
                                    margin-bottom:6px">
                            <div style="width:34px;height:34px;border-radius:50%;
                                        background:#e5e7eb;display:flex;align-items:center;
                                        justify-content:center;flex-shrink:0;overflow:hidden">
                                {thumb}
                            </div>
                            <div style="flex:1;min-width:0">
                                <div style="font-size:13px;font-weight:700;color:#111827">
                                    {pg.get("nome","—")}
                                </div>
                                <div style="font-size:11px;color:#9ca3af;font-family:monospace;margin-top:2px">
                                    ID: {pg.get("page_id","—")}
                                </div>
                            </div>
                            <div style="font-size:12px;font-weight:600;color:#3a9fd6;flex-shrink:0">
                                {pg.get("total_ads",0)} ads
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    with col_usar:
                        if st.button(
                            "Usar",
                            key=f"btn_pg_usar_{sk_ob}_{ci_ob}_{pi}",
                            use_container_width=True,
                        ):
                            salvar_ads_id(
                                e_ob,
                                pg.get("page_id") or pg.get("nome",""),
                                pg.get("profile_picture",""),
                            )
                            st.session_state.ads_editando_empresa   = None
                            st.session_state.ads_onboarding_empresa = None
                            st.session_state.ads_onboarding_paginas = []
                            st.toast(f"✅ {pg.get('nome','')} selecionado!", icon="✅")
                            st.rerun()

    # ══════════════════════════════════════════════════════════════════
    # ABA: EMPRESAS CONFIGURADAS — Cards estilo imagem 2
    # ══════════════════════════════════════════════════════════════════
    elif main_tab == "empresas":

        if not empresas_configuradas:
            st.markdown("""
            <div style='background:#fff;border:1px dashed #d1d5db;border-radius:14px;
                        padding:48px 32px;text-align:center;margin-top:8px'>
                <div style='font-size:32px;margin-bottom:12px'>⚙️</div>
                <div style='font-size:16px;font-weight:600;color:#374151;margin-bottom:6px'>Nenhuma página configurada</div>
                <div style='font-size:14px;color:#9ca3af'>Clique em <b>Configuração</b> acima para configurar suas páginas.</div>
            </div>
            """, unsafe_allow_html=True)
            st.stop()

        query_values = {}
        for e in empresas_configuradas:
            ck = e["nome"]
            ads_id_salvo = emp.get("ads_id","") if e["tipo"]=="minha" else concs[e["idx"]].get("ads_id","")
            query_values[ck] = ads_id_salvo

        # ── Barra de abas de empresas ─────────────────────────────────
        if "ads_aba_ativa" not in st.session_state:
            st.session_state.ads_aba_ativa = 0

        # Ghost buttons para abas de empresa
        aba_ghost_css = []
        for i in range(len(empresas_configuradas)):
            k = f"btn_aba_ads_{i}"
            aba_ghost_css.append(f"""
            .st-key-{k} {{
                position:fixed !important; top:-9999px !important; left:-9999px !important;
                width:0 !important; height:0 !important; overflow:hidden !important;
                opacity:0 !important; pointer-events:none !important; display:none !important;
            }}
            .stElementContainer:has(.st-key-{k}) {{
                display:none !important; height:0 !important; min-height:0 !important;
                max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
            }}
            """)
        if aba_ghost_css:
            st.markdown(f"<style>{''.join(aba_ghost_css)}</style>", unsafe_allow_html=True)

        for i in range(len(empresas_configuradas)):
            if st.button(f"aba_ads_{i}", key=f"btn_aba_ads_{i}"):
                st.session_state.ads_aba_ativa = i
                st.rerun()

        abas_nomes = [e["nome"] for e in empresas_configuradas]
        aba_ativa  = min(st.session_state.ads_aba_ativa, len(abas_nomes) - 1)

        # ── Cards de empresa no topo — estilo imagem 2
        empresas_cards_json = []
        for i, e in enumerate(empresas_configuradas):
            is_minha = e["tipo"] == "minha"
            cor = get_minha_empresa_color() if is_minha else get_concorrente_color(e["idx"])
            ads_id = emp.get("ads_id", "") if is_minha else concs[e["idx"]].get("ads_id", "")
            empresas_cards_json.append({
                "i": i,
                "nome": e["nome"],
                "tipo": e["tipo"],
                "ads_id": ads_id,
                "is_minha": is_minha,
                "badge_lbl": "Minha empresa" if is_minha else "Concorrente",
            })

        empresas_cards_str = _json.dumps(empresas_cards_json, ensure_ascii=False)

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; -webkit-font-smoothing:antialiased; }}

/* ── Container principal ── */
.main-wrap {{
    background:#ffffff;
    border-radius:16px;
    overflow:hidden;
    margin-bottom:0;
}}

/* ── Grid de cards de empresa ── */
.cards-grid {{
    display:grid;
    grid-template-columns: repeat(3,1fr);
    gap:0;
    padding:15px;
    gap:15px;
}}

/* ── Card individual — estilo da imagem 2 ── */
.emp-card {{
    background:#f9fafb;
    border:1px solid #e5e7eb;
    border-radius:12px;
    padding:16px;
    display:flex;
    align-items:center;
    gap:12px;
    cursor:pointer;
    transition:all 0.15s;
    position:relative;
}}
.emp-card:hover {{
    border-color:#3a9fd6;
    background:#fff;
    box-shadow:0 2px 10px rgba(58,159,214,0.1);
}}
.emp-card.active {{
    background:#fff;
    border: 2px solid #3b82f6;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}}
.emp-card.active::after {{
    content:'';
    position:absolute;
    bottom:0; left:0; right:0;
    height:3px;
    border-radius:0 0 12px 12px;
}}
.emp-icon {{
    width:44px; height:44px; border-radius:10px;
    background:#e9eef5;
    display:flex; align-items:center; justify-content:center;
    flex-shrink:0;
}}
.emp-card.active .emp-icon {{ background:#dbeafe; }}
.emp-icon svg {{ width:22px; height:22px; }}
.emp-info {{ flex:1; min-width:0; }}
.emp-nome {{
    font-size:14px; font-weight:700; color:#1a2e4a;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    margin-bottom:4px;
}}
.badge-minha {{
    display:inline-flex; align-items:center; gap:5px;
    background:#f0fdf4; color:#15803d;
    border:1px solid #bbf7d0;
    padding:3px 10px; border-radius:20px;
    font-size:11px; font-weight:700;
    flex-shrink:0; align-self:center;
}}
.badge-conc {{
    display:inline-flex; align-items:center; gap:5px;
    background:#eff6ff; color:#1d4ed8;
    border:1px solid #bfdbfe;
    padding:3px 10px; border-radius:20px;
    font-size:11px; font-weight:700;
    flex-shrink:0; align-self:center;
}}

/* ── Barra de abas embaixo dos cards ── */
.tabs-row {{
    display:none !important;
}}
.tab-btn {{
    padding:12px 20px;
    font-size:13px; font-weight:700;
    color:#9ca3af;
    border:none; border-bottom:3px solid transparent;
    cursor:pointer; font-family:'DM Sans',sans-serif;
    transition:all 0.15s; white-space:nowrap;
    margin-bottom:-1px;
}}
.tab-btn:hover {{ color:#374151; }}
.tab-btn.active {{
    color:#1a2e4a;
    border-bottom:4px solid #3a9fd6;
}}
.right-wrap {{
    margin-left:auto;
    display:flex; align-items:center;
    padding-right:4px;
}}
.cfg-btn {{
    width:30px; height:30px;
    border:1px solid #e5e7eb; border-radius:7px;
    background:#fff; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    color:#9ca3af; transition:all 0.12s;
}}
.cfg-btn:hover {{ background:#f3f4f6; color:#374151; border-color:#9ca3af; }}
</style>
<div class="main-wrap">
    <div class="cards-grid" id="cards-grid"></div>
    <div class="tabs-row" id="tabs-row">
        <div class="right-wrap">
            <button class="cfg-btn" onclick="triggerTab('tab_cfg')" title="Configurações">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                </svg>
            </button>
        </div>
    </div>
</div>
<script>
var EMPRESAS = {empresas_cards_str};
var ABA_ATIVA = {aba_ativa};

function buildUI() {{
    // Cards
    var grid = document.getElementById('cards-grid');
    grid.innerHTML = '';
    EMPRESAS.forEach(function(e) {{
        var card = document.createElement('div');
        card.className = 'emp-card' + (e.i === ABA_ATIVA ? ' active' : '');
        card.id = 'emp_card_' + e.i;
        var badgeHtml = e.is_minha
            ? '<span class="badge-minha">Minha empresa</span>'
            : '<span class="badge-conc">Concorrente</span>';
        card.innerHTML =
            '<div class="emp-icon">'
            + '<svg viewBox="0 0 24 24" fill="none" stroke="' + (e.i === ABA_ATIVA ? '#3b82f6' : '#64748b') + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
            + '<rect x="2" y="7" width="20" height="14" rx="2"/>'
            + '<path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>'
            + '<line x1="12" y1="12" x2="12" y2="16"/>'
            + '<line x1="10" y1="14" x2="14" y2="14"/>'
            + '</svg>'
            + '</div>'
            + '<div class="emp-info">'
            + '<div class="emp-nome">' + e.nome + '</div>'
            + (e.ads_id ? '<div style="font-size:12px;color:#9ca3af;">ID: ' + e.ads_id + '</div>' : '')
            + '</div>'
            + badgeHtml
        card.addEventListener('click', function(ev) {{
            if (ev.target.closest('.lapiz-btn')) return;
            selectAba(e.i);
        }});
        grid.appendChild(card);
    }});

    // Tabs
    var tabsRow = document.getElementById('tabs-row');
    var rightWrap = tabsRow.querySelector('.right-wrap');
    // Remove existing tabs
    tabsRow.querySelectorAll('.tab-btn').forEach(function(b) {{ b.remove(); }});
    EMPRESAS.forEach(function(e) {{
        var btn = document.createElement('button');
        btn.className = 'tab-btn' + (e.i === ABA_ATIVA ? ' active' : '');
        btn.id = 'tab_btn_' + e.i;
        btn.textContent = e.nome;
        btn.onclick = function() {{ selectAba(e.i); }};
        tabsRow.insertBefore(btn, rightWrap);
    }});

    syncHeight();
}}

function selectAba(i) {{
    ABA_ATIVA = i;
    document.querySelectorAll('.emp-card').forEach(function(c) {{ c.classList.remove('active'); }});
    document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    var card = document.getElementById('emp_card_' + i);
    var tab  = document.getElementById('tab_btn_' + i);
    if (card) card.classList.add('active');
    if (tab)  tab.classList.add('active');
    triggerBtn('aba_ads_' + i);
}}

function goConfig(i, ev) {{
    ev.stopPropagation();
    triggerBtn('tab_cfg');
}}

function triggerTab(label) {{ triggerBtn(label); }}

function triggerBtn(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}

function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {{
        try {{ if (frames[i].contentWindow === window) {{
            frames[i].style.height = (h + 2) + 'px';
            frames[i].style.marginTop = '-60px'; break;
        }} }} catch(e) {{}}
    }}
}}

buildUI();
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 200); setTimeout(syncHeight, 600);
</script>
""", height=100, scrolling=False)

        # ── s de conteúdo por empresa ─────────────────────────
        conteudo_tab_ghost_css = []
        for e in empresas_configuradas:
            sk = safe_key(e["nome"])
            for tab_name in ["anuncios", "analise"]:
                k = f"btn_conteudo_{sk}_{tab_name}"
                conteudo_tab_ghost_css.append(f"""
                .st-key-{k} {{
                    position:fixed !important; top:-9999px !important; left:-9999px !important;
                    width:0 !important; height:0 !important; overflow:hidden !important;
                    opacity:0 !important; pointer-events:none !important; display:none !important;
                }}
                .stElementContainer:has(.st-key-{k}) {{
                    display:none !important; height:0 !important; min-height:0 !important;
                    max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
                }}
                """)
        if conteudo_tab_ghost_css:
            st.markdown(f"<style>{''.join(conteudo_tab_ghost_css)}</style>", unsafe_allow_html=True)

        for e in empresas_configuradas:
            sk = safe_key(e["nome"])
            ck = e["nome"]
            for tab_name in ["anuncios", "analise"]:
                btn_key = f"btn_conteudo_{sk}_{tab_name}"
                if st.button(f"tab_{sk}_{tab_name}", key=btn_key):
                    st.session_state.ads_aba_conteudo[ck] = tab_name
                    st.rerun()

        # ── Dados e helpers ──────────────────────────────────────────
        empresas_com_dados = [
            e for e in todas_empresas
            if e["nome"] in st.session_state.ads_cache or e["nome"] in st.session_state.ads_erro
        ]

        if not empresas_com_dados:
            st.markdown("""
            <div style='background:#fff;border:1px dashed #d1d5db;border-radius:14px;padding:48px 32px;text-align:center;margin-top:8px'>
                <div style='font-size:32px;margin-bottom:12px'>📢</div>
                <div style='font-size:16px;font-weight:600;color:#374151;margin-bottom:6px'>Nenhum dado carregado ainda</div>
                <div style='font-size:14px;color:#9ca3af'>Configure as páginas e clique em <b>Buscar / Atualizar</b>.</div>
            </div>
            """, unsafe_allow_html=True)
            st.stop()

        # ── Plataformas SVG JS ────────────────────────────────────────
        def _plat_svg_js(uid: str) -> str:
            return f"""
(function(){{
    var plats={{}};
    try {{ plats = window.__PLATS_{uid}__; }} catch(e) {{ return; }}
    var C = '#9ca3af';
    var SVGS = {{
        "facebook": '<svg width="12" height="12" viewBox="0 0 24 24" fill="'+C+'"><path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.268h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/></svg>',
        "instagram": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><rect x="2" y="2" width="20" height="20" rx="5" fill="'+C+'"/><circle cx="12" cy="12" r="4.5" stroke="white" stroke-width="1.8" fill="none"/><circle cx="17.5" cy="6.5" r="1.2" fill="white"/></svg>',
        "messenger": '<svg width="16" height="16" viewBox="0 0 24 24" fill="'+C+'"><path d="M12 0C5.373 0 0 4.975 0 11.111c0 3.497 1.745 6.616 4.472 8.652V24l4.086-2.242c1.09.301 2.246.464 3.442.464 6.627 0 12-4.975 12-11.111S18.627 0 12 0zm1.191 14.963l-3.055-3.26-5.963 3.26L10.732 8.4l3.131 3.259L19.752 8.4l-6.561 6.563z"/></svg>',
        "whatsapp":  '<svg width="16" height="16" viewBox="0 0 24 24" fill="'+C+'"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>',
        "audience_network": '<svg width="16" height="16" viewBox="0 0 24 24" fill="'+C+'"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z"/></svg>',
        "threads": '<svg width="16" height="16" viewBox="0 0 192 192" fill="'+C+'"><path d="M141.537 88.988a66.667 66.667 0 00-2.518-1.143c-1.482-27.307-16.403-42.94-41.457-43.1h-.34c-14.986 0-27.449 6.396-35.12 18.036l13.779 9.452c5.73-8.695 14.724-10.548 21.348-10.548h.229c8.249.053 14.474 2.452 18.503 7.129 2.932 3.405 4.893 8.111 5.864 14.05-7.314-1.243-15.224-1.626-23.68-1.14-23.82 1.371-39.134 15.264-38.105 34.568.522 9.792 5.4 18.216 13.735 23.719 7.047 4.652 16.124 6.927 25.557 6.412 12.458-.683 22.231-5.436 29.049-14.127 5.178-6.6 8.453-15.153 9.899-25.93 5.937 3.583 10.337 8.298 12.767 13.966 4.132 9.635 4.373 25.468-8.546 38.376-11.319 11.308-24.925 16.2-45.488 16.351-22.809-.169-40.06-7.484-51.275-21.742C35.236 139.966 29.808 120.682 29.605 96c.203-24.682 5.63-43.966 16.133-57.317C56.954 24.425 74.204 17.11 97.013 16.94c22.975.17 40.526 7.52 52.171 21.847 5.71 7.026 10.015 15.86 12.853 26.162l16.147-4.308c-3.44-12.68-8.853-23.606-16.219-32.668C147.036 9.607 125.202.195 97.07 0h-.113C68.882.195 47.292 9.642 32.788 28.08 19.882 44.485 13.224 67.315 13.001 96v.027c.224 28.686 6.882 51.516 19.788 67.92C47.292 182.358 68.882 191.805 96.957 192h.114c24.92-.173 42.433-6.695 56.854-21.101 18.941-18.925 18.352-42.444 12.139-56.924-4.51-10.507-13.192-19.01-24.527-24.987zm-45.458 43.051c-10.443.588-21.287-4.098-26.698-11.76-3.28-4.626-3.27-9.498.028-13.062 3.853-4.194 10.08-6.386 17.537-6.386.799 0 1.609.024 2.427.074 9.335.539 16.788 3.712 20.91 8.931 2.653 3.367 3.604 7.573 2.733 12.094-1.765 9.151-10.228 9.867-16.937 10.109z"/></svg>'
    }};
    var el = document.getElementById('plat_icons_{uid}');
    if (!el) return;
    if (!plats || plats.length === 0) {{ el.innerHTML='<span style="color:#9ca3af;font-size:12px">—</span>'; return; }}
    el.innerHTML = plats.map(function(p) {{
        var key = p.toLowerCase().replace(' ','_').replace('-','_');
        var svg = SVGS[key] || '';
        return '<span class="plat-badge" title="'+p+'">'+(svg||('<span style="font-size:10px;color:#9ca3af">'+p[0].toUpperCase()+'</span>'))+'</span>';
    }}).join('');
}})();
"""

        # ══════════════════════════════════════════════════════════════
        # FUNÇÃO PRINCIPAL: render_ads_empresa
        # ══════════════════════════════════════════════════════════════
        def render_ads_empresa(emp_item):
            ck       = emp_item["nome"]
            nome     = emp_item["nome"]
            is_minha = emp_item["tipo"] == "minha"
            cor_av   = get_minha_empresa_color() if is_minha else get_concorrente_color(emp_item["idx"])
            avatar   = gerar_avatar(nome)
            sk       = safe_key(nome)

            if emp_item["tipo"] == "minha":
                configured_page = emp.get("ads_id","").strip()
            else:
                configured_page = concs[emp_item["idx"]].get("ads_id","").strip()

            if ck in st.session_state.ads_erro:
                st.error(f"Erro: {st.session_state.ads_erro[ck]}")
                return

            cache_entry = st.session_state.ads_cache.get(ck)
            if not cache_entry:
                st.info("Sem dados. Configure a página e clique em Buscar.")
                return

            ads_list_raw = cache_entry["data"]
            ts           = cache_entry["ts"]
            query        = cache_entry.get("query","")

            if configured_page:
                if configured_page.isdigit():
                    filtered = [a for a in ads_list_raw if str(a.get("page_id","")).strip() == configured_page]
                    ads_list = filtered if filtered else ads_list_raw
                else:
                    configured_lower = configured_page.lower()
                    exact = [a for a in ads_list_raw if (a.get("page_name") or "").strip().lower() == configured_lower]
                    if exact:
                        ads_list = exact
                    else:
                        partial = [a for a in ads_list_raw
                                   if configured_lower in (a.get("page_name") or "").strip().lower()
                                   or (a.get("page_name") or "").strip().lower() in configured_lower]
                        ads_list = partial if partial else ads_list_raw
            else:
                ads_list = ads_list_raw

            if emp_item["tipo"] == "minha":
                page_pic_empresa = st.session_state.dados["minha_empresa"].get("ads_page_pic", "") or ""
            else:
                page_pic_empresa = st.session_state.dados["concorrentes"][emp_item["idx"]].get("ads_page_pic", "") or ""

            if not page_pic_empresa:
                for ad in ads_list:
                    p = ad.get("page_profile_picture", "") or ""
                    if p and p.startswith("http"):
                        page_pic_empresa = p
                        break

            if page_pic_empresa:
                avatar_empresa_html = (
                    f'<div style="width:44px;height:44px;border-radius:50%;overflow:hidden;flex-shrink:0;border:2px solid #e5e7eb;">'
                    f'<img src="{page_pic_empresa}" style="width:100%;height:100%;object-fit:cover;display:block" '
                    f'onerror="this.parentElement.style.background=\'{cor_av}\';this.parentElement.innerHTML=\'<div style=&quot;display:flex;align-items:center;justify-content:center;width:100%;height:100%;font-size:16px;font-weight:700;color:#fff&quot;>{avatar}</div>\'" /></div>'
                )
            else:
                avatar_empresa_html = (
                    f'<div style="width:44px;height:44px;border-radius:50%;background:{cor_av};display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#fff;flex-shrink:0">{avatar}</div>'
                )

            badge_bg  = "#eff6ff" if is_minha else "#f3f4f6"
            badge_txt = "#1d4ed8" if is_minha else "#6b7280"
            badge_brd = "#bfdbfe" if is_minha else "#e5e7eb"
            badge_lbl = "Minha Empresa" if is_minha else "Concorrente"

            import urllib.parse as _urlparse
            if configured_page and configured_page.isdigit():
                lib_url = (f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=BR&is_targeted_country=false&media_type=all&search_type=page&sort_data[direction]=desc&sort_data[mode]=total_impressions&view_all_page_id={configured_page}")
            elif query:
                lib_url = (f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=BR&q={_urlparse.quote(query)}")
            else:
                lib_url = ""

            page_display = configured_page if configured_page else "—"
            lib_btn_top = f'<a href="{lib_url}" target="_blank" style="display:inline-flex;align-items:center;gap:6px;background:#042b6b;color:#fff;padding:7px 14px;border-radius:8px;font-size:13px;font-weight:700;text-decoration:none;white-space:nowrap">Ver no Meta Ad Library</a>' if lib_url else ""

            st.markdown(f"""
            <div style='background:#fff;border:1px solid #e5e7eb;border-bottom:none;border-radius:12px 12px 0 0;overflow:hidden;margin-top:-45px;'>
                <div style='display:flex;align-items:center;gap:16px;padding:16px 20px'>
                    {avatar_empresa_html}
                    <div style='flex:1;min-width:0'>
                        <div style='font-size:17px;font-weight:700;color:#111827'>{nome}</div>
                        <div style='display:flex;align-items:center;gap:6px;flex-wrap:wrap;'>
                            <span style='font-size:13px;color:#6b7280;font-weight:500'>{badge_lbl}</span>
                            <span style='color:#d1d5db;font-size:12px'>·</span>
                            <span style='font-size:13px;color:#6b7280'>Página: {page_display}</span>
                        </div>
                    </div>
                    <div style='display:flex;align-items:center;gap:0;flex-shrink:0'>
                        <div style='width:1px;height:40px;background:#e5e7eb;margin-right:20px'></div>
                        <div style='text-align:center;min-width:56px'>
                            <div style='font-size:28px;font-weight:800;color:#111827;line-height:1'>{len(ads_list)}</div>
                            <div style='font-size:11px;color:#394252;font-weight:900;text-transform:uppercase;letter-spacing:0.5px;margin-top:3px'>anúncios</div>
                        </div>
                        <div style='width:1px;height:40px;background:#e5e7eb;margin:0 20px'></div>
                        {lib_btn_top}
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)

            aba_conteudo_atual = st.session_state.ads_aba_conteudo.get(ck, "anuncios")

            # ── ABA: ANÚNCIOS ─────────────────────────────────────────
            if aba_conteudo_atual == "anuncios":

                col_key = f"ads_cols_{sk}"
                if col_key not in st.session_state:
                    st.session_state[col_key] = 4

                n_cols_atual = st.session_state.get(col_key, 4)
                filtros_key = f"filtros_{sk}"

                st.markdown(f"""
                <style>
                @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
                .st-key-{filtros_key} {{ margin-top: -30px !important; }}
                .st-key-{filtros_key} > div > div[data-testid="stHorizontalBlock"] {{
                    background: #ffffff !important;
                    border: 1px solid #e5e7eb !important;
                    border-top: none !important;
                    border-radius: 0 0 12px 12px !important;
                    padding: 20px 20px !important;
                    gap: 8px !important;
                    align-items: center !important;
                }}
                .st-key-{filtros_key} div[data-testid="stTextInput"] input {{
                    background-color: #fafafa !important;
                    border-radius: 8px !important;
                    height: 40px !important;
                    padding: 0 14px !important;
                    font-family: 'DM Sans', sans-serif !important;
                    font-size: 14px !important;
                    color: #111827 !important;
                    transition: border-color 0.15s !important;
                }}
                .st-key-{filtros_key} div[data-baseweb="select"] > div {{
                    background-color: #ffffff !important;
                    border: 2px solid #e5e7eb !important;
                    border-radius: 8px !important;
                    height: 40px !important;
                    min-height: 40px !important;
                    padding: 0 10px !important;
                    font-family: 'DM Sans', sans-serif !important;
                    font-size: 14px !important;
                    color: #6b7280 !important;
                    transition: border-color 0.15s !important;
                }}
                .st-key-ads_toggle_cols_{sk} button {{
                    height: 40px !important;
                    width: 40px !important;
                    min-width: 40px !important;
                    max-width: 40px !important;
                    padding: 4px !important;
                    border: 1px solid #e5e7eb !important;
                    border-radius: 8px !important;
                    background: #ffffff !important;
                }}
                </style>
                """, unsafe_allow_html=True)

                import unicodedata as _ud
                def _limpar_formato(s):
                    return ''.join(c for c in s if _ud.category(c) not in ('So','Sm','Sk','Mn')).strip()
                formatos_disponiveis = sorted(set(_limpar_formato(a["formato"]) for a in ads_list))

                chave_criativo_ads = f"ia_ads_criativos_{sk}"
                chave_copy_ads     = f"ia_ads_copys_{sk}"
                chave_geral_ads    = f"ia_ads_geral_{sk}"
                tem_criativo_ads   = bool(st.session_state.get(chave_criativo_ads, ""))
                tem_copy_ads       = bool(st.session_state.get(chave_copy_ads, ""))
                tem_geral_ads      = bool(st.session_state.get(chave_geral_ads, ""))

                components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.analises-bar {{
    background:#ffffff;
    border:1px solid #e5e7eb;
    border-top:none;
    padding:24px 20px 26px;
}}
.analises-bar-inner {{
    display:grid; grid-template-columns:180px 1fr; gap:20px; align-items:center;
}}
.analises-bar-left {{ display:flex; flex-direction:column; gap:6px; }}
.analises-bar-titulo {{ font-size:18px; font-weight:800; color:#0f1f35; letter-spacing:-0.3px; line-height:1.2; }}
.analises-bar-sub {{ font-size:13px; color:#9ca3af; line-height:1.5; }}
.analises-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
.atalho-card {{
    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
    padding:20px 16px; cursor:pointer; font-family:'DM Sans',sans-serif;
    display:flex; flex-direction:row; align-items:flex-start; gap:14px;
    transition:all 0.15s; text-align:left;
    box-shadow:0 1px 4px rgba(0,0,0,0.04);
}}
.atalho-card:hover {{ border-color:#c7d2fe; box-shadow:0 4px 16px rgba(99,102,241,0.1); transform:translateY(-1px); }}
.atalho-card.done {{ border-color:#bbf7d0; background:#f0fdf4; }}
.atalho-card.done:hover {{ border-color:#22c55e; box-shadow:0 4px 16px rgba(34,197,94,0.1); }}
.atalho-icon-wrap {{ width:46px; height:46px; border-radius:50%; display:flex; align-items:center; justify-content:center; flex-shrink:0; font-size:22px; }}
.atalho-icon-wrap.blue   {{ background:#e0f0ff; }}
.atalho-icon-wrap.green  {{ background:#e4f9ee; }}
.atalho-icon-wrap.purple {{ background:#ede9fe; }}
.atalho-text {{ display:flex; flex-direction:column; gap:3px; }}
.atalho-nome {{ font-size:14px; font-weight:700; color:#111827; }}
.atalho-desc {{ font-size:12px; color:#9ca3af; line-height:1.4; }}
.atalho-card.done .atalho-desc {{ color:#15803d; font-weight:600; }}
</style>
    <div class="analises-bar">
    <div class="analises-bar-inner">
        <div class="analises-bar-left">
            <div class="analises-bar-titulo">Gerar análises</div>
            <div class="analises-bar-sub">Escolha o tipo de análise que deseja executar nos anúncios.</div>
        </div>
        <div class="analises-grid">
            <button class="atalho-card {'done' if tem_criativo_ads else ''}" onclick="triggerBtn('ia_criativos_{sk}')">
                <div class="atalho-icon-wrap blue">🎨</div>
                <div class="atalho-text">
                    <span class="atalho-nome">Analisar criativos</span>
                    <span class="atalho-desc">{'✅ Gerado' if tem_criativo_ads else 'Avalie formatos visuais e mix de criativos.'}</span>
                </div>
            </button>
            <button class="atalho-card {'done' if tem_copy_ads else ''}" onclick="triggerBtn('ia_copys_{sk}')">
                <div class="atalho-icon-wrap green">✏️</div>
                <div class="atalho-text">
                    <span class="atalho-nome">Analisar copy</span>
                    <span class="atalho-desc">{'✅ Gerado' if tem_copy_ads else 'Analise textos, CTAs e tom de voz dos anúncios.'}</span>
                </div>
            </button>
            <button class="atalho-card {'done' if tem_geral_ads else ''}" onclick="triggerBtn('ia_geral_{sk}')">
                <div class="atalho-icon-wrap purple">📊</div>
                <div class="atalho-text">
                    <span class="atalho-nome">Analisar estratégia</span>
                    <span class="atalho-desc">{'✅ Gerado' if tem_geral_ads else 'Avalie estratégia geral de mídia paga.'}</span>
                </div>
            </button>
        </div>
    </div>
</div>
<script>
function triggerBtn(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '144px';
            iframes[i].style.marginTop = '-15px';
            break;
        }} }} catch(e) {{}}
    }}
}})();
</script>
""", height=144, scrolling=False)

                with st.container(key=filtros_key):
                    fcol1, fcol2, fcol3, fcol4, fcol5, fcol6 = st.columns([3, 2.5, 2.5, 2.5, 2.5, 0.6])
                    with fcol1:
                        busca_texto = st.text_input(
                            "Pesquisar no copy",
                            placeholder="Pesquisar no copy…",
                            key=f"ads_busca_{sk}",
                            label_visibility="collapsed",
                        )
                    with fcol2:
                        filtro_fmt = st.selectbox(
                            "Tipo",
                            ["Tipo (todos)"] + formatos_disponiveis,
                            key=f"ads_fmt_{sk}",
                            label_visibility="collapsed",
                        )
                    with fcol3:
                        plats_todas = sorted(set(p for a in ads_list for p in (a["plataformas"] or [])))
                        filtro_plat = st.selectbox(
                            "Plataforma",
                            ["Plataforma (todas)"] + [p.capitalize() for p in plats_todas],
                            key=f"ads_plat_{sk}",
                            label_visibility="collapsed",
                        )
                    with fcol4:
                        filtro_status = st.selectbox(
                            "Status",
                            ["Status (todos)", "Ativos", "Inativos (histórico)"],
                            key=f"ads_status_{sk}",
                            label_visibility="collapsed",
                        )
                    with fcol5:
                        filtro_ordem = st.selectbox(
                            "Ordenar",
                            ["Mais recentes", "Mais tempo ativo"],
                            key=f"ads_ordem_{sk}",
                            label_visibility="collapsed",
                        )
                    with fcol6:
                        icon_url = (
                            "https://raw.githubusercontent.com/thiagomktsantos/marketylics/4f750a3205deb9b8a618997b3b8e300e3c3bf3f3/images/icons/3-Columns.png"
                            if n_cols_atual == 4
                            else "https://raw.githubusercontent.com/thiagomktsantos/marketylics/4f750a3205deb9b8a618997b3b8e300e3c3bf3f3/images/icons/4-Columns.png"
                        )
                        toggle_cols = st.button(
                            f"![col]({icon_url})",
                            key=f"ads_toggle_cols_{sk}",
                            use_container_width=False,
                            help="Alternar 3/4 colunas",
                        )
                        if toggle_cols:
                            st.session_state[col_key] = 3 if n_cols_atual == 4 else 4
                            st.rerun()

                ads_f = ads_list
                if busca_texto:
                    q = busca_texto.lower()
                    ads_f = [a for a in ads_f if q in (a.get("body") or "").lower() or q in (a.get("title") or "").lower() or q in (a.get("body_raw") or "").lower()]
                if filtro_fmt != "Tipo (todos)":
                    ads_f = [a for a in ads_f if a["formato"] == filtro_fmt]
                if filtro_plat != "Plataforma (todas)":
                    ads_f = [a for a in ads_f if filtro_plat.lower() in (a["plataformas"] or [])]
                if filtro_status == "Ativos":
                    ads_f = [a for a in ads_f if a.get("ativo", True)]
                elif filtro_status == "Inativos (histórico)":
                    ads_f = [a for a in ads_f if not a.get("ativo", True)]

                def _parse_ts(a):
                    raw = str(a.get("data_raw", "") or "").strip()
                    try:
                        ts = int(raw)
                        return ts if ts > 10**8 else 0
                    except Exception:
                        try:
                            return int(_dt.datetime.strptime(raw[:10], "%Y-%m-%d").timestamp())
                        except Exception:
                            return 0

                if filtro_ordem == "Mais recentes":
                    ads_f = sorted(ads_f, key=_parse_ts, reverse=True)
                else:
                    ads_f = sorted(ads_f, key=_parse_ts, reverse=False)

                if not ads_f:
                    st.warning("Nenhum anúncio com os filtros aplicados.")
                    return

                n_video     = sum(1 for a in ads_f if "Vídeo"     in a["formato"])
                n_imagem    = sum(1 for a in ads_f if "Imagem"    in a["formato"])
                n_carrossel = sum(1 for a in ads_f if "Carrossel" in a["formato"])
                n_dynamic   = sum(1 for a in ads_f if a.get("is_dynamic"))
                n_ativos    = sum(1 for a in ads_f if a.get("ativo", True))
                n_inativos  = sum(1 for a in ads_f if not a.get("ativo", True))

                stats_cards = []
                stats_cards.append(f'<div class="stat-card"><div class="stat-num" style="color:#111827">{n_ativos}</div><div class="stat-lbl stat-lbl-green">Ativos</div></div>')
                if n_inativos > 0:
                    stats_cards.append(f'<div class="stat-card"><div class="stat-num" style="color:#6b7280">{n_inativos}</div><div class="stat-lbl">Histórico inativo</div></div>')
                stats_cards.append(f'<div class="stat-card"><div class="stat-num" style="color:#111827">{n_imagem}</div><div class="stat-lbl">Imagens</div></div>')
                stats_cards.append(f'<div class="stat-card"><div class="stat-num" style="color:#111827">{n_video}</div><div class="stat-lbl">Vídeos</div></div>')
                stats_cards.append(f'<div class="stat-card"><div class="stat-num" style="color:#111827">{n_carrossel}</div><div class="stat-lbl">Carrossel</div></div>')
                if n_dynamic > 0:
                    stats_cards.append(f'<div class="stat-card"><div class="stat-num" style="color:#111827">{n_dynamic}</div><div class="stat-lbl">Dinâmicos</div></div>')

                components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{background:transparent;font-family:'DM Sans',sans-serif;overflow:hidden;}}
.stats-row{{display:flex;gap:12px;flex-wrap:wrap;padding:16px 16px 4px;}}
.stat-card{{flex:1;min-width:90px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 10px;text-align:center;}}
.stat-lbl-green{{color:#15803d;}}
.stat-num{{font-size:22px;font-weight:800;}}
.stat-lbl{{color:#6b7280;font-size:12px;font-weight:600;text-transform:uppercase;margin-top:2px;}}
</style>
<div class="stats-row">{"".join(stats_cards)}</div>
<script>
function ajustarAltura(){{var h=document.body.scrollHeight;var iframes=window.parent.document.querySelectorAll('iframe');for(var i=0;i<iframes.length;i++){{try{{if(iframes[i].contentWindow===window){{iframes[i].style.height=(h+8)+'px';break;}}}}catch(e){{}}}}}}
if(window.ResizeObserver)new ResizeObserver(ajustarAltura).observe(document.body);
setTimeout(ajustarAltura,100);
</script>
""", height=80, scrolling=False)

                st.markdown("<div style='height:4px'/>", unsafe_allow_html=True)

                cta_labels = {
                    "LEARN_MORE":"Saiba Mais","SIGN_UP":"Cadastre-se","CONTACT_US":"Fale Conosco",
                    "GET_QUOTE":"Solicitar Orçamento","BOOK_TRAVEL":"Reservar",
                    "WHATSAPP_MESSAGE":"Enviar Mensagem","SEND_WHATSAPP_MESSAGE":"WhatsApp",
                    "MESSAGE_PAGE":"Enviar Mensagem","SHOP_NOW":"Comprar Agora","DOWNLOAD":"Baixar",
                    "WATCH_MORE":"Ver Mais","APPLY_NOW":"Candidatar-se","GET_OFFER":"Ver Oferta",
                    "SUBSCRIBE":"Assinar","CALL_NOW":"Ligar Agora","SEND_MESSAGE":"Enviar Mensagem",
                    "GET_DIRECTIONS":"Como Chegar","BUY_NOW":"Comprar","DONATE":"Doar",
                    "OPEN_LINK":"Abrir Link","SEE_DETAILS":"Ver Detalhes","NO_BUTTON":"",
                }

                all_cards_html = []

                for j, ad in enumerate(ads_f):
                    snap_url    = ad.get("snapshot_url") or ""
                    images      = ad.get("images") or []
                    images_b64  = ad.get("images_b64") or []
                    videos      = ad.get("videos") or []
                    is_dyn      = ad.get("is_dynamic", False)
                    baixo_vol   = ad.get("baixo_volume", False)
                    ad_id       = ad.get("id","")
                    ad_id_short = ad_id
                    plats       = ad.get("plataformas") or []
                    plat_js     = _json.dumps([p.lower() for p in plats])
                    data_inicio = ad.get("data_inicio","")
                    impressoes  = ad.get("impressoes","")
                    body        = ad.get("body") or ""
                    title       = ad.get("title") or ""
                    desc        = ad.get("description") or ""
                    cta         = ad.get("cta") or ""
                    uid         = f"{sk}_{j}"
                    page_pic    = ad.get("page_profile_picture") or ""

                    snap_url_safe = snap_url.replace("'", "").replace('"', "").replace("&", "%26")

                    body_clean  = re.sub(r'\n{2,}', '\n', body.strip())
                    title_clean = title.strip()
                    desc_clean  = desc.strip()

                    body_safe  = body_clean.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    title_safe = title_clean.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    desc_safe  = _truncar(desc_clean, 120).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

                    _raw_item = next(
                        (r for r in cache_entry.get("_raw", []) if str(r.get("adArchiveID") or r.get("ad_archive_id") or r.get("id") or "") == str(ad.get("id",""))),
                        {}
                    )
                    _snapshot_raw = _raw_item.get("snapshot") or {}
                    _cards_raw    = _snapshot_raw.get("cards") or []

                    def _safe_url(v):
                        if not v: return None
                        if isinstance(v, str) and v.startswith("http"): return v
                        return None

                    debug_keys = {
                        # ── Identificação
                        "id":                            ad.get("id", ""),
                        "page_id":                       ad.get("page_id", ""),
                        "page_name":                     ad.get("page_name", ""),
                        "formato":                       ad.get("formato", ""),
                        "plataformas":                   ad.get("plataformas", []),
                        "data_raw":                      ad.get("data_raw", ""),
                        "impressoes":                    ad.get("impressoes", ""),
                        "is_dynamic":                    ad.get("is_dynamic", False),
                        "ativo":                         ad.get("ativo", True),
                        "cta":                           cta,

                        # ── URLs de destino / página
                        "snapshot_url":                  _safe_url(snap_url),
                        "ad_snapshot_url":               _safe_url(_raw_item.get("adSnapshotURL") or _raw_item.get("ad_snapshot_url")),
                        "link_url":                      _safe_url(_raw_item.get("link_url") or _snapshot_raw.get("link_url")),
                        "website_url":                   _safe_url(_raw_item.get("website_url") or _snapshot_raw.get("website_url")),
                        "destination_url":               _safe_url(_raw_item.get("destination_url") or _snapshot_raw.get("destination_url")),
                        "caption":                       ad.get("caption") or _snapshot_raw.get("caption"),

                        # ── Imagens diretas no ad
                        "image_url":                     _safe_url(_raw_item.get("image_url")),
                        "original_image_url":            _safe_url(_raw_item.get("original_image_url")),
                        "resized_image_url":             _safe_url(_raw_item.get("resized_image_url")),
                        "thumbnail_url":                 _safe_url(_raw_item.get("thumbnail_url")),
                        "preview_image_url":             _safe_url(_raw_item.get("preview_image_url")),
                        "full_picture":                  _safe_url(_raw_item.get("full_picture")),

                        # ── Imagens no snapshot
                        "snapshot.image_url":            _safe_url(_snapshot_raw.get("image_url")),
                        "snapshot.original_image_url":   _safe_url(_snapshot_raw.get("original_image_url")),
                        "snapshot.resized_image_url":    _safe_url(_snapshot_raw.get("resized_image_url")),
                        "snapshot.thumbnail_url":        _safe_url(_snapshot_raw.get("thumbnail_url")),
                        "snapshot.background_image":     _safe_url(_snapshot_raw.get("background_image")),

                        # ── Vídeos
                        "video_hd_url":                  _safe_url(_raw_item.get("video_hd_url") or _snapshot_raw.get("video_hd_url")),
                        "video_sd_url":                  _safe_url(_raw_item.get("video_sd_url") or _snapshot_raw.get("video_sd_url")),
                        "video_url":                     _safe_url(_raw_item.get("video_url")    or _snapshot_raw.get("video_url")),
                        "videos_normalizados [0..3]":    videos[:4] if videos else [],

                        # ── Imagens normalizadas (resultado final pipeline)
                        "images_normalizadas [0..3]":    images[:4] if images else [],

                        # ── Cards (carrossel)
                        "cards_count":                   len(_cards_raw),
                        "cards[0].link_url":             _safe_url(_cards_raw[0].get("link_url"))            if _cards_raw else None,
                        "cards[0].image_url":            _safe_url(_cards_raw[0].get("image_url"))           if _cards_raw else None,
                        "cards[0].original_image_url":   _safe_url(_cards_raw[0].get("original_image_url")) if _cards_raw else None,
                        "cards[0].video_hd_url":         _safe_url(_cards_raw[0].get("video_hd_url"))       if _cards_raw else None,
                        "cards[0].video_sd_url":         _safe_url(_cards_raw[0].get("video_sd_url"))       if _cards_raw else None,
                        "cards[0].thumbnail_url":        _safe_url(_cards_raw[0].get("thumbnail_url"))      if _cards_raw else None,
                        "cards[0].body":                 _cards_raw[0].get("body")                          if _cards_raw else None,
                        "cards[0].title":                _cards_raw[0].get("title")                         if _cards_raw else None,
                        "cards[0].cta_type":             _cards_raw[0].get("cta_type")                      if _cards_raw else None,
                        "cards[1].image_url":            _safe_url(_cards_raw[1].get("image_url"))          if len(_cards_raw) > 1 else None,
                        "cards[1].original_image_url":   _safe_url(_cards_raw[1].get("original_image_url")) if len(_cards_raw) > 1 else None,
                        "cards[1].video_hd_url":         _safe_url(_cards_raw[1].get("video_hd_url"))       if len(_cards_raw) > 1 else None,

                        # ── Copy raw
                        "body_len":                      len(body),
                        "title_len":                     len(title),
                        "ad_creative_bodies":            _raw_item.get("ad_creative_bodies"),
                        "ad_creative_link_titles":       _raw_item.get("ad_creative_link_titles"),
                        "ad_creative_link_descriptions": _raw_item.get("ad_creative_link_descriptions"),
                        "snapshot.body":                 _snapshot_raw.get("body"),
                        "snapshot.title":                _snapshot_raw.get("title"),
                        "snapshot.link_description":     _snapshot_raw.get("link_description"),

                        # ── Metadados extras
                        "n_imagens_raw":                 len(images),
                        "n_videos_raw":                  len(videos),
                        "page_profile_picture":          _safe_url(ad.get("page_profile_picture")),
                        "snapshot.page_profile_picture_url": _safe_url(_snapshot_raw.get("page_profile_picture_url")),
                    }

                    # Adiciona dump completo do raw para diagnóstico
                    debug_keys["__RAW_COMPLETO__"] = _raw_item if _raw_item else "NÃO ENCONTRADO NO _raw"
                    debug_json_str = _json.dumps(debug_keys, ensure_ascii=False, indent=2)
                    debug_json_html = debug_json_str.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

                    # Thumb do card: feed baixa qualidade (índice 1), fallback para índice 0
                    img_thumb_url = images[1] if len(images) > 1 else (images[0] if images else "")
                    img_primary = images_b64[1] if len(images_b64) > 1 else (images_b64[0] if images_b64 else img_thumb_url)

                    # Fallbacks para o thumb (não usados no modal de 4 imagens)
                    img_fallbacks = []
                    if img_thumb_url and img_thumb_url not in img_fallbacks:
                        img_fallbacks.append(img_thumb_url)
                    if images_b64 and images_b64[0] not in img_fallbacks:
                        img_fallbacks.append(images_b64[0])
                    img_fallbacks.extend([u for u in images if u not in img_fallbacks])
                    srcs_js = _json.dumps(img_fallbacks)

                    if videos:
                        vid_sd = next((v for v in videos if any(x in v.lower() for x in ("sd","360","480","_sd"))), "")
                        vid_hd = next((v for v in videos if v != vid_sd), "")
                        vid_thumb      = vid_sd or vid_hd or videos[0]          # SD para thumb (leve)
                        vid_modal      = vid_hd or vid_sd or videos[0]          # HD para modal
                        vid_fallback_modal = vid_sd if vid_sd and vid_sd != vid_modal else ""

                        vid_thumb_esc          = vid_thumb.replace("'","").replace('"',"")
                        vid_modal_esc          = vid_modal.replace("'","").replace('"',"")
                        vid_fallback_modal_esc = vid_fallback_modal.replace("'","").replace('"',"") if vid_fallback_modal else ""
                        snap_url_safe_vid      = snap_url_safe

                        media_block = f"""
<div class="media-block video-thumb-block" style="position:relative;background:#000;cursor:pointer"
     id="vwrap_{uid}"
     data-modal-src="{vid_modal_esc}"
     data-modal-fallback="{vid_fallback_modal_esc}">
    <video id="vid_{uid}"
        src="{vid_thumb_esc}"
        style="width:100%;height:100%;object-fit:cover;display:block"
        preload="metadata"
        muted
        playsinline
        onloadedmetadata="this.currentTime=2.5"
        onerror="vidFallback_{uid}(this)">
    </video>
    <div id="vid_overlay_{uid}" style="position:absolute;inset:0;display:flex;align-items:center;
         justify-content:center;pointer-events:none">
        <div style="width:52px;height:52px;border-radius:50%;background:rgba(0,0,0,0.55);
                    display:flex;align-items:center;justify-content:center;
                    box-shadow:0 2px 12px rgba(0,0,0,0.5);border: 1px solid #0b3e55 !important;">
            <svg width="22" height="22" viewBox="0 0 54 54" fill="none">
                <polygon points="18,12 44,27 18,42" fill="white"/>
            </svg>
        </div>
    </div>
    <div style="position:absolute;bottom:7px;right:7px;background:rgba(0,0,0,0.6);
                color:#fff;font-size:10px;font-weight:700;padding:2px 7px;
                border-radius:4px;pointer-events:none">▶ VER VÍDEO</div>
</div>
<script>
(function(){{
    var wrapEl  = document.getElementById('vwrap_{uid}');
    var thumbEl = document.getElementById('vid_{uid}');
    var _tried  = false;
    var snapUrl = '{snap_url_safe_vid}';

    function vidFallback_{uid}(v) {{
        if (!_tried) {{
            _tried = true;
        }} else if (snapUrl && wrapEl) {{
            wrapEl.innerHTML =
                '<div style="position:absolute;inset:0;background:linear-gradient(135deg,#0f1f35,#1a3a5c);'
                + 'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;cursor:pointer"'
                + ' onclick="window.open(\\'' + snapUrl + '\\',\\'_blank\\')">'
                + '<div style="width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,0.15);'
                + 'display:flex;align-items:center;justify-content:center">'
                + '<svg width="22" height="22" viewBox="0 0 54 54" fill="none">'
                + '<polygon points="18,12 44,27 18,42" fill="white"/></svg></div>'
                + '<span style="font-size:11px;color:rgba(255,255,255,0.7);font-weight:600">▶ Ver no Ad Library</span>'
                + '</div>';
        }}
    }}

    window['vidFallback_{uid}'] = vidFallback_{uid};

    if (wrapEl) {{
        wrapEl.addEventListener('click', function() {{
            var modalSrc = wrapEl.getAttribute('data-modal-src');
            var fallback = wrapEl.getAttribute('data-modal-fallback');
            openModal(modalSrc || fallback, snapUrl, true);
        }});
    }}
}})();
</script>"""

                    elif img_primary:
                        all_imgs_js = _json.dumps(images[:4], ensure_ascii=True)
                        main_modal_imgs_js = _json.dumps(
                            [img for img in [
                                images[0] if len(images) > 0 else "",
                                images[2] if len(images) > 2 else "",
                            ] if img],
                            ensure_ascii=True
                        )
                        media_block = f"""
<div class="media-block img-block" id="mwrap_{uid}" style="position:relative;cursor:pointer">
    <img id="mimg_{uid}" src="{img_primary}" loading="lazy"
        style="width:100%;height:100%;object-fit:cover;display:block;"
        onerror="imgFallback_{uid}(this)" />
    <div id="merr_{uid}" style="display:none;width:100%;height:100%;align-items:center;justify-content:center;flex-direction:column;gap:8px;background:#f9fafb;position:absolute;top:0;left:0;">
        <span style="font-size:12px;color:#3a9fd6;font-weight:600;">{'Ver criativo →' if snap_url else 'Sem imagem'}</span>
    </div>
    <div style="position:absolute;top:8px;right:8px;background:#000;border-radius:6px;padding:3px 7px;font-size:11px;color:#fff;font-weight:600;pointer-events:none;">🔍 Ver criativos</div>
</div>
<script>
(function(){{
    var IMGS_{uid} = {all_imgs_js};
    var MAIN_IMGS_{uid} = {main_modal_imgs_js};
    var SNAP_{uid} = '{snap_url.replace("'","").replace('"',"")}';
    var wrap = document.getElementById('mwrap_{uid}');
    if (wrap) {{
        wrap.addEventListener('click', function() {{
            openModalHQ(MAIN_IMGS_{uid}, IMGS_{uid}, SNAP_{uid});
        }});
    }}
    var _srcs_{uid} = {srcs_js};
    var _idx_{uid} = 0;
}})();
function imgFallback_{uid}(img){{
    _idx_{uid}++;
    if(_idx_{uid} < _srcs_{uid}.length){{ img.src = _srcs_{uid}[_idx_{uid}]; }}
    else{{ img.style.display='none'; var e=document.getElementById('merr_{uid}'); if(e) e.style.display='flex'; }}
}}
</script>"""

                    else:
                        _sv = snap_url.replace("'", "")
                        _nm_onclick = f'onclick="openModal(\'\',\'{_sv}\',false)"' if snap_url else ""
                        _nm_color   = "#fff" if snap_url else "#c4c4c4"
                        _nm_label   = "Ver criativo no Ad Library →" if snap_url else "Sem criativo"
                        media_block = (
                            f'<div class="media-block no-media-block" {_nm_onclick} style="{"cursor:pointer;" if snap_url else ""}">'
                            f'<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#d1d5db" stroke-width="1.2">'
                            f'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>'
                            f'<polyline points="21 15 16 10 5 21"/></svg>'
                            f'<span style="font-size:12px;color:{_nm_color};font-weight:600;margin-top:8px;">{_nm_label}</span>'
                            f'</div>'
                        )

                    cta_display = cta_labels.get(cta.upper() if cta else "", cta)
                    is_ativo    = ad.get("ativo", True)
                    card_opacity = "1" if is_ativo else "0.72"

                    status_dot_html = '<div class="status-dot">Ativo</div>' if is_ativo else '<div class="status-dot-inactive">Inativo</div>'
                    baixo_vol_badge = '<span class="badge-small">Baixo volume</span>' if baixo_vol else ""

                    page_avatar_html = (
                        f'<div class="page-avatar" style="overflow:hidden;padding:0">'
                        f'<img src="{page_pic}" style="width:100%;height:100%;object-fit:cover;display:block;border-radius:50%"'
                        f' onerror="this.parentElement.style.background=\'{cor_av}\';this.parentElement.innerHTML=\'{avatar}\'" />'
                        f'</div>'
                    ) if page_pic and page_pic.startswith("http") else f'<div class="page-avatar">{avatar}</div>'

                    data_inicio_html = (
                        f'<div class="meta-row"><span class="meta-label">Veic. iniciada:</span><span>{data_inicio}</span></div>'
                    ) if data_inicio else ""

                    if body_safe and len(body_clean) > 80:
                        short_b = body_safe[:80]
                        rest_b  = body_safe[80:]
                        body_display = (
                            f'<div class="copy-body">{short_b}'
                            f'<span style="color:#9ca3af;font-size:13px" id="ell_{uid}">... </span>'
                            f'<span id="cm_{uid}" style="display:none">{rest_b}</span>'
                            f'<button id="cb_{uid}" onclick="var m=document.getElementById(\'cm_{uid}\');var b=document.getElementById(\'cb_{uid}\');var e=document.getElementById(\'ell_{uid}\');if(m.style.display===\'none\'){{m.style.display=\'inline\';b.textContent=\'ver menos\';if(e)e.style.display=\'none\'}}else{{m.style.display=\'none\';b.textContent=\'ver mais\';if(e)e.style.display=\'inline\'}}" style="background:none;border:none;color:#3a9fd6;font-weight:700;font-size:13px;cursor:pointer;padding:0;margin-left:3px;">ver mais</button></div>'
                        )
                    elif body_safe:
                        body_display = f'<div class="copy-body">{body_safe}</div>'
                    else:
                        body_display = ""

                    card_html = f"""
<div class="card" style="opacity:{card_opacity}" id="card_{uid}">
    <div class="status-bar">
        <div style="display:flex;align-items:center;gap:6px">{status_dot_html}{baixo_vol_badge}</div>
        <div style="display:flex;align-items:center;gap:6px">{'<span class="ad-id">ID: ' + ad_id_short + '</span>' if ad_id_short else ''}</div>
    </div>
    <div class="meta-info">
        {data_inicio_html}
        <div class="meta-row"><span class="meta-label">Plataformas:</span><span id="plat_icons_{uid}" class="plat-icons"></span></div>
        {'<div class="meta-row"><span class="meta-label">Impressões:</span>&nbsp;' + impressoes + '</div>' if impressoes else ''}
    </div>
    <div class="copy-section" style="position:relative">
        {'<div class="dyn-float">Dinâmico</div>' if is_dyn else ''}
        <div class="page-header">{page_avatar_html}<div style="flex:1;min-width:0"><div class="page-name">{ad.get("page_name") or nome}</div><div class="page-sponsored">Patrocinado</div></div></div>
        {body_display}
        {'<div class="copy-title">' + title_safe + '</div>' if title_safe else ''}
        {'<div class="copy-desc">' + desc_safe + '</div>' if desc_safe else ''}
        {'<div class="no-copy">Sem copy disponível.</div>' if not body_safe and not title_safe and not desc_safe else ''}
    </div>
    {media_block}
    <div class="cta-footer">
        <span class="cta-domain">{ad.get("caption") or (snap_url.replace("https://","").split("/")[0] if snap_url else "")}</span>
        <a href="{snap_url or '#'}" target="_blank" class="cta-btn" {'style="pointer-events:none;opacity:0.4"' if not snap_url else ''}>{cta_display or "Ver detalhes"}</a>
    </div>
    <div class="card-footer-btns">
        {'<a class="footer-btn lib" href="' + snap_url + '" target="_blank">Ver no Ad Library</a>' if snap_url else '<span class="footer-btn lib" style="opacity:0.35;cursor:default;pointer-events:none">Sem link</span>'}
        <button class="footer-btn ia-btn" id="ia_ads_btn_{uid}" onclick="analisarAd('{uid}', {j})">{'Reanalisar' if False else 'Analisar anúncio'}</button>
    </div>
</div>
<script>
window.__PLATS_{uid}__ = {plat_js};
{_plat_svg_js(uid)}
</script>"""
                    all_cards_html.append(card_html)

                cards_joined = "\n".join(all_cards_html)
                n_cols = st.session_state.get(col_key, 4)

                _js_modal_hq = """
function openModalHQ(hqImgs, allImgs, snapUrl) {
    var doc = window.parent.document;
    var old = doc.getElementById('ads_modal_overlay');
    if (old) old.remove();
    var overlay = doc.createElement('div');
    overlay.id = 'ads_modal_overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:999999;display:flex;align-items:center;justify-content:center;padding:20px;overflow-y:auto;';
    overlay.onclick = function(e) { if (e.target === overlay) closeModal(); };
    var box = doc.createElement('div');
    box.style.cssText = 'background:transparent;border-radius:16px;overflow:hidden;position:relative;padding:40px 24px 24px;min-width:320px;max-width:min(92vw,900px);';
    var closeBtn = doc.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = 'position:absolute;top:10px;right:12px;background:#0e1e35;border:1.5px solid #22c45e;border-radius:50%;width:34px;height:34px;font-size:17px;color:#22c45e;cursor:pointer;z-index:10;display:flex;align-items:center;justify-content:center;';
    closeBtn.onclick = closeModal;

    if (hqImgs.length <= 1) {
        renderGrid(hqImgs);
    } else {
        var results = [];
        var done    = 0;
        hqImgs.slice(0, 2).forEach(function(src, i) {
            var tmp = new window.parent.Image();
            tmp.onload = function() {
                results.push({ src: src, ratio: this.naturalHeight / (this.naturalWidth || 1) });
                done++;
                if (done === hqImgs.slice(0,2).length) {
                    results.sort(function(a, b) { return a.ratio - b.ratio; });
                    var srcs = results.map(function(r) { return r.src; });
                    var diff = Math.abs(results[0].ratio - results[1].ratio);
                    var maxR = Math.max(results[0].ratio, results[1].ratio) || 1;
                    if ((diff / maxR) < 0.15) { srcs = [srcs[0]]; }
                    renderGrid(srcs);
                }
            };
            tmp.onerror = function() {
                results.push({ src: src, ratio: i === 0 ? 0 : 999 });
                done++;
                if (done === hqImgs.slice(0,2).length) {
                    results.sort(function(a, b) { return a.ratio - b.ratio; });
                    renderGrid(results.map(function(r) { return r.src; }));
                }
            };
            tmp.src = src || '';
        });
    }

    function renderGrid(imgs) {
        var grid = doc.createElement('div');
        grid.style.cssText = 'display:grid;grid-template-columns:' + (imgs.length > 1 ? '1.4fr 1fr' : 'auto') + ';gap:14px;align-items:start;justify-content:center;';
        imgs.forEach(function(src) {
            var cell  = doc.createElement('div');
            cell.style.cssText = 'background:#0a0a0a;border-radius:10px;overflow:hidden;display:flex;flex-direction:column;';
            var imgEl = doc.createElement('img');
            imgEl.style.cssText = 'display:block;width:100%;height:auto;object-fit:contain;max-height:65vh;';
            imgEl.onerror = function() {
                cell.innerHTML = '<div style="color:#555;font-size:12px;font-family:DM Sans,sans-serif;text-align:center;padding:32px;">Imagem não disponível</div>';
            };
            imgEl.src = src || '';
            cell.appendChild(imgEl);
            grid.appendChild(cell);
        });
        box.appendChild(closeBtn);
        box.appendChild(grid);
        overlay.appendChild(box);
        doc.body.appendChild(overlay);
    }

    window.parent.__adsModalEscFn = function(e) { if (e.key === 'Escape') closeModal(); };
    doc.addEventListener('keydown', window.parent.__adsModalEscFn);
}
"""

                components.html(f"""
<!DOCTYPE html><html><head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{background:transparent;font-family:'DM Sans',sans-serif;-webkit-font-smoothing:antialiased;overflow:visible;}}
body{{padding-bottom:4px;min-height:0;}}
.ads-grid{{display:grid;grid-template-columns:repeat({n_cols},1fr);gap:12px;align-items:start;}}
.card{{background:#fff;border:1px solid #fff;border-radius:12px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.status-bar{{display:flex;align-items:center;justify-content:space-between;padding:8px 12px 6px;border-bottom:1px solid #f0f2f5;background:#fafbfc;flex-wrap:wrap;gap:4px;}}
.status-dot{{display:flex;align-items:center;gap:5px;font-size:11px;font-weight:600;color:#1aab40;}}
.status-dot::before{{content:'';width:7px;height:7px;border-radius:50%;background:#1aab40;flex-shrink:0;}}
.status-dot-inactive{{display:flex;align-items:center;gap:5px;font-size:11px;font-weight:600;color:#6b7280;}}
.status-dot-inactive::before{{content:'';width:7px;height:7px;border-radius:50%;background:#d1d5db;flex-shrink:0;}}
.ad-id{{font-size:9px;color:#8a8d91;font-family:monospace;}}
.badge-small{{background:#f3f4f6;color:#6b7280;border:1px solid #e5e7eb;padding:1px 6px;border-radius:20px;font-size:9px;font-weight:600;}}
.meta-info{{padding:6px 12px 8px;border-bottom:1px solid #f0f2f5;background:#fafbfc;}}
.meta-row{{display:flex;align-items:center;gap:5px;font-size:11px;color:#65676b;margin-bottom:4px;flex-wrap:wrap;}}
.meta-row:last-child{{margin-bottom:0;}}
.meta-label{{font-size:11px;color:#65676b;font-weight:700;flex-shrink:0;}}
.plat-icons{{display:flex;align-items:center;gap:2px;flex-wrap:wrap;}}
.plat-badge{{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;}}
.copy-section{{padding:10px 12px 8px;border-bottom:1px solid #f0f2f5;}}
.page-header{{display:flex;align-items:center;gap:8px;margin-bottom:8px;}}
.page-avatar{{width:30px;height:30px;border-radius:50%;background:{cor_av};display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;flex-shrink:0;}}
.page-name{{font-size:12px;font-weight:700;color:#050505;}}
.page-sponsored{{font-size:10px;color:#65676b;}}
.copy-body{{font-size:13px;color:#050505;line-height:1.55;white-space:pre-line;word-break:break-word;min-height:72px;padding-top:10px;border-top:2px solid #f3f4f6;}}
.copy-title{{font-size:13px;font-weight:700;color:#050505;margin-top:10px;padding-top:10px;border-top:2px solid #f3f4f6;}}
.copy-desc{{font-size:11px;color:#65676b;margin-top:2px;}}
.no-copy{{font-size:12px;color:#bcc0c4;font-style:italic;min-height:72px;padding-top:10px;border-top:2px solid #f3f4f6;}}
.dyn-float{{position:absolute;top:10px;right:10px;background:#f0f9ff;color:#0369a1;border:1px solid #bae6fd;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700;}}
.media-block{{width:100%;position:relative;overflow:hidden;background:#000;height:180px;}}
.img-block{{height:230px;background:#f0f2f5;}}
.video-thumb-block{{height:230px;}}
.no-media-block{{height:230px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#7592cc;gap:6px;}}
.cta-footer{{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:#ffffff;border-top:1px solid #e4e6ea;gap:8px;min-height:44px;}}
.cta-domain{{font-size:10px;color:#65676b;text-transform:uppercase;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.cta-btn{{background:#e4e6eb;color:#050505;border:none;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block;flex-shrink:0;}}
.card-btns{{display:grid;grid-template-columns:1fr;border-top:1px solid #e4e6ea;}}
.card-footer-btns{{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #f3f4f6;margin-top:auto;}}
.footer-btn{{padding:10px 6px;display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;font-weight:700;border:none;background:#eff6ff;cursor:pointer;font-family:'DM Sans',sans-serif;transition:background 0.12s;text-decoration:none;color:#275f8d;}}
.footer-btn:hover{{background:#13649a;color:#ffffff !important;}}
.footer-btn.lib{{border-right:1px solid #ffffff;border-radius:0 0 0 10px;}}
.footer-btn.ia-btn{{border-radius:0 0 10px 0;}}
.lib-btn-disabled{{display:flex;align-items:center;justify-content:center;padding:9px 6px;background:#f3f4f6;color:#9ca3af;font-size:11px;font-weight:600;}}
.debug-btn{{display:flex;align-items:center;justify-content:center;padding:9px 6px;background:#fffbeb;color:#92400e;border:none;border-radius:0 0 10px 0;font-size:11px;font-weight:700;cursor:pointer;border-left:1px solid #e4e6ea;}}
.debug-btn:hover{{background:#fef3c7;}}
.debug-block{{border-top:1px solid #fde68a;background:#fffbeb;}}
.debug-header{{display:flex;align-items:center;justify-content:space-between;padding:6px 12px;font-size:11px;font-weight:700;color:#92400e;cursor:pointer;}}
.debug-pre{{font-family:monospace;font-size:10px;color:#374151;padding:8px 12px;overflow-x:auto;white-space:pre;background:#fffbeb;max-height:180px;overflow-y:auto;border-top:1px solid #fde68a;}}
</style>
</head>
<body>
<div class="ads-grid">{cards_joined}</div>
<script>
function openModal(mediaSrc, snapUrl, isVideo) {{
    var doc = window.parent.document;
    var old = doc.getElementById('ads_modal_overlay');
    if (old) old.remove();

    var overlay = doc.createElement('div');
    overlay.id = 'ads_modal_overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:999999;display:flex;align-items:center;justify-content:center;padding:20px;';
    overlay.onclick = function(e) {{ if (e.target === overlay) closeModal(); }};

    var box = doc.createElement('div');
    box.style.cssText = 'background:#111;border-radius:16px;overflow:hidden;position:relative;display:inline-flex;flex-direction:column;align-items:center;max-width:min(88vw,860px);max-height:90vh;';

    var closeBtn = doc.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = 'position:absolute;top:10px;right:12px;background:#0e1e35;border:1px solid #1e395e;border-radius:50%;width:34px;height:34px;font-size:17px;color:#22c45e;cursor:pointer;z-index:10;display:flex;align-items:center;justify-content:center;';
    closeBtn.onclick = closeModal;

    var content = doc.createElement('div');
    content.id = 'ads_modal_content';

    box.appendChild(closeBtn);
    box.appendChild(content);
    overlay.appendChild(box);
    doc.body.appendChild(overlay);

    window.parent.__adsModalEscFn = function(e) {{ if (e.key === 'Escape') closeModal(); }};
    doc.addEventListener('keydown', window.parent.__adsModalEscFn);

    if (isVideo) {{
        var isDirectVideo = mediaSrc && (mediaSrc.indexOf('.mp4') !== -1 || mediaSrc.indexOf('fbcdn') !== -1);
        if (isDirectVideo) {{
            var vid = doc.createElement('video');
            vid.id = 'ads_modal_video';
            vid.src = mediaSrc;
            vid.controls = true;
            vid.autoplay = true;
            vid.playsInline = true;
            vid.style.cssText = 'display:block;max-width:min(84vw,820px);max-height:min(82vh,700px);width:auto;height:auto;border-radius:10px;background:#000;outline:none;';
            vid.onerror = function() {{
                content.innerHTML = '';
                if (snapUrl) {{
                    var wrap = doc.createElement('div');
                    wrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:16px;padding:48px 40px;min-width:280px;font-family:DM Sans,sans-serif;';
                    var btn = doc.createElement('a');
                    btn.href = snapUrl; btn.target = '_blank';
                    btn.style.cssText = 'display:inline-flex;align-items:center;gap:8px;background:#1877F2;color:#fff;padding:14px 28px;border-radius:10px;font-size:15px;font-weight:700;text-decoration:none;';
                    btn.textContent = '↗ Abrir no Ad Library';
                    wrap.appendChild(btn);
                    content.appendChild(wrap);
                }}
            }};
            content.appendChild(vid);
        }} else {{
            var wrap = doc.createElement('div');
            wrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:16px;padding:48px 40px;min-width:280px;font-family:DM Sans,sans-serif;';
            if (snapUrl) {{
                var btn = doc.createElement('a');
                btn.href = snapUrl; btn.target = '_blank';
                btn.style.cssText = 'display:inline-flex;align-items:center;gap:8px;background:#1877F2;color:#fff;padding:14px 28px;border-radius:10px;font-size:15px;font-weight:700;text-decoration:none;';
                btn.textContent = '↗ Abrir vídeo no Ad Library';
                wrap.appendChild(btn);
            }}
            content.appendChild(wrap);
        }}
    }} else {{
        if (!mediaSrc && snapUrl) {{ window.parent.open(snapUrl, '_blank'); closeModal(); return; }}
        if (!mediaSrc) {{ closeModal(); return; }}

        var loading = doc.createElement('div');
        loading.style.cssText = 'padding:40px;color:rgba(255,255,255,0.6);font-size:14px;text-align:center;font-family:DM Sans,sans-serif;';
        loading.textContent = 'Carregando…';
        content.appendChild(loading);

        var tmp = new window.parent.Image();
        tmp.onload = function() {{
            content.innerHTML = '';
            var img = doc.createElement('img');
            img.style.cssText = 'display:block;max-width:min(84vw,820px);max-height:min(82vh,820px);width:auto;height:auto;object-fit:contain;border-radius:10px;';
            img.src = mediaSrc;
            content.appendChild(img);
        }};
        tmp.onerror = function() {{
            content.innerHTML = '';
            if (snapUrl) {{ window.parent.open(snapUrl, '_blank'); closeModal(); }}
            else {{
                var msg = doc.createElement('div');
                msg.style.cssText = 'color:#aaa;font-size:14px;padding:32px;text-align:center;font-family:DM Sans,sans-serif;';
                msg.textContent = 'Imagem não disponível.';
                content.appendChild(msg);
            }}
        }};
        tmp.src = mediaSrc;
    }}
}}

{_js_modal_hq}

function closeModal() {{
    var doc = window.parent.document;
    var vid = doc.getElementById('ads_modal_video');
    if (vid) {{ vid.pause(); vid.src = ''; }}
    var overlay = doc.getElementById('ads_modal_overlay');
    if (overlay) overlay.remove();
    if (window.parent.__adsModalEscFn) {{
        doc.removeEventListener('keydown', window.parent.__adsModalEscFn);
        window.parent.__adsModalEscFn = null;
    }}
}}

document.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeModal(); }});
function toggleDebug(uid) {{
    var el = document.getElementById('debug_' + uid);
    if (!el) return;
    el.style.display = (el.style.display === 'none' || el.style.display === '') ? 'block' : 'none';
    setTimeout(syncHeight, 50);
}}
function analisarAd(uid, j) {{
    var btn = document.getElementById('ia_ads_btn_' + uid);
    if (btn) {{ btn.textContent = 'Analisando…'; btn.style.opacity = '0.6'; btn.style.pointerEvents = 'none'; }}
    var label = 'ia_ind_{sk}_' + j;
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {{
        try {{ if (frames[i].contentWindow === window) {{
            frames[i].style.height = (h + 8) + 'px';
            frames[i].style.minHeight = '0';
            break;
        }} }} catch(e) {{}}
    }}
}}
document.querySelectorAll('img,video').forEach(function(el) {{
    el.addEventListener('load',    function() {{ setTimeout(syncHeight, 30); }});
    el.addEventListener('loadedmetadata', function() {{ setTimeout(syncHeight, 30); }});
    el.addEventListener('error',   function() {{ setTimeout(syncHeight, 30); }});
}});
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 200); setTimeout(syncHeight, 600); setTimeout(syncHeight, 1500);
</script>
</body></html>
""", height=100, scrolling=False)

            # ── ABA: ANÁLISE DE IA ────────────────────────────────────
            else:
                ads_f_ia = ads_list

                chave_ia_geral     = f"ia_ads_geral_{sk}"
                chave_ia_criativos = f"ia_ads_criativos_{sk}"
                chave_ia_copys     = f"ia_ads_copys_{sk}"

                for ch in [chave_ia_geral, chave_ia_criativos, chave_ia_copys]:
                    if ch not in st.session_state:
                        st.session_state[ch] = ""

                for j in range(len(ads_f_ia)):
                    chave_ind = f"ia_ad_result_{sk}_{j}"
                    if chave_ind not in st.session_state:
                        st.session_state[chave_ind] = ""

                # Ghost buttons para análise IA
                ia_ghost_keys = (
                    [f"btn_subtab_{sk}_individuais", f"btn_subtab_{sk}_criativos", f"btn_subtab_{sk}_copys"]
                    + [f"btn_ia_ind_{sk}_{j}" for j in range(len(ads_f_ia))]
                    + [f"btn_ia_geral_{sk}", f"btn_ia_criativos_{sk}", f"btn_ia_copys_{sk}"]
                )
                ia_ghost_css = "\n".join([
                    f"""
                    .st-key-{k} {{
                        position:fixed !important; top:-9999px !important; left:-9999px !important;
                        width:0 !important; height:0 !important; overflow:hidden !important;
                        opacity:0 !important; pointer-events:none !important; display:none !important;
                    }}
                    .stElementContainer:has(.st-key-{k}) {{
                        display:none !important; height:0 !important; min-height:0 !important;
                        max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
                    }}
                    """
                    for k in ia_ghost_keys
                ])
                st.markdown(f"<style>{ia_ghost_css}</style>", unsafe_allow_html=True)

                if f"ads_subtab_{sk}" not in st.session_state:
                    st.session_state[f"ads_subtab_{sk}"] = "individuais"

                for tab_name in ["individuais", "criativos", "copys"]:
                    if st.button(f"subtab_{sk}_{tab_name}", key=f"btn_subtab_{sk}_{tab_name}"):
                        st.session_state[f"ads_subtab_{sk}"] = tab_name
                        st.rerun()

                if st.button(f"ia_geral_{sk}", key=f"btn_ia_geral_{sk}"):
                    if gemini_model is None:
                        st.session_state[chave_ia_geral] = "Configure GEMINI_API_KEY nos secrets."
                    else:
                        resumo = "\n".join([
                            f"- [{a['formato']}] Título: {_truncar(a.get('title',''),60) or '—'} | Copy: {_truncar(a.get('body',''),100) or '—'}"
                            for a in ads_f_ia[:15]
                        ])
                        n_vid = sum(1 for a in ads_f_ia if "Vídeo" in a["formato"])
                        n_img = sum(1 for a in ads_f_ia if "Imagem" in a["formato"])
                        n_car = sum(1 for a in ads_f_ia if "Carrossel" in a["formato"])
                        n_dyn = sum(1 for a in ads_f_ia if a.get("is_dynamic"))
                        with st.spinner("Analisando anúncios…"):
                            try:
                                resp = gemini_model.generate_content(f"""Você é especialista em mídia paga e marketing digital.
Analise os anúncios de "{nome}" e gere um relatório estratégico completo em português.

Empresa: {nome} | Total: {len(ads_f_ia)} | {n_img} imagens | {n_vid} vídeos | {n_car} carrosseis | {n_dyn} dinâmicos

Amostra dos anúncios:
{resumo}

---
### 🎯 Estratégia de Mídia
### ✍️ Padrões de Copy e Mensagem
### 🎨 Análise de Formatos
### 📊 Estimativa de Investimento e Alcance
### ⚠️ Pontos de Atenção
### 💡 Oportunidades Competitivas (3 ações concretas)""")
                                st.session_state[chave_ia_geral] = resp.text
                                st.rerun()
                            except Exception as ex:
                                st.session_state[chave_ia_geral] = f"Erro: {ex}"
                                st.rerun()

                if st.button(f"ia_criativos_{sk}", key=f"btn_ia_criativos_{sk}"):
                    if gemini_model is None:
                        st.session_state[chave_ia_criativos] = "Configure GEMINI_API_KEY nos secrets."
                    else:
                        resumo_criativos = "\n".join([
                            f"- [{a['formato']}] Plataformas: {', '.join(a.get('plataformas',[]))} | Título: {_truncar(a.get('title',''),60) or '—'}"
                            for a in ads_f_ia[:15]
                        ])
                        n_vid = sum(1 for a in ads_f_ia if "Vídeo" in a["formato"])
                        n_img = sum(1 for a in ads_f_ia if "Imagem" in a["formato"])
                        n_car = sum(1 for a in ads_f_ia if "Carrossel" in a["formato"])
                        with st.spinner("Analisando criativos…"):
                            try:
                                resp = gemini_model.generate_content(f"""Você é especialista em design e criação de anúncios digitais.
Analise os CRIATIVOS (formatos visuais) dos anúncios de "{nome}" em português.

Empresa: {nome} | {n_img} imagens | {n_vid} vídeos | {n_car} carrosseis

Dados dos criativos:
{resumo_criativos}

---
### 🎨 Estilo Visual Predominante
### 📱 Mix de Formatos e Plataformas
### 🏆 Formatos com Melhor Potencial
### ✅ Pontos Fortes Visuais (3 pontos)
### ⚠️ O que Melhorar (2 pontos)
### 💡 Recomendações de Criativo (2 ações concretas)""")
                                st.session_state[chave_ia_criativos] = resp.text
                                st.rerun()
                            except Exception as ex:
                                st.session_state[chave_ia_criativos] = f"Erro: {ex}"
                                st.rerun()

                if st.button(f"ia_copys_{sk}", key=f"btn_ia_copys_{sk}"):
                    if gemini_model is None:
                        st.session_state[chave_ia_copys] = "Configure GEMINI_API_KEY nos secrets."
                    else:
                        todas_copies = "\n".join([
                            f"- Título: {_truncar(a.get('title',''),80) or '—'} | Body: {_truncar(a.get('body',''),120) or '—'} | CTA: {a.get('cta','') or '—'}"
                            for a in ads_f_ia[:20]
                        ])
                        with st.spinner("Analisando copys…"):
                            try:
                                resp = gemini_model.generate_content(f"""Você é especialista em copywriting e marketing de resposta direta.
Analise as COPIES (textos) dos anúncios de "{nome}" em português.

Empresa: {nome} | {len(ads_f_ia)} anúncios analisados

Copies coletadas:
{todas_copies}

---
### ✍️ Tom de Voz e Personalidade
### 🎯 Principais Promessas e Argumentos
### 📣 Uso de CTAs (Call-to-Action)
### 🔑 Palavras e Frases Recorrentes
### ✅ Pontos Fortes nas Copies (3 pontos)
### ⚠️ O que Melhorar (2 pontos)
### 💡 Sugestões de Copy (2 exemplos concretos)""")
                                st.session_state[chave_ia_copys] = resp.text
                                st.rerun()
                            except Exception as ex:
                                st.session_state[chave_ia_copys] = f"Erro: {ex}"
                                st.rerun()

                for j, ad in enumerate(ads_f_ia):
                    if st.button(f"ia_ind_{sk}_{j}", key=f"btn_ia_ind_{sk}_{j}"):
                        chave_ind = f"ia_ad_result_{sk}_{j}"
                        if gemini_model is None:
                            st.session_state[chave_ind] = "Configure GEMINI_API_KEY nos secrets."
                        else:
                            with st.spinner(f"Analisando anúncio {j+1}…"):
                                try:
                                    resp = gemini_model.generate_content(f"""Você é especialista em mídia paga e copywriting.
Analise este anúncio específico e dê feedback estratégico em português.

Empresa: {nome}
Formato: {ad.get("formato","")}
Plataformas: {", ".join(ad.get("plataformas") or [])}
Veiculação: {ad.get("data_inicio","")}
Título: {ad.get("title","")}
Copy: {ad.get("body","")}
Descrição: {ad.get("description","")}
CTA: {ad.get("cta","")}

### 🎯 Objetivo do Anúncio
### ✍️ Análise de Copy
### 🎨 Análise de Formato e Criativo
### 💡 Sugestões de Melhoria (2 ações concretas)""")
                                    st.session_state[chave_ind] = resp.text
                                    st.rerun()
                                except Exception as ex:
                                    st.session_state[chave_ind] = f"Erro: {ex}"
                                    st.rerun()

                subtab_atual = st.session_state.get(f"ads_subtab_{sk}", "individuais")

                ind_cards_data = []
                for j, ad in enumerate(ads_f_ia):
                    chave_ind = f"ia_ad_result_{sk}_{j}"
                    resultado = st.session_state.get(chave_ind, "")
                    img_src = ""
                    if ad.get("images_b64"):
                        img_src = ad["images_b64"][0]
                    elif ad.get("images"):
                        img_src = ad["images"][0]
                    resultado_html = resultado.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>") if resultado else ""
                    ind_cards_data.append({
                        "j": j,
                        "formato": ad.get("formato",""),
                        "title": _truncar(ad.get("title",""), 80),
                        "body": _truncar(ad.get("body",""), 120),
                        "cta": ad.get("cta",""),
                        "data_inicio": ad.get("data_inicio",""),
                        "plataformas": ", ".join(ad.get("plataformas") or []),
                        "img_src": img_src,
                        "resultado": resultado_html,
                        "ativo": ad.get("ativo", True),
                    })

                ind_cards_json = _json.dumps(ind_cards_data, ensure_ascii=False)

                geral_html     = st.session_state.get(chave_ia_geral, "").replace("\n","<br>")
                criativos_html = st.session_state.get(chave_ia_criativos, "").replace("\n","<br>")
                copys_html     = st.session_state.get(chave_ia_copys, "").replace("\n","<br>")

                n_anuncios = len(ads_f_ia)
                n_vid2 = sum(1 for a in ads_f_ia if "Vídeo" in a["formato"])
                n_img2 = sum(1 for a in ads_f_ia if "Imagem" in a["formato"])
                n_car2 = sum(1 for a in ads_f_ia if "Carrossel" in a["formato"])

                components.html(f"""
<!DOCTYPE html><html><head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; -webkit-font-smoothing:antialiased; overflow:visible; }}
body {{ padding-bottom:8px; }}
.subtabs-wrap {{ background:#fff; border:1px solid #e5e7eb; border-top:none; border-bottom:none; padding:0 16px; display:flex; gap:0; border-bottom:1px solid #e5e7eb; }}
.subtab {{ padding:12px 20px; font-size:13px; font-weight:700; color:#9ca3af; background:transparent; border:none; cursor:pointer; border-bottom:3px solid transparent; margin-bottom:-1px; font-family:'DM Sans',sans-serif; transition:all 0.15s; white-space:nowrap; }}
.subtab:hover {{ color:#374151; }}
.subtab.active {{ color:#1a2e4a; border-bottom:3px solid #3a9fd6; }}
.panel {{ display:none; padding:20px 16px; background:#fff; border:1px solid #e5e7eb; border-top:none; border-radius:0 0 12px 12px; }}
.panel.active {{ display:block; }}
.stats-mini {{ display:flex; gap:10px; margin-bottom:20px; flex-wrap:wrap; }}
.stat-mini {{ flex:1; min-width:80px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:10px; padding:10px 14px; text-align:center; }}
.stat-mini-num {{ font-size:20px; font-weight:800; color:#111827; }}
.stat-mini-lbl {{ font-size:11px; color:#6b7280; font-weight:600; margin-top:2px; }}
.ind-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:14px; }}
.ind-card {{ background:#f9fafb; border:1px solid #e5e7eb; border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }}
.ind-card-top {{ display:flex; gap:12px; padding:14px; border-bottom:1px solid #f3f4f6; }}
.ind-thumb {{ width:72px; height:72px; border-radius:8px; object-fit:cover; border:1px solid #e5e7eb; flex-shrink:0; background:#f3f4f6; display:flex; align-items:center; justify-content:center; font-size:20px; overflow:hidden; }}
.ind-thumb img {{ width:100%; height:100%; object-fit:cover; border-radius:8px; }}
.ind-info {{ flex:1; min-width:0; }}
.ind-fmt {{ display:inline-block; background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; padding:2px 8px; border-radius:20px; font-size:11px; font-weight:700; margin-bottom:5px; }}
.ind-fmt-inativo {{ display:inline-block; background:#f3f4f6; color:#6b7280; border:1px solid #e5e7eb; padding:2px 8px; border-radius:20px; font-size:11px; font-weight:700; margin-bottom:5px; margin-left:4px; }}
.ind-title {{ font-size:13px; font-weight:700; color:#111827; margin-bottom:3px; line-height:1.4; }}
.ind-body {{ font-size:12px; color:#6b7280; line-height:1.5; }}
.ind-meta {{ font-size:11px; color:#9ca3af; margin-top:4px; }}
.ind-btn {{ width:100%; padding:10px 0; border:none; border-top:1px solid #e5e7eb; background:#fff; font-size:13px; font-weight:700; color:#1d4ed8; cursor:pointer; font-family:'DM Sans',sans-serif; display:flex; align-items:center; justify-content:center; gap:6px; transition:background 0.12s; }}
.ind-btn:hover {{ background:#eff6ff; }}
.ind-result {{ background:#f0fdf4; border-top:1px solid #86efac; padding:12px 14px; font-size:13px; color:#374151; line-height:1.7; max-height:220px; overflow-y:auto; }}
.ind-result-header {{ font-size:11px; font-weight:800; color:#15803d; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px; }}
.analise-wrap {{ background:#f9fafb; border:1px solid #e5e7eb; border-radius:10px; overflow:hidden; }}
.analise-header {{ padding:14px 16px; font-size:13px; font-weight:800; color:#1a2e4a; text-transform:uppercase; letter-spacing:0.3px; border-bottom:1px solid #e5e7eb; background:#fff; display:flex; align-items:center; justify-content:space-between; }}
.analise-body {{ padding:18px 16px; font-size:14px; color:#374151; line-height:1.75; background:#fff; min-height:80px; }}
.analise-empty {{ text-align:center; color:#9ca3af; font-size:14px; padding:36px 24px; background:#fff; }}
.analise-footer {{ padding:14px 16px; border-top:1px solid #f3f4f6; background:#f9fafb; }}
.btn-gerar {{ padding:10px 24px; border:1px solid #3a9fd6; border-radius:8px; background:#eff6ff; font-size:14px; font-weight:700; color:#1d4ed8; cursor:pointer; font-family:'DM Sans',sans-serif; transition:background 0.15s; }}
.btn-gerar:hover {{ background:#dbeafe; }}
</style>
</head>
<body>
<div class="subtabs-wrap">
    <button class="subtab {'active' if subtab_atual == 'individuais' else ''}" onclick="showSubtab('individuais',this)">📋 Anúncios Individuais</button>
    <button class="subtab {'active' if subtab_atual == 'criativos' else ''}" onclick="showSubtab('criativos',this)">🎨 Criativos</button>
    <button class="subtab {'active' if subtab_atual == 'copys' else ''}" onclick="showSubtab('copys',this)">✍️ Copys</button>
</div>
<div id="panel-individuais" class="panel {'active' if subtab_atual == 'individuais' else ''}">
    <div class="stats-mini">
        <div class="stat-mini"><div class="stat-mini-num">{n_anuncios}</div><div class="stat-mini-lbl">Total</div></div>
        <div class="stat-mini"><div class="stat-mini-num">{n_img2}</div><div class="stat-mini-lbl">Imagens</div></div>
        <div class="stat-mini"><div class="stat-mini-num">{n_vid2}</div><div class="stat-mini-lbl">Vídeos</div></div>
        <div class="stat-mini"><div class="stat-mini-num">{n_car2}</div><div class="stat-mini-lbl">Carrosseis</div></div>
    </div>
    <div class="ind-grid" id="ind-grid"></div>
</div>
<div id="panel-criativos" class="panel {'active' if subtab_atual == 'criativos' else ''}">
    <div class="analise-wrap">
        <div class="analise-header"><span>🎨 Análise de Criativos</span></div>
        <div class="analise-body">
            {'<div>' + criativos_html + '</div>' if criativos_html else '<div class="analise-empty">Clique em <b>Gerar Análise</b> para analisar os criativos dos anúncios.</div>'}
        </div>
        <div class="analise-footer">
            <button class="btn-gerar" onclick="triggerGlobal('ia_criativos_{sk}')">
                {'🔄 Nova Análise' if criativos_html else '⚡ Gerar Análise de Criativos'}
            </button>
        </div>
    </div>
</div>
<div id="panel-copys" class="panel {'active' if subtab_atual == 'copys' else ''}">
    <div class="analise-wrap">
        <div class="analise-header"><span>✍️ Análise de Copys</span></div>
        <div class="analise-body">
            {'<div>' + copys_html + '</div>' if copys_html else '<div class="analise-empty">Clique em <b>Gerar Análise</b> para analisar as copies dos anúncios.</div>'}
        </div>
        <div class="analise-footer">
            <button class="btn-gerar" onclick="triggerGlobal('ia_copys_{sk}')">
                {'🔄 Nova Análise' if copys_html else '⚡ Gerar Análise de Copys'}
            </button>
        </div>
    </div>
</div>
<script>
var IND_CARDS = {ind_cards_json};
function buildIndGrid() {{
    var grid = document.getElementById('ind-grid');
    if (!grid) return;
    grid.innerHTML = '';
    IND_CARDS.forEach(function(d) {{
        var card = document.createElement('div');
        card.className = 'ind-card';
        card.id = 'ind_card_' + d.j;
        var thumbHtml = d.img_src
            ? '<img src="' + d.img_src + '" onerror="this.outerHTML=\'<span>📷</span>\'" />'
            : (d.formato === 'Vídeo' ? '<span>🎬</span>' : '<span>📷</span>');
        var statusBadge = d.ativo ? '' : '<span class="ind-fmt-inativo">Inativo</span>';
        card.innerHTML =
            '<div class="ind-card-top">'
            + '<div class="ind-thumb">' + thumbHtml + '</div>'
            + '<div class="ind-info">'
            + '<span class="ind-fmt">' + (d.formato || 'Anúncio') + '</span>' + statusBadge
            + '<div class="ind-title">' + (d.title || '—') + '</div>'
            + '<div class="ind-body">' + (d.body || '—') + '</div>'
            + '<div class="ind-meta">'
            + (d.data_inicio ? '🕒 ' + d.data_inicio + ' &nbsp;' : '')
            + (d.plataformas ? '📱 ' + d.plataformas : '')
            + '</div></div></div>';
        if (d.resultado) {{
            var res = document.createElement('div');
            res.className = 'ind-result';
            res.innerHTML = '<div class="ind-result-header">Análise IA</div>' + d.resultado;
            card.appendChild(res);
        }}
        var btn = document.createElement('button');
        btn.className = 'ind-btn';
        btn.id = 'ind_btn_' + d.j;
        btn.innerHTML = d.resultado ? '🔄 Reanalisar' : '⚡ Analisar este anúncio';
        btn.onclick = (function(idx) {{
            return function() {{
                var b = document.getElementById('ind_btn_' + idx);
                if (b) {{ b.textContent = 'Analisando…'; b.style.color = '#9ca3af'; }}
                triggerGlobal('ia_ind_{sk}_' + idx);
            }};
        }})(d.j);
        card.appendChild(btn);
        grid.appendChild(card);
    }});
    syncHeight();
}}
function showSubtab(name, el) {{
    document.querySelectorAll('.subtab').forEach(function(t) {{ t.classList.remove('active'); }});
    document.querySelectorAll('.panel').forEach(function(p) {{ p.classList.remove('active'); }});
    document.getElementById('panel-' + name).classList.add('active');
    el.classList.add('active');
    triggerGlobal('subtab_{sk}_' + name);
    setTimeout(syncHeight, 100);
}}
function triggerGlobal(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {{
        try {{ if (frames[i].contentWindow === window) {{
            frames[i].style.height = (h + 20) + 'px';
            frames[i].style.minHeight = '0';
            break;
        }} }} catch(e) {{}}
    }}
}}
buildIndGrid();
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 200); setTimeout(syncHeight, 600); setTimeout(syncHeight, 1500);
</script>
</body></html>
""", height=600, scrolling=False)

        # ── Renderiza empresa da aba ativa ───────────────────────────

        empresas_com_dados = [
            e for e in empresas_configuradas
            if e["nome"] in st.session_state.ads_cache or e["nome"] in st.session_state.ads_erro
        ]

        if not empresas_com_dados:
            st.markdown("""
            <div style='background:#fff;border:1px dashed #d1d5db;border-radius:14px;padding:48px 32px;text-align:center;margin-top:8px'>
                <div style='font-size:32px;margin-bottom:12px'>📢</div>
                <div style='font-size:16px;font-weight:600;color:#374151;margin-bottom:6px'>Nenhum dado carregado ainda</div>
                <div style='font-size:14px;color:#9ca3af'>Configure as páginas e clique em <b>Buscar / Atualizar</b>.</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            aba_idx = min(st.session_state.get("ads_aba_ativa", 0), len(empresas_com_dados) - 1)
            render_ads_empresa(empresas_com_dados[aba_idx])

    # ══════════════════════════════════════════════════════════════════
    # ABA: ANÁLISE DE IA (resumo comparativo)
    # ══════════════════════════════════════════════════════════════════
    elif main_tab == "analise":

        if not st.session_state.ads_cache:
            st.info("Busque anúncios primeiro na aba **Empresas configuradas** para ver análises aqui.")
            st.stop()

        chave_comp = "ia_ads_comparativo"
        if chave_comp not in st.session_state:
            st.session_state[chave_comp] = ""

        ghost_comp_css = """
        .st-key-btn_ia_comp_geral {
            position:fixed !important; top:-9999px !important; left:-9999px !important;
            width:0 !important; height:0 !important; overflow:hidden !important;
            opacity:0 !important; pointer-events:none !important; display:none !important;
        }
        .stElementContainer:has(.st-key-btn_ia_comp_geral) {
            display:none !important; height:0 !important; min-height:0 !important;
            max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
        }
        """
        st.markdown(f"<style>{ghost_comp_css}</style>", unsafe_allow_html=True)

        if st.button("ia_comparativo", key="btn_ia_comp_geral"):
            if gemini_model is None:
                st.session_state[chave_comp] = "Configure GEMINI_API_KEY nos secrets."
            else:
                resumos = []
                for ck, entry in st.session_state.ads_cache.items():
                    ads_data = entry.get("data", [])
                    ativos = [a for a in ads_data if a.get("ativo", True)]
                    n_vid = sum(1 for a in ativos if "Vídeo" in a.get("formato",""))
                    n_img = sum(1 for a in ativos if "Imagem" in a.get("formato",""))
                    n_car = sum(1 for a in ativos if "Carrossel" in a.get("formato",""))
                    sample = "\n".join([
                        f"  - [{a.get('formato','')}] {_truncar(a.get('title','') or a.get('body',''),80)}"
                        for a in ativos[:5]
                    ])
                    resumos.append(f"""
Empresa: {ck} | {len(ativos)} anúncios ativos | {n_img} imagens | {n_vid} vídeos | {n_car} carrosseis
Amostra:
{sample}
""")
                with st.spinner("Gerando análise comparativa…"):
                    try:
                        resp = gemini_model.generate_content(f"""Você é especialista em inteligência competitiva e mídia paga.
Compare os anúncios das empresas abaixo e gere uma análise competitiva completa em português.

{'---'.join(resumos)}

---
### 🏆 Ranking de Presença Digital
### 🎯 Estratégias Comparadas
### ✍️ Tom de Voz e Mensagens
### 🎨 Mix de Formatos
### ⚔️ Análise Competitiva
### 💡 Recomendações Estratégicas (3 ações concretas)""")
                        st.session_state[chave_comp] = resp.text
                        st.rerun()
                    except Exception as ex:
                        st.session_state[chave_comp] = f"Erro: {ex}"
                        st.rerun()

        comp_html = st.session_state.get(chave_comp, "").replace("\n","<br>")

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:visible; }}
body {{ padding-bottom:8px; }}
.wrap {{ background:#fff; border:1px solid #e5e7eb; border-radius:14px; overflow:hidden; }}
.hdr {{ padding:18px 22px; border-bottom:1px solid #e5e7eb; display:flex; align-items:center; justify-content:space-between; }}
.hdr-title {{ font-size:16px; font-weight:800; color:#1a2e4a; }}
.hdr-sub {{ font-size:13px; color:#9ca3af; }}
.body {{ padding:22px; font-size:14px; color:#374151; line-height:1.8; min-height:80px; }}
.empty {{ text-align:center; color:#9ca3af; font-size:14px; padding:60px 24px; }}
.footer {{ padding:16px 22px; border-top:1px solid #f3f4f6; background:#f9fafb; }}
.btn-gerar {{
    display:inline-flex; align-items:center; gap:8px;
    padding:12px 28px; border:none; border-radius:10px;
    background:#0e2a47; font-size:15px; font-weight:700; color:#fff;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:background 0.15s;
}}
.btn-gerar:hover {{ background:#1a3a5c; }}
</style>
<div class="wrap">
    <div class="hdr">
        <div>
            <div class="hdr-title">✨ Análise Competitiva de Anúncios</div>
            <div class="hdr-sub">Comparativo inteligente de todas as empresas configuradas</div>
        </div>
    </div>
    <div class="body">
        {'<div>' + comp_html + '</div>' if comp_html else '<div class="empty">Clique em <b>Gerar Análise Comparativa</b> abaixo para comparar os anúncios de todas as empresas com IA.</div>'}
    </div>
    <div class="footer">
        <button class="btn-gerar" onclick="triggerBtn('ia_comparativo')">
            {'🔄 Regerar Análise' if comp_html else '⚡ Gerar Análise Comparativa'}
        </button>
    </div>
</div>
<script>
function triggerBtn(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {{
        try {{ if (frames[i].contentWindow === window) {{
            frames[i].style.height = (h + 12) + 'px'; break;
        }} }} catch(e) {{}}
    }}
}}
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 200); setTimeout(syncHeight, 600);
</script>
""", height=200, scrolling=False)

# ---------------------------------------------------
# PAGINA - INSIGHTS
# ---------------------------------------------------

elif st.session_state.pagina == "insights":

    periodo, data_inicio = cabecalho_analise("✨ Insights", "Estratégias geradas por IA para vencer a concorrência")
    concorrentes = st.session_state.dados["concorrentes"]

    if concorrentes:
        col_sel, col_btn = st.columns([4, 2])
        with col_sel:
            target = st.selectbox(
                "Gerar estratégia contra:",
                [c["nome"] for c in concorrentes],
                label_visibility="collapsed"
            )
        with col_btn:
            gerar = st.button("⚡ Gerar Insight", type="primary", use_container_width=True)

        if gerar:
            with st.spinner("Gerando insight..."):
                resposta = consultar_ia(f"Gere um battle card focado em vencer o concorrente {target} considerando o período: {periodo}.")
                st.markdown(resposta)
    else:
        st.info("Adicione concorrentes para gerar insights estratégicos.")

# ---------------------------------------------------
# PAGINA - REDES SOCIAIS
# ---------------------------------------------------

elif st.session_state.pagina == "redes":

    st.markdown("""
    <style>
    [data-testid="stEmpty"] > div {
        position: fixed !important;
        inset: 0 !important;
        background: rgba(0,0,0,0.7) !important;
        z-index: 999999 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 24px !important;
    }
    [data-testid="stEmpty"] > div > div {
        width: min(95vw, 560px) !important;
    }
    </style>
    """, unsafe_allow_html=True)

 
    import datetime
    import json
 
    emp = st.session_state.dados["minha_empresa"]
    concorrentes = st.session_state.dados["concorrentes"]
 
    # ── Cabeçalho ──────────────────────────────────────────────────
    col1, col2, col3 = st.columns([6, 2, 3])
 
    with col1:
        components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@font-face {
    font-family: 'Animo';
    src: url('https://raw.githubusercontent.com/thiagomktsantos/marketylics/63946b2d891db6b45cc75a45550b7aa5fe67244a/utils/Animo-font.otf') format('opentype');
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: transparent; overflow: hidden; }
.titulo {
    font-family: 'Animo', 'DM Sans', sans-serif;
    font-size: 32px; font-weight: 700; color: #1a2e4a;
    text-transform: uppercase; margin: 0 0 6px 0; letter-spacing: 0.5px;
}
.sub { font-family: 'DM Sans', sans-serif; font-size: 14px; color: #6b7280; }
</style>
<div class="titulo">Redes Sociais</div>
<div class="sub">Acompanhe e compare métricas do Instagram dos seus concorrentes em tempo real.</div>
""", height=65)
 
    with col2:
        st.markdown("""
    <style>
    .st-key-_redes_ghost_tab_perfis_,
    .st-key-_redes_ghost_tab_analise_ {
        display: none !important;
    }
    .stElementContainer:has(.st-key-_redes_ghost_tab_perfis_),
    .stElementContainer:has(.st-key-_redes_ghost_tab_analise_) {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)
 
    with col3:
        coletar = st.button(
            "Coletar dados",
            type="primary",
            use_container_width=True,
        )
        ultima_coleta = st.session_state.metricas_redes.get("ultima_coleta", "")

        import json as _jr
        d = st.session_state.metricas_redes.get("dados", [])
        _djs = _jr.dumps(d, ensure_ascii=False).replace("</", "<\\/").replace("\\", "\\\\").replace("'", "\\'") if ultima_coleta else "[]"
        fn = f'dados_redes_{ultima_coleta.replace("/","_").replace(" ","_").replace(":","")}.json' if ultima_coleta else ""

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.row-coleta {{
    display:{'flex' if ultima_coleta else 'none'};
    align-items:center; justify-content:center; gap:6px;
    font-size:13px; color:#6b7280; font-family:'DM Sans',sans-serif;
    flex-wrap:nowrap; white-space:nowrap;
}}
.link-btn {{
    font-size:11px; color:#6b7280;
    cursor:pointer; text-underline-offset:3px;
    background:none; border:none; padding:0;
    font-family:'DM Sans',sans-serif;
}}
.link-btn:hover {{ text-decoration:underline; color:#374151; }}
.sep {{ color:#d1d5db; font-size:12px; }}
.clear-btn {{
    font-size:11px; color:#6b7280;
    cursor:pointer; background:none; border:none; padding:0;
    font-family:'DM Sans',sans-serif; text-underline-offset:3px;
}}
.clear-btn:hover {{ text-decoration:underline; color:#374151;  }}
</style>
<div class="row-coleta">
    <button class="link-btn" onclick="abrirModal()">🕒 Última coleta: <b>{ultima_coleta}</b></button>
    <span class="sep">|</span>
    <button class="clear-btn" onclick="triggerLimpar()">Limpar cache</button>
</div>
<script>
var DADOS_JSON = '{_djs}';
var FILENAME   = '{fn}';
var ULTIMA     = '{ultima_coleta}';

function triggerLimpar() {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === 'limpar_cache_redes') {{ b.click(); return; }}
    }}
}}

function abrirModal() {{
    window.fechar = function() {{
        var o = window.parent.document.getElementById('raw_modal_overlay');
        if (o) o.remove();
        if (window.parent.__rawEsc) {{
            window.parent.document.removeEventListener('keydown', window.parent.__rawEsc);
            window.parent.__rawEsc = null;
        }}
    }};
    var doc = window.parent.document;
    var old = doc.getElementById('raw_modal_overlay');
    if (old) old.remove();
    var D;
    try {{ D = JSON.parse(DADOS_JSON); }} catch(e) {{ D = []; }}
    var Dstr = JSON.stringify(D, null, 2);
    var ov = doc.createElement('div');
    ov.id = 'raw_modal_overlay';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:999999;display:flex;align-items:center;justify-content:center;padding:24px;';
    ov.onclick = function(e) {{ if(e.target===ov) fechar(); }};
    var box = doc.createElement('div');
    box.style.cssText = 'background:#0d1117;border-radius:16px;overflow:hidden;position:relative;width:min(95vw,1100px);max-height:88vh;display:flex;flex-direction:column;border:1px solid #1e395e;';
    var hdr = doc.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:16px 24px;border-bottom:1px solid #21262d;background:#0e1e35;flex-shrink:0;';
    hdr.innerHTML =
        '<div><div style="font-size:15px;font-weight:700;color:#e6edf3;font-family:DM Sans,sans-serif;">📦 Dados brutos das Redes</div>'
        + '<div style="font-size:12px;color:#8b949e;margin-top:2px;">Última coleta: ' + ULTIMA + '</div></div>'
        + '<div style="display:flex;gap:10px;">'
        + '<button id="raw_copy_btn" style="padding:7px 16px;border:1px solid #1e395e;border-radius:8px;background:#0e1e35;color:#22c45e;font-size:13px;font-weight:600;cursor:pointer;">📋 Copiar</button>'
        + '<button id="raw_down_btn" style="padding:7px 16px;border:1px solid #1e395e;border-radius:8px;background:#0e1e35;color:#22c45e;font-size:13px;font-weight:600;cursor:pointer;">⬇️ Baixar JSON</button>'
        + '<button id="raw_close_btn" style="width:34px;height:34px;border-radius:50%;background:#0e1e35;border:1px solid #1e395e;color:#22c45e;font-size:18px;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center;">✕</button>'
        + '</div>';
    var pre = doc.createElement('pre');
    pre.style.cssText = 'flex:1;overflow-y:auto;overflow-x:auto;padding:20px 24px;font-size:12.5px;line-height:1.7;color:#e6edf3;font-family:monospace;background:#0d1117;margin:0;white-space:pre;max-height:calc(88vh - 80px);';
    pre.textContent = Dstr;
    box.appendChild(hdr);
    box.appendChild(pre);
    ov.appendChild(box);
    doc.body.appendChild(ov);

    doc.getElementById('raw_close_btn').addEventListener('click', window.fechar);
    doc.getElementById('raw_copy_btn').addEventListener('click', function() {{
        var b = doc.getElementById('raw_copy_btn');
        try {{
            var ta = doc.createElement('textarea');
            ta.value = Dstr;
            ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;';
            doc.body.appendChild(ta);
            ta.focus();
            ta.select();
            doc.execCommand('copy');
            doc.body.removeChild(ta);
            b.textContent = '✅ Copiado!';
            setTimeout(function() {{ b.textContent = '📋 Copiar'; }}, 2000);
        }} catch(e) {{
            b.textContent = '❌ Erro';
            setTimeout(function() {{ b.textContent = '📋 Copiar'; }}, 2000);
        }}
    }});
    doc.getElementById('raw_down_btn').addEventListener('click', function() {{
        var a = doc.createElement('a');
        a.href = URL.createObjectURL(new Blob([Dstr], {{type:'application/json'}}));
        a.download = FILENAME;
        a.click();
    }});

    window.parent.__rawEsc = function(e) {{ if(e.key==='Escape') window.fechar(); }};
    doc.addEventListener('keydown', window.parent.__rawEsc);
}}

(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '{"28px" if ultima_coleta else "0px"}';
            iframes[i].style.marginTop = '-8px';
            break;
        }} }} catch(e) {{}}
    }}
}})();
</script>
""", height=28, scrolling=False)

    # ── Ghost button limpar cache — FORA do with col3 ──────────────
    if "redes_confirmar_limpar" not in st.session_state:
        st.session_state.redes_confirmar_limpar = False

    ghost_limpar_key = "btn_limpar_cache_redes"
    st.markdown(f"""
    <style>
    .st-key-{ghost_limpar_key} {{
        position:fixed !important; top:-9999px !important; left:-9999px !important;
        width:0 !important; height:0 !important; overflow:hidden !important;
        opacity:0 !important; pointer-events:none !important; display:none !important;
    }}
    .stElementContainer:has(.st-key-{ghost_limpar_key}) {{
        display:none !important; height:0 !important; min-height:0 !important;
        max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    if st.button("limpar_cache_redes", key=ghost_limpar_key):
        st.session_state.redes_confirmar_limpar = True
        st.rerun()

    if st.session_state.get("redes_confirmar_limpar"):

        # Ghost buttons escondidos que o modal HTML vai acionar
        st.markdown("""
        <style>
        .st-key-btn_cancelar_limpar_redes,
        .st-key-btn_confirmar_limpar_redes {
            position: fixed !important; top: -9999px !important; left: -9999px !important;
            width: 0 !important; height: 0 !important; overflow: hidden !important;
            opacity: 0 !important; pointer-events: none !important; display: none !important;
        }
        .stElementContainer:has(.st-key-btn_cancelar_limpar_redes),
        .stElementContainer:has(.st-key-btn_confirmar_limpar_redes) {
            display: none !important;
        }
        </style>
        """, unsafe_allow_html=True)

        if st.button("Cancelar", key="btn_cancelar_limpar_redes"):
            st.session_state.redes_confirmar_limpar = False
            st.rerun()

        if st.button("Sim, apagar dados", key="btn_confirmar_limpar_redes"):
            st.session_state.redes_confirmar_limpar = False
            st.session_state.metricas_redes = {}
            try:
                supabase.table("ci_dados").update({"metricas_redes": {}}).eq("user_id", st.session_state.user.id).execute()
            except Exception:
                pass
            st.rerun()

        components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
html, body { background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }
.overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.72);
    z-index: 999999;
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
}
.card {
    background: #0e2a47;
    border-radius: 20px;
    padding: 32px;
    width: min(95vw, 460px);
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    border: 1px solid #1e3a5f;
}
.hdr { display:flex; align-items:center; gap:14px; margin-bottom:24px; }
.hdr-icon {
    width:46px; height:46px; border-radius:50%;
    background:#ef4444;
    display:flex; align-items:center; justify-content:center;
    font-size:22px; flex-shrink:0;
}
.hdr-title { font-size:18px; font-weight:800; color:#f1f5f9; margin-bottom:3px; }
.hdr-sub { font-size:13px; color:#94a3b8; }
.msg {
    background:#1e3a5f; border-radius:12px;
    padding:18px 20px; margin-bottom:24px;
    font-size:14px; color:#cbd5e1; line-height:1.65; text-align:center;
}
.btns { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.btn {
    padding:13px 0; border-radius:10px;
    font-size:15px; font-weight:700;
    cursor:pointer; border:none;
    font-family:'DM Sans',sans-serif;
    transition:background 0.15s;
}
.btn-cancel {
    background:#1e3a5f; color:#94a3b8;
    border:1px solid #2d4f6e;
}
.btn-cancel:hover { background:#2d4f6e; color:#e2e8f0; }
.btn-confirm {
    background:#ef4444; color:#fff;
}
.btn-confirm:hover { background:#dc2626; }
</style>
<div class="overlay">
    <div class="card">
        <div class="hdr">
            <div class="hdr-icon">🗑️</div>
            <div>
                <div class="hdr-title">Limpar cache de redes?</div>
                <div class="hdr-sub">Esta ação não pode ser desfeita.</div>
            </div>
        </div>
        <div class="msg">
            Todos os dados coletados do Instagram serão apagados.<br>
            Será necessário coletar novamente.
        </div>
        <div class="btns">
            <button class="btn btn-cancel" onclick="triggerBtn('Cancelar')">Cancelar</button>
            <button class="btn btn-confirm" onclick="triggerBtn('Sim, limpar')">Sim, limpar</button>
        </div>
    </div>
</div>
<script>
function triggerBtn(label) {
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === label) { b.click(); return; }
    }
}
(function() {
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        try { if (iframes[i].contentWindow === window) {
            iframes[i].style.position = 'fixed';
            iframes[i].style.inset = '0';
            iframes[i].style.width = '100vw';
            iframes[i].style.height = '100vh';
            iframes[i].style.zIndex = '999998';
            iframes[i].style.border = 'none';
            break;
        }} catch(e) {}
    }
})();
</script>
""", height=600, scrolling=False)

# ── HR separador — fora das colunas, com correção de espaço ────
    st.markdown("""
        <style>
        #redes-hr-wrapper {
            margin-top: -30px !important;
        }
        </style>
        <div id="redes-hr-wrapper">
            <hr style='border:none;border-top:1px solid #e5e7eb;margin:0'/>
        </div>
    """, unsafe_allow_html=True)

    # ── Helpers ────────────────────────────────────────────────────
    def fmt_num(n):
        n = int(n or 0)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n/1_000:.1f}K"
        return str(n)

    def salvar_cache_redes(dados: list):
        try:
            payload = {
                "user_id": st.session_state.user.id,
                "minha_empresa": st.session_state.dados["minha_empresa"],
                "concorrentes": st.session_state.dados["concorrentes"],
                "metricas_redes": {
                    "ultima_coleta": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "dados": dados,
                },
            }
            supabase.table("ci_dados").upsert(payload, on_conflict="user_id").execute()
        except Exception as e:
            st.toast(f"⚠️ Erro ao salvar cache: {e}", icon="⚠️")

    def carregar_cache_redes() -> dict:
        try:
            res = (
                supabase.table("ci_dados")
                .select("metricas_redes")
                .eq("user_id", st.session_state.user.id)
                .execute()
            )
            if res.data and res.data[0].get("metricas_redes"):
                return res.data[0]["metricas_redes"]
        except Exception:
            pass
        return {}

    @st.cache_data(ttl=1800, show_spinner=False)
    def coletar_rapidapi(handle: str) -> dict:
        handle_limpo = handle.lstrip("@").strip()
        if not handle_limpo:
            return {"erro": "Handle vazio"}
        try:
            rapidapi_key = st.secrets.get("RAPIDAPI_KEY", "")
            if not rapidapi_key:
                return {"erro": "RAPIDAPI_KEY não configurada"}

            headers = {
                "x-rapidapi-key": rapidapi_key,
                "x-rapidapi-host": "instagram-looter2.p.rapidapi.com",
            }

            r = requests.get(
                f"https://instagram-looter2.p.rapidapi.com/profile?username={handle_limpo}",
                headers=headers,
                timeout=15,
            )
            data = r.json()
            user_data = data
            if isinstance(data, dict):
                if "data" in data:   user_data = data["data"]
                elif "user" in data: user_data = data["user"]

            if not user_data or "message" in user_data:
                return {"erro": user_data.get("message", "Perfil não encontrado")}

            seg         = int(user_data.get("follower_count") or user_data.get("edge_followed_by", {}).get("count") or 0)
            total_posts = int(user_data.get("media_count") or user_data.get("edge_owner_to_timeline_media", {}).get("count") or 0)
            pk          = str(user_data.get("pk") or user_data.get("id") or "").strip()

            posts_data = []
            if pk:
                for endpoint in [
                    f"https://instagram-looter2.p.rapidapi.com/user-feeds?id={pk}&count=12&allow_restricted_media=false",
                    f"https://instagram-looter2.p.rapidapi.com/user-medias?id={pk}&count=12",
                ]:
                    try:
                        rp    = requests.get(endpoint, headers=headers, timeout=15)
                        pr    = rp.json()
                        items = pr if isinstance(pr, list) else pr.get("items", [])
                        if items:
                            for p in items[:12]:
                                likes    = int(p.get("like_count") or 0)
                                comments = int(p.get("comment_count") or 0)

                                thumb = ""
                                thumb_hd = ""
                                if p.get("image_versions2"):
                                    cands = p["image_versions2"].get("candidates", [])
                                    if cands:
                                        cands_sorted = sorted(cands, key=lambda c: c.get("width", 0), reverse=True)
                                        thumb_hd = cands_sorted[0].get("url", "")
                                        thumb = cands_sorted[-1].get("url", "")
                                        if len(cands_sorted) == 1:
                                            thumb = thumb_hd
                                    else:
                                        thumb_hd = ""
                                        thumb = ""

                                if not thumb_hd:
                                    thumb_hd = (
                                        p.get("display_url")
                                        or p.get("thumbnail_src")
                                        or p.get("image_url")
                                        or ""
                                    )

                                if p.get("display_resources"):
                                    resources = sorted(
                                        p["display_resources"],
                                        key=lambda r: r.get("config_width", 0),
                                        reverse=True
                                    )
                                    if resources:
                                        thumb_hd = resources[0].get("src", "") or thumb_hd

                                if not thumb_hd:
                                    thumb_hd = thumb

                                if not thumb:
                                    thumb = thumb_hd

                                if p.get("thumbnail_url") and not thumb:
                                    thumb = p["thumbnail_url"]
                                    if not thumb_hd:
                                        thumb_hd = thumb

                                caption  = ""
                                if p.get("caption"):
                                    caption = (
                                        p["caption"].get("text", "")
                                        if isinstance(p["caption"], dict)
                                        else str(p["caption"])
                                    )[:500]
                                taken_at = p.get("taken_at", 0)
                                date_str = ""
                                if taken_at:
                                    try:
                                        date_str = datetime.datetime.fromtimestamp(taken_at).strftime("%d/%m/%Y")
                                    except Exception:
                                        pass
                                shortcode = p.get("code") or p.get("shortcode") or ""
                                post_url  = f"https://www.instagram.com/p/{shortcode}/" if shortcode else ""

                                media_type = p.get("media_type", 1)
                                is_reel = media_type == 2

                                video_url = ""
                                if is_reel:
                                    video_url = (
                                        p.get("video_url")
                                        or (p.get("video_versions") or [{}])[0].get("url", "")
                                        or ""
                                    )

                                carousel_imgs = []
                                carousel_imgs_hd = []

                                if media_type == 8:
                                    for slide in (p.get("carousel_media") or []):
                                        cands = slide.get("image_versions2", {}).get("candidates", [])
                                        url_hd     = cands[0].get("url", "") if cands else ""
                                        url_thumb  = cands[-1].get("url", "") if cands else url_hd
                                        url_display = slide.get("display_uri", "")

                                        escolhida_hd    = url_hd or url_display
                                        escolhida_thumb = url_thumb or url_display or url_hd

                                        if escolhida_hd:
                                            carousel_imgs_hd.append(escolhida_hd)
                                        if escolhida_thumb:
                                            carousel_imgs.append(escolhida_thumb)

                                    if not carousel_imgs and thumb:
                                        carousel_imgs = [thumb]
                                    if not carousel_imgs_hd and thumb_hd:
                                        carousel_imgs_hd = [thumb_hd]

                                posts_data.append({
                                    "likes":          likes,
                                    "comments":       comments,
                                    "thumb":          thumb,
                                    "thumb_hd":       thumb_hd,
                                    "display_url":    p.get("display_url") or p.get("thumbnail_src") or p.get("image_url") or thumb_hd,
                                    "caption":        caption,
                                    "date":           date_str,
                                    "is_video":       is_reel,
                                    "media_type":     media_type,
                                    "video_url":      video_url,
                                    "post_url":       post_url,
                                    "shortcode":      shortcode,
                                    "carousel_imgs":  carousel_imgs,
                                    "carousel_imgs_hd": carousel_imgs_hd,
                                    "_raw": {
                                        k: v for k, v in p.items()
                                        if k not in ("carousel_media", "video_versions", "image_versions2")
                                    },
                                    "_raw_image_versions2": {
                                        "candidates": [
                                            {"width": c.get("width"), "height": c.get("height"), "url": c.get("url", "")[:80] + "..."}
                                            for c in (p.get("image_versions2") or {}).get("candidates", [])
                                        ]
                                    },
                                    "_raw_display_resources": p.get("display_resources", []),
                                })
                            break
                    except Exception:
                        continue

            if posts_data:
                eng_medio = sum(p["likes"] + p["comments"] for p in posts_data) / len(posts_data)
                eng_pct   = round(eng_medio / seg * 100, 2) if seg > 0 else 0.0
            else:
                eng_pct   = 3.0 if seg <= 10_000 else (2.0 if seg <= 50_000 else (1.5 if seg <= 100_000 else 1.0))
                eng_medio = round(seg * eng_pct / 100, 1)

            _profile_pic_raw = (
                user_data.get("profile_pic_url_hd")
                or user_data.get("profile_pic_url")
                or user_data.get("hd_profile_pic_url_info", {}).get("url", "")
                or ""
            )

            if not _profile_pic_raw and posts_data:
                try:
                    raw = posts_data[0].get("_raw", {})
                    _profile_pic_raw = (
                        raw.get("user", {}).get("profile_pic_url_hd", "")
                        or raw.get("user", {}).get("profile_pic_url", "")
                        or raw.get("caption", {}).get("user", {}).get("profile_pic_url_hd", "")
                        or raw.get("caption", {}).get("user", {}).get("profile_pic_url", "")
                        or ""
                    )
                except Exception:
                    pass

            profile_pic = _profile_pic_raw

            if profile_pic:
                try:
                    import requests as _req
                    import base64 as _b64
                    _r = _req.get(profile_pic, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                    if _r.status_code == 200:
                        _mime = _r.headers.get("content-type", "image/jpeg").split(";")[0]
                        profile_pic = f"data:{_mime};base64,{_b64.b64encode(_r.content).decode()}"
                except Exception:
                    pass

            _bio_links = user_data.get("bio_links") or []
            _external_url = (
                user_data.get("external_url")
                or (_bio_links[0].get("url", "") if _bio_links else "")
                or ""
            )

            return {
                "handle":       "@" + handle_limpo,
                "nome_exibido": user_data.get("full_name") or user_data.get("username", handle_limpo),
                "seguidores":   seg,
                "seguindo":     int(user_data.get("following_count") or 0),
                "total_posts":  total_posts,
                "bio":          (user_data.get("biography") or "")[:120],
                "external_url": _external_url,
                "is_verified":  user_data.get("is_verified", False),
                "eng_medio":    round(eng_medio, 1),
                "eng_pct":      eng_pct,
                "posts":        posts_data,
                "fonte":        "rapidapi",
                "erro":         None,
                "profile_pic":  profile_pic,
            }
        except Exception as e:
            return {"erro": str(e)}

    def calcular_score_bio(bio: str, ext_url: str, seguidores: int, eng_pct: float) -> dict:
        score = 0
        criterios = []

        if bio and len(bio.strip()) > 10:
            score += 20
            criterios.append({"label": "Tem bio", "ok": True})
        else:
            criterios.append({"label": "Tem bio", "ok": False})

        palavras_valor = [
            "crescimento", "resultado", "apoio", "solução", "transforma", "aumenta",
            "melhora", "ajuda", "economiza", "conquista", "vendas", "lucro",
            "aprenda", "domine", "sucesso", "estratégia", "especialista"
        ]
        tem_valor = any(p in bio.lower() for p in palavras_valor)
        if tem_valor:
            score += 20
            criterios.append({"label": "Proposta de valor clara", "ok": True})
        else:
            criterios.append({"label": "Proposta de valor clara", "ok": False})

        if ext_url:
            score += 15
            criterios.append({"label": "Link na bio", "ok": True})
        else:
            criterios.append({"label": "Link na bio", "ok": False})

        palavras_nicho = [
            "escola", "empresa", "marca", "negócio", "empreendedor", "coach",
            "agência", "consultoria", "clínica", "médico", "advogado", "arquiteto",
            "professor", "mentor", "especialista", "privad", "digital", "online"
        ]
        tem_nicho = any(p in bio.lower() for p in palavras_nicho)
        if tem_nicho:
            score += 20
            criterios.append({"label": "Posicionamento da marca", "ok": True})
        else:
            criterios.append({"label": "Posicionamento da marca", "ok": False})

        palavras_cta = [
            "saiba mais", "clique", "acesse", "entre", "inscreva", "baixe",
            "conheça", "veja", "assista", "siga", "participe", "reserve", "agende",
            "↓", "👇", "⬇️", "link", "whatsapp"
        ]
        tem_cta = any(p in bio.lower() for p in palavras_cta)
        if tem_cta:
            score += 15
            criterios.append({"label": "CTA na bio", "ok": True})
        else:
            criterios.append({"label": "CTA na bio", "ok": False})

        if eng_pct >= 3.0:
            score += 10
            criterios.append({"label": "Diferenciação no mercado", "ok": True})
        elif eng_pct >= 1.5:
            score += 5
            criterios.append({"label": "Diferenciação no mercado", "ok": False})
        else:
            criterios.append({"label": "Diferenciação no mercado", "ok": False})

        if score >= 80:
            classificacao, classificacao_icon = "Excelente", "🏆"
            cor_classe, bg_classe, brd_classe = "#22c55e", "#f0fdf4", "#bbf7d0"
        elif score >= 60:
            classificacao, classificacao_icon = "Bom", "👍"
            cor_classe, bg_classe, brd_classe = "#3b82f6", "#eff6ff", "#bfdbfe"
        elif score >= 40:
            classificacao, classificacao_icon = "Regular", "⚠️"
            cor_classe, bg_classe, brd_classe = "#f59e0b", "#fffbeb", "#fde68a"
        else:
            classificacao, classificacao_icon = "Precisa melhorar", "📝"
            cor_classe, bg_classe, brd_classe = "#ef4444", "#fef2f2", "#fecaca"

        oportunidades = sum(1 for c in criterios if not c["ok"])

        return {
            "score": score,
            "classificacao": classificacao,
            "classificacao_icon": classificacao_icon,
            "cor_classe": cor_classe,
            "bg_classe": bg_classe,
            "brd_classe": brd_classe,
            "criterios": criterios,
            "oportunidades": oportunidades,
        }
    
    # ── Lista de perfis ─────────────────────────────────────────────
    todas = []
    if emp.get("nome") and emp.get("instagram") and emp["instagram"] not in ("@", ""):
        todas.append({"key": "__minha__", "nome": emp["nome"], "instagram": emp["instagram"], "tipo": "minha"})
    for i, c in enumerate(concorrentes):
        if c.get("instagram") and c["instagram"] not in ("@", ""):
            todas.append({"key": f"conc_{i}", "nome": c["nome"], "instagram": c["instagram"], "tipo": "concorrente"})

    if not todas:
        st.info("Cadastre pelo menos um Instagram (sua empresa ou concorrente) para usar esta página.")
        st.stop()

    if not st.secrets.get("RAPIDAPI_KEY", ""):
        st.warning("Configure `RAPIDAPI_KEY` no secrets.toml para coletar dados.")

    cache = carregar_cache_redes()

    if coletar:
        coletar_rapidapi.clear()
        resultados_lista = []

        modal_placeholder = st.empty()

        def render_modal_coleta(processados, total, itens):
            linhas_html = []
            for item in itens:
                icone = "✅" if item.get("done") else ("⏳" if item.get("atual") else "⬜")
                detalhe = ""
                if item.get("done"):
                    detalhe = f'<span style="color:#3a9fd6;font-weight:700">{item["n"]} posts</span>'
                elif item.get("atual"):
                    detalhe = '<span style="color:#9ca3af;font-size:12px">Coletando...</span>'

                linhas_html.append(
                    '<div style="background:#1e3a5f;border-radius:10px;padding:14px 18px;'
                    'display:flex;align-items:center;justify-content:space-between;gap:12px;">'
                    '<div style="display:flex;align-items:center;gap:12px;">'
                    f'<span style="font-size:20px">{icone}</span>'
                    '<div>'
                    f'<div style="font-size:14px;font-weight:700;color:#e2e8f0">{item["nome"]}</div>'
                    '</div></div>'
                    f'{detalhe}'
                    '</div>'
                )

            linhas_itens = "".join(linhas_html)
            pct = int((processados / total) * 100) if total > 0 else 0
            is_done = processados == total
            cor_pct = "#22c55e" if is_done else "#3a9fd6"
            icone_hdr = "✅" if is_done else "⏳"
            titulo = "Busca concluída!" if is_done else "Coletando perfis..."
            plural = "s" if total > 1 else ""
            qtd_label = "empresas" if total > 1 else "empresa"
            rodape = (
                '<div style="text-align:center;margin-top:18px;font-size:13px;color:#64748b;">'
                'Fechando automaticamente...</div>'
            ) if is_done else ""

            html_modal = f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.overlay {{
    position:fixed; inset:0;
    background:rgba(0,0,0,0.72);
    z-index:999999;
    display:flex; align-items:center; justify-content:center;
    padding:24px;
}}
.card {{
    background:#0e2a47;
    border-radius:20px;
    padding:32px;
    width:min(95vw,500px);
    box-shadow:0 20px 60px rgba(0,0,0,0.5);
    border:1px solid #1e3a5f;
}}
</style>
<div class="overlay">
<div class="card">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;">
        <div style="width:42px;height:42px;border-radius:50%;background:{cor_pct};
            display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;">
            {icone_hdr}
        </div>
        <div>
            <div style="font-size:17px;font-weight:800;color:#f1f5f9;">{titulo}</div>
            <div style="font-size:13px;color:#94a3b8;">{processados}/{total} {qtd_label} processada{plural}</div>
        </div>
        <div style="margin-left:auto;font-size:22px;font-weight:900;color:{cor_pct};">{pct}%</div>
    </div>
    <div style="background:#1e3a5f;border-radius:8px;height:8px;margin-bottom:20px;overflow:hidden;">
        <div style="background:linear-gradient(90deg,#3a9fd6,#22c55e);height:100%;width:{pct}%;border-radius:8px;"></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:10px;">{linhas_itens}</div>
    {rodape}
</div>
</div>
<script>
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.position = 'fixed';
                iframes[i].style.inset = '0';
                iframes[i].style.width = '100vw';
                iframes[i].style.height = '100vh';
                iframes[i].style.zIndex = '999998';
                iframes[i].style.border = 'none';
                break;
            }}
        }} catch(e) {{}}
    }}
}})();
</script>
"""
            with modal_placeholder:
                components.html(html_modal, height=600, scrolling=False)

        itens_status = [{"nome": e["nome"], "done": False, "atual": False, "n": 0} for e in todas]

        for idx_e, e in enumerate(todas):
            itens_status[idx_e]["atual"] = True
            render_modal_coleta(idx_e, len(todas), itens_status)

            r_col = coletar_rapidapi(e["instagram"])
            n_posts = len(r_col.get("posts", [])) if r_col and not r_col.get("erro") else 0

            itens_status[idx_e]["done"] = True
            itens_status[idx_e]["atual"] = False
            itens_status[idx_e]["n"] = n_posts
            resultados_lista.append({**e, **(r_col or {"erro": "Sem resposta"})})

        render_modal_coleta(len(todas), len(todas), itens_status)
        import time; time.sleep(2)
        modal_placeholder.empty()

        salvar_cache_redes(resultados_lista)
        cache = {
            "ultima_coleta": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
            "dados": resultados_lista,
        }
        st.session_state.metricas_redes = cache
        st.toast("✅ Dados coletados e salvos!", icon="✅")

    ok = []
    if cache.get("dados"):
        ok    = [r for r in cache["dados"] if not r.get("erro")]
        erros = [r for r in cache["dados"] if r.get("erro")]
        for r in erros:
            st.warning(f"⚠️ {r['nome']}: {r['erro']}")

    # ── Estado de navegação ─────────────────────────────────────────
    if "redes_main_tab" not in st.session_state:
        st.session_state.redes_main_tab = "perfis"
    if "redes_aba_ativa" not in st.session_state:
        st.session_state.redes_aba_ativa = 0
    if "redes_analise_vistas" not in st.session_state:
        st.session_state.redes_analise_vistas = 0
    if "redes_analises_salvas" not in st.session_state:
        st.session_state.redes_analises_salvas = []

    # ── Ghost buttons — abas principais ────────────────────────────
    st.markdown("""
    <style>
    .st-key-_redes_ghost_tab_perfis_,
    .st-key-_redes_ghost_tab_analise_ {
        position: fixed !important; top: -9999px !important; left: -9999px !important;
        width: 0 !important; height: 0 !important; overflow: hidden !important;
        opacity: 0 !important; pointer-events: none !important; visibility: hidden !important; display: none !important;
    }
    .stElementContainer:has(.st-key-_redes_ghost_tab_perfis_),
    .stElementContainer:has(.st-key-_redes_ghost_tab_analise_) {
        display: none !important; height: 0 !important; min-height: 0 !important;
        max-height: 0 !important; padding: 0 !important; margin: 0 !important; overflow: hidden !important;
    }
    </style>
    """, unsafe_allow_html=True)

    if st.button("perfis_tab", key="_redes_ghost_tab_perfis_"):
        st.session_state.redes_main_tab = "perfis"
        st.rerun()
    if st.button("analise_tab", key="_redes_ghost_tab_analise_"):
        st.session_state.redes_main_tab = "analise"
        st.rerun()

    # ── Ghost buttons — abas de empresa ────────────────────────────
    aba_empresa_ghost_css = []
    for i in range(len(ok)):
        k = f"btn_redes_aba_{i}"
        aba_empresa_ghost_css.append(f"""
        .st-key-{k} {{
            position:fixed !important; top:-9999px !important; left:-9999px !important;
            width:0 !important; height:0 !important; overflow:hidden !important;
            opacity:0 !important; pointer-events:none !important; display:none !important;
        }}
        .stElementContainer:has(.st-key-{k}) {{
            display:none !important; height:0 !important; min-height:0 !important;
            max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
        }}
        """)
    if aba_empresa_ghost_css:
        st.markdown(f"<style>{''.join(aba_empresa_ghost_css)}</style>", unsafe_allow_html=True)

    for i in range(len(ok)):
        if st.button(f"redes_aba_{i}", key=f"btn_redes_aba_{i}"):
            st.session_state.redes_aba_ativa = i
            st.rerun()

    analises_redes_para_rm = st.session_state.get("redes_analises_salvas", [])
    acoes_rm_redes = {}
    for i in range(len(analises_redes_para_rm)):
        acoes_rm_redes[f"rm_{i}"] = st.button(f"_rm_redes_analise_{i}_", key=f"btn_rm_redes_analise_{i}")

    rm_css_redes = "\n".join([
        f".st-key-btn_rm_redes_analise_{i} {{ display: none !important; }}"
        f".stElementContainer:has(.st-key-btn_rm_redes_analise_{i}) {{ display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; }}"
        for i in range(len(analises_redes_para_rm))
    ])
    st.markdown(f"<style>{rm_css_redes}</style>", unsafe_allow_html=True)

    for i in range(len(analises_redes_para_rm) - 1, -1, -1):
        if acoes_rm_redes.get(f"rm_{i}"):
            st.session_state.redes_analises_salvas.pop(i)
            st.rerun()

    main_tab = st.session_state.redes_main_tab

    # ══════════════════════════════════════════════════════════════════
    # BARRA DE NAVEGAÇÃO PRINCIPAL (2 abas)
    # ══════════════════════════════════════════════════════════════════

    analises_redes_nav = st.session_state.get("redes_analises_salvas", [])
    qtd_redes_analises = len(analises_redes_nav)

    nao_lidas_redes = max(0, qtd_redes_analises - st.session_state.redes_analise_vistas)
    if main_tab == "analise":
        st.session_state.redes_analise_vistas = qtd_redes_analises
        nao_lidas_redes = 0

    components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; -webkit-font-smoothing:antialiased; }}
.nav-bar {{ display:grid; grid-template-columns: 1fr 1fr; gap:12px; width:100%; }}
.nav-item {{
    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
    padding:16px 20px; cursor:pointer; display:flex; align-items:center;
    gap:14px; transition:all 0.15s; position:relative; overflow:hidden;
}}
.nav-item:hover {{ border-color:#3a9fd6; box-shadow:0 2px 12px rgba(58,159,214,0.12); }}
.nav-item.active {{
    background:#0e2a47; border-color:#0e2a47;
    box-shadow:0 4px 20px rgba(14,42,71,0.22);
}}
.nav-item.active::after {{
    content:''; position:absolute; bottom:0;left:0;right:0; height:3px;
    background:linear-gradient(90deg,#3a9fd6,#2ecc71);
    border-radius:0 0 14px 14px;
}}
.nav-icon {{
    width:40px;height:40px;border-radius:10px;
    display:flex;align-items:center;justify-content:center;
    flex-shrink:0; background:#f3f4f6; transition:background 0.15s;
}}
.nav-item.active .nav-icon {{ background:rgba(255,255,255,0.12); }}
.nav-icon svg {{ width:20px;height:20px; }}
.nav-content {{ flex:1;min-width:0; }}
.nav-title {{ font-size:15px;font-weight:700;color:#1a2e4a; display:block;margin-bottom:2px; }}
.nav-item.active .nav-title {{ color:#ffffff; }}
.nav-sub {{ font-size:12px;color:#9ca3af; }}
.nav-item.active .nav-sub {{ color:rgba(255,255,255,0.55); }}
.nav-right {{ display:flex; flex-direction:column; align-items:flex-end; gap:5px; flex-shrink:0; }}
.count-badge {{
    min-width:26px; height:26px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-size:12px; font-weight:800; padding:0 5px;
    background:#e5e7eb; color:#6b7280;
}}
.count-badge.has {{ background:#3a9fd6; color:#fff; }}
.nav-item.active .count-badge {{ background:rgba(255,255,255,0.18); color:#fff; }}
.nav-item.active .count-badge.has {{ background:rgba(58,159,214,0.5); color:#fff; }}
.new-badge {{
    background:#ef4444; color:#fff;
    font-size:10px; font-weight:800;
    padding:2px 7px; border-radius:20px;
    letter-spacing:0.3px; text-transform:uppercase;
    animation: pulse 1.5s infinite;
}}
@keyframes pulse {{
    0%,100% {{ opacity:1; transform:scale(1); }}
    50%      {{ opacity:0.75; transform:scale(0.95); }}
}}
</style>
<div class="nav-bar">

    <div class="nav-item {'active' if main_tab == 'perfis' else ''}" onclick="triggerTab('perfis_tab')">
        <div class="nav-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="{'#ffffff' if main_tab == 'perfis' else '#6b7280'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
            </svg>
        </div>
        <div class="nav-content">
            <span class="nav-title">Perfis configurados</span>
            <span class="nav-sub">Visualize e analise cada perfil individualmente</span>
        </div>
        <div class="nav-right">
            <div class="count-badge {'has' if len(ok) > 0 else ''}">{len(ok)}</div>
        </div>
    </div>

    <div class="nav-item {'active' if main_tab == 'analise' else ''}" onclick="triggerTab('analise_tab')">
        <div class="nav-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="{'#ffffff' if main_tab == 'analise' else '#6b7280'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
        </div>
        <div class="nav-content">
            <span class="nav-title">Análise de IA</span>
            <span class="nav-sub">Relatórios individuais e comparativos</span>
        </div>
        <div class="nav-right">
            <div class="count-badge {'has' if qtd_redes_analises > 0 else ''}">{qtd_redes_analises}</div>
            {'<div class="new-badge">NOVA</div>' if nao_lidas_redes > 0 else ''}
        </div>
    </div>

</div>
<script>
function triggerTab(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
          if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '90px';
            iframes[i].style.marginTop = '-30px';
            break;
          }}
        }} catch(e) {{}}
    }}
}})();
</script>
""", height=90, scrolling=False)

    # ══════════════════════════════════════════════════════════════════
    # ABA: PERFIS CONFIGURADOS
    # ══════════════════════════════════════════════════════════════════

    if main_tab == "perfis":

        if not ok:
            st.markdown("""
            <div style='background:#fff;border:1px dashed #d1d5db;border-radius:14px;
                        padding:48px 32px;text-align:center;margin-top:8px'>
                <div style='font-size:32px;margin-bottom:12px'>📱</div>
                <div style='font-size:16px;font-weight:600;color:#374151;margin-bottom:6px'>Nenhum dado carregado ainda</div>
                <div style='font-size:14px;color:#9ca3af'>Clique em <b>Coletar dados</b> para buscar os dados do Instagram.</div>
            </div>
            """, unsafe_allow_html=True)
            st.stop()

        aba_ativa = min(st.session_state.get("redes_aba_ativa", 0), len(ok) - 1)

        # ── Cards de empresa no topo ─────────────────────────────────
        empresas_redes_json = []
        for i, r in enumerate(ok):
            is_minha = r.get("tipo") == "minha"
            cor = get_minha_empresa_color() if is_minha else get_concorrente_color(i)
            empresas_redes_json.append({
                "i": i,
                "nome": r["nome"],
                "tipo": r.get("tipo", "concorrente"),
                "handle": r.get("handle", ""),
                "is_minha": is_minha,
                "badge_lbl": "Minha empresa" if is_minha else "Concorrente",
                "cor": cor,
                "profile_pic": r.get("profile_pic", ""),
            })

        empresas_redes_str = json.dumps(empresas_redes_json, ensure_ascii=False)

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; -webkit-font-smoothing:antialiased; }}
.main-wrap {{
    background:#ffffff;
    border:1px solid #e5e7eb;
    border-radius:16px;
    overflow:hidden;
    margin-bottom:0;
}}
.cards-grid {{
    display:grid;
    grid-template-columns: repeat(3,1fr);
    gap:15px;
    padding:15px;
}}
.emp-card {{
    background:#f9fafb;
    border:1px solid #e5e7eb;
    border-radius:12px;
    padding:16px;
    display:flex;
    align-items:center;
    gap:12px;
    cursor:pointer;
    transition:all 0.15s;
    position:relative;
}}
.emp-card:hover {{
    border-color:#3a9fd6;
    background:#fff;
    box-shadow:0 2px 10px rgba(58,159,214,0.1);
}}
.emp-card.active {{
    background:#fff;
    border: 2px solid #3b82f6;
}}
.emp-icon {{
    width:44px; height:44px; border-radius:10px;
    background:#e9eef5;
    display:flex; align-items:center; justify-content:center;
    flex-shrink:0;
}}
.emp-card.active .emp-icon {{ background:#dbeafe; }}
.emp-icon svg {{ width:22px; height:22px; }}
.emp-info {{ flex:1; min-width:0; }}
.emp-nome {{
    font-size:14px; font-weight:700; color:#1a2e4a;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.emp-sep {{ color: #d1d5db; font-weight: 400; }}
.emp-handle-inline {{ font-size: 13px; font-weight: 400; color: #9ca3af; }}
.badge-minha {{
    display:inline-flex; align-items:center; gap:5px;
    background:#f0fdf4; color:#15803d;
    border:1px solid #bbf7d0;
    padding:3px 10px; border-radius:20px;
    font-size:11px; font-weight:700;
}}
.badge-conc {{
    display:inline-flex; align-items:center; gap:5px;
    background:#eff6ff; color:#1d4ed8;
    border:1px solid #bfdbfe;
    padding:3px 10px; border-radius:20px;
    font-size:11px; font-weight:700;
}}
.badge-minha, .badge-conc {{
    flex-shrink: 0;
    margin-left: auto;  /* ← adicionar */
}}
</style>
<div class="main-wrap">
    <div class="cards-grid" id="cards-grid"></div>
</div>
<script>
var EMPRESAS = {empresas_redes_str};
var ABA_ATIVA = {aba_ativa};
function buildUI() {{
    var grid = document.getElementById('cards-grid');
    grid.innerHTML = '';
    EMPRESAS.forEach(function(e) {{
        var card = document.createElement('div');
        card.className = 'emp-card' + (e.i === ABA_ATIVA ? ' active' : '');
        card.id = 'emp_card_' + e.i;
        var badgeHtml = e.is_minha
            ? '<span class="badge-minha">Minha empresa</span>'
            : '<span class="badge-conc">Concorrente</span>';
        card.innerHTML =
            '<div class="emp-icon">'
            + '<svg viewBox="0 0 24 24" fill="none" stroke="' + (e.i === ABA_ATIVA ? '#3b82f6' : '#64748b') + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
            + '<rect x="2" y="2" width="20" height="20" rx="5"/>'
            + '<circle cx="12" cy="12" r="4.5" stroke-width="1.5" fill="none"/>'
            + '<circle cx="17.5" cy="6.5" r="1.2" fill="' + (e.i === ABA_ATIVA ? '#3b82f6' : '#64748b') + '"/>'
            + '</svg>'
            + '</div>'
            + '<div class="emp-info">'
            + '<div class="emp-nome">' + e.nome + '</div>'
            + (e.handle ? '<div style="font-size:13px;color:#9ca3af;">' + e.handle + '</div>' : '')
            + '</div>'
            + badgeHtml; 
        card.addEventListener('click', function() {{ selectAba(e.i); }});
        grid.appendChild(card);
    }});
    syncHeight();
}}
function selectAba(i) {{
    ABA_ATIVA = i;
    document.querySelectorAll('.emp-card').forEach(function(c) {{ c.classList.remove('active'); }});
    var card = document.getElementById('emp_card_' + i);
    if (card) card.classList.add('active');
    triggerBtn('redes_aba_' + i);
}}
function triggerBtn(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}
function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {{
        try {{ if (frames[i].contentWindow === window) {{
            frames[i].style.height = (h + 2) + 'px';
            frames[i].style.marginTop = '-42px';
            break;
        }} }} catch(e) {{}}
    }}
}}
buildUI();
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 200); setTimeout(syncHeight, 600);
</script>
""", height=100, scrolling=False)

        # ── Dados do perfil ativo ────────────────────────────────────
        r = ok[aba_ativa]
        is_minha  = r.get("tipo") == "minha"
        badge_bg  = "#eff6ff" if is_minha else "#f3f4f6"
        badge_txt = "#1d4ed8" if is_minha else "#6b7280"
        badge_brd = "#bfdbfe" if is_minha else "#e5e7eb"
        badge_lbl = "Minha Empresa" if is_minha else "Concorrente"
        cor = get_avatar_color(aba_ativa)
        bio_txt   = (r.get("bio") or "").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ").replace('"', "&quot;").replace("'", "&#39;")
        ext_url   = (r.get("external_url") or "").strip()
        ext_url_display = ext_url.replace("https://", "").replace("http://", "").rstrip("/")
        posts_list = r.get("posts", [])

        score_data    = calcular_score_bio(bio_txt, ext_url, r.get("seguidores", 0), r.get("eng_pct", 0.0))
        score_val     = score_data["score"]
        score_cls     = score_data["classificacao"]
        score_icon    = score_data["classificacao_icon"]
        score_cor     = score_data["cor_classe"]
        score_bg      = score_data["bg_classe"]
        score_brd     = score_data["brd_classe"]
        score_crit    = score_data["criterios"]
        score_oport   = score_data["oportunidades"]

        import json as _json_score
        score_crit_json = _json_score.dumps(score_crit, ensure_ascii=False)

        seg_fmt   = fmt_num(r.get("seguidores", 0))
        posts_fmt = fmt_num(r.get("total_posts", 0))
        handle_clean = (r.get("handle") or "").lstrip("@")
        ig_url = f"https://www.instagram.com/{handle_clean}/" if handle_clean else "#"
        avatar_letras = gerar_avatar(r["nome"])
        profile_pic_url = r.get("profile_pic", "")

        # ── Estado de subtab ────────────────────────────────────────
        redes_subtab_key = f"redes_subtab_{aba_ativa}"
        if redes_subtab_key not in st.session_state:
            st.session_state[redes_subtab_key] = "postagens"

        subtab_atual = st.session_state.get(redes_subtab_key, "postagens")

        # ── Ghost buttons subtabs ───────────────────────────────────
        for sub in ["postagens"]:
            ghost_k = f"btn_redes_sub_{aba_ativa}_{sub}"
            st.markdown(f"""
            <style>
            .st-key-{ghost_k} {{
                position:fixed !important; top:-9999px !important; left:-9999px !important;
                width:0 !important; height:0 !important; overflow:hidden !important;
                opacity:0 !important; pointer-events:none !important; display:none !important;
            }}
            .stElementContainer:has(.st-key-{ghost_k}) {{
                display:none !important; height:0 !important; min-height:0 !important;
                max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
            }}
            </style>
            """, unsafe_allow_html=True)
            if st.button(f"redes_sub_{aba_ativa}_{sub}", key=ghost_k):
                st.session_state[redes_subtab_key] = sub
                st.rerun()

        # ── Ghost button bio IA ─────────────────────────────────────
        chave_bio_ia = f"ia_bio_{r.get('handle','').replace('@','')}"
        if chave_bio_ia not in st.session_state:
            st.session_state[chave_bio_ia] = ""

        st.markdown(f"""
        <style>
        .st-key-btn_bio_ia_{aba_ativa} {{
            position: fixed !important; top: -9999px !important; left: -9999px !important;
            width: 1px !important; height: 1px !important;
            opacity: 0 !important; pointer-events: none !important;
        }}
        .stElementContainer:has(.st-key-btn_bio_ia_{aba_ativa}) {{
            position: fixed !important; top: -9999px !important; left: -9999px !important;
            width: 1px !important; height: 1px !important;
            overflow: hidden !important; margin: 0 !important; padding: 0 !important;
        }}
        </style>
        """, unsafe_allow_html=True)

        analisar_bio = st.button(
            f"__bio_{aba_ativa}__",
            key=f"btn_bio_ia_{aba_ativa}",
        )
        if analisar_bio:
            if gemini_model is None:
                st.session_state[chave_bio_ia] = "Configure GEMINI_API_KEY nos secrets."
            else:
                with st.spinner("Analisando perfil…"):
                    try:
                        prompt_bio = f"""
Analise o perfil do Instagram abaixo e responda em português de forma direta e objetiva:

Bio: "{bio_txt}"
Perfil: {r.get('handle','')} — {r.get('nome_exibido','')}
Seguidores: {r.get('seguidores',0)} | Engajamento: {r.get('eng_pct',0):.2f}%

Responda com:
### Posicionamento
Qual é o posicionamento transmitido pela bio?

### Pontos Fortes
(2 pontos positivos da bio)

### O que melhorar
(2 sugestões concretas de melhoria)

### Bio sugerida
Escreva uma versão melhorada da bio (máx. 150 caracteres).
"""
                        resp = gemini_model.generate_content(prompt_bio)
                        st.session_state[chave_bio_ia] = resp.text
                        import datetime as _dt_redes
                        st.session_state.redes_analises_salvas = [
                            a for a in st.session_state.redes_analises_salvas
                            if not (a.get("tipo") == "bio" and a.get("perfil") == r.get("handle"))
                        ]
                        st.session_state.redes_analises_salvas.append({
                            "titulo": f"Análise de Perfil — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "relatorio": resp.text,
                            "tipo": "bio",
                            "perfil": r.get("handle", ""),
                            "nome": r["nome"],
                        })
                        salvar_dados_usuario(st.session_state.user.id)
                        st.rerun()
                    except Exception as e:
                        st.session_state[chave_bio_ia] = f"Erro: {e}"
                        st.rerun()

        bio_resultado = st.session_state.get(chave_bio_ia, "")
        bio_resultado_html = bio_resultado.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>") if bio_resultado else ""
 
        # ══════════════════════════════════════════════════════════════
        # IFRAME UNIFICADO: header + bio + tabs + conteúdo
        # ══════════════════════════════════════════════════════════════
 
        if subtab_atual == "postagens":
            posts_col_key = f"posts_cols_{aba_ativa}"
            if posts_col_key not in st.session_state:
                st.session_state[posts_col_key] = 4
            n_cols_posts = st.session_state.get(posts_col_key, 4)

            ghost_toggle_key = f"btn_posts_toggle_{aba_ativa}"
            st.markdown(f"""
            <style>
            .st-key-{ghost_toggle_key} {{
                position:fixed !important; top:-9999px !important; left:-9999px !important;
                width:0 !important; height:0 !important; overflow:hidden !important;
                opacity:0 !important; pointer-events:none !important; display:none !important;
            }}
            .stElementContainer:has(.st-key-{ghost_toggle_key}) {{
                display:none !important; height:0 !important; min-height:0 !important;
                max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
            }}
            </style>
            """, unsafe_allow_html=True)

            if st.button(f"posts_toggle_{aba_ativa}", key=ghost_toggle_key):
                st.session_state[posts_col_key] = 3 if n_cols_posts == 4 else 4
                st.rerun()

            for jp in range(len(posts_list)):
                ghost_post_ia_key = f"btn_post_ia_{aba_ativa}_{jp}"
                st.markdown(f"""
                <style>
                .st-key-{ghost_post_ia_key} {{
                    position:fixed !important; top:-9999px !important; left:-9999px !important;
                    width:0 !important; height:0 !important; overflow:hidden !important;
                    opacity:0 !important; pointer-events:none !important; display:none !important;
                }}
                .stElementContainer:has(.st-key-{ghost_post_ia_key}) {{
                    display:none !important; height:0 !important; min-height:0 !important;
                    max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
                }}
                </style>
                """, unsafe_allow_html=True)
                if st.button(f"post_ia_{aba_ativa}_{jp}", key=ghost_post_ia_key):
                    chave_post_ia = f"ia_post_{aba_ativa}_{jp}"
                    p_data = posts_list[jp]
                    if gemini_model is None:
                        st.session_state[chave_post_ia] = "Configure GEMINI_API_KEY nos secrets."
                    else:
                        with st.spinner(f"Analisando postagem {jp+1}…"):
                            try:
                                resp_post = gemini_model.generate_content(f"""Você é especialista em redes sociais e copywriting.
Analise esta postagem do Instagram e dê feedback estratégico em português.
 
Perfil: {r.get('handle','')} — {r.get('nome','')}
Data: {p_data.get('date','')}
Tipo: {'Vídeo' if p_data.get('is_video') else 'Foto'}
Curtidas: {p_data.get('likes',0)} | Comentários: {p_data.get('comments',0)} | Engajamento total: {p_data.get('likes',0)+p_data.get('comments',0)}
Legenda: {p_data.get('caption','') or 'Sem legenda'}
 
### 🎯 Objetivo da Postagem
Qual parece ser o objetivo desta publicação?
 
### ✍️ Análise da Legenda
Pontos fortes e fracos do copy utilizado.
 
### 📊 Desempenho
Como interpretar as métricas desta postagem?
 
### 💡 Sugestões de Melhoria
2 ações concretas para aumentar o engajamento.
""")
                                st.session_state[chave_post_ia] = resp_post.text
                                import datetime as _dt_redes
                                st.session_state.redes_analises_salvas = [
                                    a for a in st.session_state.redes_analises_salvas
                                    if not (a.get("tipo") == "postagem" and a.get("perfil") == r.get("handle") and a.get("post_idx") == jp)
                                ]
                                st.session_state.redes_analises_salvas.append({
                                    "titulo": f"Postagem {jp+1} — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                                    "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                                    "relatorio": resp_post.text,
                                    "tipo": "postagem",
                                    "perfil": r.get("handle", ""),
                                    "nome": r["nome"],
                                    "post_idx": jp,
                                })
                                salvar_dados_usuario(st.session_state.user.id)
                                st.rerun()
                            except Exception as e_post:
                                st.session_state[chave_post_ia] = f"Erro: {e_post}"
                                st.rerun()

            import json as _json_posts
            posts_json_data = []
            for jp, p in enumerate(posts_list):
                chave_post_ia = f"ia_post_{aba_ativa}_{jp}"
                resultado_ia = st.session_state.get(chave_post_ia, "")
                resultado_ia_html = resultado_ia.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>") if resultado_ia else ""
                handle_clean_post = (r.get("handle") or "").lstrip("@")
                post_url = p.get("post_url", "")
                shortcode = p.get("shortcode", "")
                if not post_url and shortcode:
                    post_url = f"https://www.instagram.com/p/{shortcode}/"
                ig_post_url = post_url if post_url else ""

                c_imgs    = p.get("carousel_imgs", []) or []
                c_imgs_hd = p.get("carousel_imgs_hd", []) or []
                if not c_imgs_hd and c_imgs:
                    c_imgs_hd = c_imgs

                posts_json_data.append({
                    "jp":               jp,
                    "thumb":            p.get("thumb", ""),
                    "thumb_hd":         p.get("thumb_hd", "") or p.get("thumb", ""),
                    "caption":          p.get("caption", ""),
                    "date":             p.get("date", ""),
                    "likes":            p.get("likes", 0),
                    "comments":         p.get("comments", 0),
                    "eng":              p.get("likes", 0) + p.get("comments", 0),
                    "is_video":         p.get("is_video", False),
                    "media_type":       p.get("media_type", 1),
                    "video_url":        p.get("video_url", ""),
                    "ig_url":           ig_post_url,
                    "resultado_ia":     resultado_ia_html,
                    "tem_ia":           bool(resultado_ia),
                    "carousel_imgs":    c_imgs,
                    "carousel_imgs_hd": c_imgs_hd,
                })

            posts_json_str = _json_posts.dumps(posts_json_data, ensure_ascii=True)
            r_seg_val = r.get("seguidores", 0)

            n_total     = len(posts_list)
            n_fotos     = sum(1 for p in posts_list if not p.get("is_video") and p.get("media_type", 1) != 8)
            n_videos    = sum(1 for p in posts_list if p.get("is_video"))
            n_carrossel = sum(1 for p in posts_list if p.get("media_type") == 8)
            total_likes = sum(p.get("likes", 0) for p in posts_list)
            total_coms  = sum(p.get("comments", 0) for p in posts_list)

            def _fmt(n):
                n = int(n or 0)
                if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
                if n >= 1_000:     return f"{n/1_000:.1f}K"
                return str(n)

            _raw_pic = r.get("profile_pic", "")
            if _raw_pic:
                img_src = _raw_pic
                avatar_html = (
                    f'<div class="avatar" id="avatar-wrap" style="padding:0;overflow:hidden;background:{cor};">'
                    f'<img src="{img_src}" id="avatar-img" '
                    f'style="width:100%;height:100%;object-fit:cover;border-radius:50%;display:block;" '
                    f'onerror="this.style.display=\'none\';'
                    f'this.parentElement.style.display=\'flex\';'
                    f'this.parentElement.style.alignItems=\'center\';'
                    f'this.parentElement.style.justifyContent=\'center\';'
                    f'this.parentElement.style.fontSize=\'18px\';'
                    f'this.parentElement.style.fontWeight=\'700\';'
                    f'this.parentElement.style.color=\'#fff\';'
                    f'this.parentElement.innerHTML=\'{avatar_letras}\';" />'
                    f'</div>'
                )
            else:
                avatar_html = f'<div class="avatar" style="background:{cor}">{avatar_letras}</div>'

            chave_criativo = f"ia_criativo_{r['handle']}"
            chave_copy     = f"ia_copy_{r['handle']}"
            chave_geral    = f"ia_geral_{r['handle']}"

            tem_criativo = bool(st.session_state.get(chave_criativo, ""))
            tem_copy     = bool(st.session_state.get(chave_copy, ""))
            tem_geral    = bool(st.session_state.get(chave_geral, ""))

            components.html(f"""
<!DOCTYPE html><html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{background:transparent;font-family:'DM Sans',sans-serif;-webkit-font-smoothing:antialiased;overflow:visible;}}
body{{padding-bottom:8px;}}

.perfil-card {{
    overflow:hidden;
}}
.perfil-header {{
    display:flex; align-items:center; gap:16px;
    padding:18px 22px 16px; border:1px solid #e5e7eb;
    border-radius: 14px 14px 0 0; background:#fff;
}}
.avatar {{
    width:52px; height:52px; border-radius:50%;
    background:{cor};
    display:flex; align-items:center; justify-content:center;
    font-size:18px; font-weight:700; color:#fff; flex-shrink:0;
}}
.info {{ flex:1; min-width:0; }}
.nome {{ font-size:20px; font-weight:700; color:#111827; letter-spacing:-0.3px; }}
.handle {{ font-size:14px; font-weight:400; color:#9ca3af; margin-left:6px; }}
.badge {{
    display:inline-block;
    background:{badge_bg}; color:{badge_txt};
    border:1px solid {badge_brd};
    padding:2px 10px; border-radius:20px;
    font-size:11px; font-weight:600; margin-top:4px;
}}
.divider-v {{ width:1px; height:44px; background:#e5e7eb; flex-shrink:0; margin:0 8px; }}
.stat-wrap {{ display:flex; align-items:center; gap:24px; flex-shrink:0; }}
.stat {{ text-align:center; }}
.stat-num {{ font-size:22px; font-weight:800; color:#111827; }}
.stat-lbl {{ font-size:12px; font-weight:600; color:#6b7280; text-transform:uppercase; margin-top:2px; }}
.btn-ig {{
    display:inline-flex; align-items:center; gap:7px;
    background:#0e2a47; color:#fff;
    padding:9px 18px; border-radius:9px;
    font-size:13px; font-weight:700; text-decoration:none;
    white-space:nowrap; flex-shrink:0; transition:background 0.15s;
}}
.btn-ig:hover {{ background:#1a3a5c; }}

.bio-section {{
    display:grid; grid-template-columns:15% 50% 35%;
     border-right:1px solid #e5e7eb; border-bottom:1px solid #e5e7eb;
     border-left:1px solid #e5e7eb; min-height:80px;
}}
.bio-label-col {{
    padding:18px 16px; border-right:1px solid #f3f4f6;
    display:flex; align-items:center; justify-content:center; background:#fafbfc;
}}
.bio-label-txt {{
    font-size:10px; font-weight:700; color:#9ca3af;
    text-transform:uppercase; letter-spacing:1px; text-align:center;
}}
.bio-left {{
    padding:18px 20px; border-right:1px solid #f3f4f6;
    display:flex; flex-direction:column; justify-content:center; gap:8px;
}}
.bio-text {{ font-size:15px; color:#374151; line-height:1.75; }}
.bio-empty {{ font-size:14px; color:#d1d5db; font-style:italic; }}
.bio-right {{
    padding:16px 20px; display:flex; flex-direction:column;
    align-items:center; justify-content:center; gap:8px; background:#fafbfc;
}}
.btn-ia {{
    width:100%; padding:10px 0; border:1px solid #3a9fd6; border-radius:8px;
    background:#eff6ff; font-size:13px; font-weight:700; color:#1d4ed8;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:background 0.15s;
    text-align:center; line-height:1;
}}
.btn-ia:hover {{ background:#dbeafe; }}
.ia-hint {{ font-size:14px; color:#9ca3af; text-align:center; line-height:1.4; }}
.bio-resultado {{
    background:#f0fdf4; border-top:1px solid #bbf7d0;
    padding:14px 20px; font-size:13px; color:#374151; line-height:1.75;
    border-bottom:1px solid #f3f4f6; display:none;
}}
.bio-resultado.show {{ display:block; }}
.bio-resultado-hdr {{
    font-size:10px; font-weight:800; color:#15803d;
    text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;
}}

/* ── BARRA DE ANÁLISES (substitui tabs-bar) ── */
.analises-bar {{
    border-right:1px solid #e5e7eb; border-bottom:1px solid #e5e7eb;
    border-left:1px solid #e5e7eb; background:#ffffff;
    padding:24px 20px 26px;
}}
.analises-bar-inner {{
    display:grid;
    grid-template-columns: 180px 1fr;
    gap:20px;
    align-items:center;
}}
.analises-bar-left {{
    display:flex;
    flex-direction:column;
    gap:6px;
}}
.analises-bar-titulo {{
    font-size:18px;
    font-weight:800;
    color:#0f1f35;
    letter-spacing:-0.3px;
    line-height:1.2;
}}
.analises-bar-sub {{
    font-size:13px;
    color:#9ca3af;
    line-height:1.5;
}}
.analises-grid {{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:12px;
}}
.atalho-card {{
    background:#fff;
    border:1px solid #e5e7eb;
    border-radius:14px;
    padding:20px 16px;
    cursor:pointer;
    font-family:'DM Sans',sans-serif;
    display:flex;
    flex-direction:row;
    align-items:flex-start;
    gap:14px;
    transition:all 0.15s;
    text-align:left;
    box-shadow:0 1px 4px rgba(0,0,0,0.04);
}}
.atalho-card:hover {{
    border-color:#c7d2fe;
    box-shadow:0 4px 16px rgba(99,102,241,0.1);
    transform:translateY(-1px);
}}
.atalho-card.done {{
    border-color:#bbf7d0;
    background:#f0fdf4;
}}
.atalho-card.done:hover {{
    border-color:#22c55e;
    box-shadow:0 4px 16px rgba(34,197,94,0.1);
}}
.atalho-icon-wrap {{
    width:46px;height:46px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    flex-shrink:0;font-size:22px;
}}
.atalho-icon-wrap.blue  {{ background:#e0f0ff; }}
.atalho-icon-wrap.green {{ background:#e4f9ee; }}
.atalho-icon-wrap.purple{{ background:#ede9fe; }}
.atalho-text {{ display:flex;flex-direction:column;gap:3px; }}
.atalho-nome {{ font-size:14px;font-weight:700;color:#111827; }}
.atalho-desc {{ font-size:12px;color:#9ca3af;line-height:1.4; }}
.atalho-card.done .atalho-desc {{ color:#15803d;font-weight:600; }}

.filters-bar {{
    display:flex; align-items:center; gap:10px;
    padding:16px 20px;
    border:1px solid #e5e7eb; border-top:none;
    background:#fff; flex-wrap:wrap;
    border-radius: 0 0 12px 12px !important;
}}
.filter-input {{
    flex:1; min-width:160px;height:40px;
    padding:0 14px; border:1px solid #f0f4f8; border-radius:8px;
    font-size:14px; font-family:'DM Sans',sans-serif; color:#374151;
    background:#fafafa; outline:none; transition:border-color 0.15s;
}}
.filter-input:focus {{ border-color:#3a9fd6; background:#fff; }}
.filter-input::placeholder {{ color:#6b7280; }}
.filter-select {{
    height:40px; padding:0 32px 0 12px;
    border:2px solid #e5e7eb; border-radius:8px;
    font-size:14px; font-family:'DM Sans',sans-serif; color:#374151;
    background:#fff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2.5'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E") no-repeat right 10px center;
    -webkit-appearance:none; appearance:none; cursor:pointer; outline:none;
}}
.filter-select:focus {{ border-color:#3a9fd6; }}
.col-toggle {{
    margin-left:auto; width:40px; height:40px;
    border:1px solid #e5e7eb; border-radius:8px;
    background:#fff; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    color:#6b7280; flex-shrink:0; transition:all 0.12s;
}}
.col-toggle:hover {{ border-color:#3a9fd6; color:#1d4ed8; background:#eff6ff; }}

.stats-row {{ display:flex; gap:12px; padding:16px 0 4px; flex-wrap:wrap; }}
.stat-card {{
    flex:1; min-width:90px; background:#fff;
    border:1px solid #e5e7eb; border-radius:12px;
    padding:14px 10px; text-align:center;
}}
.stat-num2 {{ font-size:22px; font-weight:800; color:#0f1f35; line-height:1; margin-bottom:5px; }}
.stat-lbl2 {{ font-size:12px; font-weight:600; color:#9ca3af; text-transform:uppercase; }}

.posts-grid {{ display:grid; gap:12px; margin-top:16px; }}

.post-card {{
    background:#fff; border:1px solid #e5e7eb;
    display:flex; flex-direction:column; overflow:hidden;
    position:relative; border-radius:14px;
    box-shadow:0 1px 4px rgba(0,0,0,0.06);
    transition:box-shadow 0.15s, border-color 0.15s;
}}
.post-card:hover {{ border-color:#6fd1f3; box-shadow:0 4px 16px rgba(58,159,214,0.12); }}
.thumb-wrap {{
    position:relative; width:100%; aspect-ratio:1/1;
    background:#f0f2f5; overflow:hidden; flex-shrink:0; cursor:pointer;
}}
.thumb-wrap img {{ width:100%; height:100%; object-fit:cover; display:block; }}
.thumb-fallback {{
    width:100%; height:100%;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    background:linear-gradient(135deg,#e9eef5,#d2dde9); gap:6px; cursor:pointer;
}}
.zoom-badge {{
    position:absolute; bottom:8px; right:8px;
    background:rgba(0,0,0,0.45); color:#fff;
    font-size:10px; font-weight:600; padding:3px 8px;
    border-radius:6px; pointer-events:none;
    display:flex; align-items:center; gap:4px;
}}
.metrics-row {{
    display:grid; grid-template-columns:2fr 1fr 1fr 1fr;
    border-bottom:1px solid #f3f4f6; background:#fafbfc;
}}
.metric-cell {{ padding:8px 6px; text-align:center; border-right:1px solid #f3f4f6; }}
.metric-cell:last-child {{ border-right:none; }}
.metric-cell-lbl {{ font-size:13px; margin-bottom:2px; line-height:1; }}
.metric-cell-val {{ font-size:13px; font-weight:800; color:#111827; }}
.metric-cell-val.eng {{ color:#3a9fd6; }}
.card-caption-wrap {{ padding:10px 12px 8px; flex:1; }}
.card-caption {{
    font-size:12px; color:#374151; line-height:1.55; word-break:break-word;
    display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;
}}
.card-caption.expanded {{ display:block; -webkit-line-clamp:unset; }}
.ver-copy-btn {{
    background:none; border:none; padding:2px 0 0;
    font-size:11px; font-weight:700; color:#3a9fd6;
    cursor:pointer; font-family:'DM Sans',sans-serif;
    display:block; margin-top:4px; transition:color 0.12s;
}}
.ver-copy-btn:hover {{ color:#065f9e; }}
.no-caption {{ font-size:12px; color:#d1d5db; font-style:italic; }}
.card-footer-btns {{ display:grid; grid-template-columns:1fr 1fr; border-top:1px solid #f3f4f6; margin-top:auto; }}
.footer-btn {{
    padding:10px 6px; display:flex; align-items:center; justify-content:center; gap:6px;
    font-size:12px; font-weight:700; border:none; background:#eff6ff;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:background 0.12s;
    text-decoration:none; color:#275f8d;
}}
.footer-btn:hover {{ background:#13649a; color:#ffffff !important; }}
.footer-btn.ig {{ border-right:1px solid #ffffff; }}
.post-ia-panel {{
    border-top:1px solid #bbf7d0; background:#f0fdf4;
    padding:12px 14px; font-size:12px; color:#374151; line-height:1.7;
    max-height:200px; overflow-y:auto;
}}
.post-ia-hdr {{
    font-size:10px; font-weight:800; color:#15803d;
    text-transform:uppercase; letter-spacing:0.5px;
    margin-bottom:6px; display:flex; align-items:center; gap:5px;
}}

.carousel-dots {{
    position:absolute; bottom:32px; left:50%; transform:translateX(-50%);
    display:flex; gap:4px; pointer-events:none;
}}
.carousel-dot {{
    width:5px; height:5px; border-radius:50%;
    background:rgba(255,255,255,0.5);
}}
.carousel-dot.first {{
    background:rgba(255,255,255,0.95);
    width:7px; height:7px;
}}

.no-posts {{
    background:#fff; border:1px solid #e5e7eb; border-top:none;
    border-radius:0 0 12px 12px; padding:48px 32px; text-align:center;
}}
</style>
</head>
<body>

<div class="perfil-card">
    <div class="perfil-header">
        {avatar_html}
        <div class="info">
            <div class="nome">{r["nome"]}<span class="handle">{r.get("handle","")}</span></div>
            <div class="badge">{badge_lbl}</div>
        </div>
        <div class="stat-wrap">
            <div class="divider-v"></div>
            <div class="stat">
                <div class="stat-num">{seg_fmt}</div>
                <div class="stat-lbl">Seguidores</div>
            </div>
            <div class="divider-v"></div>
            <div class="stat">
                <div class="stat-num">{posts_fmt}</div>
                <div class="stat-lbl">Postagens</div>
            </div>
            <div class="divider-v"></div>
            <a class="btn-ig" href="{ig_url}" target="_blank">Ver no Instagram</a>
        </div>
    </div>

    <!-- BIO + SCORE -->
    <div style="display:grid;grid-template-columns:1fr auto 1fr;
                border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;
                border-left:1px solid #e5e7eb;min-height:170px;background:#ffffff;">

        <!-- Coluna esquerda: bio -->
        <div style="padding:20px 24px;display:flex;flex-direction:column;gap:10px;">
            <div style="font-size:10px;font-weight:700;color:#9ca3af;
                        text-transform:uppercase;letter-spacing:1px;">BIO DO PERFIL</div>
            <div style="display:flex;flex-direction:column;gap:8px;flex:1;justify-content:center;">
                {('<div style="font-size:15px;color:#374151;line-height:1.75;">&ldquo;' + bio_txt + '&rdquo;</div>') if bio_txt else '<div style="font-size:14px;color:#d1d5db;font-style:italic;">Sem bio cadastrada neste perfil.</div>'}
                {('<div style="display:flex;align-items:center;gap:6px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3a9fd6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg><a href="' + ext_url + '" target="_blank" style="font-size:13px;font-weight:600;color:#3a9fd6;text-decoration:none;word-break:break-all;">' + ext_url_display + '</a></div>') if ext_url else ''}
            </div>
        </div>

        <!-- Divisor vertical -->
        <div style="width:1px;background:#e5e7eb;flex-shrink:0;"></div>

        <!-- Coluna direita: Score -->
        <div style="padding:20px 24px;display:flex;flex-direction:column;gap:10px;min-width:300px;">
            <!-- Header score -->
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                <div style="font-size:10px;font-weight:700;color:#9ca3af;
                            text-transform:uppercase;letter-spacing:1px;">SCORE DE PERFIL</div>
                <div style="display:inline-flex;align-items:center;gap:7px;
                            padding:8px 18px;border-radius:24px;font-size:15px;font-weight:800;
                            background:{score_bg};color:{score_cor};border:1.5px solid {score_brd};
                            letter-spacing:0.1px;">
                    {score_icon} {score_cls}
                </div>
            </div>
            <!-- Número + barra -->
            <div style="display:flex;align-items:baseline;gap:4px;line-height:1;">
                <span style="font-size:42px;font-weight:900;letter-spacing:-2px;
                             line-height:1;color:{score_cor};">{score_val}</span>
                <span style="font-size:16px;font-weight:600;color:#9ca3af;">/100</span>
            </div>
            <div style="height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden;margin-bottom:2px;">
                <div id="score-bar-fill"
                     style="height:100%;width:0%;border-radius:4px;
                            background:linear-gradient(90deg,#3b82f6,{score_cor});
                            transition:width 1.2s cubic-bezier(0.4,0,0.2,1);"></div>
            </div>
        </div>
    </div>

<!-- INSIGHTS DE IA -->
    <div style="border-right:1px solid #e5e7eb;border-left:1px solid #e5e7eb;
                background:#f8fbff;padding:20px 24px;border-bottom:1px solid #e5e7eb;">
        <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;">

            <!-- Ícone + título + descrição -->
            <div style="display:flex;align-items:flex-start;gap:10px;min-width:200px;max-width:300px;flex-shrink:0;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" style="flex-shrink:0;margin-top:2px;">
                    <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"
                          fill="#3b82f6" stroke="#3b82f6" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <div>
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;">
                        <span style="font-size:13px;font-weight:800;color:#1a2e4a;
                                     text-transform:uppercase;letter-spacing:0.5px;">Insights de IA</span>
                        <span style="background:#dbeafe;color:#1d4ed8;font-size:10px;font-weight:800;
                                     padding:2px 8px;border-radius:20px;letter-spacing:0.5px;">BETA</span>
                    </div>
                    <div style="font-size:12px;color:#6b7280;line-height:1.55;">
                        Nossa IA analisou seu posicionamento e identificou os principais pontos de atenção e oportunidades para crescimento.
                    </div>
                </div>
            </div>

            <!-- Chips dos critérios OK + oportunidades juntos -->
            <div id="insights-chips-row"
                 style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;flex:1;min-width:0;">
                 <!-- oportunidade será injetada pelo JS junto dos chips -->
            </div>

            <!-- Botão -->
            <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;flex-shrink:0;">
                <button onclick="triggerBio()"
                        style="display:inline-flex;align-items:center;justify-content:center;gap:8px;
                               padding:0;border:none;background:transparent;
                               font-size:14px;font-weight:700;color:#1d4ed8;
                               cursor:pointer;font-family:\'DM Sans\',sans-serif;white-space:nowrap;
                               text-decoration:none;letter-spacing:0.1px;">
                    {'Ver análise completa →' if bio_resultado_html else 'Ver análise completa →'}
                </button>
            </div>

        </div>
    </div>

    <!-- Resultado da análise de bio -->
    <div id="bio-res"
         style="background:#f0fdf4;border-top:1px solid #bbf7d0;
                border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;
                border-left:1px solid #e5e7eb;padding:14px 20px;
                font-size:13px;color:#374151;line-height:1.75;
                {'display:block' if bio_resultado_html else 'display:none'}">
        <div style="font-size:10px;font-weight:800;color:#15803d;
                    text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
            ✨ Análise de Perfil
        </div>
        {bio_resultado_html}
    </div>

    <div class="analises-bar">
    <div class="analises-bar-inner">
        <div class="analises-bar-left">
            <div class="analises-bar-titulo">Gerar análises</div>
            <div class="analises-bar-sub">Escolha o tipo de análise que deseja executar nas postagens.</div>
        </div>
        <div class="analises-grid">
            <button class="atalho-card {'done' if tem_criativo else ''}" onclick="trigger('criativo_{aba_ativa}')">
                <div class="atalho-icon-wrap blue">🎨</div>
                <div class="atalho-text">
                    <span class="atalho-nome">Analisar criativos</span>
                    <span class="atalho-desc">{'✅ Gerado' if tem_criativo else 'Avalie seus conteúdos visuais, identidade e estilo de comunicação.'}</span>
                </div>
            </button>
            <button class="atalho-card {'done' if tem_copy else ''}" onclick="trigger('copy_{aba_ativa}')">
                <div class="atalho-icon-wrap green">✏️</div>
                <div class="atalho-text">
                    <span class="atalho-nome">Analisar copy</span>
                    <span class="atalho-desc">{'✅ Gerado' if tem_copy else 'Analise textos, legendas, tom de voz e gatilhos de conversão.'}</span>
                </div>
            </button>
            <button class="atalho-card {'done' if tem_geral else ''}" onclick="trigger('geral_{aba_ativa}')">
                <div class="atalho-icon-wrap purple">📊</div>
                <div class="atalho-text">
                    <span class="atalho-nome">Analisar estratégia</span>
                    <span class="atalho-desc">{'✅ Gerado' if tem_geral else 'Avalie posicionamento, oferta, público e oportunidades de crescimento.'}</span>
                </div>
            </button>
        </div>
    </div>
</div>

{"" if posts_list else '<div class="no-posts"><div style="font-size:28px;margin-bottom:10px">📸</div><div style="font-size:15px;font-weight:600;color:#374151;margin-bottom:6px">Sem postagens disponíveis</div><div style="font-size:13px;color:#9ca3af">Colete os dados novamente para carregar as postagens.</div></div>'}

{f"""
<div class="filters-bar">
    <input class="filter-input" id="filter-text" type="text" placeholder="Pesquisar no copy..." oninput="applyFilters()" />
    <select class="filter-select" id="filter-tipo" onchange="applyFilters()">
        <option value="todos">Tipo de Postagem (todos)</option>
        <option value="foto">Fotos</option>
        <option value="video">Vídeos</option>
        <option value="carrossel">Carrossel</option>
    </select>
    <select class="filter-select" id="filter-ordem" onchange="applyFilters()">
        <option value="recentes">Mais recentes</option>
        <option value="likes">Mais curtidas</option>
        <option value="eng">Maior engajamento</option>
    </select>
    <button class="col-toggle" onclick="toggleCols()" title="Alternar colunas">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="5" height="18" rx="1"/>
            <rect x="10" y="3" width="5" height="18" rx="1"/>
            <rect x="17" y="3" width="5" height="18" rx="1"/>
        </svg>
    </button>
</div>

<div class="stats-row">
    <div class="stat-card"><div class="stat-num2" id="stat-total">{n_total}</div><div class="stat-lbl2">Postagens</div></div>
    <div class="stat-card"><div class="stat-num2" id="stat-fotos">{n_fotos}</div><div class="stat-lbl2">Fotos</div></div>
    <div class="stat-card"><div class="stat-num2" id="stat-videos">{n_videos}</div><div class="stat-lbl2">Vídeos</div></div>
    <div class="stat-card"><div class="stat-num2" id="stat-carrossel">{n_carrossel}</div><div class="stat-lbl2">Carrossel</div></div>
    <div class="stat-card"><div class="stat-num2" id="stat-likes">{_fmt(total_likes)}</div><div class="stat-lbl2">Curtidas</div></div>
    <div class="stat-card"><div class="stat-num2" id="stat-coms">{_fmt(total_coms)}</div><div class="stat-lbl2">Comentários</div></div>
</div>

<div class="posts-grid" id="posts-grid"></div>
""" if posts_list else ""}

<script>
var ALL_POSTS = {posts_json_str if posts_list else "[]"};
var N_COLS    = {n_cols_posts};
var R_SEG     = {r_seg_val};

var POST_STORE = {{}};
ALL_POSTS.forEach(function(p) {{ POST_STORE[p.jp] = p; }});

function fmtNum(n) {{
    n = Math.round(n || 0);
    if (n >= 1000000) return (n/1000000).toFixed(1) + 'M';
    if (n >= 1000)    return (n/1000).toFixed(1) + 'K';
    return String(n);
}}

function upgradeCdnUrl(url) {{
    if (!url) return url;
    try {{
        var upgraded = url
            .replace(/\/s\d+x\d+\//g, '/s1440x1440/')
            .replace(/\/p\d+x\d+\//g, '/p1440x1440/')
            .replace(/\/c\d+\.\d+\.\d+\.\d+\//g, '/');
        return upgraded;
    }} catch(e) {{ return url; }}
}}

function updateStats(posts) {{
    var nF = posts.filter(function(p){{ return !p.is_video && p.media_type !== 8; }}).length;
    var nV = posts.filter(function(p){{ return  p.is_video; }}).length;
    var nC = posts.filter(function(p){{ return  p.media_type === 8; }}).length;
    var tL = posts.reduce(function(s,p){{ return s+(p.likes||0); }}, 0);
    var tC = posts.reduce(function(s,p){{ return s+(p.comments||0); }}, 0);
    document.getElementById('stat-total').textContent     = posts.length;
    document.getElementById('stat-fotos').textContent     = nF;
    document.getElementById('stat-videos').textContent    = nV;
    document.getElementById('stat-carrossel').textContent = nC;
    document.getElementById('stat-likes').textContent     = fmtNum(tL);
    document.getElementById('stat-coms').textContent      = fmtNum(tC);
}}

function openModalByIdx(idx) {{
    var p = POST_STORE[idx];
    if (!p) return;
    var imgs = [];
    if (p.media_type === 8) {{
        imgs = (p.carousel_imgs_hd && p.carousel_imgs_hd.length)
            ? p.carousel_imgs_hd
            : (p.carousel_imgs && p.carousel_imgs.length ? p.carousel_imgs : []);
    }} else if (!p.is_video) {{
        imgs = [p.thumb_hd || p.thumb || ''];
    }}
    openModal(p.thumb_hd || p.thumb || '', p.ig_url || '#', p.video_url || '', p.is_video, imgs);
}}

function _showVideoFallback(content, doc, thumbUrl, igUrl) {{
    var wrap = doc.createElement('div');
    wrap.style.cssText = 'position:relative;display:inline-flex;flex-direction:column;align-items:center;';
    if (thumbUrl) {{
        var img = doc.createElement('img');
        img.src = thumbUrl;
        img.style.cssText = 'display:block;max-width:min(84vw,820px);max-height:min(70vh,700px);width:auto;height:auto;object-fit:contain;border-radius:10px;filter:brightness(0.6);';
        wrap.appendChild(img);
    }}
    var playBtn = doc.createElement('a');
    playBtn.href = igUrl; playBtn.target = '_blank';
    playBtn.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:10px;text-decoration:none;';
    playBtn.innerHTML = '<div style="width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,0.92);display:flex;align-items:center;justify-content:center;box-shadow:0 4px 20px rgba(0,0,0,0.4);"><svg width="22" height="22" viewBox="0 0 54 54" fill="none"><polygon points="18,12 44,27 18,42" fill="#E1306C"/></svg></div><span style="color:#fff;font-size:13px;font-weight:700;font-family:DM Sans,sans-serif;background:rgba(0,0,0,0.5);padding:5px 14px;border-radius:20px;">Ver vídeo no Instagram</span>';
    wrap.appendChild(playBtn);
    content.appendChild(wrap);
}}

function openModal(thumbUrl, igUrl, videoUrl, isVideo, carouselImgs) {{
    var doc = window.parent.document;
    var old = doc.getElementById('redes_modal_overlay');
    if (old) old.remove();
    var overlay = doc.createElement('div');
    overlay.id = 'redes_modal_overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:999999;display:flex;align-items:center;justify-content:center;padding:20px;';
    overlay.onclick = function(e) {{ if (e.target === overlay) closeModal(); }};
    var box = doc.createElement('div');
    box.style.cssText = 'background:#111;border-radius:16px;overflow:hidden;position:relative;display:inline-flex;flex-direction:column;align-items:center;max-width:min(88vw,860px);max-height:90vh;';
    var closeBtn = doc.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = 'position:absolute;top:10px;right:12px;background:#0e1e35;border:1px solid #1e395e;border-radius:50%;width:34px;height:34px;font-size:17px;color:#22c45e;cursor:pointer;z-index:10;display:flex;align-items:center;justify-content:center;';
    closeBtn.onclick = closeModal;
    var content = doc.createElement('div');
    content.id = 'redes_modal_content';
    content.style.cssText = 'display:flex;align-items:center;justify-content:center;position:relative;min-width:280px;min-height:200px;';
    box.appendChild(closeBtn); box.appendChild(content); overlay.appendChild(box); doc.body.appendChild(overlay);
    window.parent.__redesModalEscFn = function(e) {{ if (e.key === 'Escape') closeModal(); }};
    doc.addEventListener('keydown', window.parent.__redesModalEscFn);
    if (isVideo) {{
        if (videoUrl) {{
            var vid = doc.createElement('video');
            vid.src = videoUrl; vid.controls = true; vid.autoplay = true; vid.playsInline = true;
            vid.style.cssText = 'display:block;max-width:min(84vw,820px);max-height:min(82vh,700px);width:auto;height:auto;border-radius:10px;background:#000;outline:none;';
            vid.onerror = function() {{ content.innerHTML = ''; _showVideoFallback(content, doc, thumbUrl, igUrl); }};
            content.appendChild(vid);
        }} else {{ _showVideoFallback(content, doc, thumbUrl, igUrl); }}
        return;
    }}
    var imgs = (carouselImgs && carouselImgs.length > 0) ? carouselImgs : (thumbUrl ? [thumbUrl] : []);
    if (!imgs.length) {{ window.parent.open(igUrl, '_blank'); closeModal(); return; }}
    var curIdx = 0;
    function renderSlide(i) {{
        content.innerHTML = '';
        var spinner = doc.createElement('div');
        spinner.id = 'modal_spinner';
        spinner.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.4);border-radius:10px;z-index:5;';
        spinner.innerHTML = '<div style="width:36px;height:36px;border:3px solid rgba(255,255,255,0.2);border-top-color:#fff;border-radius:50%;animation:spin 0.7s linear infinite;"></div>';
        content.appendChild(spinner);
        var img = doc.createElement('img');
        img.style.cssText = 'display:block;max-width:min(84vw,820px);max-height:min(76vh,820px);width:auto;height:auto;object-fit:contain;border-radius:10px;opacity:0;transition:opacity 0.2s;';
        var hdUrl = upgradeCdnUrl(imgs[i]);
        var originalUrl = imgs[i];
        var triedOriginal = (hdUrl === originalUrl);
        img.onload = function() {{ var sp = doc.getElementById('modal_spinner'); if (sp) sp.remove(); img.style.opacity = '1'; }};
        img.onerror = function() {{
            if (!triedOriginal) {{ triedOriginal = true; img.src = originalUrl; return; }}
            var sp = doc.getElementById('modal_spinner'); if (sp) sp.remove();
            img.style.display = 'none';
            var fb = doc.createElement('div');
            fb.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:16px;padding:48px 40px;font-family:DM Sans,sans-serif;';
            fb.innerHTML = '<p style="color:rgba(255,255,255,0.6);font-size:13px">Imagem não disponível (URL expirada).</p><a href="' + igUrl + '" target="_blank" style="display:inline-flex;align-items:center;gap:8px;background:#E1306C;color:#fff;padding:14px 28px;border-radius:10px;font-size:15px;font-weight:700;text-decoration:none;">↗ Ver no Instagram</a>';
            content.appendChild(fb);
        }};
        img.src = hdUrl; content.appendChild(img);
        if (imgs.length > 1) {{
            var counter = doc.createElement('div');
            counter.style.cssText = 'position:absolute;top:10px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.55);color:#fff;font-size:12px;font-weight:700;padding:4px 14px;border-radius:20px;font-family:DM Sans,sans-serif;pointer-events:none;white-space:nowrap;z-index:6;';
            counter.textContent = (i + 1) + ' / ' + imgs.length; content.appendChild(counter);
            var dotsWrap = doc.createElement('div');
            dotsWrap.style.cssText = 'position:absolute;bottom:12px;left:50%;transform:translateX(-50%);display:flex;gap:5px;pointer-events:none;z-index:6;';
            for (var d = 0; d < imgs.length; d++) {{
                var dot = doc.createElement('div');
                dot.style.cssText = 'width:' + (d === i ? '18px' : '6px') + ';height:6px;border-radius:3px;background:' + (d === i ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.4)') + ';transition:all 0.2s;';
                dotsWrap.appendChild(dot);
            }}
            content.appendChild(dotsWrap);
            if (i > 0) {{
                var prev = doc.createElement('button');
                prev.innerHTML = '&#8249;';
                prev.style.cssText = 'position:absolute;left:-26px;top:50%;transform:translateY(-50%);width:48px;height:48px;border-radius:50%;background:rgba(255,255,255,0.15);border:none;color:#fff;font-size:32px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background 0.15s;line-height:1;z-index:6;';
                prev.onmouseover = function() {{ this.style.background = 'rgba(255,255,255,0.28)'; }};
                prev.onmouseout  = function() {{ this.style.background = 'rgba(255,255,255,0.15)'; }};
                prev.onclick = function(e) {{ e.stopPropagation(); curIdx--; renderSlide(curIdx); }};
                content.appendChild(prev);
            }}
            if (i < imgs.length - 1) {{
                var next = doc.createElement('button');
                next.innerHTML = '&#8250;';
                next.style.cssText = 'position:absolute;right:-26px;top:50%;transform:translateY(-50%);width:48px;height:48px;border-radius:50%;background:rgba(255,255,255,0.15);border:none;color:#fff;font-size:32px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background 0.15s;line-height:1;z-index:6;';
                next.onmouseover = function() {{ this.style.background = 'rgba(255,255,255,0.28)'; }};
                next.onmouseout  = function() {{ this.style.background = 'rgba(255,255,255,0.15)'; }};
                next.onclick = function(e) {{ e.stopPropagation(); curIdx++; renderSlide(curIdx); }};
                content.appendChild(next);
            }}
            var kbFn = function(e) {{
                if (e.key === 'ArrowLeft'  && curIdx > 0)              {{ curIdx--; renderSlide(curIdx); }}
                if (e.key === 'ArrowRight' && curIdx < imgs.length - 1) {{ curIdx++; renderSlide(curIdx); }}
            }};
            doc.removeEventListener('keydown', window.parent.__redesModalEscFn);
            window.parent.__redesModalEscFn = function(e) {{ if (e.key === 'Escape') {{ closeModal(); return; }} kbFn(e); }};
            doc.addEventListener('keydown', window.parent.__redesModalEscFn);
        }}
    }}
    var styleEl = doc.getElementById('redes_modal_spinner_style');
    if (!styleEl) {{
        styleEl = doc.createElement('style');
        styleEl.id = 'redes_modal_spinner_style';
        styleEl.textContent = '@keyframes spin {{ to {{ transform: rotate(360deg); }} }}';
        doc.head.appendChild(styleEl);
    }}
    renderSlide(0);
}}

function closeModal() {{
    var doc = window.parent.document;
    var overlay = doc.getElementById('redes_modal_overlay');
    if (overlay) overlay.remove();
    if (window.parent.__redesModalEscFn) {{
        doc.removeEventListener('keydown', window.parent.__redesModalEscFn);
        window.parent.__redesModalEscFn = null;
    }}
}}

function getFiltered() {{
    var texto = (document.getElementById('filter-text') ? document.getElementById('filter-text').value : '').toLowerCase().trim();
    var tipo  = document.getElementById('filter-tipo')  ? document.getElementById('filter-tipo').value  : 'todos';
    var ordem = document.getElementById('filter-ordem') ? document.getElementById('filter-ordem').value : 'recentes';
    var posts = ALL_POSTS.slice();
    if (texto)           posts = posts.filter(function(p){{ return (p.caption||'').toLowerCase().indexOf(texto) !== -1; }});
    if (tipo === 'foto')      posts = posts.filter(function(p){{ return !p.is_video && p.media_type !== 8; }});
    if (tipo === 'video')     posts = posts.filter(function(p){{ return  p.is_video; }});
    if (tipo === 'carrossel') posts = posts.filter(function(p){{ return  p.media_type === 8; }});
    if (ordem === 'likes') posts.sort(function(a,b){{ return (b.likes||0)-(a.likes||0); }});
    else if (ordem === 'eng') posts.sort(function(a,b){{ return ((b.likes||0)+(b.comments||0))-((a.likes||0)+(a.comments||0)); }});
    return posts;
}}

function buildGrid(posts) {{
    var grid = document.getElementById('posts-grid');
    if (!grid) return;
    grid.style.gridTemplateColumns = 'repeat(' + N_COLS + ', 1fr)';
    grid.innerHTML = '';
    posts.forEach(function(p) {{
        var idx        = p.jp;
        var hasCaption = !!(p.caption && p.caption.trim());
        var mediaType  = p.media_type || 1;
        var typeLbl    = mediaType === 8 ? 'Carrossel' : (mediaType === 2 ? 'Vídeo' : 'Foto');
        var badgeColor = mediaType === 8 ? '#7c3aed'   : (mediaType === 2 ? '#e1306c' : '#0ea5e9');
        var badgeIcon;
        if (mediaType === 2) {{ badgeIcon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="white"><polygon points="5,3 19,12 5,21"/></svg>'; }}
        else if (mediaType === 8) {{ badgeIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round"><rect x="2" y="2" width="20" height="20" rx="2"/><line x1="8" y1="2" x2="8" y2="22"/><line x1="16" y1="2" x2="16" y2="22"/></svg>'; }}
        else {{ badgeIcon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><circle cx="8.5" cy="8.5" r="1.5" fill="white"/><polyline points="21 15 16 10 5 21"/></svg>'; }}
        var thumbUrl     = (p.thumb  || '').trim();
        var engTotal     = (p.likes||0) + (p.comments||0);
        var igUrl        = p.ig_url || '#';
        var iconFallback = mediaType === 2 ? '🎬' : (mediaType === 8 ? '🖼️' : '📷');
        var nSlides = (p.carousel_imgs_hd && p.carousel_imgs_hd.length) || (p.carousel_imgs && p.carousel_imgs.length) || 0;
        var dotsHtml = '';
        if (mediaType === 8 && nSlides > 1) {{
            dotsHtml = '<div class="carousel-dots">';
            var maxDots = Math.min(nSlides, 5);
            for (var d = 0; d < maxDots; d++) {{ dotsHtml += '<div class="carousel-dot' + (d === 0 ? ' first' : '') + '"></div>'; }}
            if (nSlides > 5) dotsHtml += '<div class="carousel-dot" style="opacity:0.4">…</div>';
            dotsHtml += '</div>';
        }}
        var playOverlay = p.is_video
            ? '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;"><div style="width:52px;height:52px;border-radius:50%;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;"><svg width="20" height="20" viewBox="0 0 54 54" fill="none"><polygon points="18,12 44,27 18,42" fill="white"/></svg></div></div>'
            : '';
        var thumbInner = thumbUrl
            ? '<img id="pimg_' + idx + '" src="' + thumbUrl + '" loading="lazy" alt="" />' + playOverlay + dotsHtml
            : '<div class="thumb-fallback" onclick="openModalByIdx(' + idx + ')"><span style="font-size:28px">' + iconFallback + '</span><span style="font-size:11px;color:#9ca3af;margin-top:4px">Sem imagem</span></div>' + dotsHtml;
        var card = document.createElement('div');
        card.className = 'post-card'; card.id = 'pcard_' + idx;
        card.innerHTML =
            '<div class="thumb-wrap" id="tw_' + idx + '" onclick="openModalByIdx(' + idx + ')">' + thumbInner
            + '<div class="zoom-badge" style="background:' + badgeColor + 'cc">' + badgeIcon + ' ' + typeLbl + '</div></div>'
            + '<div class="metrics-row">'
            + '<div class="metric-cell"><span class="metric-cell-val" style="font-size:11px;font-weight:700">' + (p.date || '—') + '</span></div>'
            + '<div class="metric-cell"><span class="metric-cell-lbl">❤️</span><span class="metric-cell-val">' + fmtNum(p.likes||0) + '</span></div>'
            + '<div class="metric-cell"><span class="metric-cell-lbl">💬</span><span class="metric-cell-val">' + fmtNum(p.comments||0) + '</span></div>'
            + '<div class="metric-cell"><span class="metric-cell-lbl">⚡</span><span class="metric-cell-val eng">' + fmtNum(engTotal) + '</span></div>'
            + '</div>'
            + '<div class="card-caption-wrap">'
            + (hasCaption ? '<div class="card-caption" id="cap_' + idx + '">' + p.caption + '</div><button class="ver-copy-btn" id="vcb_' + idx + '" onclick="toggleCopy(' + idx + ')">ver mais</button>' : '<span class="no-caption">Sem legenda</span>')
            + '</div>'
            + (p.resultado_ia ? '<div class="post-ia-panel"><div class="post-ia-hdr">✨ Análise de IA</div>' + p.resultado_ia + '</div>' : '')
            + '<div class="card-footer-btns">'
            + (igUrl && igUrl !== '#' ? '<a class="footer-btn ig" href="' + igUrl + '" target="_blank">Ver no Instagram</a>' : '<span class="footer-btn ig" style="opacity:0.35;cursor:default;pointer-events:none">Sem link</span>')
            + '<button class="footer-btn ia" id="ia_btn_' + idx + '" onclick="analisarPost(' + idx + ')">' + (p.tem_ia ? 'Reanalisar' : 'Analisar postagem') + '</button>'
            + '</div>';
        if (thumbUrl) {{
            var imgEl = card.querySelector('#pimg_' + idx);
            if (imgEl) {{
                imgEl.onerror = (function(i, icon) {{
                    return function() {{
                        var tw = document.getElementById('tw_' + i);
                        if (tw) {{ tw.innerHTML = '<div class="thumb-fallback" onclick="openModalByIdx(' + i + ')"><span style="font-size:28px">' + icon + '</span><span style="font-size:11px;color:#9ca3af;margin-top:4px">Sem imagem</span></div>'; }}
                    }};
                }})(idx, iconFallback);
            }}
        }}
        grid.appendChild(card);
    }});
    syncHeight();
}}

function toggleCopy(idx) {{
    var capEl = document.getElementById('cap_' + idx);
    var btn   = document.getElementById('vcb_' + idx);
    if (!capEl || !btn) return;
    var expanded = capEl.classList.contains('expanded');
    capEl.classList.toggle('expanded', !expanded);
    btn.textContent = expanded ? 'ver mais' : 'ver menos';
    setTimeout(syncHeight, 60);
}}

function analisarPost(idx) {{
    var btn = document.getElementById('ia_btn_' + idx);
    if (btn) {{ btn.textContent = 'Analisando…'; btn.style.opacity = '0.6'; btn.style.pointerEvents = 'none'; }}
    var label = 'post_ia_{aba_ativa}_' + idx;
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}

// Animar barra de score
(function() {{
    var fill = document.getElementById('score-bar-fill');
    if (fill) {{ setTimeout(function() {{ fill.style.width = '{score_val}%'; }}, 200); }}
}})();

// Renderizar critérios OK
(function() {{
    var crits = {score_crit_json};
    var html = '';
    crits.filter(function(c) {{ return c.ok; }}).forEach(function(c) {{
        html += '<div style="display:inline-flex;align-items:center;gap:5px;font-size:12px;'
              + 'font-weight:600;color:#15803d;background:#f0fdf4;border:1px solid #bbf7d0;'
              + 'padding:5px 12px;border-radius:20px;">'
              + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#15803d" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
              + ' ' + c.label + '</div>';
    }});
    var row1 = document.getElementById('insights-crit-row');
    if (row1) row1.innerHTML = html;
    var row2 = document.getElementById('insights-chips-row');
    if (row2) {{
        row2.innerHTML = html + '{"<div style=\'display:inline-flex;align-items:center;font-size:12px;font-weight:700;color:#2563eb;background:#dbeafe;border:1px solid #bfdbfe;padding:5px 12px;border-radius:20px;white-space:nowrap;\'>+" + str(score_oport) + " oportunidade" + ("s" if score_oport != 1 else "") + "</div>" if score_oport > 0 else ""}';
    }}
}})();

function applyFilters() {{
    var posts = getFiltered();
    updateStats(posts);
    buildGrid(posts);
}}

function toggleCols() {{
    var btns = window.parent.document.querySelectorAll('button');
    var label = 'posts_toggle_{aba_ativa}';
    for (var b of btns) {{ if ((b.textContent||b.innerText||'').split(/\s+/).join(' ').trim() === label) {{ b.click(); return; }} }}
}}

function triggerBio() {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === '__bio_{aba_ativa}__') {{ b.click(); return; }}
    }}
}}

function trigger(label) {{
    var searches = [window.parent.document, document];
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var fi = 0; fi < frames.length; fi++) {{
        try {{ if (frames[fi].contentDocument) searches.push(frames[fi].contentDocument); }} catch(e) {{}}
    }}
    for (var si = 0; si < searches.length; si++) {{
        try {{
            var btns = searches[si].querySelectorAll('button');
            for (var bi = 0; bi < btns.length; bi++) {{
                var txt = (btns[bi].textContent || btns[bi].innerText || '').split(/\s+/).join(' ').trim();
                if (txt === label) {{
                    var btn = btns[bi];
                    setTimeout(function() {{ btn.click(); }}, 50);
                    return;
                }}
            }}
        }} catch(e) {{}}
    }}
}}

function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {{
        try {{
            if (frames[i].contentWindow === window) {{
                frames[i].style.height = (h + 12) + 'px';
                frames[i].style.marginTop = '-277px';
                break;
            }}
        }} catch(e) {{}}
    }}
}}

applyFilters();
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
setTimeout(syncHeight, 300); setTimeout(syncHeight, 800); setTimeout(syncHeight, 1500);
</script>
</body></html>
""", height=500, scrolling=False)
 
        # ══════════════════════════════════════════════════════════════
        # SUB-ABA: ANÁLISE DE IA
        # ══════════════════════════════════════════════════════════════
        
        resultados_ia_btns = {}
        for btn_sfx in ["criativo", "copy", "geral"]:
            ghost_k_ia = f"btn_{btn_sfx}_{aba_ativa}_ia"
            st.markdown(f"""
            <style>
            .st-key-{ghost_k_ia} {{
                position: fixed !important; top: -9999px !important; left: -9999px !important;
                width: 1px !important; height: 1px !important;
                opacity: 0 !important;
            }}
            .stElementContainer:has(.st-key-{ghost_k_ia}) {{
                position: fixed !important; top: -9999px !important; left: -9999px !important;
                width: 1px !important; height: 1px !important;
                overflow: hidden !important; margin: 0 !important; padding: 0 !important;
            }}
            </style>
            """, unsafe_allow_html=True)
            resultados_ia_btns[btn_sfx] = st.button(f"{btn_sfx}_{aba_ativa}", key=ghost_k_ia)

        chave_criativo = f"ia_criativo_{r['handle']}"
        chave_copy     = f"ia_copy_{r['handle']}"
        chave_geral    = f"ia_geral_{r['handle']}"
        
        for ch in [chave_criativo, chave_copy, chave_geral]:
            if ch not in st.session_state:
                st.session_state[ch] = ""

        resumo_posts = "\n".join([
            f"- {p.get('date','')} | {p.get('likes',0)} curtidas "
            f"{p.get('comments',0)} comentários | {p.get('caption','')[:80]}"
            for p in posts_list[:12]
        ]) if posts_list else "Sem posts disponíveis."

        perfil_ctx = f"""
Perfil: {r.get('handle','')} — {r.get('nome_exibido','')}
Bio: {r.get('bio','')}
Seguidores: {r.get('seguidores',0)} | Posts: {r.get('total_posts',0)} | Eng. médio: {r.get('eng_medio',0)} ({r.get('eng_pct',0):.2f}%)
Últimos posts:
{resumo_posts}
"""

        def _render_modal_redes_ia(fase: str, nome_analise: str, pct: int, _ph):
            is_done  = fase == "concluido"
            sub1     = "Análise concluída!" if is_done else "Gerando análise…"
            sub2     = "Redirecionando…"    if is_done else "Processando com IA…"
            cor_pct  = "#22c55e" if is_done else "#3a9fd6"
            rodape   = '<div style="text-align:center;margin-top:18px;font-size:13px;color:#64748b;">Fechando automaticamente…</div>' if is_done else ""
            nome_safe = (nome_analise or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("'","&#39;").replace('"',"&quot;")
            html_modal = f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.overlay {{ position:fixed; inset:0; background:rgba(0,0,0,0.72); z-index:999999; display:flex; align-items:center; justify-content:center; padding:24px; }}
.card {{ background:#0e2a47; border-radius:20px; padding:32px; width:min(95vw,480px); box-shadow:0 20px 60px rgba(0,0,0,0.5); border:1px solid #1e3a5f; }}
.spin-wrap {{ width:44px; height:44px; border-radius:50%; border:3px solid #1e3a5f; border-top-color:#3a9fd6; flex-shrink:0; animation: spin 0.85s linear infinite; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style>
<div class="overlay"><div class="card">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;">
        {'<div style="width:44px;height:44px;border-radius:50%;background:#22c55e;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;">✅</div>' if is_done else '<div class="spin-wrap"></div>'}
        <div style="flex:1;min-width:0;">
            <div style="font-size:17px;font-weight:800;color:#f1f5f9;">{sub1}</div>
            <div style="font-size:13px;color:#94a3b8;margin-top:3px;">{sub2}</div>
        </div>
        <div style="font-size:22px;font-weight:900;color:{cor_pct};flex-shrink:0;">{pct}%</div>
    </div>
    <div style="background:#1e3a5f;border-radius:8px;height:8px;margin-bottom:20px;overflow:hidden;">
        <div style="background:linear-gradient(90deg,#3a9fd6,#22c55e);height:100%;width:{pct}%;border-radius:8px;"></div>
    </div>
    <div style="background:#071929;border-radius:12px;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #1a3a5a;margin-bottom:4px;">
        <div>
            <div style="font-size:14px;font-weight:700;color:#e2e8f0;">{nome_safe}</div>
            <div style="font-size:12px;color:#4a7099;margin-top:3px;">Analisando com IA…</div>
        </div>
        <div style="font-size:18px;">{'✅' if is_done else '⏳'}</div>
    </div>
    {rodape}
</div></div>
<script>
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.position = 'fixed'; iframes[i].style.inset = '0';
            iframes[i].style.width = '100vw'; iframes[i].style.height = '100vh';
            iframes[i].style.zIndex = '999998'; iframes[i].style.border = 'none';
            break;
        }} }} catch(e) {{}}
    }}
}})();
</script>"""
            with _ph:
                components.html(html_modal, height=600, scrolling=False)

        if resultados_ia_btns["criativo"]:
            if gemini_model is None:
                st.session_state[chave_criativo] = "Configure GEMINI_API_KEY nos secrets."
            else:
                _ph = st.empty()
                _render_modal_redes_ia("gerando", f"Criativos — {r['nome']}", 40, _ph)
                try:
                    resp = gemini_model.generate_content(f"""
{perfil_ctx}
Analise os CRIATIVOS (imagens/vídeos) deste perfil com base nas legendas e métricas.
Responda em português com:
### Análise de Criativo
**Estilo visual predominante:** ...
**Formatos mais usados:** ...
**Posts com melhor desempenho:** ...
**Pontos fortes visuais:** (3 pontos)
**O que melhorar:** (2 pontos)
Seja direto e objetivo.
""")
                    st.session_state[chave_criativo] = resp.text
                    import datetime as _dt_redes
                    st.session_state.redes_analises_salvas = [
                        a for a in st.session_state.redes_analises_salvas
                        if not (a.get("tipo") == "criativos" and a.get("perfil") == r.get("handle"))
                    ]
                    st.session_state.redes_analises_salvas.append({
                        "titulo": f"Criativos — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                        "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "relatorio": resp.text,
                        "tipo": "criativos",
                        "perfil": r.get("handle", ""),
                        "nome": r["nome"],
                    })
                    _render_modal_redes_ia("concluido", f"Criativos — {r['nome']}", 100, _ph)
                    salvar_dados_usuario(st.session_state.user.id)
                    import time as _t; _t.sleep(1.2)
                    _ph.empty()
                    st.rerun()
                except Exception as e:
                    _ph.empty()
                    st.session_state[chave_criativo] = f"Erro: {e}"
                    st.rerun()

        if resultados_ia_btns["copy"]:
            if gemini_model is None:
                st.session_state[chave_copy] = "Configure GEMINI_API_KEY nos secrets."
            else:
                _ph = st.empty()
                _render_modal_redes_ia("gerando", f"Copy — {r['nome']}", 40, _ph)
                try:
                    resp = gemini_model.generate_content(f"""
{perfil_ctx}
Analise as LEGENDAS (copy) deste perfil Instagram.
Responda em português com:
### Análise de Copy
**Tom de voz predominante:** ...
**Uso de CTAs:** ...
**Uso de hashtags:** ...
**Pontos fortes nas legendas:** (3 pontos)
**O que melhorar:** (2 pontos)
Seja direto e objetivo.
""")
                    st.session_state[chave_copy] = resp.text
                    import datetime as _dt_redes
                    st.session_state.redes_analises_salvas = [
                        a for a in st.session_state.redes_analises_salvas
                        if not (a.get("tipo") == "copy" and a.get("perfil") == r.get("handle"))
                    ]
                    st.session_state.redes_analises_salvas.append({
                        "titulo": f"Copy — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                        "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "relatorio": resp.text,
                        "tipo": "copy",
                        "perfil": r.get("handle", ""),
                        "nome": r["nome"],
                    })
                    _render_modal_redes_ia("concluido", f"Copy — {r['nome']}", 100, _ph)
                    salvar_dados_usuario(st.session_state.user.id)
                    import time as _t; _t.sleep(1.2)
                    _ph.empty()
                    st.rerun()
                except Exception as e:
                    _ph.empty()
                    st.session_state[chave_copy] = f"Erro: {e}"
                    st.rerun()

        if resultados_ia_btns["geral"]:
            if gemini_model is None:
                st.session_state[chave_geral] = "Configure GEMINI_API_KEY nos secrets."
            else:
                _ph = st.empty()
                _render_modal_redes_ia("gerando", f"Estratégia — {r['nome']}", 40, _ph)
                try:
                    resp = gemini_model.generate_content(f"""
{perfil_ctx}
Faça uma análise geral estratégica deste perfil Instagram.
Responda em português com:
### Análise Geral
**Posicionamento:** ...
**Frequência de posts:** ...
### Pontos Fortes (3 pontos)
### Pontos de Atenção (2 pontos)
### Recomendações Estratégicas (3 ações concretas)
Seja direto e objetivo.
""")
                    st.session_state[chave_geral] = resp.text
                    import datetime as _dt_redes
                    st.session_state.redes_analises_salvas = [
                        a for a in st.session_state.redes_analises_salvas
                        if not (a.get("tipo") == "geral_perfil" and a.get("perfil") == r.get("handle"))
                    ]
                    st.session_state.redes_analises_salvas.append({
                        "titulo": f"Análise Geral — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                        "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "relatorio": resp.text,
                        "tipo": "geral_perfil",
                        "perfil": r.get("handle", ""),
                        "nome": r["nome"],
                    })
                    _render_modal_redes_ia("concluido", f"Estratégia — {r['nome']}", 100, _ph)
                    salvar_dados_usuario(st.session_state.user.id)
                    import time as _t; _t.sleep(1.2)
                    _ph.empty()
                    st.rerun()
                except Exception as e:
                    _ph.empty()
                    st.session_state[chave_geral] = f"Erro: {e}"
                    st.rerun()

    # ══════════════════════════════════════════════════════════════════
    # ABA: ANÁLISE DE IA — Comparativo geral
    # ══════════════════════════════════════════════════════════════════
 
    elif main_tab == "analise":

        import json as _json_redes
        import datetime as _dt_redes

        analises_redes = st.session_state.get("redes_analises_salvas", [])

        # Marcar como vistas
        st.session_state.redes_analise_vistas = len(analises_redes)

        # Ghost buttons para gerar análises ausentes
        tipos_pendentes = {
            "comparativo": not any(a.get("tipo") == "comparativo" for a in analises_redes),
        }
        for rr in ok:
            h = rr.get("handle", "")
            for tipo in ["criativos", "copy", "geral_perfil"]:
                chave_flag = f"pendente_{tipo}_{h}"
                tipos_pendentes[chave_flag] = not any(
                    a.get("tipo") == tipo and a.get("perfil") == h for a in analises_redes
                )

       # Ghost button comparativo
        ghost_comp_key = "btn_redes_comp_geral"
        st.markdown(f"""
        <style>
        .st-key-{ghost_comp_key} {{
            position:fixed !important; top:-9999px !important; left:-9999px !important;
            width:0 !important; height:0 !important; overflow:hidden !important;
            opacity:0 !important; pointer-events:none !important; display:none !important;
        }}
        .stElementContainer:has(.st-key-{ghost_comp_key}) {{
            display:none !important; height:0 !important; min-height:0 !important;
            max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
        }}
        </style>
        """, unsafe_allow_html=True)

        if st.button("redes_comparativo", key=ghost_comp_key):
            if gemini_model is None:
                st.toast("Configure GEMINI_API_KEY nos secrets.", icon="⚠️")
            elif not ok:
                st.toast("Nenhum perfil com dados disponível.", icon="⚠️")
            else:
                chave_comp_redes = "ia_comp_redes_geral"
                resumo_perfis = "\n\n".join([
                    f"Perfil: {rr.get('handle','')} — {rr.get('nome_exibido', rr.get('nome',''))}\n"
                    f"Seguidores: {rr.get('seguidores',0)} | Posts: {rr.get('total_posts',0)} | "
                    f"Eng. médio: {rr.get('eng_medio',0)} ({rr.get('eng_pct',0):.2f}%)\n"
                    f"Bio: {rr.get('bio','')}\n"
                    f"Últimos posts:\n" + "\n".join([
                        f"  - {p.get('date','')} | {p.get('likes',0)} curtidas "
                        f"{p.get('comments',0)} comentários | {p.get('caption','')[:80]}"
                        for p in rr.get("posts", [])[:6]
                    ])
                    for rr in ok
                ])
                with st.spinner("Gerando comparativo…"):
                    try:
                        resp = gemini_model.generate_content(f"""
Você é especialista em marketing digital e redes sociais.
Compare os perfis do Instagram abaixo e faça uma análise comparativa estratégica em português.

{resumo_perfis}

Responda com:
### Visão Geral Comparativa
Comparação resumida dos perfis em termos de presença e engajamento.

### Quem se Destaca e Por Quê
Destaque o perfil com melhor desempenho e explique os motivos.

### Pontos Fortes de Cada Perfil
Para cada perfil, 1-2 pontos fortes.

### Oportunidades Identificadas
2-3 oportunidades estratégicas para os perfis com menor desempenho.

### Recomendações Finais
3 ações concretas para melhorar a presença geral no Instagram.

Seja direto, objetivo e baseado nos dados fornecidos.
""")
                        st.session_state[chave_comp_redes] = resp.text
                        import datetime as _dt_redes
                        st.session_state.redes_analises_salvas = [
                            a for a in st.session_state.redes_analises_salvas
                            if a.get("tipo") != "comparativo"
                        ]
                        st.session_state.redes_analises_salvas.append({
                            "titulo": f"Comparativo Geral — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "relatorio": resp.text,
                            "tipo": "comparativo",
                            "perfis": [rr.get("handle","") for rr in ok],
                        })
                        salvar_dados_usuario(st.session_state.user.id)
                        st.rerun()
                    except Exception as e:
                        st.toast(f"Erro ao gerar comparativo: {e}", icon="⚠️")

        # Separar por tipo para exibição
        por_tipo = {
            "bio":         [(i, a) for i, a in enumerate(analises_redes) if a.get("tipo") == "bio"],
            "postagem":    [(i, a) for i, a in enumerate(analises_redes) if a.get("tipo") == "postagem"],
            "criativos":   [(i, a) for i, a in enumerate(analises_redes) if a.get("tipo") == "criativos"],
            "copy":        [(i, a) for i, a in enumerate(analises_redes) if a.get("tipo") == "copy"],
            "geral_perfil":[(i, a) for i, a in enumerate(analises_redes) if a.get("tipo") == "geral_perfil"],
            "comparativo": [(i, a) for i, a in enumerate(analises_redes) if a.get("tipo") == "comparativo"],
        }

        relatorios_js = {str(i): a.get("relatorio", "") for i, a in enumerate(analises_redes)}
        relatorios_json = _json_redes.dumps(relatorios_js, ensure_ascii=False)

        def _card_redes(idx_real, analise):
            titulo = analise.get("titulo", "—")
            tipo   = analise.get("tipo", "")
            icons  = {"bio": "👤", "postagem": "📸", "criativos": "🎨", "copy": "✍️", "geral_perfil": "📊", "comparativo": "🏆"}
            icon   = icons.get(tipo, "📋")
            nome_arquivo = titulo.replace(" ", "_").replace("/","_").replace("(","").replace(")","").replace(".","")
            return f"""
<div class="analise-card" id="card_{idx_real}">
    <div class="card-top" onclick="toggleCard({idx_real})">
        <div class="card-icon-wrap">{icon}</div>
        <div class="card-info">
            <div class="card-titulo">{titulo}</div>
        </div>
        <div class="card-chevron" id="chev_{idx_real}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </div>
    </div>
    <div class="card-body" id="body_{idx_real}" style="display:none">
        <div class="card-relatorio" id="rel_{idx_real}"></div>
        <div class="card-acoes">
            <button class="btn-dl" onclick="baixar({idx_real}, '{nome_arquivo}')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Baixar .txt
            </button>
            <button class="btn-rm" onclick="remover({idx_real})">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                Remover
            </button>
        </div>
    </div>
</div>"""

        def _secao_redes(titulo_sec, icon_sec, lista, tipo_sec, btn_label=None, btn_trigger=None):
            items_html = "".join(_card_redes(i, a) for i, a in reversed(lista)) if lista else ""
            empty_html = ""
            if not lista:
                if btn_label and btn_trigger:
                    empty_html = f"""
<div class="empty-state">
    <div class="empty-icon">{icon_sec}</div>
    <div class="empty-txt">Nenhuma análise de {titulo_sec.lower()} ainda.</div>
    <button class="btn-gerar-vazio" onclick="triggerBtn('{btn_trigger}')">{btn_label}</button>
</div>"""
                else:
                    empty_html = f"""
<div class="empty-state">
    <div class="empty-icon">{icon_sec}</div>
    <div class="empty-txt">Nenhuma análise de {titulo_sec.lower()} ainda.<br>Vá em <b>Perfis configurados</b> para gerar.</div>
</div>"""
            return f"""
<div class="secao">
    <div class="secao-header">
        <div class="secao-icon-lbl">{icon_sec}</div>
        <div class="secao-titulo">{titulo_sec}</div>
        {'<button class="btn-regerar" onclick="triggerBtn(\'' + btn_trigger + '\')">' + btn_label + '</button>' if btn_label and btn_trigger and lista else ''}
        <div class="secao-count {'has' if lista else ''}">{len(lista)}</div>
    </div>
    {'<div class="secao-cards">' + items_html + '</div>' if lista else empty_html}
</div>"""

        html_analise_redes = f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html {{ background:transparent; font-family:'DM Sans',sans-serif; -webkit-font-smoothing:antialiased; }}
body {{ background:transparent; overflow:visible; padding-bottom:16px; }}
.secao {{ margin-bottom:20px; }}
.secao-header {{
    display:flex; align-items:center; gap:8px;
    padding:0 4px 10px; border-bottom:2px solid #e5e7eb; margin-bottom:10px;
}}
.secao-icon-lbl {{ font-size:16px; flex-shrink:0; }}
.secao-titulo {{
    font-size:13px; font-weight:800; color:#6b7280;
    text-transform:uppercase; letter-spacing:0.8px; flex:1;
}}
.btn-regerar {{
    padding:4px 12px; border-radius:20px;
    border:1px solid #3a9fd6; background:#eff6ff;
    font-size:11px; font-weight:700; color:#1d4ed8;
    cursor:pointer; font-family:'DM Sans',sans-serif;
    transition:background 0.15s; white-space:nowrap;
}}
.btn-regerar:hover {{ background:#dbeafe; }}
.secao-count {{
    background:#f3f4f6; color:#9ca3af;
    font-size:12px; font-weight:700;
    padding:2px 10px; border-radius:20px; flex-shrink:0;
}}
.secao-count.has {{ background:#3a9fd6; color:#fff; }}
.secao-cards {{
    display:flex; flex-direction:column;
    border:1px solid #e5e7eb; border-radius:12px;
    overflow:hidden; background:#fff;
}}
.analise-card {{ border-bottom:1px solid #f3f4f6; }}
.analise-card:last-child {{ border-bottom:none; }}
.card-top {{
    display:flex; align-items:center; gap:12px;
    padding:14px 16px; cursor:pointer;
    transition:background 0.12s; user-select:none;
}}
.card-top:hover {{ background:#f9fafb; }}
.card-icon-wrap {{ font-size:18px; flex-shrink:0; }}
.card-info {{ flex:1; min-width:0; }}
.card-titulo {{
    font-size:14px; font-weight:600; color:#111827;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.card-chevron {{
    color:#d1d5db; flex-shrink:0; transition:transform 0.2s, color 0.15s;
    display:flex; align-items:center;
}}
.card-chevron.open {{ transform:rotate(180deg); color:#3a9fd6; }}
.card-top:hover .card-chevron {{ color:#9ca3af; }}
.card-body {{ padding:16px; background:#fafbfc; border-top:1px solid #f3f4f6; }}
.card-relatorio {{
    font-size:13px; color:#374151; line-height:1.8;
    max-height:400px; overflow-y:auto;
    padding:14px 16px; border-radius:8px;
    background:#fff; border:1px solid #e5e7eb;
    margin-bottom:12px; white-space:pre-wrap; word-break:break-word;
}}
.card-acoes {{ display:flex; gap:8px; }}
.btn-dl {{
    flex:1; padding:9px 14px; border-radius:8px;
    border:1px solid #e5e7eb; background:#fff;
    font-size:13px; font-weight:600; color:#374151;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:all 0.15s;
    display:flex; align-items:center; justify-content:center; gap:6px;
}}
.btn-dl:hover {{ background:#eff6ff; border-color:#3a9fd6; color:#1d4ed8; }}
.btn-rm {{
    padding:9px 14px; border-radius:8px;
    border:1px solid #e5e7eb; background:#fff;
    font-size:13px; font-weight:600; color:#9ca3af;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:all 0.15s; white-space:nowrap;
    display:flex; align-items:center; justify-content:center; gap:6px;
}}
.btn-rm:hover {{ background:#fef2f2; border-color:#fca5a5; color:#dc2626; }}
.empty-state {{
    border:1px dashed #e5e7eb; border-radius:12px;
    padding:28px 24px; text-align:center;
    display:flex; flex-direction:column; align-items:center; gap:8px;
    background:#fff;
}}
.empty-icon {{ font-size:24px; opacity:0.5; }}
.empty-txt {{ font-size:13px; color:#9ca3af; line-height:1.6; }}
.btn-gerar-vazio {{
    margin-top:4px; padding:9px 20px; border-radius:8px;
    border:1px solid #3a9fd6; background:#eff6ff;
    font-size:13px; font-weight:700; color:#1d4ed8;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:background 0.15s;
}}
.btn-gerar-vazio:hover {{ background:#dbeafe; }}
</style>

{_secao_redes("Análise de Perfil", "👤", por_tipo["bio"], "bio")}
{_secao_redes("Análise de Postagens", "📸", por_tipo["postagem"], "postagem")}
{_secao_redes("Análise de Criativos", "🎨", por_tipo["criativos"], "criativos")}
{_secao_redes("Análise de Copy", "✍️", por_tipo["copy"], "copy")}
{_secao_redes("Análise Geral por Perfil", "📊", por_tipo["geral_perfil"], "geral_perfil")}
{_secao_redes("Comparativo Geral", "🏆", por_tipo["comparativo"], "comparativo",
    btn_label="⚡ Gerar Comparativo" if por_tipo["comparativo"] else "⚡ Gerar Comparativo",
    btn_trigger="redes_comparativo")}

<script>
var RELATORIOS = {relatorios_json};

function toggleCard(idx) {{
    var body = document.getElementById('body_' + idx);
    var chev = document.getElementById('chev_' + idx);
    var rel  = document.getElementById('rel_' + idx);
    var aberto = body.style.display !== 'none';
    body.style.display = aberto ? 'none' : 'block';
    chev.classList.toggle('open', !aberto);
    if (!aberto && rel && !rel.dataset.loaded) {{
        rel.textContent = RELATORIOS[String(idx)] || '';
        rel.dataset.loaded = '1';
    }}
    setTimeout(ajustarAltura, 60);
}}

function remover(idx) {{
    var targetText = '_rm_redes_analise_' + idx + '_';
    var btns = window.parent.document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {{
        if ((btns[i].innerText || '').trim() === targetText) {{ btns[i].click(); return; }}
    }}
}}

function baixar(idx, nome) {{
    var conteudo = RELATORIOS[String(idx)] || '';
    var blob = new Blob([conteudo], {{type: 'text/plain;charset=utf-8'}});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = nome + '.txt';
    a.click();
}}

function triggerBtn(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === label) {{ b.click(); return; }}
    }}
}}

function ajustarAltura() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.height = (h + 8) + 'px'; break;
            }}
        }} catch(e) {{}}
    }}
}}

var ro = new ResizeObserver(ajustarAltura);
ro.observe(document.body);
window.addEventListener('load', ajustarAltura);
setTimeout(ajustarAltura, 200);
setTimeout(ajustarAltura, 600);
setTimeout(ajustarAltura, 1200);
</script>"""

        if not analises_redes:
            components.html("""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
html, body { background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }
.empty {
    background:#fff; border:1px dashed #d1d5db; border-radius:14px;
    padding:64px 48px; text-align:center;
    display:flex; flex-direction:column; align-items:center; gap:14px;
}
</style>
<div class="empty">
    <div style="font-size:40px">📋</div>
    <div style="font-size:18px;font-weight:700;color:#374151">Nenhuma análise ainda</div>
    <div style="font-size:14px;color:#9ca3af;line-height:1.7;max-width:400px">
        Vá em <b>Perfis configurados</b>, abra um perfil e gere análises de bio,
        postagens, criativos ou copy. O comparativo geral fica disponível aqui.
    </div>
</div>
<script>
(function() {
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        try { if (iframes[i].contentWindow === window) {
            iframes[i].style.height = '300px'; break;
        } } catch(e) {}
    }
})();
</script>
""", height=300, scrolling=False)
        else:
            components.html(html_analise_redes, height=300, scrolling=False)
