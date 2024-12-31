import doctest
from . import dj_sql_tools
from . import dj_meta

# https://stackoverflow.com/questions/2380527/django-doctests-in-views-py, answer by Andre Miras
def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(dj_sql_tools))
    tests.addTests(doctest.DocTestSuite(dj_meta))
    return tests
