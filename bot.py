import asyncio
import logging
import secrets
from html import escape
from aiogram import Bot, Dispatcher, BaseMiddleware, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from config import settings
from database import Database

MENU = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='Добавить'),KeyboardButton(text='Список'),KeyboardButton(text='Удалить')],
    [KeyboardButton(text='Проверка'),KeyboardButton(text='Статистика')]],
    resize_keyboard=True,is_persistent=False,one_time_keyboard=False)

class Access(BaseMiddleware):
    def __init__(self, allowed):
        self.allowed = allowed
    async def __call__(self, handler, event, data):
        message = event.message if isinstance(event,CallbackQuery) else event
        if not event.from_user or event.from_user.id not in self.allowed or not message or message.chat.type != 'private':
            if isinstance(event,CallbackQuery):
                await event.answer('Доступ запрещён',show_alert=True)
            elif isinstance(event,Message):
                await event.answer('Доступ запрещён')
            return
        return await handler(event,data)

async def send_lines(message, lines):
    chunk = ''
    for line in lines:
        if len(chunk)+len(line)+1 > 3500 and chunk:
            await message.answer(chunk,parse_mode='HTML',link_preview_options=LinkPreviewOptions(is_disabled=True))
            chunk = ''
        chunk += line+'\n'
    if chunk:
        await message.answer(chunk,parse_mode='HTML',link_preview_options=LinkPreviewOptions(is_disabled=True))

