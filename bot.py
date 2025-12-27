import os
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client

# ================= НАСТРОЙКА =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем ключи из переменных окружения Railway
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Проверка переменных
if not all([SUPABASE_URL, SUPABASE_KEY, BOT_TOKEN]):
    missing = []
    if not SUPABASE_URL: missing.append("SUPABASE_URL")
    if not SUPABASE_KEY: missing.append("SUPABASE_KEY")
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    logger.error(f"❌ Отсутствуют переменные окружения: {', '.join(missing)}")
    exit(1)

# Инициализация Supabase клиента
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Supabase клиент инициализирован")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Supabase: {e}")
    exit(1)

# ================= БАЗА ДАННЫХ =================
class DatabaseManager:
    """Менеджер для работы с Supabase"""
    
    @staticmethod
    async def get_user_nick(telegram_id: int) -> str:
        """Получить ник пользователя"""
        try:
            response = supabase.table('users') \
                .select('game_nick') \
                .eq('telegram_id', telegram_id) \
                .execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]['game_nick']
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения ника: {e}")
            return None
    
    @staticmethod
    async def save_user_nick(telegram_id: int, username: str, name: str, game_nick: str) -> bool:
        """Сохранить или обновить ник пользователя"""
        try:
            # Проверяем существующего пользователя
            existing = supabase.table('users') \
                .select('telegram_id') \
                .eq('telegram_id', telegram_id) \
                .execute()
            
            user_data = {
                'telegram_id': telegram_id,
                'telegram_username': username,
                'telegram_name': name,
                'game_nick': game_nick,
                'updated_at': datetime.now().isoformat()
            }
            
            if existing.data and len(existing.data) > 0:
                # Обновляем существующего
                supabase.table('users') \
                    .update(user_data) \
                    .eq('telegram_id', telegram_id) \
                    .execute()
                logger.info(f"📝 Обновлен ник для {telegram_id}: {game_nick}")
            else:
                # Добавляем нового
                user_data['created_at'] = datetime.now().isoformat()
                supabase.table('users').insert(user_data).execute()
                logger.info(f"✅ Добавлен новый пользователь {telegram_id}: {game_nick}")
            
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения ника: {e}")
            return False
    
    @staticmethod
    async def get_stats():
        """Получить статистику"""
        try:
            response = supabase.table('users') \
                .select('telegram_id', count='exact') \
                .execute()
            
            total = response.count if hasattr(response, 'count') else len(response.data)
            
            # Получаем топ-5 последних пользователей
            recent = supabase.table('users') \
                .select('telegram_name, game_nick, created_at') \
                .order('created_at', desc=True) \
                .limit(5) \
                .execute()
            
            return {
                'total': total or 0,
                'recent': recent.data if recent.data else []
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return {'total': 0, 'recent': []}
    
    @staticmethod
    async def search_nick(search_text: str):
        """Поиск по нику или имени"""
        try:
            response = supabase.table('users') \
                .select('telegram_name, game_nick') \
                .or_(f'game_nick.ilike.%{search_text}%,telegram_name.ilike.%{search_text}%') \
                .limit(10) \
                .execute()
            
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"❌ Ошибка поиска: {e}")
            return []

