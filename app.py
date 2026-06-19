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
                "redes_analises_salvas": row.get("redes_analises_salvas", []),
                "ads_analises_salvas": row.get("ads_analises_salvas", []),
                "seo_cache": row.get("seo_cache", {}),
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
        "redes_analises_salvas": [],
        "ads_analises_salvas": [],
    }

def salvar_dados_usuario(user_id: str):
    try:
        payload = {
            "user_id": user_id,
            "minha_empresa": st.session_state.dados["minha_empresa"],
            "concorrentes": st.session_state.dados["concorrentes"],
            "metricas_redes": st.session_state.metricas_redes,
            "analises_salvas": st.session_state.get("analises_salvas", []),
            "redes_analises_salvas": st.session_state.get("redes_analises_salvas", []),
            "ads_analises_salvas": st.session_state.get("ads_analises_salvas", []),
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
if "redes_analises_salvas" not in st.session_state:
    st.session_state.redes_analises_salvas = []

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
# EXTRAÇÃO DE SEO — título, description, H1, H2s
# ---------------------------------------------------

def extrair_seo_site(url: str) -> dict:
    url_fmt = formatar_url(url)
    resultado = {
        "title": "", "description": "", "h1": "",
        "h2s": [], "status": "erro", "extraido_em": "", "contato": {}
    }
    if not url_fmt:
        return resultado
    try:
        import re as _re
        import datetime as _dt
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        resp = requests.get(url_fmt, headers=headers, timeout=12, allow_redirects=True)
        resp.encoding = resp.apparent_encoding
        html = resp.text

        m_title = _re.search(r'<title[^>]*>(.*?)</title>', html, _re.IGNORECASE | _re.DOTALL)
        if m_title:
            resultado["title"] = _re.sub(r'\s+', ' ', m_title.group(1)).strip()

        m_desc = _re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
            html, _re.IGNORECASE
        ) or _re.search(
            r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
            html, _re.IGNORECASE
        )
        if m_desc:
            resultado["description"] = _re.sub(r'\s+', ' ', m_desc.group(1)).strip()

        m_h1 = _re.search(r'<h1[^>]*>(.*?)</h1>', html, _re.IGNORECASE | _re.DOTALL)
        if m_h1:
            resultado["h1"] = _re.sub(r'<[^>]+>', '', m_h1.group(1)).strip()

        h2s = _re.findall(r'<h2[^>]*>(.*?)</h2>', html, _re.IGNORECASE | _re.DOTALL)
        resultado["h2s"] = [
            _re.sub(r'<[^>]+>', '', h).strip()
            for h in h2s if _re.sub(r'<[^>]+>', '', h).strip()
        ][:6]

        # ── Canais de Contato ─────────────────────────────────────
        ct = {}

        # WhatsApp
        wa_link = _re.findall(
            r'(?:wa\.me|whatsapp\.com/send|api\.whatsapp\.com/send)[^\d]*(\d{8,15})',
            html, _re.IGNORECASE
        )
        wa_href = _re.findall(
            r'href=["\'][^"\']*(?:wa\.me|whatsapp)[^"\']*?(\d{10,15})[^"\']*["\']',
            html, _re.IGNORECASE
        )
        wa_texto_depois = _re.findall(
            r'(?:whatsapp|whats|zap|wpp)\D{0,50}(\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4})',
            html, _re.IGNORECASE
        )
        wa_texto_antes = _re.findall(
            r'(\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4})\D{0,50}(?:whatsapp|whats|zap|wpp)',
            html, _re.IGNORECASE
        )
        wa_todos = wa_link or wa_href or wa_texto_depois or wa_texto_antes
        ct["whatsapp"] = wa_todos[0] if wa_todos else ""

        # Telefone
        tel_link = _re.findall(r'href=["\']tel:([+\d\s()\-]{6,20})["\']', html, _re.IGNORECASE)
        tel_depois = _re.findall(
            r'(?:telefone|fone|tel\.?|ligamos|ligue|celular|cel\.?)\D{0,20}(\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4})',
            html, _re.IGNORECASE
        )
        tel_antes = _re.findall(
            r'(\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4})\D{0,30}(?:telefone|fone|ligue|celular)',
            html, _re.IGNORECASE
        )
        wa_num_limpo = _re.sub(r'\D', '', ct.get("whatsapp", ""))
        def nao_e_whatsapp(n):
            return _re.sub(r'\D', '', n) != wa_num_limpo if wa_num_limpo else True
        tel_todos = [t for t in (tel_link or tel_depois or tel_antes) if nao_e_whatsapp(t)]
        ct["telefone"] = tel_todos[0].strip() if tel_todos else ""

        # E-mail — decodifica proteção Cloudflare/Elementor (data-cfemail) + fallback regex
        def decode_cfemail(encoded: str) -> str:
            try:
                enc = bytes.fromhex(encoded)
                key = enc[0]
                return ''.join(chr(b ^ key) for b in enc[1:])
            except Exception:
                return ""

        cf_emails = _re.findall(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', html)
        cf_decoded = [decode_cfemail(e) for e in cf_emails]

        cf_script = _re.findall(r'__cf_email__["\s]*,["\s]*["\']([0-9a-fA-F]+)["\']', html)
        cf_decoded += [decode_cfemail(e) for e in cf_script]

        import html as _html_parser
        html_decoded = _html_parser.unescape(html)
        html_decoded = html_decoded.replace('&#160;', '').replace('&nbsp;', '').replace('\u00a0', '')

        mail_link = _re.findall(r'href=["\']mailto:([^"\'?\s]+)["\']', html, _re.IGNORECASE)
        mail_link = [m for m in mail_link if not _re.search(r'\.(png|jpg|svg|webp)$', m, _re.IGNORECASE)]

        mail_texto = _re.findall(
            r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b',
            html_decoded, _re.IGNORECASE
        )
        mail_ignorar = {
            'sentry', 'example', 'test', 'noreply', 'no-reply', 'wordpress',
            'schema', 'w3', 'jquery', 'elementor', 'woocommerce', 'plugin',
            'theme', 'cdn', 'static', 'assets', 'googletagmanager',
            'google-analytics', 'facebook', 'pixel', 'yoast'
        }
        mail_texto = [
            m for m in mail_texto
            if not any(ign in m.lower() for ign in mail_ignorar)
            and not m.endswith(('.png', '.jpg', '.svg', '.webp', '.css', '.js', '.gif'))
            and '.' in m.split('@')[-1]
            and len(m) < 80
            and not m.startswith('@')
        ]

        mail_todos = cf_decoded if cf_decoded else (mail_link if mail_link else mail_texto)
        ct["email"] = mail_todos[0] if mail_todos else ""

        # Chat ao vivo
        ct["chat_ao_vivo"] = bool(_re.search(
            r'(intercom|zendesk|freshchat|tawk\.to|livechat|crisp\.chat|jivochat|hubspot.*chat|tidio|drift|leadster)',
            html, _re.IGNORECASE
        ))

        # Formulário de contato
        ct["formulario"] = bool(_re.search(
            r'<form[^>]*>.{0,600}(contato|contact|mensagem|message|nome|name|fale)',
            html, _re.IGNORECASE | _re.DOTALL
        ))

        # Botão/widget flutuante
        ct["botao_flutuante"] = bool(
            _re.search(
                r'(whatsapp[-_]?(button|widget|float|fixed|sticky|fab)'
                r'|float(ing)?[-_]?(button|btn|whats|chat|cta|action)'
                r'|fixed[-_]?(button|btn|cta|whats|chat|widget|action)'
                r'|fab[-_]?button|sticky[-_]?(button|btn|cta|chat)'
                r'|btn[-_]?float|button[-_]?fixed'
                r'|zopim|tawk|crisp|jivochat|tidio|drift|intercom|freshchat'
                r'|leadster|nld-chatbot|nld-avatar)',
                html, _re.IGNORECASE
            ) or _re.search(
                r'position\s*:\s*(fixed|sticky).{0,500}'
                r'(button|btn|cta|chat|contato|whats|fale|ajuda|help|atendimento|speak|flutuante|float)',
                html, _re.IGNORECASE | _re.DOTALL
            ) or _re.search(
                r'(button|btn|cta|chat|contato|whats|fale|ajuda|atendimento).{0,500}'
                r'position\s*:\s*(fixed|sticky)',
                html, _re.IGNORECASE | _re.DOTALL
            )
        )

        # Popup de saída
        ct["popup_saida"] = bool(_re.search(
            r'(exit.?intent|mouseleave.*popup|exit.?popup|exit.?modal'
            r'|exitIntent|exit_intent|onmouseleave.*modal)',
            html, _re.IGNORECASE
        ))

        # Popup de rolagem
        ct["popup_rolagem"] = bool(_re.search(
            r'(scroll.{0,20}(popup|modal|trigger|show|banner|offer|lead)'
            r'|scrollDepth|scroll_depth|scrollPercent|scroll.?percent'
            r'|ScrollTrigger|data-scroll-trigger'
            r'|onscroll.{0,50}(modal|popup|show)'
            r'|(popup|modal).{0,50}scroll)',
            html, _re.IGNORECASE
        ))

        # Instagram
        ig = _re.findall(
            r'instagram\.com/([a-zA-Z0-9_.]{2,30})(?:/|["\'\s]|$)',
            html, _re.IGNORECASE
        )
        ig = [i for i in ig if i.lower() not in ('p', 'reel', 'reels', 'explore', 'stories', 'tv', 'share', 'accounts')]
        ct["instagram"] = ig[0] if ig else ""

        # Facebook
        fb = _re.findall(
            r'facebook\.com/([a-zA-Z0-9_.]{2,60})(?:/|["\'\s]|$)',
            html, _re.IGNORECASE
        )
        fb = [f for f in fb if f.lower() not in ('sharer', 'share', 'tr', 'login', 'dialog', 'plugins', 'photo', 'watch')]
        ct["facebook"] = fb[0] if fb else ""

        # LinkedIn
        li = _re.findall(
            r'linkedin\.com/(?:company|in)/([a-zA-Z0-9_\-]{2,60})(?:/|["\'\s]|$)',
            html, _re.IGNORECASE
        )
        ct["linkedin"] = li[0] if li else ""

        # YouTube
        yt = _re.findall(
            r'youtube\.com/(?:channel/|@|c/)([a-zA-Z0-9_\-]{2,60})(?:/|["\'\s]|$)',
            html, _re.IGNORECASE
        )
        ct["youtube"] = yt[0] if yt else ""

        resultado["contato"] = ct
        resultado["status"] = "ok"
        resultado["extraido_em"] = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")

    except Exception as e:
        resultado["status"] = f"erro: {e}"

    return resultado

def extrair_e_salvar_seo(url: str, chave: str):
    if "seo_cache" not in st.session_state:
        st.session_state.seo_cache = {}
    if url:
        seo = extrair_seo_site(url)
        seo["sitemap"] = extrair_sitemap(url)
        st.session_state.seo_cache[chave] = seo
        salvar_seo_cache()

# SITEMAP -----------------

def extrair_sitemap(url: str) -> dict:
    import re as _re
    import datetime as _dt

    resultado = {
        "urls": [], "total": 0,
        "status": "erro", "extraido_em": ""
    }
    url_fmt = formatar_url(url)
    if not url_fmt:
        return resultado

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xml,text/xml,*/*;q=0.8",
    }

    def buscar_urls_sitemap(sitemap_url, profundidade=0):
        if profundidade > 2:
            return []
        try:
            r = requests.get(sitemap_url, headers=headers, timeout=10, allow_redirects=True)
            if r.status_code != 200:
                return []
            conteudo = r.text

            # Sitemap index — contém outros sitemaps
            sub_sitemaps = _re.findall(r'<loc>\s*(.*?sitemap.*?)\s*</loc>', conteudo, _re.IGNORECASE)
            if sub_sitemaps:
                todas = []
                for sub in sub_sitemaps[:5]:
                    todas += buscar_urls_sitemap(sub.strip(), profundidade + 1)
                return todas

            # Sitemap normal — contém páginas
            locs = _re.findall(r'<loc>\s*(https?://[^\s<]+)\s*</loc>', conteudo)
            return [l.strip() for l in locs]
        except Exception:
            return []

    # 1. Tenta achar pelo robots.txt
    base = url_fmt.rstrip("/")
    try:
        robots = requests.get(f"{base}/robots.txt", headers=headers, timeout=8)
        sm_declarado = _re.findall(r'(?i)sitemap:\s*(https?://\S+)', robots.text)
    except Exception:
        sm_declarado = []

    candidatos = sm_declarado + [
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
        f"{base}/sitemap-index.xml",
        f"{base}/wp-sitemap.xml",
        f"{base}/sitemap/sitemap-index.xml",
    ]

    todas_urls = []
    for candidato in candidatos:
        urls = buscar_urls_sitemap(candidato)
        if urls:
            todas_urls = urls
            break

    if todas_urls:
        resultado["urls"]   = todas_urls[:80]  # limita a 80 para exibição
        resultado["total"]  = len(todas_urls)
        resultado["status"] = "ok"
    else:
        resultado["status"] = "sem_sitemap"

    resultado["extraido_em"] = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    return resultado

# SALVAR — SEO CACHE  -------------
def salvar_seo_cache():
    """Persiste st.session_state.seo_cache no Supabase."""
    try:
        user_id = st.session_state.user.id
        seo_cache = st.session_state.get("seo_cache", {})
        payload = {
            "user_id": user_id,
            "minha_empresa":  st.session_state.dados["minha_empresa"],
            "concorrentes":   st.session_state.dados["concorrentes"],
            "metricas_redes": st.session_state.get("metricas_redes", {}),
            "analises_salvas":       st.session_state.get("analises_salvas", []),
            "redes_analises_salvas": st.session_state.get("redes_analises_salvas", []),
            "ads_analises_salvas":   st.session_state.get("ads_analises_salvas", []),
            "seo_cache": seo_cache,        # ← campo novo
        }
        supabase.table("ci_dados").upsert(payload, on_conflict="user_id").execute()
    except Exception as e:
        st.toast(f"⚠️ Erro ao salvar SEO: {e}", icon="⚠️")

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
                        st.session_state.redes_analises_salvas = dados_db.get("redes_analises_salvas", [])
                        st.session_state.ads_analises_salvas = dados_db.get("ads_analises_salvas", [])
                        st.session_state.seo_cache = dados_db.get("seo_cache", {})
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

# ---------------------------------------------------
# FUNÇÕES GLOBAIS
# ---------------------------------------------------

def _render_modal_redes_ia(fase: str, nome_analise: str, pct: int, _ph):
    is_done   = fase == "concluido"
    sub1      = "Análise concluída!" if is_done else "Gerando análise…"
    sub2      = "Redirecionando…"    if is_done else "Processando com IA…"
    cor_pct   = "#22c55e" if is_done else "#3a9fd6"
    rodape    = '<div style="text-align:center;margin-top:18px;font-size:13px;color:#64748b;">Fechando automaticamente…</div>' if is_done else ""
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
# HOME — Pagina - Minha Empresa
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
                        if emp.get("site"):
                            extrair_e_salvar_seo(emp["site"], emp["nome"])
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
                if site_clean and n:
                    extrair_e_salvar_seo(site_clean, n)
                salvar_dados_usuario(st.session_state.user.id)
                st.rerun()
 
    concorrentes = st.session_state.dados["concorrentes"]
 
    if concorrentes:
        import json as _json_conc
 
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
 
            var hdr = document.createElement('div');
            hdr.className = 'card-header';
            hdr.innerHTML =
                '<div class="avatar" style="background:' + c.cor + '">' + c.avatar + '</div>'
                + '<div style="flex:1;min-width:0">'
                + '<div class="name">' + c.nome + '</div>'
                + '<span class="badge">Concorrente</span>'
                + '</div>';
            card.appendChild(hdr);
 
            var dvd = document.createElement('div');
            dvd.className = 'divider';
            card.appendChild(dvd);
 
            var body = document.createElement('div');
            body.className = 'card-body';
            body.innerHTML =
                '<div class="sec-title">Presença Digital</div>'
                + makeRow(ICON_GLOBE, '#f3f4f6',  'Site',      c.url)
                + makeRow(igIcon(c.idx), '#fff0f6', 'Instagram', c.instagram)
                + makeRow(ICON_FB,    '#e8f0fe',  'Facebook',  c.fb_page);
            card.appendChild(body);
 
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

        # ── Banner "Mantenha seus concorrentes atualizados" ──────
        st.markdown("""
        <div style='background:#e7fbff;border:1px solid #6fd1f3;border-radius:12px;
                    padding:14px 20px;display:flex;align-items:center;gap:16px;
                    margin-top:-38px;box-shadow:0 1px 3px rgba(0,0,0,0.04)'>
            <div style='width:42px;height:42px;border-radius:10px;background:#007dbb;
                        display:flex;align-items:center;justify-content:center;flex-shrink:0'>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"
                          stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    <circle cx="9" cy="7" r="4"
                          stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"
                          stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"
                          stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div>
                <div style='font-size:16px;font-weight:600;color:#0f172a'>Mantenha seus concorrentes atualizados</div>
                <div style='font-size:13px;color:#64748b;margin-top:-3px'>Monitorar concorrentes regularmente garante análises mais precisas e decisões mais estratégicas.</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

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
    import math as _math

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

        return {
            "score": score,
            "classificacao": classificacao,
            "classificacao_icon": classificacao_icon,
            "cor_classe": cor_classe,
            "bg_classe": bg_classe,
            "brd_classe": brd_classe,
            "criterios": criterios,
            "oportunidades": sum(1 for c in criterios if not c["ok"]),
        }

    emp = st.session_state.dados["minha_empresa"]
    concorrentes = st.session_state.dados["concorrentes"]

    # ── Cabeçalho ─────────────────────────────────────────────────────
    h1, h2 = st.columns([6, 4])

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
        ultima_redes = st.session_state.metricas_redes.get("ultima_coleta", "")
        ultima_ads   = ""
        for v in st.session_state.get("ads_cache", {}).values():
            if v.get("ultima_coleta"):
                ultima_ads = v["ultima_coleta"]
                break
            if v.get("ts"):
                ultima_ads = v["ts"]
                break

        update_items = []
        if ultima_redes:
            update_items.append({
                "label": "INSTAGRAM", "valor": ultima_redes, "icon_bg": "#f0f9ff",
                "icon": "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='#0369a1' stroke-width='2'><rect x='2' y='2' width='20' height='20' rx='5'/><circle cx='12' cy='12' r='4.5' fill='none'/><circle cx='17.5' cy='6.5' r='1.2' fill='#0369a1'/></svg>",
            })
        if ultima_ads:
            update_items.append({
                "label": "META ADS", "valor": ultima_ads, "icon_bg": "#fff7ed",
                "icon": "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='#c2410c' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 11l19-9-9 19-2-8-8-2z'/></svg>",
            })

        if update_items:
            cards_html = ""
            for item in update_items:
                cards_html += (
                    f"<div style='display:flex;align-items:center;white-space:nowrap'>"
                    f"<div style='width:24px;height:24px;border-radius:6px;background:{item['icon_bg']};"
                    f"display:flex;align-items:center;justify-content:center;flex-shrink:0'>{item['icon']}</div>"
                    f"<span style='font-size:11px;font-weight:700;color:#374151'>{item['label']}: {item['valor']}</span>"
                    f"</div>"
                )
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:4px'>"
                f"<span style='font-size:11px;font-weight:700;color:#1a2e4a;text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap'>Fonte:</span>"
                f"{cards_html}</div>", unsafe_allow_html=True
            )
        else:
            st.markdown(
                "<div style='background:#f9fafb;border:1px dashed #e5e7eb;border-radius:10px;"
                "padding:10px 14px;text-align:center'>"
                "<div style='font-size:12px;color:#9ca3af'>Sem dados coletados ainda</div></div>",
                unsafe_allow_html=True
            )

    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:16px 0 24px 0'/>", unsafe_allow_html=True)

    # ── Lista de empresas ──────────────────────────────────────────────
    todas_empresas_geral = []
    if emp.get("nome"):
        todas_empresas_geral.append({
            "nome": emp["nome"], "tipo": "minha",
            "instagram": emp.get("instagram", ""), "site": emp.get("site", ""),
            "setor": emp.get("setor", ""), "tipo_nicho": emp.get("tipo", ""),
            "cidade": emp.get("cidade", ""), "estado": emp.get("estado", ""),
        })
    for c in concorrentes:
        if c.get("nome"):
            todas_empresas_geral.append({
                "nome": c["nome"], "tipo": "concorrente",
                "instagram": c.get("instagram", ""), "site": c.get("url", ""),
                "setor": "", "tipo_nicho": "", "cidade": "", "estado": "",
            })

    # ── Filtro ────────────────────────────────────────────────────────
    if "geral_empresa_filtro" not in st.session_state:
        st.session_state.geral_empresa_filtro = 0 if todas_empresas_geral else "todas"

    _filtro_ghost_css = []
    for _i in range(len(todas_empresas_geral)):
        _k = f"btn_geral_filtro_{_i}"
        _filtro_ghost_css.append(f"""
        .st-key-{_k} {{
            position:fixed !important; top:-9999px !important; left:-9999px !important;
            width:0 !important; height:0 !important; overflow:hidden !important;
            opacity:0 !important; pointer-events:none !important; display:none !important;
        }}
        .stElementContainer:has(.st-key-{_k}) {{
            display:none !important; height:0 !important; min-height:0 !important;
            max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
        }}
        """)
    st.markdown(f"<style>{''.join(_filtro_ghost_css)}</style>", unsafe_allow_html=True)

    for _i in range(len(todas_empresas_geral)):
        if st.button(f"geral_filtro_{_i}", key=f"btn_geral_filtro_{_i}"):
            st.session_state.geral_empresa_filtro = _i
            st.rerun()

    filtro_empresa_ativo = st.session_state.get("geral_empresa_filtro", 0)

    # ── Cache de redes ─────────────────────────────────────────────────
    cache_redes = st.session_state.metricas_redes.get("dados", [])
    dados_redes_map = {}
    for r in cache_redes:
        if not r.get("erro") and r.get("nome"):
            dados_redes_map[r["nome"]] = r

    ads_cache = st.session_state.get("ads_cache", {})

    def fmt_num(n):
        n = int(n or 0)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n/1_000:.1f}K"
        return str(n)

    # ══════════════════════════════════════════════════════════════════
    # CARDS DE NAVEGAÇÃO
    # ══════════════════════════════════════════════════════════════════
    if todas_empresas_geral:

        empresas_cards_nav_json = []
        for i, e in enumerate(todas_empresas_geral):
            is_minha = e["tipo"] == "minha"
            cor = get_minha_empresa_color() if is_minha else get_concorrente_color(i)
            r_nav = dados_redes_map.get(e["nome"], {})
            profile_pic_nav = r_nav.get("profile_pic", "") if r_nav else ""
            handle_nav = e.get("instagram", "") or (r_nav.get("handle", "") if r_nav else "")
            empresas_cards_nav_json.append({
                "nome": e["nome"], "tipo": e["tipo"], "handle": handle_nav,
                "is_minha": is_minha,
                "badge_lbl": "Minha empresa" if is_minha else "Concorrente",
                "cor": cor, "profile_pic": profile_pic_nav, "i": i,
                "active": (filtro_empresa_ativo == i),
            })

        empresas_cards_nav_str = _json.dumps(empresas_cards_nav_json, ensure_ascii=False)

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; -webkit-font-smoothing:antialiased; }}
.main-wrap {{ background:#d2dde9; border-radius:16px; overflow:hidden; }}
.cards-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; padding:12px; }}
.emp-card {{
    background:#f9fafb; border:1px solid #e5e7eb; border-radius:12px; padding:16px;
    display:flex; align-items:center; gap:12px; cursor:pointer; transition:all 0.15s;
}}
.emp-card:hover {{ border-color:#3a9fd6; background:#fff; box-shadow:0 2px 10px rgba(58,159,214,0.1); }}
.emp-card.active {{ background:#fff; border:2px solid #3b82f6; }}
.emp-icon {{ width:44px; height:44px; border-radius:22px; background:#e9eef5; display:flex; align-items:center; justify-content:center; flex-shrink:0; overflow:hidden; }}
.emp-icon img {{ width:100%; height:100%; object-fit:cover; border-radius:22px; }}
.emp-nome {{ font-size:14px; font-weight:700; color:#1a2e4a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.badge-minha {{ display:inline-flex; align-items:center; background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:700; flex-shrink:0; margin-left:auto; }}
.badge-conc  {{ display:inline-flex; align-items:center; background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:700; flex-shrink:0; margin-left:auto; }}
</style>
<div class="main-wrap"><div class="cards-grid" id="cards-grid-geral"></div></div>
<script>
var EMPRESAS = {empresas_cards_nav_str};
function buildUI() {{
    var grid = document.getElementById('cards-grid-geral');
    grid.innerHTML = '';
    EMPRESAS.forEach(function(e) {{
        var card = document.createElement('div');
        card.className = 'emp-card' + (e.active ? ' active' : '');
        var strokeColor = e.active ? '#3b82f6' : '#64748b';
        var iconInner = '<svg viewBox="0 0 24 24" fill="none" stroke="' + strokeColor + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px"><rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="4.5" stroke-width="1.5" fill="none"/><circle cx="17.5" cy="6.5" r="1.2" fill="' + strokeColor + '"/></svg>';
        if (e.profile_pic) iconInner = '<img src="' + e.profile_pic + '" />';
        var badgeHtml = e.is_minha ? '<span class="badge-minha">Minha empresa</span>' : '<span class="badge-conc">Concorrente</span>';
        card.innerHTML = '<div class="emp-icon">' + iconInner + '</div>'
            + '<div style="min-width:0;flex:1;">'
            + '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:2px;">'
            + '<div class="emp-nome">' + e.nome + '</div>' + badgeHtml + '</div>'
            + (e.handle ? '<div style="font-size:12px;color:#9ca3af;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + e.handle + '</div>' : '')
            + '</div>';
        card.addEventListener('click', function() {{ selectFiltro(e.i); }});
        grid.appendChild(card);
    }});
    syncHeight();
}}
function selectFiltro(i) {{
    var label = 'geral_filtro_' + i;
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        if ((b.textContent||b.innerText||'').trim() === label) {{ b.click(); return; }}
    }}
}}
function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    var frames = window.parent.document.querySelectorAll('iframe');
    for (var i=0;i<frames.length;i++) {{
        try {{ if (frames[i].contentWindow===window) {{ frames[i].style.height=(h+2)+'px'; break; }} }} catch(e) {{}}
    }}
}}
buildUI();
if (window.ResizeObserver) new ResizeObserver(syncHeight).observe(document.body);
setTimeout(syncHeight,200); setTimeout(syncHeight,600);
</script>
""", height=100, scrolling=False)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════
    # FUNÇÕES DE DONUT
    # ══════════════════════════════════════════════════════════════════

    # Donut com texto ao LADO direito (usado em Tipos de Conteúdo e Formato)
    def make_donut_svg(pct, color, label, count, size=48, stroke=5):
        r = (size / 2) - stroke - 2
        cx = cy = size / 2
        circum = round(2 * _math.pi * r, 2)
        dash = round(pct / 100 * circum, 2)
        gap  = round(circum - dash, 2)
        offset = round(circum * 0.25, 2)
        return (
            f'<div style="display:flex;align-items:center;gap:5px;flex:1;min-width:0;">'
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0;">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#f0f0f0" stroke-width="{stroke}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}"'
            f' stroke-dasharray="{dash} {gap}" stroke-dashoffset="{offset}" stroke-linecap="round"/>'
            f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="middle"'
            f' font-size="11" font-weight="800" fill="{color}" font-family="DM Sans,sans-serif">{count}</text>'
            f'</svg>'
            f'<div style="display:flex;flex-direction:column;min-width:0;">'
            f'<span style="font-size:13px;font-weight:800;color:{color};line-height:1.2;">{pct}%</span>'
            f'<span style="font-size:9px;color:#405068;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;white-space:nowrap;">{label}</span>'
            f'</div></div>'
        )

    # SVGs inline das redes
    PLAT_ICONS_SVG = {
        "facebook": (
            '#1877f2',
            'Facebook',
            '<path fill="#1877f2" d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.268h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/>'
        ),
        "instagram": (
            '#e1306c',
            'Instagram',
            '<path fill="url(#ig_grad)" d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>'
        ),
        "messenger": (
            '#0084ff',
            'Messenger',
            '<path fill="#0084ff" d="M12 0C5.373 0 0 4.975 0 11.111c0 3.497 1.745 6.616 4.472 8.652V24l4.086-2.242c1.09.301 2.246.464 3.442.464 6.627 0 12-4.975 12-11.111S18.627 0 12 0zm1.193 14.963l-3.056-3.259-5.963 3.259L10.733 8.4l3.13 3.259L19.752 8.4l-6.559 6.563z"/>'
        ),
        "whatsapp": (
            '#25d366',
            'WhatsApp',
            '<path fill="#25d366" d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>'
        ),
        "audience_network": (
            '#3a9fd6',
            'Audience',
            '<circle cx="12" cy="12" r="10" fill="#3a9fd6"/><path fill="#fff" d="M12 6a6 6 0 100 12A6 6 0 0012 6zm0 2a4 4 0 110 8 4 4 0 010-8zm0 1.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5z"/>'
        ),
        "threads": (
            '#1a2e4a',
            'Threads',
            '<path fill="#1a2e4a" d="M12.186 24h-.007c-3.581-.024-6.334-1.205-8.184-3.509C2.35 18.44 1.5 15.586 1.472 12.01v-.017c.028-3.579.879-6.43 2.525-8.482C5.845 1.205 8.6.024 12.18 0h.014c2.746.02 5.043.725 6.826 2.098 1.677 1.29 2.858 3.13 3.509 5.467l-2.04.569c-1.104-3.96-3.898-5.984-8.304-6.015-2.91.022-5.11.936-6.54 2.717C4.307 6.504 3.616 8.914 3.589 12c.027 3.086.718 5.496 2.057 7.164 1.43 1.783 3.631 2.698 6.54 2.717 2.623-.02 4.358-.631 5.8-2.045 1.647-1.613 1.618-3.593 1.09-4.798-.31-.71-.873-1.3-1.634-1.75-.192 1.352-.622 2.446-1.284 3.272-.886 1.102-2.14 1.704-3.73 1.79-1.202.065-2.361-.218-3.259-.801-1.063-.689-1.685-1.749-1.752-2.979-.065-1.19.408-2.285 1.33-3.082.88-.76 2.119-1.207 3.583-1.291a13.853 13.853 0 012.62.144c-.107-.568-.26-1.031-.465-1.38-.363-.622-.937-.955-1.754-.98h-.075c-.544 0-1.478.152-2.02 1.31l-1.877-.867c.853-1.842 2.431-2.308 3.892-2.308h.106c2.854.088 4.192 1.836 4.502 5.388.779.567 1.408 1.233 1.853 1.99.747 1.28 1 2.79.712 4.264-.332 1.69-1.257 3.17-2.692 4.27C17.253 23.266 15.006 24 12.186 24z"/>'
        ),
    }

    # Donut para plataformas com círculo em cima, legenda embaixo (grid)
    def make_donut_plat(pct, color, label, count, plat_key, size=52, stroke=5):
        r = (size / 2) - stroke - 2
        cx = cy = size / 2
        circum = round(2 * _math.pi * r, 2)
        dash = round(pct / 100 * circum, 2)
        gap  = round(circum - dash, 2)
        offset = round(circum * 0.25, 2)
        icon_s = size * 0.36
        icon_x = cx - icon_s / 2
        icon_y = cy - icon_s / 2
        _, _, path_data = PLAT_ICONS_SVG.get(plat_key, ('#64748b', label, '<circle cx="12" cy="12" r="8" fill="#64748b"/>'))

        defs = ""
        if plat_key == "instagram":
            defs = (
                f'<defs>'
                f'<linearGradient id="ig_grad" x1="0%" y1="100%" x2="100%" y2="0%">'
                f'<stop offset="0%" style="stop-color:#f09433"/>'
                f'<stop offset="25%" style="stop-color:#e6683c"/>'
                f'<stop offset="50%" style="stop-color:#dc2743"/>'
                f'<stop offset="75%" style="stop-color:#cc2366"/>'
                f'<stop offset="100%" style="stop-color:#bc1888"/>'
                f'</linearGradient>'
                f'</defs>'
            )

        return (
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:4px;flex:1;min-width:0;">'
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg">'
            f'{defs}'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#f0f0f0" stroke-width="{stroke}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}"'
            f' stroke-dasharray="{dash} {gap}" stroke-dashoffset="{offset}" stroke-linecap="round"/>'
            f'<g transform="translate({icon_x:.1f},{icon_y:.1f}) scale({icon_s/24:.3f})">'
            f'{path_data}'
            f'</g>'
            f'</svg>'
            f'<div style="text-align:center;">'
            f'<div style="font-size:12px;font-weight:700;color:{color};">{count}</div>'
            f'<div style="font-size:9px;color:#405068;font-weight:700;text-transform:uppercase;letter-spacing:0.3px;white-space:nowrap;">{label}</div>'
            f'</div></div>'
        )

    def calcular_categorias_ads(ads_lista: list) -> dict:
        palavras_beneficio = [
            "economiz","aumente","aumenta","melhora","melhore","resultado","resultados",
            "transforma","conquiste","conquista","garanta","garante","lucro","lucre",
            "ganhe","ganha","facilita","simplifica","reduza","reduz","alcance",
        ]
        palavras_prova_social = [
            "cliente","clientes","avaliaç","avaliacoes","depoimento","depoimentos",
            "estrelas","aprovado","milhares","mais de","comprovado","case","satisfeitos","recomendam",
        ]
        palavras_urgencia = [
            "agora","hoje","últim","ultim","corre","corra","acaba em","vagas limitadas",
            "por tempo limitado","termina","última chance","apenas hoje","não perca","restam","expira",
        ]
        palavras_cta_direto = [
            "clique","saiba mais","compre","compra","agende","agora mesmo","fale com",
            "chame no whatsapp","acesse","cadastre-se","inscreva-se","garanta já","peça já","solicite",
        ]

        def texto_do_anuncio(ad):
            campos = ["body","texto","ad_creative_body","title","headline","description","creative_text"]
            return " ".join(ad.get(c,"") for c in campos if isinstance(ad.get(c,""),str) and ad.get(c,"").strip()).lower()

        def tipo_midia(ad):
            if ad.get("is_video") or ad.get("media_type")=="video" or ad.get("video_url") or ad.get("formato")=="Vídeo":
                return "video"
            if ad.get("media_type")==8 or ad.get("is_carousel") or ad.get("media_type")=="carousel" or ad.get("formato")=="Carrossel":
                return "carrossel"
            return "imagem"

        def extrair_plataformas(ad):
            plats_raw = ad.get("plataformas") or ad.get("publisher_platform") or ad.get("publisherPlatform") or ad.get("publisher_platforms") or []
            if isinstance(plats_raw, str): plats_raw = [plats_raw]
            result = []
            for p in plats_raw:
                if isinstance(p, dict):
                    result.append((p.get("name") or p.get("value") or str(p)).strip().lower())
                elif isinstance(p, str) and p.strip():
                    result.append(p.strip().lower())
            return result

        def extrair_destino(ad):
            import re as _re
            snapshot = ad.get("snapshot") or {}
            candidatos = [ad.get("caption"),ad.get("destination_url"),ad.get("website_url"),ad.get("link_url"),
                          snapshot.get("caption"),snapshot.get("link_url"),snapshot.get("website_url"),snapshot.get("destination_url")]
            for url in candidatos:
                if not url or not isinstance(url, str): continue
                url = url.strip()
                dominio = _re.sub(r'^https?://','',url).split('/')[0].split('?')[0].replace('www.','').strip()
                if dominio and '.' in dominio and 'facebook.com' not in dominio and 'fb.com' not in dominio and 'fbcdn' not in dominio:
                    return dominio
            return ""

        contagens = {"beneficio":0,"prova_social":0,"urgencia":0,"cta_direto":0}
        midia = {"video":0,"imagem":0,"carrossel":0}
        plat_count = {}
        dest_count = {}

        for ad in ads_lista:
            txt = texto_do_anuncio(ad)
            if any(p in txt for p in palavras_beneficio):    contagens["beneficio"] += 1
            if any(p in txt for p in palavras_prova_social): contagens["prova_social"] += 1
            if any(p in txt for p in palavras_urgencia):     contagens["urgencia"] += 1
            if any(p in txt for p in palavras_cta_direto):   contagens["cta_direto"] += 1
            midia[tipo_midia(ad)] += 1
            for p in extrair_plataformas(ad):
                plat_count[p] = plat_count.get(p,0) + 1
            dest = extrair_destino(ad)
            if dest: dest_count[dest] = dest_count.get(dest,0) + 1

        return {
            "total": len(ads_lista),
            "beneficio": contagens["beneficio"], "prova_social": contagens["prova_social"],
            "urgencia": contagens["urgencia"],   "cta_direto": contagens["cta_direto"],
            "video": midia["video"], "imagem": midia["imagem"], "carrossel": midia["carrossel"],
            "plataformas": plat_count,
            "destinos": sorted(dest_count.items(), key=lambda x: x[1], reverse=True)[:3],
        }

    seo_cache = st.session_state.get("seo_cache", {})

    # ══════════════════════════════════════════════════════════════════
    # MONTA DADOS POR EMPRESA
    # ══════════════════════════════════════════════════════════════════
    if todas_empresas_geral:

        empresas_cards_data = []
        for i, e in enumerate(todas_empresas_geral):
            if i != filtro_empresa_ativo:
                continue

            is_minha = e["tipo"] == "minha"
            cor = get_minha_empresa_color() if is_minha else get_concorrente_color(i)
            av  = gerar_avatar(e["nome"])
            badge_lbl = "Minha Empresa" if is_minha else "Concorrente"
            badge_bg  = "#f0fdf4" if is_minha else "#eff6ff"
            badge_col = "#15803d" if is_minha else "#1d4ed8"
            badge_brd = "#bbf7d0" if is_minha else "#bfdbfe"

            r = dados_redes_map.get(e["nome"])
            tem_redes = bool(r)
            redes_info = None

            if tem_redes:
                pp = r.get("profile_pic","")
                if pp and pp.startswith("data:"):
                    av_html = f'<div style="width:32px;height:32px;border-radius:50%;overflow:hidden;flex-shrink:0;"><img src="{pp}" style="width:100%;height:100%;object-fit:cover;border-radius:50%;" /></div>'
                else:
                    av_html = f'<div style="width:32px;height:32px;border-radius:50%;background:{cor};display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;flex-shrink:0">{av}</div>'

                bio_txt_geral = (r.get("bio") or "").replace("<","&lt;").replace(">","&gt;")
                ext_url_geral = (r.get("external_url") or "").strip()
                score_geral   = calcular_score_bio(bio_txt_geral, ext_url_geral, r.get("seguidores",0), r.get("eng_pct",0.0))

                posts_lista = r.get("posts",[])
                n_fotos     = sum(1 for p in posts_lista if not p.get("is_video") and p.get("media_type",1) != 8)
                n_videos    = sum(1 for p in posts_lista if p.get("is_video"))
                n_carrossel = sum(1 for p in posts_lista if p.get("media_type") == 8)
                n_total_tp  = len(posts_lista) or 1

                # ── Nuvem de palavras: extrai palavras da bio + legenda dos posts ──
                import re as _re
                stop_words_bio = {
                    "de","da","do","das","dos","em","e","a","o","as","os","um","uma","uns","umas",
                    "para","por","com","que","se","na","no","nas","nos","ao","aos","à","às","mais",
                    "ou","mas","como","são","sua","seu","suas","seus","esta","este","essa","esse",
                    "pelo","pela","pelos","pelas","entre","até","já","pra","pro","pros","pras",
                    "vai","vão","tem","têm","bem","sim","não","sem","só","lá","cá","você","voce",
                    "além","isso","isto","aquilo","tudo","nada","muito","muita","muitos","muitas",
                    "pouco","poucos","poucas","dia","ano","mês","vez","aqui","ali","anos","dias",
                    "meses","vezes","todo","toda","todos","todas","ser","ter","pode","nosso","nossa",
                    "nossos","nossas","qual","quais","quando","onde","quem","porque","the","and","of",
                    "to","in","is","it","for","on","with","that","this","are","from","at","an","be",
                    "by","not","or","was","we","our","your","have","has","will","can","more","also",
                }
                texto_nuvem = bio_txt_geral + " "
                for p in posts_lista[:30]:
                    texto_nuvem += (p.get("caption") or "") + " "
                tokens_nuvem = _re.sub(r'[^a-záéíóúàãõâêîôûçñü\s]', ' ', texto_nuvem.lower()).split()
                freq_nuvem = {}
                for w in tokens_nuvem:
                    if len(w) >= 4 and w not in stop_words_bio:
                        freq_nuvem[w] = freq_nuvem.get(w, 0) + 1
                nuvem_palavras = sorted(freq_nuvem.items(), key=lambda x: x[1], reverse=True)[:20]

                redes_info = {
                    "av_html": av_html,
                    "seg":     fmt_num(r.get("seguidores",0)),
                    "eng":     f'{r.get("eng_pct",0):.1f}%',
                    "posts":   fmt_num(r.get("total_posts",0)),
                    "eng_med": fmt_num(int(r.get("eng_medio",0))),
                    "score_val":  score_geral["score"],
                    "score_cor":  score_geral["cor_classe"],
                    "score_icon": score_geral["classificacao_icon"],
                    "score_lbl":  score_geral["classificacao"],
                    "score_criterios":     score_geral["criterios"],
                    "score_oportunidades": score_geral["oportunidades"],
                    "score_faltando": [c["label"] for c in score_geral["criterios"] if not c["ok"]],
                    "pct_foto":    round(n_fotos     / n_total_tp * 100),
                    "pct_vid":     round(n_videos    / n_total_tp * 100),
                    "pct_carr":    round(n_carrossel / n_total_tp * 100),
                    "n_fotos":     n_fotos,
                    "n_videos":    n_videos,
                    "n_carrossel": n_carrossel,
                    "n_total_tp":  len(posts_lista),
                    "nuvem_palavras": nuvem_palavras,
                }

            av_html_fallback = (redes_info["av_html"] if tem_redes else
                f'<div style="width:32px;height:32px;border-radius:50%;background:{cor};display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;flex-shrink:0">{av}</div>')

            site_url = e.get("site","") or ""
            seo      = seo_cache.get(e["nome"],{})
            sitemap  = seo.get("sitemap",{})

            seo_status_ok = seo.get("status") == "ok"
            seo_pontos = sum([bool(seo.get("title")), bool(seo.get("h1")), bool(seo.get("description")),
                              bool(seo.get("h2s")), sitemap.get("status")=="ok"])
            seo_score_val = round((seo_pontos / 5) * 100) if seo_status_ok else 0

            if seo_score_val >= 80:   seo_score_lbl, seo_score_icon, seo_score_cor = "Excelente","🏆","#22c55e"
            elif seo_score_val >= 60: seo_score_lbl, seo_score_icon, seo_score_cor = "Bom","👍","#3b82f6"
            elif seo_score_val >= 40: seo_score_lbl, seo_score_icon, seo_score_cor = "Regular","⚠️","#f59e0b"
            else:                     seo_score_lbl, seo_score_icon, seo_score_cor = "Precisa melhorar","📝","#ef4444"

            seo_items_check = [
                {"label": "Title",       "ok": bool(seo.get("title"))},
                {"label": "H1",          "ok": bool(seo.get("h1"))},
                {"label": "Meta Desc.",  "ok": bool(seo.get("description"))},
                {"label": "Seções (H2)", "ok": bool(seo.get("h2s"))},
                {"label": "Sitemap",     "ok": sitemap.get("status") == "ok"},
            ]
            seo_faltando = [c["label"] for c in seo_items_check if not c["ok"]]

            ads_entry = ads_cache.get(e["nome"],{})
            ads_lista = ads_entry.get("data",[]) if ads_entry else []
            tem_ads   = len(ads_lista) > 0
            ads_info  = calcular_categorias_ads(ads_lista) if tem_ads else None

            empresas_cards_data.append({
                "nome": e["nome"], "cor": cor, "av_html": av_html_fallback,
                "badge_lbl": badge_lbl, "badge_bg": badge_bg, "badge_col": badge_col, "badge_brd": badge_brd,
                "tem_redes": tem_redes, "redes": redes_info,
                "site": site_url, "ig": e.get("instagram","") or "",
                "seo_status_ok": seo_status_ok, "seo_score_val": seo_score_val,
                "seo_score_lbl": seo_score_lbl, "seo_score_icon": seo_score_icon, "seo_score_cor": seo_score_cor,
                "seo_faltando": seo_faltando,
                "seo_title": seo.get("title",""), "seo_desc": seo.get("description",""),
                "seo_h1": seo.get("h1",""), "seo_h2s": seo.get("h2s",[]),
                "seo_extraido_em": seo.get("extraido_em",""), "seo_contato": seo.get("contato",{}),
                "sitemap_urls": sitemap.get("urls",[]), "sitemap_total": sitemap.get("total",0),
                "sitemap_status": sitemap.get("status",""),
                "tem_ads": tem_ads, "ads": ads_info,
            })

        # ── Tooltip CSS ────────────────────────────────────────────────
        tooltip_css = """
/* ── Tooltip genérico para badges de oportunidade ── */
.oport-wrap {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: default;
}
.oport-wrap .oport-tip {
    display: none;
    position: absolute;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    background: #1a2e4a;
    color: #fff;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 11px;
    line-height: 1.9;
    min-width: 190px;
    max-width: 230px;
    z-index: 9999;
    white-space: normal;
    box-shadow: 0 6px 20px rgba(0,0,0,0.28);
    pointer-events: none;
    font-family: 'DM Sans', sans-serif;
    text-align: left;
}
.oport-wrap .oport-tip::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: #1a2e4a;
}
.oport-wrap:hover .oport-tip { display: block; }

