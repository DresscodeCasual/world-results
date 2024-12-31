from django.shortcuts import render

from .views_common import group_required

from django.apps import apps

from django.db import models as dj_models
from operator import itemgetter

import logging

log = logging.getLogger(__name__)

def relation_type(f):
        if not f.is_relation:
            assert not (f.many_to_many or f.many_to_one or f.one_to_many or f.one_to_one)
            return '-'
        else:
            assert sum(map(int, [f.many_to_many, f.many_to_one, f.one_to_many, f.one_to_one])) == 1
        if f.many_to_many:
            return 'm2m'
        elif f.many_to_one:
            return 'm2o'
        elif f.one_to_many:
            return 'o2m';
        else:
            assert f.one_to_one
            return 'o2o'


def model_name_as_link(model: dj_models.Model, up=False, short=True):
    url_prefix = '../' if up else ''
    link_text_prefix = '' if short else model._meta.app_label + '.'

    return '<a href="{}{}">{}{}</a>'.format(
        url_prefix,
        model._meta.app_label + '.' + model.__name__,
        link_text_prefix,
        model.__name__
    )


def mk_table_of_models():
    log.info('mk_table_of_models()')

    def find_related(model):
        related_models = {
            'o2o' : [],
            'o2m' : [],
            'm2o' : [],
            'm2m' : []
        }
        for f in model._meta.get_fields(include_parents=True, include_hidden=True):
            r_type = relation_type(f)
            if r_type != '-':
                related_models[r_type].append(model_name_as_link(f.related_model))

        # return {k : ':'.join(v) for k, v in related_models.items()}
        return related_models


    def show_verbose_name_if_exists(model):
        v_name = model._meta.verbose_name
        if v_name.lower() == model.__name__.lower():
            return ''
        else:
            return '<br />' + str(v_name)

    table_header = [
            'Модель',
            'sql-таблица',
            'Число полей',
            'Число полей (с унаследованными и скрытыми)',
            'один к одному',
            'один ко многим',
            'многие к одному',
            'многие ко многим'
        ]

    n_of_columns = len(table_header)
    table_header = None  # Real table header is in the template file.
    table_body = []

    for app_config in apps.get_app_configs():
        for model in app_config.get_models():
            related_models = find_related(model)
            # print '-===', related_models

            models_row = [
                model_name_as_link(model, short=False) + show_verbose_name_if_exists(model),
                model._meta.db_table,
                len(model._meta.get_fields(include_parents=False, include_hidden=False)),
                len(model._meta.get_fields(include_parents=True, include_hidden=True)),
                ', '.join(related_models['o2o']),
                ', '.join(related_models['o2m']),
                ', '.join(related_models['m2o']),
                ', '.join(related_models['m2m']),
                 app_config.label + ( model.order_for_db_structure if hasattr(model, 'order_for_db_structure') else zzz ) + model.__name__
            ]
            assert len(models_row) == n_of_columns + 1
            table_body.append(models_row)

    table_body.sort(key=itemgetter(-1))
    table_body = [x[:-1] for x in table_body]

    return table_header, table_body
# /def mk_table_of_models()


def mk_table_of_fields(model_name):
    log.info('mk_table_of_fields(model_name)')

    # if model.__name__ != 'Club': return

    def safe_getattr(f, attr):
        try:
            res = getattr(f, attr)
            return res
        except AttributeError:
            return '-'

    def smart_safe_getattr(f, attr):
        res = safe_getattr(f, attr)
        if res == False:
            res = ' '
        elif str(res) == 'django.db.models.fields.NOT_PROVIDED':
            res = '(не указано)'
        return res

    def smart2_safe_getattr(f, attr):
        res = safe_getattr(f, attr)
        if res is None:
            res = ' '
        return res

    def safe_method(f, attr):
        try:
            res = getattr(f, attr)()
            return res
        except AttributeError:
            return '-'

    def get_related_model_name(f, unused):
        model = safe_getattr(f, 'related_model')
        if model == '-' or model is None:
            return '-'
        else:
            return model_name_as_link(model, up=True)

    model = apps.get_model(model_name)

    columns_specification = (
        ('Name', lambda f, s: f.name),
        ('verbose_name', safe_getattr),
        ('Type', lambda f, s: type(f).__name__),
        ('attname', safe_getattr),
        ('help_text',   safe_getattr),
#        ( '__unicode__', safe_method),
        ('primary_key', smart_safe_getattr),
        ('unique',  smart_safe_getattr),
        ('auto_created', smart_safe_getattr),
        ('column', safe_getattr),
        ('max_length', safe_getattr),
        ('db_column', smart2_safe_getattr),
        ('db_index', smart_safe_getattr),
        ('default', smart_safe_getattr),
        ('related_model', get_related_model_name),
        ('relation_type', lambda f, s: relation_type(f))
    )


    table_header = list(map(itemgetter(0), columns_specification))

    table_body = []

    for f in model._meta.get_fields(include_parents=True, include_hidden=True):
        if f.model != model:
            log.info('f.model != model: model={}, field={}, f.model={}'.format(str(model), str(f), str(f.model)))
