import logging
import re
import difflib
import feedparser

from telegram.constants import ChatMemberStatus
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import storage

# --- Настройки ---
BOT_TOKEN = "8887397564:AAFH19UK93YaOv6aWbhtZl45fqei2b9bnIY"

# Посилання на веб-панель після деплою на Render (розділ "Как обновить ссылку" в інструкції)
WEBAPP_URL = "https://example.com"

NEWS_CHECK_INTERVAL_SECONDS = 600  # раз на 10 хвилин

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    text = (
        "👋 Вітаю!\n\n"
        "Я бот сповіщень про повітряну тривогу.\n"
        "Коли з'явиться тривога у вашому регіоні — я надішлю повідомлення сюди.\n\n"
        "Тисни кнопку нижче, щоб відкрити меню налаштувань — усе на кнопках, "
        "команди набирати не обов'язково."
    )
    await update.message.reply_text(text, reply_markup=_main_menu_keyboard(context))


async def help_command_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Отправляет список команд в указанный чат."""
    text = (
        "📋 Доступні команди:\n\n"
        "/menu — головне меню на кнопках (рекомендовано)\n"
        "/start — привітання\n"
        "/help — цей список команд\n"
        "/channels — список каналів розсилки (тривоги, новини, тест, видалення)\n"
        "/removechannel — видалити канал зі списку (з id) або показати список з id\n"
        "/sources — список джерел новин\n"
        "/addsource — додати сайт (RSS) як джерело\n"
        "/addtgsource — додати Telegram-канал як джерело\n"
        "/newsfilter — фільтр новин за ключовими словами\n\n"
        "Щоб додати канал — натисни кнопку нижче й обери канал зі списку. "
        "Бот сам зареєструється, коли отримає права адміністратора."
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "➕ Додати бота в канал",
            url=f"https://t.me/{context.bot.username}?startchannel&admin=change_info+post_messages+edit_messages+delete_messages+invite_users+restrict_members+pin_messages+promote_members+manage_chat+manage_video_chats+anonymous",
        )
    ]])
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список доступных команд."""
    await help_command_for_chat(context, update.effective_chat.id)


def _main_menu_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    add_channel_url = (
        f"https://t.me/{context.bot.username}?startchannel&admin="
        "change_info+post_messages+edit_messages+delete_messages+invite_users+"
        "restrict_members+pin_messages+promote_members+manage_chat+manage_video_chats+anonymous"
    )
    rows = []
    if WEBAPP_URL and WEBAPP_URL != "https://example.com":
        rows.append([InlineKeyboardButton("🖥 Відкрити панель", web_app=WebAppInfo(url=WEBAPP_URL))])
    rows += [
        [InlineKeyboardButton("📡 Мої канали", callback_data="menu:channels")],
        [InlineKeyboardButton("📰 Джерела новин", callback_data="menu:sources")],
        [InlineKeyboardButton("➕ Додати бота в канал", url=add_channel_url)],
        [InlineKeyboardButton("➕ Додати джерело новин", callback_data="menu:addsource_help")],
        [InlineKeyboardButton("❓ Допомога", callback_data="menu:help")],
    ]
    return InlineKeyboardMarkup(rows)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает главное меню бота."""
    await update.message.reply_text(
        "🔧 Головне меню\n\nОбери, що хочеш налаштувати:",
        reply_markup=_main_menu_keyboard(context),
    )


async def on_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия кнопок главного меню."""
    query = update.callback_query
    await query.answer()
    section = query.data.split(":", 1)[1]
    chat_id = query.message.chat_id

    if section == "channels":
        await _send_channels_list(context, chat_id)

    elif section == "sources":
        await _send_sources_list(context, chat_id)

    elif section == "addsource_help":
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "➕ Додати джерело новин:\n\n"
                "🌐 Сайт (RSS) — надішли:\n"
                "<code>/addsource Назва https://посилання-на-rss</code>\n\n"
                "📢 Telegram-канал — просто напиши:\n"
                "<code>/addtgsource</code>\n"
                "і слідуй інструкціям."
            ),
            parse_mode="HTML",
        )

    elif section == "help":
        await help_command_for_chat(context, chat_id)

    # Показуємо меню знову внизу, щоб не треба було набирати /menu кожного разу
    await context.bot.send_message(
        chat_id=chat_id,
        text="🔧 Головне меню:",
        reply_markup=_main_menu_keyboard(context),
    )


