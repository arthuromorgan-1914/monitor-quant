import os
import shutil
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
import gspread
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time
import threading
import random 
from flask import Flask
from datetime import datetime, timedelta
from pathlib import Path
import feedparser
from tradingview_ta import TA_Handler, Interval, Exchange
import schedule
import requests

# ==============================================================================
# 1. CONFIGURAÇÕES
# ==============================================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

print("--- INICIANDO QUANTBOT V58 (BDR AUTO-FIX) ---")
if not TOKEN: print("ERRO: TOKEN não encontrado.")

bot = telebot.TeleBot(TOKEN) if TOKEN else None
ultimo_sinal_enviado = {} 
VOLUME_MINIMO_BRL = 5_000_000 

# LISTAS (Adicionei BDRs ao Pool da B3)
POOL_CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "XRP-USD", "LINK-USD", "AVAX-USD", "DOT-USD"]

POOL_B3 = [
    "PETR4.SA", "VALE3.SA", "PRIO3.SA", "ITUB4.SA", "WEGE3.SA", "BBAS3.SA",
    "GGBR4.SA", "CSAN3.SA", "BBDC4.SA", "BPAC11.SA", "RENT3.SA", "LREN3.SA",
    "HAPV3.SA", "RADL3.SA", "SUZB3.SA", "ELET3.SA", "EQTL3.SA", "SBSP3.SA",
    "VBBR3.SA", "RAIL3.SA", "CMIG4.SA", "TIMS3.SA", "VIVT3.SA", "JBSS3.SA",
    # BDRs Populares (Agora monitorados também)
    "AAPL34.SA", "NVDC34.SA", "MSFT34.SA", "TSLA34.SA", "AMZO34.SA", "GOGL34.SA"
]

# ==============================================================================
# 2. FUNÇÕES AUXILIARES (COM TRADUTOR DE BDR)
# ==============================================================================
def formatar_preco(valor):
    if valor < 50: return f"{valor:.4f}"
    return f"{valor:.2f}"

def corrigir_escala(symbol, preco):
    if "USD" in symbol: return preco 
    if preco > 10000: return preco / 10000
    return preco

def normalizar_simbolo(entrada):
    """
    Inteligência para corrigir Tickers errados e converter EUA -> BDR.
    """
    s = entrada.upper().strip()
    
    # === MAPA DE TRADUÇÃO BDR (O Pulo do Gato) ===
    mapa_bdr = {
        "AAPL": "AAPL34.SA",    "APPLE": "AAPL34.SA",
        "NVDA": "NVDC34.SA",    "NVIDIA": "NVDC34.SA",
        "MSFT": "MSFT34.SA",    "MICROSOFT": "MSFT34.SA",
        "TSLA": "TSLA34.SA",    "TESLA": "TSLA34.SA",
        "AMZN": "AMZO34.SA",    "AMAZON": "AMZO34.SA",
        "GOOGL": "GOGL34.SA",   "GOOGLE": "GOGL34.SA",
        "META": "M1TA34.SA",    "FACEBOOK": "M1TA34.SA",
        "NFLX": "NFLX34.SA",    "NETFLIX": "NFLX34.SA"
    }
    
    # 1. Verifica se está no mapa de tradução
    if s in mapa_bdr: return mapa_bdr[s]
    
    # 2. Se já tem sufixo correto
    if "." in s or "-" in s: return s 
    
    # 3. Detecção Cripto
    if s in [x.split("-")[0] for x in POOL_CRYPTO]: return f"{s}-USD"
    
    # 4. Padrão B3 (Ações terminam em número)
    if len(s) <= 6 and s[-1].isdigit(): return f"{s}.SA"
    
    # 5. Padrão B3 Genérico (Se não cair nas anteriores, tenta .SA)
    return f"{s}.SA"

def gerar_link_apple(ativo):
    return f"https://stocks.apple.com/symbol/{ativo}"

def pegar_dados_yahoo(symbol, verificar_volume=False):
    try:
        symbol_corrigido = normalizar_simbolo(symbol)
        df = yf.Ticker(symbol_corrigido).history(period="1mo", interval="15m")
        if df is None or df.empty: 
            print(f"⚠️ Yahoo vazio para: {symbol_corrigido} (Original: {symbol})")
            return None
        
        if verificar_volume and "USD" not in symbol_corrigido:
            vol_financeiro = df['Volume'].iloc[-1] * df['Close'].iloc[-1]
            if vol_financeiro < VOLUME_MINIMO_BRL:
                return None
        return df
    except Exception as e:
        print(f"Erro Yahoo ({symbol}): {e}")
        return None