#        if not f.is_relation:
#          assert not hasattr(f, 'related_model')
        if f.is_relation:
            assert f.many_to_many + f.many_to_one + f.one_to_many + f.one_to_one == 1
            assert hasattr(f, 'related_model')
        assert f.concrete == hasattr(f, 'db_column')
        assert f.concrete == hasattr(f, 'column')
#        if not ((type(f).__name__ == 'ManyToOneRel') == (relation_type(f) == 'o2m') == f.auto_created):
 #           print f, type(f).__name__, relation_type(f), f.auto_created

        assert (type(f).__name__ == 'ManyToOneRel') == (relation_type(f) == 'o2m')
        assert (type(f).__name__ == 'ForeignKey') == (relation_type(f) == 'm2o')

        assert (type(f).__name__ in {'OneToOneRel', 'OneToOneField'}) == (relation_type(f) == 'o2o')
        # https://stackoverflow.com/questions/28180207/difference-between-djangos-onetoonefield-and-djangos-onetoonerel?utm_medium=organic&utm_source=google_rich_qa&utm_campaign=google_rich_qa

        assert (type(f).__name__ in {'ManyToManyRel', 'ManyToManyField'}) ==  (relation_type(f) == 'm2m')

        if f.auto_created:
            assert type(f).__name__ in {'ManyToOneRel', 'AutoField', 'OneToOneRel', 'ManyToManyRel'}
        if type(f).__name__ in { 'ManyToOneRel', 'OneToOneRel', 'ManyToManyRel'}:
            assert f.auto_created
        # type AutoField may be not f.auto_created...

        # uni = safe_method(f, '__str__')
        # print(f'Field: {f.name}, auto_created: {f.auto_created}, type: {type(f).__name__}, uni: {uni}')
        # assert (f.auto_created and (type(f).__name__ != 'AutoField')) == (uni == '-')

        related_model = safe_getattr(f, 'related_model')
        assert related_model != '-'
        assert (relation_type(f) == '-') == (related_model is None)

#        assert if type(f).__name__ == 'ManyToOneRel':

        fields_row = [fun(f, s) for s, fun in columns_specification]
        table_body.append(list(map(str, fields_row)))

    return table_header, table_body
# /def mk_table_of_fields(model_name)


@group_required('admins')
def show_abstract_table(
            request,
            table_header,
            table_body,
            page_title=None,
            table_title=None,
            text_before_header=None,
            footer=None
        ):
    context = {}
    context['page_title'] = page_title
    context['table_header'] = table_header
    context['table_body'] = table_body
    context['page_title'] = page_title
    context['table_title'] = table_title
    context['text_before_header'] = text_before_header
    context['footer'] = footer
    return render(request, "editor/abstract_table.html", context)


@group_required('admins')
def db_structure(request, model_name=None):
    log.info('db_structure()')

    if model_name is None:
        page_title = table_title = 'Список моделей'
        table_header, table_body = mk_table_of_models()
        text_before_header = footer = None
    else:
        page_title = table_title = 'Модель ' + model_name
        table_header, table_body = mk_table_of_fields(model_name)
        text_before_header = footer = '<a href="../">Список моделей</a>'

    context = {}
    context['page_title'] = page_title
    context['table_body'] = table_body
    context['page_title'] = page_title
    context['table_title'] = table_title
    context['text_before_header'] = text_before_header
    context['footer'] = footer

    if model_name is None:
        assert table_header is None  # table header is in the template file
        return render(request, "editor/db_structure.html", context)
    else:
        context['table_header'] = table_header
        return render(request, "editor/abstract_table.html", context)
