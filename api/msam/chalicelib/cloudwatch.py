# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
This file contains helper functions related to CloudWatch alarms.
"""

import datetime
import json
import os
import time
from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from botocore.config import Config
from jsonpath_ng import parse

# table names generated by CloudFormation
ALARMS_TABLE_NAME = os.environ["ALARMS_TABLE_NAME"]
EVENTS_TABLE_NAME = os.environ["EVENTS_TABLE_NAME"]
CLOUDWATCH_EVENTS_TABLE_NAME = os.environ["CLOUDWATCH_EVENTS_TABLE_NAME"]

# user-agent config
STAMP = os.environ["BUILD_STAMP"]
MSAM_BOTO3_CONFIG = Config(user_agent="aws-media-services-applications-mapper/{stamp}/cloudwatch.py".format(stamp=STAMP))


def update_alarm_records(region_name, alarm, subscriber_arns):
    """
    Update a single alarm's status in the table.
    """
    try:
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        region_alarm_name = "{}:{}".format(region_name, alarm["AlarmName"])
        if 'Namespace' in alarm:
            namespace = alarm['Namespace']
        else:
            namespace = "n/a"
        updated = int(time.time())
        for resource_arn in subscriber_arns:
            item = {
                "RegionAlarmName": region_alarm_name,
                "ResourceArn": resource_arn,
                "StateValue": alarm['StateValue'],
                "Namespace": namespace,
                "StateUpdated": int(alarm['StateUpdatedTimestamp'].timestamp()),
                "Updated": updated
            }
            ddb_table.put_item(Item=item)
    except ClientError as error:
        print(error)


def update_alarm_subscriber(region_name, alarm_name, subscriber_arn):
    """
    Update a single subscriber's alarm status in the alarms table.
    """
    try:
        print(f"update subscriber {subscriber_arn} alarm {alarm_name} in region {region_name}")
        cloudwatch = boto3.client('cloudwatch', region_name=region_name, config=MSAM_BOTO3_CONFIG)
        response = cloudwatch.describe_alarms(AlarmNames=[alarm_name])
        alarms = response['CompositeAlarms'] + response['MetricAlarms']
        for alarm in alarms:
            update_alarm_records(region_name, alarm, [subscriber_arn])
    except ClientError as error:
        print(error)


def update_alarms(region_name, alarm_names):
    """
    Update a list of alarms' status in the alarms table for a given region.
    """
    try:
        print(f"update alarms {alarm_names} in region {region_name}")
        cloudwatch = boto3.client('cloudwatch', region_name=region_name, config=MSAM_BOTO3_CONFIG)
        response = cloudwatch.describe_alarms(AlarmNames=alarm_names)
        alarms = response['CompositeAlarms'] + response['MetricAlarms']
        for alarm in alarms:
            print(f"alarm {alarm['AlarmName']}")
            subscribers = subscribers_to_alarm(alarm["AlarmName"], region_name)
            print(f"subscribers {subscribers}")
            update_alarm_records(region_name, alarm, subscribers)
        while "NextToken" in response:
            response = cloudwatch.describe_alarms(AlarmNames=alarm_names, NextToken=response["NextToken"])
            alarms = response['CompositeAlarms'] + response['MetricAlarms']
            for alarm in alarms:
                print(f"alarm {alarm['AlarmName']}")
                subscribers = subscribers_to_alarm(alarm["AlarmName"], region_name)
                print(f"subscribers {subscribers}")
                update_alarm_records(region_name, alarm, subscribers)
    except ClientError as error:
        print(error)


def alarms_for_subscriber(resource_arn):
    """
    API entry point to return all alarms subscribed to by a node.
    """
    # split_items = []
    scanned_items = []
    try:
        resource_arn = unquote(resource_arn)
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        ddb_index_name = 'ResourceArnIndex'
        response = ddb_table.query(IndexName=ddb_index_name, KeyConditionExpression=Key('ResourceArn').eq(resource_arn))
        if "Items" in response:
            scanned_items = response["Items"]
        while "LastEvaluatedKey" in response:
            response = ddb_table.query(IndexName=ddb_index_name, KeyConditionExpression=Key('ResourceArn').eq(resource_arn), ExclusiveStartKey=response['LastEvaluatedKey'])
            if "Items" in response:
                scanned_items = scanned_items + response["Items"]
        print(scanned_items)
        for item in scanned_items:
            split_attr = item["RegionAlarmName"].split(':', maxsplit=1)
            region = split_attr[0]
            name = split_attr[1]
            item["Region"] = region
            item["AlarmName"] = name
            # alarm = {"Region": region, "AlarmName": name}
            # split_items.append(alarm)
    except ClientError as error:
        print(error)
    # return [dict(t) for t in {tuple(d.items()) for d in split_items}]
    return scanned_items


def all_subscribed_alarms():
    """
    API entry point to return a unique list of all subscribed alarms in the database.
    """
    split_items = []
    try:
        scanned_items = []
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        response = ddb_table.scan(ProjectionExpression="RegionAlarmName")
        if "Items" in response:
            scanned_items = response["Items"]
        while "LastEvaluatedKey" in response:
            response = ddb_table.scan(ProjectionExpression="RegionAlarmName", ExclusiveStartKey=response['LastEvaluatedKey'])
            if "Items" in response:
                scanned_items = scanned_items + response["Items"]
        for item in scanned_items:
            split_attr = item["RegionAlarmName"].split(':', maxsplit=1)
            region = split_attr[0]
            name = split_attr[1]
            alarm = {"Region": region, "AlarmName": name}
            split_items.append(alarm)
    except ClientError as error:
        print(error)
    return [dict(t) for t in {tuple(d.items()) for d in split_items}]


def filtered_alarm(alarm):
    """
    Restructure a CloudWatch alarm into a simpler form.
    """
    arn = [match.value for match in parse('$..AlarmArn').find(alarm)]
    name = [match.value for match in parse('$..AlarmName').find(alarm)]
    metric = [match.value for match in parse('$..MetricName').find(alarm)]
    namespace = [match.value for match in parse('$..Namespace').find(alarm)]
    state = [match.value for match in parse('$..StateValue').find(alarm)]
    updated = [match.value for match in parse('$..StateUpdatedTimestamp').find(alarm)]
    filtered = {
        "AlarmArn": arn[0] if arn else None,
        "AlarmName": name[0] if name else None,
        "MetricName": metric[0] if metric else None,
        "Namespace": namespace[0] if namespace else None,
        "StateValue": state[0] if state else None,
        "StateUpdated": int(updated[0].timestamp()) if updated else None
    }
    print(filtered)
    return filtered


def get_cloudwatch_alarms_region(region):
    """
    API entry point to retrieve all CloudWatch alarms for a given region.
    """
    alarms = []
    try:
        region = unquote(region)
        client = boto3.client('cloudwatch', region_name=region, config=MSAM_BOTO3_CONFIG)
        response = client.describe_alarms()
        # return the response or an empty object
        if "MetricAlarms" in response:
            for alarm in response["MetricAlarms"]:
                # print(json.dumps(alarm, default=str))
                alarms.append(filtered_alarm(alarm))
        while "NextToken" in response:
            response = client.describe_alarms(NextToken=response["NextToken"])
            # return the response or an empty object
            if "MetricAlarms" in response:
                for alarm in response["MetricAlarms"]:
                    # print(json.dumps(alarm, default=str))
                    alarms.append(filtered_alarm(alarm))
    except ClientError as error:
        print(error)
    return alarms


def get_cloudwatch_events_state(state):
    """
    API entry point to retrieve all pipeline events in a given state (set, clear).
    """
    events = []
    dynamodb = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
    table = dynamodb.Table(EVENTS_TABLE_NAME)
    response = table.query(IndexName='AlarmStateIndex', KeyConditionExpression=Key('alarm_state').eq(state))
    if "Items" in response:
        events = response["Items"]
    return events


def group_events(events):
    group = {}
    group["down"] = []
    group["running"] = []
    group["degraded"] = []
    def ensure_details(evt):
        if "detail" not in evt:
            if "data" in evt:
                evt["detail"] = json.loads(evt["data"])
            else:
                evt["detail"] = {}
        if "pipeline" not in evt["detail"]:
            evt["detail"]["pipeline"] = str(0)
        return evt
    for eventdata in events:
        event = ensure_details(eventdata)
        arn = event["resource_arn"]
        pl = event["detail"]["pipeline"]
        def is_same_arn(d):
            i = ensure_details(d)
            return bool(i["resource_arn"] == arn)
        def is_same_pl(d):
            i = ensure_details(d)
            return bool("pipeline" in i["detail"] and i["detail"]["pipeline"] == pl)
        def is_diff_pl(d):
            i = ensure_details(d)
            return bool("pipeline" in i["detail"] and i["detail"]["pipeline"] != pl)
        def is_pl_down(d):
            i = ensure_details(d)
            return bool("pipeline_state" in i["detail"] and not i["detail"]["pipeline_state"])
        same_arn_events = list(filter(is_same_arn, events))
        all_down_pipelines = list(filter(is_pl_down, same_arn_events))
        same_down_pipelines = list(filter(is_same_pl, all_down_pipelines))
        diff_down_pipelines = list(filter(is_diff_pl, all_down_pipelines))
        if len(diff_down_pipelines) > 0 and len(same_down_pipelines) == 0:
            event["detail"]["running"] = bool(False)
            event["detail"]["degraded"] = bool(True)
            group["degraded"].append(event)
        elif len(diff_down_pipelines) == 0 and len(same_down_pipelines) > 0:
            event["detail"]["running"] = bool(False)
            event["detail"]["degraded"] = bool(True)
            group["degraded"].append(event)
        elif len(diff_down_pipelines) > 0 and len(same_down_pipelines) > 0:
            event["detail"]["running"] = bool(False)
            event["detail"]["degraded"] = bool(False)
            group["down"].append(event)
        else:
            event["detail"]["running"] = bool(True)
            event["detail"]["degraded"] = bool(False)
            group["running"].append(event)
    return group


def get_cloudwatch_events_state_groups(state):
    """
    Group all events by down, degraded and running pipelines
    """
    events = get_cloudwatch_events_state(state)
    return group_events(events)


def get_cloudwatch_events_resource(resource_arn, start_time=0, end_time=0):
    """
    API entry point to retrieve all CloudWatch events related to a given resource.
    """
    cw_events = []
    try:
        resource_arn = unquote(resource_arn)
        dynamodb = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        table = dynamodb.Table(CLOUDWATCH_EVENTS_TABLE_NAME)
        key = None
        if (start_time > 0 and end_time > 0):
            key = Key('resource_arn').eq(resource_arn) & Key('timestamp').between(start_time, end_time)
        elif(start_time > 0 and end_time == 0):
            key = Key('resource_arn').eq(resource_arn) & Key('timestamp').gte(start_time)
        else:
            key = Key('resource_arn').eq(resource_arn)
        response = table.query(KeyConditionExpression=key)
        if "Items" in response:
            cw_events = response["Items"]
        while "LastEvaluatedKey" in response:
            response = table.query(KeyConditionExpression=key, ExclusiveStartKey=response['LastEvaluatedKey'])
            if "Items" in response:
                cw_events = cw_events + response["Items"]
    except ClientError as error:
        print(error)
    return cw_events


def incoming_cloudwatch_alarm(event, _):
    """
    Standard AWS Lambda entry point for receiving CloudWatch alarm notifications.
    """
    print(event)
    try:
        updated_timestamp = int(time.time())
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        for record in event["Records"]:
            region = (record["Sns"]["TopicArn"]).split(":")[3]
            alarm = json.loads(record["Sns"]["Message"])
            alarm_name = [match.value for match in parse('$..AlarmName').find(alarm)]
            # look up the resources with this region alarm name
            metric = [match.value for match in parse('$..MetricName').find(alarm)]
            namespace = [match.value for match in parse('$..Namespace').find(alarm)]
            state = [match.value for match in parse('$..NewStateValue').find(alarm)]
            updated = [match.value for match in parse('$..StateChangeTime').find(alarm)]
            region_alarm_name = "{}:{}".format(region, alarm_name[0] if alarm_name else None)
            subscribers = subscribers_to_alarm(alarm_name[0] if alarm_name else None, region)
            for resource_arn in subscribers:
                item = {
                    "RegionAlarmName": region_alarm_name,
                    "ResourceArn": resource_arn,
                    "Namespace": namespace[0] if namespace else None,
                    "StateUpdated": int(datetime.datetime.strptime(updated[0], '%Y-%m-%dT%H:%M:%S.%f%z').timestamp()) if updated else None,
                    "StateValue": state[0] if state else None,
                    "Updated": updated_timestamp
                }
                ddb_table.put_item(Item=item)
                print("{} updated via alarm notification".format(resource_arn))
    except ClientError as error:
        print(error)
    return True


def subscribe_resource_to_alarm(request, alarm_name, region):
    """
    API entry point to subscribe one or more nodes to a CloudWatch alarm in a region.
    """
    try:
        alarm_name = unquote(alarm_name)
        region = unquote(region)
        region_alarm_name = "{}:{}".format(region, alarm_name)
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        resources = request.json_body
        for resource_arn in resources:
            print(resource_arn)
            # store it
            item = {"RegionAlarmName": region_alarm_name, "ResourceArn": resource_arn}
            ddb_table.put_item(Item=item)
            update_alarm_subscriber(region, alarm_name, resource_arn)
        return True
    except ClientError as error:
        print(error)
        return False


def subscribed_with_state(alarm_state):
    """
    API entry point to return nodes subscribed to alarms in a given alarm state (OK, ALARM, INSUFFICIENT_DATA).
    """
    resources = {}
    try:
        alarm_state = unquote(alarm_state)
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        response = ddb_table.query(IndexName='StateValueIndex', KeyConditionExpression=Key('StateValue').eq(alarm_state))
        for item in response["Items"]:
            # store it
            if item["ResourceArn"] in resources:
                entry = resources[item["ResourceArn"]]
                entry["AlarmCount"] = entry["AlarmCount"] + 1
            else:
                entry = {"ResourceArn": item["ResourceArn"], "AlarmCount": 1}
            resources[item["ResourceArn"]] = entry
        while "LastEvaluatedKey" in response:
            response = ddb_table.query(IndexName='StateValueIndex', KeyConditionExpression=Key('StateValue').eq(alarm_state), ExclusiveStartKey=response['LastEvaluatedKey'])
            for item in response["Items"]:
                # store it
                if item["ResourceArn"] in resources:
                    entry = resources[item["ResourceArn"]]
                    entry["AlarmCount"] = entry["AlarmCount"] + 1
                else:
                    entry = {"ResourceArn": item["ResourceArn"], "AlarmCount": 1}
                resources[item["ResourceArn"]] = entry
    except ClientError as error:
        print(error)
    return list(resources.values())


def subscribers_to_alarm(alarm_name, region):
    """
    API entry point to return subscribed nodes of a CloudWatch alarm in a region.
    """
    subscribers = set()
    try:
        alarm_name = unquote(alarm_name)
        region = unquote(region)
        region_alarm_name = "{}:{}".format(region, alarm_name)
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        ddb_index_name = 'RegionAlarmNameIndex'
        response = ddb_table.query(IndexName=ddb_index_name, KeyConditionExpression=Key('RegionAlarmName').eq(region_alarm_name))
        for item in response["Items"]:
            subscribers.add(item["ResourceArn"])
        while "LastEvaluatedKey" in response:
            response = ddb_table.query(IndexName=ddb_index_name, KeyConditionExpression=Key('RegionAlarmName').eq(region_alarm_name), ExclusiveStartKey=response['LastEvaluatedKey'])
            for item in response["Items"]:
                subscribers.add(item["ResourceArn"])
    except ClientError as error:
        print(error)
    return sorted(subscribers)


def unsubscribe_resource_from_alarm(request, alarm_name, region):
    """
    API entry point to subscribe one or more nodes to a CloudWatch alarm in a region.
    """
    try:
        alarm_name = unquote(alarm_name)
        region = unquote(region)
        region_alarm_name = "{}:{}".format(region, alarm_name)
        ddb_table_name = ALARMS_TABLE_NAME
        ddb_resource = boto3.resource('dynamodb', config=MSAM_BOTO3_CONFIG)
        ddb_table = ddb_resource.Table(ddb_table_name)
        resources = request.json_body
        for resource_arn in resources:
            # store it
            item = {"RegionAlarmName": region_alarm_name, "ResourceArn": resource_arn}
            # delete it
            ddb_table.delete_item(Key=item)
        return True
    except ClientError as error:
        print(error)
        return False
