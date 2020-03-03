from .lambda_function import *
from . import *

def test_lambda_function():
    resp = lambda_handler(cloudwatch_event({}), None)
    assert resp == {'statusCode': 200, 'body': '"Hello Python"'}