def _channel_keyboard(ch: dict) -> InlineKeyboardMarkup:
    enabled = ch.get("enabled", True)
    news_enabled = ch.get("news_enabled", False)
    keywords = ch.get("news_keywords", [])
    status_label = "🟢 Тривоги: Увімкнено" if enabled else "🔴 Тривоги: Вимкнено"
    news_label = "📰 Новини: Увімкнено" if news_enabled else "📰 Новини: Вимкнено"
    filter_label = f"🔎 Фільтр: {len(keywords)} слів" if keywords else "🔎 Фільтр: немає"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(status_label, callback_data=f"toggle:{ch['id']}")],
        [InlineKeyboardButton(news_label, callback_data=f"newstoggle:{ch['id']}")],
        [InlineKeyboardButton(filter_label, callback_data=f"filterinfo:{ch['id']}")],
        [InlineKeyboardButton("📝 Написати новину зараз", callback_data=f"onenews:{ch['id']}")],
        [
            InlineKeyboardButton("🔔 Тест", callback_data=f"test:{ch['id']}"),
            InlineKeyboardButton("🗑 Видалити", callback_data=f"del:{ch['id']}"),
        ],
    ])


async def _send_channels_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Отправляет список каналов с кнопками управления в указанный чат."""
    channels = storage.get_channels()
    if not channels:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Каналів ще немає.\n\nНатисни /start і скористайся кнопкою «➕ Додати бота в канал».",
        )
        return

    await context.bot.send_message(chat_id=chat_id, text="📡 Канали розсилки:")
    for ch in channels:
        await context.bot.send_message(chat_id=chat_id, text=ch["title"], reply_markup=_channel_keyboard(ch))


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список каналов с кнопками управления."""
    await _send_channels_list(context, update.effective_chat.id)


async def on_channel_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия кнопок «Тест» и «Видалити» в списке каналов."""
    query = update.callback_query
    await query.answer()

    action, chat_id_str = query.data.split(":", 1)
    chat_id = int(chat_id_str)

    if action == "del":
        ok = storage.remove_channel(chat_id)
        leave_error = None
        try:
            await context.bot.leave_chat(chat_id)
        except Exception as e:
            leave_error = str(e)
            logger.warning(f"Не вдалося вийти з каналу {chat_id}: {leave_error}")

        if ok and not leave_error:
            await query.edit_message_text(f"🗑 «{query.message.text}» видалено, бот вийшов з каналу.")
        elif ok and leave_error:
            await query.edit_message_text(
                f"🗑 «{query.message.text}» видалено зі списку розсилки.\n"
                f"⚠️ Але вийти з каналу не вдалося: {leave_error}"
            )
        else:
            await query.edit_message_text("Канал вже видалено або не знайдено.")

    elif action == "test":
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔔 Тестове повідомлення від бота сповіщень про тривогу.",
            )
            await query.answer("✅ Тестове повідомлення надіслано", show_alert=True)
        except Exception as e:
            await query.answer(f"⛔ Помилка: {e}", show_alert=True)

    elif action == "toggle":
        current = storage.is_channel_enabled(chat_id)
        storage.set_channel_enabled(chat_id, not current)
        channels = storage.get_channels()
        ch = next((c for c in channels if c["id"] == chat_id), None)
        if ch:
            await query.edit_message_reply_markup(reply_markup=_channel_keyboard(ch))
            state_text = "увімкнено" if ch["enabled"] else "вимкнено"
            await query.answer(f"Авто-тривоги {state_text} для цього каналу")

    elif action == "newstoggle":
        current = storage.is_channel_news_enabled(chat_id)
        storage.set_channel_news_enabled(chat_id, not current)
        channels = storage.get_channels()
        ch = next((c for c in channels if c["id"] == chat_id), None)
        if ch:
            await query.edit_message_reply_markup(reply_markup=_channel_keyboard(ch))
            state_text = "увімкнено" if ch.get("news_enabled") else "вимкнено"
            await query.answer(f"Автоновини {state_text} для цього каналу")

    elif action == "filterinfo":
        keywords = storage.get_channel_keywords(chat_id)
        current = ", ".join(keywords) if keywords else "немає (пропускаються всі новини)"
        await query.answer()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                f"🔎 Фільтр для «{query.message.text}»:\n"
                f"Поточний: {current}\n\n"
                f"Щоб налаштувати — надішли:\n"
                f"<code>/newsfilter {chat_id} війна, фронт, обстріл</code>\n\n"
                f"Щоб прибрати фільтр — надішли:\n"
                f"<code>/newsfilter {chat_id} clear</code>"
            ),
            parse_mode="HTML",
        )


    elif action == "onenews":
        keywords = storage.get_channel_keywords(chat_id)
        result = _get_latest_single_news(keywords)
        if result is None:
            await query.answer("Не знайдено новин під поточний фільтр.", show_alert=True)
            return

        source_name, title, link = result
        text = f"📰 <b>{source_name}</b>\n\n{title}\n{link}"
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML",
                disable_web_page_preview=False,
            )
            storage.add_seen_news(link)
            storage.add_recent_title(_normalize_title(title))
            await query.answer("✅ Новину надіслано в канал", show_alert=True)
        except Exception as e:
            await query.answer(f"⛔ Помилка: {e}", show_alert=True)


async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удаляет канал из списка рассылки по ID."""
    channels = storage.get_channels()

    if not context.args:
        if not channels:
            await update.message.reply_text("Каналів ще немає.")
            return
        lines = ["Щоб видалити канал, напиши:\n/removechannel <id>\n\nСписок каналів:"]
        for ch in channels:
            lines.append(f"• {ch['title']} — id: {ch['id']}")
        await update.message.reply_text("\n".join(lines))
        return

    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID має бути числом. Приклад: /removechannel -1001234567890")
        return

    ok = storage.remove_channel(chat_id)
    if ok:
        await update.message.reply_text("✅ Канал видалено зі списку розсилки.")
    else:
        await update.message.reply_text("Канал з таким id не знайдено у списку.")


