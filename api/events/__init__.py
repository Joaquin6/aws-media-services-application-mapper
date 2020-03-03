import json

def cloudwatch_event(payload: dict) -> dict:
    return {
        'resource': '',
        'path': '',
        'httpMethod': '',
        'headers': {},
        'requestContext': {
            'resourcePath': '',
            'httpMethod': ''
        },
        'body': json.dumps(payload)
    }
