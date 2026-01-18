import requests

# --- SUAS CHAVES (COLE AQUI) ---
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"  # Ex: "7123123:AAF..."
CHAT_ID = "1116977306"  # Ex: "123456789"
# -------------------------------

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dados = {"chat_id": CHAT_ID, "text": mensagem}
    try:
        resposta = requests.post(url, data=dados)
        if resposta.status_code == 200:
            print("✅ Mensagem enviada com sucesso!")
        else:
            print(f"❌ Erro ao enviar: {resposta.text}")
    except Exception as e:
        print(f"Erro de conexão: {e}")

# Teste
print("Tentando enviar mensagem...")
enviar_telegram("Olá Guilherme! Sou seu Robô Quant. O sistema de alertas está ativo! 🚀")