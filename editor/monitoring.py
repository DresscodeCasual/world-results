from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from django.db.models import Min, Q
from django.urls import reverse

import datetime
import os

from results import models, models_klb, results_util

# Number of free bytes that ordinary users
# are allowed to use (excl. reserved space)
def get_available_space():
    statvfs = os.statvfs(settings.BASE_DIR)
    return statvfs.f_frsize * statvfs.f_bavail

N_BAD_USERS_TO_SEND = 3
def check_users_and_runners_links(robot):
    res = ''
    users_wo_profile = User.objects.filter(user_profile=None)
    if users_wo_profile.exists():
        res += '\n\nПользователей, у которых не было профиля: {}. Первые:'.format(users_wo_profile.count())
        for user in users_wo_profile[:N_BAD_USERS_TO_SEND]:
            models.User_profile.objects.get_or_create(user=user)
            res += '\n{} {}{} (создали профиль только что)'.format(
                user.get_full_name(), results_util.SITE_URL, reverse('results:user_details', kwargs={'user_id': user.id}))

    active_users_wo_runner = User.objects.filter(is_active=True, runner=None)
    if active_users_wo_runner.exists():
        res += '\n\nАктивных пользователей, у которых не был указан бегун: {}. Первые:'.format(active_users_wo_runner.count())
        for user in active_users_wo_runner[:N_BAD_USERS_TO_SEND]:
            if hasattr(user, 'user_profile'):
                user.user_profile.create_runner(robot, comment='При ночной проверке роботом')
                res += '\n{} {}{} (создали бегуна только что)'.format(user.get_full_name(), results_util.SITE_URL, user.user_profile.get_absolute_url())

    inactive_users_with_runner = User.objects.filter(is_active=False, runner__isnull=False)
    if inactive_users_with_runner.exists():
        res += '\n\nНеактивных пользователей, у которых указан бегун: {}. Первые:'.format(inactive_users_with_runner.count())
        for user in inactive_users_with_runner[:N_BAD_USERS_TO_SEND]:
            if hasattr(user, 'user_profile'):
                res += '\n{} {}{}'.format(user.get_full_name(), results_util.SITE_URL, user.user_profile.get_absolute_url())

    klb_persons_wo_runner = models.Klb_person.objects.filter(runner=None)
    if klb_persons_wo_runner.exists():
        res += '\n\nУчастников КЛБМатчей, не привязанных ни к какому бегуну: {}. Первые:'.format(klb_persons_wo_runner.count())
        for person in klb_persons_wo_runner[:N_BAD_USERS_TO_SEND]:
            res += '\n{} {}{}'.format(person.get_full_name_with_birthday(), results_util.SITE_URL, person.get_absolute_url())

    klb_results_wo_person = models.Klb_result.objects.filter(klb_person=None)
    if klb_results_wo_person.exists():
        res += '\n\nРезультатов КЛБМатчей, не привязанных ни к какому КЛБ-участнику: {}. Первые:'.format(klb_results_wo_person.count())
        for klb_result in klb_results_wo_person[:N_BAD_USERS_TO_SEND]:
            res += '\n{} (id {}), результат {} (id {})'.format(
                klb_result.race.name_with_event(), klb_result.race.id, klb_result.time_seconds_raw, klb_result.id)

    klb_results_wo_participant = models.Klb_result.objects.filter(klb_participant=None)
    if klb_results_wo_participant.exists():
        res += f'\n\nРезультатов КЛБМатчей, не привязанных ни к какому участнику отдельных матчей: {klb_results_wo_participant.count()}. Первые:'
        for klb_result in klb_results_wo_participant[:N_BAD_USERS_TO_SEND]:
            res += '\n{} (id {}), результат {} (id {})'.format(
                klb_result.race.name_with_event(), klb_result.race.id, klb_result.time_seconds_raw, klb_result.id)

    # 7383 - because of double Alexandr Terentyev in 2017
    min_id_klb_persons = models.Klb_person.objects.values('lname', 'fname', 'birthday').annotate(minid=Min('id')).order_by()
    min_ids = set(obj['minid'] for obj in min_id_klb_persons)
    duplicate_klb_persons = models.Klb_person.objects.exclude(pk=7383).exclude(id__in=min_ids)
    if duplicate_klb_persons.exists():
        res += '\n\nПар участников КЛБМатчей с одинаковыми фамилией, именем, датой рождения: {}. Первые:'.format(duplicate_klb_persons.count())
        for person in duplicate_klb_persons[:N_BAD_USERS_TO_SEND]:
            res += '\n{} {}{}'.format(person.get_full_name_with_birthday(), results_util.SITE_URL,
                reverse('results:runners', kwargs={'lname': person.lname, 'fname': person.fname}))

    unoff_results_with_no_runner = models.Result.objects.filter(runner=None).exclude(source=models.RESULT_SOURCE_DEFAULT)
    n_unoff_results_with_no_runner = unoff_results_with_no_runner.count()
    if n_unoff_results_with_no_runner:
        res += f'\n\nРезультатов, добавленных вручную и не привязанных к бегунам: {n_unoff_results_with_no_runner}. Первые:'
        for result_id in unoff_results_with_no_runner.values_list('pk', flat=True)[:N_BAD_USERS_TO_SEND]:
            res += f'\n{result_id}'

    klb_results_user_unclaimed_exceptions = {
        2023: [8155080, # Денис Симонов denis.simonov85@mail.ru не хочет видеть на своей странице
        ],
    }
    klb_results_user_unclaimed = models.Klb_result.objects.filter(is_error=False, result__user=None, result__race__event__start_date__year=models_klb.CUR_KLB_YEAR).exclude(
        result__runner__user=None).exclude(result_id__in=klb_results_user_unclaimed_exceptions.get(models_klb.CUR_KLB_YEAR, set()))
    n_klb_results_user_unclaimed = klb_results_user_unclaimed.count()
    if n_klb_results_user_unclaimed:
        res += f'\n\nРезультатов в КЛБМатче-{models_klb.CUR_KLB_YEAR}, которые пользователи от себя отвязали: {n_klb_results_user_unclaimed}. Первые:'
        for result_id in klb_results_user_unclaimed.values_list('result_id', flat=True)[:N_BAD_USERS_TO_SEND]:
            res += f'\n{result_id}'

    races_kept_for_reg_only_but_with_results = models.Race.objects.filter(kept_for_reg_history_only=True).exclude(load_status=models.RESULTS_NOT_LOADED)
    n_races_kept_for_reg_only_but_with_results = races_kept_for_reg_only_but_with_results.count()
    if n_races_kept_for_reg_only_but_with_results:
        res += f'\n\nДистанций, помеченных как хранимые только ради регистрации через наш сайт, но на которых есть результаты: {n_races_kept_for_reg_only_but_with_results}. Первые:'
        for race in races_kept_for_reg_only_but_with_results[:N_BAD_USERS_TO_SEND]:
            res += f'\n{results_util.SITE_URL}{race.get_absolute_url()}'

    cancelled_events = set(models.Event.objects.filter(Q(cancelled=True) | Q(invisible=True)).values_list('pk', flat=True))
    cancelled_events_with_results = set(models.Result.objects.filter(race__event_id__in=cancelled_events).values_list('race__event_id', flat=True))
    n_cancelled_events_with_results = len(cancelled_events_with_results)
    if n_cancelled_events_with_results:
        res += f'\n\nНевидимых или отменённых забегов с результатами: {n_cancelled_events_with_results}. Первые:'
        for event_id in list(cancelled_events_with_results)[:N_BAD_USERS_TO_SEND]:
            res += f'\n{event_id}'

    return res

