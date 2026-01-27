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
# 1. CONFIGURAÇÕES (SEGURAS)
# ==============================================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

NOME_PLANILHA_GOOGLE = "Trades do Robô Quant"

# Debug inicial no console do Render
print("--- INICIANDO QUANTBOT V50 ---")
if not TOKEN: print("ERRO: TOKEN não encontrado.")
if not GEMINI_KEY: print("ERRO: GEMINI_KEY não encontrada.")

bot = telebot.TeleBot(TOKEN) if TOKEN else None
ultimo_sinal_enviado = {} 

PADRAO_VIGILANCIA = ["PETR4.SA", "VALE3.SA", "BTC-USD", "ETH-USD"]

POOL_TOP_40 = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "WEGE3", "PRIO3", "RENT3", 
    "GGBR4", "SUZB3", "BPAC11", "EQTL3", "RADL3", "RAIL3", "RDOR3", "CMIG4", 
    "ELET3", "LREN3", "TOTS3", "CSAN3", "HAPV3", "VBBR3", "BBSE3", "GOAU4", 
    "MGLU3", "B3SA3", "TIMS3", "KLBN11", "ABEV3", "CPLE6", "EMBR3", "VIVT3",
    "JBSS3", "BRFS3", "CVCB3", "AZUL4", "PCAR3", "MRFG3", "GMAT3", "SBSP3"
]

# ==============================================================================
# 2. FUNÇÕES AUXILIARES
# ==============================================================================
def formatar_preco(valor):
    if valor < 50: return f"{valor:.4f}"
    return f"{valor:.2f}"

def corrigir_escala(symbol, preco):
    symbol_upper = symbol.upper()
    if "BTC" in symbol_upper: return preco
    if preco > 10000: return preco / 10000
    return preco

def normalizar_simbolo(entrada):
    s = entrada.upper().strip()
    if "." in s or "-" in s: return s
    criptos = ["BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "AVAX", "DOT", "LINK", "SHIB"]
    if s in criptos: return f"{s}-USD"
    if s[-1] in ['3', '4', '5', '6', '1']: return f"{s}.SA"
    return s

def pegar_dados_yahoo(symbol):
    try:
        symbol_corrigido = normalizar_simbolo(symbol)
        # Tenta baixar
        df = yf.Ticker(symbol_corrigido).history(period="1mo", interval="15m")
        if df is None or df.empty: 
            print(f"DEBUG: Yahoo retornou vazio para {symbol_corrigido}")
            return None
        return df
    except Exception as e:
        print(f"DEBUG: Erro Yahoo: {e}")
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

    # Ordem: Tenta o 2.5 Flash primeiro, se falhar tenta o 2.0
    modelos = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
    erros_log = []
    
    for modelo in modelos:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={GEMINI_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            
            # Timeout curto para não travar o bot
            response = requests.post(url, headers=headers, json=data, timeout=25)
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                erros_log.append(f"{modelo}: {response.text}")
                continue
        except Exception as e:
            erros_log.append(f"{modelo}: {str(e)}")
            continue
            
    print(f"DEBUG IA ERRO: {erros_log}")
    return f"⚠️ IA Falhou. Erro técnico: {erros_log[0] if erros_log else 'Timeout'}"

# ==============================================================================
# 5. SCANNER TOP 40
# ==============================================================================
def escanear_mercado_top40(apenas_fortes=False):
    oportunidades = []
    for simbolo in POOL_TOP_40:
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
                    "texto": f"{simbolo} ({tag} | R$ {fechamento:.2f})",
                    "rsi": rsi,
                    "symbol": simbolo
                })
            time.sleep(0.1)
        except: continue
    return oportunidades

