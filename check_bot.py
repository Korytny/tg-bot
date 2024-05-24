import logging
import os
from telethon import TelegramClient, events, Button
import aiohttp
import datetime
from urllib.parse import unquote
import base64

# Настройки для Telethon
API_ID = os.environ['API_ID']  # Замените на ваш API_ID
API_HASH = os.environ['API_HASH']  # Замените на ваш API_HASH
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']  # Замените на токен вашего бота
API_KEY = os.environ['API_KEY']  # Замените на ваш реальный API-ключ

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Глобальный словарь для хранения состояния пользователей
user_responses = {}

# Создание клиента Telegram
client = TelegramClient('bot_session', API_ID, API_HASH)

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    full_command = event.message.message
    logging.info(f"Full command received: {full_command}")

    # Проверяем, есть ли параметры после '/start '
    if len(full_command.split()) > 1:
        encoded_params = full_command.split(maxsplit=1)[1]
        try:
            # Добавляем недостающие символы "=" для декодирования
            padding = '=' * (4 - len(encoded_params) % 4)
            encoded_params += padding
            decoded_params = base64.urlsafe_b64decode(encoded_params).decode()
            logging.info(f"Decoded params: {decoded_params}")
            utm_data = dict(param.split('=') for param in decoded_params.split('&') if '=' in param)
            utm_source = utm_data.get('utm_source', 'unknown')
            utm_medium = utm_data.get('utm_medium', 'unknown')
            logging.info(f"Received UTM parameters: source={utm_source}, medium={utm_medium}")
        except Exception as e:
            logging.error(f"Error decoding params: {e}")
            utm_source = utm_medium = 'unknown'
    else:
        utm_source = utm_medium = 'unknown'
        logging.info("No UTM parameters found.")

    user_id = event.sender_id
    sender = await event.get_sender()
    first_name = sender.first_name or "Неизвестно"
    last_name = sender.last_name or "Неизвестно"
    telegram_username = sender.username

    logging.info(f"Received /start command from user_id {user_id}")

    user_info = await check_user(user_id, first_name, last_name, telegram_username)

    if user_info is None:
        logging.info("User not found, proceeding with registration")

        # Формируем путь к файлу с уникальным именем, включая user_id
        photo_path = f'user_photo_{user_id}.jpg'

        # Попытка загрузить аватар пользователя
        try:
            photo = await client.download_profile_photo(user_id, file=photo_path)
            if photo:
                logging.info(f"Avatar downloaded and saved as {photo_path}")
            else:
                logging.info("No avatar to download, proceeding without photo")
                photo_path = None  # Устанавливаем photo_path в None, если фото нет
        except Exception as e:
            logging.error(f"Failed to download avatar: {str(e)}")
            photo_path = None  # В случае ошибки также устанавливаем photo_path в None

        registration_response = await register_user(
            user_id=user_id,
            username=telegram_username,
            first_name=first_name,
            last_name=last_name,
            photo_path=photo_path,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign='unknown'
        )

        if registration_response:
            logging.info("Registration successful, starting user testing")
            await client.send_message(user_id, f"Привет, {first_name}! Вы успешно зарегистрированы.")
            await manage_user_testing(event)
        else:
            logging.error("Registration failed")
            await client.send_message(user_id, "Не удалось зарегистрировать пользователя. Пожалуйста, попробуйте позже.")
    elif not user_info.get('gender') or not user_info.get('country') or user_info.get('news_preference') is None:
        logging.info("User found but missing some information, starting user testing")
        await manage_user_testing(event)
    else:
        logging.info("User found and all information is complete")
        await client.send_message(user_id, f"Привет, {first_name}! Рады видеть вас снова.")

@client.on(events.NewMessage)
async def handle_all_messages(event):
    user_id = event.sender_id

    # Проверка, находится ли пользователь в процессе тестирования
    if user_responses.get(user_id, {}).get('in_testing'):
        logging.info(f"User is currently in testing, ignoring message: {event.text} from user_id: {user_id}")
        return

    # Игнорируем команду /start, чтобы не возникал конфликт
    if event.text.startswith('/start'):
        return

    logging.info(f"Handling general message: {event.text} from user_id {user_id}")
    await event.respond('Добро пожаловать! Давай общаться.', buttons=Button.clear())


async def main():
    logging.info("Starting the bot")
    await client.start(bot_token=TELEGRAM_BOT_TOKEN)
    await client.run_until_disconnected()

