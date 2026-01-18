import yfinance as yf
import traceback

print("--- INICIANDO DIAGNÓSTICO PROFUNDO ---")
print(f"Versão do yfinance: {yf.__version__}")

target = "PETR4.SA"

try:
    print(f"\n1. Tentando conectar em {target}...")
    ticker = yf.Ticker(target)
    
    # Tentamos pegar 5 dias. 
    # Se falhar aqui, o traceback vai nos dizer EXATAMENTE o motivo.
    dados = ticker.history(period="5d")
    
    if dados.empty:
        print("❌ Resultado: Tabela VAZIA (Conectou mas não veio nada).")
        print("   Isso geralmente indica bloqueio de IP ou falta de dados no Yahoo.")
    else:
        print(f"✅ SUCESSO! Conexão restabelecida.")
        print(f"   Preço atual: {dados['Close'].iloc[-1]:.2f}")

except Exception:
    print("❌ ERRO CRÍTICO ENCONTRADO (O culpado é este):")
    traceback.print_exc()

print("\n--- FIM DO DIAGNÓSTICO ---")