from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters
)
from datetime import datetime
import os

# Struktur:
# {
#   chat_id: {
#       "isi pesan": [
#           {"user": "Andre", "time": "2026-02-22 10:01:02"},
#           {"user": "Budi", "time": "2026-02-22 10:05:11"},
#       ]
#   }
# }
group_messages = {}

def now_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

async def detect_duplicate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    text = update.message.text.strip().lower()
    user = update.message.from_user.first_name
    time_now = now_time()

    if chat_id not in group_messages:
        group_messages[chat_id] = {}

    if text not in group_messages[chat_id]:
        # Pesan pertama
        group_messages[chat_id][text] = [
            {"user": user, "time": time_now}
        ]
        return

    # Sudah pernah ada → DUPLIKAT
    history = group_messages[chat_id][text]
    history.append({"user": user, "time": time_now})

    # Bangun pesan laporan
    report = "❌DETEKSI DITEMUKAN❌\n"
    report += f"Isi pesan : {update.message.text}\n\n"

    for idx, item in enumerate(history):
        if idx == 0:
            report += f"{item['user']} : Pengirim pertama kali\n"
            report += f"{item['time']}\n"
        elif idx == len(history) - 1:
            report += f"{item['user']} : Pengirim saat ini\n"
            report += f"{item['time']}\n"
        else:
            report += f"{item['user']} : Pengirim ke-{idx+1}\n"
            report += f"{item['time']}\n"

    await update.message.reply_text(report)

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise Exception("BOT_TOKEN belum di-set")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(
        MessageHandler(filters.TEXT & filters.GROUPS, detect_duplicate)
    )

    print("🤖 Bot deteksi duplikat aktif...")
    app.run_polling()

if __name__ == "__main__":
    main()