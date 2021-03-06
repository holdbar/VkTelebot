# -*- coding: utf-8 -*-

import local_config as config
import tornado
import vk
from tornado.httpserver import HTTPServer
from tornado.ioloop import PeriodicCallback, IOLoop
from tornado.queues import Queue, QueueEmpty
from telebot import TeleBot, types
import pdb


# periodic launch of async tasks to process tasks in queue
class CustomPeriodicCallback(PeriodicCallback):
    def __init__(self, request_queue, response_queue, callback_time, io_loop=None):
        if callback_time <= 0:
            raise ValueError("Periodic callback time must be positive")

        self.callback_time = callback_time
        self.io_loop = io_loop or IOLoop.current()
        self._running = False
        self._timeout = None
        self.request_queue = request_queue
        self.response_queue = response_queue


    # queue processing, single thread work with DB
    # taske task from queue, process, write changes into DB
    def queue_callback(self):
        try:
            message = self.request_queue.get_nowait()

        except QueueEmpty:
            pass
        else:
            start = False
            is_reset = False
            if message['text'] == 'telegram_cmd':
                self.response_queue.put({
                    'chat_id':message['chat_id'],
                    'wait_message_id': message['wait_message_id'],
                    'message_text': question,
                    'markup': markup
                    })
            self.request_queue.task_done()


    def _run(self):
        if not self._running:
            return
        try:
            return self.queue_callback()

        except Exception:
            self.io_loop.handle_callback_exception(self.queue_callback)
        finally:
            self._schedule_next()


# periodic lanch of requests reciever and reply sender
class BotPeriodicCallback(PeriodicCallback):
    def __init__(self, bot, callback_time, io_loop=None):
        if callback_time <= 0:
            raise ValueError("Periodic callback time must be positive")

        self.callback_time = callback_time
        self.io_loop = io_loop or IOLoop.current()
        self._running = False
        self._timeout = None
        self.bot = bot


    def bot_callback(self, timeout=1):
        if self.bot.skip_pending:
            self.bot.skip_pending = False
        updates = self.bot.get_updates(offset=(self.bot.last_update_id + 1), timeout=timeout)
        self.bot.process_new_updates(updates)
        self.bot.send_response_messages()


    def _run(self):
        if not self._running:
            return
        try:
            return self.bot_callback()

        except Exception:
            self.io_loop.handle_callback_exception(self.bot_callback)
        finally:
            self._schedule_next()


# periodic check of updates from VK
class VkPeriodicCallback(PeriodicCallback):
    def __init__(self, bot, user_dict, callback_time, io_loop=None):
        if callback_time <= 0:
            raise ValueError("Periodic callback time must be positive")

        self.callback_time = callback_time
        self.io_loop = io_loop or IOLoop.current()
        self._running = False
        self._timeout = None
        self.user_dict = user_dict
        self.bot = bot


    def update_user_dict(self, dialog_id, last_message_id, user_id):
        """Update dictionary where last messages and dialogs id are stored.
        
        Helps to prevent downloading already downloaded messages.
        """

        self.dialog_id = str(dialog_id)
        self.last_message_id = int(last_message_id)
        self.user_id = user_id
        self.user_dict[self.user_id]['dialog_dict'][self.dialog_id] = {'last_message_id':self.last_message_id, 
                                                                       'dialog_id' : int(dialog_id)}


    def get_contacts(bot, tele_id):
        """Returns list of your contacts."""

        if tele_id == config.USERID:
            session = vk.AuthSession(app_id=config.APPID, user_login=config.LOGIN, 
                                    user_password=config.PASSWORD, scope='messages')
            vk_api = vk.API(session, v='5.38')
            response = vk_api.messages.getDialogs()
            for item in response['items']:
                # pdb.set_trace()
                if item['message'].get('chat_id'):
                    chat_name = item['message']['title']
                    dialog_id = str(2000000000 + item['message']['chat_id'])
                else:
                    user_id = item['message'].get('user_id')
                    user = vk_api.users.get(user_id=user_id)
                    chat_name = user[0].get('last_name') + ' ' + user[0].get('first_name')
                    dialog_id = str(user_id)

                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton(text=chat_name, callback_data=dialog_id))
                bot.send_message(tele_id, 'Contact:', reply_markup=keyboard)
        else:
            bot.send_message(tele_id, 'You are not authorized')


    def set_response_addressat(user_dict, user_id, addressat_id):
        """Updates user_dict to set response addressat VK ID.

        ID is retrieved by choosing message in telegram.
        """

        user_dict = user_dict
        user_id = str(user_id)
        addressat_id = addressat_id
        user_dict[user_id]['addressat_id'] = addressat_id



    def mark_messages_read(peer_id):
        """Marks chosen dialog as read."""

        session = vk.AuthSession(app_id=config.APPID, user_login=config.LOGIN, 
                                user_password=config.PASSWORD, scope='messages')
        vk_api = vk.API(session, v='5.38')
        vk_api.messages.markAsRead(peer_id=peer_id)  # for chat peer_id = 2000000000 + chat_id       


    def send_messages(peer_id, message):
        """Sends messages to VK."""

        session = vk.AuthSession(app_id=config.APPID, user_login=config.LOGIN, 
                                user_password=config.PASSWORD, scope='messages')
        vk_api = vk.API(session, v='5.38')
        vk_api.messages.send(peer_id=peer_id, message=message)



    def get(self):
        """Makes auth and then call method to retrieve unread messages.

        Then pushes messages to telegram.
        """
        
        # choose user to check updates(!!TODO CONNECT TO DB AND RUN LOOP TO CHOOSE USER)
        user_id = str(config.USERID)
        # authentication with user's credentials
        session = vk.AuthSession(app_id=config.APPID, user_login=config.LOGIN, 
                                user_password=config.PASSWORD, scope='messages')
        vk_api = vk.API(session, v='5.38')

        if int(user_id) == config.USERID:
            #pdb.set_trace()
            result_list = self.get_messages(vk_api, user_id)
            text = ''
            for item in result_list:
                one_text = ''
                user = item[0]
                for l in item[1]:
                    one_text = one_text + l +'\n'
                text = text + user + '\n' + one_text + '\n'
                if text == '':
                    pass
                else:
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.add(types.InlineKeyboardButton(text=user, callback_data=item[2]))
                    self.bot.send_message(user_id, text, reply_markup=keyboard)
                    text = ''
        else:
            self.bot.send_message(user_id, 'You are not authorized')


    def get_messages(self, vk_api, user_id):
        """Get dialogs with unread messages.

        Then it prints user, user_id and messages.
        """

        response = vk_api.messages.getDialogs(unread=1)
        # print(response)
        result_list = []
        items = response.get('items')
        for item in items:
            message_list = []
            count = item.get('unread')
            last_message = item.get('message')
            last_message_id = last_message.get('id')
            if last_message.get('chat_id'):
                chat_name = last_message.get('title')
                dialog_id = str(2000000000 + last_message.get('chat_id'))
            else:
                chat_name = ''
                dialog_id = str(last_message.get('user_id'))
            if dialog_id in self.user_dict[user_id]['dialog_dict']:

                if int(last_message_id) <= self.user_dict[user_id]['dialog_dict'][dialog_id]['last_message_id']:
                    pass
                else:
                    self.update_user_dict(dialog_id, last_message_id, user_id)
                    result_list.append(self.get_unread_history(vk_api, dialog_id, chat_name, 
                                                                last_message, count, message_list))
            else:
                self.update_user_dict(dialog_id, last_message_id, user_id)
                result_list.append(self.get_unread_history(vk_api, dialog_id, chat_name, 
                                                                last_message, count, message_list))

        return result_list


    def get_unread_history(self, vk_api, dialog_id, chat_name, last_message, count, message_list):
        """Gets unread history by dialog_id."""
        user_id = last_message.get('user_id')
        user = vk_api.users.get(user_id=user_id)
        user = user[0].get('last_name') + ' ' + user[0].get('first_name') + ' ' + chat_name
        if chat_name == '':
            history = vk_api.messages.getHistory(user_id=dialog_id,start_message=-1,count=count)
        else:
            history = vk_api.messages.getHistory(user_id=dialog_id,start_message=-1,count=count)
        messages = history.get('items')
        for message in messages:
            message_list.append(message.get('body'))

        return (user, message_list, str(dialog_id))


    def _run(self):
        if not self._running:
            return
        try:
            return self.get()

        except Exception:
            self.io_loop.handle_callback_exception(self.get)
        finally:
            self._schedule_next()