async def news_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Устанавливает фильтр по ключевым словам для новостей канала."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Використання:\n"
            "/newsfilter <id_каналу> слово1, слово2, слово3\n"
            "/newsfilter <id_каналу> clear — прибрати фільтр\n\n"
            "ID каналу можна побачити в /channels."
        )
        return

    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID має бути числом. Приклад: /newsfilter -1001234567890 війна")
        return

    rest = " ".join(context.args[1:])

    if rest.strip().lower() == "clear":
        ok = storage.set_channel_keywords(chat_id, [])
        if ok:
            await update.message.reply_text("✅ Фільтр прибрано — надсилатимуться всі новини.")
        else:
            await update.message.reply_text("Канал з таким id не знайдено.")
        return

    keywords = [w.strip().lower() for w in rest.split(",") if w.strip()]
    if not keywords:
        await update.message.reply_text("Не вдалося розпізнати ключові слова. Розділяй їх комою.")
        return

    ok = storage.set_channel_keywords(chat_id, keywords)
    if ok:
        await update.message.reply_text(
            f"✅ Фільтр встановлено: {', '.join(keywords)}\n"
            f"Надсилатимуться лише новини, де є хоча б одне з цих слів у заголовку."
        )
    else:
        await update.message.reply_text("Канал з таким id не знайдено.")


def _source_keyboard(source: dict) -> InlineKeyboardMarkup:
    status_label = "🟢 Увімкнено" if source.get("enabled", True) else "🔴 Вимкнено"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(status_label, callback_data=f"srctoggle:{source['name']}"),
        InlineKeyboardButton("🗑 Видалити", callback_data=f"srcdel:{source['name']}"),
    ]])


