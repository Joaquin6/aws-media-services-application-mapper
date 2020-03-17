# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
This Lambda is responsible for receiving and storing CloudWatch events
originating from Media Services. This Lambda must be installed into
each region where Media Services are created.
"""

import os
import json
import time
import datetime
from random import randint
from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from jsonpath_ng import parse

DYNAMO_REGION_NAME=os.environ["EVENTS_TABLE_REGION"]
DYNAMO_RESOURCE = boto3.resource('dynamodb', region_name=DYNAMO_REGION_NAME)
EVENTS_TABLE = DYNAMO_RESOURCE.Table(os.environ["EVENTS_TABLE_NAME"])
CLOUDWATCH_EVENTS_TABLE = DYNAMO_RESOURCE.Table(os.environ["CLOUDWATCH_EVENTS_TABLE_NAME"])
CONTENT_TABLE_NAME = os.environ["CONTENT_TABLE_NAME"]
ITEM_TTL = int(os.environ["ITEM_TTL"])


def lambda_handler(event, _):
    """
    Entry point for CloudWatch event receipt.
    """
    try:
        item = {}
        print(event)
        item["timestamp"] = int(datetime.datetime.strptime(
            event["time"], '%Y-%m-%dT%H:%M:%SZ').timestamp())
        item["expires"] = item["timestamp"] + ITEM_TTL
        # give timestamp a millisecond precision
        item["timestamp"] = item["timestamp"] * 1000 + randint(1, 999)
        item["data"] = json.dumps(event["detail"])
        item["type"] = event["detail-type"]
        if "eventName" in event["detail"]:
            item["type"] = item["type"] + ": " + event["detail"]["eventName"]

        # catch all the various forms of ARN from the media services
        arn_expr = parse('$..arn|aRN|resource-arn|channel_arn|multiplex_arn|flowArn|PlaybackConfigurationArn|resourceArn')
        original_arns = [match.value for match in arn_expr.find(event)]
        arns = []
        # remove arn that is for userIdentity or inputSecurityGroup
        # note: can't remove an item from a list that's being iterated over so doing it this way instead =P
        for arn in original_arns:
            if "user" in arn or "role" in arn or "inputSecurityGroup" in arn:
                pass
            else:
                arns.append(arn)
        if arns:
            item["resource_arn"] = unquote(arns[0])

        if event["source"] == "aws.medialive":
            # handle medialive pipeline alerts
            if "MediaLive" in event["detail-type"] and "Alert" in event["detail-type"]:
                event["alarm_id"] = event["detail"]["alarm_id"]
                event["alarm_state"] = event["detail"]["alarm_state"].lower()
                event["timestamp"] = int(datetime.datetime.strptime(
                    event["time"], '%Y-%m-%dT%H:%M:%SZ').timestamp())
                event["expires"] = event["timestamp"] + ITEM_TTL
                event["detail"]["time"] = event["time"]
                # multiplex pipeline alerts do not have a "detail.channel_arn" property.
                if "Multiplex" in event["detail-type"]:
                    event["resource_arn"] = event["detail"]["multiplex_arn"]
                else:
                    event["resource_arn"] = event["detail"]["channel_arn"]
                    event["detail"]["idle_state"] = get_idle_state(event)
                event["detail"]["pipeline_state"] = get_pipeline_state(event)
                EVENTS_TABLE.put_item(Item=event)
                if "Multiplex" in event["detail-type"]:
                    print("Multiplex alert stored")
                else:
                    print("MediaLive alert stored")
            if "BatchUpdateSchedule" in item["type"]:
                print("Creating an ARN for BatchUpdateSchedule event.")
                item["resource_arn"] = "arn:aws:medialive:" + event['region'] + ":" + \
                    event['account'] + ":channel:" + \
                    event['detail']['requestParameters']['channelId']
        elif event["source"] == "aws.mediapackage":
            if "HarvestJob" in item["type"]:
                print("Asking MediaPackage for the ARN of endpoint in a HarvestJob event.")
                # to get the ARN, ask mediapackage to describe the origin endpoint
                # the ARN available through resources is the HarvestJob ARN, not the endpoint
                orig_id_expr = parse('$..origin_endpoint_id')
                orig_id = [match.value for match in orig_id_expr.find(event)]
                if orig_id:
                    emp_client = boto3.client('mediapackage')
                    response = emp_client.describe_origin_endpoint(Id=orig_id[0])
                    item["resource_arn"] = response["Arn"]
                else:
                    print("Skipping this event. Origin ID not present in the HarvestJob event." + item["type"])
        # for certain events, the ARN is not labeled as an ARN but instead put in the resources list
        if not arns and event["resources"]:
            if "vod" not in event["resources"][0]:
                item["resource_arn"] = event["resources"][0]
        # if item has no resource arn, don't save in DB
        if "resource_arn" in item:
            print("Storing media service event.")
            print(item)
            CLOUDWATCH_EVENTS_TABLE.put_item(Item=item)
        else:
            print("Skipping this event. " + item["type"])
    except ClientError as error:
        print(error)
    return True


def get_pipeline_state(event):
    """
    Check for pipeline state only if source is aws.medialive
    """
    running_pipeline = bool(True)
    resource_arn = event["resource_arn"]
    try:
        if event["source"] == "aws.medialive" and event["detail"]["alarm_state"] == "SET":
            items = get_content_items(resource_arn)
            item = items[0]
            if "service" in item and item["service"] == "medialive-multiplex":
                running_pipeline = bool(False)
            else:
                data = json.loads(item["data"])
                if "ChannelClass" in data and data["ChannelClass"] == "STANDARD":
                    running_pipeline = bool(False)
    except ClientError as error:
        print(error)
    if "pipeline" in event["detail"]:
        log_msg = 'Pipeline {} state to for {} is {}'
        print(log_msg.format(event["detail"]["pipeline"], resource_arn, running_pipeline))
    return running_pipeline


def get_content_items(resource_arn):
    """
    Fetch content records for the given arn.
    """
    items = []
    try:
        resource = boto3.resource('dynamodb', region_name=DYNAMO_REGION_NAME)
        CONTENT_TABLE = resource.Table(CONTENT_TABLE_NAME)
        response = CONTENT_TABLE.query(KeyConditionExpression=Key('arn').eq(resource_arn))
        if "Items" in response:
            items = response["Items"]
        while "LastEvaluatedKey" in response:
            response = CONTENT_TABLE.query(KeyConditionExpression=Key('arn').eq(resource_arn), ExclusiveStartKey=response['LastEvaluatedKey'])
            items = items + response["Items"]
    except ClientError as error:
        print(error)
    return items


def put_ddb_items(items):
    """
    Add a list of cache items to the content (cache) DynamoDB table.
    """
    # shared resource and table
    ddb_resource = boto3.resource('dynamodb')
    ddb_table = ddb_resource.Table(CONTENT_TABLE_NAME)
    for item in items:
        ddb_table.put_item(Item=item)
    return True


def get_idle_state(event):
    """
    Check for idle state only if source is aws.medialive, for now
    """
    idle_state = bool(False)
    region_name = event["region"]
    channel_arn = event["detail"]["channel_arn"]
    channel_id = channel_arn.split(':').pop()
    try:
        if event["source"] == "aws.medialive":
            service = boto3.client("medialive")
            channel = service.describe_channel(ChannelId=channel_id)
            if 'State' in channel and channel['State'] == 'IDLE':
                idle_state = bool(True)
            channel_contents = []
            items = get_content_items(event["detail"]["channel_arn"])
            for item in items:
                service = "medialive-channel"
                arn = item["arn"]
                if 'data' in item:
                    data = json.loads(item['data'])
                    data['idle_state'] = idle_state
                channel_contents.append(node_to_ddb_item(arn, service, region_name, item))
            put_ddb_items(channel_contents);
    except ClientError as error:
        print(error)
    log_msg = 'Channel ID {} has a {} idle_state'
    print(log_msg.format(channel_id, idle_state))
    return idle_state


def node_to_ddb_item(arn, service, region, config):
    """
    Restructure an item from a List or Describe API call into a cache item.
    """
    now = int(time.time())
    item = {"arn": arn, "region": region, "service": service, "updated": now, "expires": now + ITEM_TTL, "data": json.dumps(config, default=str)}
    return item