# Sends the list of all Function_calls that weren't mailed yet
def send_function_calls_letter():
    body = 'Доброе утро! Это — ежедневное письмо о том, что сделал за ночь робот.\n\n'

    if get_available_space() < 200000000:
        body += 'Осталось меньше 200 мегабайт места на диске!\nБольшие файлы можно поискать командой `find / -xdev -type f -size +300M`.\n\n'

    three_days_ago = timezone.now() - datetime.timedelta(days=3)
    n_letters = models.Message_from_site.objects.filter(is_sent=False, date_posted__gte=three_days_ago).count()
    if n_letters:
        body += f'За последние 3 дня не получилось отправить {n_letters} пис{results_util.ending(n_letters, 30)}!\n\n'

    prev_message_ids = set(models.Function_call.objects.filter(message__is_sent=False).values_list('message_id', flat=True))
    if prev_message_ids:
        body += f'Писем о действиях робота, которые не получилось отправить ранее: {len(prev_message_ids)}. ID последнего: {max(prev_message_ids)}\n\n'

    calls = models.Function_call.objects.filter(message=None).order_by('pk')
    for i, call in enumerate(calls):
        body += f'{i + 1}. {call.description}: {call.name}({call.args})\n'
        body += f'Старт: {call.start_time}\n'
        if call.running_time:
            if call.result:
                body += f'Результат: {call.result}\n'
            body += f'Время работы: {call.running_time}\n\n'
        else:
            body += f'Не завершилось. Ошибка: {call.error}\n\n'

    body += 'Ваш смотритель за Роботом Присоединителем'

    message_from_site = models.Message_from_site.objects.create(
        message_type=models.MESSAGE_TYPE_FROM_ROBOT,
        title='Новости от Робота Смотрителя',
        body=body,
        created_by=models.USER_ROBOT_CONNECTOR,
    )
    message_from_site.try_send()
    if message_from_site.is_sent:
        calls.update(message=message_from_site)
