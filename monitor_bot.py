import os
import shutil
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import time
import threading
import random 
from flask import Flask
from datetime import datetime
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

# --- SUA CHAVE (Verifique se tirou a restrição no Google Cloud!) ---
GEMINI_KEY = "AIzaSyDLyUB_4G8ITkpF7a7MC6wRHz4AzJe25rY"

bot = telebot.TeleBot(TOKEN)

# LISTA DE CAÇA
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
    {"symbol": "TSLA", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "TSLA"},
    {"symbol": "AAPL", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "AAPL"},
]

# ==============================================================================
# 2. FUNÇÃO DE DADOS (YAHOO)
# ==============================================================================
def pegar_dados_yahoo(symbol):
    try:
        df = yf.Ticker(symbol).history(period="1mo", interval="15m")
        if df is None or df.empty: return None
        return df
    except Exception as e:
        print(f"⚠️ Erro Yahoo ({symbol}): {e}")
        return None

# ==============================================================================
# 3. FUNÇÕES DO SHEETS
# ==============================================================================
def conectar_google(verbose=False):
    if not os.path.exists('creds.json'): return None, "❌ Erro: 'creds.json' sumiu."
    try:
        gc = gspread.service_account(filename='creds.json')
        sh = gc.open(NOME_PLANILHA_GOOGLE)
        return sh, "Sucesso"
    except Exception as e: return None, f"❌ Erro Google: {str(e)}"

def ler_carteira():
    sh, _ = conectar_google()
    if sh:
        try: return [x.upper().strip() for x in sh.worksheet("Carteira").col_values(1) if x.strip()]
        except: return []
    return []

def adicionar_ativo(novo_ativo):
    sh, msg = conectar_google(verbose=True)
    if sh:
        try:
            ws = sh.worksheet("Carteira")
            if novo_ativo.upper() in [x.strip().upper() for x in ws.col_values(1)]:
                return "⚠️ Já existe."
            ws.append_row([novo_ativo.upper()])
            return "✅ Sucesso! Adicionado."
        except Exception as e: return f"❌ Erro Carteira: {str(e)}"
    else: return msg

def registrar_trade(ativo, preco, tipo="Compra"):
    sh, _ = conectar_google()
    if sh:
        try:
            status = "Aberta" if tipo == "Compra" else "Encerrada"
            sh.sheet1.append_row([datetime.now().strftime('%d/%m %H:%M'), ativo, tipo, preco, "", "", status])
            return True
        except: return False
    return False

def verificar_ultimo_status(ativo):
    sh, _ = conectar_google()
    if sh:
        try:
            dados = sh.sheet1.get_all_values()
            for linha in reversed(dados):
                if len(linha) > 2 and linha[1].strip().upper() == ativo.strip().upper():
                    return linha[2].strip()
        except: return None
    return None

# ==============================================================================
# 4. INTEGRAÇÃO IA (AJUSTADA PARA SEU JSON) 💎
# ==============================================================================
def consultar_gemini(prompt):
    # Esses nomes vieram do seu JSON. Um deles TEM que funcionar.
    modelos = [
        "gemini-2.0-flash",       # Estável e rápido
        "gemini-flash-latest",    # Genérico (aponta pro 1.5 ou 2.0)
        "gemini-pro"              # Clássico
    ]
    
    ultimo_erro = ""
    
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                # Se der 403, é bloqueio de chave. Se der 404, é nome errado.
                ultimo_erro = f"{modelo} deu erro {response.status_code}"
                continue
        except Exception as e:
            ultimo_erro = str(e)
            continue
            
    return f"❌ Falha IA ({ultimo_erro}). Verifique se a chave tem restrição de API no Google Cloud."

# ==============================================================================
# 5. ANÁLISE TÉCNICA
# ==============================================================================
def analisar_ativo_tecnico(ativo):
    try:
        df = pegar_dados_yahoo(ativo)
        if df is None or len(df) < 50: return "❌ Erro Yahoo Finance."
        
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        preco = df['Close'].iloc[-1]
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        
        prompt = (
            f"Analise o ativo {ativo}. Preço: {preco:.2f} | RSI: {rsi:.1f} | "
            f"Média 9: {sma9:.2f} | Média 21: {sma21:.2f}. Tendência: {tendencia}. "
            "Resuma em 3 linhas: Cenário técnico e recomendação. Use emojis."
        )
        return consultar_gemini(prompt)
    except Exception as e:
        return f"Erro script: {str(e)}"

