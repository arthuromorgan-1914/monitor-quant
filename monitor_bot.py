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
import requests
import schedule

# ==============================================================================
# 1. CONFIGURAÇÕES
# ==============================================================================
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"
CHAT_ID = "1116977306"
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

# Chave do Gemini
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
# 3. FUNÇÕES DO SHEETS (COM MEMÓRIA)
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

def registrar_trade(ativo, preco, tipo="Compra"):
    sh = conectar_google()
    if sh:
        try:
            status = "Aberta" if tipo == "Compra" else "Encerrada"
            sh.sheet1.append_row([datetime.now().strftime('%d/%m %H:%M'), ativo, tipo, preco, "", "", status])
            return True
        except: return False
    return False

# NOVA FUNÇÃO: Verifica o último registro na planilha para não repetir
def verificar_ultimo_status(ativo):
    sh = conectar_google()
    if sh:
        try:
            # Pega todas as linhas da aba de trades (Sheet1)
            dados = sh.sheet1.get_all_values()
            # Inverte a lista para procurar do mais recente para o mais antigo
            for linha in reversed(dados):
                # Coluna B (índice 1) é o Ativo, Coluna C (índice 2) é o Tipo (Compra/Venda)
                if len(linha) > 2 and linha[1].strip().upper() == ativo.strip().upper():
                    return linha[2].strip() # Retorna "Compra" ou "Venda"
        except: return None
    return None

# ==============================================================================
# 4. FUNÇÃO DO CAÇADOR (HUNTER)
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
            time.sleep(2) 
        except Exception as e:
            relatorio.append(f"Erro {alvo['symbol']}: {e}")
            time.sleep(2)
            
    # 2. Notícias
    sentimento = "Iniciando..."
    if not GEMINI_KEY:
        sentimento = "Erro: Chave GEMINI não configurada."
    else:
        try:
            manchetes = []
            feeds = ["https://www.infomoney.com.br/feed/", "https://br.investing.com/rss/news.rss"]
            try:
                for url in feeds:
                    d = feedparser.parse(url)
                    if d.entries:
                        for entry in d.entries[:3]:
                            manchetes.append(f"Título: {entry.title} | Link: {entry.link}")
            except: pass
            
            if not manchetes:
                sentimento = "Aviso: Sem notícias no RSS."
            else:
                url_google = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-001:generateContent?key={GEMINI_KEY}"
                
                prompt = (
                    f"Analise estas manchetes: {manchetes}. "
                    "Responda EXATAMENTE neste formato de 3 linhas (use emojis):\n"
                    "Sentimento: (Resumo curto do humor do mercado)\n"
                    "Destaque: (A notícia mais relevante resumida)\n"
                    "Fonte: (O link da notícia destaque)"
                )
                
                payload = {"contents": [{"parts": [{"text": prompt}]}]}
                
                resp = requests.post(url_google, json=payload, timeout=8)
                
                if resp.status_code == 200:
                    try:
                        dados = resp.json()
                        sentimento = dados['candidates'][0]['content']['parts'][0]['text']
                    except:
                        sentimento = "Erro ao ler JSON da IA."
                elif resp.status_code == 429:
                    sentimento = "⚠️ Cota da IA excedida (Tente mais tarde)."
                else:
                    sentimento = f"Erro Google ({resp.status_code})"
        except requests.exceptions.Timeout:
            sentimento = "⚠️ Timeout (Google demorou)."
        except Exception as e:
            sentimento = f"Erro Técnico: {str(e)}"

    return relatorio, sentimento, novos

# ==============================================================================
# 5. AUTOMAÇÃO
# ==============================================================================
def enviar_relatorio_agendado():
    try:
        bot.send_message(CHAT_ID, "⏰ **Relatório Automático**\nIniciando análise...")
        achados, humor, n = executar_hunter()
        txt = f"📋 **RELATÓRIO HUNTER**\n\n🌡️ *Clima:* {humor}\n\n"
        txt += "\n".join(achados) if achados else "🚫 Nada em 'Compra Forte'."
        txt += f"\n\n🔢 Novos: {n}"
        bot.send_message(CHAT_ID, txt, parse_mode="Markdown", disable_web_page_preview=True)
        print(f"Relatório enviado às {datetime.now()}")
    except Exception as e:
        print(f"Erro no agendamento: {e}")

