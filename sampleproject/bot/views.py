from django.shortcuts import render
from django.conf import settings
from django_telegrambot.apps import DjangoTelegramBot

# Create your views here.
def index(request):
    bot_list = [bot.instance for bot in DjangoTelegramBot.bots_data]
    context = {'bot_list': bot_list, 'update_mode':settings.DJANGO_TELEGRAMBOT['MODE']}
    return render(request, 'bot/index.html', context)