async def _send_sources_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Отправляет список источников новостей с кнопками управления в указанный чат."""
    sources = storage.get_sources()
    if not sources:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "Джерел ще немає.\n\n"
                "Сайт (RSS): /addsource Назва https://посилання-на-rss\n"
                "Telegram-канал: /addtgsource"
            ),
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📡 Джерела новин:\n\n"
            "➕ Додати сайт (RSS): /addsource Назва https://посилання-на-rss\n"
            "➕ Додати Telegram-канал: /addtgsource"
        ),
    )
    for s in sources:
        if s.get("type") == "telegram":
            label = f"📢 {s['name']} (Telegram-канал)"
        else:
            label = f"🌐 {s['name']}\n{s.get('url', '')}"
        await context.bot.send_message(chat_id=chat_id, text=label, reply_markup=_source_keyboard(s))


async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список источников новостей с кнопками управления."""
    await _send_sources_list(context, update.effective_chat.id)


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавляет новый RSS-источник."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Використання:\n/addsource Назва https://посилання-на-rss\n\n"
            "Приклад:\n/addsource Цензор.НЕТ https://censor.net.ua/includes/news_ukr.xml"
        )
        return

    url = context.args[-1]
    name = " ".join(context.args[:-1])

    if not url.startswith("http"):
        await update.message.reply_text("Останнім аргументом має бути посилання на RSS (починається з http).")
        return

    # Перевіримо, що посилання взагалі схоже на робочий RSS
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            await update.message.reply_text(
                "⚠️ За цим посиланням не знайдено новин. Перевір, що це правильний RSS. "
                "Джерело всеодно буде додано, спробуй пізніше."
            )
    except Exception:
        pass

    ok = storage.add_source(name, url)
    if ok:
        await update.message.reply_text(f"✅ Джерело «{name}» додано.")
    else:
        await update.message.reply_text(f"Джерело з назвою «{name}» вже є. Обери іншу назву.")


async def add_telegram_source_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начинает процесс добавления Telegram-канала как источника новостей."""
    context.user_data["awaiting_source_forward"] = True
    await update.message.reply_text(
        "📢 Щоб додати Telegram-канал як джерело новин:\n\n"
        "1. Додай бота в цей канал (як адміністратора — так само, як для звичайних каналів)\n"
        "2. Перешли сюди (в особисті) будь-який пост із цього каналу\n\n"
        "Наступний пересланий пост я зареєструю саме як джерело новин."
    )


async def on_source_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия кнопок управления источниками."""
    query = update.callback_query
    await query.answer()

    action, name = query.data.split(":", 1)

    if action == "srctoggle":
        sources = storage.get_sources()
        current = next((s for s in sources if s["name"] == name), None)
        if not current:
            await query.edit_message_text("Джерело не знайдено, можливо вже видалено.")
            return
        storage.set_source_enabled(name, not current.get("enabled", True))
        sources = storage.get_sources()
        updated = next((s for s in sources if s["name"] == name), None)
        await query.edit_message_reply_markup(reply_markup=_source_keyboard(updated))

    elif action == "srcdel":
        ok = storage.remove_source(name)
        if ok:
            await query.edit_message_text(f"🗑 Джерело «{name}» видалено.")
        else:
            await query.edit_message_text("Джерело вже видалено або не знайдено.")