# ================= КОМАНДЫ БОТА =================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    
    # Получаем текущий ник
    current_nick = await DatabaseManager.get_user_nick(user.id)
    
    welcome_text = (
        f"👋 **Привет, {user.first_name}!**\n\n"
        f"Я бот для отображения игровых ников в Telegram группах.\n\n"
    )
    
    if current_nick:
        welcome_text += (
            f"✅ Твой текущий ник: **{current_nick}**\n\n"
            f"📝 Изменить: `/nick НовыйНик`\n"
            f"📊 Статистика: `/stats`\n"
            f"🔍 Найти игрока: `/find ник`\n\n"
        )
    else:
        welcome_text += (
            f"🎮 **Чтобы начать:**\n"
            f"1. Установи игровой ник: `/nick ТвойНик`\n"
            f"2. Добавь меня в группу как администратора\n"
            f"3. Пиши в группе - я подпишу твои сообщения!\n\n"
            f"📝 Пример: `/nick КрутойИгрок`\n\n"
        )
    
    welcome_text += (
        f"⚙️ **Техническая информация:**\n"
        f"• База данных: Supabase\n"
        f"• Хостинг: Railway\n"
        f"• Код: GitHub\n\n"
        f"Напиши `/help` для всех команд"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def nick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /nick - установка/изменение ника"""
    user = update.effective_user
    
    # Если не указан ник - показываем текущий
    if not context.args:
        current_nick = await DatabaseManager.get_user_nick(user.id)
        if current_nick:
            await update.message.reply_text(
                f"🎮 **Твой текущий ник:** {current_nick}\n\n"
                f"Чтобы изменить, напиши:\n"
                f"`/nick НовыйИгровойНик`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "📝 **Установи игровой ник:**\n\n"
                "Напиши: `/nick ТвойНик`\n\n"
                "Примеры:\n"
                "• `/nick ProPlayer`\n"
                "• `/nick КрутойГеймер`\n"
                "• `/nick Охотник23`\n\n"
                "⚠️ **Требования:**\n"
                "• От 2 до 32 символов\n"
                "• Без запрещенных символов",
                parse_mode='Markdown'
            )
        return
    
    # Получаем ник из аргументов
    game_nick = ' '.join(context.args).strip()
    
    # Валидация ника
    if len(game_nick) < 2:
        await update.message.reply_text("❌ Слишком короткий ник. Минимум 2 символа.")
        return
    
    if len(game_nick) > 32:
        await update.message.reply_text("❌ Слишком длинный ник. Максимум 32 символа.")
        return
    
    # Запрещенные символы
    forbidden_chars = ['<', '>', '&', '"', "'", '`', '\\']
    for char in forbidden_chars:
        if char in game_nick:
            await update.message.reply_text(f"❌ Ник содержит запрещенный символ: {char}")
            return
    
    # Сохраняем в базу данных
    success = await DatabaseManager.save_user_nick(
        user.id, 
        user.username, 
        user.first_name, 
        game_nick
    )
    
    if success:
        # Получаем статистику
        stats = await DatabaseManager.get_stats()
        
        await update.message.reply_text(
            f"✅ **Отлично, {user.first_name}!**\n\n"
            f"🎮 Твой игровой ник: **{game_nick}**\n\n"
            f"📊 Всего игроков в базе: **{stats['total']}**\n\n"
            f"**Что дальше:**\n"
            f"1. Добавь меня в группу как администратора\n"
            f"2. Дай права на удаление сообщений\n"
            f"3. Пиши в группе - я подпишу твои сообщения!\n\n"
            f"🔄 Изменить ник: `/nick НовыйНик`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ Не удалось сохранить ник. Попробуй позже или обратись к администратору."
        )

async def mynick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mynick - показать мой ник"""
    user = update.effective_user
    current_nick = await DatabaseManager.get_user_nick(user.id)
    
    if current_nick:
        # Получаем дату регистрации
        try:
            response = supabase.table('users') \
                .select('created_at') \
                .eq('telegram_id', user.id) \
                .execute()
            
            reg_date = ""
            if response.data and len(response.data) > 0:
                created = response.data[0]['created_at']
                if created:
                    date_obj = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    reg_date = date_obj.strftime(" (%d.%m.%Y)")
        except:
            reg_date = ""
        
        await update.message.reply_text(
            f"🎮 **Твой игровой ник:** {current_nick}{reg_date}\n\n"
            f"Изменить: `/nick НовыйНик`\n"
            f"Посмотреть статистику: `/stats`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ У тебя еще нет игрового ника.\n\n"
            "Установи его командой:\n"
            "`/nick ТвойИгровойНик`\n\n"
            "Пример: `/nick Игрок007`",
            parse_mode='Markdown'
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats - статистика"""
    stats = await DatabaseManager.get_stats()
    
    response = (
        f"📊 **Статистика бота:**\n\n"
        f"👥 **Всего игроков:** {stats['total']}\n"
        f"🗄️ **База данных:** Supabase\n"
        f"🚂 **Хостинг:** Railway\n"
        f"💾 **Хранилище:** PostgreSQL\n\n"
    )
    
    if stats['recent']:
        response += "🆕 **Последние игроки:**\n"
        for idx, user in enumerate(stats['recent'][:5], 1):
            # Форматируем дату
            try:
                date_obj = datetime.fromisoformat(user['created_at'].replace('Z', '+00:00'))
                date_str = date_obj.strftime("%d.%m")
            except:
                date_str = "сегодня"
            
            response += f"{idx}. {user['game_nick']} ({user['telegram_name']}) - {date_str}\n"
    
    response += "\n🔍 Найти игрока: `/find ник`"
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /find - поиск игрока"""
    if not context.args:
        await update.message.reply_text(
            "🔍 **Поиск игроков:**\n\n"
            "Напиши: `/find ник_или_имя`\n\n"
            "Примеры:\n"
            "• `/find pro` - найдет ProPlayer, ProGamer и т.д.\n"
            "• `/find алекс` - найдет Алексей, Александр\n"
            "• `/find 007` - найдет по цифрам в нике",
            parse_mode='Markdown'
        )
        return
    
    search_text = ' '.join(context.args)
    results = await DatabaseManager.search_nick(search_text)
    
    if results:
        response = f"🔍 **Найдено по запросу '{search_text}':**\n\n"
        for idx, user in enumerate(results[:10], 1):
            response += f"{idx}. **{user['game_nick']}** ({user['telegram_name']})\n"
        
        if len(results) > 10:
            response += f"\n... и еще {len(results) - 10} результатов"
    else:
        response = f"❌ По запросу '{search_text}' ничего не найдено.\n\nПопробуй другой запрос."
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - справка"""
    help_text = (
        "🆘 **Доступные команды:**\n\n"
        "`/start` - Начало работы с ботом\n"
        "`/nick [ник]` - Установить/изменить игровой ник\n"
        "`/mynick` - Показать текущий ник\n"
        "`/stats` - Статистика бота и игроков\n"
        "`/find [текст]` - Поиск игрока по нику или имени\n"
        "`/help` - Эта справка\n\n"
        "**📖 Как использовать:**\n"
        "1. Установи ник через `/nick ТвойНик`\n"
        "2. Добавь бота в группу как администратора\n"
        "3. Дай права: удаление и отправка сообщений\n"
        "4. Пиши в группе - бот подпишет твои сообщения!\n\n"
        "**⚙️ Техническая информация:**\n"
        "• База данных: Supabase (PostgreSQL)\n"
        "• Хостинг: Railway\n"
        "• Исходный код: GitHub\n"
        "• Авто-бэкапы: ежедневно\n\n"
        "**📞 Поддержка:**\n"
        "Проблемы с ботом? Обратись к администратору."
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений в группе"""
    # Проверяем, что это группа
    if update.message.chat.type not in ['group', 'supergroup']:
        return
    
    # Игнорируем команды
    if update.message.text and update.message.text.startswith('/'):
        return
    
    user = update.effective_user
    user_id = user.id
    message_text = update.message.text or ""
    
    # Получаем ник из базы данных
    game_nick = await DatabaseManager.get_user_nick(user_id)
    
    if game_nick:
        # Отправляем сообщение с ником
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"**🎮 {game_nick}:** {message_text}",
            parse_mode='Markdown'
        )
        
        # Удаляем оригинальное сообщение
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение {update.message.message_id}: {e}")
            
            # Если не удалось удалить, удаляем наше сообщение чтобы не было дубля
            try:
                await sent_message.delete()
            except:
                pass
    
    else:
        # Если у пользователя нет ника
        try:
            reminder = await update.message.reply_text(
                f"👤 {user.first_name}, для отправки сообщений нужен игровой ник!\n\n"
                f"Напиши мне в личные сообщения:\n"
                f"`/nick ТвойИгровойНик`",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            
            # Удаляем напоминание через 15 секунд
            await asyncio.sleep(15)
            await reminder.delete()
            
        except Exception as e:
            logger.error(f"Ошибка напоминания: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка при обработке обновления: {context.error}")
    
    # Можно отправить сообщение админу об ошибке
    if update and update.effective_user:
        try:
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке команды.\n"
                "Попробуй еще раз или обратись к администратору."
            )
        except:
            pass

# ================= ЗАПУСК БОТА =================
def main():
    """Основная функция запуска"""
    logger.info("=" * 50)
    logger.info("🚀 Запуск Telegram бота с Supabase + Railway")
    logger.info(f"📊 Supabase URL: {SUPABASE_URL[:30]}..." if SUPABASE_URL else "❌ Нет Supabase URL")
    logger.info(f"🔑 Bot Token: {'Установлен' if BOT_TOKEN else '❌ Нет токена'}")
    logger.info("=" * 50)
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден! Добавьте в переменные Railway")
        return
    
    # Создаем приложение бота
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем команды
    commands = [
        ("start", start_command),
        ("nick", nick_command),
        ("mynick", mynick_command),
        ("stats", stats_command),
        ("find", find_command),
        ("help", help_command),
    ]
    
    for cmd_name, cmd_handler in commands:
        application.add_handler(CommandHandler(cmd_name, cmd_handler))
    
    # Обработчик сообщений в группах
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group_message
    ))
    
    # Обработчик для личных сообщений (не команды)
    async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "💬 **Я бот для игровых ников!**\n\n"
            "Доступные команды:\n"
            "`/start` - Начало работы\n"
            "`/nick` - Установить ник\n"
            "`/help` - Все команды\n\n"
            "Добавь меня в группу для работы!"
        )
    
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_private_message
    ))
    
    # Регистрируем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("✅ Бот успешно инициализирован")
    logger.info("🔄 Ожидание сообщений...")
    
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == '__main__':
    main()
