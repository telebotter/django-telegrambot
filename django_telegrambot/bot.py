from telegram import Bot
from telegram.ext import Dispatcher, Updater


class BotData:
    def __init__(self,
                 token,
                 *,
                 unique_id=None,
                 use_context=False,
                 allowed_updates=None,
                 timeout=None,
                 proxy=None,
                 instance: Bot = None,
                 dispatcher: Dispatcher = None,
                 updater: Updater = None):
        self.token = token
        self.unique_id = unique_id
        self.use_context = use_context
        self.allowed_updates = allowed_updates
        self.timeout = timeout
        self.proxy = proxy
        self.instance = instance
        self.dispatcher = dispatcher
        self.updater = updater
