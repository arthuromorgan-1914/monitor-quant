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

print("--- INICIANDO QUANTBOT V55 (WATCHLIST MAKER) ---")
if not TOKEN: print("ERRO: TOKEN não encontrado.")

bot = telebot.TeleBot(TOKEN) if TOKEN else None
ultimo_sinal_enviado = {} 
VOLUME_MINIMO_BRL = 5_000_000 

PADRAO_VIGILANCIA = ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "WEGE3.SA", "PRIO3.SA"]

POOL_B3_TOTAL = [
    "PETR4", "VALE3", "PRIO3", "CSAN3", "RRRP3", "USIM5", "GGBR4", "GOAU4", "SUZB3", "KLBN11", "SLCE3", "SMTO3", "VBBR3", "RAIZ4",
    "ITUB4", "BBDC4", "BBAS3", "BPAC11", "SANB11", "B3SA3", "BBSE3", "PSSA3", "ITSA4", "CIEL3",
    "LREN3", "MGLU3", "ARZZ3", "SOMA3", "RDOR3", "RADL3", "NTCO3", "CRFB3", "ASAI3", "JBSS3", "BRFS3", "MRFG3", "BEEF3", "ABEV3",
    "WEGE3", "ELET3", "EQTL3", "CMIG4", "CPLE6", "EGIE3", "ENEV3", "TAEE11", "CPFE3", "SBSP3", "CSMG3",
    "CYRE3", "MRVE3", "EZTC3", "IGTI11", "MULT3", "ALOS3",
    "TOTS3", "VIVT3", "TIMS3",
    "RAIL3", "AZUL4", "GOLL4", "EMBR3", "RENT3", "MOVI3",
    "HAPV3", "FLRY3", "YDUQ3", "CVCB3"
]

# ==============================================================================
# 2. FUNÇÕES AUXILIARES
# ==============================================================================
def formatar_preco(valor):
    if valor < 50: return f"{valor:.4f}"
    return f"{valor:.2f}"

def corrigir_escala(symbol, preco):
    if preco > 10000: return preco / 10000
    return preco

def normalizar_simbolo(entrada):
    s = entrada.upper().strip()
    if "." in s: return s 
    if "-" in s: return s 
    criptos = ["BTC", "ETH", "SOL", "ADA", "XRP", "USDT"]
    if s in criptos: return f"{s}-USD"
    return f"{s}.SA"

def gerar_link_apple(ativo):
    return f"stocks://?symbol={ativo}"

def pegar_dados_yahoo(symbol, verificar_volume=False):
    try:
        symbol_corrigido = normalizar_simbolo(symbol)
        df = yf.Ticker(symbol_corrigido).history(period="1mo", interval="15m")
        if df is None or df.empty: return None
        
        if verificar_volume:
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
        except: return PADRAO_VIGILANCIA
    return PADRAO_VIGILANCIA

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

def validar_sinal_com_ia(ativo, sinal, df):
    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
    vol = df['Volume'].iloc[-1]
    preco = df['Close'].iloc[-1]
    contexto = "Cruzamento de Alta (9>21)" if sinal == "COMPRA" else "Cruzamento de Baixa (9<21)"
    prompt = (
        f"Atue como Trader Sênior. Analise {ativo} (15min). "
        f"Setup: {contexto}. Preço={preco:.2f}, RSI={rsi:.1f}, MM9={sma9:.2f}, MM21={sma21:.2f}. "
        f"PERGUNTA: Sinal confiável? "
        f"Responda EXATAMENTE: 'VEREDITO: APROVADO' ou 'VEREDITO: REPROVADO'. E explicação curta."
    )
    resposta = consultar_gemini(prompt)
    if "APROVADO" in resposta.upper():
        motivo = resposta.split("APROVADO")[-1].strip().replace(".", "")[:50]
        return True, motivo
    else:
        return False, "IA Reprovou"

# ==============================================================================
# 5. SCANNER DE MERCADO
# ==============================================================================
def escanear_mercado_b3(apenas_fortes=False):
    oportunidades = []
    pool_limpo = list(set(POOL_B3_TOTAL))
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
                fechamento = analise.indicators.get("close", 0)
                oportunidades.append({
                    "texto": f"{simbolo} ({tag})",
                    "rsi": rsi,
                    "symbol": simbolo,
                    "preco": fechamento
                })
            time.sleep(0.05)
        except: continue
    return oportunidades

def gerar_alocacao(valor):
    raw_ops = escanear_mercado_b3(apenas_fortes=False)
    if not raw_ops: return "⚠️ O Scanner não achou tendências."
    top_20 = sorted(raw_ops, key=lambda x: x['rsi'], reverse=True)[:20]
    lista_para_ia = [x['texto'] for x in top_20]
    prompt = (
        f"Atue como Robo-Advisor B3. Investimento: R$ {valor}. "
        f"Oportunidades: {', '.join(lista_para_ia)}. "
        f"Monte uma carteira com 4 ativos. Responda com lista."
    )
    return consultar_gemini(prompt)