# ==============================================================================
# 3. GOOGLE SHEETS
# ==============================================================================
def conectar_google():
    if not os.path.exists('creds.json'): return None
    try:
        gc = gspread.service_account(filename='creds.json')
        return gc.open(NOME_PLANILHA_GOOGLE)
    except: return None

def ler_carteira_vigilancia():
    sh = conectar_google()
    if sh:
        try: return [x.upper().strip() for x in sh.worksheet("Carteira").col_values(1) if x.strip()]
        except: return POOL_B3[:5]
    return POOL_B3[:5]

def registrar_sugestao(ativo, sinal, preco):
    sh = conectar_google()
    if sh:
        try:
            try: ws = sh.worksheet("Sugestoes")
            except: ws = sh.add_worksheet(title="Sugestoes", rows=1000, cols=5)
            ws.append_row([datetime.now().strftime('%d/%m/%Y'), ativo, sinal, preco])
            return True
        except: return False
    return False

def registrar_portfolio_real(ativo, tipo, preco):
    sh = conectar_google()
    if sh:
        try:
            try: ws = sh.worksheet("Portfolio")
            except: ws = sh.add_worksheet(title="Portfolio", rows=1000, cols=6)
            tipo_norm = "Compra" if tipo.upper() in ["COMPRA", "COMPRAR"] else "Venda"
            status = "🟢 Aberta" if tipo_norm == "Compra" else "🔴 Encerrada"
            ws.append_row([datetime.now().strftime('%d/%m %H:%M'), ativo, tipo_norm, preco, status])
            return True
        except: return False
    return False

# ==============================================================================
# 4. INTEGRAÇÃO IA
# ==============================================================================
def consultar_gemini(prompt):
    if not GEMINI_KEY: return "❌ Erro: Chave Gemini ausente."
    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            response = requests.post(url, headers=headers, json=data, timeout=25)
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
        except: continue
    return "TIMEOUT IA"

def validar_sinal_com_ia(ativo, sinal, df, tipo_ativo="B3"):
    preco = df['Close'].iloc[-1]
    
    if tipo_ativo == "CRYPTO":
        supertrend = df['SUPERT_7_3.0'].iloc[-1] if 'SUPERT_7_3.0' in df.columns else 0
        stoch_k = df['STOCHk_14_3_3'].iloc[-1] if 'STOCHk_14_3_3' in df.columns else 50
        prompt = (
            f"Atue como Crypto Trader. Analise {ativo} (15min). "
            f"Sinal: {sinal} (Supertrend + StochRSI). "
            f"Dados: Preço=${preco:.2f}, StochK={stoch_k:.1f}. "
            f"Veredito: 'APROVADO' ou 'REPROVADO'? Explique."
        )
    else:
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        vol = df['Volume'].iloc[-1]
        prompt = (
            f"Atue como Trader B3. Analise {ativo} (15min). "
            f"Sinal: {sinal} (MM9x21). Preço=R${preco:.2f}, RSI={rsi:.1f}, Volume={vol}. "
            f"Veredito: 'APROVADO' ou 'REPROVADO'? Explique."
        )

    resposta = consultar_gemini(prompt)
    if "APROVADO" in resposta.upper():
        motivo = resposta.split("APROVADO")[-1].strip().replace(".", "")[:50]
        return True, motivo
    else:
        return False, "IA Reprovou (Risco)"

# ==============================================================================
# 5. ESTRATÉGIAS
# ==============================================================================
def estrategia_b3(df):
    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
    if sma9 > 10000: sma9 /= 10000
    if sma21 > 10000: sma21 /= 10000

    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70): return "COMPRA"
    elif (sma9 < sma21) and (sma9_prev >= sma21_prev): return "VENDA"
    return None

def estrategia_crypto(df):
    supertrend = df.ta.supertrend(length=10, multiplier=3)
    if supertrend is None: return None
    st_dir_col = [c for c in supertrend.columns if "d_" in c][0]
    direction = supertrend[st_dir_col].iloc[-1]
    
    stoch = df.ta.stoch(k=14, d=3, smooth_k=3)
    if stoch is None: return None
    k_col = [c for c in stoch.columns if "STOCHk" in c][0]
    k_val = stoch[k_col].iloc[-1]
    
    if direction == 1 and k_val < 20: return "COMPRA"
    elif direction == -1: return "VENDA"
    return None

# ==============================================================================
# 6. SCANNER E ALOCAÇÃO
# ==============================================================================
def escanear_mercado_b3(apenas_fortes=False):
    oportunidades = []
    pool_limpo = [x.replace(".SA", "") for x in POOL_B3]
    for simbolo in pool_limpo:
        try:
            handler = TA_Handler(symbol=simbolo, screener="brazil", exchange="BMFBOVESPA", interval=Interval.INTERVAL_1_DAY)
            analise = handler.get_analysis()
            rec = analise.summary['RECOMMENDATION']
            should_add = False
            tag = ""
            if "STRONG_BUY" in rec:
                tag = "🔥"
                should_add = True
            elif "BUY" in rec and not apenas_fortes:
                tag = "✅"
                should_add = True
            if should_add:
                rsi = analise.indicators.get("RSI", 50)
                oportunidades.append({"texto": f"{simbolo} ({tag})", "rsi": rsi, "symbol": simbolo})
            time.sleep(0.05)
        except: continue
    return oportunidades