async def main():
    token, allowed, path = settings()
    db = Database(path)
    bot,dp = Bot(token),Dispatcher()
    dp.message.outer_middleware(Access(allowed))
    dp.callback_query.outer_middleware(Access(allowed))
    states = {}

    async def choices(message, rows, stage, organization_key=None):
        nonce = secrets.token_hex(5)
        states[message.chat.id] = {'stage':stage,'nonce':nonce,'rows':rows,'organization_key':organization_key}
        for start in range(0,len(rows),30):
            keyboard = [[InlineKeyboardButton(text=row['name'][:100],callback_data=f'{nonce}:{i}')]
                        for i,row in enumerate(rows[start:start+30],start)]
            prompt = 'Выберите точку для удаления' if stage=='delete_point' else 'Выберите название организации' if stage in ('organization','delete_organization') else 'Выберите город'
            await message.answer(prompt,
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

    async def add_prompt(message, state):
        step = state['step']
        rows = db.organizations() if step == 0 else db.cities() if step == 1 else []
        state['rows'] = rows
        state['nonce'] = secrets.token_hex(5)
        prompts = ['Введите название организации или выберите из базы',
                   'Введите город или выберите из базы',
                   'Введите полный адрес точки']
        await message.answer(prompts[step]+'\nДля отмены — /cancel',reply_markup=MENU)
        for start in range(0,len(rows),30):
            keyboard = [[InlineKeyboardButton(text=row['name'][:100],callback_data=f'{state["nonce"]}:{i}')]
                        for i,row in enumerate(rows[start:start+30],start)]
            await message.answer('Организации из базы:' if step == 0 else 'Города из базы:',
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

    async def accept_add(message, state, value):
        fields = ['organization','city','address']
        limits = [120,120,500]
        step = state['step']
        if not value or len(value)>limits[step]:
            await message.answer(f'Введите текст длиной от 1 до {limits[step]} символов')
            return
        state['draft'][fields[step]] = value
        state['step'] += 1
        if step < 2:
            await add_prompt(message,state)
            return
        state['stage']='review'
        state['nonce']=secrets.token_hex(5)
        draft=state['draft']
        await send_lines(message,['<b>Проверьте новую точку:</b>',f'Организация: {escape(draft["organization"])}',
            f'Город: {escape(draft["city"])}',f'Адрес: {escape(draft["address"])}'])
        await message.answer('Сохранить?',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='Сохранить',callback_data=state['nonce']+':save'),
            InlineKeyboardButton(text='Отмена',callback_data=state['nonce']+':cancel')]]))

    @dp.message(CommandStart())
    @dp.message(Command('cancel'))
    @dp.message(F.text == 'Отмена')
    async def start(message: Message):
        states.pop(message.chat.id,None)
        await message.answer('Выберите действие',reply_markup=MENU)

    @dp.message(F.text.in_({'Добавить','Список','Удалить','Проверка','Статистика'}))
    async def menu(message: Message):
        states.pop(message.chat.id,None)
        if message.text=='Добавить':
            states[message.chat.id] = {'stage':'add','step':0,'draft':{}}
            await add_prompt(message,states[message.chat.id])
        elif message.text=='Проверка':
            states[message.chat.id] = {'stage':'check'}
            await message.answer('Введите название организации, полный адрес или часть адреса',reply_markup=MENU)
        elif message.text in ('Список','Удалить'):
            rows = db.organizations()
            if rows:
                await choices(message,rows,'delete_organization' if message.text=='Удалить' else 'organization')
            else:
                await message.answer('База пока пустая — нажмите «Добавить»',reply_markup=MENU)
        else:
            organizations,cities = db.organizations(),db.cities()
            lines = [f'<b>Всего точек:</b> {db.total()}',f'<b>Организаций:</b> {len(organizations)}',
                     f'<b>Городов с точками:</b> {len(cities)}','', '<b>Точки по организациям:</b>']
            lines += [f'{escape(row["name"])} — {row["count"]}' for row in organizations] or ['Нет записей']
            lines += ['', '<b>Точки по городам:</b>']
            lines += [f'{escape(row["name"])} — {row["count"]}' for row in cities] or ['Нет записей']
            await send_lines(message,lines)

    @dp.callback_query()
    async def callback(query: CallbackQuery):
        state = states.get(query.from_user.id)
        try:
            nonce,action = (query.data or '').split(':')
            if not state or nonce!=state.get('nonce'):
                raise ValueError()
            if state['stage']=='delete_review':
                if action not in ('delete','cancel'):
                    raise ValueError()
                if action=='delete':
                    try:
                        deleted = db.delete(state['point_id'])
                    except Exception:
                        await query.answer('Ошибка удаления — попробуйте снова',show_alert=True)
                        return
                    states.pop(query.from_user.id,None)
                    await query.answer()
                    await query.message.answer('Точка удалена' if deleted else 'Эта точка уже удалена',reply_markup=MENU)
                else:
                    states.pop(query.from_user.id,None)
                    await query.answer()
                    await query.message.answer('Удаление отменено',reply_markup=MENU)
                return
            if state['stage']=='add':
                index = int(action)
                if state['step'] not in (0,1) or index < 0:
                    raise ValueError()
                value = state['rows'][index]['name']
                # Invalidate these buttons before awaiting the next prompt.
                state['nonce'] = None
                await query.answer()
                await accept_add(query.message,state,value)
                return
            if state['stage']=='review':
                if action not in ('save','cancel'):
                    raise ValueError()
                states.pop(query.from_user.id,None)
                if action=='save':
                    try:
                        saved = db.add(**state['draft'],user_id=query.from_user.id)
                    except Exception:
                        states[query.from_user.id] = state
                        await query.answer('Ошибка сохранения. Попробуйте снова',show_alert=True)
                        return
                    await query.answer()
                    await query.message.answer('Точка сохранена' if saved else 'Эта точка уже есть: организация, город и адрес совпадают',reply_markup=MENU)
                else:
                    await query.answer()
                    await query.message.answer('Добавление отменено',reply_markup=MENU)
                return
            index = int(action)
            if index < 0 or state['stage'] not in ('organization','city','delete_organization','delete_city','delete_point'):
                raise ValueError()
            row = state['rows'][index]
        except (ValueError,IndexError,KeyError):
            await query.answer('Этот выбор устарел. Используйте кнопки текущего шага',show_alert=True)
            return
        await query.answer()
        if state['stage']=='delete_organization':
            cities = db.cities(row['key'])
            if not cities:
                await query.message.answer('У этой организации больше нет точек — нажмите «Удалить» заново')
                return
            await choices(query.message,cities,'delete_city',row['key'])
            return
        if state['stage']=='delete_city':
            points = db.points(state['organization_key'],row['key'])
            if not points:
                await query.message.answer('В этом городе больше нет точек — нажмите «Удалить» заново')
                return
            rows = [{'name':f'{i} — {point["address"]}', 'id':point['id']} for i,point in enumerate(points,1)]
            await choices(query.message,rows,'delete_point')
            return
        if state['stage']=='delete_point':
            point = db.point(row['id'])
            if point is None:
                await query.message.answer('Эта точка уже удалена — нажмите «Удалить» заново')
                return
            nonce = secrets.token_hex(5)
            states[query.from_user.id] = {'stage':'delete_review','nonce':nonce,'point_id':point['id']}
            await send_lines(query.message,['<b>Удалить эту точку?</b>',f'Организация: {escape(point["organization"])}',
                                           f'Город: {escape(point["city"])}',f'Адрес: {escape(point["address"])}'])
            await query.message.answer('Подтвердите удаление',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='Удалить точку',callback_data=nonce+':delete'),
                InlineKeyboardButton(text='Отмена',callback_data=nonce+':cancel')]]))
            return
        if state['stage']=='organization':
            await choices(query.message,db.cities(row['key']),'city',row['key'])
        else:
            points = db.points(state['organization_key'],row['key'])
            if not points:
                await query.message.answer('В этом городе пока нет точек')
                return
            lines = [f'<b>{escape(points[0]["organization"])} · {escape(row["name"])}</b>',
                     f'Количество точек: {len(points)}', '', '<b>Адреса:</b>']
            lines += [f'{i}. {escape(point["address"])}' for i,point in enumerate(points,1)]
            await send_lines(query.message,lines)

    @dp.message()
    async def input_message(message: Message):
        state = states.get(message.chat.id)
        if not state:
            await message.answer('Выберите действие',reply_markup=MENU)
            return
        value = (message.text or '').strip()
        if state['stage']=='check':
            if not value:
                await message.answer('Введите название организации или адрес')
                return
            organization_found = db.exists(value)
            points = db.find_addresses(value)
            if organization_found:
                await message.answer('Такое название уже имеется в базе',reply_markup=MENU)
            if points:
                lines = [f'<b>Совпадений по адресу: {len(points)}</b>']
                for i, point in enumerate(points, 1):
                    lines += ['', f'{i}. <b>{escape(point["organization"])} · {escape(point["city"])}</b>',
                              f'Адрес: {escape(point["address"])}']
                await send_lines(message, lines)
            elif not organization_found:
                await message.answer('Название организации или адрес не найдены в базе',reply_markup=MENU)
            return
        if state['stage']!='add':
            await message.answer('Используйте кнопки выбора или /cancel')
            return
        await accept_add(message,state,value)

    try:
        await dp.start_polling(bot,allowed_updates=['message','callback_query'])
    finally:
        db.close()
        await bot.session.close()

if __name__=='__main__':
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