# Add queue and result to the bot
class AppTeleBot(TeleBot, object):
    def __init__(self, token, request_queue, response_queue, threaded=True, skip_pending=False):
        super(AppTeleBot, self).__init__(token, threaded=True, skip_pending=False)
        self.request_queue = request_queue
        self.response_queue = response_queue


    # send all processed data from  result queue
    def send_response_messages(self):
        try:
            message = self.response_queue.get_nowait()

        except QueueEmpty:
            pass
        else:
            self.send_chat_action(message['chat_id'], 'typing')
            if message['message_text'] == 'contact':
                self.send_contact(message['chat_id'], phone_number=PHONE_NUMBER, last_name=LAST_NAME, 
                                  first_name=FIRST_NAME, reply_markup=message['markup'])
            else:
                self.send_chat_action(message['chat_id'], message['message_text'], reply_markup=message['markup'])
            self.response_queue.task_done()



def main():
    TOKEN = config.TOKEN

    request_queue = Queue(maxsize=0) 
    response_queue = Queue(maxsize=0)
    bot = AppTeleBot(TOKEN, request_queue, response_queue)

    user_id = config.USERID
    user_dict = {str(user_id):{'dialog_dict':{}}}


    @bot.message_handler(commands=['start','help'])
    def send_welcome(message):
        msg = bot.send_message(message.chat.id, 'Hello from bot')


    @bot.message_handler(commands=['pm'])
    def send_pm(message):
        peer_id = user_dict[str(message.chat.id)]['addressat_id']
        VkPeriodicCallback.send_messages(peer_id, message.text[3:])


    @bot.message_handler(commands=['cont'])
    def get_contacts(message):
        VkPeriodicCallback.get_contacts(bot, message.chat.id)


    @bot.callback_query_handler(func=lambda call: True)
    def callback_inline(call):
        VkPeriodicCallback.mark_messages_read(call.data)
        VkPeriodicCallback.set_response_addressat(user_dict, user_id, call.data)

        

    # add requests to the bot into queue
    @bot.message_handler(func=lambda message: True, content_types=['text'])
    def echo_all(message):
        markup = ReplyKeyboardRemove(selective=false)
        response = bot.send_message(message.chat.id, u'Please wait...', reply_markup=markup)
        bot.request_queue.put({
            'text': message.text,
            'chat_id': message.chat.id,
            'username': message.chat.username,
            'last_name': message.chat.last_name,
            'message_id': message.message_id,
            'wait_message_id': response.message_id
            })


    ioloop = tornado.ioloop.IOLoop.instance()

    BotPeriodicCallback(bot, 5000, ioloop).start()
    CustomPeriodicCallback(request_queue, response_queue, 5000, ioloop).start()
    VkPeriodicCallback(bot, user_dict, 5000, ioloop).start()

    ioloop.start()


if __name__ == "__main__":
    main()