async def check_user(user_id, name, surname, telegram):
    url = 'https://robogpt.me/api/followers/'
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }
    # Удаляем параметры с None значениями
    params = {
        'filters[$and][0][name][$eq]': name,
        'filters[$and][1][surname][$eq]': surname,
        'filters[$and][2][telegram][$eq]': telegram
    }
    params = {k: v for k, v in params.items() if v is not None}  # Очистка параметров от None значений

    logging.info(f"Sending request to check user: {params}")

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as response:
            response_status = response.status
            response_data = await response.json() if response_status == 200 else {}

            logging.info(f"Received response for user check: Status {response_status}, Data {response_data}")

            if response_data['data']:
                user_data = response_data['data'][0]['attributes']
                user_data['db_user_id'] = response_data['data'][0]['id']
                user_responses[user_id] = user_responses.get(user_id, {})
                user_responses[user_id].update(user_data)  # Обновление с сохранением предыдущих данных
                logging.info(f"db_user_id {user_data['db_user_id']} saved for user_id {user_id}")
                return user_data
            else:
                user_responses[user_id] = user_responses.get(user_id, {})
                user_responses[user_id].update({'db_user_id': None})  # Явное указание отсутствия db_user_id
                logging.info(f"No db_user_id found for user_id {user_id}. Data set to None.")
                return None

async def register_user(user_id, username, first_name, last_name, photo_path, utm_source, utm_medium, utm_campaign):
    logging.info(f"Starting registration for user: {username}")

    if photo_path:
        try:
            image_id = await upload_image_to_media_library(photo_path)
            logging.info(f"Image uploaded successfully, image_id: {image_id}")
        except Exception as e:
            logging.error(f"Failed to upload image: {str(e)}")
            image_id = None
    else:
        image_id = None

    url = 'https://robogpt.me/api/followers'
    headers = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}

    data = {
        'data': {
            'tgUserID': user_id,
            'telegram': username if username is not None else "",  # Заменяем None на пустую строку
            'name': first_name,
            'utm_source': utm_source,  # Сохраняем UTM-метку источника
            'utm_medium': utm_medium,  # Сохраняем UTM-метку канала
            'utm_campaign': utm_campaign,  # Сохраняем UTM-метку кампании
            'surname': last_name,
            'blocked': False,
            'lastLogin': datetime.datetime.now().isoformat(),
            'media': image_id,
            'type': 'New',
        }
    }

    # Добавляем 'media' только если image_id не None
    if image_id is not None:
        data['data']['media'] = image_id

    logging.info(f"Sending registration data: {data}")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            response_data = await response.json()
            logging.info(f"Registration response: {response_data}")
            if response.status == 200:
                # Проверка наличия нужных данных в ответе
                if 'data' in response_data and response_data['data']:
                    user_data = response_data['data']
                    user_data['db_user_id'] = user_data.get('id')
                    user_responses[user_id] = user_data
                    logging.info(f"User data saved with db_user_id {user_data['db_user_id']}")
                    return user_data
                else:
                    logging.error("Registration data is missing in the response")
                    return None
            else:
                logging.error(f"Failed to register user: HTTP {response.status}, Response: {await response.text()}")
                return None

async def upload_image_to_media_library(image_path):
    url = 'https://robogpt.me/api/upload'
    headers = {'Authorization': f'Bearer {API_KEY}'}
    files = {'files': open(image_path, 'rb')}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=files, headers=headers) as response:
            if response.status == 200:
                uploaded_media = await response.json()
                return uploaded_media[0]['id']
            else:
                raise Exception(f"Failed to upload image: {await response.text()}")

async def manage_user_testing(event, callback_data=None):
    user_id = event.sender_id

    # Проверка наличия данных пользователя и db_user_id
    if user_id not in user_responses or 'db_user_id' not in user_responses[user_id]:
        logging.error(f"No db_user_id found for user_id {user_id}, cannot proceed.")
        await event.respond("Произошла ошибка во время обработки вашего запроса. Попробуйте перезапустить процесс.")
        return

    logging.info(f"Entered manage_user_testing for user_id {user_id} with event type {type(event).__name__}, data: {callback_data}")

    # Обновление состояния пользователя на основе callback данных
    if callback_data:
        update_user_state(user_id, callback_data)

    current_state = user_responses[user_id].get("state", "ask_gender")

    # Если состояние "ask_gender", значит тестирование начинается
    if current_state == "ask_gender":
        # Отправляем приветственное сообщение перед первым вопросом
        await client.send_message(user_id, "Пройдите, пожалуйста, небольшое тестирование из 3-х вопросов")

    # Обработка состояний и отправка соответствующих вопросов или действий
    if current_state == "ask_gender":
        markup = [Button.inline("Мужчина", data="men"), Button.inline("Женщина", data="woman")]
        await client.send_message(user_id, "Вы мужчина или женщина?", buttons=markup)
    elif current_state == "ask_country":
        markup = [Button.inline("Россия", data="Russia"), Button.inline("Другая страна", data="other")]
        await client.send_message(user_id, "В какой стране вы проживаете?", buttons=markup)
    elif current_state == "ask_news":
        markup = [Button.inline("Да", data="yes"), Button.inline("Нет", data="no")]
        await client.send_message(user_id, "Хотите ли вы получать новости?", buttons=markup)
    elif current_state == "completed":
        # Проверка предпочтения получения новостей
        if user_responses[user_id].get('news_preference', False):
            # Сохраняем результаты перед отправкой новостей
            await submit_responses(user_responses[user_id]['db_user_id'], user_responses[user_id])
            await send_news(user_id)
        else:
            await submit_responses(user_responses[user_id]['db_user_id'], user_responses[user_id])
            await client.send_message(user_id, "Спасибо за ответы! Ваша информация сохранена.")

