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
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"
CHAT_ID = "1116977306"
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

# --- 🛑 COLE SUA CHAVE NOVA AQUI ---
GEMINI_KEY = "AIzaSyAeFpuANuD23TPbJO4l431bMjkOwCu8sRE"

bot = telebot.TeleBot(TOKEN)

# CONTROLE DE SINAIS (Memória RAM)
ultimo_sinal_enviado = {} 

# LISTA UNIVERSAL
ALVOS_CAÇADOR = [
    {"symbol": "PETR4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PETR4.SA"},
    {"symbol": "VALE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "VALE3.SA"},
    {"symbol": "WEGE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "WEGE3.SA"},
    {"symbol": "PRIO3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PRIO3.SA"},
    {"symbol": "ITUB4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "ITUB4.SA"},
    {"symbol": "BTCUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "BTC-USD"},
    {"symbol": "ETHUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "ETH-USD"},
    {"symbol": "SOLUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "SOL-USD"},
    {"symbol": "NVDA", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "NVDA"},
]

# ==============================================================================
# 2. FUNÇÕES AUXILIARES
# ==============================================================================
def formatar_preco(valor):
    if valor < 50: return f"{valor:.4f}"
    return f"{valor:.2f}"

def pegar_dados_yahoo(symbol):
    try:
        df = yf.Ticker(symbol).history(period="1mo", interval="15m")
        if df is None or df.empty: return None
        return df
    except: return None

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
        except: return []
    return []

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
# 4. INTEGRAÇÃO IA (MODO DEBUG DETALHADO) 🕵️‍♂️
# ==============================================================================
def consultar_gemini(prompt):
    # Ordem alterada: Prioridade para o 2.0 que vimos funcionar no JSON
    modelos = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash-latest"]
    
    erros_log = []
    
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                # Salva o erro real (JSON do Google)
                erros_log.append(f"{modelo}: {response.text}")
                continue
        except Exception as e:
            erros_log.append(f"{modelo}: {str(e)}")
            continue
            
    # Se falhar tudo, retorna o relatório de erro para a gente consertar
    erro_formatado = "\n".join(erros_log)
    return f"⚠️ FALHA IA:\n{erro_formatado[:3000]}"

def buscar_oportunidades_mercado():
    candidatas = []
    pool = ["PETR4", "VALE3", "ITUB4", "BBAS3", "WEGE3", "PRIO3", "RENT3", "GGBR4", "CMIG4", "ELET3"]
    for simbolo in pool:
        try:
            handler = TA_Handler(symbol=simbolo, screener="brazil", exchange="BMFBOVESPA", interval=Interval.INTERVAL_1_DAY)
            analise = handler.get_analysis()
            if "BUY" in analise.summary['RECOMMENDATION']:
                candidatas.append(f"{simbolo} (R$ {analise.indicators.get('close',0):.2f})")
        except: continue
    return candidatas

def gerar_alocacao(valor):
    ops = buscar_oportunidades_mercado()
    if not ops: return "⚠️ O Scanner não achou tendências de alta claras no Top 10 hoje."
    
    # Prompt ajustado para fazer a conta
    prompt = (
        f"Atue como Robo-Advisor Matemático. O cliente tem EXATAMENTE R$ {valor} para investir. "
        f"As melhores oportunidades técnicas hoje são: {', '.join(ops)}. "
        f"TAREFA: "
        f"1) Escolha 3 ativos dessa lista. "
        f"2) Divida o valor de R$ {valor} entre eles (ex: R$ X em PETR4, R$ Y em VALE3). "
        f"3) Explique o porquê da alocação. "
        f"Responda com uma lista clara e valores em Reais."
    )
    return consultar_gemini(prompt)

def analisar_ativo_tecnico(ativo):
    try:
        df = pegar_dados_yahoo(ativo)
        if df is None: return "Erro ao baixar dados do Yahoo Finance."
        
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        preco = df['Close'].iloc[-1]
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        
        prompt = (
            f"Analise o ativo {ativo}. Preço Atual: {preco:.2f} | RSI: {rsi:.1f} | "
            f"Média Curta (9): {sma9:.2f} | Média Longa (21): {sma21:.2f}. "
            f"Tendência Técnica: {tendencia}. "
            "Faça uma análise rápida de 3 linhas sobre se é hora de comprar ou vender."
        )
        return consultar_gemini(prompt)
    except Exception as e: return f"Erro script: {str(e)}"

# ==============================================================================
# 5. TELEGRAM HANDLERS
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Hunter", callback_data="CMD_HUNTER"), InlineKeyboardButton("🎩 Consultor", callback_data="CMD_CONSULTOR"))
    markup.row(InlineKeyboardButton("📂 Portfólio", callback_data="CMD_PORTFOLIO"))
    
    txt = (
        "🤖 **QuantBot V42 - Debug**\n\n"
        "**Comandos Manuais:**\n"
        "`/comprar ATIVO PRECO`\n"
        "`/vender ATIVO PRECO`\n"
        "`/analisar ATIVO` (Análise IA)\n\n"
    )
    bot.reply_to(message, txt, reply_markup=markup, parse_mode="Markdown")

# COMANDO ANALISAR (ESTAVA FALTANDO OU FALHANDO?)
@bot.message_handler(commands=['analisar'])
def analise(m):
    try:
        # Formato: /analisar PETR4
        partes = m.text.split()
        if len(partes) < 2:
            bot.reply_to(m, "⚠️ Use: `/analisar ATIVO` (Ex: `/analisar PETR4`)")
            return
            
        ativo = partes[1].upper()
        bot.send_chat_action(m.chat.id, 'typing') # Mostra "digitando..."
        res = analisar_ativo_tecnico(ativo)
        bot.reply_to(m, f"📊 **Análise {ativo}:**\n\n{res}", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(m, f"❌ Erro comando: {str(e)}")

@bot.message_handler(commands=['comprar'])
def manual_buy(m):
    try:
        partes = m.text.split()
        ativo = partes[1].upper()
        preco = partes[2].replace(",", ".")
        if registrar_portfolio_real(ativo, "Compra", preco):
            bot.reply_to(m, f"✅ Compra de **{ativo}** registrada!", parse_mode="Markdown")
        else: bot.reply_to(m, "❌ Erro planilha.")
    except: bot.reply_to(m, "⚠️ Use: `/comprar ATIVO PREÇO`")

@bot.message_handler(commands=['vender'])
def manual_sell(m):
    try:
        partes = m.text.split()
        ativo = partes[1].upper()
        preco = partes[2].replace(",", ".")
        if registrar_portfolio_real(ativo, "Venda", preco):
            bot.reply_to(m, f"🔻 Venda de **{ativo}** registrada!", parse_mode="Markdown")
        else: bot.reply_to(m, "❌ Erro planilha.")
    except: bot.reply_to(m, "⚠️ Use: `/vender ATIVO PREÇO`")

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    # AÇÕES
    if c.data.startswith("REAL|"):
        _, tipo, ativo, preco = c.data.split("|")
        if registrar_portfolio_real(ativo, tipo, preco):
            emoji = "✅" if tipo == "COMPRA" else "🔻"
            bot.send_message(c.message.chat.id, f"{emoji} {ativo} registrado!")
            bot.answer_callback_query(c.id, "Feito!")

    elif c.data.startswith("SUGEST|"):
        _, tipo, ativo, preco = c.data.split("|")
        registrar_sugestao(ativo, tipo, preco)
        bot.answer_callback_query(c.id, "Arquivado.")
        bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=f"👀 Sugestão arquivada.")

    # MENU
    elif c.data == "CMD_CONSULTOR":
        msg = bot.send_message(c.message.chat.id, "💰 Qual valor total para investir? (Ex: 5000)", reply_markup=ForceReply())
        bot.register_next_step_handler(msg, lambda m: bot.reply_to(m, gerar_alocacao(float(m.text.replace(",", ".")))))
    
    elif c.data == "CMD_PORTFOLIO":
        sh = conectar_google()
        try: 
            dados = sh.worksheet("Portfolio").get_all_values()[-5:]
            txt = "📂 **Últimos Registros:**\n"
            for row in dados: txt += f"{row[1]} | {row[2]} | {row[3]}\n"
            bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")
        except: bot.send_message(c.message.chat.id, "Portfólio vazio.")

    elif c.data == "CMD_HUNTER":
        bot.answer_callback_query(c.id, "Analisando...")
        threading.Thread(target=enviar_relatorio_agendado).start()

# ==============================================================================
# 6. LOOP DE MONITORAMENTO
# ==============================================================================
def loop():
    while True:
        try:
            lista_vigilancia = ler_carteira_vigilancia()
            for atv in lista_vigilancia:
                try:
                    df = pegar_dados_yahoo(atv)
                    if df is None: continue
                    
                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    preco = df['Close'].iloc[-1]
                    preco_str = formatar_preco(preco)

                    sinal = None
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70):
                        sinal = "COMPRA"
                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev):
                        sinal = "VENDA"
                    
                    if sinal:
                        chave_memoria = f"{atv}_{sinal}_{datetime.now().day}"
                        if chave_memoria not in ultimo_sinal_enviado:
                            markup = InlineKeyboardMarkup()
                            if sinal == "COMPRA":
                                btn_real = InlineKeyboardButton(f"✅ Comprei", callback_data=f"REAL|COMPRA|{atv}|{preco_str}")
                                emoji = "🟢"
                            else:
                                btn_real = InlineKeyboardButton(f"🔻 Vendi", callback_data=f"REAL|VENDA|{atv}|{preco_str}")
                                emoji = "🔴"
                            
                            btn_sugest = InlineKeyboardButton(f"👀 Ciente", callback_data=f"SUGEST|{sinal}|{atv}|{preco_str}")
                            markup.add(btn_real, btn_sugest)
                            bot.send_message(CHAT_ID, f"{emoji} **SINAL {sinal}**: {atv}\nPreço: {preco_str}", reply_markup=markup)
                            ultimo_sinal_enviado[chave_memoria] = True
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

# FUNÇÃO HUNTER COMPLETA
def executar_hunter_completo():
    sentimento = "Sem notícias."
    try:
        manchetes = []
        d = feedparser.parse("https://br.investing.com/rss/news.rss")
        for entry in d.entries[:4]: manchetes.append(entry.title)
        if manchetes:
            prompt = f"Resuma o sentimento do mercado em 2 linhas com base em: {manchetes}."
            sentimento = consultar_gemini(prompt)
    except: pass

    achados = []
    for alvo in ALVOS_CAÇADOR:
        try:
            h = TA_Handler(symbol=alvo['symbol'], screener=alvo['screener'], exchange=alvo['exchange'], interval=Interval.INTERVAL_1_DAY)
            if "STRONG" in h.get_analysis().summary['RECOMMENDATION']: achados.append(f"🔥 {alvo['symbol']}")
        except: pass
    return sentimento, achados

def enviar_relatorio_agendado():
    humor, achados = executar_hunter_completo()
    txt_sinais = "\n".join(achados) if achados else "🚫 Sem sinais fortes."
    msg = f"🗞️ **NOTÍCIAS:**\n{humor}\n\n🏹 **HUNTER:**\n{txt_sinais}"
    bot.send_message(CHAT_ID, msg)

def thread_agendamento():
    times = ["09:30", "13:00", "16:30"]
    for t in times: schedule.every().day.at(t).do(enviar_relatorio_agendado)
    while True: schedule.run_pending(); time.sleep(60)

app = Flask(__name__)
@app.route('/')
def home(): return "QuantBot V42 (Final Debug)"

if __name__ == "__main__":
    threading.Thread(target=loop).start()
    threading.Thread(target=thread_agendamento).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()