import sys
sys.path.insert(0, '.')

# Importar la lógica de detección directamente desde bot_señales
from bot_señales import es_señal

mensajes = [
    # Señales válidas
    "XAUUSD BUY 2345.50\nSL: 2340.00\nTP: 2355.00",
    "GOLD SELL NOW\nTarget: 2300\nStop: 2360",
    "GBPUSD LONG entry 1.2750 TP 1.2800 SL 1.2720",
    "🔥 EURUSD BUY 1.0850\n💰 TP1: 1.0880\n🛑 SL: 1.0820",
    "SHORT BTCUSD @ 65000\nSL 66500 | TP 62000",

    # Deben ignorarse
    "Good morning traders! Have a great week 💪",
    "El mercado abre en 30 minutos, prepárense",
    "📢 Únete a nuestro canal premium",
    "NFP data coming out today, stay cautious",
    "1234567",  # número sin contexto
]

print(f"{'RESULTADO':<12} {'MOTIVO':<45} MENSAJE")
print("─" * 100)

for msg in mensajes:
    valido, motivo = es_señal(msg)
    resultado = "✅ REENVIAR" if valido else "❌ IGNORAR"
    preview = msg.split('\n')[0][:50]
    print(f"{resultado:<12} {motivo:<45} {preview!r}")