def analisar_ativo_tecnico(ativo):
    try:
        symbol_corrigido = normalizar_simbolo(ativo)
        df = pegar_dados_yahoo(symbol_corrigido, verificar_volume=True)
        if df is None: return f"❌ {ativo}: Volume baixo ou sem dados."
        preco_bruto = df['Close'].iloc[-1]
        preco = corrigir_escala(symbol_corrigido, preco_bruto)
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        if sma9 > 10000: sma9 /= 10000
        if sma21 > 10000: sma21 /= 10000
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        prompt = (
            f"Analise {symbol_corrigido}. Preço: {preco:.2f} | RSI: {rsi:.1f} | "
            f"M9/M21: {sma9:.2f}/{sma21:.2f} ({tendencia}). "
            "Dê veredito: Compra/Venda?"
        )
        return consultar_gemini(prompt)
    except Exception as e: return f"Erro: {str(e)}"

# ==============================================================================
# 6. TELEGRAM HANDLERS
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Hunter B3", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("🍏 App Watchlist", callback_data="CMD_MERCADO_APPLE")) # Atalho novo
    markup.row(InlineKeyboardButton("🎩 Consultor", callback_data="CMD_CONSULTOR"))
    markup.row(InlineKeyboardButton("📂 Portfólio", callback_data="CMD_PORTFOLIO"))
    txt = "🤖 **QuantBot V55**\n\n`/mercado` -> Lista p/ adicionar no iOS.\n`/analisar ATIVO`"
    bot.reply_to(message, txt, reply_markup=markup, parse_mode="Markdown")

# === NOVO COMANDO /mercado ===
@bot.message_handler(commands=['mercado'])
def comando_mercado(m):
    bot.send_chat_action(m.chat.id, 'typing')
    bot.reply_to(m, "🔎 Varrendo a Bolsa para montar sua Watchlist... aguarde.")
    
    # Busca apenas os FORTES (Strong Buy)
    ops = escanear_mercado_b3(apenas_fortes=True)
    
    if not ops:
        bot.reply_to(m, "🤷‍♂️ Mercado morno. Nenhuma 'Strong Buy' agora.")
        return

    # Pega os Top 8 (para não encher demais a tela)
    top_ops = sorted(ops, key=lambda x: x['rsi'], reverse=True)[:8]
    
    markup = InlineKeyboardMarkup()
    # Cria botões em pares (2 por linha)
    row = []
    for item in top_ops:
        sym = item['symbol'] # Ex: PETR4
        sym_apple = f"{sym}.SA" # Formato Apple
        link = gerar_link_apple(sym_apple)
        btn = InlineKeyboardButton(f" {sym}", url=link)
        row.append(btn)
        
        if len(row) == 2:
            markup.row(row[0], row[1])
            row = []
            
    if row: markup.row(row[0]) # Adiciona o que sobrou
    
    txt = "📋 **Top Oportunidades B3 (Watchlist Maker)**\n\nClique para abrir no app Bolsa e adicionar:"
    bot.send_message(m.chat.id, txt, reply_markup=markup, parse_mode="Markdown")

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
        if registrar_portfolio_real(atv, "Compra", prc): bot.reply_to(m, "✅ Registrado!")
    except: bot.reply_to(m, "Erro.")

@bot.message_handler(commands=['vender'])
def manual_sell(m):
    try:
        partes = m.text.split()
        atv = partes[1].upper()
        prc = partes[2].replace(",", ".")
        if registrar_portfolio_real(atv, "Venda", prc): bot.reply_to(m, "🔻 Registrado!")
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
        
    elif c.data == "CMD_MERCADO_APPLE":
        comando_mercado(c.message) # Chama a função do comando /mercado
        
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
# 7. LOOP MONITORAMENTO
# ==============================================================================
def loop():
    while True:
        try:
            lista = ler_carteira_vigilancia()
            for atv in lista:
                try:
                    df = pegar_dados_yahoo(atv, verificar_volume=True)
                    if df is None: continue
                    
                    preco_bruto = df['Close'].iloc[-1]
                    atv_corr = normalizar_simbolo(atv)
                    preco = corrigir_escala(atv_corr, preco_bruto)

                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    if sma9 > 10000: sma9 /= 10000
                    if sma21 > 10000: sma21 /= 10000
                    
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    
                    sinal = None
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev): sinal = "COMPRA"
                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev): sinal = "VENDA"
                    
                    if sinal:
                        chave = f"{atv}_{sinal}_{datetime.now().day}_{datetime.now().hour}"
                        if chave not in ultimo_sinal_enviado:
                            ok, motivo = validar_sinal_com_ia(atv_corr, sinal, df)
                            if ok:
                                mk = InlineKeyboardMarkup()
                                mk.add(InlineKeyboardButton("✅ Real", callback_data=f"REAL|{sinal}|{atv}|{formatar_preco(preco)}"))
                                mk.add(InlineKeyboardButton(" App", url=gerar_link_apple(atv_corr)))
                                bot.send_message(CHAT_ID, f"🚨 {sinal} **{atv}**\nPreço: {formatar_preco(preco)}\n\n🧠 {motivo}", reply_markup=mk, parse_mode="Markdown")
                                ultimo_sinal_enviado[chave] = True
                            else: ultimo_sinal_enviado[chave] = True
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

# ==============================================================================
# 8. HUNTER
# ==============================================================================
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
    def home(): return "QuantBot V55 (Watchlist)"
    if __name__ == "__main__":
        threading.Thread(target=loop).start()
        threading.Thread(target=thread_agendamento).start()
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
        bot.infinity_polling()