def update_user_state(user_id, data):
    """Обновляем состояние пользователя на основе полученного ответа."""
    logging.info(f"Updating state for user_id {user_id} with data {data}")
    state = user_responses[user_id].get("state", "ask_gender")

    if state == "ask_gender":
        if data == "men" or data == "woman":
            user_responses[user_id]["gender"] = data
            user_responses[user_id]["state"] = "ask_country"  # Переход к следующему вопросу
        else:
            logging.error("Invalid gender response received.")
    elif state == "ask_country":
        user_responses[user_id]["country"] = data
        user_responses[user_id]["state"] = "ask_news"
    elif state == "ask_news":
        user_responses[user_id]["news_preference"] = True if data == "yes" else False
        user_responses[user_id]["state"] = "completed"
    else:
        logging.error(f"Unhandled state: {state} with data: {data}")

async def send_news(user_id):
    if user_id not in user_responses:
        user_responses[user_id] = {'news_index': 0}
    elif 'news_index' not in user_responses[user_id]:
        user_responses[user_id]['news_index'] = 0

    news_list = await fetch_news(user_id)

    if news_list:
        news = news_list[0]  # Поскольку fetch_news возвращает список с одной новостью
        news_text = f"**{news['name']}**\n{news['description']}\n\n{news['content']}"
        markup = [Button.inline("Далее", data="next_news")]

        if news['media_url']:
            await client.send_file(user_id, news['media_url'], caption=news_text, buttons=markup)
        else:
            await client.send_message(user_id, news_text, buttons=markup, parse_mode='md')

        # Увеличиваем индекс новости для пользователя
        user_responses[user_id]['news_index'] += 1
    else:
        await client.send_message(user_id, "Это была последняя новость.")
        await update_user_status(user_id, 'Reader')
        user_responses[user_id]['news_index'] = 0  # Сброс индекса новостей для повторной итерации

async def fetch_news(user_id):
    current_index = user_responses[user_id].get('news_index', 0)
    url = f'https://robogpt.me/api/contents?pagination[start]={current_index}&pagination[limit]=1'
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }

    logging.info("Fetching the next news item from the database.")

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            response_status = response.status
            response_data = await response.json() if response_status == 200 else {}

            if response_data.get('data', []):
                item = response_data['data'][0]
                return [{
                    'name': item['attributes']['name'],
                    'description': item['attributes']['description'],
                    'content': item['attributes']['content_txt'],
                    'media_url': item['attributes'].get('media_url')
                }]
            else:
                logging.error("Failed to fetch news or no news available.")
                return []

@client.on(events.CallbackQuery)
async def handle_callback_query(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    logging.info(f"CallbackQuery received with data: {data} from user {user_id}")

    await event.answer()

    if data == "next_news":
        await send_news(user_id)
    else:
        await manage_user_testing(event, callback_data=data)

async def submit_responses(db_user_id, responses):
    url = f'https://robogpt.me/api/followers/{db_user_id}'
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }
    # Объединяем данные ответов с обновлением статуса
    data_to_send = {
        'gender': responses.get("gender"),
        'country': responses.get("country"),
        'news_preference': responses.get("news_preference"),
        'type': 'Tested'  # Обновляем статус на "Tested"
    }

    logging.info(f"Submitting responses and updating status for db_user_id {db_user_id}: {data_to_send}")

    async with aiohttp.ClientSession() as session:
        async with session.put(url, json={'data': data_to_send}, headers=headers) as response:
            response_text = await response.text()
            if response.status == 200:
                logging.info(f"User info and status updated successfully for db_user_id {db_user_id}. Server response: {response_text}")
            else:
                logging.error(f"Failed to update user info and status for db_user_id {db_user_id}: HTTP {response.status}, Response: {response_text}")

async def update_user_status(user_id, new_status):
    if user_id in user_responses and 'db_user_id' in user_responses[user_id]:
        db_user_id = user_responses[user_id]['db_user_id']
        url = f'https://robogpt.me/api/followers/{db_user_id}'
        headers = {
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json'
        }
        data_to_send = {
            'type': new_status
        }
        logging.info(f"Updating user status to {new_status} for db_user_id {db_user_id}")

        async with aiohttp.ClientSession() as session:
            async with session.put(url, json={'data': data_to_send}, headers=headers) as response:
                response_text = await response.text()
                if response.status == 200:
                    logging.info(f"User status updated successfully for db_user_id {db_user_id}. Server response: {response_text}")
                else:
                    logging.error(f"Failed to update user status for db_user_id {db_user_id}: HTTP {response.status}, Response: {response_text}")
    else:
        logging.error(f"No db_user_id found for user_id {user_id}. Cannot update status.")

if __name__ == '__main__':
    client.start(bot_token=TELEGRAM_BOT_TOKEN)
    client.run_until_disconnected()