def gerar_alocacao(valor):
    raw_ops = escanear_mercado_b3(apenas_fortes=False)
    if not raw_ops: return "⚠️ Sem tendências B3 hoje."
    top_20 = sorted(raw_ops, key=lambda x: x['rsi'], reverse=True)[:20]
    lista_para_ia = [x['texto'] for x in top_20]
    prompt = f"Robo-Advisor B3. R$ {valor}. Ops: {', '.join(lista_para_ia)}. Monte carteira com 4 ativos."
    return consultar_gemini(prompt)

def analisar_ativo_tecnico(ativo):
    try:
        symbol_corrigido = normalizar_simbolo(ativo)
        is_crypto = "USD" in symbol_corrigido
        
        df = pegar_dados_yahoo(symbol_corrigido, verificar_volume=not is_crypto)
        if df is None: return f"❌ Erro ao baixar dados de {symbol_corrigido}. Verifique o ticker."
        
        if is_crypto:
            sinal = estrategia_crypto(df)
            indicadores = f"Supertrend/StochRSI. Sinal: {sinal if sinal else 'Neutro'}"
        else:
            sinal = estrategia_b3(df)
            indicadores = "MM9/MM21 + RSI."
            
        preco = df['Close'].iloc[-1]
        prompt = f"Analise {symbol_corrigido} (15min). {indicadores}. Preço {preco}. Veredito?"
        return consultar_gemini(prompt)
    except Exception as e: return f"Erro: {str(e)}"

# ==============================================================================
# 7. TELEGRAM
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Hunter B3", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("🍏 Watchlist", callback_data="CMD_MERCADO_APPLE"))
    markup.row(InlineKeyboardButton("🎩 Consultor", callback_data="CMD_CONSULTOR"))
    markup.row(InlineKeyboardButton("📂 Portfólio", callback_data="CMD_PORTFOLIO"))
    txt = "🤖 **QuantBot V58 - BDR Fix**\n\nAgora entendo 'AAPL' como 'AAPL34.SA'.\n\n`/analisar ATIVO`"
    bot.reply_to(message, txt, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['mercado'])
def comando_mercado(m):
    bot.send_chat_action(m.chat.id, 'typing')
    bot.reply_to(m, "🔎 Varrendo B3 + BDRs...")
    ops = escanear_mercado_b3(apenas_fortes=True)
    if not ops:
        bot.reply_to(m, "🤷‍♂️ Nada forte agora.")
        return
    top_ops = sorted(ops, key=lambda x: x['rsi'], reverse=True)[:8]
    markup = InlineKeyboardMarkup()
    row = []
    for item in top_ops:
        sym = item['symbol']
        # Corrige BDRs para o link da Apple funcionar
        # Apple as vezes prefere AAPL ao invés de AAPL34.SA, mas vamos testar com o .SA
        link = gerar_link_apple(f"{sym}.SA")
        row.append(InlineKeyboardButton(f" {sym}", url=link))
        if len(row) == 2:
            markup.row(row[0], row[1])
            row = []
    if row: markup.row(row[0])
    bot.send_message(m.chat.id, "📋 **Top Oportunidades:**", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['analisar'])
def analise(m):
    try:
        partes = m.text.split()
        if len(partes) < 2: return bot.reply_to(m, "Use: `/analisar ATIVO`")
        atv = partes[1].upper()
        bot.send_chat_action(m.chat.id, 'typing')
        msg = bot.reply_to(m, f"🔍 Analisando **{atv}**...", parse_mode="Markdown")
        res = analisar_ativo_tecnico(atv)
        bot.edit_message_text(chat_id=m.chat.id, message_id=msg.message_id, text=f"📊 **{atv}**\n\n{res}")
    except: pass

@bot.message_handler(commands=['comprar'])
def manual_buy(m):
    try:
        partes = m.text.split()
        atv = partes[1].upper()
        prc = partes[2].replace(",", ".")
        if registrar_portfolio_real(atv, "Compra", prc): bot.reply_to(m, "✅ Salvo!")
    except: bot.reply_to(m, "Erro.")

