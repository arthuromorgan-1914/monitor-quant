import requests

print("--- DIAGNÓSTICO DO TELEGRAM ---")

# ==========================================
# CONFIRA SE NÃO TEM ESPAÇOS EM BRANCO EXTRAS
TOKEN = "8487773967:AAGUMCgvgUKyPYRQFXzeReg-T5hzu6ohDJw"      
CHAT_ID = "1116977306"  
# ==========================================

def testar_envio():
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    
    # Teste 1: Texto Simples (Sem formatação)
    # Isso elimina a chance de ser erro de Markdown (*, _)
    print(f"\nTentativa 1: Texto Simples para ID {CHAT_ID}...")
    data_simples = {
        "chat_id": CHAT_ID, 
        "text": "Teste de Diagnóstico: Se você ler isso, as chaves estão certas."
    }
    
    resp = requests.post(url, data=data_simples)
    
    print(f"Status Code: {resp.status_code}")
    if resp.status_code == 200:
        print("✅ SUCESSO! O problema era a formatação (Markdown).")
    else:
        print(f"❌ ERRO: O Telegram recusou.")
        print(f"   Mensagem do Servidor: {resp.text}")

    # Teste 2: Verificar se as chaves batem
    if resp.status_code == 401:
        print("\n⚠️ ANÁLISE: Erro 401 significa TOKEN errado.")
        print("   Verifique se copiou o token do BotFather inteiro.")
    
    if resp.status_code == 400:
        print("\n⚠️ ANÁLISE: Erro 400 geralmente é CHAT_ID errado.")
        print("   Verifique se o número do ID está correto (userinfobot).")

testar_envio()