def gerar_alocacao(valor):
    raw_ops = escanear_mercado_top40(apenas_fortes=False)
    if not raw_ops: return "⚠️ O Scanner não achou tendências de alta claras hoje."
    
    top_15 = sorted(raw_ops, key=lambda x: x['rsi'], reverse=True)[:15]
    lista_para_ia = [x['texto'] for x in top_15]
    
    manchetes = []
    try:
        d = feedparser.parse("https://br.investing.com/rss/news.rss")
        for entry in d.entries[:3]: manchetes.append(entry.title)
    except: pass

    prompt = (
        f"Atue como Consultor (Robo-Advisor). Cliente tem R$ {valor}. "
        f"Notícias: {manchetes}. "
        f"Oportunidades: {', '.join(lista_para_ia)}. "
        f"TAREFA: "
        f"1) Escolha 3 ou 4 ativos diversos. "
        f"2) Distribua R$ {valor}. "
        f"3) Explique. Responda com lista e emojis."
    )
    return consultar_gemini(prompt)

def analisar_ativo_tecnico(ativo):
    try:
        symbol_corrigido = normalizar_simbolo(ativo)
        df = pegar_dados_yahoo(symbol_corrigido)
        
        if df is None: return f"❌ Não encontrei dados para {symbol_corrigido}."
        
        preco_bruto = df['Close'].iloc[-1]
        preco = corrigir_escala(symbol_corrigido, preco_bruto)
        
        sma9 = ta.sma(df['Close'], length=9).iloc[-1]
        sma21 = ta.sma(df['Close'], length=21).iloc[-1]
        
        # Correção médias
        if sma9 > 10000 and "BTC" not in symbol_corrigido: sma9 /= 10000
        if sma21 > 10000 and "BTC" not in symbol_corrigido: sma21 /= 10000
        
        rsi = ta.rsi(df['Close'], length=14).iloc[-1]
        tendencia = "ALTA" if sma9 > sma21 else "BAIXA"
        
        prompt = (
            f"Analise {symbol_corrigido}. Preço: {preco:.2f} | RSI: {rsi:.1f} | "
            f"M9/M21: {sma9:.2f}/{sma21:.2f} ({tendencia}). "
            "Dê um veredito técnico curto e direto."
        )
        return consultar_gemini(prompt)
    except Exception as e: return f"Erro script: {str(e)}"

# ==============================================================================
# 6. TELEGRAM HANDLERS (CORREÇÃO V50)
# ==============================================================================
@bot.message_handler(commands=['start', 'menu'])
def menu_principal(message):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📰 Hunter", callback_data="CMD_HUNTER"))
    markup.row(InlineKeyboardButton("🎩 Consultor", callback_data="CMD_CONSULTOR"))
    markup.row(InlineKeyboardButton("📂 Portfólio", callback_data="CMD_PORTFOLIO"))
    txt = "🤖 **QuantBot V50 - Safe Mode**\n\n`/comprar ATIVO PRECO`\n`/vender ATIVO PRECO`\n`/analisar ATIVO`"
    bot.reply_to(message, txt, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['analisar'])
def analise(m):
    try:
        partes = m.text.split()
        if len(partes) < 2: return bot.reply_to(m, "Use: `/analisar ATIVO`")
        
        atv_digitado = partes[1].upper()
        
        # 1. Feedback Imediato
        bot.send_chat_action(m.chat.id, 'typing')
        msg_wait = bot.reply_to(m, f"🔍 Analisando **{atv_digitado}**...", parse_mode="Markdown")
        
        # 2. Processamento
        res = analisar_ativo_tecnico(atv_digitado)
        
        # 3. Resposta SEM Markdown (Para evitar o erro que trava o bot)
        cabecalho = f"📊 ANÁLISE: {atv_digitado}\n\n"
        bot.edit_message_text(chat_id=m.chat.id, message_id=msg_wait.message_id, text=cabecalho + res)
        
    except Exception as e:
        print(f"DEBUG: Erro no handler analisar: {e}")
        bot.reply_to(m, f"❌ Erro interno: {e}")

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
    elif c.data == "CMD_CONSULTOR":
        msg = bot.send_message(c.message.chat.id, "💰 Quanto investir?", reply_markup=ForceReply())
        bot.register_next_step_handler(msg, passo_consultor_valor)
    elif c.data == "CMD_PORTFOLIO":
        sh = conectar_google()
        try: 
            dados = sh.worksheet("Portfolio").get_all_values()[-5:]
            txt = "📂 **Últimos Registros:**\n"
            for row in dados: txt += f"{row[1]} | {row[2]} | {row[3]}\n"
            bot.send_message(c.message.chat.id, txt, parse_mode="Markdown")
        except: bot.send_message(c.message.chat.id, "Vazio.")
    elif c.data == "CMD_HUNTER":
        bot.answer_callback_query(c.id, "Varrendo...")
        bot.send_message(c.message.chat.id, "🔭 **Hunter:** Buscando oportunidades... (~40s)")
        threading.Thread(target=enviar_relatorio_agendado).start()

