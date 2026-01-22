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
from flask import Flask
from datetime import datetime
from pathlib import Path
import feedparser
from tradingview_ta import TA_Handler, Interval, Exchange
import ccxt
import requests  # <--- NOVA IMPORTAÇÃO ESSENCIAL

# ==============================================================================
# 1. CONFIGURAÇÕES
# ==============================================================================
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"
CHAT_ID = "1116977306"
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

# Chave do Gemini (Pega do Render)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

bot = telebot.TeleBot(TOKEN)

# LISTA DE CAÇA
ALVOS_CAÇADOR = [
    # BRASIL (B3)
    {"symbol": "PETR4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PETR4.SA"},
    {"symbol": "VALE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "VALE3.SA"},
    {"symbol": "WEGE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "WEGE3.SA"},
    {"symbol": "PRIO3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PRIO3.SA"},
    {"symbol": "ITUB4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "ITUB4.SA"},
    # CRIPTO (Binance - USDT)
    {"symbol": "BTCUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "BTC-USD"},
    {"symbol": "ETHUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "ETH-USD"},
    {"symbol": "SOLUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "SOL-USD"},
    {"symbol": "DOGEUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "DOGE-USD"},
    {"symbol": "SHIBUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "SHIB-USD"},
    {"symbol": "XRPUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "XRP-USD"},
    # EUA
    {"symbol": "NVDA", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "NVDA"},
    {"symbol": "TSLA", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "TSLA"},
    {"symbol": "AAPL", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "AAPL"},
]

# ==============================================================================
# 2. FUNÇÕES DE DADOS
# ==============================================================================
def pegar_dados_binance(symbol):
    symbol_binance = symbol.replace("-", "/").replace("USD", "USDT")
    exchange = ccxt.binance()
    try:
        candles = exchange.fetch_ohlcv(symbol_binance, timeframe='15m', limit=50)
        df = pd.DataFrame(candles, columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Time'] = pd.to_datetime(df['Time'], unit='ms')
        df['Close'] = df['Close'].astype(float)
        return df
    except Exception as e:
        print(f"⚠️ Erro Binance ({symbol}): {e}")
        return None

def pegar_dados_yahoo(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")
        return df
    except: return None

# ==============================================================================
# 3. FUNÇÕES DO SHEETS
# ==============================================================================
def conectar_google():
    try:
        gc = gspread.service_account(filename='creds.json')
        sh = gc.open(NOME_PLANILHA_GOOGLE)
        return sh
    except Exception as e:
        print(f"❌ Erro Google: {e}")
        return None

def ler_carteira():
    sh = conectar_google()
    if sh:
        try:
            return [x.upper().strip() for x in sh.worksheet("Carteira").col_values(1) if x.strip()]
        except: return []
    return []

def adicionar_ativo(novo_ativo):
    sh = conectar_google()
    if sh:
        try:
            ws = sh.worksheet("Carteira")
            if novo_ativo.upper() in [x.strip().upper() for x in ws.col_values(1)]:
                return "Já existe"
            ws.append_row([novo_ativo.upper()])
            return "Sucesso"
        except: return "Erro"
    return "Erro Conexão"

def registrar_trade(ativo, preco):
    sh = conectar_google()
    if sh:
        try:
            sh.sheet1.append_row([datetime.now().strftime('%d/%m %H:%M'), ativo, "Compra", preco, "", "", "Aberta"])
            return True
        except: return False
    return False

# ==============================================================================
# 4. FUNÇÃO DO CAÇADOR (HUNTER) - MODO DIRETO (REST API)
# ==============================================================================
def executar_hunter():
    relatorio = []
    novos = 0
    
    # 1. Scanner Técnico
    for alvo in ALVOS_CAÇADOR:
        try:
            handler = TA_Handler(symbol=alvo['symbol'], screener=alvo['screener'], exchange=alvo['exchange'], interval=Interval.INTERVAL_1_DAY)
            rec = handler.get_analysis().summary['RECOMMENDATION']
            if "STRONG_BUY" in rec:
                res = adicionar_ativo(alvo['nome_sheet'])
                if res == "Sucesso":
                    relatorio.append(f"✅ {alvo['symbol']} (Novo!)")
                    novos += 1
                elif res == "Já existe":
                    relatorio.append(f"⚠️ {alvo['symbol']} (Já vigiando)")
        except Exception as e:
            relatorio.append(f"Erro {alvo['symbol']}: {e}")
            
    # 2. Notícias (Gemini VIA API DIRETA)
    sentimento = "Iniciando..."
    if not GEMINI_KEY:
        sentimento = "Erro: Chave GEMINI não configurada."
    else:
        try:
            manchetes = []
            feeds = ["https://www.infomoney.com.br/feed/", "https://br.investing.com/rss/news.rss"]
            for url in feeds:
                d = feedparser.parse(url)
                if d.entries:
                    for entry in d.entries[:2]: manchetes.append(f"- {entry.title}")
            
            if not manchetes:
                sentimento = "Aviso: Sem notícias no RSS."
            else:
                # Atualizado para a versão vigente em 2026
                url_google = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_KEY}"
                prompt = f"Resuma o sentimento do mercado em 1 frase curta baseada nestas manchetes: {manchetes}"
                payload = {"contents": [{"parts": [{"text": prompt}]}]}
                
                resp = requests.post(url_google, json=payload, timeout=10)
                
                if resp.status_code == 200:
                    sentimento = resp.json()['candidates'][0]['content']['parts'][0]['text']
                else:
                    sentimento = f"Erro Google ({resp.status_code}): {resp.text[:100]}"
                    
        except Exception as e:
            sentimento = f"Erro Técnico: {str(e)}"

    return relatorio, sentimento, novos

# ==============================================================================
# 5. BOT TELEGRAM
# ==============================================================================
@bot.message_handler(commands=['start', 'menu', 'status'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔫 Caçar Oportunidades (Hunter)", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("📋 Ver Lista de Vigília", callback_data="CMD_LISTA"))
    bot.reply_to(message, "🤖 **Painel Quant**\nO que deseja?", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    if call.data.startswith("COMPRA|"):
        _, ativo, preco = call.data.split("|")
        if registrar_trade(ativo, preco):
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{call.message.text}\n\n✅ **REGISTRADO!**")
    
    elif call.data == "CMD_HUNTER":
        bot.answer_callback_query(call.id, "Buscando...")
        bot.send_message(CHAT_ID, "🕵️ **Analisando Mercado...**")
        achados, humor, n = executar_hunter()
        txt = f"📋 **RELATÓRIO HUNTER**\n\n🌡️ *Clima:* {humor}\n\n"
        txt += "\n".join(achados) if achados else "🚫 Nada em 'Compra Forte'."
        txt += f"\n\n🔢 Novos: {n}"
        bot.send_message(CHAT_ID, txt, parse_mode="Markdown")
        
    elif call.data == "CMD_LISTA":
        lista = ler_carteira()
        txt = f"📋 **Vigiando {len(lista)}:**\n" + "\n".join([f"`{x}`" for x in lista])
        bot.send_message(CHAT_ID, txt, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_manual(m):
    try: bot.reply_to(m, f"Resultado: {adicionar_ativo(m.text.split()[1].upper())}")
    except: bot.reply_to(m, "Use: /add ATIVO")

# ==============================================================================
# 6. LOOP MONITOR
# ==============================================================================
def loop_monitoramento():
    while True:
        try:
            print(f"--- Ciclo {datetime.now().strftime('%H:%M')} ---")
            carteira = ler_carteira()
            cache = Path.home() / ".cache" / "py-yfinance"
            if cache.exists(): shutil.rmtree(cache)

            for ativo in carteira:
                try:
                    if "USD" in ativo: df = pegar_dados_binance(ativo)
                    else: df = pegar_dados_yahoo(ativo)

                    if df is None or len(df) < 25: continue
                    
                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev):
                        preco = df['Close'].iloc[-1]
                        fmt = f"{preco:.8f}" if preco < 1 else f"{preco:.2f}"
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"📝 Registrar @ {fmt}", callback_data=f"COMPRA|{ativo}|{fmt}"))
                        bot.send_message(CHAT_ID, f"🟢 **OPORTUNIDADE**\nAtivo: {ativo}\nPreço: {fmt}\nCruzamento 9x21", reply_markup=markup, parse_mode="Markdown")
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

app = Flask(__name__)
@app.route('/')
def home(): return "Robô Ativo 🚀"

if __name__ == "__main__":
    threading.Thread(target=loop_monitoramento).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()