async def on_forwarded_from_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Если пересылают боту сообщение из канала — регистрируем канал."""
    msg = update.message
    if not msg or not msg.forward_origin:
        return

    origin = msg.forward_origin
    chat = getattr(origin, "chat", None)
    if chat is None:
        await msg.reply_text(
            "Не вдалося визначити канал. Переконайся, що переслав пост саме з каналу."
        )
        return

    try:
        member = await context.bot.get_chat_member(chat.id, context.bot.id)
    except Exception:
        await msg.reply_text(
            "Не бачу цей канал. Спочатку додай бота в канал як адміністратора."
        )
        return

    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        await msg.reply_text("Бот доданий у канал, але не є адміністратором — додай права адміна.")
        return

    if context.user_data.get("awaiting_source_forward"):
        context.user_data["awaiting_source_forward"] = False
        ok = storage.add_telegram_source(chat.title or str(chat.id), chat.id)
        # Якщо цей канал випадково потрапив і в список розсилки (наприклад, автоматично
        # при додаванні бота) — прибираємо його звідти, щоб джерело і отримувач не плуталися.
        storage.remove_channel(chat.id)
        if ok:
            await msg.reply_text(f"✅ Канал «{chat.title}» додано як джерело новин.")
        else:
            await msg.reply_text(f"Канал «{chat.title}» вже є серед джерел новин.")
        return

    is_new = storage.add_channel(chat.id, chat.title or str(chat.id))
    if is_new:
        await msg.reply_text(f"✅ Канал «{chat.title}» додано до списку розсилки.")
    else:
        await msg.reply_text(f"Канал «{chat.title}» вже є у списку.")


def _normalize_title(title: str) -> str:
    """Приводит заголовок к виду для сравнения: нижний регистр, без пунктуации."""
    title = title.lower()
    title = re.sub(r"[^\w\sа-яіїєґ]", " ", title, flags=re.UNICODE)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _is_similar_title(title: str, others: list, threshold: float = 0.72) -> bool:
    """Проверяет, похож ли заголовок на один из уже отправленных (та же новость с другого джерела)."""
    for other in others:
        ratio = difflib.SequenceMatcher(None, title, other).ratio()
        if ratio >= threshold:
            return True
    return False


def _get_latest_single_news(keywords: list) -> tuple | None:
    """Возвращает одну самую свежую новость (source_name, title, link) среди всех источников,
    с учётом фильтра ключевых слов. None, если подходящей новости не нашлось."""
    candidates = []
    for source_name, feed_url in storage.get_active_rss_sources():
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue
        for entry in feed.entries[:10]:
            title_lower = entry.title.lower()
            if keywords and not any(kw in title_lower for kw in keywords):
                continue
            published = entry.get("published_parsed")
            candidates.append((published, source_name, entry.title, entry.link))

    if not candidates:
        return None

    # Сортуємо за датою публікації (найновіша перша); якщо дати немає — в кінець
    candidates.sort(key=lambda c: c[0] or (), reverse=True)
    _published, source_name, title, link = candidates[0]
    return source_name, title, link


async def check_news(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Периодически проверяет RSS-ленты и рассылает новые новости, исключая дублікаты между джерелами."""
    news_channels = [ch for ch in storage.get_channels() if ch.get("news_enabled")]
    if not news_channels:
        return

    seen = set(storage.get_seen_news())
    recent_titles = storage.get_recent_titles()
    batch_titles: list[str] = []  # заголовки, уже отправленные в этом цикле проверки

    for source_name, feed_url in storage.get_active_rss_sources():
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            logger.warning(f"Не вдалося отримати RSS {source_name}: {e}")
            continue

        new_entries = [entry for entry in feed.entries if entry.link not in seen]
        for entry in reversed(new_entries[:5]):  # не больше 5 новых за раз с одного источника
            norm_title = _normalize_title(entry.title)

            # Дубликат той самой новости з іншого джерела — не надсилаємо, але позначаємо переглянутою
            if _is_similar_title(norm_title, recent_titles) or _is_similar_title(norm_title, batch_titles):
                storage.add_seen_news(entry.link)
                seen.add(entry.link)
                logger.info(f"Пропущено як дублікат: {entry.title}")
                continue

            text = f"📰 <b>{source_name}</b>\n\n{entry.title}\n{entry.link}"
            entry_title_lower = entry.title.lower()

            for ch in news_channels:
                keywords = ch.get("news_keywords", [])
                if keywords and not any(kw in entry_title_lower for kw in keywords):
                    continue  # новина не проходить фільтр цього каналу
                try:
                    await context.bot.send_message(
                        chat_id=ch["id"], text=text, parse_mode="HTML",
                        disable_web_page_preview=False,
                    )
                except Exception as e:
                    logger.warning(f"Не вдалося надіслати новину в {ch['id']}: {e}")

            storage.add_seen_news(entry.link)
            storage.add_recent_title(norm_title)
            seen.add(entry.link)
            recent_titles.append(norm_title)
            batch_titles.append(norm_title)


