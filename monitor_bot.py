import os
import shutil
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
import yfinance as yf
import pandas_ta as ta
import time
import threading
from flask import Flask
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. CONFIGURAÇÕES
# ==============================================================================
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"
CHAT_ID = "1116977306"  
NOME_PLANILHA_GOOGLE = "Trades do Robô Quant" 

bot = telebot.TeleBot(TOKEN)

# ==============================================================================
# 2. FUNÇÕES DO GOOGLE SHEETS (O CÉREBRO)
# ==============================================================================
def conectar_google():
    try:
        gc = gspread.service_account(filename='creds.json')
        sh = gc.open(NOME_PLANILHA_GOOGLE)
        return sh
    except Exception as e:
        print(f"❌ Erro ao conectar Google: {e}")
        return None

def ler_carteira_do_sheets():
    sh = conectar_google()
    if sh:
        try:
            worksheet = sh.worksheet("Carteira") # Busca a aba 'Carteira'
            lista = worksheet.col_values(1) # Lê a coluna A inteira
            # Filtra linhas vazias se houver
            lista = [x.upper().strip() for x in lista if x.strip()]
            return lista
        except:
            print("⚠️ Aba 'Carteira' não encontrada. Usando lista de emergência.")
            return ["BTC-USD", "ETH-USD"] # Backup
    return []

def adicionar_ativo_sheets(novo_ativo):
    sh = conectar_google()
    if sh:
        try:
            worksheet = sh.worksheet("Carteira")
            # Verifica se já existe para não duplicar
            lista_atual = worksheet.col_values(1)
            if novo_ativo in lista_atual:
                return "Já existe"
            
            worksheet.append_row([novo_ativo])
            return "Sucesso"
        except Exception as e:
            return f"Erro: {e}"
    return "Erro Conexão"

def remover_ativo_sheets(ativo_remover):
    sh = conectar_google()
    if sh:
        try:
            worksheet = sh.worksheet("Carteira")
            cell = worksheet.find(ativo_remover)
            if cell:
                worksheet.delete_rows(cell.row)
                return "Sucesso"
            else:
                return "Não encontrado"
        except Exception as e:
            return f"Erro: {e}"
    return "Erro Conexão"

def registrar_trade_sheets(ativo, tipo, preco):
    sh = conectar_google()
    if sh:
        try:
            worksheet = sh.sheet1 # Primeira aba (Log de Trades)
            data_hoje = datetime.now().strftime('%d/%m/%Y %H:%M')
            worksheet.append_row([data_hoje, ativo, tipo, preco, "", "", "Aberta"])
            return True
        except:
            return False
    return False

# ==============================================================================
# 3. COMANDOS DO TELEGRAM (INTERAÇÃO)
# ==============================================================================