/* ── Score tooltip (ícone ?) ── */
.score-tooltip-wrap { position:relative; display:inline-flex; align-items:center; }
.score-tooltip-wrap .tip {
    display:none; position:absolute; bottom:22px; left:50%; transform:translateX(-50%);
    background:#1a2e4a; color:#fff; border-radius:8px; padding:10px 12px; font-size:11px;
    line-height:1.8; width:200px; z-index:9999; white-space:normal;
    box-shadow:0 4px 16px rgba(0,0,0,0.25); pointer-events:none; font-family:'DM Sans',sans-serif;
}
.score-tooltip-wrap .tip::after {
    content:''; position:absolute; top:100%; left:50%; transform:translateX(-50%);
    border:5px solid transparent; border-top-color:#1a2e4a;
}
.score-tooltip-wrap:hover .tip { display:block; }
.q-badge {
    width:14px; height:14px; border-radius:50%; background:#e5e7eb; display:inline-flex;
    align-items:center; justify-content:center; font-size:9px; font-weight:800; color:#9ca3af;
    cursor:default; flex-shrink:0; margin-left:5px;
}
"""

        # ── Monta HTML de cada empresa ─────────────────────────────────
        for d in empresas_cards_data:

            # ── REDES SOCIAIS ──────────────────────────────────────────
            if d["tem_redes"]:
                m = d["redes"]

                def stat_item(icon_path, icon_color, icon_bg, valor, valor_color, label):
                    return (
                        f'<div style="display:flex;flex-direction:column;align-items:center;gap:6px;flex:1;">'
                        f'<div style="width:38px;height:38px;border-radius:50%;background:{icon_bg};'
                        f'display:flex;align-items:center;justify-content:center;flex-shrink:0;">'
                        f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="{icon_color}" '
                        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{icon_path}</svg>'
                        f'</div>'
                        f'<div style="font-size:16px;font-weight:800;color:{valor_color};line-height:1;">{valor}</div>'
                        f'<div style="font-size:9px;color:#9ca3af;font-weight:700;text-transform:uppercase;'
                        f'letter-spacing:0.5px;white-space:nowrap;">{label}</div>'
                        f'</div>'
                    )

                path_seg  = '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>'
                path_eng  = '<path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/>'
                path_post = '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>'
                path_enm  = '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>'

                stats_block_html = (
                    '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:10px;">'
                    '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;margin-bottom:14px;">Estatísticas</div>'
                    '<div style="display:flex;gap:4px;align-items:flex-start;">'
                    + stat_item(path_seg,  "#6b7280", "#f3f4f6", m["seg"],     "#111827", "Seguid.")
                    + stat_item(path_eng,  "#3a9fd6", "#e0f2fe", m["eng"],     "#3a9fd6", "Engaj.%")
                    + stat_item(path_post, "#8b5cf6", "#f5f3ff", m["posts"],   "#374151", "Posts")
                    + stat_item(path_enm,  "#22c55e", "#f0fdf4", m["eng_med"], "#374151", "Eng/Post")
                    + '</div></div>'
                )

                score_nok = m["score_oportunidades"]
                score_faltando_html = "".join(f'<div style="display:flex;align-items:center;gap:5px;">❌ {f}</div>' for f in m.get("score_faltando", []))
                if score_nok > 0:
                    score_nok_html = (
                        f'<div class="oport-wrap">'
                        f'<div style="display:inline-flex;align-items:center;font-size:11px;font-weight:700;'
                        f'color:#2563eb;background:#dbeafe;padding:4px 11px;border-radius:20px;white-space:nowrap;flex-shrink:0;">+'
                        f'{score_nok} oportunidade{"s" if score_nok != 1 else ""}</div>'
                        f'<div class="oport-tip"><div style="font-size:11px;font-weight:700;color:#93c5fd;margin-bottom:6px;">O que melhorar:</div>'
                        f'{score_faltando_html}</div>'
                        f'</div>'
                    )
                else:
                    score_nok_html = ""

                score_chips_html = "".join(
                    '<div class="score-chip-ok"><span class="score-check"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span> ' + c["label"] + '</div>'
                    for c in m["score_criterios"] if c["ok"]
                )

                score_block_html = (
                    '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
                    '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">'
                    '<div style="display:flex;align-items:center;">'
                    '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;">Score de Perfil</div>'
                    '<div class="score-tooltip-wrap"><div class="q-badge">?</div>'
                    '<div class="tip"><span style="font-size:11px;font-weight:700;color:#fff;">Como é calculado:</span><br>'
                    '✅ Tem bio +20<br>✅ Proposta de valor +20<br>✅ Posicionamento +20<br>'
                    '✅ Link na bio +15<br>✅ CTA na bio +15<br>✅ Engajamento ≥3% +10'
                    '</div></div></div>'
                    + score_nok_html +
                    '</div>'
                    '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;">'
                    '<div style="display:flex;align-items:baseline;gap:4px;line-height:1;flex-shrink:0;">'
                    f'<span style="font-size:30px;font-weight:900;letter-spacing:-2px;line-height:1;color:{m["score_cor"]};">{m["score_val"]}</span>'
                    '<span style="font-size:15px;font-weight:600;color:#9ca3af;">/100</span></div>'
                    f'<div style="display:inline-flex;align-items:center;gap:7px;padding:8px 16px;border-radius:12px;font-size:14px;font-weight:800;background:{m["score_cor"]}1a;color:{m["score_cor"]};white-space:nowrap;flex-shrink:0;">'
                    f'{m["score_icon"]} {m["score_lbl"]}</div></div>'
                    f'<div style="height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden;margin-bottom:10px;">'
                    f'<div style="height:100%;width:{m["score_val"]}%;border-radius:4px;background:linear-gradient(90deg,#3b82f6,{m["score_cor"]});"></div></div>'
                    f'<div style="display:flex;flex-wrap:wrap;">{score_chips_html}</div>'
                    '</div>'
                )

                # Tipos de conteúdo
                tipo_donuts = (
                    '<div style="display:flex;gap:8px;align-items:center;">'
                    + make_donut_svg(m["pct_foto"], d["cor"], "Fotos",     m["n_fotos"])
                    + make_donut_svg(m["pct_vid"],  d["cor"], "Reels",     m["n_videos"])
                    + make_donut_svg(m["pct_carr"], d["cor"], "Carrossel", m["n_carrossel"])
                    + '</div>'
                )

                tipos_block_html = (
                    '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
                    '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">'
                    '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;">Tipos de Conteúdo</div>'
                    f'<div style="font-size:11px;font-weight:700;color:#374151;background:#f3f4f6;padding:3px 10px;border-radius:20px;white-space:nowrap;">Total: {m["n_total_tp"]}</div>'
                    '</div>' + tipo_donuts + '</div>'
                )

                # ── Nuvem de palavras ──────────────────────────────────
                nuvem = m.get("nuvem_palavras", [])
                if nuvem:
                    COLOR_NUVEM_TXT = [
                        "#1d4ed8", "#15803d", "#7e22ce", "#c2410c",
                        "#0f766e", "#b91c1c", "#854d0e", "#334155",
                    ]
                    nuvem_chips = ""
                    for idx, (palavra, freq) in enumerate(nuvem):
                        txt_c = COLOR_NUVEM_TXT[idx % len(COLOR_NUVEM_TXT)]
                        nuvem_chips += (
                            f'<span style="display:inline-flex;align-items:center;gap:2px;font-size:11px;'
                            f'font-weight:600;background:#f8f8f8;color:{txt_c};padding:3px 10px;'
                            f'border-radius:20px;line-height:1.3;white-space:nowrap;cursor:default;">'
                            f'{palavra}'
                            f'<span style="font-size:9px;font-weight:700;opacity:0.55;margin-left:2px;">{freq}x</span>'
                            f'</span>'
                        )
                    nuvem_block_html = (
                        '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
                        '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;margin-bottom:10px;">Nuvem de Palavras</div>'
                        f'<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;">{nuvem_chips}</div>'
                        '</div>'
                    )
                else:
                    nuvem_block_html = ""

                redes_block_html = stats_block_html + score_block_html + tipos_block_html + nuvem_block_html
            else:
                redes_block_html = (
                    '<div style="text-align:center;padding:20px 10px;background:#f9fafb;border:1px dashed #e5e7eb;border-radius:10px;">'
                    '<div style="font-size:20px;margin-bottom:6px;">📊</div>'
                    '<div style="font-size:11px;color:#9ca3af;">Sem dados de redes sociais coletados</div></div>'
                )
            d["redes_block_html"] = redes_block_html

            # ── ANÚNCIOS ───────────────────────────────────────────────
            if d["tem_ads"]:
                a = d["ads"]
                total_ads = a["total"] or 1

                def barra_tipo(label, valor, total, cor):
                    pct = round(valor / total * 100) if total else 0
                    return (
                        '<div style="margin-bottom:8px;">'
                        '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">'
                        f'<span style="font-size:11px;color:#374151;font-weight:600;">{label}</span>'
                        f'<span style="font-size:11px;font-weight:800;color:{cor};">{valor}</span></div>'
                        f'<div style="height:5px;background:#e5e7eb;border-radius:3px;overflow:hidden;">'
                        f'<div style="height:100%;width:{pct}%;background:{cor};border-radius:3px;"></div></div></div>'
                    )

                formato_donuts = (
                    '<div style="display:flex;gap:8px;align-items:center;">'
                    + make_donut_svg(round(a["video"]     / total_ads * 100), d["cor"], "Vídeo",     a["video"])
                    + make_donut_svg(round(a["imagem"]    / total_ads * 100), d["cor"], "Imagem",    a["imagem"])
                    + make_donut_svg(round(a["carrossel"] / total_ads * 100), d["cor"], "Carrossel", a["carrossel"])
                    + '</div>'
                )
                ads_formato_block = (
                    '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
                    '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">'
                    '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;">Formato</div>'
                    f'<div style="font-size:11px;font-weight:700;color:#374151;background:#f3f4f6;padding:3px 10px;border-radius:20px;white-space:nowrap;">Total: {a["total"]}</div>'
                    '</div>' + formato_donuts + '</div>'
                )

                ads_tipos_block = (
                    '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
                    '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;margin-bottom:12px;">Tipos de anúncio</div>'
                    + barra_tipo("💰 Com benefício",    a["beneficio"],    total_ads, "#3a9fd6")
                    + barra_tipo("👥 Com prova social", a["prova_social"], total_ads, "#22c55e")
                    + barra_tipo("⏰ Com urgência",     a["urgencia"],     total_ads, "#f59e0b")
                    + barra_tipo("👉 CTA direto",       a["cta_direto"],   total_ads, "#8b5cf6")
                    + '</div>'
                )

                plat_dict  = a.get("plataformas", {})
                plat_total = sum(plat_dict.values()) or 1
                plat_items = sorted(plat_dict.items(), key=lambda x: x[1], reverse=True)[:5]

                plat_donuts = '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start;">'
                for plat_key, plat_val in plat_items:
                    cor_plat, label_plat, _ = PLAT_ICONS_SVG.get(plat_key, ("#64748b", plat_key.capitalize(), ""))
                    pct_plat = round(plat_val / plat_total * 100)
                    plat_donuts += make_donut_plat(pct_plat, cor_plat, label_plat, plat_val, plat_key, size=52, stroke=5)
                plat_donuts += '</div>'

                ads_plat_block = (
                    '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
                    '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;margin-bottom:12px;">Plataformas</div>'
                    + plat_donuts + '</div>'
                )

                destinos = a.get("destinos", [])
                if destinos:
                    dest_max  = max(v for _, v in destinos) or 1
                    dest_rows = ""
                    for dom, cnt in destinos:
                        pct = round(cnt / dest_max * 100)
                        dom_display = dom if len(dom) <= 28 else dom[:25] + "…"
                        dest_rows += (
                            '<div style="margin-bottom:8px;">'
                            '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">'
                            f'<span style="font-size:11px;color:#374151;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:75%;">🔗 {dom_display}</span>'
                            f'<span style="font-size:11px;font-weight:800;color:#1a2e4a;">{cnt}</span></div>'
                            f'<div style="height:5px;background:#e5e7eb;border-radius:3px;overflow:hidden;">'
                            f'<div style="height:100%;width:{pct}%;background:#6366f1;border-radius:3px;"></div></div></div>'
                        )
                    ads_dest_content = dest_rows
                else:
                    ads_dest_content = '<div style="font-size:11px;color:#d1d5db;font-style:italic;">Sem dados de destino</div>'

                ads_dest_block = (
                    '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
                    '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;margin-bottom:12px;">Destinos dos anúncios</div>'
                    + ads_dest_content + '</div>'
                )

                ads_block_html = ads_formato_block + ads_tipos_block + ads_plat_block + ads_dest_block
            else:
                ads_block_html = (
                    '<div style="text-align:center;padding:20px 10px;background:#f9fafb;border:1px dashed #e5e7eb;border-radius:10px;">'
                    '<div style="font-size:20px;margin-bottom:6px;">📣</div>'
                    '<div style="font-size:11px;color:#9ca3af;">Sem dados de anúncios coletados</div></div>'
                )
            d["ads_block_html"] = ads_block_html

        empresas_cards_json = _json.dumps(empresas_cards_data, ensure_ascii=False)

        components.html(f"""
