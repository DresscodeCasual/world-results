from unittest import TestCase
import os

from editor.scrape import runsignup
from editor.scrape.runsignup import RunsignupRace

from bs4 import BeautifulSoup
from datetime import datetime
import pprint

RACES_INPUT=os.path.join(os.path.dirname(__file__), 'runsignup_golden/races.html')
RACES_INPUT_LAST=os.path.join(os.path.dirname(__file__), 'runsignup_golden/races_last.html')

def make_race_filename(name):
    return os.path.join(os.path.dirname(__file__), f'runsignup_golden/{name}.html')

def make_result_filename(name):
    return os.path.join(os.path.dirname(__file__), f'runsignup_golden/{name}_results.html')

class RunsignupTestCase(TestCase):
    def setUp(self):
        self.input_file = open(RACES_INPUT, 'r', encoding='utf-8')
        self.input_html = self.input_file.read()

    def tearDown(self):
        self.input_file.close()

    def test_parse_row_no_tags(self):
        soup = BeautifulSoup(self.input_html, 'html.parser')
        row = soup.find('tbody').tr
        expected = RunsignupRace('/Race/KY/Louisville/WILDWORKOUTS',
                                 'WILD WORKOUTS',
                                 datetime.fromisoformat('2024-07-01'),
                                 'Louisville, KY US',
                                 '40213',
                                 [],
                                 [])
        actual = runsignup.parse_row(row)
        self.assertEqual(actual, expected, msg = pprint.pformat((actual, expected)))

    def test_parse_row_tags(self):
        soup = BeautifulSoup(self.input_html, 'html.parser')
        rows = list(soup.find('tbody').children)
        row = rows[3]
        expected = RunsignupRace('/Race/OH/Belpre/GemmasLymeDiseaseandObesityAwarenessVirtual5kFunRunfortheCure',
                                 'Gemma\'s Lyme Disease and Obesity Awareness Virtual 5k Fun Run for the Cure',
                                 datetime.fromisoformat('2024-07-01'),
                                 'Belpre, OH US',
                                 '45714',
                                 ['5K', 'Virtual Event'],
                                 [])
        actual = runsignup.parse_row(row)
        self.assertEqual(actual, expected, msg = pprint.pformat((actual, expected)))

    def test_parse_all(self):
        # print(runsignup.parse_html(self.input_html))
        expected = [
            RunsignupRace(url='/Race/KY/Louisville/WILDWORKOUTS',
                          name='WILD WORKOUTS',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Louisville, KY US',
                          zip='40213',
                          tags=[],
                          resultsets=[]),
            RunsignupRace(url='/Race/OH/Belpre/GemmasLymeDiseaseandObesityAwarenessVirtual5kFunRunfortheCure',
                          name="Gemma's Lyme Disease and Obesity Awareness Virtual 5k Fun Run for the Cure",
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Belpre, OH US',
                          zip='45714',
                          tags=['5K', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NJ/LongBranch/LakeTakanasseeSummerSeries',
                          name='Lake Takanassee Summer Series',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Long Branch, NJ US',
                          zip='07740',
                          tags=['3.1 Miles', '2 Miles', '1500m', '1 Mile'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NY/Geneseo/GeneseoXCRacestoLetchworth',
                          name='Geneseo XC Races to Letchworth!',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Geneseo, NY US',
                          zip='14454',
                          tags=['260 Miles', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/MI/Brighton/TeamRunningLabHalfFullMarathonTrainingGroup',
                          name='Team Running Lab Half / Full Marathon Training Group',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Brighton, MI US',
                          zip='48116',
                          tags=['13.1 Miles', '26.2 Miles'],
                          resultsets=[]),
            RunsignupRace(url='/Race/MD/Baltimore/Grit',
                          name='GRIT',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Baltimore, MD US',
                          zip='21224',
                          tags=['Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/TN/Gatlinburg/Reachout5k',
                          name='REACH OUT 5K RUN',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Gatlinburg, TN US',
                          zip='37738', tags=['5K', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/TX/OakRidgeTNtoAmarillo/TourdeLiveWise',
                          name='Tour de LiveWise',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Oak Ridge, TN to Amarillo, TX US',
                          zip='37830',
                          tags=['Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/MA/Boxboro/HouseRabbitNetworkRace',
                          name='House Rabbit Network 5K & Family "Bunny Hop" Fun Run _______________________________ After-Party at Craft Food Halls',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Boxboro, MA US',
                          zip='01719',
                          tags=['5K', '1K', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NY/Buffalo/CheeseletesInPersonVirtual5k',
                          name='2024 Cheeseletes Virtual 5k',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Buffalo, NY US',
                          zip='14202',
                          tags=['5K', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/FL/AtlanticBeach/DONNADIYFundraiser',
                          name='DONNA DIY Fundraiser',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Atlantic Beach, FL US',
                          zip='32233',
                          tags=[],
                          resultsets=[]),
            RunsignupRace(url='/Race/FL/AnyTownVIRTUAL/SharkBaitSummerRunningWalkingChallenge',
                          name='Shark Bait Summer Running/Walking Challenge',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Any Town-VIRTUAL, FL US',
                          zip='33543',
                          tags=['150 Miles', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/VA/VirginiaBeach/CDSEFESVBChallenge',
                          name='CDSE Miles Challenge!',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Virginia Beach, VA US',
                          zip='23462',
                          tags=['Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/FL/AnyCityAnyState/TourDeTampa',
                          name='Le Tour de Tampa',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Any City - Any State, FL US',
                          zip='99999',
                          tags=['Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NY/Brooklyn/BMTPROJECT40',
                          name='BMT STEPS 2 GREATNESS CHALLENGE SUMMER 2024',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Brooklyn, NY US',
                          zip='11201',
                          tags=['200 Miles', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NC/ChapelHill/ACPAAwarenessMonthRaceChallenge',
                          name='ACPA Awareness Month 60 Mile Challenge',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Chapel Hill, NC US',
                          zip='27517',
                          tags=['60 Miles', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NC/ChapelHill/RoadlessRacesVirtualChallenge',
                          name='Roadless Races Virtual Challenge',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Chapel Hill, NC US',
                          zip='27516',
                          tags=['31 Miles', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NJ/Boonton/MorrisCountyStridersSummerSeries',
                          name='Morris County Striders Summer Series',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Boonton, NJ US',
                          zip='07005',
                          tags=['5K'],
                          resultsets=[]),
            RunsignupRace(url='https://www.ticketsignup.io/TicketEvent/2024FallLineTrailblazerCampaign',
                          name='2024 Fall Line Trailblazer Campaign',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Richmond Region, VA US',
                          zip='23230',
                          tags=[],
                          resultsets=[]),
            RunsignupRace(url='/Race/MA/VineyardHaven/VineyardHavenLibrary5kRunWalktotheChop',
                          name='27th Annual Vineyard Haven Library 5k Run/Walk to the Chop (2024 Hybrid Event)',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Vineyard Haven, MA US',
                          zip='02568',
                          tags=['5K', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='https://www.ticketsignup.io/TicketEvent/PCNSummerFunPhotoContest',
                          name='Summer Fun Photo Contest',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Camp Hill, PA US',
                          zip='17011',
                          tags=[],
                          resultsets=[]),
            RunsignupRace(url='/Race/VA/Roanoke/innerathlete',
                          name='Inner Athlete Virtual Strength and Conditioning Program',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Roanoke, VA US',
                          zip='24018',
                          tags=['Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/MA/RunAnywhere/5kfortheKidsbenefitingBCH',
                          name="Virtual 5k for the Kids: benefiting Boston Children's Hospital",
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Run Anywhere, MA US',
                          zip='00000',
                          tags=['5K', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/NY/Anywhere/5KJusticeRun',
                          name='5k Justice Run',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='Anywhere, NY US',
                          zip='00000',
                          tags=['5K', 'Virtual Event'],
                          resultsets=[]),
            RunsignupRace(url='/Race/FL/ANYTOWNORCITYVIRTUAL/RunLikeAPantherVirtual5k10k',
                          name='Run Like A Panther Virtual 5k/10k',
                          date=datetime(2024, 7, 1, 0, 0),
                          place='ANY TOWN OR CITY VIRTUAL, FL US',
                          zip='33543',
                          tags=['5K', 'Virtual Event'],
                          resultsets=[])
        ]
        self.assertListEqual(runsignup.parse_html(self.input_html)[0], expected)

    def test_next_page(self):
        soup = BeautifulSoup(self.input_html, 'html.parser')
        self.assertEqual(runsignup.get_next_page(soup), '/Races?page=2')

        with open(RACES_INPUT_LAST, 'r', encoding='utf-8') as last_file:
            last_html = last_file.read()
            soup = BeautifulSoup(last_html, 'html.parser')
            self.assertEqual(runsignup.get_next_page(soup), None)

    def test_result_url(self):
        for name, expected in [('fl-westpalmbeach-yls5k', {(59285, None, '/Race/Results/59285')}),
                               ('ky-louisville-wildworkouts', set()),
                               ('pa-virtualrace-phoenixjuly2024', {(167821, None, '/Race/Results/167821')}),
                               ('md-baltimore-grit', {(90618, None, '/Race/Results/90618')}),
                               ('ma-runanywhere-5kfortheKids', {(165887, None, '/Race/Results/Simple/165887')}),
                               ('ca-oxnard-riverpark5k', {(164483, None, '/Race/Results/164483/')}),
                               ('ca-newportbeach-coveathlonsummerrace', {(163521, 471960, '/Race/Results/163521#resultSetId-471960;perpage:100'),
                                                                         (168038, 473252, '/Race/Results/168038#resultSetId-473252;perpage:100')})]:
            with open(make_race_filename(name), 'r', encoding='utf-8') as file:
                html = file.read()
                self.assertEqual(runsignup.get_series_id(html), expected)

    def test_race_ids(self):
        for name, expected in [('fl-westpalmbeach-yls5k',
                                {(420851, '/Race/Results/59285/?resultSetId=420851'),
                                 (338846, '/Race/Results/59285/?resultSetId=338846'),
                                 (337568, '/Race/Results/59285/?resultSetId=337568'),
                                 (213991, '/Race/Results/59285/?resultSetId=213991'),
                                 (213992, '/Race/Results/59285/?resultSetId=213992'),
                                 (148057, '/Race/Results/59285/?resultSetId=148057'),
                                 (110357, '/Race/Results/59285/?resultSetId=110357'),
                                 (112000, '/Race/Results/59285/?resultSetId=112000')}),
                               ('pa-virtualrace-phoenixjuly2024',
                                {(472773, '/Race/Results/167821/?resultSetId=472773'),
                                 (472774, '/Race/Results/167821/?resultSetId=472774'),
                                 (472775, '/Race/Results/167821/?resultSetId=472775'),
                                 (472776, '/Race/Results/167821/?resultSetId=472776')}),
                               ('md-baltimore-grit',
                                {(459290, '/Race/Results/90618/?resultSetId=459290'),
                                 (459362, '/Race/Results/90618/?resultSetId=459362'),
                                 (459365, '/Race/Results/90618/?resultSetId=459365'),
                                 (420578, '/Race/Results/90618/?resultSetId=420578'),
                                 (424095, '/Race/Results/90618/?resultSetId=424095'),
                                 (381192, '/Race/Results/90618/?resultSetId=381192'),
                                 (355409, '/Race/Results/90618/?resultSetId=355409'),
                                 (358569, '/Race/Results/90618/?resultSetId=358569'),
                                 (314702, '/Race/Results/90618/?resultSetId=314702'),
                                 (287129, '/Race/Results/90618/?resultSetId=287129'),
                                 (287131, '/Race/Results/90618/?resultSetId=287131'),
                                 (254359, '/Race/Results/90618/?resultSetId=254359'),
                                 (260751, '/Race/Results/90618/?resultSetId=260751'),
                                 (197012, '/Race/Results/90618/?resultSetId=197012'),
                                 (197013, '/Race/Results/90618/?resultSetId=197013'),
                                 (197014, '/Race/Results/90618/?resultSetId=197014'),
                                 (197015, '/Race/Results/90618/?resultSetId=197015'),
                                 (205590, '/Race/Results/90618/?resultSetId=205590')})]:
            with open(make_result_filename(name), 'r', encoding='utf-8') as file:
                html = file.read()
                self.assertEqual(runsignup.get_resultset_ids(html), expected)