@bot.message_handler(commands=['ativos', 'lista'])
def comando_listar(message):
    carteira_atual = ler_carteira_do_sheets()
    qtd = len(carteira_atual)
    texto = f"📋 **Carteira Monitorada ({qtd}):**\n\n"
    for ativo in carteira_atual:
        texto += f"• `{ativo}`\n"
    texto += "\nPara adicionar: /add CODIGO\nPara remover: /del CODIGO"
    bot.reply_to(message, texto, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def comando_adicionar(message):
    try:
        # Pega o texto depois do comando. Ex: "/add WEGE3.SA" -> "WEGE3.SA"
        novo_ativo = message.text.split()[1].upper().strip()
        bot.reply_to(message, f"⏳ Adicionando {novo_ativo} na planilha...")
        
        resultado = adicionar_ativo_sheets(novo_ativo)
        
        if resultado == "Sucesso":
            bot.reply_to(message, f"✅ **{novo_ativo}** adicionado! Será analisado no próximo ciclo.")
        elif resultado == "Já existe":
            bot.reply_to(message, f"⚠️ {novo_ativo} já está na lista.")
        else:
            bot.reply_to(message, f"❌ Erro: {resultado}")
    except:
        bot.reply_to(message, "Use assim: `/add PETR4.SA`", parse_mode="Markdown")

@bot.message_handler(commands=['del', 'remove'])
def comando_remover(message):
    try:
        ativo_remover = message.text.split()[1].upper().strip()
        bot.reply_to(message, f"⏳ Removendo {ativo_remover}...")
        
        resultado = remover_ativo_sheets(ativo_remover)
        
        if resultado == "Sucesso":
            bot.reply_to(message, f"🗑️ **{ativo_remover}** removido da lista.")
        elif resultado == "Não encontrado":
            bot.reply_to(message, f"⚠️ {ativo_remover} não estava na lista.")
        else:
            bot.reply_to(message, f"❌ Erro: {resultado}")
    except:
        bot.reply_to(message, "Use assim: `/del PETR4.SA`", parse_mode="Markdown")

# Handler do Botão de Compra
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    dados = call.data.split("|")
    if dados[0] == "COMPRA":
        bot.answer_callback_query(call.id, "Registrando...")
        if registrar_trade_sheets(dados[1], "Compra Simulada", dados[2]):
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                text=f"{call.message.text}\n\n✅ REGISTRADO NA PLANILHA!")
        else:
            bot.answer_callback_query(call.id, "❌ Erro ao salvar.")

# ==============================================================================
# 4. LOOP DE ANÁLISE (SCANNER)
# ==============================================================================
def enviar_alerta(ativo, preco):
    markup = InlineKeyboardMarkup()
    botao = InlineKeyboardButton(text=f"📝 Simular Compra @ {preco:.2f}", callback_data=f"COMPRA|{ativo}|{preco:.2f}")
    markup.add(botao)
    bot.send_message(CHAT_ID, f"🟢 **OPORTUNIDADE**\n\nAtivo: {ativo}\nPreço: {preco:.2f}\nCruzamento de Médias", reply_markup=markup, parse_mode="Markdown")

def analisar_mercado():
    while True:
        hora = datetime.now().strftime('%H:%M')
        print(f"\n--- Ciclo {hora} ---")
        
        # 1. ATUALIZA A LISTA DIRETO DA PLANILHA NO INÍCIO DE CADA CICLO
        carteira_vigente = ler_carteira_do_sheets()
        print(f"Ativos carregados: {len(carteira_vigente)}")

        cache = Path.home() / ".cache" / "py-yfinance"
        if cache.exists(): shutil.rmtree(cache)

        encontrou = False
        for ativo in carteira_vigente:
            try:
                # Validação rápida de string vazia
                if len(ativo) < 3: continue
                
                df = yf.Ticker(ativo).history(period="5d", interval="15m")
                if len(df) < 22: continue
                
                sma9 = ta.sma(df['Close'], length=9).iloc[-1]
                sma21 = ta.sma(df['Close'], length=21).iloc[-1]
                sma9_prev = ta.sma(df['Close'], length=9).iloc[-2]
                sma21_prev = ta.sma(df['Close'], length=21).iloc[-2]
                
                if (sma9 > sma21) and (sma9_prev <= sma21_prev):
                    enviar_alerta(ativo, df['Close'].iloc[-1])
                    encontrou = True
                
                time.sleep(1.5)
            except Exception as e:
                print(f"Erro {ativo}: {e}")

        if not encontrou:
             bot.send_message(CHAT_ID, f"📉 Monitor ({hora}): Nada nas {len(carteira_vigente)} ações. Vigia Segue.")

        print("Dormindo 15 minutos...")
        time.sleep(900)

# ==============================================================================
# 5. SERVIDOR WEB
# ==============================================================================
app = Flask(__name__)
@app.route('/')
def home(): return "Robô v6.0 - Gerenciamento Dinâmico"

if __name__ == "__main__":
    t_flask = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000))))
    t_flask.start()
    
    t_market = threading.Thread(target=analisar_mercado)
    t_market.start()
    
    bot.infinity_polling()