def thread_agendamento():
    schedule.every().day.at("07:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("10:15").do(enviar_relatorio_agendado)
    schedule.every().day.at("13:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("16:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("18:30").do(enviar_relatorio_agendado)
    schedule.every().day.at("21:00").do(enviar_relatorio_agendado)
    
    print("📅 Agendador iniciado (TZ: SP)")
    while True:
        schedule.run_pending()
        time.sleep(60)

# ==============================================================================
# 6. BOT TELEGRAM
# ==============================================================================
@bot.message_handler(commands=['start', 'menu', 'status'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔫 Caçar Oportunidades (Hunter)", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("📋 Ver Lista de Vigília", callback_data="CMD_LISTA"))
    bot.reply_to(message, "🤖 **Painel Quant**\nO que deseja?", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    try:
        if call.data.startswith("COMPRA|"):
            _, ativo, preco = call.data.split("|")
            if registrar_trade(ativo, preco, "Compra"):
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{call.message.text}\n\n✅ **COMPRA REGISTRADA!**")
        
        elif call.data.startswith("VENDA|"):
            _, ativo, preco = call.data.split("|")
            if registrar_trade(ativo, preco, "Venda"):
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{call.message.text}\n\n🔴 **VENDA REGISTRADA!**")
        
        elif call.data == "CMD_HUNTER":
            bot.answer_callback_query(call.id, "Buscando... (Isso leva uns 30s)")
            bot.send_message(CHAT_ID, "🕵️ **Analisando Mercado com Calma...**")
            achados, humor, n = executar_hunter()
            txt = f"📋 **RELATÓRIO HUNTER**\n\n🌡️ *Clima:* {humor}\n\n"
            txt += "\n".join(achados) if achados else "🚫 Nada em 'Compra Forte'."
            txt += f"\n\n🔢 Novos: {n}"
            bot.send_message(CHAT_ID, txt, parse_mode="Markdown", disable_web_page_preview=True)
            
        elif call.data == "CMD_LISTA":
            lista = ler_carteira()
            txt = f"📋 **Vigiando {len(lista)}:**\n" + "\n".join([f"`{x}`" for x in lista])
            bot.send_message(CHAT_ID, txt, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro Callback: {e}")

@bot.message_handler(commands=['add'])
def add_manual(m):
    try: bot.reply_to(m, f"Resultado: {adicionar_ativo(m.text.split()[1].upper())}")
    except: bot.reply_to(m, "Use: /add ATIVO")

# ==============================================================================
# 7. LOOP MONITOR (COM FILTRO DE REPETIÇÃO)
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

                    if df is None or len(df) < 50: continue
                    
                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    
                    preco = df['Close'].iloc[-1]
                    fmt = f"{preco:.8f}" if preco < 1 else f"{preco:.2f}"

                    # Consulta o último status na planilha para evitar repetição
                    ultimo_status = verificar_ultimo_status(ativo)

                    # SINAL DE COMPRA
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev):
                        if rsi < 70:
                            if ultimo_status != "Compra": # Só avisa se o último NÃO for Compra
                                markup = InlineKeyboardMarkup()
                                markup.add(InlineKeyboardButton(f"📝 Registrar @ {fmt}", callback_data=f"COMPRA|{ativo}|{fmt}"))
                                bot.send_message(CHAT_ID, f"🟢 **COMPRA**\nAtivo: {ativo}\nPreço: {fmt}\nRSI: {rsi:.0f}\nCruzamento: 9 > 21", reply_markup=markup, parse_mode="Markdown")
                            else:
                                print(f"Silenciado {ativo}: Já está comprado.")

                    # SINAL DE VENDA
                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev):
                        if ultimo_status != "Venda": # Só avisa se o último NÃO for Venda
                            markup = InlineKeyboardMarkup()
                            markup.add(InlineKeyboardButton(f"📉 Registrar Saída @ {fmt}", callback_data=f"VENDA|{ativo}|{fmt}"))
                            bot.send_message(CHAT_ID, f"🔴 **VENDA (SAÍDA)**\nAtivo: {ativo}\nPreço: {fmt}\nRSI: {rsi:.0f}\nCruzamento: 9 < 21", reply_markup=markup, parse_mode="Markdown")
                        else:
                            print(f"Silenciado {ativo}: Já está vendido.")
                    
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

app = Flask(__name__)
@app.route('/')
def home(): return "Robô Quant Inteligente 🧠"

if __name__ == "__main__":
    threading.Thread(target=loop_monitoramento).start()
    threading.Thread(target=thread_agendamento).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()