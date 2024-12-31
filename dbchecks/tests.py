import doctest
from . import dbchecks

# https://stackoverflow.com/questions/2380527/django-doctests-in-views-py, answer by Andre Miras

def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(dbchecks))
    return tests