async def on_source_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловит новые посты из каналов, подключённых как Telegram-источники новостей."""
    post = update.channel_post
    if not post:
        return

    # Захист від зациклення: не реагуємо на власні пости бота
    if post.from_user and post.from_user.id == context.bot.id:
        return

    source = storage.get_telegram_source_by_chat_id(post.chat.id)
    if not source:
        return  # цей канал не зареєстрований як джерело новин

    text_content = post.text or post.caption
    if not text_content:
        return  # пост без тексту (тільки фото/відео без підпису) — пропускаємо

    title = text_content.strip().split("\n")[0][:200]
    norm_title = _normalize_title(title)

    recent_titles = storage.get_recent_titles()
    if _is_similar_title(norm_title, recent_titles):
        logger.info(f"Пропущено як дублікат (telegram-джерело): {title}")
        return

    if post.chat.username:
        link = f"https://t.me/{post.chat.username}/{post.message_id}"
    else:
        link = f"з каналу «{post.chat.title}»"

    text = f"📰 <b>{source['name']}</b>\n\n{title}\n{link}"
    title_lower = title.lower()

    news_channels = [ch for ch in storage.get_channels() if ch.get("news_enabled")]
    for ch in news_channels:
        keywords = ch.get("news_keywords", [])
        if keywords and not any(kw in title_lower for kw in keywords):
            continue
        try:
            await context.bot.send_message(
                chat_id=ch["id"], text=text, parse_mode="HTML",
                disable_web_page_preview=False,
            )
        except Exception as e:
            logger.warning(f"Не вдалося надіслати новину в {ch['id']}: {e}")

    storage.add_recent_title(norm_title)


async def _prime_seen_news() -> None:
    """Для каждого нового источника запоминает текущие новости без отправки,
    чтобы не разослать всю старую ленту разом при первом подключении фида."""
    primed = set(storage.get_primed_feeds())
    for _source_name, feed_url in storage.get_active_rss_sources():
        if feed_url in primed:
            continue
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue
        for entry in feed.entries:
            storage.add_seen_news(entry.link)
        storage.mark_feed_primed(feed_url)


async def _set_commands(application: Application) -> None:
    await _prime_seen_news()
    await application.bot.set_my_commands([
        BotCommand("start", "Привітання"),
        BotCommand("menu", "Головне меню на кнопках"),
        BotCommand("help", "Список команд"),
        BotCommand("channels", "Список каналів розсилки"),
        BotCommand("removechannel", "Видалити канал зі списку"),
        BotCommand("newsfilter", "Фільтр новин за ключовими словами"),
        BotCommand("sources", "Керування джерелами новин"),
        BotCommand("addsource", "Додати нове джерело новин (RSS)"),
    ])


async def on_bot_added_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Автоматически регистрирует канал, если боту дали права администратора."""
    result = update.my_chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    chat = result.chat

    if new_status == ChatMemberStatus.ADMINISTRATOR and old_status != ChatMemberStatus.ADMINISTRATOR:
        is_new = storage.add_channel(chat.id, chat.title or str(chat.id))
        if is_new:
            logger.info(f"Канал автоматично зареєстровано: {chat.title} ({chat.id})")
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text="✅ Бот сповіщень про тривогу підключено до цього каналу.",
                )
            except Exception:
                pass
    elif new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        storage.remove_channel(chat.id)
        logger.info(f"Бота видалено з каналу {chat.title} ({chat.id}), видалено зі списку")


def build_application() -> Application:
    """Создаёт и настраивает Application бота (без запуска polling)."""
    application = Application.builder().token(BOT_TOKEN).post_init(_set_commands).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("channels", list_channels))
    application.add_handler(CommandHandler("removechannel", remove_channel))
    application.add_handler(CommandHandler("newsfilter", news_filter))
    application.add_handler(CommandHandler("sources", list_sources))
    application.add_handler(CommandHandler("addsource", add_source))
    application.add_handler(CommandHandler("addtgsource", add_telegram_source_start))
    application.add_handler(MessageHandler(filters.FORWARDED, on_forwarded_from_channel))
    application.add_handler(ChatMemberHandler(on_bot_added_to_chat, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, on_source_channel_post))
    application.add_handler(CallbackQueryHandler(on_menu_button, pattern=r"^menu:"))
    application.add_handler(CallbackQueryHandler(on_source_button, pattern=r"^src(toggle|del):"))
    application.add_handler(CallbackQueryHandler(on_channel_button))

    application.job_queue.run_repeating(check_news, interval=NEWS_CHECK_INTERVAL_SECONDS, first=30)
    return application


def main() -> None:
    application = build_application()
    logger.info("Бот запущено, очікую на команди...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()