<!DOCTYPE html><html>
<head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
body {{ padding-bottom:8px; }}
{tooltip_css}
.empresa-card {{
    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
    padding:18px 20px 20px; margin-top:16px; overflow:hidden;
}}
/* ── Cabeçalho do card ── */
.empresa-card-hdr {{ display:flex; align-items:center; gap:10px; margin-bottom:10px; }}
.empresa-card-nome {{ font-size:16px; font-weight:800; color:#1a2e4a; flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.badge {{ display:inline-block; padding:2px 9px; border-radius:20px; font-size:10px; font-weight:700; flex-shrink:0; }}
/* ── Divisor abaixo do nome ── */
.empresa-card-divider {{ border:none; border-top:1.5px solid #e5e7eb; margin:0 0 16px 0; }}
/* ── Grid de colunas ── */
.cols-wrap {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; align-items:start; }}
.col {{ display:flex; flex-direction:column; min-width:0; }}
/* ── Título de coluna com cor específica por seção ── */
.col-title {{
    display:flex; align-items:center; gap:6px; font-size:12px; font-weight:800;
    text-transform:uppercase; letter-spacing:0.5px;
    padding:8px 12px; border-radius:8px; margin-bottom:10px;
}}
.col-title-redes  {{ background:#eff6ff; color:#1d4ed8; border-left:3px solid #3b82f6; }}
.col-title-site   {{ background:#f0fdf4; color:#15803d; border-left:3px solid #22c55e; }}
.col-title-ads    {{ background:#fff7ed; color:#c2410c; border-left:3px solid #f97316; }}
/* ── Borda lateral colorida por coluna ── */
.col-redes  {{ border-left:2px solid #3b82f620; padding-left:8px; margin-left:-8px; }}
.col-site   {{ border-left:2px solid #22c55e20; padding-left:8px; margin-left:-8px; }}
.col-ads    {{ border-left:2px solid #f9731620; padding-left:8px; margin-left:-8px; }}
.placeholder-box {{
    text-align:center; padding:14px 10px; background:#f9fafb; border:1px dashed #e5e7eb;
    border-radius:8px; font-size:10px; color:#b0b6bf; font-style:italic;
}}
.contato-grupo-title {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:0.7px; color:#b0b8c4; margin-bottom:7px; }}
.contato-chips {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:4px; }}
.contato-chip {{ display:inline-flex; align-items:center; gap:3px; font-size:11px; font-weight:600; color:#374151; }}
.contato-divider {{ border:none; border-top:1px solid #f3f4f6; margin:8px 0; }}
.termos-sub {{ font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:0.7px; color:#b0b8c4; margin-bottom:7px; }}
.termos-chips {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:8px; }}
.termo-chip {{ display:inline-flex; align-items:center; gap:2px; font-size:11px; font-weight:600; background:#f8f8f8; border-radius:20px; padding:3px 10px; cursor:default; line-height:1.3; }}
.termo-chip-bigram {{ border-radius:10px; padding:4px 11px; }}
.termo-count {{ font-size:9px; font-weight:700; opacity:0.55; margin-left:2px; }}
.score-chip-ok {{ display:inline-flex; align-items:center; gap:3px; font-size:11px; font-weight:600; color:#15803d; padding:2px 4px; white-space:nowrap; }}
.score-check {{ border:1px solid #22c45f; border-radius:5px; background:#22c45e; width:10px; height:10px; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0; }}
@media (max-width:760px) {{ .cols-wrap {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div id="cards"></div>
<script>
var DATA = {empresas_cards_json};
function esc(s) {{ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

var CONTACT_ICONS = {{
    whatsapp:'<svg width="15" height="15" viewBox="0 0 24 24" fill="#3593cf"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>',
    telefone:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M6.62 10.79a15.05 15.05 0 006.59 6.59l2.2-2.2a1 1 0 011.01-.24c1.12.37 2.33.57 3.58.57a1 1 0 011 1V20a1 1 0 01-1 1C9.61 21 3 14.39 3 6a1 1 0 011-1h3.5a1 1 0 011 1c0 1.25.2 2.46.57 3.58a1 1 0 01-.25 1.01l-2.2 2.2z"/></svg>',
    email:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M20 4H4a2 2 0 00-2 2v12a2 2 0 002 2h16a2 2 0 002-2V6a2 2 0 00-2-2zm0 4.7l-8 5.334L4 8.7V6.297l8 5.333 8-5.333V8.7z"/></svg>',
    instagram:'<svg width="15" height="15" viewBox="0 0 24 24" fill="#3593cf"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/></svg>',
    facebook:'<svg width="15" height="15" viewBox="0 0 24 24" fill="#3593cf"><path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.268h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/></svg>',
    linkedin:'<svg width="15" height="15" viewBox="0 0 24 24" fill="#3593cf"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>',
    youtube:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M23.495 6.205a3.007 3.007 0 00-2.088-2.088c-1.87-.501-9.396-.501-9.396-.501s-7.507-.01-9.396.501A3.007 3.007 0 00.527 6.205a31.247 31.247 0 00-.522 5.805 31.247 31.247 0 00.522 5.783 3.007 3.007 0 002.088 2.088c1.868.502 9.396.502 9.396.502s7.506 0 9.396-.502a3.007 3.007 0 002.088-2.088 31.247 31.247 0 00.5-5.783 31.247 31.247 0 00-.5-5.805zM9.609 15.601V8.408l6.264 3.602z"/></svg>',
    chat_ao_vivo:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2zm-2 10H6v-2h12v2zm0-3H6V7h12v2z"/></svg>',
    formulario:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm-1 7V3.5L18.5 9H13zm-5 4h8v2H8v-2zm0 4h5v2H8v-2z"/></svg>',
    botao_flutuante:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5 11h-4v4h-2v-4H7v-2h4V7h2v4h4v2z"/></svg>',
    popup_saida:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zm-3.293 10.293l-1.414 1.414L12 12.414l-2.293 2.293-1.414-1.414L10.586 11 8.293 8.707l1.414-1.414L12 9.586l2.293-2.293 1.414 1.414L13.414 11l2.293 2.293z"/></svg>',
    popup_rolagem:'<svg width="16" height="16" viewBox="0 0 24 24" fill="#3593cf"><path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zm-7 13l-5-5 1.41-1.41L12 13.17l7.59-7.59L21 7l-9 9z"/></svg>',
}};
var CONTACT_LABEL_MAP = {{
    whatsapp:'WhatsApp',telefone:'Telefone',email:'E-mail',instagram:'Instagram',
    facebook:'Facebook',linkedin:'LinkedIn',youtube:'YouTube',chat_ao_vivo:'Chat ao vivo',
    formulario:'Formulário',botao_flutuante:'Btn. flutuante',popup_saida:'Popup saída',popup_rolagem:'Popup rolagem',
}};
var CONTACT_GRUPOS = [
    {{titulo:'Contato direto',keys:['whatsapp','telefone','email']}},
    {{titulo:'Redes sociais',keys:['instagram','facebook','linkedin','youtube']}},
    {{titulo:'Recursos de engajamento',keys:['chat_ao_vivo','formulario','botao_flutuante','popup_saida','popup_rolagem']}},
];
var STOP_WORDS = new Set(['de','da','do','das','dos','em','e','a','o','as','os','um','uma','uns','umas','para','por','com','que','se','na','no','nas','nos','ao','aos','à','às','mais','ou','mas','como','são','sua','seu','suas','seus','esta','este','essa','esse','pelo','pela','pelos','pelas','entre','até','já','pra','pro','pros','pras','vai','vão','tem','têm','bem','sim','não','sem','só','lá','cá','você','voce','além','isso','isto','aquilo','tudo','nada','muito','muita','muitos','muitas','pouco','poucos','poucas','dia','ano','mês','vez','aqui','ali','anos','dias','meses','vezes','todo','toda','todos','todas','ser','ter','pode','nosso','nossa','nossos','nossas','qual','quais','quando','onde','quem','porque','clique','clicar','acesse','acessar','saiba','saber','veja','ver','descubra','descobrir','confira','conferir','fale','contate','contatar','receba','receber','envie','enviar','inscreva','inscrever','baixe','baixar','assine','assinar','comece','começar','inicie','iniciar','experimente','testar','teste','ligue','ligar','entrar','entre','sair','voltar','conheça','conhecer','aprenda','aprender','entenda','entender','ofereça','oferecer','oferecendo','garantir','garanta','crescer','cresça','facilitar','facilitamos','acabar','acabam','ajudar','ajudamos','transformar','transformamos','impulsionar','realizar','realizamos','promover','promovemos','permitir','permitimos','gerar','geramos','presentes','presença','presente','melhor','melhorar','grande','maior','menor','rápido','fácil','simples','novo','nova','novos','novas','completo','completa','completos','completas','único','única','especial','especiais','perfeito','perfeita','ideal','principais','principal','importante','importantes','eficiente','eficientes','inovador','inovadora','moderno','moderna','avançado','avançada','the','and','of','to','in','is','it','for','on','with','that','this','are','from','at','an','be','by','not','or','was','we','our','your','have','has','will','can','more','also','their','which','about','when','than','its','into','been','they','them','what','who']);
var COLOR_PALETTE = [
    {{bg:'#eff6ff',border:'#93c5fd',text:'#1d4ed8'}},{{bg:'#f0fdf4',border:'#6ee7b7',text:'#15803d'}},
    {{bg:'#fdf4ff',border:'#d8b4fe',text:'#7e22ce'}},{{bg:'#fff7ed',border:'#fdba74',text:'#c2410c'}},
    {{bg:'#f0fdfa',border:'#5eead4',text:'#0f766e'}},{{bg:'#fef2f2',border:'#fca5a5',text:'#b91c1c'}},
];
function isVerbLike(w) {{ return /^(clica|acessa|saib|vej|descubr|confir|receb|envi|inscrev|baix|assin|comec|inici|experim|lig|entr|conhec|aprend|entend|ofer|garant|cresc|facilit|acab|ajud|transform|impulsion|realiz|promov|permit|ger|apresent|mostr|demonstr|ilustr|explor|desenvolv)/.test(w); }}
function calcTopWords(d) {{
    var textoFull = [d.seo_title||'',d.seo_h1||'',d.seo_desc||''].concat(d.seo_h2s||[]).join(' ');
    var textoNorm = textoFull.toLowerCase().replace(/[^a-záéíóúàãõâêîôûçñü\\s]/gi,' ');
    var tokens = textoNorm.split(/\\s+/).filter(function(w){{return w.length>=2;}});
    function bigramKey(w1,w2){{return [w1,w2].sort().join('|');}}
    var freqBiRaw={{}};
    for(var bi=0;bi<tokens.length-1;bi++){{
        var w1=tokens[bi],w2=tokens[bi+1];
        if(w1.length>=3&&w2.length>=3&&!STOP_WORDS.has(w1)&&!STOP_WORDS.has(w2)&&!isVerbLike(w1)&&!isVerbLike(w2)){{
            var bk=bigramKey(w1,w2);
            if(!freqBiRaw[bk])freqBiRaw[bk]={{count:0,displayPair:w1+' '+w2}};
            freqBiRaw[bk].count++;
        }}
    }}
    var freqUni={{}};
    tokens.forEach(function(w){{if(w.length>=5&&!STOP_WORDS.has(w)&&!isVerbLike(w))freqUni[w]=(freqUni[w]||0)+1;}});
    var usedInBigram=new Set(),combined=[];
    Object.keys(freqBiRaw).forEach(function(bk){{
        var entry=freqBiRaw[bk];
        if(entry.count>=2){{var parts=bk.split('|');usedInBigram.add(parts[0]);usedInBigram.add(parts[1]);combined.push({{word:entry.displayPair,count:entry.count}});}}
    }});
    Object.keys(freqBiRaw).forEach(function(bk){{
        var entry=freqBiRaw[bk];
        if(entry.count===1){{
            var parts=bk.split('|');
            if(parts[0].length>=5&&parts[1].length>=5&&!usedInBigram.has(parts[0])&&!usedInBigram.has(parts[1])&&(freqUni[parts[0]]||0)<=1&&(freqUni[parts[1]]||0)<=1&&parts[0].length>=4&&parts[1].length>=4){{
                usedInBigram.add(parts[0]);usedInBigram.add(parts[1]);combined.push({{word:entry.displayPair,count:1}});
            }}
        }}
    }});
    Object.keys(freqUni).forEach(function(w){{if(!usedInBigram.has(w))combined.push({{word:w,count:freqUni[w]}});}});
    return combined.filter(function(item){{return item.word.split(' ').every(function(p){{return p.length>=3;}});}})
        .sort(function(a,b){{return b.count-a.count;}}).filter(function(item){{return item.count>1;}}).slice(0,14);
}}
function buildSeoColumn(d,colEl) {{
    if(!d.seo_status_ok){{colEl.innerHTML+='<div class="placeholder-box">Extraia o SEO na página de Sites para ver os dados aqui.</div>';return;}}
    var scoreNum=d.seo_score_val;
    var scoreTextColor=scoreNum>=80?'#15803d':scoreNum>=40?'#92400e':'#b91c1c';
    var scoreBg=scoreNum>=80?'#f0fdf4':scoreNum>=40?'#fffbeb':'#fef2f2';
    var scoreTxt2=scoreNum>=80?'Excelente 🏆':scoreNum>=60?'Bom 👍':scoreNum>=40?'Regular ⚠️':'Precisa melhorar 📝';
    var scoreBarColor=scoreNum>=80?'#22c55e':scoreNum>=40?'#f59e0b':'#ef4444';
    var scoreBarId='seo_dash_bar_'+Math.random().toString(36).slice(2);
    var SEO_ITEMS=[
        {{label:'Title',ok:!!d.seo_title}},{{label:'H1',ok:!!d.seo_h1}},
        {{label:'Meta Desc.',ok:!!d.seo_desc}},{{label:'Seções (H2)',ok:d.seo_h2s&&d.seo_h2s.length>0}},
        {{label:'Sitemap',ok:d.sitemap_status==='ok'}},
    ];
    var nok=SEO_ITEMS.filter(function(i){{return !i.ok;}}).length;
    var seoFaltandoHtml=(d.seo_faltando||[]).map(function(f){{return '<div style="display:flex;align-items:center;gap:5px;">❌ '+esc(f)+'</div>';}}).join('');
    var nokHtml='';
    if(nok>0){{
        nokHtml='<div class="oport-wrap">'
            +'<div style="display:inline-flex;align-items:center;font-size:11px;font-weight:700;color:#2563eb;background:#dbeafe;padding:4px 11px;border-radius:20px;white-space:nowrap;flex-shrink:0;">+'+nok+' oportunidade'+(nok!==1?'s':'')+'</div>'
            +'<div class="oport-tip"><div style="font-size:11px;font-weight:700;color:#93c5fd;margin-bottom:6px;">O que melhorar:</div>'+seoFaltandoHtml+'</div>'
            +'</div>';
    }}
    var chipsHtml='';
    SEO_ITEMS.forEach(function(it){{if(it.ok)chipsHtml+='<div class="score-chip-ok"><span class="score-check"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span> '+it.label+'</div>';}});

    /* ── Score de SEO com badge "?" igual ao de Redes ── */
    var scoreBlock=document.createElement('div');
    scoreBlock.style.cssText='background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;';
    scoreBlock.innerHTML=
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">'
        +'<div style="display:flex;align-items:center;">'
        +'<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;">Score de SEO</div>'
        +'<div class="score-tooltip-wrap"><div class="q-badge">?</div>'
        +'<div class="tip"><span style="font-size:11px;font-weight:700;color:#fff;">Como é calculado:</span><br>'
        +'✅ Title +20<br>✅ H1 +20<br>✅ Meta Desc. +20<br>✅ Seções (H2) +20<br>✅ Sitemap +20'
        +'</div></div>'
        +'</div>'
        +nokHtml+'</div>'
        +'<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;">'
        +'<div style="display:flex;align-items:baseline;gap:4px;line-height:1;flex-shrink:0;"><span style="font-size:30px;font-weight:900;letter-spacing:-2px;line-height:1;color:'+scoreTextColor+';">'+scoreNum+'</span><span style="font-size:15px;font-weight:600;color:#9ca3af;">/100</span></div>'
        +'<div style="display:inline-flex;align-items:center;gap:7px;padding:8px 16px;border-radius:12px;font-size:14px;font-weight:800;background:'+scoreBg+';color:'+scoreTextColor+';white-space:nowrap;flex-shrink:0;">'+scoreTxt2+'</div></div>'
        +'<div style="height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden;margin-bottom:10px;"><div id="'+scoreBarId+'" style="height:100%;width:0%;border-radius:4px;background:linear-gradient(90deg,#22c55e,'+scoreBarColor+');transition:width 1.2s cubic-bezier(0.4,0,0.2,1);"></div></div>'
        +'<div style="display:flex;flex-wrap:wrap;">'+chipsHtml+'</div>';
    colEl.appendChild(scoreBlock);
    setTimeout(function(){{var bar=document.getElementById(scoreBarId);if(bar)bar.style.width=scoreNum+'%';}},250);
    var ct=d.seo_contato||{{}};
    var gruposHtml='',algumGrupo=false;
    CONTACT_GRUPOS.forEach(function(g){{
        var ativos=g.keys.filter(function(k){{return !!ct[k];}});
        if(!ativos.length)return;
        algumGrupo=true;
        if(gruposHtml)gruposHtml+='<hr class="contato-divider"/>';
        gruposHtml+='<div class="contato-grupo-title">'+g.titulo+'</div><div class="contato-chips">';
        ativos.forEach(function(k){{gruposHtml+='<div class="contato-chip">'+(CONTACT_ICONS[k]||'')+(CONTACT_LABEL_MAP[k]||k)+'</div>';}});
        gruposHtml+='</div>';
    }});
    if(algumGrupo){{
        var ctBlock=document.createElement('div');
        ctBlock.style.cssText='background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;';
        ctBlock.innerHTML='<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;margin-bottom:12px;">Canais de Contato</div>'+gruposHtml;
        colEl.appendChild(ctBlock);
    }}
    var topWords=calcTopWords(d);
    if(topWords.length>0){{
        var bigrams=topWords.filter(function(w){{return w.word.indexOf(' ')>-1;}});
        var unigrams=topWords.filter(function(w){{return w.word.indexOf(' ')===-1;}});
        function makeChip(item,idx,isBigram){{
            var col=COLOR_PALETTE[idx%COLOR_PALETTE.length];
            var countBadge=item.count>1?'<span class="termo-count">'+item.count+'x</span>':'';
            return '<span class="termo-chip'+(isBigram?' termo-chip-bigram':'')+'" style="color:'+col.text+';" title="'+item.count+'x mencionado">'+esc(item.word)+countBadge+'</span>';
        }}
        var bigramsHtml=bigrams.map(function(item,i){{return makeChip(item,i,true);}}).join('');
        var unigramsHtml=unigrams.map(function(item,i){{return makeChip(item,i,false);}}).join('');
        var kwBlock=document.createElement('div');
        kwBlock.style.cssText='background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-bottom:10px;';
        var innerHtml='<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#1a2e4a;margin-bottom:12px;">Termos mais usados</div>';
        if(bigramsHtml)innerHtml+='<div class="termos-sub">Expressões-chave</div><div class="termos-chips">'+bigramsHtml+'</div>';
        if(unigramsHtml)innerHtml+='<div class="termos-sub">Palavras frequentes</div><div class="termos-chips">'+unigramsHtml+'</div>';
        kwBlock.innerHTML=innerHtml;
        colEl.appendChild(kwBlock);
    }}
}}
function buildCards() {{
    var el=document.getElementById('cards');
    DATA.forEach(function(d) {{
        var card=document.createElement('div');
        card.className='empresa-card';
        card.style.borderTop='3px solid '+d.cor;

        /* ── Cabeçalho com nome + divider ── */
        var hdr=document.createElement('div');
        hdr.className='empresa-card-hdr';
        hdr.innerHTML=d.av_html+'<span class="empresa-card-nome">'+esc(d.nome)+'</span>'
            +'<span class="badge" style="background:'+d.badge_bg+';color:'+d.badge_col+';border:1px solid '+d.badge_brd+'">'+d.badge_lbl+'</span>';
        card.appendChild(hdr);

        /* ── HR abaixo do nome ── */
        var divider=document.createElement('hr');
        divider.className='empresa-card-divider';
        card.appendChild(divider);

        /* ── Grid de 3 colunas ── */
        var cols=document.createElement('div');
        cols.className='cols-wrap';

        /* Coluna Redes – azul */
        var colRedes=document.createElement('div');
        colRedes.className='col col-redes';
        colRedes.innerHTML='<div class="col-title col-title-redes">📱 Redes Sociais</div>'+d.redes_block_html;

        /* Coluna Site – verde */
        var colSite=document.createElement('div');
        colSite.className='col col-site';
        var colSiteTitle=document.createElement('div');
        colSiteTitle.className='col-title col-title-site';
        colSiteTitle.textContent='🌐 Site';
        colSite.appendChild(colSiteTitle);
        buildSeoColumn(d,colSite);

        /* Coluna Anúncios – laranja */
        var colAds=document.createElement('div');
        colAds.className='col col-ads';
        colAds.innerHTML='<div class="col-title col-title-ads">📣 Anúncios</div>'+d.ads_block_html;

        cols.appendChild(colRedes);
        cols.appendChild(colSite);
        cols.appendChild(colAds);
        card.appendChild(cols);
        el.appendChild(card);
    }});
    syncH();
}}
function syncH() {{
    var h=Math.max(document.body.scrollHeight,document.documentElement.scrollHeight);
    var iframes=window.parent.document.querySelectorAll('iframe');
    for(var i=0;i<iframes.length;i++){{
        try{{if(iframes[i].contentWindow===window){{iframes[i].style.height=(h+8)+'px';iframes[i].style.marginTop='-20px';break;}}}}catch(e){{}}
    }}
}}
buildCards();
if(window.ResizeObserver)new ResizeObserver(syncH).observe(document.body);
setTimeout(syncH,300);setTimeout(syncH,800);setTimeout(syncH,2000);
</script>
</body></html>
""", height=900, scrolling=False)

    else:
        st.markdown(
            "<div style='background:#fff;border:1px dashed #d1d5db;border-radius:14px;"
            "padding:48px 32px;text-align:center;margin-top:16px'>"
            "<div style='font-size:32px;margin-bottom:12px'>📊</div>"
            "<div style='font-size:15px;font-weight:600;color:#374151;margin-bottom:6px'>Sem empresas cadastradas</div>"
            "<div style='font-size:13px;color:#9ca3af'>Cadastre sua empresa e concorrentes para ver o painel.</div>"
            "</div>",
            unsafe_allow_html=True
        )
        
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
    if "seo_cache" not in st.session_state:
        st.session_state.seo_cache = {}
 
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
        triggered = st.button(f"SITE_IA_{idx_s}", key=f"btn_site_ia_{idx_s}")
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
            <div style="font-size:12px;color:#4a7099;margin-top:3px;">Analisando site com IA…</div>
        </div>
        <div style="font-size:18px;">{icone}</div>
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
        <div style="background:linear-gradient(90deg,#3a9fd6,#22c55e);height:100%;width:{pct}%;transition:width 0.3s;border-radius:8px;"></div>
    </div>
    <div style="background:#071929;border-radius:12px;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #1a3a5a;margin-bottom:4px;">
        <div>
            <div style="font-size:14px;font-weight:700;color:#e2e8f0;">{desc_safe}</div>
            <div style="font-size:12px;color:#4a7099;margin-top:3px;">Relatório comparativo geral…</div>
        </div>
        <div style="font-size:18px;">{icone}</div>
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
    # BARRA DE NAVEGAÇÃO PRINCIPAL
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
            iframes[i].style.marginTop = '-35px';
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
 
        cards_json_str = _json_sites.dumps(cards_data, ensure_ascii=False)
 
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
.btn-wrap-preview {{ padding:0 14px 12px; }}
.btn-analisar {{
    width:100%;padding:11px 0;
    border:1px solid #3a9fd6;border-radius:8px;
    background:#eff6ff;font-size:14px;font-weight:700;color:#1d4ed8;
    cursor:pointer;font-family:'DM Sans',sans-serif;
    transition:background 0.15s;
    display:flex;align-items:center;justify-content:center;gap:7px;
}}
.btn-analisar:hover {{ background:#dbeafe; }}
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
</style>
</head>
<body>
<div class="outer-wrap">
    <div class="cards-grid" id="cards-grid"></div>
</div>
 
<script>
var CARDS = {cards_json_str};
 
function esc(s) {{
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
 
function buildCards() {{
    var grid = document.getElementById('cards-grid');
    grid.innerHTML = '';
 
    CARDS.forEach(function(c) {{
        var card = document.createElement('div');
        card.className = 'site-card';
        card.style.borderTop = '3px solid ' + c.cor;
 
        // ── Header ──────────────────────────────────────────────
        var hdr = document.createElement('div');
        hdr.className = 'card-header';
        hdr.innerHTML =
            '<div class="avatar" style="background:' + c.cor + '">' + c.avatar + '</div>'
            + '<div style="flex:1;min-width:0;overflow:hidden;">'
            +   '<div class="card-name">' + esc(c.nome) + '</div>'
            + '</div>'
            + '<span class="badge" style="'
            +   'background:' + c.badge_bg + ';'
            +   'color:' + c.badge_txt + ';'
            +   'border:1px solid ' + c.badge_brd + ';'
            +   'white-space:nowrap;flex-shrink:0;">'
            + c.badge_lbl
            + '</span>';
        card.appendChild(hdr);
 
        // ── URL row ──
        var urlRow = document.createElement('div');
        urlRow.className = 'url-row';
        urlRow.innerHTML =
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            + '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>'
            + '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'
            + '</svg>'
            + '<span>' + esc(c.url) + '</span>';
        card.appendChild(urlRow);
 
        // ── Preview ──
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

        // ── Botão Analisar com IA ──
        var btnWrapPreview = document.createElement('div');
        btnWrapPreview.className = 'btn-wrap-preview';
        var btnIA = document.createElement('button');
        btnIA.className = 'btn-analisar';
        btnIA.id = 'btn_analisar_' + c.idx;
        btnIA.innerHTML = c.tem_analise ? '🔁 Fazer nova análise com IA' : '✨ Analisar este site com IA';
        btnIA.onclick = (function(idx, btnEl) {{
            return function() {{
                btnEl.disabled = true;
                btnEl.innerHTML = '⏳ Analisando…';
                triggerSiteIA(idx);
            }};
        }})(c.idx, btnIA);
        btnWrapPreview.appendChild(btnIA);
        card.appendChild(btnWrapPreview);

        // ── Badge de análise ──
        if (c.tem_analise && c.ultima_analise) {{
            var abadge = document.createElement('div');
            abadge.className = 'analise-badge';
            abadge.title = 'Ver análise na aba Análise de IA';
            abadge.innerHTML =
                '<div style="display:flex;align-items:center;gap:7px;">'
                + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#15803d" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
                + '<span>Última análise: <b>' + c.ultima_analise + '</b></span>'
                + '</div>'
                + '<span style="font-size:12px;opacity:0.7;">→ Ver análise</span>';
            abadge.onclick = function() {{ triggerAnaliseTab(); }};
            card.appendChild(abadge);
        }}

        // ── Padding final ──
        var spacer = document.createElement('div');
        spacer.style.height = '6px';
        card.appendChild(spacer);
 
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
 
function triggerSiteIA(idx) {{
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
                iframes[i].style.marginTop = '-30px';
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
        st.session_state.sites_analise_vistas = len(analises)

        subtabs_sites_def = [
            ("individual", "🏢", "Individuais"),
            ("geral",      "📋", "Relatórios Gerais"),
        ]

        ghost_subtabs_sites_css = ", ".join([
            f".st-key-btn_sites_analise_sub_{stk}, .stElementContainer:has(.st-key-btn_sites_analise_sub_{stk})"
            for stk, _, _ in subtabs_sites_def
        ])
        st.markdown(f"""
        <style>
        {ghost_subtabs_sites_css} {{
            position:fixed !important; top:-9999px !important; left:-9999px !important;
            width:0 !important; height:0 !important; overflow:hidden !important;
            opacity:0 !important; pointer-events:none !important; display:none !important;
            min-height:0 !important; max-height:0 !important; padding:0 !important; margin:0 !important;
        }}
        </style>
        """, unsafe_allow_html=True)

        if "sites_analise_subtab" not in st.session_state:
            st.session_state.sites_analise_subtab = "individual"

        for stk, _, _ in subtabs_sites_def:
            if st.button(f"sites_analise_sub_{stk}", key=f"btn_sites_analise_sub_{stk}"):
                st.session_state.sites_analise_subtab = stk
                st.rerun()

        subtab_sites = st.session_state.sites_analise_subtab
        contagens_sites = {
            stk: len([a for a in analises if a.get("tipo") == stk])
            for stk, _, _ in subtabs_sites_def
        }

        st.session_state.relatorio_gemini = ""

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.tabs-wrap {{ display:grid; grid-template-columns:repeat(2,1fr); gap:8px; width:100%; }}
.tab-pill {{
    display:flex; align-items:center; justify-content:center; gap:6px;
    padding:10px 8px; border-radius:10px; cursor:pointer;
    border:1.5px solid #e5e7eb; background:#fff; text-decoration:none;
    font-size:13px; font-weight:600; color:#6b7280;
    transition:all 0.15s; white-space:nowrap;
    font-family:'DM Sans',sans-serif; line-height:1; width:100%;
}}
.tab-pill:hover {{ border-color:#3a9fd6; color:#1d4ed8; background:#eff6ff; }}
.tab-pill.active {{ background:#0e2a47; border-color:#0e2a47; color:#fff; }}
.tab-badge {{
    font-size:11px; font-weight:800; padding:2px 8px; border-radius:20px;
    background:#e5e7eb; color:#6b7280; line-height:1.4; flex-shrink:0;
}}
.tab-pill.active .tab-badge {{ background:rgba(255,255,255,0.15); color:#fff; }}
.tab-badge.has {{ background:#3a9fd6; color:#fff; }}
.tab-pill.active .tab-badge.has {{ background:#3a9fd6; color:#fff; }}
</style>
<div class="tabs-wrap">
{''.join([
    f'''<a class="tab-pill {'active' if subtab_sites == stk else ''}"
        href="javascript:void(0)"
        onclick="(function(){{var btns=window.parent.document.querySelectorAll('button');for(var b of btns){{var t=(b.textContent||b.innerText||'').split(/\\s+/).join(' ').trim();if(t==='sites_analise_sub_{stk}'){{b.click();return;}}}}}})()"
    >{icon} {lbl} <span class="tab-badge {'has' if contagens_sites.get(stk,0) > 0 else ''}">{contagens_sites.get(stk,0)}</span></a>'''
    for stk, icon, lbl in subtabs_sites_def
])}
</div>
<script>
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '52px';
            iframes[i].style.marginTop = '-47px';
            break;
        }} }} catch(e) {{}}
    }}
}})();
</script>
""", height=52, scrolling=False)

        lista_sites_ativa = [a for a in analises if a.get("tipo") == subtab_sites]
        icons_sites_map   = {"individual": "🏢", "geral": "📋"}
        labels_sites_map  = {"individual": "Individuais", "geral": "Relatórios Gerais"}
        icon_sites_ativo  = icons_sites_map.get(subtab_sites, "📋")
        label_sites_ativo = labels_sites_map.get(subtab_sites, "")

        def _md_to_html_sites(txt):
            if not txt: return ""
            import re as _re

            txt = txt.replace("&", "&amp;")
            txt = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', txt)
            txt = _re.sub(r'^### (.+)$', r'<h3>\1</h3>', txt, flags=_re.MULTILINE)
            txt = _re.sub(r'^## (.+)$',  r'<h2>\1</h2>', txt, flags=_re.MULTILINE)
            txt = _re.sub(r'^# (.+)$',   r'<h1>\1</h1>', txt, flags=_re.MULTILINE)
            txt = _re.sub(r'^---+$', '<hr>', txt, flags=_re.MULTILINE)

            def _apply_inline(s):
                return _re.sub(r'\*([^*\n]+?)\*', r'<em>\1</em>', s)

            def _get_ol_match(line):
                return _re.match(r'^(\s*)(\d+)\.\s+(.*)', line)

            def _get_ul_match(line):
                return _re.match(r'^(\s*)[\*\-]\s+(.*)', line)

            lines = txt.split('\n')
            output = []
            list_stack = []

            def close_until(target_indent):
                while list_stack and list_stack[-1][1] >= target_indent:
                    tag, _ = list_stack.pop()
                    output.append(f'</{tag}>')

            def close_all():
                while list_stack:
                    tag, _ = list_stack.pop()
                    output.append(f'</{tag}>')

            i = 0
            while i < len(lines):
                line = lines[i]
                if not line.strip():
                    i += 1
                    continue
                stripped = line.strip()
                if _re.match(r'^\s*<(h[123]|hr)', line):
                    close_all()
                    output.append(stripped)
                    i += 1
                    continue
                m_ol = _get_ol_match(line)
                if m_ol:
                    item_indent = len(m_ol.group(1))
                    content     = _apply_inline(m_ol.group(3))
                    close_until(item_indent + 1)
                    if not list_stack or list_stack[-1][1] < item_indent or list_stack[-1][0] != 'ol':
                        if list_stack and list_stack[-1][1] == item_indent and list_stack[-1][0] != 'ol':
                            tag, _ = list_stack.pop()
                            output.append(f'</{tag}>')
                        output.append('<ol>')
                        list_stack.append(('ol', item_indent))
                    output.append(f'<li>{content}</li>')
                    i += 1
                    continue
                m_ul = _get_ul_match(line)
                if m_ul:
                    item_indent = len(m_ul.group(1))
                    content     = _apply_inline(m_ul.group(2))
                    close_until(item_indent + 1)
                    if not list_stack or list_stack[-1][1] < item_indent or list_stack[-1][0] != 'ul':
                        if list_stack and list_stack[-1][1] == item_indent and list_stack[-1][0] != 'ul':
                            tag, _ = list_stack.pop()
                            output.append(f'</{tag}>')
                        output.append('<ul>')
                        list_stack.append(('ul', item_indent))
                    output.append(f'<li>{content}</li>')
                    i += 1
                    continue
                close_all()
                output.append(f'<p>{_apply_inline(stripped)}</p>')
                i += 1

            close_all()
            return '\n'.join(output)

        relatorios_sites_html     = {str(i): _md_to_html_sites(a.get("relatorio","")) for i, a in enumerate(analises)}
        relatorios_sites_json     = _json_sites.dumps(relatorios_sites_html, ensure_ascii=False)
        relatorios_sites_raw      = {str(i): a.get("relatorio","") for i, a in enumerate(analises)}
        relatorios_sites_raw_json = _json_sites.dumps(relatorios_sites_raw, ensure_ascii=False)

        if lista_sites_ativa:
            cards_sites_html = ""
            for a in reversed(lista_sites_ativa):
                idx_real = analises.index(a)
                icon_a   = icons_sites_map.get(a.get("tipo",""), "📋")
                titulo_a = a.get("titulo","—").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                nome_arq = titulo_a.replace(" ","_").replace("/","_").replace("(","").replace(")","").replace(".","")
                cards_sites_html += f"""
        <div class="card-row" style="border-bottom:1px solid #f3f4f6;background:#fff;">
            <div class="card-hdr" data-idx="{idx_real}"
                 style="display:flex;align-items:center;gap:10px;padding:12px 16px;
                        cursor:pointer;background-color:#0e2a47;">
                <span style="font-size:18px;flex-shrink:0;">{icon_a}</span>
                <div style="flex:1;min-width:0;font-size:14px;font-weight:600;color:#ffffff;
                            overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{titulo_a}</div>
                <button class="btn-fullscreen" data-idx="{idx_real}" title="Abrir em tela cheia"
                    style="flex-shrink:0;background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.25);
                           border-radius:6px;width:30px;height:30px;display:flex;align-items:center;
                           justify-content:center;cursor:pointer;transition:background 0.15s;">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"
                         stroke-linecap="round" stroke-linejoin="round">
                        <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
                    </svg>
                </button>
                <button class="btn-raw" data-idx="{idx_real}" title="Ver texto original"
                    style="flex-shrink:0;background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.25);
                           border-radius:6px;width:30px;height:30px;display:flex;align-items:center;
                           justify-content:center;cursor:pointer;transition:background 0.15s;">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"
                         stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="16 18 22 12 16 6"/>
                        <polyline points="8 6 2 12 8 18"/>
                    </svg>
                </button>
                <span class="btn-chevron" data-idx="{idx_real}"
                      style="color:#d1d5db;transition:transform 0.2s;display:flex;align-items:center;flex-shrink:0;cursor:pointer;">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </span>
            </div>
            <div id="sb_{idx_real}" style="display:none;border-top:1px solid #f3f4f6;">
                <div id="sr_{idx_real}"
                     style="font-size:14px;color:#374151;line-height:1.8;padding:14px 16px;word-break:break-word;"></div>
                <div style="display:flex;gap:8px;padding:10px 16px;background:#f9fafb;border-top:1px solid #f3f4f6;">
                    <button class="btn-download" data-idx="{idx_real}" data-filename="{nome_arq}"
                        style="flex:1;padding:9px;border-radius:8px;border:1px solid #e5e7eb;
                               background:#fff;font-size:13px;font-weight:600;color:#374151;
                               cursor:pointer;font-family:'DM Sans',sans-serif;">
                        ⬇️ Baixar .txt
                    </button>
                </div>
            </div>
        </div>"""

            components.html(f"""
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:visible; }}
        body {{ padding-bottom:8px; }}
        [id^="sr_"] h1,[id^="sr_"] h2,[id^="sr_"] h3 {{ font-size:18px; font-weight:800; color:#2454a3; margin:14px 0 11px; padding-bottom:4px; border-bottom:2px solid #e5e7eb; text-transform:uppercase; }}
        [id^="sr_"] p  {{ margin:0 0 8px; line-height:1.7; }}
        [id^="sr_"] ul {{ margin:5px 0 15px 28px; }}
        [id^="sr_"] li {{ margin:0 0 3px; line-height:1.6; }}
        [id^="sr_"] li::marker {{ color:#00c162; }}
        [id^="sr_"] hr {{ display:none; }}
        [id^="sr_"] ol {{ margin:5px 0 15px 5px; list-style:none; counter-reset:meu-contador; }}
        [id^="sr_"] ol > li {{ margin:0 0 3px; line-height:1.6; position:relative; padding-left:35px; margin-bottom:15px; }}
        [id^="sr_"] ol > li::before {{ counter-increment:meu-contador; content:counter(meu-contador); position:absolute; left:0; top:0; background-color:#00aae6; color:#ffffff; border-radius:50%; width:25px; height:25px; display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:bold; }}
        [id^="sr_"] ol > li > ul {{ margin:6px 0 0 0; list-style:none; padding-left:0; }}
        [id^="sr_"] ol > li > ul > li {{ position:relative; padding-left:18px; margin-bottom:8px; line-height:1.6; }}
        [id^="sr_"] ol > li > ul > li::before {{ content:'◦'; position:absolute; left:0; top:0; color:#00aae6; font-size:18px; line-height:1.3; font-weight:normal; background:none; border-radius:0; width:auto; height:auto; }}
        #smb h1,#smb h2,#smb h3 {{ font-size:16px; font-weight:800; color:#0f1f35; margin:18px 0 8px; padding-bottom:6px; border-bottom:2px solid #e5e7eb; text-transform:uppercase; }}
        #smb p  {{ margin:0 0 10px; line-height:1.75; }}
        #smb ul {{ margin:6px 0 14px 24px; }}
        #smb li {{ margin:0 0 4px; line-height:1.65; }}
        #smb li::marker {{ color:#00c162; }}
        #smb hr {{ display:none; }}
        #smb ol {{ margin:5px 0 15px 5px; list-style:none; counter-reset:meu-contador; }}
        #smb ol > li {{ line-height:1.6; position:relative; padding-left:35px; margin-bottom:15px; }}
        #smb ol > li::before {{ counter-increment:meu-contador; content:counter(meu-contador); position:absolute; left:0; top:0; background-color:#00aae6; color:#ffffff; border-radius:50%; width:25px; height:25px; display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:bold; }}
        #smb ol > li > ul {{ margin:6px 0 0 0; list-style:none; padding-left:0; }}
        #smb ol > li > ul > li {{ position:relative; padding-left:18px; margin-bottom:8px; line-height:1.6; }}
        #smb ol > li > ul > li::before {{ content:'◦'; position:absolute; left:0; top:0; color:#00aae6; font-size:18px; line-height:1.3; font-weight:normal; background:none; border-radius:0; width:auto; height:auto; }}
        </style>

        <div style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;margin-top:8px;">
            {cards_sites_html}
        </div>

        <script>
        var RELS     = {relatorios_sites_json};
        var RELS_RAW = {relatorios_sites_raw_json};

        function syncH() {{
            var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
            var frames = window.parent.document.querySelectorAll('iframe');
            for (var i = 0; i < frames.length; i++) {{
                try {{ if (frames[i].contentWindow === window) {{
                    frames[i].style.height = (h + 8) + 'px';
                    frames[i].style.marginTop = '-57px';
                    break;
                }} }} catch(e) {{}}
            }}
        }}

        function toggleSite(idx) {{
            var b = document.getElementById('sb_' + idx);
            var r = document.getElementById('sr_' + idx);
            var chevrons = document.querySelectorAll('.btn-chevron[data-idx="' + idx + '"]');
            if (!b) return;
            var open = b.style.display !== 'none';
            b.style.display = open ? 'none' : 'block';
            chevrons.forEach(function(c) {{ c.style.transform = open ? '' : 'rotate(180deg)'; }});
            if (!open && r && !r.dataset.loaded) {{
                r.innerHTML = RELS[String(idx)] || '';
                r.dataset.loaded = '1';
            }}
            setTimeout(syncH, 100);
        }}

        function abrirModal(idx) {{
            var doc  = window.parent.document;
            var html = RELS[String(idx)] || '';
            var raw  = RELS_RAW[String(idx)] || '';
            var old  = doc.getElementById('sites_modal_overlay');
            if (old) old.remove();
            var ov = doc.createElement('div');
            ov.id = 'sites_modal_overlay';
            ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:999999;'
                + 'display:flex;align-items:flex-start;justify-content:center;padding:32px 24px;overflow-y:auto;';
            ov.addEventListener('click', function(e) {{ if (e.target === ov) fecharModal(); }});
            var box = doc.createElement('div');
            box.style.cssText = 'background:#fff;border-radius:16px;overflow:hidden;width:min(95vw,860px);'
                + 'display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,0.4);';
            var hdr = doc.createElement('div');
            hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:16px 24px;'
                + 'background:#24658e;flex-shrink:0;gap:12px;';
            var titleEl = doc.createElement('div');
            titleEl.style.cssText = 'font-size:15px;font-weight:700;color:#fff;flex:1;min-width:0;'
                + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            titleEl.textContent = 'Análise completa';
            var rawBtn = doc.createElement('button');
            rawBtn.id = 'sites_modal_raw_btn';
            rawBtn.textContent = 'Ver texto original';
            rawBtn.style.cssText = 'padding:6px 14px;border:1px solid rgba(255,255,255,0.3);border-radius:6px;'
                + 'background:rgba(255,255,255,0.12);color:#fff;font-size:12px;font-weight:700;cursor:pointer;'
                + 'font-family:DM Sans,sans-serif;white-space:nowrap;';
            rawBtn.addEventListener('click', function() {{ toggleModalView(html, raw); }});
            var closeBtn = doc.createElement('button');
            closeBtn.textContent = '✕';
            closeBtn.style.cssText = 'width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.12);'
                + 'border:1px solid rgba(255,255,255,0.25);color:#fff;font-size:17px;cursor:pointer;'
                + 'display:flex;align-items:center;justify-content:center;flex-shrink:0;';
            closeBtn.addEventListener('click', fecharModal);
            hdr.appendChild(titleEl);
            hdr.appendChild(rawBtn);
            hdr.appendChild(closeBtn);
            var body = doc.createElement('div');
            body.id = 'smb';
            body.style.cssText = 'padding:28px 32px;font-size:14px;color:#374151;line-height:1.85;'
                + 'overflow-y:auto;max-height:75vh;word-break:break-word;';
            body.innerHTML = html || '<p style="color:#9ca3af">Sem conteúdo.</p>';
            box.appendChild(hdr);
            box.appendChild(body);
            ov.appendChild(box);
            doc.body.appendChild(ov);
            window.__sitesModalShowingRaw = false;
            window.parent.__sitesModalEsc = function(e) {{ if (e.key === 'Escape') fecharModal(); }};
            doc.addEventListener('keydown', window.parent.__sitesModalEsc);
        }}

        function toggleModalView(html, raw) {{
            var doc  = window.parent.document;
            var body = doc.getElementById('smb');
            var btn  = doc.getElementById('sites_modal_raw_btn');
            if (!body || !btn) return;
            window.__sitesModalShowingRaw = !window.__sitesModalShowingRaw;
            if (window.__sitesModalShowingRaw) {{
                body.style.cssText += ';font-family:monospace;white-space:pre-wrap;font-size:12.5px;background:#0d1117;color:#e6edf3;';
                body.textContent = raw;
                btn.textContent  = 'Ver formatado';
            }} else {{
                body.style.fontFamily = ''; body.style.whiteSpace = '';
                body.style.fontSize   = '14px'; body.style.background = '#fff'; body.style.color = '#374151';
                body.innerHTML  = html;
                btn.textContent = 'Ver texto original';
            }}
        }}

        function fecharModal() {{
            var doc = window.parent.document;
            var ov  = doc.getElementById('sites_modal_overlay');
            if (ov) ov.remove();
            if (window.parent.__sitesModalEsc) {{
                doc.removeEventListener('keydown', window.parent.__sitesModalEsc);
                window.parent.__sitesModalEsc = null;
            }}
        }}

        function abrirRaw(idx) {{
            var doc = window.parent.document;
            var raw = RELS_RAW[String(idx)] || '';
            var old = doc.getElementById('sites_raw_overlay');
            if (old) old.remove();
            var ov = doc.createElement('div');
            ov.id = 'sites_raw_overlay';
            ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:999999;'
                + 'display:flex;align-items:center;justify-content:center;padding:24px;';
            ov.addEventListener('click', function(e) {{ if (e.target === ov) ov.remove(); }});
            var box = doc.createElement('div');
            box.style.cssText = 'background:#0d1117;border-radius:16px;overflow:hidden;width:min(95vw,1000px);'
                + 'max-height:88vh;display:flex;flex-direction:column;border:1px solid #1e395e;';
            var hdr = doc.createElement('div');
            hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:14px 22px;'
                + 'border-bottom:1px solid #1e395e;background:#0e1e35;flex-shrink:0;';
            var info = doc.createElement('div');
            info.innerHTML = '<div style="font-size:14px;font-weight:700;color:#e6edf3;font-family:DM Sans,sans-serif;">📄 Texto original</div>'
                + '<div style="font-size:11px;color:#8b949e;margin-top:2px;">Markdown bruto</div>';
            var btnsWrap = doc.createElement('div');
            btnsWrap.style.cssText = 'display:flex;gap:8px;';
            var copyBtn = doc.createElement('button');
            copyBtn.textContent = '📋 Copiar';
            copyBtn.style.cssText = 'padding:6px 14px;border:1px solid #1e395e;border-radius:7px;background:#0e1e35;'
                + 'color:#22c45e;font-size:12px;font-weight:700;cursor:pointer;';
            copyBtn.addEventListener('click', function() {{
                var ta = doc.createElement('textarea');
                ta.value = raw;
                ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;';
                doc.body.appendChild(ta); ta.focus(); ta.select();
                try {{ doc.execCommand('copy'); copyBtn.textContent = '✅ Copiado!'; }}
                catch(e) {{ copyBtn.textContent = '❌ Erro'; }}
                doc.body.removeChild(ta);
                setTimeout(function() {{ copyBtn.textContent = '📋 Copiar'; }}, 2000);
            }});
            var closeRaw = doc.createElement('button');
            closeRaw.textContent = '✕';
            closeRaw.style.cssText = 'width:32px;height:32px;border-radius:50%;background:#0e1e35;'
                + 'border:1px solid #1e395e;color:#22c45e;font-size:17px;cursor:pointer;'
                + 'display:flex;align-items:center;justify-content:center;';
            closeRaw.addEventListener('click', function() {{ ov.remove(); }});
            btnsWrap.appendChild(copyBtn);
            btnsWrap.appendChild(closeRaw);
            hdr.appendChild(info);
            hdr.appendChild(btnsWrap);
            var pre = doc.createElement('pre');
            pre.style.cssText = 'flex:1;overflow-y:auto;overflow-x:auto;padding:20px 24px;font-size:12.5px;'
                + 'line-height:1.7;color:#e6edf3;font-family:monospace;background:#0d1117;margin:0;'
                + 'white-space:pre-wrap;word-break:break-word;';
            pre.textContent = raw;
            box.appendChild(hdr);
            box.appendChild(pre);
            ov.appendChild(box);
            doc.body.appendChild(ov);
            var escFn = function(e) {{ if (e.key === 'Escape') {{ ov.remove(); doc.removeEventListener('keydown', escFn); }} }};
            doc.addEventListener('keydown', escFn);
        }}

        document.addEventListener('click', function(e) {{
            var fs = e.target.closest('.btn-fullscreen');
            if (fs) {{ e.stopPropagation(); abrirModal(parseInt(fs.dataset.idx)); return; }}
            var rv = e.target.closest('.btn-raw');
            if (rv) {{ e.stopPropagation(); abrirRaw(parseInt(rv.dataset.idx)); return; }}
            var dl = e.target.closest('.btn-download');
            if (dl) {{
                e.stopPropagation();
                var raw = RELS_RAW[String(dl.dataset.idx)] || '';
                var a = document.createElement('a');
                a.href = URL.createObjectURL(new Blob([raw], {{type:'text/plain'}}));
                a.download = dl.dataset.filename + '.txt';
                a.click();
                return;
            }}
            var hdr = e.target.closest('.card-hdr');
            if (hdr && !e.target.closest('button')) {{
                toggleSite(parseInt(hdr.dataset.idx));
                return;
            }}
            var ch = e.target.closest('.btn-chevron');
            if (ch) {{ toggleSite(parseInt(ch.dataset.idx)); return; }}
        }});

        (function() {{
            var cards = document.querySelectorAll('[id^="sb_"]');
            if (cards.length === 1) {{
                var m = cards[0].id.match(/sb_(\d+)/);
                if (m) setTimeout(function() {{ toggleSite(parseInt(m[1])); }}, 150);
            }}
        }})();

        if (window.ResizeObserver) new ResizeObserver(syncH).observe(document.body);
        setTimeout(syncH, 200);
        setTimeout(syncH, 600);
        </script>
        """, height=100, scrolling=False)

        else:
            empty_msg = {
                "individual": "Vá em <b>Sites configurados</b> e clique em <b>Analisar este site com IA</b>.",
                "geral":      "Clique em <b>Gerar Relatório Geral</b> no topo da página.",
            }.get(subtab_sites, "Nenhuma análise ainda.")

            st.markdown(f"""
            <div style="border:1px dashed #e5e7eb;border-radius:12px;padding:48px 24px;
                        text-align:center;background:#fff;margin-top:8px;
                        display:flex;flex-direction:column;align-items:center;gap:10px;">
                <div style="font-size:32px;opacity:0.4;">{icon_sites_ativo}</div>
                <div style="font-size:14px;color:#9ca3af;">Nenhuma análise de {label_sites_ativo.lower()} ainda.</div>
                <div style="font-size:13px;color:#9ca3af;">{empty_msg}</div>
            </div>
            """, unsafe_allow_html=True)

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
            or body.strip()[:120] in desc.strip()
            or desc.strip()[:120] in body.strip()
        ):
            desc = ""

        # Limpa desc se tiver alta sobreposição de palavras com o body
        if desc and body:
            _desc_words = set(desc.strip().lower().split())
            _body_words = set(body.strip().lower().split())
            if _desc_words and _body_words:
                _overlap = len(_desc_words & _body_words) / max(len(_desc_words), 1)
                if _overlap > 0.6:
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
            or item.get("display_format")
            or ""
        ).upper()

        _dco_formats = ("DCO", "DYNAMIC_CREATIVE", "DYNAMIC")
        _is_dco = raw_media_type in _dco_formats or item.get("display_format", "").upper() in _dco_formats

        has_video   = bool(videos) or raw_media_type in ("VIDEO", "REELS")
        has_cards   = len(cards) > 1 and not has_video and not _is_dco
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

    def empresa_tem_ads_id(e: dict) -> bool:
        if e["tipo"] == "minha":
            return bool(emp.get("ads_id", "").strip())
        else:
            cd = concs[e["idx"]]
            return bool(cd.get("ads_id", "").strip())

    todas_empresas = []
    if emp.get("nome"):
        todas_empresas.append({"nome": emp["nome"], "tipo": "minha", "idx": 0})
    for i, c in enumerate(concs):
        if c.get("nome"):
            todas_empresas.append({"nome": c["nome"], "tipo": "concorrente", "idx": i})
    
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
    if "ads_analises_salvas" not in st.session_state:
        st.session_state.ads_analises_salvas = []

    def safe_key(s):
        return re.sub(r"[^a-zA-Z0-9_]", "_", s)

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

    st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:-10px 0 8px 0'/>", unsafe_allow_html=True)

    _ids_coletados = set(st.session_state.ads_cache.keys())
    _empresas_sem_config = [e for e in todas_empresas if not empresa_tem_ads_id(e)]
    _empresas_sem_dados  = [e for e in todas_empresas if empresa_tem_ads_id(e) and e["nome"] not in _ids_coletados]

    if _empresas_sem_config:
        _nomes = ", ".join(e["nome"] for e in _empresas_sem_config)
        st.info(
            f"⚙️ **{_nomes}** {'não está configurada' if len(_empresas_sem_config) == 1 else 'não estão configuradas'}. "
            f"Vá em **Configuração** para adicionar o ID da página."
        )
    if _empresas_sem_dados:
        _nomes = ", ".join(e["nome"] for e in _empresas_sem_dados)
        st.info(
            f"📡 **{_nomes}** {'foi adicionada' if len(_empresas_sem_dados) == 1 else 'foram adicionadas'} "
            f"mas ainda não {'tem' if len(_empresas_sem_dados) == 1 else 'têm'} dados coletados. "
            f"Clique em **Buscar / Atualizar Anúncios** para incluí-las."
        )

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
        <div class="nav-right">
            <div class="count-badge {'has' if len(st.session_state.get('ads_analises_salvas', [])) > 0 else ''}">{len(st.session_state.get('ads_analises_salvas', []))}</div>
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

        # ── Recupera valores via query_params
        for ci in range(len(todas_empresas)):
            qk = f"_cfg_val_{ci}"
            if qk in st.query_params:
                st.session_state[f"cfg_val_temp_{ci}"] = st.query_params[qk]

        # ── CSS ocultar ghost buttons
        all_ghost_css = "".join([f"""
        .st-key-cfg_ghost_edit_{ci},
        .st-key-cfg_ghost_cancel_{ci},
        .st-key-cfg_do_buscar_{ci},
        .st-key-cfg_do_salvar_{ci} {{
            position:fixed!important;top:-9999px!important;left:-9999px!important;
            width:0!important;height:0!important;overflow:hidden!important;
            opacity:0!important;pointer-events:none!important;display:none!important;
        }}
        .stElementContainer:has(.st-key-cfg_ghost_edit_{ci}),
        .stElementContainer:has(.st-key-cfg_ghost_cancel_{ci}),
        .stElementContainer:has(.st-key-cfg_do_buscar_{ci}),
        .stElementContainer:has(.st-key-cfg_do_salvar_{ci}) {{
            display:none!important;height:0!important;min-height:0!important;
            max-height:0!important;padding:0!important;margin:0!important;overflow:hidden!important;
        }}
        """ for ci in range(len(todas_empresas))])

        # CSS ocultar ghost buttons do "Usar página"
        usar_ghost_css_parts = []
        for ci, e in enumerate(todas_empresas):
            for pi in range(8):
                sk_e = safe_key(e["nome"])
                k = f"cfg_usar_pg_{sk_e}_{ci}_{pi}"
                usar_ghost_css_parts.append(f"""
                .st-key-{k} {{
                    position:fixed!important;top:-9999px!important;left:-9999px!important;
                    width:0!important;height:0!important;overflow:hidden!important;
                    opacity:0!important;pointer-events:none!important;display:none!important;
                }}
                .stElementContainer:has(.st-key-{k}) {{
                    display:none!important;height:0!important;min-height:0!important;
                    max-height:0!important;padding:0!important;margin:0!important;overflow:hidden!important;
                }}
                """)

        st.markdown(f"<style>{all_ghost_css}{''.join(usar_ghost_css_parts)}</style>", unsafe_allow_html=True)

        # ── Ghost triggers principais
        ghost_edit      = {}
        ghost_cancel    = {}
        ghost_do_buscar = {}
        ghost_do_salvar = {}

        for ci, e in enumerate(todas_empresas):
            ghost_edit[ci]      = st.button(f"edit_{ci}",      key=f"cfg_ghost_edit_{ci}")
            ghost_cancel[ci]    = st.button(f"cancel_{ci}",    key=f"cfg_ghost_cancel_{ci}")
            ghost_do_buscar[ci] = st.button(f"do_buscar_{ci}", key=f"cfg_do_buscar_{ci}")
            ghost_do_salvar[ci] = st.button(f"do_salvar_{ci}", key=f"cfg_do_salvar_{ci}")

        # ── Ghost triggers "Usar página"
        ghost_usar_pg = {}
        for ci, e in enumerate(todas_empresas):
            ghost_usar_pg[ci] = {}
            for pi in range(8):
                sk_e = safe_key(e["nome"])
                k = f"cfg_usar_pg_{sk_e}_{ci}_{pi}"
                ghost_usar_pg[ci][pi] = st.button(f"usar_pg_{ci}_{pi}", key=k)

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
                for k in list(st.query_params.keys()):
                    if k.startswith("_cfg_val_"):
                        del st.query_params[k]
                st.rerun()

            if ghost_do_buscar[ci]:
                val = st.session_state.get(f"cfg_val_temp_{ci}", "").strip()
                if val:
                    st.session_state.ads_onboarding_empresa = e["nome"]
                    st.session_state.ads_editando_empresa   = e["nome"]
                    paginas = buscar_paginas_facebook(val)
                    st.session_state.ads_onboarding_paginas = paginas
                    qk = f"_cfg_val_{ci}"
                    if qk in st.query_params:
                        del st.query_params[qk]
                    st.rerun()

            if ghost_do_salvar[ci]:
                val = st.session_state.get(f"cfg_val_temp_{ci}", "").strip()
                if val:
                    salvar_ads_id(e, val)
                    st.session_state.ads_editando_empresa   = None
                    st.session_state.ads_onboarding_empresa = None
                    st.session_state.ads_onboarding_paginas = []
                    qk = f"_cfg_val_{ci}"
                    if qk in st.query_params:
                        del st.query_params[qk]
                    st.toast(f"✅ {e['nome']} salvo!", icon="✅")
                    st.rerun()

            # Processar "Usar página" da lista de resultados
            if onboarding_empresa == e["nome"] and onboarding_paginas:
                e_ob = e
                for pi, pg in enumerate(onboarding_paginas[:8]):
                    if ghost_usar_pg[ci].get(pi):
                        salvar_ads_id(
                            e_ob,
                            pg.get("page_id") or pg.get("nome", ""),
                            pg.get("profile_picture", ""),
                        )
                        st.session_state.ads_editando_empresa   = None
                        st.session_state.ads_onboarding_empresa = None
                        st.session_state.ads_onboarding_paginas = []
                        st.toast(f"✅ {pg.get('nome', '')} selecionado!", icon="✅")
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
            is_minha   = e["tipo"] == "minha"
            ads_id     = emp.get("ads_id","") if is_minha else concs[e["idx"]].get("ads_id","")
            page_pic   = emp.get("ads_page_pic","") if is_minha else concs[e["idx"]].get("ads_page_pic","")
            has_id     = bool(ads_id.strip())
            is_editing = (editando_empresa == e["nome"])
            cor        = get_minha_empresa_color() if is_minha else get_concorrente_color(e["idx"])
            av_txt     = gerar_avatar(e["nome"])
            badge_lbl  = "Minha empresa" if is_minha else "Concorrente"
            badge_bg   = "#f0fdf4" if is_minha else "#eff6ff"
            badge_col  = "#15803d" if is_minha else "#1d4ed8"
            badge_brd  = "#bbf7d0" if is_minha else "#bfdbfe"
            id_bg      = "#f0fdf4" if has_id else "#f3f4f6"
            id_brd     = "#bbf7d0" if has_id else "#e5e7eb"
            id_fw      = "600"     if has_id else "400"
            id_color   = "#15803d" if has_id else "#9ca3af"
            id_ff      = "monospace" if has_id else "inherit"
            id_text    = ads_id if has_id else "Não configurado"

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

            # Bloco de resultados encontrados (dentro do card, após os botões)
            resultados_block = ""
            if is_editing and onboarding_empresa == e["nome"] and onboarding_paginas:
                pgs_html = ""
                for pi, pg in enumerate(onboarding_paginas[:8]):
                    initial = (pg.get("nome","P") or "P")[0].upper()
                    pic_pg  = pg.get("profile_picture","")
                    thumb_html = (
                        f'<img src="{pic_pg}" style="width:32px;height:32px;border-radius:50%;'
                        f'object-fit:cover;display:block" onerror="this.style.display=\'none\'" />'
                        if pic_pg and pic_pg.startswith("http")
                        else f'<span style="font-size:13px;font-weight:700;color:#6b7280">{initial}</span>'
                    )
                    sk_e = safe_key(e["nome"])
                    ghost_label = f"usar_pg_{ci}_{pi}"
                    pgs_html += f"""
                    <div style="display:flex;align-items:center;gap:10px;padding:9px 12px;
                                background:#f9fafb;border:1px solid #e5e7eb;border-radius:9px;
                                margin-bottom:6px;">
                        <div style="width:32px;height:32px;border-radius:50%;background:#e5e7eb;
                                    display:flex;align-items:center;justify-content:center;
                                    flex-shrink:0;overflow:hidden;">
                            {thumb_html}
                        </div>
                        <div style="flex:1;min-width:0;">
                            <div style="font-size:13px;font-weight:700;color:#111827;
                                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                {pg.get("nome","—")}
                            </div>
                            <div style="font-size:11px;color:#9ca3af;font-family:monospace;margin-top:1px;">
                                ID: {pg.get("page_id","—")}
                            </div>
                        </div>
                        <span style="font-size:12px;font-weight:600;color:#3a9fd6;flex-shrink:0;margin-right:8px;">
                            {pg.get("total_ads",0)} ads
                        </span>
                        <button onclick="triggerGhost('{ghost_label}')"
                            style="padding:7px 16px;border:none;border-radius:7px;background:#0e2a47;
                                   color:#fff;font-size:12px;font-weight:700;cursor:pointer;
                                   font-family:'DM Sans',sans-serif;flex-shrink:0;transition:background 0.12s;"
                            onmouseover="this.style.background='#1a3a5c'"
                            onmouseout="this.style.background='#0e2a47'">
                            Usar
                        </button>
                    </div>"""

                resultados_block = f"""
                <div style="margin-top:10px;border-top:1px solid #e5e7eb;padding-top:12px;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                             stroke="#3a9fd6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                        </svg>
                        <span style="font-size:11px;font-weight:700;color:#0369a1;
                                     text-transform:uppercase;letter-spacing:0.5px;">
                            {len(onboarding_paginas[:8])} página(s) encontrada(s)
                        </span>
                    </div>
                    {pgs_html}
                </div>"""

            if is_editing:
                cards_html += f"""
                <div class="card" style="{border_style}" id="card_wrap_{ci}">
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
                        <span style="background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;
                                     padding:4px 10px;border-radius:8px;font-size:11px;font-weight:700;
                                     flex-shrink:0;">✏️ Editando</span>
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
                        <div class="edit-section">
                            <div style="font-size:11px;font-weight:700;color:#9ca3af;
                                        text-transform:uppercase;letter-spacing:0.8px;
                                        margin-bottom:8px">ID ou nome da página do Facebook</div>
                            <input
                                id="cfg_input_{ci}"
                                type="text"
                                value="{ads_id}"
                                placeholder="Ex: Educbank  ou  106889667774994"
                                style="width:100%;height:42px;border:1.5px solid #e5e7eb;
                                       border-radius:8px;padding:0 14px;font-size:14px;
                                       font-family:'DM Sans',sans-serif;color:#111827;
                                       background:#fafafa;outline:none;
                                       margin-bottom:12px;display:block;box-sizing:border-box;"
                                onfocus="this.style.borderColor='#3a9fd6';this.style.background='#fff'"
                                onblur="this.style.borderColor='#e5e7eb';this.style.background='#fafafa'"
                            />
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                                <button class="btn-buscar" id="btn_buscar_{ci}" onclick="handleBuscar({ci})">
                                    🔍 Buscar páginas
                                </button>
                                <button class="btn-salvar" id="btn_salvar_{ci}" onclick="handleSalvar({ci})">
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
                            {resultados_block}
                        </div>
                    </div>
                    <div class="card-footer">
                        <button class="cancel-btn" onclick="triggerGhost('cancel_{ci}')">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                                 stroke="currentColor" stroke-width="2.5"
                                 stroke-linecap="round" stroke-linejoin="round">
                                <line x1="18" y1="6" x2="6" y2="18"/>
                                <line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                            Cancelar
                        </button>
                    </div>
                </div>"""
            else:
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
                    </div>
                    <div class="card-footer">
                        <button class="edit-btn" onclick="triggerGhost('edit_{ci}')">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                                 stroke="currentColor" stroke-width="2"
                                 stroke-linecap="round" stroke-linejoin="round">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                            </svg>
                            Editar
                        </button>
                    </div>
                </div>"""

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.outer {{ background:#d2dde9; border:1px solid #cbd5e1; border-radius:16px; padding:16px; }}
.cards-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }}
.card {{ background:#fff; border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }}
.card-header {{ display:flex; align-items:center; gap:12px; padding:16px 16px 12px; }}
.card-body {{ padding:0 16px 14px; display:flex; flex-direction:column; gap:12px; }}
.edit-section {{ padding-top:12px; border-top:1px solid #f3f4f6; }}
.nome {{ font-size:14px; font-weight:700; color:#1a2e4a; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.card-footer {{ border-top:1px solid #f3f4f6; padding:0; }}
.edit-btn {{ width:100%; padding:10px 0; background:#fff; border:none; outline:none;
    font-size:13px; font-weight:600; color:#6b7280; cursor:pointer;
    font-family:'DM Sans',sans-serif; display:flex; align-items:center;
    justify-content:center; gap:7px; transition:background 0.12s; }}
.edit-btn:hover {{ background:#f9fafb; color:#111827; }}
.cancel-btn {{ width:100%; padding:10px 0; background:#fff; border:none; outline:none;
    font-size:13px; font-weight:600; color:#9ca3af; cursor:pointer;
    font-family:'DM Sans',sans-serif; display:flex; align-items:center;
    justify-content:center; gap:6px; transition:all 0.12s; }}
.cancel-btn:hover {{ background:#fef2f2; color:#dc2626; }}
.btn-buscar {{ display:flex; align-items:center; justify-content:center; gap:7px;
    padding:10px 0; border:1.5px solid #3a9fd6; border-radius:8px;
    background:#eff6ff; font-size:13px; font-weight:700; color:#1d4ed8;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:all 0.15s; }}
.btn-buscar:hover:not(:disabled) {{ background:#dbeafe; }}
.btn-buscar:disabled {{ opacity:0.65; cursor:not-allowed; }}
.btn-salvar {{ display:flex; align-items:center; justify-content:center; gap:7px;
    padding:10px 0; border:none; border-radius:8px;
    background:#0e2a47; font-size:13px; font-weight:700; color:#fff;
    cursor:pointer; font-family:'DM Sans',sans-serif; transition:background 0.15s; }}
.btn-salvar:hover:not(:disabled) {{ background:#1a3a5c; }}
.btn-salvar:disabled {{ opacity:0.65; cursor:not-allowed; }}
</style>
<div class="outer">
    <div class="cards-grid">{cards_html}</div>
</div>
<script>
var SPINNER = '<svg style="animation:spin 0.8s linear infinite;display:inline-block;vertical-align:middle;" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>';

function triggerGhost(label) {{
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
        if (txt === String(label)) {{ b.click(); return; }}
    }}
}}

function saveValToURL(ci, val) {{
    var url = new URL(window.parent.location.href);
    url.searchParams.set('_cfg_val_' + ci, val);
    window.parent.history.replaceState({{}}, '', url);
}}

function handleBuscar(ci) {{
    var inp = document.getElementById('cfg_input_' + ci);
    var val = (inp || {{}}).value || '';
    if (!val.trim()) {{ alert('Digite um nome ou ID antes de buscar.'); return; }}

    var btn = document.getElementById('btn_buscar_' + ci);
    var btnS = document.getElementById('btn_salvar_' + ci);
    if (btn) {{
        btn.disabled = true;
        btn.innerHTML = SPINNER + ' &nbsp;Buscando...';
        btn.style.background = '#f0f9ff';
        btn.style.color = '#0369a1';
        btn.style.borderColor = '#7dd3fc';
    }}
    if (btnS) {{ btnS.disabled = true; }}

    saveValToURL(ci, val);
    setTimeout(function() {{ triggerGhost('do_buscar_' + ci); }}, 300);
}}

function handleSalvar(ci) {{
    var inp = document.getElementById('cfg_input_' + ci);
    var val = (inp || {{}}).value || '';
    if (!val.trim()) {{ alert('Digite um ID ou nome antes de salvar.'); return; }}

    var btn = document.getElementById('btn_salvar_' + ci);
    if (btn) {{
        btn.disabled = true;
        btn.innerHTML = SPINNER + ' &nbsp;Salvando...';
    }}

    saveValToURL(ci, val);
    setTimeout(function() {{ triggerGhost('do_salvar_' + ci); }}, 300);
}}

function syncHeight() {{
    var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, document.body.offsetHeight);
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{
            if (iframes[i].contentWindow === window) {{
                iframes[i].style.height = (h + 32) + 'px';
                iframes[i].style.marginTop = '-8px';
                iframes[i].style.overflow = 'visible';
                break;
            }}
        }} catch(ex) {{}}
    }}
}}

if (window.ResizeObserver) {{
    new ResizeObserver(function() {{ syncHeight(); }}).observe(document.body);
    new ResizeObserver(function() {{ syncHeight(); }}).observe(document.documentElement);
}}
document.addEventListener('DOMContentLoaded', syncHeight);
window.addEventListener('load', syncHeight);
[100, 300, 600, 1000, 1500].forEach(function(t) {{ setTimeout(syncHeight, t); }});
</script>
""", height=700, scrolling=False)

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
    background:#d2dde9;
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
            chave_ia_criativos = f"ia_ads_criativos_{sk}"
            chave_ia_copys     = f"ia_ads_copys_{sk}"
            chave_ia_geral     = f"ia_ads_geral_{sk}"

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

            # Ghost buttons para análise IA — padrão Redes
            ia_analise_ghost_css = []
            for _gk in [f"btn_ia_criativos_{sk}", f"btn_ia_copys_{sk}", f"btn_ia_geral_{sk}"]:
                ia_analise_ghost_css.append(f"""
                .st-key-{_gk} {{
                    position:fixed !important; top:-9999px !important; left:-9999px !important;
                    width:1px !important; height:1px !important;
                    opacity:0 !important; pointer-events:none !important;
                }}
                .stElementContainer:has(.st-key-{_gk}) {{
                    position:fixed !important; top:-9999px !important; left:-9999px !important;
                    width:1px !important; height:1px !important;
                    overflow:hidden !important; margin:0 !important; padding:0 !important;
                }}
                """)
            st.markdown(f"<style>{''.join(ia_analise_ghost_css)}</style>", unsafe_allow_html=True)

            if st.button(f"ia_criativos_{sk}", key=f"btn_ia_criativos_{sk}"):
                if gemini_model is None:
                    st.session_state[chave_ia_criativos] = "Configure GEMINI_API_KEY nos secrets."
                else:
                    resumo_criativos = "\n".join([
                        f"- [{a['formato']}] Plataformas: {', '.join(a.get('plataformas',[]))} | Título: {_truncar(a.get('title',''),60) or '—'}"
                        for a in ads_list[:15]
                    ])
                    n_vid = sum(1 for a in ads_list if "Vídeo" in a["formato"])
                    n_img = sum(1 for a in ads_list if "Imagem" in a["formato"])
                    n_car = sum(1 for a in ads_list if "Carrossel" in a["formato"])
                    _ph_ads = st.empty()
                    _render_modal_redes_ia("gerando", f"Criativos — {nome}", 40, _ph_ads)
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
                        import datetime as _dt_ads
                        st.session_state.ads_analises_salvas = [
                            a for a in st.session_state.ads_analises_salvas
                            if not (a.get("tipo") == "criativos_ads" and a.get("empresa") == nome)
                        ]
                        st.session_state.ads_analises_salvas.append({
                            "titulo": f"Criativos — {nome} — {_dt_ads.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            "data": _dt_ads.datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "relatorio": resp.text,
                            "tipo": "criativos_ads",
                            "empresa": nome,
                        })
                        _render_modal_redes_ia("concluido", f"Criativos — {nome}", 100, _ph_ads)
                        salvar_dados_usuario(st.session_state.user.id)
                        st.session_state.ads_main_tab = "analise"
                        import time as _t_ads; _t_ads.sleep(1.2)
                        _ph_ads.empty()
                        st.rerun()
                    except Exception as ex:
                        _ph_ads.empty()
                        st.session_state[chave_ia_criativos] = f"Erro: {ex}"
                        st.rerun()

            if st.button(f"ia_copys_{sk}", key=f"btn_ia_copys_{sk}"):
                if gemini_model is None:
                    st.session_state[chave_ia_copys] = "Configure GEMINI_API_KEY nos secrets."
                else:
                    todas_copies = "\n".join([
                        f"- Título: {_truncar(a.get('title',''),80) or '—'} | Body: {_truncar(a.get('body',''),120) or '—'} | CTA: {a.get('cta','') or '—'}"
                        for a in ads_list[:20]
                    ])
                    _ph_ads = st.empty()
                    _render_modal_redes_ia("gerando", f"Copys — {nome}", 40, _ph_ads)
                    try:
                        resp = gemini_model.generate_content(f"""Você é especialista em copywriting e marketing de resposta direta.
Analise as COPIES (textos) dos anúncios de "{nome}" em português.

Empresa: {nome} | {len(ads_list)} anúncios analisados

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
                        import datetime as _dt_ads
                        st.session_state.ads_analises_salvas = [
                            a for a in st.session_state.ads_analises_salvas
                            if not (a.get("tipo") == "copys_ads" and a.get("empresa") == nome)
                        ]
                        st.session_state.ads_analises_salvas.append({
                            "titulo": f"Copys — {nome} — {_dt_ads.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            "data": _dt_ads.datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "relatorio": resp.text,
                            "tipo": "copys_ads",
                            "empresa": nome,
                        })
                        _render_modal_redes_ia("concluido", f"Copys — {nome}", 100, _ph_ads)
                        salvar_dados_usuario(st.session_state.user.id)
                        st.session_state.ads_main_tab = "analise"
                        import time as _t_ads; _t_ads.sleep(1.2)
                        _ph_ads.empty()
                        st.rerun()
                    except Exception as ex:
                        _ph_ads.empty()
                        st.session_state[chave_ia_copys] = f"Erro: {ex}"
                        st.rerun()

            if st.button(f"ia_geral_{sk}", key=f"btn_ia_geral_{sk}"):
                if gemini_model is None:
                    st.session_state[chave_ia_geral] = "Configure GEMINI_API_KEY nos secrets."
                else:
                    resumo = "\n".join([
                        f"- [{a['formato']}] Título: {_truncar(a.get('title',''),60) or '—'} | Copy: {_truncar(a.get('body',''),100) or '—'}"
                        for a in ads_list[:15]
                    ])
                    n_vid = sum(1 for a in ads_list if "Vídeo" in a["formato"])
                    n_img = sum(1 for a in ads_list if "Imagem" in a["formato"])
                    n_car = sum(1 for a in ads_list if "Carrossel" in a["formato"])
                    n_dyn = sum(1 for a in ads_list if a.get("is_dynamic"))
                    _ph_ads = st.empty()
                    _render_modal_redes_ia("gerando", f"Estratégia — {nome}", 40, _ph_ads)
                    try:
                        resp = gemini_model.generate_content(f"""Você é especialista em mídia paga e marketing digital.
Analise os anúncios de "{nome}" e gere um relatório estratégico completo em português.

Empresa: {nome} | Total: {len(ads_list)} | {n_img} imagens | {n_vid} vídeos | {n_car} carrosseis | {n_dyn} dinâmicos

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
                        import datetime as _dt_ads
                        st.session_state.ads_analises_salvas = [
                            a for a in st.session_state.ads_analises_salvas
                            if not (a.get("tipo") == "estrategia" and a.get("empresa") == nome)
                        ]
                        st.session_state.ads_analises_salvas.append({
                            "titulo": f"Estratégia — {nome} — {_dt_ads.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                            "data": _dt_ads.datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "relatorio": resp.text,
                            "tipo": "estrategia",
                            "empresa": nome,
                        })
                        _render_modal_redes_ia("concluido", f"Estratégia — {nome}", 100, _ph_ads)
                        salvar_dados_usuario(st.session_state.user.id)
                        st.session_state.ads_main_tab = "analise"
                        import time as _t_ads; _t_ads.sleep(1.2)
                        _ph_ads.empty()
                        st.rerun()
                    except Exception as ex:
                        _ph_ads.empty()
                        st.session_state[chave_ia_geral] = f"Erro: {ex}"
                        st.rerun()

            # Ghost buttons análise individual por anúncio
            ia_ind_ghost_css = []
            for j in range(len(ads_list) if 'ads_list' in dir() else 0):
                _gk_ind = f"btn_ia_ind_{sk}_{j}"
                ia_ind_ghost_css.append(f"""
                .st-key-{_gk_ind} {{
                    position:fixed !important; top:-9999px !important; left:-9999px !important;
                    width:1px !important; height:1px !important;
                    opacity:0 !important; pointer-events:none !important;
                }}
                .stElementContainer:has(.st-key-{_gk_ind}) {{
                    position:fixed !important; top:-9999px !important; left:-9999px !important;
                    width:1px !important; height:1px !important;
                    overflow:hidden !important; margin:0 !important; padding:0 !important;
                }}
                """)
            if ia_ind_ghost_css:
                st.markdown(f"<style>{''.join(ia_ind_ghost_css)}</style>", unsafe_allow_html=True)

            page_pic_empresa = ads_list[0].get("page_profile_picture", "") or "" if ads_list else ""

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

                        # ── Calcular insights rápidos dos anúncios ──────────────
            _palavras_beneficio = [
                "resultado", "transforma", "melhora", "aumenta", "economiza",
                "conquista", "lucro", "ganho", "crescimento", "solução", "resolver",
                "benefício", "vantagem", "desconto", "grátis", "gratuito", "oferta",
                "promoção", "exclusivo", "garanta", "aproveite",
            ]
            _palavras_prova = [
                "cliente", "avaliação", "depoimento", "aprovado", "testado",
                "recomend", "anos de", "cases", "resultado real", "história",
                "prova", "satisf", "mais de", "mil cliente", "atendemos",
                "confiança", "parceiro",
            ]
            _palavras_urgencia = [
                "últimas", "último", "vagas", "hoje", "agora", "limitado",
                "por tempo", "não perca", "corra", "só até", "encerra",
                "prazo", "urgente", "restam",
            ]
            _palavras_cta = [
                "clique", "acesse", "saiba mais", "fale conosco", "solicite",
                "cadastre", "entre em contato", "whatsapp", "ligue", "agende",
                "compre", "adquira", "inscreva",
            ]

            def _conta_tipo(lista, palavras):
                count = 0
                for _a in lista:
                    _txt = ((_a.get("body") or "") + " " + (_a.get("title") or "")).lower()
                    if any(p in _txt for p in palavras):
                        count += 1
                return count

            _n_beneficio = _conta_tipo(ads_list, _palavras_beneficio)
            _n_prova     = _conta_tipo(ads_list, _palavras_prova)
            _n_urgencia  = _conta_tipo(ads_list, _palavras_urgencia)
            _n_cta       = _conta_tipo(ads_list, _palavras_cta)
            _n_video_ins = sum(1 for _a in ads_list if "Vídeo" in _a.get("formato", ""))
            _n_carrossel_ins = sum(1 for _a in ads_list if "Carrossel" in _a.get("formato", ""))

            # Monta chips de insights
            _insight_chips = []
            if _n_beneficio > 0:
                _insight_chips.append(("🎯", f"{_n_beneficio} com benefício", "#15803d", "#f0fdf4", "#bbf7d0"))
            if _n_prova > 0:
                _insight_chips.append(("⭐", f"{_n_prova} com prova social", "#1d4ed8", "#eff6ff", "#bfdbfe"))
            if _n_urgencia > 0:
                _insight_chips.append(("⚡", f"{_n_urgencia} com urgência", "#92400e", "#fffbeb", "#fde68a"))
            if _n_cta > 0:
                _insight_chips.append(("📣", f"{_n_cta} com CTA direto", "#6d28d9", "#f5f3ff", "#ddd6fe"))
            if _n_video_ins > 0:
                _insight_chips.append(("🎬", f"{_n_video_ins} em vídeo", "#0e7490", "#ecfeff", "#a5f3fc"))
            if _n_carrossel_ins > 0:
                _insight_chips.append(("🖼️", f"{_n_carrossel_ins} carrossel", "#9333ea", "#faf5ff", "#e9d5ff"))

            _chips_html = "".join([
                f'<div style="display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600;'
                f'color:{cor};background:{bg};border:1px solid {brd};padding:5px 12px;border-radius:20px;white-space:nowrap;">'
                f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="{cor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
                f' {label}</div>'
                for icon, label, cor, bg, brd in _insight_chips
            ]) if _insight_chips else '<span style="font-size:13px;color:#9ca3af;">Gere análises para ver insights detalhados.</span>'

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
                            <div style='font-size:22px;font-weight:800;color:#111827;line-height:1'>{len(ads_list)}</div>
                            <div style='font-size:12px;color:#6b7280;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;margin-top:3px'>anúncios</div>
                        </div>
                        <div style='width:1px;height:40px;background:#e5e7eb;margin:0 20px'></div>
                        <div style='display:flex;align-items:center;gap:10px;flex-shrink:0'>
                            <a href='javascript:void(0)'
                               onclick="(function(){{var btns=window.parent.document.querySelectorAll('button');for(var b of btns){{var t=(b.textContent||b.innerText||'').split(/\s+/).join(' ').trim();if(t==='ia_copys_{sk}'){{b.click();return;}}}}}})()"
                               style='display:inline-flex;flex-direction:column;align-items:flex-start;gap:2px;background:#fff;color:#111827;border:1.5px solid #e5e7eb;padding:10px 18px;border-radius:10px;text-decoration:none;white-space:nowrap;transition:all 0.15s;font-family:DM Sans,sans-serif;min-width:180px;'
                               onmouseover="this.style.borderColor='#3a9fd6';this.style.background='#f0f9ff'"
                               onmouseout="this.style.borderColor='#e5e7eb';this.style.background='#fff'">
                                <span style='display:flex;align-items:center;gap:7px;'>
                                    <span style='font-size:22px;line-height:1;flex-shrink:0;margin-top:1px;background-color:#f3f4f6;padding:6px 3px;border-radius:5px;'>📢</span>
                                    <span style='display:flex;flex-direction:column;gap:0px;'>
                                        <span style='font-size:13px;font-weight:700;color:#111827;line-height:1.3;'>Analisar anúncios</span>
                                        <span style='font-size:11px;font-weight:400;color:#747a87;'>Copies, CTAs e padrões de texto</span>
                                    </span>
                                </span>
                            </a>
                            <a href='javascript:void(0)'
                               onclick="(function(){{var btns=window.parent.document.querySelectorAll('button');for(var b of btns){{var t=(b.textContent||b.innerText||'').split(/\s+/).join(' ').trim();if(t==='ia_geral_{sk}'){{b.click();return;}}}}}})()"
                               style='display:inline-flex;flex-direction:column;align-items:flex-start;gap:2px;background:#fff;color:#111827;border:1.5px solid #e5e7eb;padding:10px 18px;border-radius:10px;text-decoration:none;white-space:nowrap;transition:all 0.15s;font-family:DM Sans,sans-serif;min-width:180px;'
                               onmouseover="this.style.borderColor='#3a9fd6';this.style.background='#f0f9ff'"
                               onmouseout="this.style.borderColor='#e5e7eb';this.style.background='#fff'">
                                <span style='display:flex;align-items:center;gap:7px;'>
                                    <span style='font-size:22px;line-height:1;flex-shrink:0;margin-top:1px;background-color:#f3f4f6;padding:6px 3px;border-radius:5px;'>📊</span>
                                    <span style='display:flex;flex-direction:column;gap:0px;'>
                                        <span style='font-size:13px;font-weight:700;color:#111827;line-height:1.3;'>Analisar estratégia</span>
                                        <span style='font-size:11px;font-weight:400;color:#747a87;'>Formatos, mix de mídia e insights</span>
                                    </span>
                                </span>
                            </a>
                        </div>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)

            for j, ad_ind in enumerate(ads_list):
                if st.button(f"ia_ind_{sk}_{j}", key=f"btn_ia_ind_{sk}_{j}"):
                    chave_ind = f"ia_ad_result_{sk}_{j}"
                    if gemini_model is None:
                        st.session_state[chave_ind] = "Configure GEMINI_API_KEY nos secrets."
                    else:
                        _ph_ind = st.empty()
                        _render_modal_redes_ia("gerando", f"Anúncio {j+1} — {nome}", 40, _ph_ind)
                        try:
                            import datetime as _dt_ads
                            resp_ind = gemini_model.generate_content(f"""Você é especialista em mídia paga e copywriting.
Analise este anúncio de "{nome}" e dê feedback estratégico em português.

Formato: {ad_ind.get('formato','')}
Plataformas: {', '.join(ad_ind.get('plataformas') or [])}
Data início: {ad_ind.get('data_inicio','')}
Impressões: {ad_ind.get('impressoes','')}
Body: {ad_ind.get('body','') or '—'}
Título: {ad_ind.get('title','') or '—'}
CTA: {ad_ind.get('cta','') or '—'}

### 🎯 Objetivo do Anúncio
### ✍️ Análise do Copy
### 🎨 Análise do Criativo
### 📊 Desempenho Estimado
### 💡 Sugestões de Melhoria (2 ações concretas)""")
                            st.session_state[chave_ind] = resp_ind.text
                            st.session_state.ads_analises_salvas = [
                                a for a in st.session_state.ads_analises_salvas
                                if not (a.get("tipo") == "anuncio_ind" and a.get("empresa") == nome and a.get("ad_idx") == j)
                            ]
                            st.session_state.ads_analises_salvas.append({
                                "titulo": f"Anúncio {j+1} — {nome} — {_dt_ads.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                                "data": _dt_ads.datetime.now().strftime("%d/%m/%Y %H:%M"),
                                "relatorio": resp_ind.text,
                                "tipo": "anuncio_ind",
                                "empresa": nome,
                                "ad_idx": j,
                            })
                            _render_modal_redes_ia("concluido", f"Anúncio {j+1} — {nome}", 100, _ph_ind)
                            salvar_dados_usuario(st.session_state.user.id)
                            st.session_state.ads_main_tab = "analise"
                            st.session_state.ads_analise_subtab = "anuncio_ind"
                            import time as _t_ads; _t_ads.sleep(1.2)
                            _ph_ind.empty()
                            st.rerun()
                        except Exception as ex_ind:
                            _ph_ind.empty()
                            st.session_state[chave_ind] = f"Erro: {ex_ind}"
                            st.rerun()

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
                .st-key-{filtros_key} {{ margin-top: -16px !important; }}
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
.stat-card{{flex:1;min-width:90px;background:#ffffff;border-radius:12px;padding:14px 10px;text-align:center;}}
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
                    box-shadow:0 2px 12px rgba(0,0,0,0.5);border: 2px solid #ffffff !important;">
            <svg width="22" height="22" viewBox="0 0 54 54" fill="none">
                <polygon points="18,12 44,27 18,42" fill="white"/>
            </svg>
        </div>
    </div>
    <div style="position:absolute;bottom:7px;right:7px;background:#ffffff;
                color:#000000;font-size:10px;font-weight:700;padding:2px 7px;
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
                + 'display:flex;align-items:center;justify-content:center;border: 2px solid #ffffff !important;">'
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
    <div style="position:absolute;top:8px;right:8px;background:#ffffff;border-radius:6px;padding:3px 7px;font-size:11px;color:#000000;font-weight:600;pointer-events:none;">🔍 VER CRIATIVOS</div>
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
        {'<div class="no-copy">Sem copy disponível.</div>' if not body_safe and not title_safe else ''}
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

                subtab_map = {
                    "criativos_ads": "criativos",
                    "copys_ads":     "copys",
                    "estrategia":    "individuais",
                    "anuncio_ind":   "individuais",
                }
                ultimo_tipo = next(
                    (a["tipo"] for a in reversed(st.session_state.ads_analises_salvas)
                     if a.get("empresa") == nome),
                    None,
                )
                if ultimo_tipo:
                    st.session_state[f"ads_subtab_{sk}"] = subtab_map.get(ultimo_tipo, "individuais")

                for j in range(len(ads_f_ia)):
                    chave_ind = f"ia_ad_result_{sk}_{j}"
                    if chave_ind not in st.session_state:
                        st.session_state[chave_ind] = ""

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

        # Exibir análises individuais salvas com abas por tipo
        analises_ads = st.session_state.get("ads_analises_salvas", [])

        if "ads_analise_subtab" not in st.session_state:
            st.session_state.ads_analise_subtab = "criativos_ads"

        subtabs_ads_def = [
            ("anuncio_ind",     "📢", "Anúncios"),
            ("criativos_ads",   "🎨", "Criativos"),
            ("copys_ads",       "✍️", "Copys"),
            ("estrategia",      "📊", "Estratégia"),
            ("comparativo_ads", "🏆", "Comparativo"),
        ]

        # Ghost buttons para subtabs
        ghost_subtabs_css = ", ".join([
            f".st-key-btn_ads_analise_sub_{stk}, .stElementContainer:has(.st-key-btn_ads_analise_sub_{stk})"
            for stk, _, _ in subtabs_ads_def
        ])
        st.markdown(f"""
        <style>
        {ghost_subtabs_css} {{
            position:fixed !important; top:-9999px !important; left:-9999px !important;
            width:0 !important; height:0 !important; overflow:hidden !important;
            opacity:0 !important; pointer-events:none !important; display:none !important;
            min-height:0 !important; max-height:0 !important; padding:0 !important; margin:0 !important;
        }}
        </style>
        """, unsafe_allow_html=True)

        for stk, _, _ in subtabs_ads_def:
            if st.button(f"ads_analise_sub_{stk}", key=f"btn_ads_analise_sub_{stk}"):
                st.session_state.ads_analise_subtab = stk
                st.rerun()

        subtab_ads_ativa = st.session_state.ads_analise_subtab
        contagens_ads = {
            stk: len([a for a in analises_ads if a.get("tipo") == stk])
            for stk, _, _ in subtabs_ads_def
        }

        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.tabs-wrap {{ display:grid; grid-template-columns:repeat(5,1fr); gap:8px; width:100%; }}
.tab-pill {{
    display:flex; align-items:center; justify-content:center; gap:6px;
    padding:10px 8px; border-radius:10px; cursor:pointer;
    border:1.5px solid #e5e7eb; background:#fff; text-decoration: none;
    font-size:13px; font-weight:600; color:#6b7280;
    transition:all 0.15s; white-space:nowrap;
    font-family:'DM Sans',sans-serif; line-height:1; width:100%;
}}
.tab-pill:hover {{ border-color:#3a9fd6; color:#1d4ed8; background:#eff6ff; }}
.tab-pill.active {{ background:#0e2a47; border-color:#0e2a47; color:#fff; }}
.tab-badge {{
    font-size:11px; font-weight:800; padding:2px 8px; border-radius:20px;
    background:#e5e7eb; color:#6b7280; line-height:1.4; flex-shrink:0;
}}
.tab-pill.active .tab-badge {{ background:rgba(255,255,255,0.15); color:#fff; }}
.tab-badge.has {{ background:#3a9fd6; color:#fff; }}
</style>
<div class="tabs-wrap">
{''.join([
    f'''<a class="tab-pill {'active' if subtab_ads_ativa == stk else ''}"
        href="javascript:void(0)"
        onclick="(function(){{var btns=window.parent.document.querySelectorAll('button');for(var b of btns){{var t=(b.textContent||b.innerText||'').split(/\\s+/).join(' ').trim();if(t==='ads_analise_sub_{stk}'){{b.click();return;}}}}}})()"
    >{icon} {lbl} <span class="tab-badge {'has' if contagens_ads.get(stk,0) > 0 else ''}">{contagens_ads.get(stk,0)}</span></a>'''
    for stk, icon, lbl in subtabs_ads_def
])}
</div>
<script>
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '52px';
            iframes[i].style.marginTop = '-47px';
            break;
        }} }} catch(e) {{}}
    }}
}})();
</script>
""", height=52, scrolling=False)

        lista_ads_ativa = [a for a in analises_ads if a.get("tipo") == subtab_ads_ativa]
        import json as _json_analises
        import re as _re_md
        import html as _html_mod
        def _md_to_html(txt):
            if not txt: return ""
            txt = txt.replace("&", "&amp;")
            txt = _re_md.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', txt)
            txt = _re_md.sub(r'\*(.+?)\*',     r'<em>\1</em>', txt)
            txt = _re_md.sub(r'^### (.+)$', r'<h3>\1</h3>', txt, flags=_re_md.MULTILINE)
            txt = _re_md.sub(r'^## (.+)$',  r'<h2>\1</h2>', txt, flags=_re_md.MULTILINE)
            txt = _re_md.sub(r'^# (.+)$',   r'<h1>\1</h1>', txt, flags=_re_md.MULTILINE)
            txt = _re_md.sub(r'^---+$', '<hr>', txt, flags=_re_md.MULTILINE)
            txt = _re_md.sub(r'^\s*[\*\-] (.+)$', r'<li>\1</li>', txt, flags=_re_md.MULTILINE)
            txt = _re_md.sub(r'(<li>.*?</li>\n?)+', lambda m: '<ul>' + m.group(0) + '</ul>', txt, flags=_re_md.DOTALL)
            blocos = _re_md.split(r'\n{2,}', txt)
            partes = []
            for bloco in blocos:
                bloco = bloco.strip()
                if not bloco:
                    continue
                if _re_md.match(r'^<(h[123]|ul|hr|li)', bloco):
                    partes.append(bloco)
                else:
                    bloco = bloco.replace('\n', ' ')
                    partes.append(f'<p>{bloco}</p>')
            return '\n'.join(partes)

        relatorios_ads_ind = {str(i): _md_to_html(a.get("relatorio","")) for i, a in enumerate(analises_ads)}
        relatorios_ads_json = _json_analises.dumps(relatorios_ads_ind, ensure_ascii=False)

        icons_ads = {"anuncio_ind":"📢","criativos_ads":"🎨","copys_ads":"✍️","estrategia":"📊","comparativo_ads":"🏆"}

        if lista_ads_ativa:
            cards_ads_html = ""
            for a in reversed(lista_ads_ativa):
                idx_real = analises_ads.index(a)
                icon_a   = icons_ads.get(a.get("tipo",""), "📋")
                titulo_a = a.get("titulo","—").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                nome_arq = titulo_a.replace(" ","_").replace("/","_").replace("(","").replace(")","").replace(".","")
                cards_ads_html += f"""
<div style="border-bottom:1px solid #f3f4f6;background:#fff;">
    <div style="display:flex;align-items:center;gap:12px;padding:14px 16px;cursor:pointer;transition:background 0.12s;background-color:#0e2a47;"
         onclick="(function(){{var b=document.getElementById('ab_{idx_real}');var c=document.getElementById('ac_{idx_real}');var r=document.getElementById('ar_{idx_real}');var open=b.style.display!=='none';b.style.display=open?'none':'block';c.style.transform=open?'':'rotate(180deg)';if(!open&&r&&!r.dataset.loaded){{r.innerHTML=RELS['{idx_real}']||'';r.dataset.loaded='1';}}setTimeout(syncH,100);}})()">
        <span style="font-size:18px;flex-shrink:0">{icon_a}</span>
        <div style="flex:1;min-width:0;font-size:14px;font-weight:600;color:#ffffff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{titulo_a}</div>
        <span id="ac_{idx_real}" style="color:#d1d5db;transition:transform 0.2s;display:flex;align-items:center;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </span>
    </div>
    <div id="ab_{idx_real}" style="display:none;border-top:1px solid #f3f4f6;">
        <div id="ar_{idx_real}" style="font-size:14px;color:#374151;line-height:1.8;padding:14px 16px;word-break:break-word;"></div>
        <div style="display:flex;gap:8px;padding:10px 16px;background:#f9fafb;border-top:1px solid #f3f4f6;">
            <button onclick="(function(){{var c=RELS['{idx_real}']||'';var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([c],{{type:'text/plain'}}));a.download='{nome_arq}.txt';a.click();}})()"
                style="flex:1;padding:9px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;font-size:13px;font-weight:600;color:#374151;cursor:pointer;font-family:'DM Sans',sans-serif;">
                ⬇️ Baixar .txt
            </button>
        </div>
    </div>
</div>"""

            components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{background:transparent;font-family:'DM Sans',sans-serif;overflow:visible;}}
body{{padding-bottom:8px;}}
[id^="ar_"] h1,[id^="ar_"] h2,[id^="ar_"] h3{{font-size:15px;font-weight:800;color:#0f1f35;margin:14px 0 8px;padding:0;border-bottom:2px solid #e5e7eb;text-transform:uppercase;padding-bottom:5px;}}
[id^="ar_"] p{{margin:0 0 8px;padding:0;line-height:1.7;}}
[id^="ar_"] ul{{margin:5px 0 15px 28px;padding:0;}}
[id^="ar_"] li{{margin:0 0 3px;padding:0;line-height:1.6;}}
[id^="ar_"] li::marker {{color:#00c162;}}
[id^="ar_"] hr{{display:none;}}
</style>
<div style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;margin-top:8px;">
    {cards_ads_html}
</div>
<script>
var RELS = {relatorios_ads_json};
function syncH(){{
    var h=Math.max(document.body.scrollHeight,document.documentElement.scrollHeight);
    var frames=window.parent.document.querySelectorAll('iframe');
    for(var i=0;i<frames.length;i++){{
        try{{if(frames[i].contentWindow===window){{
            frames[i].style.height=(h+8)+'px';
            frames[i].style.marginTop='-57px';
            break;
        }}}}catch(e){{}}
    }}
}}
if(window.ResizeObserver)new ResizeObserver(syncH).observe(document.body);
setTimeout(syncH,200);setTimeout(syncH,600);
(function(){{
    var cards=document.querySelectorAll('[id^="ab_"]');
    if(cards.length===1){{
        var m=cards[0].id.match(/ab_(\d+)/);
        if(m){{setTimeout(function(){{
            var b=document.getElementById('ab_'+m[1]);
            var c=document.getElementById('ac_'+m[1]);
            var r=document.getElementById('ar_'+m[1]);
            if(b)b.style.display='block';
            if(c)c.style.transform='rotate(180deg)';
            if(r&&!r.dataset.loaded){{r.innerHTML=RELS[m[1]]||'';r.dataset.loaded='1';}}
            syncH();
        }},150);}}
    }}
}})();
</script>
""", height=100, scrolling=False)
        else:
            icon_empty = icons_ads.get(subtab_ads_ativa, "📋")
            if subtab_ads_ativa == "comparativo_ads":
                chave_comp = "ia_ads_comparativo"
                if chave_comp not in st.session_state:
                    st.session_state[chave_comp] = ""
                comp_html = st.session_state.get(chave_comp, "").replace("\n","<br>")
                components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>*{{margin:0;padding:0;box-sizing:border-box;}}html,body{{background:transparent;font-family:'DM Sans',sans-serif;overflow:visible;}}</style>
<div style="background:#fff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;margin-top:8px;">
    <div style="padding:18px 22px;border-bottom:1px solid #e5e7eb;">
        <div style="font-size:16px;font-weight:800;color:#1a2e4a;">✨ Análise Competitiva de Anúncios</div>
        <div style="font-size:13px;color:#9ca3af;margin-top:2px;">Comparativo inteligente de todas as empresas configuradas</div>
    </div>
    <div style="padding:22px;font-size:14px;color:#374151;line-height:1.8;min-height:80px;">
        {'<div>' + comp_html + '</div>' if comp_html else '<div style="text-align:center;color:#9ca3af;padding:40px 0;">Clique em <b>Gerar Análise Comparativa</b> abaixo para comparar os anúncios de todas as empresas com IA.</div>'}
    </div>
    <div style="padding:16px 22px;border-top:1px solid #f3f4f6;background:#f9fafb;">
        <button onclick="(function(){{var btns=window.parent.document.querySelectorAll('button');for(var b of btns){{var t=(b.textContent||b.innerText||'').split(/\\s+/).join(' ').trim();if(t==='ia_comparativo'){{b.click();return;}}}}}})()"
            style="display:inline-flex;align-items:center;gap:8px;padding:12px 28px;border:none;border-radius:10px;background:#0e2a47;font-size:15px;font-weight:700;color:#fff;cursor:pointer;font-family:'DM Sans',sans-serif;">
            {'🔄 Regerar Análise' if comp_html else '⚡ Gerar Análise Comparativa'}
        </button>
    </div>
</div>
<script>
function syncH(){{var h=Math.max(document.body.scrollHeight,document.documentElement.scrollHeight);var frames=window.parent.document.querySelectorAll('iframe');for(var i=0;i<frames.length;i++){{try{{if(frames[i].contentWindow===window){{frames[i].style.height=(h+8)+'px';break;}}}}catch(e){{}}}}}}
if(window.ResizeObserver)new ResizeObserver(syncH).observe(document.body);
setTimeout(syncH,200);setTimeout(syncH,600);
</script>
""", height=100, scrolling=False)
            else:
                st.markdown(f"""
                <div style="border:1px dashed #e5e7eb;border-radius:12px;padding:48px 24px;
                            text-align:center;background:#fff;margin-top:8px;">
                    <div style="font-size:32px;opacity:0.4;margin-bottom:10px">{icon_empty}</div>
                    <div style="font-size:14px;color:#9ca3af;">Nenhuma análise aqui ainda.<br>
                    Vá em <b>Empresas configuradas</b> para gerar.</div>
                </div>
                """, unsafe_allow_html=True)
                
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
            _all_urls = [
                link.get("url", "") for link in _bio_links if link.get("url", "")
            ]
            if not _all_urls and user_data.get("external_url"):
                _all_urls = [user_data["external_url"]]
            _external_url = " | ".join(_all_urls)

            return {
                "handle":       "@" + handle_limpo,
                "nome_exibido": user_data.get("full_name") or user_data.get("username", handle_limpo),
                "seguidores":   seg,
                "seguindo":     int(user_data.get("following_count") or 0),
                "total_posts":  total_posts,
                "bio":          (user_data.get("biography") or ""),
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

    def _build_links_html(urls_str: str) -> str:
        urls = [u.strip() for u in urls_str.split("|") if u.strip()]
        if not urls:
            return ""

        icon_svg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#3a9fd6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>'

        def _link_row(url):
            display = url.replace("https://", "").replace("http://", "").rstrip("/")
            return (
                f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
                f'{icon_svg}'
                f'<a href="{url}" target="_blank" style="font-size:13px;font-weight:600;'
                f'color:#3a9fd6;text-decoration:none;white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis;max-width:340px;">{display}</a>'
                f'</div>'
            )

        import hashlib
        uid = hashlib.md5(urls[0].encode()).hexdigest()[:8]

        extras = urls[1:]

        if not extras:
            return _link_row(urls[0])

        extra_rows = "".join(_link_row(u) for u in extras)
        n_extra = len(extras)
        display_first = urls[0].replace("https://", "").replace("http://", "").rstrip("/")

        return (
            f'<div style="display:flex;flex-direction:column;gap:0;">'

            # Primeira linha: ícone + link + "e mais N"
            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
            f'{icon_svg}'
            f'<a href="{urls[0]}" target="_blank" style="font-size:13px;font-weight:600;'
            f'color:#3a9fd6;text-decoration:none;white-space:nowrap;overflow:hidden;'
            f'text-overflow:ellipsis;max-width:220px;">{display_first}</a>'
            f'<button '
            f'onclick="var el=document.getElementById(\'extra_links_{uid}\'),'
            f'btn=document.getElementById(\'btn_links_{uid}\');'
            f'if(el.style.display===\'none\'){{el.style.display=\'block\';btn.textContent=\'ver menos\';}}' 
            f'else{{el.style.display=\'none\';btn.textContent=\'e mais {n_extra}\';}}" '
            f'id="btn_links_{uid}" '
            f'style="background:none;border:none;padding:0;font-size:13px;font-weight:600;'
            f'color:#6b7280;cursor:pointer;font-family:\'DM Sans\',sans-serif;'
            f'white-space:nowrap;flex-shrink:0;">'
            f'e mais {n_extra} links'
            f'</button>'
            f'</div>'

            # Links extras ocultos
            f'<div id="extra_links_{uid}" style="display:none;">{extra_rows}</div>'

            f'</div>'
        )
    
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

    # Detectar perfis configurados que ainda não foram coletados
    handles_coletados = {r.get("instagram", "").lstrip("@").strip().lower() for r in cache.get("dados", [])}
    novas_empresas = [
        e for e in todas
        if e["instagram"].lstrip("@").strip().lower() not in handles_coletados
    ]
    if novas_empresas:
        nomes = ", ".join(e["nome"] for e in novas_empresas)
        st.info(
            f"📡 **{nomes}** {'foi adicionada' if len(novas_empresas) == 1 else 'foram adicionadas'} "
            f"mas ainda não {'tem' if len(novas_empresas) == 1 else 'têm'} dados coletados. "
            f"Clique em **Coletar dados** para incluí-las."
        )

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
            iframes[i].style.marginTop = '-50px';
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
            if todas:
                pass
            else:
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
    background:#d2dde9;
    border-radius:16px;
    overflow:hidden;
    margin-bottom:0;
}}
.cards-grid {{
    display:grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap:12px;
    padding:12px;
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
<div style="display:flex;flex-direction:column;">
    <div class="main-wrap" style="width:100%;">
        <div class="cards-grid" id="cards-grid"></div>
    </div>
    <div id="comp-card-wrap" style="width:100%;display:block;"></div>
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
            + '<div class="emp-info" style="min-width:0;flex:1;">'
            + '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:2px;">'
            + '<div class="emp-nome" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;">' + e.nome + '</div>'
            + badgeHtml
            + '</div>'
            + (e.handle ? '<div style="font-size:12px;color:#9ca3af;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + e.handle + '</div>' : '')
            + '</div>';
        card.addEventListener('click', function() {{ selectAba(e.i); }});
        grid.appendChild(card);
    }});

    var compCard = document.createElement('div');
    compCard.style.cssText =
        'background:#034777;'
        + 'border-radius:0 0 14px 14px;padding:10px 16px;'
        + 'display:flex;align-items:center;justify-content:center;gap:8px;cursor:pointer;'
        + 'transition:all 0.15s;width:98%;margin:0 auto;box-sizing:border-box;';
    compCard.onmouseover = function() {{
        this.style.boxShadow = '0 4px 16px rgba(58,159,214,0.25)';
        this.style.background = '#036e77';
    }};
    compCard.onmouseout = function() {{
        this.style.boxShadow = 'none';
        this.style.background = '#034777';
    }};
    compCard.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;gap:8px;"><div style="width:20px;height:20px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:16px;">🏆</div><span style="font-size:13px;font-weight:700;color:#ffffff;white-space:nowrap;">Gerar Análise Comparativa</span><span style="font-size:12px;font-weight:400;color:#76bbe0;white-space:nowrap;">(Compara todos os perfis das empresas com IA)</span></div>';
    compCard.addEventListener('click', function() {{ triggerBtn('redes_comparativo'); }});
    var wrap = document.getElementById('comp-card-wrap');
    if (wrap) wrap.appendChild(compCard);

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
            frames[i].style.marginTop = '-62px';
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
            position: fixed !important;
            top: -9999px !important;
            left: -9999px !important;
            width: 1px !important;
            height: 1px !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }}
        .stElementContainer:has(.st-key-btn_bio_ia_{aba_ativa}) {{
            position: fixed !important;
            top: -9999px !important;
            left: -9999px !important;
            width: 1px !important;
            height: 1px !important;
            overflow: hidden !important;
            margin: 0 !important;
            padding: 0 !important;
        }}
        </style>
        """, unsafe_allow_html=True)

        analisar_bio = st.button(
            f"bio_ia_{aba_ativa}",
            key=f"btn_bio_ia_{aba_ativa}",
        )
        if analisar_bio:
            if gemini_model is None:
                st.session_state[chave_bio_ia] = "Configure GEMINI_API_KEY nos secrets."
            else:
                _ph = st.empty()
                _render_modal_redes_ia("gerando", f"Análise de Perfil — {r['nome']}", 40, _ph)
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
                    st.session_state.redes_analises_salvas.append({
                        "titulo": f"Análise de Perfil — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                        "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "relatorio": resp.text,
                        "tipo": "bio",
                        "perfil": r.get("handle", ""),
                        "nome": r["nome"],
                    })

                    _render_modal_redes_ia("concluido", f"Análise de Perfil — {r['nome']}", 100, _ph)
                    salvar_dados_usuario(st.session_state.user.id)
                    import time as _t; _t.sleep(1.2)
                    _ph.empty()
                    st.session_state[chave_bio_ia] = ""
                    st.session_state.redes_main_tab = "analise"
                    st.session_state.redes_analise_subtab = "bio"
                    st.rerun()
                except Exception as e:
                    _ph.empty()
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

            handle_clean_toggle = r.get('handle', '').replace('@', '')
            cols_toggle_key = f"ads_toggle_cols_{handle_clean_toggle}"
            n_cols_posts = st.session_state.get(posts_col_key, 4)
            icon_cols_url = (
                "https://raw.githubusercontent.com/thiagomktsantos/marketylics/4f750a3205deb9b8a618997b3b8e300e3c3bf3f3/images/icons/3-Columns.png"
                if n_cols_posts == 4
                else "https://raw.githubusercontent.com/thiagomktsantos/marketylics/4f750a3205deb9b8a618997b3b8e300e3c3bf3f3/images/icons/4-Columns.png"
            )

            st.markdown(f"""
            <style>
            .st-key-{cols_toggle_key} button {{
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

            if st.button(
                f"![col]({icon_cols_url})",
                key=cols_toggle_key,
                use_container_width=False,
                help="Alternar 3/4 colunas",
            ):
                st.session_state[posts_col_key] = 3 if n_cols_posts == 4 else 4
                st.rerun()
            # ADICIONAR — ghost button oculto para toggle de colunas
            cols_toggle_ghost_key = f"ghost_cols_toggle_{handle_clean_toggle}"
            st.markdown(f"""
            <style>
            .st-key-{cols_toggle_ghost_key} {{
                position:fixed !important; top:-9999px !important; left:-9999px !important;
                width:0 !important; height:0 !important; overflow:hidden !important;
                opacity:0 !important; pointer-events:none !important; display:none !important;
            }}
            .stElementContainer:has(.st-key-{cols_toggle_ghost_key}) {{
                display:none !important; height:0 !important; min-height:0 !important;
                max-height:0 !important; padding:0 !important; margin:0 !important; overflow:hidden !important;
            }}
            </style>
            """, unsafe_allow_html=True)

            if st.button(f"toggle_cols_{handle_clean_toggle}", key=cols_toggle_ghost_key):
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

            oportHtml_js = (
                f'\'<div style="display:inline-flex;align-items:center;font-size:12px;font-weight:700;'
                f'color:#2563eb;background:#dbeafe;border:1px solid #bfdbfe;padding:5px 12px;'
                f'border-radius:20px;white-space:nowrap;">+{score_oport} oportunidade'
                f'{"s" if score_oport != 1 else ""}</div>\''
                if score_oport > 0 else "''"
            )

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
.action-btns {{
    display:flex; flex-direction:row; gap:10px; flex-shrink:0;
}}
.action-btn {{
    display:flex; align-items:center; gap:10px;
    background:#fff; border:1.5px solid #e5e7eb; border-radius:12px;
    padding:10px 14px; cursor:pointer;
    font-family:'DM Sans',sans-serif;
    transition:all 0.15s; min-width:180px;
    text-align:left;
}}
.action-btn:hover {{
    border-color:#c7d2fe;
    box-shadow:0 4px 14px rgba(99,102,241,0.1);
}}
.action-btn-icon {{
    width:38px; height:38px; border-radius:10px;
    display:flex; align-items:center; justify-content:center;
    font-size:20px; flex-shrink:0;
}}
.action-btn-icon.blue   {{ background:#f3f4f6; }}
.action-btn-icon.purple {{ background:#f3f4f6; }}
.action-btn-text {{ display:flex; flex-direction:column; gap:2px; }}
.action-btn-title {{ font-size:13px; font-weight:700; color:#111827; }}
.action-btn-desc  {{ font-size:11px; color:#9ca3af; line-height:1.3; }}

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
    border:2px solid #e5e7eb;
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
    border:1px solid #e5e7eb; border-radius:8px;
    font-size:14px; font-family:'DM Sans',sans-serif; color:#374151;
    background:#fafafa url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2.5'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E") no-repeat right 10px center;
    -webkit-appearance:none; appearance:none; cursor:pointer; outline:none;
}}
.filter-select:focus {{ border-color:#3a9fd6; }}
.col-toggle {{
    margin-left:auto; width:38px; height:38px;
    border:2px solid #e5e7eb; border-radius:8px;
    background:#ffffff; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    flex-shrink:0; transition:all 0.12s;
}}
.col-toggle:hover {{ border-color:#d1d5db; background:#f3f4f6; }}

.stats-row {{ display:flex; gap:12px; padding:16px 0 4px; flex-wrap:wrap; }}
.stat-card {{
    flex:1; min-width:90px; background:#fff;
    border-radius:12px;
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
.post-card:hover {{ border:2px solid #6fd1f3; box-shadow:0 4px 16px rgba(58,159,214,0.12); }}
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
        <div class="action-btns">
            <button class="action-btn" onclick="trigger('postagens_{aba_ativa}')">
                <div class="action-btn-icon blue">📸</div>
                <div class="action-btn-text">
                    <span class="action-btn-title">Analisar postagens</span>
                    <span class="action-btn-desc">Criativos, copy e gatilhos</span>
                </div>
            </button>
            <button class="action-btn" onclick="trigger('geral_{aba_ativa}')">
                <div class="action-btn-icon purple">📊</div>
                <div class="action-btn-text">
                    <span class="action-btn-title">Analisar estratégia</span>
                    <span class="action-btn-desc">Posicionamento e crescimento</span>
                </div>
            </button>
        </div>
    </div>
    </div>

    <!-- BIO + SCORE -->
    <div style="display:grid;grid-template-columns:1fr auto 1fr;
                border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;
                border-left:1px solid #e5e7eb;min-height:170px;background:#ffffff;">

        <!-- Coluna esquerda: bio -->
        <div style="padding:20px 24px;display:flex;flex-direction:column;gap:0px;">
            <div style="font-size:12px;font-weight:700;color:#6b7280;
                        text-transform:uppercase;letter-spacing:1px;">BIO DO PERFIL</div>
            <div style="display:flex;flex-direction:column;gap:10px;flex:1;justify-content:center;">
                {('<div style="font-size:15px;color:#374151;line-height:1.75;">&ldquo;' + bio_txt + '&rdquo;</div>') if bio_txt else '<div style="font-size:14px;color:#d1d5db;font-style:italic;">Sem bio cadastrada neste perfil.</div>'}
                {(_build_links_html(ext_url)) if ext_url else ''}
            </div>
        </div>

        <!-- Divisor vertical -->
        <div style="width:1px;background:#e5e7eb;flex-shrink:0;height:80%;margin:auto;"></div>

        <!-- Coluna direita: Score -->
        <div style="padding:20px 24px;display:flex;flex-direction:column;gap:12px;min-width:300px;">
            <div style="font-size:12px;font-weight:700;color:#1a2e4a;
                        text-transform:uppercase;letter-spacing:1px;">SCORE DE PERFIL</div>
            <!-- Número + badge na mesma linha -->
            <div style="display:flex;align-items:center;gap:14px;justify-content:space-between;">
                <div style="display:flex;align-items:baseline;gap:4px;line-height:1;">
                    <span style="font-size:52px;font-weight:900;letter-spacing:-2px;
                                 line-height:1;color:{score_cor};">{score_val}</span>
                    <span style="font-size:16px;font-weight:600;color:#9ca3af;">/100</span>
                </div>
                <div style="display:inline-flex;align-items:center;gap:7px;
                            padding:10px 20px;border-radius:14px;font-size:17px;font-weight:800;
                            background:{score_bg};color:{score_cor};border:none;
                           letter-spacing:0.1px;white-space:nowrap;">
                    {score_icon} {score_cls}
                </div>
            </div>
            <div style="height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden;">
                <div id="score-bar-fill"
                     style="height:100%;width:0%;border-radius:4px;
                            background:linear-gradient(90deg,#3b82f6,{score_cor});
                            transition:width 1.2s cubic-bezier(0.4,0,0.2,1);"></div>
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
        <img id="cols-img" src="{icon_cols_url}" width="20" height="20" style="display:block;" />
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

(function() {{
    var btn = document.getElementById('cols-toggle-btn');
    if (!btn) return;
    var svg3 = '<rect x="3" y="3" width="5" height="18" rx="1"/><rect x="10" y="3" width="5" height="18" rx="1"/><rect x="17" y="3" width="5" height="18" rx="1"/>';
    var svg4 = '<rect x="2" y="3" width="4" height="18" rx="1"/><rect x="7.5" y="3" width="4" height="18" rx="1"/><rect x="13" y="3" width="4" height="18" rx="1"/><rect x="18.5" y="3" width="4" height="18" rx="1"/>';
    var icon = document.getElementById('cols-icon');
    if (icon) icon.innerHTML = N_COLS === 4 ? svg3 : svg4;
    btn.title = N_COLS === 4 ? 'Alternar para 3 colunas' : 'Alternar para 4 colunas';
}})();

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
    playBtn.innerHTML = '<div style="width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,0.92);display:flex;align-items:center;justify-content:center;box-shadow:0 4px 20px rgba(0,0,0,0.4);border:2px solid #ffffff !important;"><svg width="22" height="22" viewBox="0 0 54 54" fill="none"><polygon points="18,12 44,27 18,42" fill="#E1306C"/></svg></div><span style="color:#fff;font-size:13px;font-weight:700;font-family:DM Sans,sans-serif;background:rgba(0,0,0,0.5);padding:5px 14px;border-radius:20px;">Ver vídeo no Instagram</span>';
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
            ? '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;"><div style="width:52px;height:52px;border-radius:50%;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;border:2px solid #ffffff !important;"><svg width="20" height="20" viewBox="0 0 54 54" fill="none"><polygon points="18,12 44,27 18,42" fill="white"/></svg></div></div>'
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
              + 'font-weight:600;color:#15803d;background:#ffffff;border:1px solid #bbf7d0;'
              + 'padding:5px 12px;border-radius:20px;">'
              + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#15803d" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
              + ' ' + c.label + '</div>';
    }});
    var row2 = document.getElementById('insights-chips-row');
    if (row2) row2.innerHTML = html + {oportHtml_js};
}})();

function applyFilters() {{
    var posts = getFiltered();
    updateStats(posts);
    buildGrid(posts);
}}

function toggleCols() {{
    var key = '{cols_toggle_key}';
    var btns = window.parent.document.querySelectorAll('button');
    for (var b of btns) {{
        var wrap = b.closest('[data-testid="stElementContainer"]');
        if (wrap && wrap.classList.contains('st-key-' + key)) {{ b.click(); return; }}
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
                frames[i].style.marginTop = '-324px';
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
        for btn_sfx in ["postagens", "geral"]:
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

        if resultados_ia_btns["postagens"]:
            if gemini_model is None:
                st.toast("Configure GEMINI_API_KEY nos secrets.", icon="⚠️")
            else:
                _ph = st.empty()
                import datetime as _dt_redes
                import time as _t

                _render_modal_redes_ia("gerando", f"Postagens — {r['nome']}", 30, _ph)
                try:
                    resp_cri = gemini_model.generate_content(f"""
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
                    st.session_state[chave_criativo] = resp_cri.text
                    st.session_state.redes_analises_salvas.append({
                        "titulo": f"Criativos — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                        "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "relatorio": resp_cri.text,
                        "tipo": "criativos",
                        "perfil": r.get("handle", ""),
                        "nome": r["nome"],
                    })
                except Exception as e:
                    st.toast(f"Erro nos criativos: {e}", icon="⚠️")

                _render_modal_redes_ia("gerando", f"Postagens — {r['nome']}", 70, _ph)
                try:
                    resp_cop = gemini_model.generate_content(f"""
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
                    st.session_state[chave_copy] = resp_cop.text
                    st.session_state.redes_analises_salvas.append({
                        "titulo": f"Copy — {r['nome']} ({r.get('handle','')}) — {_dt_redes.datetime.now().strftime('%d/%m/%Y %H:%M')}",
                        "data": _dt_redes.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "relatorio": resp_cop.text,
                        "tipo": "copy",
                        "perfil": r.get("handle", ""),
                        "nome": r["nome"],
                    })
                except Exception as e:
                    st.toast(f"Erro no copy: {e}", icon="⚠️")

                _render_modal_redes_ia("concluido", f"Postagens — {r['nome']}", 100, _ph)
                salvar_dados_usuario(st.session_state.user.id)
                _t.sleep(1.2)
                _ph.empty()
                st.session_state.redes_main_tab = "analise"
                st.session_state.redes_analise_subtab = "criativos"
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
                    st.session_state.redes_main_tab = "analise"
                    st.session_state.redes_analise_subtab = "geral_perfil"
                    st.rerun()
                except Exception as e:
                    _ph.empty()
                    st.session_state[chave_geral] = f"Erro: {e}"
                    st.rerun()

    # ══════════════════════════════════════════════════════════════════
    # ABA: ANÁLISE DE IA — Comparativo geral
    # ══════════════════════════════════════════════════════════════════
 
    elif main_tab == "analise":

        ok = []
        if cache.get("dados"):
            ok = [r for r in cache["dados"] if not r.get("erro")]

        import json as _json_redes
        import datetime as _dt_redes

        analises_redes = st.session_state.get("redes_analises_salvas", [])

        # Marcar como vistas
        st.session_state.redes_analise_vistas = len(analises_redes)

        subtabs_def = [
            ("bio",          "👤", "Perfil"),
            ("postagem",     "📸", "Postagens"),
            ("geral_perfil", "📊", "Geral"),
            ("comparativo",  "🏆", "Comparativo"),
        ]

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

        # Ghost buttons subtabs
        ghost_subtabs_css = ", ".join([
            f".st-key-btn_redes_analise_sub_{stk}, .stElementContainer:has(.st-key-btn_redes_analise_sub_{stk})"
            for stk, _, _ in subtabs_def
        ])
        st.markdown(f"""
        <style>
        {ghost_subtabs_css} {{
            position:fixed !important; top:-9999px !important; left:-9999px !important;
            width:0 !important; height:0 !important; overflow:hidden !important;
            opacity:0 !important; pointer-events:none !important; display:none !important;
            min-height:0 !important; max-height:0 !important; padding:0 !important; margin:0 !important;
        }}
        </style>
        """, unsafe_allow_html=True)

        if "redes_analise_subtab" not in st.session_state:
            st.session_state.redes_analise_subtab = "bio"

        for stk, _, _ in subtabs_def:
            if st.button(f"redes_analise_sub_{stk}", key=f"btn_redes_analise_sub_{stk}"):
                st.session_state.redes_analise_subtab = stk
                st.rerun()

        subtab_analise = st.session_state.redes_analise_subtab
        contagens = {}
        for stk, _, _ in subtabs_def:
            if stk == "postagem":
                contagens[stk] = len([
                    a for a in analises_redes
                    if a.get("tipo") in ("postagem", "criativos", "copy")
                ])
            else:
                contagens[stk] = len([a for a in analises_redes if a.get("tipo") == stk])

        # ── Barra de subtabs
        components.html(f"""
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:hidden; }}
.tabs-wrap {{
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:8px;
    width:100%;
}}
.tab-pill {{
    display:flex; align-items:center; justify-content:center; gap:6px;
    padding:10px 8px; border-radius:10px; cursor:pointer;
    border:1.5px solid #e5e7eb; background:#fff; text-decoration:none;
    font-size:13px; font-weight:600; color:#6b7280;
    transition:all 0.15s; white-space:nowrap;
    font-family:'DM Sans',sans-serif; line-height:1; width:100%;
}}
.tab-pill:hover {{ border-color:#3a9fd6; color:#1d4ed8; background:#eff6ff; }}
.tab-pill.active {{ background:#0e2a47; border-color:#0e2a47; color:#fff; }}
.tab-badge {{
    font-size:11px; font-weight:800; padding:2px 8px; border-radius:20px;
    background:#e5e7eb; color:#6b7280; line-height:1.4; flex-shrink:0;
}}
.tab-pill.active .tab-badge {{ background:rgba(255,255,255,0.15); color:#fff; }}
.tab-badge.has {{ background:#3a9fd6; color:#fff; }}
.tab-pill.active .tab-badge.has {{ background:#3a9fd6; color:#fff; }}
</style>
<div class="tabs-wrap">
{''.join([
    f'''<a class="tab-pill {'active' if subtab_analise == stk else ''}"
        href="javascript:void(0)"
        onclick="(function(){{var btns=window.parent.document.querySelectorAll('button');for(var b of btns){{var t=(b.textContent||b.innerText||'').split(/\\s+/).join(' ').trim();if(t==='redes_analise_sub_{stk}'){{b.click();return;}}}}}})()"
    >{icon} {lbl} <span class="tab-badge {'has' if contagens.get(stk,0) > 0 else ''}">{contagens.get(stk,0)}</span></a>'''
    for stk, icon, lbl in subtabs_def
])}
</div>
<script>
(function() {{
    var iframes = window.parent.document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {{
        try {{ if (iframes[i].contentWindow === window) {{
            iframes[i].style.height = '52px';
            iframes[i].style.marginTop = '-47px';
            break;
        }} }} catch(e) {{}}
    }}
}})();
</script>
""", height=52, scrolling=False)

        # ── Conteúdo da subtab ativa
        if subtab_analise == "postagem":
            lista_ativa = [
                a for a in analises_redes
                if a.get("tipo") in ("postagem", "criativos", "copy")
            ]
        else:
            lista_ativa = [a for a in analises_redes if a.get("tipo") == subtab_analise]
        icons_map   = {"bio":"👤","postagem":"📸","criativos":"🎨","copy":"✍️","geral_perfil":"📊","comparativo":"🏆"}
        labels_map  = {"bio":"Perfil","postagem":"Postagens","criativos":"Criativos","copy":"Copy","geral_perfil":"Geral","comparativo":"Comparativo"}
        icon_ativo  = icons_map.get(subtab_analise, "📋")
        label_ativo = labels_map.get(subtab_analise, "")

        def _md_to_html_redes(txt):
            if not txt: return ""
            import re as _re

            txt = txt.replace("&", "&amp;")
            txt = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', txt)
            txt = _re.sub(r'^### (.+)$', r'<h3>\1</h3>', txt, flags=_re.MULTILINE)
            txt = _re.sub(r'^## (.+)$',  r'<h2>\1</h2>', txt, flags=_re.MULTILINE)
            txt = _re.sub(r'^# (.+)$',   r'<h1>\1</h1>', txt, flags=_re.MULTILINE)
            txt = _re.sub(r'^---+$', '<hr>', txt, flags=_re.MULTILINE)

            def _apply_inline(s):
                return _re.sub(r'\*([^*\n]+?)\*', r'<em>\1</em>', s)

            def _get_ol_match(line):
                return _re.match(r'^(\s*)(\d+)\.\s+(.*)', line)

            def _get_ul_match(line):
                return _re.match(r'^(\s*)[\*\-]\s+(.*)', line)

            lines = txt.split('\n')
            output = []
            list_stack = []

            def close_until(target_indent):
                while list_stack and list_stack[-1][1] >= target_indent:
                    tag, _ = list_stack.pop()
                    output.append(f'</{tag}>')

            def close_all():
                while list_stack:
                    tag, _ = list_stack.pop()
                    output.append(f'</{tag}>')

            i = 0
            while i < len(lines):
                line = lines[i]

                if not line.strip():
                    i += 1
                    continue

                stripped = line.strip()

                if _re.match(r'^\s*<(h[123]|hr)', line):
                    close_all()
                    output.append(stripped)
                    i += 1
                    continue

                m_ol = _get_ol_match(line)
                if m_ol:
                    item_indent = len(m_ol.group(1))
                    content     = _apply_inline(m_ol.group(3))
                    close_until(item_indent + 1)
                    if not list_stack or list_stack[-1][1] < item_indent or list_stack[-1][0] != 'ol':
                        if list_stack and list_stack[-1][1] == item_indent and list_stack[-1][0] != 'ol':
                            tag, _ = list_stack.pop()
                            output.append(f'</{tag}>')
                        output.append('<ol>')
                        list_stack.append(('ol', item_indent))
                    output.append(f'<li>{content}</li>')
                    i += 1
                    continue

                m_ul = _get_ul_match(line)
                if m_ul:
                    item_indent = len(m_ul.group(1))
                    content     = _apply_inline(m_ul.group(2))
                    close_until(item_indent + 1)
                    if not list_stack or list_stack[-1][1] < item_indent or list_stack[-1][0] != 'ul':
                        if list_stack and list_stack[-1][1] == item_indent and list_stack[-1][0] != 'ul':
                            tag, _ = list_stack.pop()
                            output.append(f'</{tag}>')
                        output.append('<ul>')
                        list_stack.append(('ul', item_indent))
                    output.append(f'<li>{content}</li>')
                    i += 1
                    continue

                close_all()
                output.append(f'<p>{_apply_inline(stripped)}</p>')
                i += 1

            close_all()
            html = '\n'.join(output)

            # ── Pós-processamento: envolve seções em caixas ──
            BOX_RULES = [
                (r'(pontos?\s+forte[s]?|positivo[s]?|destaques?|quem\s+se\s+destaca|o\s+que\s+funciona|o\s+que\s+est[aá]\s+funcionando|aspectos?\s+positivos?|qualidade[s]?)',
                 '#16a34a', '#f0fdf4', '#bbf7d0', '✅'),
                (r'(o\s+que\s+melhorar|pontos?\s+de\s+aten[çc][ãa]o|fraqueza[s]?|clareza|inconsist[eê]ncia[s]?|o\s+que\s+pode\s+melhorar|limita[çc][õo]e[s]?|gaps?)',
                 '#d97706', '#fffbeb', '#fde68a', '💡'),
                (r'(recomenda[çc][õo]e[s]?|a[çc][õo]e[s]?\s+concreta[s]?|pr[oó]ximos?\s+passo[s]?|sugest[õo]e[s]?|como\s+melhorar|plano\s+de\s+a[çc][ãa]o|bio\s+sugerida|caption[s]?\s+sugerido[s]?|legenda[s]?\s+sugerida[s]?|copy\s+sugerido|texto[s]?\s+sugerido[s]?|exemplo[s]?\s+de\s+copy|exemplo[s]?\s+de\s+caption|exemplo[s]?\s+de\s+legenda)',
                 '#2563eb', '#eff6ff', '#bfdbfe', '🎯'),
                (r'(oportunidade[s]?|estrat[eé]gia[s]?|crescimento|potencial|expans[ãa]o|nichos?|mercado[s]?|tend[eê]ncia[s]?)',
                 '#7c3aed', '#f5f3ff', '#ddd6fe', '🚀'),
                (r'(vis[ãa]o\s+geral|an[aá]lise\s+geral|an[aá]lise\s+comparativa|vis[ãa]o\s+geral\s+comparativa|contexto|panorama|resumo\s+geral|overview)',
                 '#0891b2', '#ecfeff', '#a5f3fc', '📊'),
                (r'(posicionamento|identidade|tom\s+de\s+voz|persona|voz\s+da\s+marca|proposta\s+de\s+valor|diferencial)',
                 '#4f46e5', '#eef2ff', '#c7d2fe', '🎨'),
                (r'(engajamento|m[eé]trica[s]?|desempenho|resultado[s]?|performance|taxa[s]?|alcance|impress[õo]e[s]?|frequ[eê]ncia|cad[eê]ncia|consist[eê]ncia)',
                 '#db2777', '#fdf2f8', '#fbcfe8', '📈'),
                (r'(criativo[s]?|visual|est[eé]tica|formato[s]?|design|imagens?|v[ií]deos?|reels?|stories?|carrossel[s]?|layout|paleta)',
                 '#ea580c', '#fff7ed', '#fed7aa', '🖼️'),
                (r'(hashtag[s]?|seo|descoberta|palavras?\s*[- ]?\s*chave|busca|indexa[çc][ãa]o|alcance\s+org[âa]nico)',
                 '#059669', '#ecfdf5', '#a7f3d0', '#️⃣'),
                (r'(an[aá]lise\s+d[ao]\s+bio|an[aá]lise\s+d[ao]\s+perfil|sobre\s+o\s+perfil|apresenta[çc][ãa]o|descri[çc][ãa]o\s+d[ao]\s+perfil|bio\s+atual)',
                 '#475569', '#f8fafc', '#cbd5e1', '👤'),
                (r'(p[úu]blico[- ]alvo|audi[êe]ncia|segmento|seguidor[es]?|comunidade|nicho\s+de\s+p[úu]blico)',
                 '#0d9488', '#f0fdfa', '#99f6e4', '🎯'),
            ]

            FALLBACK_BOX = ('#1e40af', '#f0f9ff', '#bae6fd', '📋')

            def _wrap_section(html_str):
                import re as _r2

                partes = _r2.split(r'(<h[23][^>]*>.*?</h[23]>)', html_str, flags=_r2.DOTALL)

                output_parts = []
                i2 = 0
                while i2 < len(partes):
                    parte = partes[i2]
                    m_hdr = _r2.match(r'<(h[23])[^>]*>(.*?)<\/h[23]>', parte, flags=_r2.DOTALL)
                    if m_hdr:
                        hdr_txt       = m_hdr.group(2)
                        hdr_txt_clean = _r2.sub(r'<[^>]+>', '', hdr_txt)
                        conteudo      = partes[i2 + 1] if i2 + 1 < len(partes) else ""
                        i2 += 1

                        matched_box = False
                        for pattern, border, bg, border_light, icon in BOX_RULES:
                            if _r2.search(pattern, hdr_txt_clean, flags=_r2.IGNORECASE):
                                caixa = (
                                    f'<div style="border:2px solid {border_light};border-left:4px solid {border};'
                                    f'border-radius:10px;background:{bg};padding:16px 20px;margin:12px 0;">'
                                    f'<div style="font-size:13px;font-weight:800;color:{border};border-bottom:2px solid {border};'
                                    f'text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">'
                                    f'{icon} {hdr_txt_clean}</div>'
                                    f'<div>{conteudo}</div>'
                                    f'</div>'
                                )
                                output_parts.append(caixa)
                                matched_box = True
                                break

                        if not matched_box:
                            border, bg, border_light, icon = FALLBACK_BOX
                            caixa = (
                                f'<div style="border:2px solid {border_light};border-left:4px solid {border};'
                                f'border-radius:10px;background:{bg};padding:16px 20px;margin:12px 0;">'
                                f'<div style="font-size:13px;font-weight:800;color:{border};'
                                f'text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">'
                                f'{icon} {hdr_txt_clean}</div>'
                                f'<div>{conteudo}</div>'
                                f'</div>'
                            )
                            output_parts.append(caixa)
                    else:
                        output_parts.append(parte)
                    i2 += 1

                return ''.join(output_parts)

            import re as _re_promote
            html = _re_promote.sub(
                r'<p><strong>([^<]+?):?</strong></p>',
                r'<h3>\1</h3>',
                html
            )
            html = _wrap_section(html)
            return html

        relatorios_redes      = {str(i): _md_to_html_redes(a.get("relatorio","")) for i, a in enumerate(analises_redes)}
        relatorios_redes_json = _json_redes.dumps(relatorios_redes, ensure_ascii=False)
        relatorios_raw        = {str(i): a.get("relatorio","")                     for i, a in enumerate(analises_redes)}
        relatorios_raw_json   = _json_redes.dumps(relatorios_raw, ensure_ascii=False)

        if lista_ativa:
            cards_redes_html = ""
            for a in reversed(lista_ativa):
                idx_real = analises_redes.index(a)
                icon_a   = icons_map.get(a.get("tipo",""), "📋")
                titulo_a = a.get("titulo","—").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                nome_arq = titulo_a.replace(" ","_").replace("/","_").replace("(","").replace(")","").replace(".","")
                cards_redes_html += f"""
        <div class="card-row" style="border-bottom:1px solid #f3f4f6;background:#fff;">
            <div class="card-hdr" data-idx="{idx_real}"
                 style="display:flex;align-items:center;gap:10px;padding:12px 16px;
                        cursor:pointer;background-color:#0e2a47;">
                <span style="font-size:18px;flex-shrink:0;">{icon_a}</span>
                <div style="flex:1;min-width:0;font-size:14px;font-weight:600;color:#ffffff;
                            overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{titulo_a}</div>

                <button class="btn-fullscreen" data-idx="{idx_real}" title="Abrir em tela cheia"
                    style="flex-shrink:0;background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.25);
                           border-radius:6px;width:30px;height:30px;display:flex;align-items:center;
                           justify-content:center;cursor:pointer;transition:background 0.15s;">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"
                         stroke-linecap="round" stroke-linejoin="round">
                        <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
                    </svg>
                </button>

                <button class="btn-raw" data-idx="{idx_real}" title="Ver texto original"
                    style="flex-shrink:0;background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.25);
                           border-radius:6px;width:30px;height:30px;display:flex;align-items:center;
                           justify-content:center;cursor:pointer;transition:background 0.15s;">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"
                         stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="16 18 22 12 16 6"/>
                        <polyline points="8 6 2 12 8 18"/>
                    </svg>
                </button>

                <span class="btn-chevron" data-idx="{idx_real}"
                      style="color:#d1d5db;transition:transform 0.2s;display:flex;align-items:center;flex-shrink:0;cursor:pointer;">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </span>
            </div>

            <div id="rb_{idx_real}" style="display:none;border-top:1px solid #f3f4f6;">
                <div id="rr_{idx_real}"
                     style="font-size:14px;color:#374151;line-height:1.8;padding:14px 16px;word-break:break-word;"></div>
                <div style="display:flex;gap:8px;padding:10px 16px;background:#f9fafb;border-top:1px solid #f3f4f6;">
                    <button class="btn-download" data-idx="{idx_real}" data-filename="{nome_arq}"
                        style="flex:1;padding:9px;border-radius:8px;border:1px solid #e5e7eb;
                               background:#fff;font-size:13px;font-weight:600;color:#374151;
                               cursor:pointer;font-family:'DM Sans',sans-serif;">
                        ⬇️ Baixar .txt
                    </button>
                    <button class="btn-excluir" data-idx="{idx_real}"
                        style="padding:9px 16px;border-radius:8px;border:1px solid #fecaca;
                               background:#fef2f2;font-size:13px;font-weight:600;color:#dc2626;
                               cursor:pointer;font-family:'DM Sans',sans-serif;
                               display:flex;align-items:center;gap:6px;white-space:nowrap;
                               transition:all 0.15s;"
                        onmouseover="this.style.background='#dc2626';this.style.color='#fff';this.style.borderColor='#dc2626';"
                        onmouseout="this.style.background='#fef2f2';this.style.color='#dc2626';this.style.borderColor='#fecaca';">
                        🗑️ Excluir
                    </button>
                </div>
            </div>
        </div>"""

            components.html(f"""
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        html, body {{ background:transparent; font-family:'DM Sans',sans-serif; overflow:visible; }}
        body {{ padding-bottom:8px; }}
        [id^="rr_"] ol > li > ul > li::before {{
            content: '◦';
            position: absolute;
            left: 0; top: 0;
            color: #00aae6;
            font-size: 18px;
            line-height: 1.3;
            font-weight: normal;
            background: none;
            border-radius: 0;
            width: auto; height: auto;
        }}
        [id^="rr_"] div[style*="border-left"] ul,
        #smb_redes div[style*="border-left"] ul {{
            margin: 4px 0 0 18px;
            list-style: disc;
        }}
        [id^="rr_"] div[style*="border-left"] li,
        #smb_redes div[style*="border-left"] li {{
            margin-bottom: 6px;
            line-height: 1.6;
        }}
        [id^="rr_"] div[style*="border-left"] ol,
        #smb_redes div[style*="border-left"] ol {{
            margin: 4px 0 0 0;
            list-style: none;
            counter-reset: meu-contador;
            padding-left: 0;
        }}
        [id^="rr_"] div[style*="border-left"] ol > li,
        #smb_redes div[style*="border-left"] ol > li {{
            position: relative;
            padding-left: 34px;
            margin-bottom: 10px;
            line-height: 1.6;
        }}
        [id^="rr_"] div[style*="border-left"] ol > li::before,
        #smb_redes div[style*="border-left"] ol > li::before {{
            counter-increment: meu-contador;
            content: counter(meu-contador);
            position: absolute;
            left: 0; top: 0;
            background-color: #00aae6;
            color: #fff;
            border-radius: 50%;
            width: 24px; height: 24px;
            display: flex; align-items: center; justify-content: center;
            font-size: 13px; font-weight: bold;
        }}
        [id^="rr_"] div[style*="border-left"] p,
        #smb_redes div[style*="border-left"] p {{
            margin: 0 0 6px;
            line-height: 1.7;
        }}
        #smb_redes h1,#smb_redes h2,#smb_redes h3 {{
            font-size:16px; font-weight:800; color:#0f1f35;
            margin:18px 0 8px; padding-bottom:6px;
            border-bottom:2px solid #e5e7eb; text-transform:uppercase;
        }}
        #smb_redes p  {{ margin:0 0 10px; line-height:1.75; }}
        #smb_redes ul {{ margin:6px 0 14px 24px; }}
        #smb_redes li {{ margin:0 0 4px; line-height:1.65; }}
        #smb_redes li::marker {{ color:#00c162; }}
        #smb_redes hr {{ display:none; }}
        #smb_redes ol {{
            margin: 5px 0 15px 5px;
            list-style: none;
            counter-reset: meu-contador;
        }}
        #smb_redes ol > li {{
            line-height: 1.6;
            position: relative;
            padding-left: 35px;
            margin-bottom: 15px;
        }}
        #smb_redes ol > li::before {{
            counter-increment: meu-contador;
            content: counter(meu-contador);
            position: absolute;
            left: 0; top: 0;
            background-color: #00aae6;
            color: #ffffff;
            border-radius: 50%;
            width: 25px; height: 25px;
            display: flex; align-items: center; justify-content: center;
            font-size: 14px; font-weight: bold;
        }}
        #smb_redes ol > li > ul {{
            margin: 6px 0 0 0;
            list-style: none;
            padding-left: 0;
        }}
        #smb_redes ol > li > ul > li {{
            position: relative;
            padding-left: 18px;
            margin-bottom: 8px;
            line-height: 1.6;
        }}
        #smb_redes ol > li > ul > li::before {{
            content: '◦';
            position: absolute;
            left: 0; top: 0;
            color: #00aae6;
            font-size: 18px;
            line-height: 1.3;
            font-weight: normal;
            background: none;
            border-radius: 0;
            width: auto; height: auto;
        }}
        </style>

        <div style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;margin-top:8px;">
            {cards_redes_html}
        </div>

        <script>
        var RELS     = {relatorios_redes_json};
        var RELS_RAW = {relatorios_raw_json};

        function syncH() {{
            var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
            var frames = window.parent.document.querySelectorAll('iframe');
            for (var i = 0; i < frames.length; i++) {{
                try {{ if (frames[i].contentWindow === window) {{
                    frames[i].style.height = (h + 8) + 'px';
                    frames[i].style.marginTop = '-57px';
                    break;
                }} }} catch(e) {{}}
            }}
        }}

        function toggleRedes(idx) {{
            var b = document.getElementById('rb_' + idx);
            var r = document.getElementById('rr_' + idx);
            var chevrons = document.querySelectorAll('.btn-chevron[data-idx="' + idx + '"]');
            if (!b) return;
            var open = b.style.display !== 'none';
            b.style.display = open ? 'none' : 'block';
            chevrons.forEach(function(c) {{ c.style.transform = open ? '' : 'rotate(180deg)'; }});
            if (!open && r && !r.dataset.loaded) {{
                r.innerHTML = RELS[String(idx)] || '';
                r.dataset.loaded = '1';
            }}
            setTimeout(syncH, 100);
        }}

        function abrirModal(idx) {{
            var doc  = window.parent.document;
            var html = RELS[String(idx)] || '';
            var raw  = RELS_RAW[String(idx)] || '';
            var old  = doc.getElementById('redes_analise_modal_overlay');
            if (old) old.remove();

            var ov = doc.createElement('div');
            ov.id = 'redes_analise_modal_overlay';
            ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:999999;'
                + 'display:flex;align-items:flex-start;justify-content:center;padding:32px 24px;overflow-y:auto;';
            ov.addEventListener('click', function(e) {{ if (e.target === ov) fecharModal(); }});

            var box = doc.createElement('div');
            box.style.cssText = 'background:#fff;border-radius:16px;overflow:hidden;width:min(95vw,860px);'
                + 'display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,0.4);';

            var hdr = doc.createElement('div');
            hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:16px 24px;'
                + 'background:#0e2a47;flex-shrink:0;gap:12px;';

            var titleEl = doc.createElement('div');
            titleEl.style.cssText = 'font-size:15px;font-weight:700;color:#fff;flex:1;min-width:0;'
                + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            titleEl.textContent = 'Análise completa';

            var rawBtn = doc.createElement('button');
            rawBtn.id = 'redes_modal_raw_btn';
            rawBtn.textContent = 'Ver texto original';
            rawBtn.style.cssText = 'padding:6px 14px;border:1px solid rgba(255,255,255,0.3);border-radius:6px;'
                + 'background:rgba(255,255,255,0.12);color:#fff;font-size:12px;font-weight:700;cursor:pointer;'
                + 'font-family:DM Sans,sans-serif;white-space:nowrap;';
            rawBtn.addEventListener('click', function() {{ toggleModalView(html, raw); }});

            var closeBtn = doc.createElement('button');
            closeBtn.textContent = '✕';
            closeBtn.style.cssText = 'width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.12);'
                + 'border:1px solid rgba(255,255,255,0.25);color:#fff;font-size:17px;cursor:pointer;'
                + 'display:flex;align-items:center;justify-content:center;flex-shrink:0;';
            closeBtn.addEventListener('click', fecharModal);

            hdr.appendChild(titleEl);
            hdr.appendChild(rawBtn);
            hdr.appendChild(closeBtn);

            var body = doc.createElement('div');
            body.id = 'smb_redes';
            body.style.cssText = 'padding:28px 32px;font-size:14px;color:#374151;line-height:1.85;'
                + 'overflow-y:auto;max-height:75vh;word-break:break-word;';
            body.innerHTML = html || '<p style="color:#9ca3af">Sem conteúdo.</p>';

            box.appendChild(hdr);
            box.appendChild(body);
            ov.appendChild(box);
            doc.body.appendChild(ov);

            window.__redesAnaliseModalShowingRaw = false;

            window.parent.__redesAnaliseModalEsc = function(e) {{ if (e.key === 'Escape') fecharModal(); }};
            doc.addEventListener('keydown', window.parent.__redesAnaliseModalEsc);
        }}

        function toggleModalView(html, raw) {{
            var doc  = window.parent.document;
            var body = doc.getElementById('smb_redes');
            var btn  = doc.getElementById('redes_modal_raw_btn');
            if (!body || !btn) return;
            window.__redesAnaliseModalShowingRaw = !window.__redesAnaliseModalShowingRaw;
            if (window.__redesAnaliseModalShowingRaw) {{
                body.style.cssText += ';font-family:monospace;white-space:pre-wrap;font-size:12.5px;background:#0d1117;color:#e6edf3;';
                body.textContent = raw;
                btn.textContent  = 'Ver formatado';
            }} else {{
                body.style.fontFamily = ''; body.style.whiteSpace = '';
                body.style.fontSize   = '14px'; body.style.background = '#fff'; body.style.color = '#374151';
                body.innerHTML  = html;
                btn.textContent = 'Ver texto original';
            }}
        }}

        function fecharModal() {{
            var doc = window.parent.document;
            var ov  = doc.getElementById('redes_analise_modal_overlay');
            if (ov) ov.remove();
            if (window.parent.__redesAnaliseModalEsc) {{
                doc.removeEventListener('keydown', window.parent.__redesAnaliseModalEsc);
                window.parent.__redesAnaliseModalEsc = null;
            }}
        }}

        function abrirRaw(idx) {{
            var doc = window.parent.document;
            var raw = RELS_RAW[String(idx)] || '';
            var old = doc.getElementById('redes_raw_overlay');
            if (old) old.remove();

            var ov = doc.createElement('div');
            ov.id = 'redes_raw_overlay';
            ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:999999;'
                + 'display:flex;align-items:center;justify-content:center;padding:24px;';
            ov.addEventListener('click', function(e) {{ if (e.target === ov) ov.remove(); }});

            var box = doc.createElement('div');
            box.style.cssText = 'background:#0d1117;border-radius:16px;overflow:hidden;width:min(95vw,1000px);'
                + 'max-height:88vh;display:flex;flex-direction:column;border:1px solid #1e395e;';

            var hdr = doc.createElement('div');
            hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:14px 22px;'
                + 'border-bottom:1px solid #1e395e;background:#0e1e35;flex-shrink:0;';

            var info = doc.createElement('div');
            info.innerHTML = '<div style="font-size:14px;font-weight:700;color:#e6edf3;font-family:DM Sans,sans-serif;">📄 Texto original</div>'
                + '<div style="font-size:11px;color:#8b949e;margin-top:2px;">Markdown bruto</div>';

            var btnsWrap = doc.createElement('div');
            btnsWrap.style.cssText = 'display:flex;gap:8px;';

            var copyBtn = doc.createElement('button');
            copyBtn.textContent = '📋 Copiar';
            copyBtn.style.cssText = 'padding:6px 14px;border:1px solid #1e395e;border-radius:7px;background:#0e1e35;'
                + 'color:#22c45e;font-size:12px;font-weight:700;cursor:pointer;';
            copyBtn.addEventListener('click', function() {{
                var ta = doc.createElement('textarea');
                ta.value = raw;
                ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;';
                doc.body.appendChild(ta); ta.focus(); ta.select();
                try {{ doc.execCommand('copy'); copyBtn.textContent = '✅ Copiado!'; }}
                catch(e) {{ copyBtn.textContent = '❌ Erro'; }}
                doc.body.removeChild(ta);
                setTimeout(function() {{ copyBtn.textContent = '📋 Copiar'; }}, 2000);
            }});

            var closeRaw = doc.createElement('button');
            closeRaw.textContent = '✕';
            closeRaw.style.cssText = 'width:32px;height:32px;border-radius:50%;background:#0e1e35;'
                + 'border:1px solid #1e395e;color:#22c45e;font-size:17px;cursor:pointer;'
                + 'display:flex;align-items:center;justify-content:center;';
            closeRaw.addEventListener('click', function() {{ ov.remove(); }});

            btnsWrap.appendChild(copyBtn);
            btnsWrap.appendChild(closeRaw);
            hdr.appendChild(info);
            hdr.appendChild(btnsWrap);

            var pre = doc.createElement('pre');
            pre.style.cssText = 'flex:1;overflow-y:auto;overflow-x:auto;padding:20px 24px;font-size:12.5px;'
                + 'line-height:1.7;color:#e6edf3;font-family:monospace;background:#0d1117;margin:0;'
                + 'white-space:pre-wrap;word-break:break-word;';
            pre.textContent = raw;

            box.appendChild(hdr);
            box.appendChild(pre);
            ov.appendChild(box);
            doc.body.appendChild(ov);

            var escFn = function(e) {{ if (e.key === 'Escape') {{ ov.remove(); doc.removeEventListener('keydown', escFn); }} }};
            doc.addEventListener('keydown', escFn);
        }}

        function excluirAnalise(idx) {{
            var label = '_rm_redes_analise_' + idx + '_';
            var btns  = window.parent.document.querySelectorAll('button');
            for (var b of btns) {{
                var txt = (b.textContent || b.innerText || '').split(/\s+/).join(' ').trim();
                if (txt === label) {{ b.click(); return; }}
            }}
        }}

        document.addEventListener('click', function(e) {{
            var fs = e.target.closest('.btn-fullscreen');
            if (fs) {{ e.stopPropagation(); abrirModal(parseInt(fs.dataset.idx)); return; }}

            var rv = e.target.closest('.btn-raw');
            if (rv) {{ e.stopPropagation(); abrirRaw(parseInt(rv.dataset.idx)); return; }}

            var dl = e.target.closest('.btn-download');
            if (dl) {{
                e.stopPropagation();
                var raw = RELS_RAW[String(dl.dataset.idx)] || '';
                var a = document.createElement('a');
                a.href = URL.createObjectURL(new Blob([raw], {{type:'text/plain'}}));
                a.download = dl.dataset.filename + '.txt';
                a.click();
                return;
            }}

            var ex = e.target.closest('.btn-excluir');
            if (ex) {{
                e.stopPropagation();
                excluirAnalise(parseInt(ex.dataset.idx));
                return;
            }}

            var hdr = e.target.closest('.card-hdr');
            if (hdr && !e.target.closest('button')) {{
                toggleRedes(parseInt(hdr.dataset.idx));
                return;
            }}

            var ch = e.target.closest('.btn-chevron');
            if (ch) {{ toggleRedes(parseInt(ch.dataset.idx)); return; }}
        }});

        (function() {{
            var cards = document.querySelectorAll('[id^="rb_"]');
            if (cards.length === 1) {{
                var m = cards[0].id.match(/rb_(\d+)/);
                if (m) setTimeout(function() {{ toggleRedes(parseInt(m[1])); }}, 150);
            }}
        }})();

        if (window.ResizeObserver) new ResizeObserver(syncH).observe(document.body);
        setTimeout(syncH, 200);
        setTimeout(syncH, 600);
        </script>
        """, height=100, scrolling=False)
        else:
            btn_vazio_html = ""
            if subtab_analise == "comparativo":
                btn_vazio_html = """
<button onclick="(function(){var btns=window.parent.document.querySelectorAll('button');for(var b of btns){var t=(b.textContent||b.innerText||'').split(/\\s+/).join(' ').trim();if(t==='redes_comparativo'){b.click();return;}}})()"
    style="margin-top:4px;padding:10px 22px;border-radius:8px;border:none;
           background:#0e2a47;font-size:14px;font-weight:700;color:#fff;
           cursor:pointer;font-family:'DM Sans',sans-serif;">
    ⚡ Gerar Comparativo
</button>"""
            else:
                btn_vazio_html = '<div style="font-size:13px;color:#9ca3af;">Vá em <b>Perfis configurados</b> para gerar.</div>'

            st.markdown(f"""
            <div style="border:1px dashed #e5e7eb;border-radius:12px;padding:48px 24px;
                        text-align:center;background:#fff;margin-top:8px;
                        display:flex;flex-direction:column;align-items:center;gap:10px;">
                <div style="font-size:32px;opacity:0.4;">{icon_ativo}</div>
                <div style="font-size:14px;color:#9ca3af;">Nenhuma análise de {label_ativo.lower()} ainda.</div>
                {btn_vazio_html}
            </div>
            """, unsafe_allow_html=True)
