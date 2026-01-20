import os
import shutil
import telebot # A nova biblioteca de botões
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread # O carteiro do Google
import yfinance as yf
import pandas_ta as ta
import time
import random
import threading
from flask import Flask
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. CONFIGURAÇÕES (PREENCHA AQUI!)
# ==============================================================================
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"      
CHAT_ID = "1116977306"  
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant" # Nome exato da sua planilha

# Ativos para monitorar
CARTEIRA = [
    # Cripto (24h)
    "BTC-USD", "ETH-USD", "SOL-USD", 
    "LINK-USD", "AVAX-USD", "ADA-USD", "XRP-USD", # <-- As novas Altcoins
    
    # Ações Brasil (B3)
    "PETR4.SA", "VALE3.SA", "WEGE3.SA", "PRIO3.SA",
    
    # Ações EUA (Tech & Quantum)
    "AAPL", "NVDA", "MSFT", "TSLA",
    "IONQ", "RGTI" # <-- As novas de Quantum
]

# Conecta ao Bot do Telegram
bot = telebot.TeleBot(TOKEN)

# ==============================================================================
# 2. SISTEMA GOOGLE SHEETS (O ESCRITURÁRIO)
# ==============================================================================
def registrar_na_planilha(ativo, tipo, preco):
    try:
        # Conecta usando o arquivo creds.json que está na pasta
        gc = gspread.service_account(filename='creds.json')
        sh = gc.open(NOME_PLANILHA_GOOGLE)
        worksheet = sh.sheet1 # Primeira aba
        
        data_hoje = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        # Adiciona a linha nova
        # Colunas: Data | Ativo | Tipo | Preço Entrada | Preço Saída | Resultado | Status
        worksheet.append_row([data_hoje, ativo, tipo, preco, "", "", "Aberta"])
        return True
    except Exception as e:
        print(f"❌ Erro Google: {e}")
        return False

# ==============================================================================
# 3. O OUVIDO DO ROBÔ (ESCUTA OS BOTÕES)
# ==============================================================================
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    # O botão manda dados assim: "COMPRA|PETR4.SA|30.50"
    dados = call.data.split("|")
    acao = dados[0]
    ativo = dados[1]
    preco = dados[2]

    if acao == "COMPRA":
        bot.answer_callback_query(call.id, "Registrando na planilha...")
        
        sucesso = registrar_na_planilha(ativo, "Compra Simulada", preco)
        
        if sucesso:
            # Edita a mensagem para mostrar que deu certo
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"{call.message.text}\n\n✅ REGISTRADO NA PLANILHA!"
            )
        else:
            bot.answer_callback_query(call.id, "❌ Erro ao salvar na planilha.")

# ==============================================================================
# 4. O CÉREBRO ANALÍTICO (LOOP DE MERCADO)
# ==============================================================================
def enviar_alerta_com_botao(ativo, preco):
    markup = InlineKeyboardMarkup()
    # Cria o botão com os dados escondidos (COMPRA|ATIVO|PRECO)
    botao = InlineKeyboardButton(
        text=f"📝 Simular Compra @ {preco:.2f}", 
        callback_data=f"COMPRA|{ativo}|{preco:.2f}"
    )
    markup.add(botao)
    
    msg = f"🟢 **OPORTUNIDADE DETECTADA**\n\nAtivo: {ativo}\nPreço: {preco:.2f}\nSetup: Cruzamento de Médias (9x21)"
    
    try:
        bot.send_message(CHAT_ID, msg, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Erro Telegram: {e}")

def analisar_mercado():
    while True:
        hora_atual = datetime.now().strftime('%H:%M')
        print(f"\n--- Varredura Iniciada ({hora_atual}) ---")
        
        # Limpa cache para evitar dados velhos
        cache_path = Path.home() / ".cache" / "py-yfinance"
        if cache_path.exists(): shutil.rmtree(cache_path)

        encontrou_algo = False

        for ativo in CARTEIRA:
            try:
                ticker = yf.Ticker(ativo)
                df = ticker.history(period="6mo")
                
                if len(df) < 22: continue
                
                # Cálculo das Médias
                media_curta = ta.sma(df['Close'], length=9).iloc[-1]
                media_longa = ta.sma(df['Close'], length=21).iloc[-1]
                media_curta_ontem = ta.sma(df['Close'], length=9).iloc[-2]
                media_longa_ontem = ta.sma(df['Close'], length=21).iloc[-2]
                preco_atual = df['Close'].iloc[-1]
                
                # LÓGICA DE GATILHO:
                # Só avisa se cruzou HOJE (ontem estava baixo, hoje está alto)
                cruzou_pra_cima = (media_curta > media_longa) and (media_curta_ontem <= media_longa_ontem)
                
                if cruzou_pra_cima:
                    print(f"🚀 {ativo}: DISPARANDO ALERTA")
                    enviar_alerta_com_botao(ativo, preco_atual)
                    encontrou_algo = True
                
                time.sleep(2) # Pausa leve entre ativos

            except Exception as e:
                print(f"Erro em {ativo}: {e}")

        if not encontrou_algo:
             # Heartbeat simples (sem botão) só para avisar que está vivo
             bot.send_message(CHAT_ID, f"📉 Monitor ({hora_atual}): Mercado calmo. Sigo vigiando.")

        print("Dormindo 60 minutos...")
        time.sleep(3600)

# ==============================================================================
# 5. O CORAÇÃO (SERVIDOR WEB + THREADS)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Robô Trader v5.0 - Com Google Sheets e Botões!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    # 1. Inicia o Servidor Web (para o Render) em uma linha paralela
    t_flask = threading.Thread(target=run_flask)
    t_flask.start()

    # 2. Inicia o Scanner de Mercado em outra linha paralela
    t_market = threading.Thread(target=analisar_mercado)
    t_market.start()

    print("✅ Robô Iniciado! Escutando Telegram...")
    bot.send_message(CHAT_ID, "🤖 Monitor v5.0 Online!\nAgora com botões de registro no Planilhas.")
    
    # 3. O programa principal fica aqui ESCUTANDO os botões eternamente
    bot.infinity_polling()