# ==============================================================================
# 6. FUNÇÃO HUNTER
# ==============================================================================
def executar_hunter():
    relatorio = []
    novos = 0
    
    # Scanner
    for alvo in ALVOS_CAÇADOR:
        try:
            handler = TA_Handler(symbol=alvo['symbol'], screener=alvo['screener'], exchange=alvo['exchange'], interval=Interval.INTERVAL_1_DAY)
            if "STRONG_BUY" in handler.get_analysis().summary['RECOMMENDATION']:
                res = adicionar_ativo(alvo['nome_sheet'])
                if "Sucesso" in res:
                    relatorio.append(f"✅ {alvo['symbol']} (Novo!)")
                    novos += 1
                elif "Já existe" in res:
                    relatorio.append(f"⚠️ {alvo['symbol']} (Já vigiando)")
            time.sleep(random.uniform(2, 5))
        except: time.sleep(5)
            
    # Notícias
    try:
        manchetes = []
        try:
            d = feedparser.parse("https://br.investing.com/rss/news.rss")
            for entry in d.entries[:3]: manchetes.append(f"{entry.title}")
        except: pass
        
        if not manchetes: sentimento = "Sem notícias."
        else:
            sentimento = consultar_gemini(f"Resuma o sentimento destas notícias em 2 linhas: {manchetes}")
    except Exception as e:
        sentimento = f"Erro IA: {str(e)}"

    return relatorio, sentimento, novos

# ==============================================================================
# 7. ROTINAS
# ==============================================================================
def tarefa_hunter_background(chat_id):
    achados, humor, n = executar_hunter()
    txt = f"📋 RELATÓRIO\n\n🌡️ {humor}\n\n" + ("\n".join(achados) if achados else "🚫 Sem 'Strong Buy'.")
    bot.send_message(chat_id, txt)

def enviar_relatorio_agendado(): tarefa_hunter_background(CHAT_ID)

def thread_agendamento():
    times = ["07:00", "10:15", "13:00", "16:00", "18:30"]
    for t in times: schedule.every().day.at(t).do(enviar_relatorio_agendado)
    while True: schedule.run_pending(); time.sleep(60)

# ==============================================================================
# 8. BOT COMMANDS
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu(m):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("🔫 Hunter", callback_data="CMD_HUNTER"), InlineKeyboardButton("📋 Lista", callback_data="CMD_LISTA"))
    bot.reply_to(m, "🤖 **QuantBot V29**\nUse: /add, /del, /analisar", reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: True)
def callback(c):
    if c.data == "CMD_HUNTER":
        bot.answer_callback_query(c.id, "Caçando...")
        threading.Thread(target=tarefa_hunter_background, args=(CHAT_ID,)).start()
    elif c.data == "CMD_LISTA":
        bot.send_message(CHAT_ID, f"📋 **Carteira:**\n" + "\n".join(ler_carteira()), parse_mode="Markdown")
    elif "COMPRA|" in c.data or "VENDA|" in c.data:
        op, atv, prc = c.data.split("|")
        registrar_trade(atv, prc, op)
        bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id, text=f"✅ {op} Registrada!")

@bot.message_handler(commands=['add'])
def add(m):
    try: bot.reply_to(m, adicionar_ativo(m.text.split()[1].upper()))
    except: bot.reply_to(m, "Use: /add ATIVO")

@bot.message_handler(commands=['del'])
def delete(m):
    try:
        atv = m.text.split()[1].upper()
        sh, _ = conectar_google()
        sh.worksheet("Carteira").delete_rows(sh.worksheet("Carteira").find(atv).row)
        bot.reply_to(m, f"🗑️ {atv} deletado!")
    except: bot.reply_to(m, "Erro ao deletar.")

@bot.message_handler(commands=['analisar'])
def analise(m):
    try:
        atv = m.text.split()[1].upper()
        msg = bot.reply_to(m, f"🔍 Analisando {atv}...")
        res = analisar_ativo_tecnico(atv)
        bot.edit_message_text(chat_id=m.chat.id, message_id=msg.message_id, text=f"📊 **{atv}**\n{res}", parse_mode="Markdown")
    except: bot.reply_to(m, "Use: /analisar ATIVO")

# ==============================================================================
# 9. START
# ==============================================================================
def loop():
    while True:
        try:
            for atv in ler_carteira():
                try:
                    df = pegar_dados_yahoo(atv)
                    if df is None: continue
                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    preco = df['Close'].iloc[-1]
                    last = verificar_ultimo_status(atv)

                    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70) and (last != "Compra"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"Comprar @ {preco:.2f}", callback_data=f"COMPRA|{atv}|{preco:.2f}"))
                        bot.send_message(CHAT_ID, f"🟢 **SINAL COMPRA**: {atv}\nPreço: {preco:.2f}", reply_markup=markup)
                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev) and (last != "Venda"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"Vender @ {preco:.2f}", callback_data=f"VENDA|{atv}|{preco:.2f}"))
                        bot.send_message(CHAT_ID, f"🔴 **SINAL VENDA**: {atv}\nPreço: {preco:.2f}", reply_markup=markup)
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

app = Flask(__name__)
@app.route('/')
def home(): return "QuantBot V29 (Permission Fix)"

if __name__ == "__main__":
    threading.Thread(target=loop).start()
    threading.Thread(target=thread_agendamento).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()