@bot.message_handler(commands=['vender'])
def manual_sell(m):
    try:
        partes = m.text.split()
        atv = partes[1].upper()
        prc = partes[2].replace(",", ".")
        if registrar_portfolio_real(atv, "Venda", prc): bot.reply_to(m, "🔻 Salvo!")
    except: bot.reply_to(m, "Erro.")

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.data.startswith("REAL|"):
        _, tipo, atv, prc = c.data.split("|")
        registrar_portfolio_real(atv, tipo, prc)
        bot.answer_callback_query(c.id, "Feito!")
        bot.send_message(c.message.chat.id, f"✅ {atv} salvo!")
    elif c.data == "CMD_CONSULTOR":
        msg = bot.send_message(c.message.chat.id, "💰 Valor?", reply_markup=ForceReply())
        bot.register_next_step_handler(msg, passo_consultor_valor)
    elif c.data == "CMD_MERCADO_APPLE": comando_mercado(c.message)
    elif c.data == "CMD_PORTFOLIO":
        sh = conectar_google()
        try: 
            dados = sh.worksheet("Portfolio").get_all_values()[-5:]
            txt = "📂 **Últimos:**\n"
            for row in dados: txt += f"{row[1]} | {row[2]} | {row[3]}\n"
            bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")
        except: bot.send_message(c.message.chat.id, "Vazio.")
    elif c.data == "CMD_HUNTER":
        bot.answer_callback_query(c.id, "Varrendo...")
        threading.Thread(target=enviar_relatorio_agendado).start()

def passo_consultor_valor(message):
    try:
        val = float(message.text.replace(",", ".").replace("R$", ""))
        bot.reply_to(message, "⏳ Calculando...")
        bot.reply_to(message, f"🎩 **Sugestão:**\n\n{gerar_alocacao(val)}")
    except: pass

# ==============================================================================
# 8. LOOP
# ==============================================================================
def loop():
    while True:
        try:
            lista = ler_carteira_vigilancia()
            for atv in lista:
                try:
                    atv_corr = normalizar_simbolo(atv) # Normaliza antes de tudo
                    is_crypto = "USD" in atv_corr
                    
                    df = pegar_dados_yahoo(atv_corr, verificar_volume=not is_crypto)
                    if df is None: continue
                    
                    preco_bruto = df['Close'].iloc[-1]
                    preco = corrigida = corrigir_escala(atv_corr, preco_bruto)
                    preco_str = formatar_preco(preco)

                    if is_crypto:
                        sinal = estrategia_crypto(df)
                        tipo_ativo = "CRYPTO"
                    else:
                        sinal = estrategia_b3(df)
                        tipo_ativo = "B3"
                    
                    if sinal:
                        chave = f"{atv_corr}_{sinal}_{datetime.now().day}_{datetime.now().hour}"
                        if chave not in ultimo_sinal_enviado:
                            aprovado, motivo = validar_sinal_com_ia(atv_corr, sinal, df, tipo_ativo)
                            if aprovado:
                                mk = InlineKeyboardMarkup()
                                mk.add(InlineKeyboardButton("✅ Real", callback_data=f"REAL|{sinal}|{atv}|{preco_str}"))
                                mk.add(InlineKeyboardButton(" App", url=gerar_link_apple(atv_corr)))
                                emoji = "🟢" if sinal == "COMPRA" else "🔴"
                                bot.send_message(CHAT_ID, f"{emoji} **SINAL {sinal}**: {atv_corr}\nPreço: {preco_str}\n\n🧠 {motivo}", reply_markup=mk, parse_mode="Markdown")
                                ultimo_sinal_enviado[chave] = True
                            else: ultimo_sinal_enviado[chave] = True
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

def executar_hunter_completo():
    sentimento = "Sem notícias."
    try:
        d = feedparser.parse("https://br.investing.com/rss/news.rss")
        manchetes = [entry.title for entry in d.entries[:3]]
        if manchetes: sentimento = consultar_gemini(f"Resuma: {manchetes}")
    except: pass
    raw = escanear_mercado_b3(apenas_fortes=True)
    return sentimento, [x['texto'] for x in raw]

def enviar_relatorio_agendado():
    humor, achados = executar_hunter_completo()
    msg = f"🗞️ **MERCADO:**\n{humor}\n\n🔥 **OPORTUNIDADES:**\n" + ("\n".join(achados) if achados else "Nada.")
    bot.send_message(CHAT_ID, msg)

def thread_agendamento():
    times = ["09:30", "13:00", "16:30"]
    for t in times: schedule.every().day.at(t).do(enviar_relatorio_agendado)
    while True: schedule.run_pending(); time.sleep(60)

if TOKEN:
    app = Flask(__name__)
    @app.route('/')
    def home(): return "QuantBot V58 (BDR Fix)"
    if __name__ == "__main__":
        threading.Thread(target=loop).start()
        threading.Thread(target=thread_agendamento).start()
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
        bot.infinity_polling()
