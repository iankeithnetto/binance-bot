from flask import Flask, jsonify
from datetime import datetime
import os

app = Flask(__name__)

start_time = datetime.now()
status = {"running": True, "balance": 0, "trades": 0, "pnl": 0}

@app.route('/')
def home():
    uptime = str(datetime.now() - start_time).split('.')[0]
    return f"""
    <html>
    <head><title>Binance Bot</title>
    <style>
        body {{ background:#0a0a0a; color:#00ff00; font-family:monospace; padding:50px; text-align:center; }}
        h1 {{ color:#00ff00; }}
        .box {{ border:1px solid #00ff00; padding:20px; margin:20px auto; max-width:400px; text-align:left; }}
        .green {{ color:#00ff00; }}
    </style></head>
    <body>
        <h1>🤖 Binance Trading Bot</h1>
        <div class="box">
            <p>Status: <span class="green">● Running</span></p>
            <p>Uptime: {uptime}</p>
            <p>Balance: ${status['balance']:,.2f}</p>
            <p>Trades: {status['trades']}</p>
            <p>P&L: ${status['pnl']:,.2f}</p>
        </div>
        <p style="color:#555;">Auto-refreshes every 30 seconds</p>
        <meta http-equiv="refresh" content="30">
    </body>
    </html>
    """

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "uptime": str(datetime.now() - start_time)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
