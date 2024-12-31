import requests
import pandas as pd
import json
import os
import sys

def findraceinfo_new(z):
    searchfor_begin = 'var config'
    searchfor_end = 'function init(page)'
    raceidcontainer = str(r.content)
    index_begin = raceidcontainer.find(searchfor_begin)
    index_end = raceidcontainer.find(searchfor_end)
    raceinfo = raceidcontainer[index_begin+13:index_end-13]
    return raceinfo

if len(sys.argv) < 2:
    print('Please provide the URL at russiarunning.ru as an argument')
else:
    url = sys.argv[1]
    r = requests.get(url, allow_redirects = True)
    raceinfo = findraceinfo_new(r.content)
    json_raceinfo = raceinfo.replace("\\", "00000")
    x = json.loads(json_raceinfo)
    event_code = x['eventCode']
    writer = pd.ExcelWriter('combined_table_{}.xlsx'.format(event_code))
    race_ids = [(i['Id'], i['Code']) for i in x['races']]
    for i in race_ids:
        tableurl = 'https://russiarunning.com/Results/Services/DownloadProtocol?raceId={}&templateCode=RussiaRunning&fileExtension=xls&culture=ru'.format(i[0])
        results = requests.get(tableurl, allow_redirects = True)
        open('results' + str(i[1]) + '.xlsx', 'wb').write(results.content)
        df = pd.read_excel('results' + str(i[1]) + '.xlsx')
        df.to_excel(writer, sheet_name = str(i[1]), index = False, header = False)
        os.remove('results' + str(i[1]) + '.xlsx')
    writer.save()