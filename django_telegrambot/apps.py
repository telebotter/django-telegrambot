# coding=utf-8
# django_telegram_bot/apps.py
import os.path
import importlib
from collections import OrderedDict

import telegram
import logging
from time import sleep

from django.apps import AppConfig
from django.apps import apps
from django.conf import settings
from django.utils.module_loading import module_has_submodule

from telegram.ext import Dispatcher
from telegram.ext import Updater
from telegram.error import InvalidToken
from telegram.error import RetryAfter
from telegram.error import TelegramError
from telegram.utils.request import Request
from telegram.ext import messagequeue as mq

from .mqbot import MQBot


logger = logging.getLogger(__name__)


TELEGRAM_BOT_MODULE_NAME = settings.DJANGO_TELEGRAMBOT.get('BOT_MODULE_NAME', 'telegrambot')
WEBHOOK_MODE, POLLING_MODE = range(2)


class classproperty(property):
    def __get__(self, obj, objtype=None):
        return super(classproperty, self).__get__(objtype)
    def __set__(self, obj, value):
        super(classproperty, self).__set__(type(obj), value)
    def __delete__(self, obj):
        super(classproperty, self).__delete__(type(obj))


class DjangoTelegramBot(AppConfig):

    name = 'django_telegrambot'
    verbose_name = 'Django TelegramBot'
    ready_run = False
    bots_data = OrderedDict()
    __used_tokens = set()

    @classproperty
    def dispatcher(cls):
        try:
            #print("Getting value default dispatcher")
            bot_data = list(cls.bots_data.values())[0]
            cls.__used_tokens.add(bot_data['token'])
            return next(bot_data['dispatcher'])
        except StopIteration:
            raise ReferenceError("No bots are defined")

    @classproperty
    def updater(cls):
        try:
            #print("Getting value default dispatcher")
            bot_data = list(cls.bots_data.values())[0]
            cls.__used_tokens.add(bot_data['token'])
            return next(bot_data['updater'])
        except StopIteration:
            raise ReferenceError("No bots are defined")


    @classmethod
    def getBotById(cls, bot_id=None, safe=True):
        if bot_id is None:
            return list(cls.bots_data.values())[0]
        else:
            try:
                bot = cls.bots_data[bot_id]
            except KeyError:
                if not safe:
                    return None
                try:
                    bot = next(filter(lambda bot: bot['id'] == bot_id, list(cls.bots_data.values())))
                except StopIteration:
                    try:
                        bot = next(filter(lambda bot: bot['bot'].username == bot_id, list(cls.bots_data.values())))
                    except StopIteration:
                        return None
            cls.__used_tokens.add(bot['token'])
            return bot


    @classmethod
    def get_dispatcher(cls, bot_id=None, safe=True):
        bot = cls.getBotById(bot_id, safe)
        if bot:
            return bot['dispatcher']
        else:
            return None


    @classmethod
    def getDispatcher(cls, bot_id=None, safe=True):
        return cls.get_dispatcher(bot_id, safe)


    @classmethod
    def get_bot(cls, bot_id=None, safe=True):
        bot = cls.getBotById(bot_id, safe)
        if bot:
            return bot['bot']
        else:
            return None


    @classmethod
    def getBot(cls, bot_id=None, safe=True):
        return cls.get_bot(bot_id, safe)


    @classmethod
    def get_updater(cls, bot_id=None, safe=True):
        bot = cls.getBotById(bot_id, safe)
        if bot:
            return bot['updater']
        else:
            return None


    @classmethod
    def getUpdater(cls, id=None, safe=True):
        return cls.get_updater(id, safe)


    def ready(self):
        if DjangoTelegramBot.ready_run:
            return
        DjangoTelegramBot.ready_run = True

        self.mode = WEBHOOK_MODE
        if settings.DJANGO_TELEGRAMBOT.get('MODE', 'WEBHOOK') == 'POLLING':
            self.mode = POLLING_MODE

        modes = ['WEBHOOK','POLLING']
        logger.info('Django Telegram Bot <{} mode>'.format(modes[self.mode]))

        bots_list = settings.DJANGO_TELEGRAMBOT.get('BOTS', [])

        if self.mode == WEBHOOK_MODE:
            webhook_site = settings.DJANGO_TELEGRAMBOT.get('WEBHOOK_SITE', None)
            if not webhook_site:
                logger.warn('Required TELEGRAM_WEBHOOK_SITE missing in settings')
                return
            if webhook_site.endswith("/"):
                webhook_site = webhook_site[:-1]

            webhook_base = settings.DJANGO_TELEGRAMBOT.get('WEBHOOK_PREFIX','/')
            if webhook_base.startswith("/"):
                webhook_base = webhook_base[1:]
            if webhook_base.endswith("/"):
                webhook_base = webhook_base[:-1]

            cert = settings.DJANGO_TELEGRAMBOT.get('WEBHOOK_CERTIFICATE', None)
            certificate = None
            if cert and os.path.exists(cert):
                logger.info('WEBHOOK_CERTIFICATE found in {}'.format(cert))
                certificate=open(cert, 'rb')
            elif cert:
                logger.error('WEBHOOK_CERTIFICATE not found in {} '.format(cert))

        for b in bots_list:
            bot_data = {
                'token': b['TOKEN'],
                'id': b.get('ID', None)
            }

            context = b.get('CONTEXT', False),
            allowed_updates = b.get('ALLOWED_UPDATES', None)
            timeout = b.get('TIMEOUT', None)
            proxy = b.get('PROXY', None)

            if self.mode == WEBHOOK_MODE:
                try:
                    if b.get('MESSAGEQUEUE_ENABLED',False):
                        q = mq.MessageQueue(all_burst_limit=b.get('MESSAGEQUEUE_ALL_BURST_LIMIT',29),
                        all_time_limit_ms=b.get('MESSAGEQUEUE_ALL_TIME_LIMIT_MS',1024))
                        if proxy:
                            request = Request(proxy_url=proxy['proxy_url'], urllib3_proxy_kwargs=proxy['urllib3_proxy_kwargs'], con_pool_size=b.get('MESSAGEQUEUE_REQUEST_CON_POOL_SIZE',8))
                        else:
                            request = Request(con_pool_size=b.get('MESSAGEQUEUE_REQUEST_CON_POOL_SIZE',8))
                        bot = MQBot(bot_data['token'], request=request, mqueue=q)
                    else:
                        request = None
                        if proxy:
                            request = Request(proxy_url=proxy['proxy_url'], urllib3_proxy_kwargs=proxy['urllib3_proxy_kwargs'])
                        bot = telegram.Bot(token=bot_data['token'], request=request)

                    bot_data['dispatcher'] = Dispatcher(bot, None, workers=0, use_context=context)
                    if not settings.DJANGO_TELEGRAMBOT.get('DISABLE_SETUP', False):
                        hookurl = '{}/{}/{}/'.format(webhook_site, webhook_base, bot_data['token'])
                        max_connections = b.get('WEBHOOK_MAX_CONNECTIONS', 40)
                        setted = bot.setWebhook(hookurl, certificate=certificate, timeout=timeout, max_connections=max_connections, allowed_updates=allowed_updates)
                        webhook_info = bot.getWebhookInfo()
                        real_allowed = webhook_info.allowed_updates if webhook_info.allowed_updates else ["ALL"]
                        bot.more_info = webhook_info
                        logger.info('Telegram Bot <{}> setting webhook [ {} ] max connections:{} allowed updates:{} pending updates:{} : {}'.format(bot.username, webhook_info.url, webhook_info.max_connections, real_allowed, webhook_info.pending_update_count, setted))
                    else:
                        logger.info('Telegram Bot setting webhook without enabling receiving')
                except InvalidToken:
                    logger.error('Invalid Token : {}'.format(bot_data['token']))
                    return
                except RetryAfter as er:
                    logger.debug('Error: "{}". Will retry in {} seconds'.format(
                            er.message,
                            er.retry_after
                        )
                    )
                    sleep(er.retry_after)
                    self.ready()
                except TelegramError as er:
                    logger.error('Error: "{}"'.format(er.message))
                    return

            else:
                try:
                    if not settings.DJANGO_TELEGRAMBOT.get('DISABLE_SETUP', False):
                        updater = Updater(token=bot_data['token'], request_kwargs=proxy, use_context=context)
                        bot = updater.bot
                        bot.delete_webhook()
                        bot_data['updater'] = updater
                        bot_data['dispatcher'] = updater.dispatcher
                        DjangoTelegramBot.__used_tokens.add(bot_data['token'])
                    else:
                        request = None
                        if proxy:
                            request = Request(proxy_url=proxy['proxy_url'], urllib3_proxy_kwargs=proxy['urllib3_proxy_kwargs'])
                        bot = telegram.Bot(token=bot_data['token'], request=request)
                        bot_data['dispatcher'] = Dispatcher(bot, None, workers=0, use_context=context)
                except InvalidToken:
                    logger.error('Invalid Token : {}'.format(bot_data['token']))
                    return
                except RetryAfter as er:
                    logger.debug('Error: "{}". Will retry in {} seconds'.format(
                            er.message,
                            er.retry_after
                        )
                    )
                    sleep(er.retry_after)
                    self.ready()
                except TelegramError as er:
                    logger.error('Error: "{}"'.format(er.message))
                    return

            bot_data['bot'] = bot
            DjangoTelegramBot.bots_data[bot_data['token']] = bot_data

        first_bot = list(DjangoTelegramBot.bots_data.values())[0]
        if not settings.DJANGO_TELEGRAMBOT.get('DISABLE_SETUP', False):
            logger.debug('Telegram Bot <{}> set as default bot'.format(first_bot['bot'].username))
        else:
            logger.debug('Telegram Bot <{}> set as default bot'.format(first_bot['id'] if first_bot['id'] else first_bot['token']))

        def module_imported(module_name, method_name, execute):
            try:
                m = importlib.import_module(module_name)
                if execute and hasattr(m, method_name):
                    logger.debug('Run {}.{}()'.format(module_name,method_name))
                    getattr(m, method_name)()
                else:
                    logger.debug('Run {}'.format(module_name))

            except ImportError as er:
                if settings.DJANGO_TELEGRAMBOT.get('STRICT_INIT'):
                    raise er
                else:
                    logger.error('{} : {}'.format(module_name, repr(er)))
                    return False

            return True

        # import telegram bot handlers for all INSTALLED_APPS
        for app_config in apps.get_app_configs():
            if module_has_submodule(app_config.module, TELEGRAM_BOT_MODULE_NAME):
                module_name = '%s.%s' % (app_config.name, TELEGRAM_BOT_MODULE_NAME)
                if module_imported(module_name, 'main', True):
                    logger.info('Loaded {}'.format(module_name))

        num_bots=len(DjangoTelegramBot.__used_tokens)
        if self.mode == POLLING_MODE and num_bots>0:
            logger.info('Please manually start polling update for {0} bot{1}. Run command{1}:'.format(num_bots, 's' if num_bots>1 else ''))
            for token in DjangoTelegramBot.__used_tokens:
                updater = DjangoTelegramBot.get_updater(bot_id=token)
                logger.info('python manage.py botpolling --username={}'.format(updater.bot.username))
