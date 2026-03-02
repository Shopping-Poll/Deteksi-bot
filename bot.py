from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters
)
from datetime import datetime
import os
import logging
import sqlite3
import hashlib
import signal
import sys
import pytz
from dotenv import load_dotenv

# Setup logging dengan timezone Jakarta
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Set timezone untuk logging
logging.Formatter.converter = lambda *args: datetime.now(pytz.timezone('Asia/Jakarta')).timetuple()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class DuplicateDetectorBot:
    def __init__(self):
        # Load environment variables
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        load_dotenv(env_path)
        
        self.token = os.environ.get("BOT_TOKEN")
        if not self.token:
            raise Exception("❌ BOT_TOKEN belum di-set")
        
        # Set zona waktu Jakarta
        self.timezone = pytz.timezone('Asia/Jakarta')
        
        # Inisialisasi struktur data in-memory
        self.group_messages = {}
        
        # Setup database sebagai backup persistence
        self.setup_database()
        
        # Setup signal handlers untuk graceful shutdown
        self.setup_signal_handlers()
        
        logger.info("🤖 Bot deteksi duplikat initialized dengan timezone Jakarta")
    
    def setup_database(self):
        """Setup database SQLite sebagai backup persistence"""
        db_path = os.getenv('DB_PATH', 'messages.db')
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_hash TEXT,
                message_text TEXT,
                user_id INTEGER,
                user_name TEXT,
                timestamp DATETIME,
                UNIQUE(chat_id, message_hash, timestamp)
            )
        ''')
        self.conn.commit()
        logger.info(f"📊 Database initialized at: {db_path}")
        
        # Load existing data dari database ke memory
        self.load_from_database()
    
    def load_from_database(self):
        """Load data dari database ke memory structure"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT chat_id, message_text, user_name, timestamp 
                FROM messages 
                ORDER BY timestamp ASC
            ''')
            
            for chat_id, message_text, user_name, timestamp in cursor.fetchall():
                if chat_id not in self.group_messages:
                    self.group_messages[chat_id] = {}
                
                if message_text not in self.group_messages[chat_id]:
                    self.group_messages[chat_id][message_text] = []
                
                self.group_messages[chat_id][message_text].append({
                    "user": user_name,
                    "time": timestamp
                })
            
            logger.info(f"✅ Loaded {cursor.rowcount} messages from database")
        except Exception as e:
            logger.error(f"Error loading from database: {e}")
    
    def setup_signal_handlers(self):
        """Handle shutdown signals untuk cleanup"""
        def signal_handler(signum, frame):
            logger.info("🛑 Received shutdown signal")
            self.cleanup()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def cleanup(self):
        """Cleanup sebelum shutdown"""
        logger.info("🔚 Cleaning up...")
        if hasattr(self, 'conn'):
            self.conn.close()
            logger.info("📊 Database connection closed")
    
    def get_current_time(self):
        """Mendapatkan waktu saat ini dalam zona waktu Jakarta"""
        return datetime.now(self.timezone)
    
    def format_time_for_db(self, dt=None):
        """Format waktu untuk penyimpanan di database"""
        if dt is None:
            dt = self.get_current_time()
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    
    def format_time_display(self, dt_str):
        """Format waktu untuk ditampilkan ke user"""
        try:
            # Parse waktu dari database/struktur
            dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            # Pastikan waktu memiliki timezone Jakarta
            if dt.tzinfo is None:
                dt = self.timezone.localize(dt)
            return dt.strftime('%Y/%m/%d %H:%M:%S')
        except Exception as e:
            logger.error(f"Error formatting time: {e}")
            return dt_str
    
    def generate_message_hash(self, text):
        """Generate hash untuk pesan (optional, untuk database)"""
        normalized_text = ' '.join(text.lower().split())
        return hashlib.md5(normalized_text.encode()).hexdigest()
    
    async def detect_duplicate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler utama untuk mendeteksi pesan duplikat"""
        try:
            if not update.message or not update.message.text:
                return

            chat_id = update.message.chat_id
            text = update.message.text.strip()  # Simpan original text untuk display
            text_lower = text.lower()  # Untuk perbandingan case-insensitive
            user = update.message.from_user.first_name or str(update.message.from_user.id)
            user_id = update.message.from_user.id
            time_now = self.format_time_for_db()
            time_display = self.format_time_display(time_now)

            # Skip pesan terlalu pendek (opsional, bisa disesuaikan)
            if len(text) < 3:
                return

            # Inisialisasi struktur untuk chat_id jika belum ada
            if chat_id not in self.group_messages:
                self.group_messages[chat_id] = {}

            # Simpan ke database sebagai backup
            try:
                cursor = self.conn.cursor()
                message_hash = self.generate_message_hash(text)
                cursor.execute('''
                    INSERT INTO messages 
                    (chat_id, message_hash, message_text, user_id, user_name, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (chat_id, message_hash, text, user_id, user, time_now))
                self.conn.commit()
            except sqlite3.IntegrityError:
                # Duplicate di database, skip
                pass
            except Exception as e:
                logger.error(f"Database error: {e}")

            # Cek apakah ini pesan pertama untuk teks ini di grup
            if text_lower not in self.group_messages[chat_id]:
                # Pesan pertama
                self.group_messages[chat_id][text_lower] = [
                    {"user": user, "time": time_now, "original_text": text}
                ]
                logger.info(f"✅ First message in chat {chat_id}: {text[:50]}...")
                return

            # Sudah pernah ada → DUPLIKAT
            history = self.group_messages[chat_id][text_lower]
            
            # Cek apakah ini duplikat dari user yang sama dalam waktu dekat (opsional)
            last_entry = history[-1] if history else None
            if last_entry and last_entry['user'] == user:
                # Cek apakah dalam 5 menit terakhir
                last_time = datetime.strptime(last_entry['time'], '%Y-%m-%d %H:%M:%S')
                current_time = datetime.strptime(time_now, '%Y-%m-%d %H:%M:%S')
                if (current_time - last_time).total_seconds() < 300:  # 5 menit
                    logger.info(f"⏭️ Skipping rapid duplicate from same user in chat {chat_id}")
                    return

            # Tambahkan ke history
            history.append({
                "user": user, 
                "time": time_now,
                "original_text": text
            })

            # Batasi history per pesan (opsional, simpan 10 terakhir)
            if len(history) > 10:
                history = history[-10:]
                self.group_messages[chat_id][text_lower] = history

            # Bangun pesan laporan yang lebih informatif
            report = "❌NOMOR SUDAH PERNAH JOIN❌\n"
            report += f"📝NOMOR : {text}\n"
            report += "─" * 30 + "\n\n"

            for idx, item in enumerate(history):
                time_formatted = self.format_time_display(item['time'])
                if idx == 0:
                    report += f"📌 PERTAMA KALI:\n"
                elif idx == len(history) - 1:
                    report += f"\n🔴 SAAT INI:\n"
                else:
                    report += f"\n📋 KE-{idx + 1}:\n"
                
                report += f"👤 {item['user']}\n"
                report += f"⏰ {time_formatted} WIB\n"
                
                # Tampilkan preview pesan jika berbeda dari pesan utama
                if 'original_text' in item and item['original_text'] != text:
                    report += f"💬 {item['original_text'][:50]}...\n"

            report += "\n" + "─" * 30
            report += f"\n📊 Total {len(history)} kali dikirim"

            await update.message.reply_text(report)
            logger.info(f"🚫 Duplicate detected in chat {chat_id}: {text[:50]}...")

            # Bersihkan pesan lama dari database (lebih dari 30 hari)
            try:
                cursor = self.conn.cursor()
                cursor.execute('''
                    DELETE FROM messages 
                    WHERE timestamp < datetime("now", "-30 days")
                ''')
                self.conn.commit()
            except Exception as e:
                logger.error(f"Error cleaning database: {e}")

        except Exception as e:
            logger.error(f"Error in detect_duplicate: {e}")
    
    def run(self):
        """Menjalankan bot"""
        try:
            app = ApplicationBuilder().token(self.token).build()
            
            # Handler untuk pesan teks di grup
            app.add_handler(
                MessageHandler(filters.TEXT & filters.GROUPS, self.detect_duplicate)
            )
            
            # Handler untuk pesan teks di private chat (opsional)
            app.add_handler(
                MessageHandler(filters.TEXT & filters.PRIVATE, self.detect_duplicate)
            )

            current_time = self.format_time_display(self.format_time_for_db())
            logger.info(f"🤖 Bot deteksi duplikat aktif pada {current_time} WIB")
            logger.info("📝 Menunggu pesan...")
            
            # Jalankan bot dengan graceful shutdown
            app.run_polling(
                drop_pending_updates=True,
                close_loop=False
            )
            
        except Exception as e:
            logger.error(f"❌ Error running bot: {e}")
            self.cleanup()
            sys.exit(1)

def main():
    """Entry point"""
    bot = DuplicateDetectorBot()
    bot.run()

if __name__ == "__main__":
    main()
