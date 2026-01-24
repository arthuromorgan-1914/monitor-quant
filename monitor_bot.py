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

# --- SUA CHAVE ATIVA (V23/V24) ---
GEMINI_KEY = "AIzaSyC052VU7LJ5YeS0J8095BEuADDy4WTvpV0"

bot = telebot.TeleBot(TOKEN)

# LISTA DE CAÇA (HUNTER)
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
# 2. FUNÇÕES DE DADOS (MERCADO)
# ==============================================================================
def pegar_dados_binance(symbol):
    symbol_binance = symbol.replace("-", "/").replace("USD", "USDT")
    exchange = ccxt.binance()
    try:
        candles = exchange.fetch_ohlcv(symbol_binance, timeframe='15m', limit=100)
        df = pd.DataFrame(candles, columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Time'] = pd.to_datetime(df['Time'], unit='ms')
        df['Close'] = df['Close'].astype(float)
        return df
    except Exception as e:
        print(f"⚠️ Erro Binance ({symbol}): {e}")
        return None

def pegar_dados_yahoo(symbol):
    try:
        df = yf.Ticker(symbol).history(period="1mo", interval="15m") # Pegando mais dados para o calculo ficar preciso
        return df
    except: return None

# ==============================================================================
# 3. FUNÇÕES DO SHEETS
# ==============================================================================
def conectar_google(verbose=False):
    if not os.path.exists('creds.json'):
        msg = "❌ Erro Crítico: O arquivo 'creds.json' NÃO está no Render."
        if verbose: return None, msg
        print(msg)
        return None, msg

    try:
        gc = gspread.service_account(filename='creds.json')
        sh = gc.open(NOME_PLANILHA_GOOGLE)
        return sh, "Sucesso"
    except Exception as e:
        return None, f"❌ Erro Google: {str(e)}"

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
            return f"❌ Erro na aba 'Carteira': {str(e)}"
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
# 4. FUNÇÃO DE INTEGRAÇÃO COM GEMINI (SERVIÇO IA)
# ==============================================================================
def consultar_gemini(prompt):
    modelos = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"]
    
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                continue # Tenta o próximo modelo
        except:
            continue
            
    return "❌ A IA não conseguiu responder agora (Erro de Conexão)."

# ==============================================================================
# 5. NOVO COMANDO: ANALISAR ATIVO
# ==============================================================================
def analisar_ativo_tecnico(ativo):
    try:
        # 1. Pega dados
        if "USD" in ativo: df = pegar_dados_binance(ativo)
        else: df = pegar_dados_yahoo(ativo)
        
        if df is None or len(df) < 50: return "❌ Não consegui ler os dados desse ativo."
        
        # 2. Calcula Indicadores
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        preco_atual = df['Close'].iloc[-1]
        
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        
        # 3. Monta o Prompt para a IA
        prompt = (
            f"Atue como um analista de trading Quant Sênior. Analise o ativo {ativo} agora. "
            f"Dados Técnicos (Gráfico 15min): Preço: {preco_atual:.2f} | RSI(14): {rsi:.1f} | "
            f"Média Curta (9): {sma9:.2f} | Média Longa (21): {sma21:.2f}. "
            f"A tendência das médias está de {tendencia}. "
            "Resuma em 3 ou 4 linhas curtas: Qual o sentimento técnico? Há sinal de compra ou venda? Use emojis."
        )
        
        return consultar_gemini(prompt)
        
    except Exception as e:
        return f"Erro na análise: {str(e)}"

# ==============================================================================
# 6. FUNÇÃO DO CAÇADOR (HUNTER)
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
                if "Sucesso" in res:
                    relatorio.append(f"✅ {alvo['symbol']} (Novo!)")
                    novos += 1
                elif "Já existe" in res:
                    relatorio.append(f"⚠️ {alvo['symbol']} (Já vigiando)")
            
            time.sleep(random.uniform(2, 5))
            
        except Exception as e:
            time.sleep(5)
            
    # 2. Notícias e IA
    try:
        manchetes = []
        feeds = ["https://www.infomoney.com.br/feed/", "https://br.investing.com/rss/news.rss"]
        try:
            for url in feeds:
                d = feedparser.parse(url)
                if d.entries:
                    for entry in d.entries[:3]:
                        manchetes.append(f"Título: {entry.title}")
        except: pass
        
        if not manchetes:
            sentimento = "Sem notícias."
        else:
            prompt_news = (
                f"Analise estas manchetes: {manchetes}. "
                "Responda EXATAMENTE: Sentimento: (Resumo) | Destaque: (Melhor notícia)."
            )
            sentimento = consultar_gemini(prompt_news)
    except Exception as e:
        sentimento = f"Erro IA News: {str(e)}"

    return relatorio, sentimento, novos

# ==============================================================================
# 7. AUTOMAÇÃO E TAREFAS
# ==============================================================================
def tarefa_hunter_background(chat_id):
    try:
        achados, humor, n = executar_hunter()
        txt = f"📋 RELATÓRIO HUNTER\n\n🌡️ {humor}\n\n"
        txt += "\n".join(achados) if achados else "🚫 Nada em 'Compra Forte'."
        bot.send_message(chat_id, txt, parse_mode=None, disable_web_page_preview=True)
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Erro relatório: {e}")

def enviar_relatorio_agendado():
    tarefa_hunter_background(CHAT_ID)

def thread_agendamento():
    schedule.every().day.at("07:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("10:15").do(enviar_relatorio_agendado)
    schedule.every().day.at("13:00").do(enviar_relatorio_agendado)
    schedule.every().day.at("16:00").do(enviar_relatorio_agendado)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ==============================================================================
# 8. HANDLERS TELEGRAM
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔫 Hunter (Caçar)", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("📋 Ver Lista", callback_data="CMD_LISTA"))
    bot.reply_to(message, "🤖 **Painel Quant**\nComandos:\n/add ATIVO\n/del ATIVO\n/analisar ATIVO", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_geral(call):
    if call.data.startswith("COMPRA|"):
        _, ativo, preco = call.data.split("|")
        if registrar_trade(ativo, preco, "Compra"):
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{call.message.text}\n✅ REGISTRADO!")
    
    elif call.data.startswith("VENDA|"):
        _, ativo, preco = call.data.split("|")
        if registrar_trade(ativo, preco, "Venda"):
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{call.message.text}\n🔴 REGISTRADO!")
    
    elif call.data == "CMD_HUNTER":
        bot.answer_callback_query(call.id, "Caçando...")
        threading.Thread(target=tarefa_hunter_background, args=(CHAT_ID,)).start()
        
    elif call.data == "CMD_LISTA":
        lista = ler_carteira()
        bot.send_message(CHAT_ID, f"📋 **Vigiando:**\n" + "\n".join([f"`{x}`" for x in lista]), parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_manual(m):
    try: bot.reply_to(m, adicionar_ativo(m.text.split()[1].upper()))
    except: bot.reply_to(m, "Use: /add ATIVO")

@bot.message_handler(commands=['del'])
def del_manual(m):
    try:
        ativo = m.text.split()[1].upper()
        sh, _ = conectar_google()
        ws = sh.worksheet("Carteira")
        ws.delete_rows(ws.find(ativo).row)
        bot.reply_to(m, f"🗑️ {ativo} deletado!")
    except: bot.reply_to(m, "Erro ou não encontrado.")

# --- COMANDO NOVO: ANALISAR ---
@bot.message_handler(commands=['analisar'])
def analisar_cmd(m):
    try:
        # Pega o ativo
        ativo = m.text.split()[1].upper()
        msg_wait = bot.reply_to(m, f"🕵️‍♂️ **Analisando {ativo}...**\n(Calculando indicadores e consultando IA)")
        
        # Chama a função inteligente
        analise = analisar_ativo_tecnico(ativo)
        
        # Edita a mensagem com a resposta
        bot.edit_message_text(chat_id=m.chat.id, message_id=msg_wait.message_id, text=f"📊 **Análise IA: {ativo}**\n\n{analise}", parse_mode="Markdown")
        
    except IndexError:
        bot.reply_to(m, "⚠️ Use: `/analisar ATIVO` (ex: `/analisar PETR4.SA`)")
    except Exception as e:
        bot.reply_to(m, f"Erro: {e}")

# ==============================================================================
# 9. LOOP PRINCIPAL
# ==============================================================================
def loop_monitoramento():
    while True:
        try:
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
                    
                    last = verificar_ultimo_status(ativo)

                    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70) and (last != "Compra"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"Comprar @ {preco:.2f}", callback_data=f"COMPRA|{ativo}|{preco:.2f}"))
                        bot.send_message(CHAT_ID, f"🟢 **SINAL COMPRA**: {ativo}\nPreço: {preco:.2f}", reply_markup=markup)

                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev) and (last != "Venda"):
                        markup = InlineKeyboardMarkup()
                        markup.add(InlineKeyboardButton(f"Vender @ {preco:.2f}", callback_data=f"VENDA|{ativo}|{preco:.2f}"))
                        bot.send_message(CHAT_ID, f"🔴 **SINAL VENDA**: {ativo}\nPreço: {preco:.2f}", reply_markup=markup)
                    
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

app = Flask(__name__)
@app.route('/')
def home(): return "Robô V24 (Analista IA) 🕵️‍♂️"

if __name__ == "__main__":
    threading.Thread(target=loop_monitoramento).start()
    threading.Thread(target=thread_agendamento).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    bot.infinity_polling()