def passo_consultor_valor(message):
    try:
        valor = float(message.text.replace(",", ".").replace("R$", ""))
        bot.send_chat_action(message.chat.id, 'typing')
        bot.reply_to(message, f"🤖 Analisando **Top 40** para R$ {valor:.2f}...\n⏳ Aguarde...")
        sugestao = gerar_alocacao(valor)
        bot.reply_to(message, f"🎩 **Sugestão:**\n\n{sugestao}") # Sem Markdown aqui tb por segurança
    except: bot.reply_to(message, "❌ Use números.")

# ==============================================================================
# 7. LOOP MONITORAMENTO
# ==============================================================================
def loop():
    while True:
        try:
            lista_vigilancia = ler_carteira_vigilancia()
            for atv in lista_vigilancia:
                try:
                    df = pegar_dados_yahoo(atv)
                    if df is None: continue
                    
                    preco_bruto = df['Close'].iloc[-1]
                    atv_corr = normalizar_simbolo(atv)
                    preco = corrigir_escala(atv_corr, preco_bruto)

                    sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                    sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                    
                    if sma9 > 10000 and "BTC" not in atv_corr: sma9 /= 10000
                    if sma21 > 10000 and "BTC" not in atv_corr: sma21 /= 10000
                    
                    sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                    sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                    
                    rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                    preco_str = formatar_preco(preco)

                    sinal = None
                    if (sma9 > sma21) and (sma9_prev <= sma21_prev) and (rsi < 70): sinal = "COMPRA"
                    elif (sma9 < sma21) and (sma9_prev >= sma21_prev): sinal = "VENDA"
                    
                    if sinal:
                        chave = f"{atv}_{sinal}_{datetime.now().day}"
                        if chave not in ultimo_sinal_enviado:
                            markup = InlineKeyboardMarkup()
                            emoji = "🟢" if sinal == "COMPRA" else "🔴"
                            cb_real = f"REAL|{sinal}|{atv}|{preco_str}"
                            markup.add(InlineKeyboardButton(f"✅ Executar Real", callback_data=cb_real),
                                     InlineKeyboardButton(f"👀 Ciente", callback_data=f"SUGEST|{sinal}|{atv}|{preco_str}"))
                            bot.send_message(CHAT_ID, f"{emoji} **SINAL {sinal}**: {atv}\nPreço: {preco_str}", reply_markup=markup)
                            ultimo_sinal_enviado[chave] = True
                    time.sleep(1)
                except: pass
            time.sleep(900)
        except: time.sleep(60)

# ==============================================================================
# 8. HUNTER & AGENDAMENTO
# ==============================================================================
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

    raw_ops = escanear_mercado_top40(apenas_fortes=True)
    achados = [x['texto'] for x in raw_ops]
    return sentimento, achados

def enviar_relatorio_agendado():
    humor, achados = executar_hunter_completo()
    txt_sinais = "\n".join(achados) if achados else "🚫 Sem sinais 'Forte'."
    msg = f"🗞️ **MERCADO:**\n{humor}\n\n🔥 **OPORTUNIDADES:**\n{txt_sinais}"
    bot.send_message(CHAT_ID, msg)

def thread_agendamento():
    times = ["09:30", "13:00", "16:30"]
    for t in times: schedule.every().day.at(t).do(enviar_relatorio_agendado)
    while True: schedule.run_pending(); time.sleep(60)

if TOKEN:
    app = Flask(__name__)
    @app.route('/')
    def home(): return "QuantBot V50 (SafeText)"

    if __name__ == "__main__":
        threading.Thread(target=loop).start()
        threading.Thread(target=thread_agendamento).start()
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
        bot.infinity_polling()