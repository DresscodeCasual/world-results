from collections import namedtuple
import datetime
import json
from pathlib import Path
import re
import io

import click
import requests
import xlsxwriter

class IncorrectUrl(ValueError):
    pass

class EventId:
    def __init__(self, url):
        matches = re.findall(r"/Event/(\d+)/Course/(\d+)/", url)
        if len(matches) != 1:
            raise IncorrectUrl()
        self.event, self.course = list(map(int, matches[0]))

def fetch_bibs(event_id, limit):
    url = f"https://results.athlinks.com/event/{event_id.event}"
    PER_PAGE = 100
    params = {
        "eventCourseId": event_id.course,
        "from": 0,
        "limit": PER_PAGE,
    }
    req = requests.get(url, params)
    print(('Json URL: ' + req.url))
    first_page = req.json()
    total_athletes = first_page[0]["totalAthletes"]
    if limit is not None and limit < total_athletes:
        total_athletes = limit
    results = first_page[0]["interval"]["intervalResults"]
    for start in range(PER_PAGE, total_athletes, PER_PAGE):
        params["from"] = start
        page = requests.get(url, params).json()
        results += page[0]["interval"]["intervalResults"]
    return [result["bib"] for result in results]

def fetch_result(event_id, bib):
    url = "https://results.athlinks.com/individual"
    params = {
        "bib": bib,
        "eventId": event_id.event,
        "eventCourseId": event_id.course,
    }
    return requests.get(url, params).json()

def get(structure, path):
    """Достаёт из глубокой структуры поле по задаваемому строкой пути. При
    отсутствии возвращает None.

    >>> get({"foo": [{"bar": 42}]}, "foo 0 bar")
    42
    """
    for key in path.split():
        try:
            try:
                structure = structure[int(key)]
            except ValueError:
                structure = structure[key]
        except (IndexError, KeyError):
            return None
    return structure

def field_present(results, field):
    for record in results:
        if get(record, field.path) is not None:
            return True
    return False

Field = namedtuple("Field", "header path")

class Int(Field):
    width = 6

    ABSURDLY_HIGH = 900000

    def write(self, worksheet, row, col, record, _time_format):
        try:
            x = int(get(record, self.path))
            # У нефинишировавших на сервере указано «999999 место».
            if x > 0 and x < self.ABSURDLY_HIGH:
                worksheet.write(row, col, x)
        except (TypeError, ValueError):
            pass

class Str(Field):
    width = 15

    def write(self, worksheet, row, col, record, _time_format):
        x = get(record, self.path)
        # На сервере довольно много бессмысленных строк типа "," и
        # "--". Скорее всего, они не несут полезной информации.
        if x is not None and not re.match(r'\W*$', str(x)):
            if (self.header == "Статус") and (x == "CONF") and (get(record, "racerHasFinished") == False):
                # Ugly hack for strange athlinks rows with distance different from given,
                # e.g. Камчатный at https://www.athlinks.com/event/200468/results/Event/852444/Course/1575836/Results
                x = "DNF"
            worksheet.write(row, col, x)

class SmallStr(Str):
    width = 6

class MediumStr(Str):
    width = 9

class Time(Field):
    width = 9

    EPSILON = datetime.timedelta(seconds=1)

    def write(self, worksheet, row, col, record, time_format):
        try:
            x = get(record, self.path)
            t = datetime.timedelta(milliseconds=x["timeInMillis"])
            # Отсутствующее время на сервере сохранено как -1 мс. Но
            # если вдруг иногда -1, а иногда и 0 — то это, наверно,
            # тоже не надо показывать.
            if t > self.EPSILON:
                worksheet.write_datetime(row, col, t, time_format)
        except (TypeError, KeyError):
            return None

def get_fields(results):
    fields = [
        Int("BIB", "bib"),
        Str("Фамилия", "lastName"),
        Str("Имя", "firstName"),
        Int("Возраст", "age"),
        Str("Город", "locality"),
        Str("Регион", "region"),
        SmallStr("Страна", "country"),
        Int("Место в абсолюте", "intervals 0 brackets 0 rank"),
        Int("Всего участников", "intervals 0 brackets 0 totalAthletes"),
        SmallStr("Пол", "gender"),
        Int("Место среди пола", "intervals 0 brackets 1 rank"),
        Int("Участников в нём", "intervals 0 brackets 1 totalAthletes"),
        MediumStr("Группа", "intervals 0 brackets 2 bracketName"),
        Int("Место в группе", "intervals 0 brackets 2 rank"),
        Int("Участников в ней", "intervals 0 brackets 2 totalAthletes"),
        Str("Статус", "entryStatus"),
        Time("Чистое время", "intervals 0 chipTime"),
        Time("Грязное время", "intervals 0 gunTime"),
    ]
    intervals = get(results, "0 intervals")
    if intervals:
        for i, interval in enumerate(intervals):
            intervalName = get(interval, "intervalName")
            intervalFull = get(interval, "intervalFull")
            if intervalName and not intervalFull:
                fields.append(Time(intervalName, f"intervals {i} chipTime"))
    return [field for field in fields if field_present(results, field)]

def write(output, results):
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()
    bold = workbook.add_format({"bold": True})
    fields = get_fields(results)
    for col_number, field in enumerate(fields):
        worksheet.set_column(col_number, col_number, field.width)
        worksheet.write(0, col_number, field.header, bold)
    time_format = workbook.add_format({"num_format": "hh:mm:ss", "align": "left"})
    for row_number, record in enumerate(results):
        for col_number, field in enumerate(fields):
            field.write(worksheet, row_number + 1, col_number, record, time_format)
    workbook.close()

@click.command()
@click.argument("url")
@click.argument("output", type=click.Path(dir_okay=False))
@click.option("--top", type=int)
@click.option("--save-json/--no-save-json", default=True)
def main(url, output, top, save_json):
    try:
        event_id = EventId(url)
    except IncorrectUrl:
        click.echo("Не понимаю такой исходный URL", err=True)
        return
    results = None
    json_file = Path(output).with_suffix(".json")
    if json_file.exists():
        with io.open(json_file, encoding="utf8") as json_fp:
            results = json.load(json_fp)
        click.echo(f"Использую результаты из {json_file}")
    if results is None:
        click.echo("Скачиваю список участников")
        bibs = fetch_bibs(event_id, top)
        if not bibs:
            click.echo("Нет участников!")
            return
        if top is not None:
            bibs = bibs[:top]
        label = f"Скачиваю подробные результаты {len(bibs)} участников"
        with click.progressbar(bibs, label=label) as bibs:
            results = [fetch_result(event_id, bib) for bib in bibs]
        if save_json:
            click.echo(f"Записываю исходные данные в {json_file}")
            with io.open(json_file, "w", encoding="utf8") as json_fp:
                json.dump(
                    results,
                    json_fp,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=4
                )
    write(output, results)

if __name__=="__main__":
    main()
