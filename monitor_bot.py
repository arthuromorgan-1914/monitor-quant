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
import ccxt
import schedule
import requests

# ==============================================================================
# 1. CONFIGURAÇÕES
# ==============================================================================
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"
CHAT_ID = "1116977306"
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

# --- COLE SUA CHAVE AQUI DENTRO DAS ASPAS ---
GEMINI_KEY = "AIzaSyC052VU7LJ5YeS0J8095BEuADDy4WTvpV0" 

bot = telebot.TeleBot(TOKEN)

# LISTA DE CAÇA (HUNTER)
ALVOS_CAÇADOR = [
    # BRASIL (B3)
    {"symbol": "PETR4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PETR4.SA"},
    {"symbol": "VALE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "VALE3.SA"},
    {"symbol": "WEGE3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "WEGE3.SA"},
    {"symbol": "PRIO3", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "PRIO3.SA"},
    {"symbol": "ITUB4", "screener": "brazil", "exchange": "BMFBOVESPA", "nome_sheet": "ITUB4.SA"},
    # CRIPTO (Binance)
    {"symbol": "BTCUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "BTC-USD"},
    {"symbol": "ETHUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "ETH-USD"},
    {"symbol": "SOLUSDT", "screener": "crypto", "exchange": "BINANCE", "nome_sheet": "SOL-USD"},
    # EUA
    {"symbol": "NVDA", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "NVDA"},
    {"symbol": "TSLA", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "TSLA"},
    {"symbol": "AAPL", "screener": "america", "exchange": "NASDAQ", "nome_sheet": "AAPL"},
]

# ==============================================================================
# 2. FUNÇÕES DE DADOS (MERCADO)
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
# 3. FUNÇÕES DO SHEETS (MODO DEBUG LIGADO 🕵️‍♂️)
# ==============================================================================
def conectar_google(verbose=False):
    if not os.path.exists('creds.json'):
        msg = "❌ Erro Crítico: O arquivo 'creds.json' NÃO está no Render. Verifique em 'Secret Files'."
        if verbose: return None, msg
        print(msg)
        return None, msg

    try:
        gc = gspread.service_account(filename='creds.json')
        sh = gc.open(NOME_PLANILHA_GOOGLE)
        return sh, "Sucesso"

    except Exception as e:
        erro_str = str(e)
        msg_final = f"❌ Erro desconhecido: {erro_str}"
        
        if "SpreadsheetNotFound" in erro_str:
            msg_final = f"❌ Não achei a planilha '{NOME_PLANILHA_GOOGLE}'. Verifique o nome exato ou se compartilhou com o email do JSON."
        elif "invalid_grant" in erro_str:
            msg_final = "❌ Chave inválida. O conteúdo do 'creds.json' pode estar corrompido."
        elif "403" in erro_str:
             msg_final = "❌ Erro 403: Sem permissão. Você esqueceu de ativar a 'Google Sheets API' ou 'Drive API' no Google Cloud?"
        
        if verbose: return None, msg_final
        return None, msg_final

def ler_carteira():
    sh, _ = conectar_google()
    if sh:
        try:
            return [x.upper().strip() for x in sh.worksheet("Carteira").col_values(1) if x.strip()]
        except: return []
    return []

def adicionar_ativo(novo_ativo):
    sh, mensagem_erro = conectar_google(verbose=True)
    if sh:
        try:
            ws = sh.worksheet("Carteira")
            if novo_ativo.upper() in [x.strip().upper() for x in ws.col_values(1)]:
                return "⚠️ Já existe na lista"
            ws.append_row([novo_ativo.upper()])
            return "✅ Sucesso! Adicionado."
        except Exception as e:
            return f"❌ Conectou no Google, mas falhou na aba 'Carteira'. Erro: {str(e)}"
    else:
        return mensagem_erro

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
# 4. FUNÇÃO DO CAÇADOR (LISTA DE IA ATUALIZADA V21)
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
                if res == "✅ Sucesso! Adicionado.":
                    relatorio.append(f"✅ {alvo['symbol']} (Novo!)")
                    novos += 1
                elif "Já existe" in res:
                    relatorio.append(f"⚠️ {alvo['symbol']} (Já vigiando)")
                else:
                    relatorio.append(f"❌ Erro Planilha: {res}")
            
            tempo_espera = random.uniform(5, 10)
            print(f"Dormindo {tempo_espera:.1f}s para não travar...")
            time.sleep(tempo_espera) 
            
        except Exception as e:
            relatorio.append(f"Erro {alvo['symbol']}: {str(e)}")
            time.sleep(10)
            
    # 2. Notícias e IA (Lista LIMPA - Sem modelos velhos)
    sentimento = "Iniciando..."
    if "COLE_SUA_CHAVE" in GEMINI_KEY:
        sentimento = "Erro: Chave não configurada no código."
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
                prompt = (
                    f"Analise estas manchetes financeiras: {manchetes}. "
                    "Responda EXATAMENTE neste formato de 3 linhas (use emojis):\n"
                    "Sentimento: (Resumo curto do humor do mercado)\n"
                    "Destaque: (A notícia mais relevante resumida)\n"
                    "Fonte: (O link da notícia destaque)"
                )
                
                # --- AQUI ESTA A CORREÇÃO V21 ---
                # Usamos apenas os modelos que sabemos que funcionam
                modelos = [
                    "gemini-2.0-flash",    # O mais novo
                    "gemini-1.5-flash",    # O padrão rápido
                    "gemini-1.5-pro",      # O padrão inteligente
                ]
                
                sucesso = False
                ultimo_erro = ""
                
                for modelo in modelos:
                    if sucesso: break
                    try:
                        url_google = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
                        headers = {'Content-Type': 'application/json'}
                        data = {"contents": [{"parts": [{"text": prompt}]}]}
                        
                        response = requests.post(url_google, headers=headers, json=data, timeout=30)
                        
                        if response.status_code == 200:
                            try:
                                sentimento = response.json()['candidates'][0]['content']['parts'][0]['text']
                                sucesso = True
                            except:
                                ultimo_erro = "JSON vazio"
                                continue
                        else:
                            ultimo_erro = f"Erro {response.status_code} no {modelo}"
                            continue
                            
                    except Exception as e:
                        ultimo_erro = str(e)
                        continue

                if not sucesso:
                    sentimento = f"Falha IA: {ultimo_erro}"

        except Exception as e:
            sentimento = f"Erro Geral IA: {str(e)}"

    return relatorio, sentimento, novos

# ==============================================================================
# 5. TAREFA EM SEGUNDO PLANO
# ==============================================================================
def tarefa_hunter_background(chat_id):
    try:
        achados, humor, n = executar_hunter()
        
        txt = f"📋 RELATÓRIO HUNTER\n\n🌡️ Clima: {humor}\n\n"
        txt += "\n".join(achados) if achados else "🚫 Nada em 'Compra Forte'."
        txt += f"\n\n🔢 Novos: {n}"
        
        bot.send_message(chat_id, txt, parse_mode=None, disable_web_page_preview=True)
        
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Erro ao gerar relatório: {e}")

# ==============================================================================
# 6. AUTOMAÇÃO E BOT
# ==============================================================================
def enviar_relatorio_agendado():
    try:
        bot.send_message(CHAT_ID, "⏰ **Relatório Automático**\nIniciando análise...")
        tarefa_hunter_background(CHAT_ID)
    except Exception as e:
        print(f"Erro no agendamento: {e}")

def thread_agendamento():
    schedule.every().day.at("07:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("10:15").do(enviar_relatorio_agendado)
    schedule.every().day.at("13:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("16:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("18:30").do(enviar_relatorio_agendado)
    schedule.every().day.at("21:00").do(enviar_relatorio_agendado)
    while True:
        schedule.run_pending()
        time.sleep(60)

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
            bot.answer_callback_query(call.id, "Iniciando caçada (Modo Seguro)...")
            bot.send_message(CHAT_ID, "🕵️ **O Caçador saiu (Isso vai levar uns 2 minutos)...**\n(Estou indo devagar para não ser bloqueado)")
            t = threading.Thread(target=tarefa_hunter_background, args=(CHAT_ID,))
            t.start()
            
        elif call.data == "CMD_LISTA":
            lista = ler_carteira()
            txt = f"📋 **Vigiando {len(lista)}:**\n" + "\n".join([f"`{x}`" for x in lista])
            bot.send_message(CHAT_ID, txt, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro Callback: {e}")

@bot.message_handler(commands=['add'])
def add_manual(m):
    try:
        ativo = m.text.split()[1].upper()
        resultado = adicionar_ativo(ativo)
        bot.reply_to(m, resultado)
    except: 
        bot.reply_to(m, "Uso incorreto. Digite: /add ATIVO")

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
                    
                    ultimo_status = verificar_ultimo_status(ativo)

                    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70) and (ultimo_status != "Compra"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"📝 Registrar @ {fmt}", callback_data=f"COMPRA|{ativo}|{fmt}"))
                        bot.send_message(CHAT_ID, f"🟢 **COMPRA**\nAtivo: {ativo}\nPreço: {fmt}\nRSI: {rsi:.0f}\nCruzamento: 9 > 21", reply_markup=markup, parse_mode="Markdown")

                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev) and (ultimo_status != "Venda"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"📉 Registrar Saída @ {fmt}", callback_data=f"VENDA|{ativo}|{fmt}"))
                        bot.send_message(CHAT_ID, f"🔴 **VENDA (SAÍDA)**\nAtivo: {ativo}\nPreço: {fmt}\nRSI: {rsi:.0f}\nCruzamento: 9 < 21", reply_markup=markup, parse_mode="Markdown")
                    
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

app = Flask(__name__)
@app.route('/')
def home(): return "Robô V21 (Lista IA Limpa) 🧹"

if __name__ == "__main__":
    threading.Thread(target=loop_monitoramento).start()
    threading.Thread(target=thread_agendamento).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()